"""媒体健康扫描：库内影片文件的三态检测（只读，不动任何文件）

与 `duplicate_scanner`（扫磁盘找同番号重复文件）互补：本模块遍历**数据库里
记录的 file_path**，检查库里的影片文件是否还有效。duplicate 回答「磁盘上有
什么」，本模块回答「库里记的还在不在」——NAS 掉线、文件被移走/删除/改名、
下载中断留下的损坏文件，都只能从这里发现。

五态判定（按顺序，命中即停）：
- no_path       库里有记录但 file_path 为空（从未下载/整理，如在线源影片）
- drive_missing 盘符未就绪（NAS 掉线/未挂载/网络盘掉线）
- file_missing  盘符在但文件不在（被移走/删除/改名/整理规则改错目录）
- probe_failed  文件在但 ffprobe 探测失败（损坏/0 字节/非视频/下载中断）
- ok            以上都不是

设计约束：
- 🔴 全程只读：只用 os.path.exists / ffprobe -show_format 读文件，不写、不删、
  不移动任何文件。扫描结果只是报告，清理动作由用户决定。
- 默认快检（exists，毫秒级）；probe=True 才对存在文件跑 ffprobe（慢，按需）。
  🔴 ffprobe 是子进程，全库（jav 近万 + PH 九万）逐部跑会跑几个小时，
  因此 probe_limit 封顶（默认 500，超出记 probe_skipped）。
- 明细每类封顶 200 条（detail_limit），防响应体爆炸；*_total 计数是全量的
  （明细条数 + 溢出计数），前端拿 total 展示真实规模。
- 幽灵盘符（net use 报错误 85 的孤儿 DOS 设备）：os.path.isdir 对盘符返回
  True 但子路径全不可达，这类会落 file_missing——页面提示用户走
  /files/network-drives 的 DefineDosDevice 修复，不在本模块处理。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from app.utils.bin_tools import get_ffprobe_path
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 明细每类封顶（*_total 计数仍是全量的）
DETAIL_LIMIT = 200
# 深检默认封顶：超过这个数量的存在文件不跑 ffprobe，记入 probe_skipped
PROBE_LIMIT_DEFAULT = 500
# ffprobe 单文件超时（秒）：损坏文件可能让 ffprobe 挂住
PROBE_TIMEOUT = 15
# 深检并发：ffprobe 是 CPU/IO 混合的子进程，全并发会拖垮服务
PROBE_CONCURRENCY = 4


@dataclass
class HealthIssue:
    """一条异常记录（四态之一）"""
    movie_id: int
    code: Optional[str]
    title: Optional[str]
    file_path: str
    detail: str = ""  # 附加说明（盘符/ffprobe 错误摘要）


@dataclass
class ModuleHealthResult:
    """单模块扫描结果"""
    module: str
    scanned: int = 0
    ok: int = 0
    no_path: int = 0
    drive_missing: list[HealthIssue] = field(default_factory=list)
    file_missing: list[HealthIssue] = field(default_factory=list)
    probe_failed: list[HealthIssue] = field(default_factory=list)
    drive_missing_extra: int = 0  # 明细封顶后溢出的条数
    file_missing_extra: int = 0
    probe_failed_extra: int = 0
    probe_skipped: int = 0
    probe_errors: int = 0  # -1 = ffprobe 不可用（深检降级）
    duration_ms: int = 0

    def to_dict(self) -> dict:
        dm_total = len(self.drive_missing) + self.drive_missing_extra
        fm_total = len(self.file_missing) + self.file_missing_extra
        pf_total = len(self.probe_failed) + self.probe_failed_extra
        return {
            "module": self.module,
            "scanned": self.scanned,
            "ok": self.ok,
            "no_path": self.no_path,
            "drive_missing": [i.__dict__ for i in self.drive_missing],
            "file_missing": [i.__dict__ for i in self.file_missing],
            "probe_failed": [i.__dict__ for i in self.probe_failed],
            "drive_missing_total": dm_total,
            "file_missing_total": fm_total,
            "probe_failed_total": pf_total,
            "probe_skipped": self.probe_skipped,
            "probe_errors": self.probe_errors,
            "duration_ms": self.duration_ms,
            "issue_total": dm_total + fm_total + pf_total,
        }


def _drive_of(file_path: str) -> str:
    """取路径的盘符（Windows: 'Z:' → 'Z:\\'；无盘符返回 ''）。

    🔴 Path.drive 对「非单字母盘符」（如历史数据里的 'ZZ:'）返回空字符串
    （2026-10-25 实测，Python 3.14 pathlib），导致盘符检查被静默跳过、
    掉线片误落 file_missing。因此 Path 解析失败时用正则兜底提取盘符部分，
    让这类路径也走 drive_missing 判定（isdir 对它们返回 False）。
    """
    drive = ""
    try:
        drive = Path(file_path).drive
    except (TypeError, ValueError):
        drive = ""
    if not drive:
        m = re.match(r"^\s*([A-Za-z]{1,2}):", str(file_path))
        if m:
            drive = m.group(1) + ":"
    if not drive:
        return ""
    return drive.rstrip("\\/") + "\\"


async def _probe_file(ffprobe: str, file_path: str) -> tuple[bool, str]:
    """ffprobe 探测单文件。返回 (是否正常, 错误摘要)。

    只用 -show_format -show_streams 读元信息，不解码画面，耗时毫秒级。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error",
            "-show_format", "-show_streams",
            "-print_format", "json",
            file_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # ffprobe 启动失败（不存在/权限）
        return False, f"{type(e).__name__}: {e}"
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return False, f"ffprobe 超时（>{PROBE_TIMEOUT}s，文件可能损坏或位于无响应的网络路径）"
    if proc.returncode == 0:
        return True, ""
    err = (stderr or b"").decode("utf-8", "replace").strip()
    return False, err[:200] or f"ffprobe 返回码 {proc.returncode}"


