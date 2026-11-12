"""字幕下载 —— 适配器公共基础设施。

与 ``app/services/subtitle_online.py``（播放器「在线字幕」）**完全正交**：
- 那个只服务播放器、输出 WebVTT、不落盘、不走代理；
- 本包只服务「下载并落盘为 ``<视频名>.srt``」，两套解析互不复用（口径不同，
  见 DESIGN.md §0.3 / §3.6）。

本文件提供：
- 候选模型 ``SubtitleCandidate`` / 时间预算 ``Budget``
- 进程级限速闸门 ``RateGate``（interval 约束，跨任务共享）
- 唯一出网入口 ``request()``（代理只来自 ``get_effective_proxy_url()`` + ``trust_env=False``）
- 番号守卫 ``normalize_code()`` / ``title_matches_code()``
- SRT 规范化 ``normalize_srt()``
- 选优 ``merge_and_rank()`` 与落盘登记读写
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量
# 全部集中于此：改限速/超时只改这里，禁止散落到各适配器。

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MAX_BYTES = 4 * 1024 * 1024      # 单文件上限，与 subtitle_online.py 一致
CONNECT_TIMEOUT = 8.0
VIDEO_BUDGET_S = 45.0            # 单部影片整体预算
MAX_CANDIDATES_TRY = 3           # 最多尝试几个候选
SEARCH_RESULTS_LIMIT = 4         # 每站最多展开几条结果详情页
MAX_SIZE_PROBES = 3              # 最多几次 HEAD 补大小
REGISTRY_KEEP = 5000             # 落盘登记最多保留条数
RETRY_BACKOFF = 0.8

LANG_RANK = {"zh-CN": 2, "zh-TW": 1}          # 简体优先
LANG_LABEL = {"zh-CN": "简体中文", "zh-TW": "繁体中文"}
SOURCE_LABEL = {"subtitlecat": "SubtitleCat", "aiyi1": "爱译网"}
SOURCE_PRIORITY = {"subtitlecat": 0, "aiyi1": 1}


# ---------------------------------------------------------------- 异常
class SubtitleError(Exception):
    """字幕链路的统一异常基类，``reason`` 直接对外。"""

    reason = "download_failed"


class SourceBlocked(SubtitleError):
    """站点拦截（403/429/503/Cloudflare/turnstile）。"""

    reason = "blocked"


class SourceTimeout(SubtitleError):
    """连接/读取超时，或时间预算耗尽。"""

    reason = "timeout"


class DownloadFailed(SubtitleError):
    """HTTP 4xx、超限、空内容、解析失败等。"""

    reason = "download_failed"


class BudgetExceeded(SourceTimeout):
    """时间预算不足，主动放弃（不干等）。"""

    reason = "timeout"


# ---------------------------------------------------------------- 预算
@dataclass
class Budget:
    """单部影片的时间预算（monotonic 截止时刻）。"""

    deadline: float

    @classmethod
    def start(cls, seconds: float = VIDEO_BUDGET_S) -> "Budget":
        return cls(deadline=time.monotonic() + max(0.0, seconds))

    def left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def expired(self) -> bool:
        return self.left() <= 0.0

    def clamp(self, seconds: float) -> float:
        return max(0.0, min(seconds, self.left()))


# ---------------------------------------------------------------- 限速
@dataclass(frozen=True)
class RatePolicy:
    """站点限速策略。

    ``min_interval`` 是**两次请求之间的最小间隔**（唯一硬约束）。
    ``window`` / ``max_in_window`` 保留为可选的滑动窗口约束，默认关闭
    （0 表示不启用）——历史口径里的「20s / 2 次」是「超时 20s / 重试 2 次」，
    不是「20 秒内最多 2 次」，按窗口限流会让批量吞吐慢近百倍。
    """

    min_interval: float
    read_timeout: float
    retries: int
    window: float = 0.0
    max_in_window: int = 0


POLICIES: dict[str, RatePolicy] = {
    # 站点      间隔     读超时  重试
    "subtitlecat": RatePolicy(0.70, 20.0, 2),
    "aiyi1": RatePolicy(1.00, 15.0, 1),
    "subtitle_cdn": RatePolicy(0.20, 60.0, 2),
}


class RateGate:
    """按策略间隔串行化请求；同一事件循环内进程级共享。

    批量任务与单条请求共用同一闸门，因此提高并发只减少排队等待，
    不会突破站点限速。
    """

    def __init__(self, policy: RatePolicy):
        self.policy = policy
        self._lock = asyncio.Lock()
        self._next_at = 0.0
        self.acquired = 0

    async def acquire(self, budget: Budget | None = None) -> float:
        """拿到一次请求许可，返回实际等待秒数。

        预算不足时抛 :class:`BudgetExceeded`（宁可放弃也不干等）。
        """
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                if budget is not None and wait > budget.left():
                    raise BudgetExceeded("等待站点限速会超出本次时间预算")
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self.policy.min_interval
            self.acquired += 1
            return max(0.0, wait)


_GATES: dict[str, tuple[Any, RateGate]] = {}


def gate(name: str) -> RateGate:
    """取（或惰性创建）指定闸门；事件循环变化时重建，避免跨 loop 复用。"""
    loop = asyncio.get_running_loop()
    item = _GATES.get(name)
    if item is None or item[0] is not loop:
        item = (loop, RateGate(POLICIES[name]))
        _GATES[name] = item
    return item[1]


def gate_key_for(url: str | None, *, default: str = "subtitle_cdn") -> str:
    """按域名/后缀判定闸门键。"""
    if not url:
        return default
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = (parts.path or "").lower()
    if host.endswith("hinimg.com"):
        return "subtitle_cdn"
    if path.endswith((".srt", ".ass", ".ssa")):
        return "subtitle_cdn"
    if host.endswith("subtitlecat.com"):
        return "subtitlecat"
    if host.endswith("aiyi1.com"):
        return "aiyi1"
    return default


# ---------------------------------------------------------------- 出网
def http_client(url: str, policy: RatePolicy | None = None) -> httpx.AsyncClient:
    """唯一出网入口：代理只来自 get_effective_proxy_url()，且 trust_env=False。"""
    from app.services.proxy_manager import get_effective_proxy_url

    pol = policy or POLICIES.get(gate_key_for(url), POLICIES["subtitle_cdn"])
    timeout = httpx.Timeout(pol.read_timeout, connect=CONNECT_TIMEOUT)
    return httpx.AsyncClient(
        proxy=get_effective_proxy_url(url=url),
        trust_env=False,
        timeout=timeout,
        follow_redirects=True,
        headers=BASE_HEADERS,
    )


_BLOCK_MARKERS = ("just a moment", "cf-chl", "turnstile", "attention required")


def _is_blocked_response(status: int, body: bytes) -> bool:
    if status in (401, 403, 429, 503):
        return True
    head = body[:4096].decode("utf-8", "ignore").lower()
    return any(marker in head for marker in _BLOCK_MARKERS)


async def request(
    url: str,
    *,
    method: str = "GET",
    referer: str = "",
    budget: Budget | None = None,
    gate_name: str | None = None,
    policy: RatePolicy | None = None,
    max_bytes: int = MAX_BYTES,
) -> tuple[httpx.Response, bytes]:
    """带闸门 + 重试的唯一请求实现。

    重试只针对连接错误 / 读超时 / 5xx；403/404/解析失败不重试（重试只会加速封禁）。
    每次重试前重新过闸门。
    """
    key = gate_name or gate_key_for(url)
    pol = policy or POLICIES.get(key, POLICIES["subtitle_cdn"])
    extra = {"Referer": referer} if referer else {}

    last_error: Exception | None = None
    for attempt in range(pol.retries + 1):
        if budget is not None and budget.expired():
            raise BudgetExceeded("时间预算已耗尽")
        await gate(key).acquire(budget)
        try:
            async with http_client(url, pol) as client:
                response = await client.request(method, url, headers=extra)
                body = response.content
                if _is_blocked_response(response.status_code, body[:4096] if method != "HEAD" else b""):
                    raise SourceBlocked(f"站点拒绝访问（HTTP {response.status_code}）")
                if response.status_code >= 500:
                    raise SourceTimeout(f"站点返回 {response.status_code}")
                if response.status_code >= 400:
                    raise DownloadFailed(f"站点返回 HTTP {response.status_code}")
                if method != "HEAD" and len(body) > max_bytes:
                    raise DownloadFailed(f"响应超过 {max_bytes // 1024 // 1024} MiB")
                return response, body
        except SourceBlocked:
            raise
        except DownloadFailed:
            raise
        except (httpx.TransportError, SourceTimeout) as exc:
            # 连接失败/读超时/代理不可用/协议错误：可重试，最终归因 timeout
            last_error = exc
            if attempt >= pol.retries:
                break
            if budget is not None and budget.left() < RETRY_BACKOFF:
                break
            await asyncio.sleep(RETRY_BACKOFF)
        except httpx.HTTPError as exc:
            raise DownloadFailed(f"网络错误：{type(exc).__name__}") from exc

    raise SourceTimeout(f"连接站点超时：{type(last_error).__name__ if last_error else 'unknown'}")


async def fetch_text(url: str, **kwargs) -> tuple[str, str]:
    """抓 HTML，返回 (文本, 最终 URL)。编码按 utf-8 容错。"""
    response, body = await request(url, **kwargs)
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, "replace"), str(response.url)
    except LookupError:
        return body.decode("utf-8", "replace"), str(response.url)


async def fetch_size(url: str, *, referer: str = "", budget: Budget | None = None,
                     policy: RatePolicy | None = None) -> int | None:
    """HEAD 探测文件大小（只接受 Content-Length）。"""
    response, _ = await request(
        url, method="HEAD", referer=referer, budget=budget,
        gate_name="subtitle_cdn", policy=policy,
    )
    raw = response.headers.get("content-length")
    try:
        size = int(raw) if raw else None
    except (TypeError, ValueError):
        size = None
    return size if size and size > 0 else None


def parse_size(text: str) -> int | None:
    """把 "61KB" / "1.2 MB" 换算成字节。"""
    match = re.search(r"([\d.]+)\s*([KMG]?)B", (text or "").upper())
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2)
    factor = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[unit]
    return int(value * factor)


# ---------------------------------------------------------------- 候选
@dataclass(frozen=True)
class SubtitleCandidate:
    """一个「可下载的单个语种字幕文件」——不是「一个搜索结果」。"""

    source: str                 # subtitlecat | aiyi1
    language: str               # zh-CN | zh-TW
    title: str
    detail_url: str             # 详情/文章页，同时作为 Referer
    download_url: str           # .srt 直链
    referer: str
    size_declared: int | None = None
    file_name: str = ""

    @property
    def sort_key(self) -> tuple:
        return (
            -LANG_RANK.get(self.language, 0),
            -(self.size_declared or 0),
            SOURCE_PRIORITY.get(self.source, 9),
            self.title,
        )

    @property
    def language_label(self) -> str:
        return LANG_LABEL.get(self.language, self.language)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "source_label": SOURCE_LABEL.get(self.source, self.source),
            "language": self.language,
            "language_label": self.language_label,
            "title": self.title,
            "size": self.size_declared,
        }


class SubtitleSource(Protocol):
    name: str

    async def search(self, code: str, *, budget: Budget) -> list[SubtitleCandidate]: ...

    async def probe_size(self, cand: SubtitleCandidate, *, budget: Budget) -> int | None: ...

    async def download(self, cand: SubtitleCandidate, *, budget: Budget) -> bytes: ...


def merge_and_rank(candidates: list[SubtitleCandidate]) -> list[SubtitleCandidate]:
    """按 download_url 去重后排序（简体 > 繁体，同语言大者优先，再按源优先级）。"""
    seen: set[str] = set()
    unique: list[SubtitleCandidate] = []
    for cand in candidates:
        key = (cand.download_url or "").split("?")[0]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(cand)
    return sorted(unique, key=lambda c: c.sort_key)


# ---------------------------------------------------------------- 番号守卫
def normalize_code(raw: str) -> str:
    """唯一口径：复用 extract_number，禁止自写番号正则。"""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        from app.scraper.number import extract_number

        result = extract_number(text)
    except Exception:  # noqa: BLE001 - 番号识别异常一律视为无番号
        logger.debug("extract_number 失败: %r", text, exc_info=True)
        return ""
    return ((result.number if result else "") or "").strip().upper()


def code_from_path(file_path: str | None) -> str:
    """从文件路径（含父目录回退）取番号。"""
    if not file_path:
        return ""
    try:
        from app.scraper.number import extract_number_from_path

        result = extract_number_from_path(str(file_path))
    except Exception:  # noqa: BLE001
        return ""
    return ((result.number if result else "") or "").strip().upper()


def title_matches_code(title: str, code: str) -> bool:
    """标题归一化后必须包含目标番号（数字边界精确），防误匹配。"""
    target = (code or "").strip().upper()
    text = (title or "").strip()
    if not target or not text:
        return False
    if normalize_code(text) == target:
        return True
    norm = target.replace("_", "-")
    upper = text.upper().replace("_", "-")
    return bool(re.search(r"(?<![A-Z0-9])" + re.escape(norm) + r"(?![0-9])", upper))


# ---------------------------------------------------------------- SRT 规范化
_ARROW_RE = re.compile(r"\s*(?:-{1,2}>|→|—>|–>|＞)\s*")
_TIME_TOKEN_RE = re.compile(r"\d{1,3}(?:\s*[:：．。.,，]\s*\d{1,4}){1,5}")
_FULLWIDTH_MAP = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH_MAP.update({ord("："): ord(":"), ord("．"): ord("."), ord("。"): ord("."),
                       ord("，"): ord(",")})
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u2060\ufeff"), None)


def _normalize_time_axis(line: str) -> tuple[str, list[str]]:
    """把一行时间轴规整成 "HH:MM:SS,mmm --> HH:MM:SS,mmm"，返回 (行, 生效的修复项)。"""
    fixes: list[str] = []
    raw = line
    translated = line.translate(_FULLWIDTH_MAP)
    if translated != line:
        fixes.append("fullwidth_colon")
        line = translated

    parts = _ARROW_RE.split(line)
    if len(parts) < 2:
        return raw, []
    if "-->" not in line:
        fixes.append("arrow")

    stamps: list[str] = []
    for chunk in parts[:2]:
        token = _TIME_TOKEN_RE.search(chunk)
        if not token:
            return raw, []
        stamp, stamp_fixes = _normalize_stamp(token.group(0))
        if stamp is None:
            return raw, []
        fixes.extend(stamp_fixes)
        stamps.append(stamp)
    return f"{stamps[0]} --> {stamps[1]}", fixes


def _normalize_stamp(token: str) -> tuple[str | None, list[str]]:
    """单侧时间戳 → HH:MM:SS,mmm。"""
    fixes: list[str] = []
    text = token.strip()
    has_ms_sep = bool(re.search(r"[,，.]", text))
    # 有毫秒分隔符时，最后一段是毫秒；否则按「末段 >2 位即毫秒」推断
    chunks = [c for c in re.split(r"[:：．。.,，]", text) if c.strip() != ""]
    if len(chunks) < 2:
        return None, []
    milliseconds = 0
    numeric = [int(c) for c in chunks if c.isdigit()]
    if len(numeric) != len(chunks):
        return None, []
    if has_ms_sep:
        milliseconds = numeric[-1]
        core = numeric[:-1]
    elif len(str(numeric[-1])) > 2:
        milliseconds = numeric[-1]
        core = numeric[:-1]
    else:
        core = numeric

    if len(core) > 3:
        fixes.append("dup_minute")
        if len(core) == 4:
            core = core[:3]          # HH:MM:SS:FF → 丢帧号
        else:
            core = core[-3:]         # 小时/分钟重复 → 取末尾 3 段
    while len(core) < 3:
        core.insert(0, 0)

    hours, minutes, seconds = core[-3], core[-2], core[-1]
    ms_text = str(milliseconds)
    if len(ms_text) > 3:
        if len(ms_text) == 4:
            fixes.append("ms4")
        ms_text = ms_text[:3]
    else:
        ms_text = ms_text.ljust(3, "0")
    if hours > 99:
        return None, []
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms_text}", fixes


def _stamp_to_seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.split(":")
    seconds, milliseconds = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000.0


def _seconds_to_stamp(value: float) -> str:
    total = max(0.0, value)
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    seconds = int(total % 60)
    milliseconds = int(round((total - int(total)) * 1000)) % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def normalize_srt(raw: bytes) -> tuple[str, dict]:
    """字节 → 标准 SRT 文本（UTF-8、LF、块号 1..N）。

    规则见 DESIGN.md §3.7（N1~N10）：编码嗅探 / BOM / 零宽字符（保留 U+200D）/
    全角标点 / 箭头变体 / 分钟重复 / 4 位毫秒 / 时间合法性 / 块重建 / 无 BOM 输出。
    """
    meta: dict[str, Any] = {
        "source_encoding": "utf-8",
        "lines": 0,
        "blocks": 0,
        "fixes": [],
        "dropped": 0,
    }
    if not raw:
        return "", meta

    from app.services.subtitle_matcher import detect_subtitle_encoding

    encoding = detect_subtitle_encoding(raw)
    meta["source_encoding"] = encoding
    try:
        text = raw.decode(encoding, "replace")
    except LookupError:
        text = raw.decode("utf-8", "replace")
        meta["source_encoding"] = "utf-8"

    fixes: list[str] = []
    if text.startswith("\ufeff"):
        fixes.append("bom")
        text = text.lstrip("\ufeff")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 零宽字符：U+200B/200C/2060/FEFF 一律删除（正文与时间轴都清）；
    # **保留 U+200D（ZWJ）**——删掉会改变泰文/表情合写字形，属于改字而非清洗。
    cleaned = text.translate(_ZERO_WIDTH)
    if cleaned != text:
        fixes.append("zero_width")
        text = cleaned

    lines = text.split("\n")
    blocks: list[tuple[str, list[str]]] = []
    dropped = 0
    index = 0
    total = len(lines)
    while index < total:
        line = lines[index]
        if not _ARROW_RE.search(line.lstrip("\ufeff")):
            index += 1
            continue
        stamp_line, line_fixes = _normalize_time_axis(line)
        if not _ARROW_RE.search(stamp_line) or "-->" not in stamp_line:
            index += 1
            continue
        start_text, end_text = stamp_line.split("-->", 1)
        start_stamp = start_text.strip()
        end_stamp = end_text.strip()
        try:
            start_value = _stamp_to_seconds(start_stamp)
            end_value = _stamp_to_seconds(end_stamp)
        except (ValueError, IndexError):
            index += 1
            dropped += 1
            continue
        for item in line_fixes:
            if item not in fixes:
                fixes.append(item)
        if end_value <= start_value:
            end_value = start_value + 1.0
            if "end_fix" not in fixes:
                fixes.append("end_fix")
            end_stamp = _seconds_to_stamp(end_value)

        index += 1
        body: list[str] = []
        while index < total:
            candidate = lines[index]
            if _ARROW_RE.search(candidate):
                break
            if _looks_like_index(candidate) and _next_is_timing(lines, index + 1):
                break
            body.append(candidate.rstrip())
            index += 1
        while body and not body[-1].strip():
            body.pop()
        if not body or not any(item.strip() for item in body):
            dropped += 1
            continue
        blocks.append((f"{start_stamp} --> {end_stamp}", body))

    output: list[str] = []
    for order, (stamp, body) in enumerate(blocks, start=1):
        output.append(str(order))
        output.append(stamp)
        output.extend(body)
        output.append("")
    result = "\n".join(output).rstrip("\n")
    if result:
        result += "\n"

    meta["fixes"] = fixes + (["reindex"] if blocks else [])
    meta["blocks"] = len(blocks)
    meta["lines"] = sum(1 for line in result.split("\n") if line.strip())
    meta["dropped"] = dropped
    return result, meta


def _looks_like_index(line: str) -> bool:
    text = line.strip()
    return bool(text) and text.isdigit() and len(text) <= 6


def _next_is_timing(lines: list[str], start: int) -> bool:
    for index in range(start, min(len(lines), start + 3)):
        text = lines[index].strip()
        if not text:
            continue
        return bool(_ARROW_RE.search(text))
    return False


# ---------------------------------------------------------------- 落盘路径
def srt_target_path(video_path: str | Path) -> Path:
    """``<视频名>.srt`` —— 与视频严格同目录。"""
    path = Path(video_path)
    return path.with_name(path.stem + ".srt")


# ---------------------------------------------------------------- 登记表
def registry_path() -> Path:
    from app.config.manager import get_config_manager

    base = Path(get_config_manager().computed.data_dir) / "subtitles"
    return base / "download_registry.json"


def load_registry() -> dict:
    from app.utils.atomic_write import atomic_read_json

    data = atomic_read_json(registry_path(), None)
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"version": 1, "items": {}}
    return data


_registry_lock: asyncio.Lock | None = None
_registry_loop: Any = None


def _registry_mutex() -> asyncio.Lock:
    global _registry_lock, _registry_loop
    loop = asyncio.get_running_loop()
    if _registry_lock is None or _registry_loop is not loop:
        _registry_lock = asyncio.Lock()
        _registry_loop = loop
    return _registry_lock


async def registry_record(video_path: str, entry: dict) -> None:
    """写一条落盘登记（失败只记日志，不影响主流程）。"""
    from app.utils.atomic_write import atomic_write_json

    key = str(video_path)
    async with _registry_mutex():
        try:
            data = await asyncio.to_thread(load_registry)
            items = data.setdefault("items", {})
            items.pop(key, None)
            items[key] = entry
            if len(items) > REGISTRY_KEEP:
                ordered = sorted(items.items(), key=lambda kv: kv[1].get("at") or "")
                for old_key, _ in ordered[: len(items) - REGISTRY_KEEP]:
                    items.pop(old_key, None)
            await asyncio.to_thread(atomic_write_json, registry_path(), data)
        except Exception:  # noqa: BLE001 - 登记失败不能拖垮下载
            logger.warning("写字幕登记失败: %s", key, exc_info=True)


async def registry_lookup(video_path: str | None) -> dict | None:
    if not video_path:
        return None
    try:
        data = await asyncio.to_thread(load_registry)
    except Exception:  # noqa: BLE001
        return None
    return (data.get("items") or {}).get(str(video_path))
