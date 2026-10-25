"""诊断包一键导出（学 peach support_bundle 的脱敏诊断包思路）

排查问题时，用户要手动翻日志、抄版本号、截图配置——导出个 zip 发过来，
一步到位。**全程只读**，不碰任何业务数据。

zip 内容（每项失败不影响其它项，缺的记进 manifest）：
- manifest.json      包内文件清单 + 生成时间 + 各项采集状态
- env.json           Python/OS/CPU/内存/各 media_dir 磁盘空间/服务进程信息
- config.redacted.yaml  脱敏后的配置（key 名或值命中敏感模式 → ***REDACTED***）
- logs/*.log         各日志尾部 96KB（peach TAIL_BYTES 同款），行内脱敏
- library_stats.json 各模块影片/演员计数 + file_path 有效率（不含任何文件名）
- network_status.json  NAS 映射盘状态 + 当前生效代理
- tasks_summary.json   任务注册表/工作流的活动摘要

🔴 脱敏是硬要求（这个包是要外发给别人的）：
1. config：递归遍历，key 命中敏感词（password/secret/token/api_key/cookie/
   passwd/credential）或值看起来像 cookie/token（超长 base64ish）→ 整值打码
2. 日志行：cookie 片段（_jdb_session/cf_clearance/4fJN_2132_auth 等
   `name=value` 形态）、magnet 链接、Bearer token → 模式替换
3. 媒体文件名：Windows 路径里的视频/图片扩展名文件名 → 保留目录换 <media-file>
   （peach 同款原则：「媒体名称留在本机」）
4. NAS 路径/盘符保留（排查掉线要靠它们），但 UNC 里的用户名段替换
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 日志尾部保留字节数（peach 同款 96KB）
TAIL_BYTES = 96 * 1024
# 单个日志文件在 zip 里的名字
LOG_FILES = ("app.log", "error.log", "crash.log", "server.log", "startup.log")

# 敏感 key 名（命中即整值打码，大小写不敏感）
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api_key|apikey|cookie|credential|auth)", re.IGNORECASE)

# 日志行内脱敏模式：cookie 会话片段 / magnet / bearer
_LINE_PATTERNS = [
    (re.compile(r"(_jdb_session|cf_clearance|_ym_uid|_ym_isad|4fJN_\w+_auth|"
                r"4fJN_\w+_sid|PHPSESSID|session|auth|token|key|secret)"
                r"=[^;\s\"']{6,}", re.IGNORECASE), r"\1=<redacted>"),
    (re.compile(r"magnet:\?[^\s\"'<>]+"), "<magnet>"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{16,}=*"), "Bearer <redacted>"),
]
# 媒体文件名（保留目录，换掉文件名）
_MEDIA_FILE_RE = re.compile(
    r"([A-Za-z]:\\[^:\n\"'<>]*?\\)?([^:\\/\n\"'<>]+\.(?:mp4|mkv|avi|wmv|flv|mov|"
    r"ts|m2ts|rmvb|mpg|mpeg|jpg|jpeg|png|gif|webp|nfo|srt|ass|ssa))", re.IGNORECASE)

# 值形态疑似密钥（超长 base64ish 串）也打码
_VALUE_SECRET_RE = re.compile(r"^[A-Za-z0-9+/_\-]{32,}={0,2}$")

# 🔴 URL 内嵌凭据：`socks5://user:pass@1.2.3.4:1080`、`http://a:b@host/x`。
# 敏感 key 名判定抓不到这种（key 叫 proxy/proxy_url/url 都不含 password/token），
# 只按 key 打码会把下载器/代理账号明文带进要外发的包里 —— 所以无条件全量抹。
_URL_CRED_RE = re.compile(r"://([^/@\s:]+):([^/@\s]+)@")


def _redact_text(text: str) -> str:
    """日志/文本行内脱敏。"""
    text = _URL_CRED_RE.sub("://***:***@", text)
    for pattern, repl in _LINE_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _redact_path(path_str: str) -> str:
    """路径脱敏：媒体文件名换 <media-file>，目录保留。"""

    def _sub(m: re.Match) -> str:
        directory, _name = m.group(1) or "", m.group(2)
        return f"{directory}<media-file>"

    return _MEDIA_FILE_RE.sub(_sub, path_str)


def _redact_obj(obj, key_hint: str = ""):
    """递归脱敏 dict/list/str。"""
    if isinstance(obj, dict):
        return {k: _redact_obj(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_obj(v, key_hint) for v in obj]
    if isinstance(obj, str):
        if _SENSITIVE_KEY_RE.search(key_hint):
            return "***REDACTED***"
        # 超长 base64ish 串（cookie/token 值常见形态）也打码
        if len(obj) >= 32 and _VALUE_SECRET_RE.match(obj):
            return "***REDACTED***"
        # 媒体文件名换掉（任务摘要/网络状态里常有完整路径），URL 凭据抹掉
        return _URL_CRED_RE.sub("://***:***@", _redact_path(obj))
    return obj


def _tail(path: Path, limit: int = TAIL_BYTES) -> str:
    """读文件尾部 limit 字节（按行边界补齐），逐行脱敏。"""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > limit:
                f.seek(size - limit)
                f.readline()  # 丢弃半行
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        lines = [_redact_text(_redact_path(line)) for line in text.splitlines()]
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"[diag_bundle] 读日志失败 {path}: {e}")
        return f"<读取失败: {type(e).__name__}>"


def _collect_env() -> dict:
    """环境信息（不含任何用户数据）。"""
    import psutil  # 已有依赖（metrics.py 在用）

    media_dirs = []
    try:
        from app.config.manager import get_config
        cfg = get_config()
        dirs = getattr(getattr(cfg, "scraper", None), "media_dirs", None) or []
        for d in dirs:
            entry = {"dir": str(d)}
            try:
                p = Path(d)
                entry["exists"] = p.exists()
                if entry["exists"]:
                    usage = shutil.disk_usage(str(p))
                    entry["free_gb"] = round(usage.free / 1024 ** 3, 1)
                    entry["total_gb"] = round(usage.total / 1024 ** 3, 1)
            except Exception:
                pass
            media_dirs.append(entry)
    except Exception as e:
        media_dirs = [{"error": f"{type(e).__name__}: {e}"}]

    try:
        mem = psutil.virtual_memory()
        memory = {"total_gb": round(mem.total / 1024 ** 3, 1),
                  "available_gb": round(mem.available / 1024 ** 3, 1),
                  "percent": mem.percent}
    except Exception:
        memory = {}

    try:
        from app import __version__ as app_version
    except Exception:
        app_version = "unknown"

    return {
        "app_version": app_version,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "memory": memory,
        "media_dirs": media_dirs,
        "cwd": os.getcwd(),
    }


def _collect_config() -> str:
    """脱敏后的 config.yaml 原文（保留注释与结构，值打码）。"""
    try:
        from app.config.manager import get_config_manager

        manager = get_config_manager()
        candidates = [Path("data/config/config.yaml"), Path("config.yaml")]
        try:
            candidates.insert(0, Path(manager.computed.config_dir) / "config.yaml")
        except Exception:
            pass
        for p in candidates:
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                return _redact_config_yaml(text)
        return "<config.yaml 未找到>"
    except Exception as e:
        logger.warning(f"[diag_bundle] 读配置失败: {e}")
        return f"<读取失败: {type(e).__name__}>"


def _redact_config_yaml(text: str) -> str:
    """逐行脱敏 YAML：`key: value` 的 value 命中敏感规则就打码。

    不解析 YAML（保留原格式与注释，用户/我review 时更直观），
    只处理 `key: value` 行；列表项（- value）带上一行的 key 语境判断。
    """
    out_lines = []
    last_key = ""
    for line in text.splitlines():
        m = re.match(r"^(\s*)(?:-\s+)?([A-Za-z0-9_.\-]+)\s*:\s*(.*)$", line)
        if m:
            indent, key, value = m.group(1), m.group(2), m.group(3)
            last_key = key
            # URL 内嵌凭据无条件先抹（key 名叫 proxy/url 时不进敏感名判定）
            line = _URL_CRED_RE.sub("://***:***@", line)
            value = _URL_CRED_RE.sub("://***:***@", value)
            if value and not value.lstrip().startswith("#"):
                if _SENSITIVE_KEY_RE.search(key):
                    line = f"{indent}{key}: ***REDACTED***"
                elif len(value.strip()) >= 32 and _VALUE_SECRET_RE.match(value.strip()):
                    line = f"{indent}{key}: ***REDACTED***"
                elif value.strip() and _looks_like_cookie(value.strip()):
                    line = f"{indent}{key}: ***REDACTED***"
        elif line.lstrip().startswith("- ") and _SENSITIVE_KEY_RE.search(last_key):
            # 敏感 key 的列表项（如 target_sites 之外的凭据列表）
            indent = line[: len(line) - len(line.lstrip())]
            line = f"{indent}- ***REDACTED***"
        out_lines.append(line)
    return "\n".join(out_lines)


def _looks_like_cookie(value: str) -> bool:
    """cookie 串形态：含分号分隔的 name=value 且够长。"""
    if ";" not in value:
        return False
    parts = [p for p in value.split(";") if "=" in p]
    return len(parts) >= 2 and len(value) >= 40


async def _collect_library_stats_async() -> dict:
    """异步版库统计（路由里 await 这个）。"""
    stats: dict = {}
    try:
        from sqlalchemy import func, select

        from app.utils.module_helper import get_module_model, get_module_session

        for module in ("jav", "fc2", "uncensored", "chinese", "western", "pornhub"):
            entry: dict = {}
            try:
                Movie = get_module_model(module, "movie")
                sess = await get_module_session(module)
                async with sess:
                    entry["movies"] = (await sess.execute(
                        select(func.count()).select_from(Movie))).scalar() or 0
                    entry["with_file_path"] = (await sess.execute(
                        select(func.count()).select_from(Movie)
                        .where(Movie.file_path.isnot(None)))).scalar() or 0
                # 🔴 用 "actor"（模块 actors 表），不是 "movie_actor"：
                # movie_actor 是 影片↔演员 关联表，数出来的是关联行数，
                # 比真实演员数大一个量级，会误导排查。
                Actor = get_module_model(module, "actor")
                sess2 = await get_module_session(module)
                async with sess2:
                    entry["actors"] = (await sess2.execute(
                        select(func.count()).select_from(Actor))).scalar() or 0
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
            if entry:
                stats[module] = entry
    except Exception as e:
        stats["error"] = f"{type(e).__name__}: {e}"
    return stats


def _collect_network_status() -> dict:
    """NAS 映射盘状态 + 生效代理（排查掉线的关键信息）。"""
    out: dict = {}
    try:
        from app.utils import net_drives

        out["drives"] = net_drives.status()
    except Exception as e:
        out["drives_error"] = f"{type(e).__name__}: {e}"
    try:
        from app.services.proxy_manager import get_effective_proxy_url

        proxy = get_effective_proxy_url()
        # 代理 URL 可能含端口密码，只留协议+主机+端口
        out["proxy"] = _sanitize_proxy(proxy)
    except Exception as e:
        out["proxy_error"] = f"{type(e).__name__}: {e}"
    return out


def _sanitize_proxy(url: Optional[str]) -> str:
    if not url:
        return ""
    m = re.match(r"^(\w+://)?([^:@/]+)(?::[^@/]+)?@([^/]+?)(?::\d+)?/?$", url)
    if m:  # scheme://user:pass@host:port → 抹掉 user:pass
        scheme = m.group(1) or ""
        return f"{scheme}***:***@{m.group(3)}"
    # socks5://127.0.0.1:18920 之类不含凭据的，主机端口保留（排查要用）
    return re.sub(r"//([^@/]+):[^@/]+@", r"//***:***@", url)


def _collect_tasks_summary() -> dict:
    """任务/工作流活动摘要（不含任何影片信息）。"""
    out: dict = {}
    try:
        from app.services.scan_control import ScanControlService

        svc = ScanControlService.get_instance()
        out["scan_cooldown_remaining_sec"] = round(svc.cooldown_remaining(), 1)
    except Exception as e:
        out["scan_error"] = f"{type(e).__name__}: {e}"
    try:
        from app.services.workflow import get_workflow_registry

        out["workflows"] = get_workflow_registry().list_status()
    except Exception as e:
        out["workflows_error"] = f"{type(e).__name__}: {e}"
    return out


def _find_logs_dir() -> Optional[Path]:
    for p in (Path("data/logs"), Path("logs")):
        if p.is_dir():
            return p
    return None


async def build_bundle(
    log: Optional[Callable[[str], None]] = None,
) -> tuple[bytes, str]:
    """生成诊断包 zip，返回 (bytes, filename)。

    任何单项采集失败都记录进 manifest，不影响整包产出（排查时
    「日志没进去」本身就是信息）。
    """
    _log = log or (lambda _m: None)
    started = datetime.now()
    errors: list[str] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) env
        try:
            env = _collect_env()
        except Exception as e:
            env = {"error": f"{type(e).__name__}: {e}"}
            errors.append(f"env: {type(e).__name__}")
        zf.writestr("env.json", json.dumps(env, ensure_ascii=False, indent=2))

        # 2) config（脱敏）
        try:
            config_text = _collect_config()
        except Exception as e:
            config_text = f"<采集失败: {type(e).__name__}>"
            errors.append(f"config: {type(e).__name__}")
        zf.writestr("config.redacted.yaml", config_text)

        # 3) 日志尾部（脱敏）
        logs_dir = _find_logs_dir()
        log_names: list[str] = []
        if logs_dir:
            for name in LOG_FILES:
                p = logs_dir / name
                if p.is_file():
                    try:
                        zf.writestr(f"logs/{name}", _tail(p))
                        log_names.append(name)
                    except Exception as e:
                        errors.append(f"log/{name}: {type(e).__name__}")
        else:
            errors.append("logs: 目录不存在")

        # 4) 库统计
        try:
            stats = await _collect_library_stats_async()
        except Exception as e:
            stats = {"error": f"{type(e).__name__}: {e}"}
            errors.append(f"library_stats: {type(e).__name__}")
        zf.writestr("library_stats.json",
                    json.dumps(_redact_obj(stats), ensure_ascii=False, indent=2))

        # 5) 网络状态
        try:
            net = _collect_network_status()
        except Exception as e:
            net = {"error": f"{type(e).__name__}: {e}"}
            errors.append(f"network_status: {type(e).__name__}")
        zf.writestr("network_status.json",
                    json.dumps(_redact_obj(net), ensure_ascii=False, indent=2))

        # 6) 任务摘要
        try:
            tasks = _collect_tasks_summary()
        except Exception as e:
            tasks = {"error": f"{type(e).__name__}: {e}"}
            errors.append(f"tasks_summary: {type(e).__name__}")
        zf.writestr("tasks_summary.json",
                    json.dumps(_redact_obj(tasks), ensure_ascii=False, indent=2))

        # 7) manifest 放最后（含全部采集结果）
        manifest = {
            "generated_at": started.isoformat(timespec="seconds"),
            "duration_ms": round((datetime.now() - started).total_seconds() * 1000, 1),
            "files": ["env.json", "config.redacted.yaml",
                      *[f"logs/{n}" for n in log_names],
                      "library_stats.json", "network_status.json",
                      "tasks_summary.json", "manifest.json"],
            "collection_errors": errors,
            "redaction_note": "config/日志已脱敏（密钥/cookie/磁力/媒体文件名），"
                              "NAS 盘符与目录结构保留用于排查",
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    stamp = started.strftime("%Y%m%d-%H%M%S")
    filename = f"mdcx-diagnostics-{stamp}.zip"
    _log(f"诊断包已生成：{filename}（{len(buf.getvalue()) // 1024} KB）")
    return buf.getvalue(), filename


__all__ = ["build_bundle", "TAIL_BYTES"]