async def scan_media_health(
    module: str,
    probe: bool = False,
    probe_limit: int = PROBE_LIMIT_DEFAULT,
) -> dict:
    """扫描单模块的影片文件健康状态（只读）。

    Args:
        module: 模块名（jav/fc2/uncensored/chinese/western/pornhub）
        probe: 是否对存在的文件跑 ffprobe 深检（慢，默认关）
        probe_limit: 深检文件数封顶，超出记 probe_skipped

    Returns:
        ModuleHealthResult.to_dict()，五态明细 + 全量汇总计数
    """
    from app.utils.module_helper import get_module_model, get_module_session

    t0 = time.monotonic()
    result = ModuleHealthResult(module=module)

    Movie = get_module_model(module, "movie")
    sess = await get_module_session(module)
    async with sess:
        # 只取需要的列：全字段 load 九万行会把内存和序列化拖爆
        stmt = select(Movie.id, Movie.code, Movie.title, Movie.file_path)
        rows = (await sess.execute(stmt)).all()

    ffprobe = get_ffprobe_path() if probe else None
    if probe and (not ffprobe or not os.path.isfile(ffprobe)):
        # ffprobe 不可用：深检降级为快检，明确告知而不是静默跳过
        result.probe_errors = -1
        logger.warning(f"[media_health] {module} 深检降级：ffprobe 不可用")
        ffprobe = None
        probe = False

    # 盘符存在性缓存：同一盘符只查一次（快检阶段的核心优化）
    drive_cache: dict[str, bool] = {}

    probe_budget = probe_limit if probe else 0
    sem = asyncio.Semaphore(PROBE_CONCURRENCY) if probe else None

    async def _probe_one(file_path: str) -> tuple[bool, str]:
        assert sem is not None and ffprobe is not None
        async with sem:
            return await _probe_file(ffprobe, file_path)

    # 快检全做完再统一跑深检：快检结果先出，深检失败不丢快检数据
    probe_jobs: list[tuple[int, Optional[str], Optional[str], str]] = []

    for row in rows:
        result.scanned += 1
        movie_id, code, title, file_path = row[0], row[1], row[2], row[3]

        if not file_path or not str(file_path).strip():
            result.no_path += 1
            continue

        file_path = str(file_path)
        drive = _drive_of(file_path)
        if drive:
            if drive not in drive_cache:
                drive_cache[drive] = os.path.isdir(drive)
            if not drive_cache[drive]:
                if len(result.drive_missing) < DETAIL_LIMIT:
                    result.drive_missing.append(HealthIssue(
                        movie_id=movie_id, code=code, title=title,
                        file_path=file_path,
                        detail=f"盘符 {drive} 未就绪（NAS 掉线或未挂载）",
                    ))
                else:
                    result.drive_missing_extra += 1
                continue

        if not os.path.isfile(file_path):
            if len(result.file_missing) < DETAIL_LIMIT:
                result.file_missing.append(HealthIssue(
                    movie_id=movie_id, code=code, title=title,
                    file_path=file_path, detail="文件不存在（被移走/删除/改名）",
                ))
            else:
                result.file_missing_extra += 1
            continue

        if probe:
            if probe_budget > 0:
                probe_budget -= 1
                probe_jobs.append((movie_id, code, title, file_path))
            else:
                result.probe_skipped += 1
                result.ok += 1  # 未深检的文件按 ok 计（存在性已通过）
        else:
            result.ok += 1

    # 统一跑深检（保留快检已得的所有结果）
    if probe_jobs:
        outcomes = await asyncio.gather(*[_probe_one(j[3]) for j in probe_jobs])
        for (movie_id, code, title, file_path), (ok, err) in zip(probe_jobs, outcomes):
            if ok:
                result.ok += 1
            elif len(result.probe_failed) < DETAIL_LIMIT:
                result.probe_failed.append(HealthIssue(
                    movie_id=movie_id, code=code, title=title,
                    file_path=file_path, detail=err,
                ))
            else:
                result.probe_failed_extra += 1

    result.duration_ms = int((time.monotonic() - t0) * 1000)
    d = result.to_dict()
    logger.info(
        f"[media_health] {module} 扫描完成：scanned={d['scanned']} ok={d['ok']} "
        f"drive_missing={d['drive_missing_total']} file_missing={d['file_missing_total']} "
        f"probe_failed={d['probe_failed_total']} no_path={d['no_path']} "
        f"({d['duration_ms']}ms)"
    )
    return d


__all__ = ["scan_media_health", "ModuleHealthResult", "HealthIssue"]
