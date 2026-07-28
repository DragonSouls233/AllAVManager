"""Post-download quality-control checks.

直接从 mp-relay 复制，零修改可用。
依赖：ffprobe 在 PATH 或标准安装路径下。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Common video extensions in a JAV release.
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".ts"}

# Minimum acceptable duration (seconds) for the largest video file.
# Most JAV runs 60-180 minutes; <30min is almost certainly truncated/ad-only.
_MIN_DURATION_SEC = 30 * 60

# Minimum size in MiB (very small files are likely sample clips or broken).
_MIN_SIZE_MIB = 200


@dataclass
class QcResult:
    passed: bool
    reason: str = ""
    largest_file: str = ""
    duration_sec: float = 0.0
    size_mib: float = 0.0


def _ffprobe_path() -> Optional[str]:
    """Find ffprobe — first on PATH, then under common Windows install locations."""
    if shutil.which("ffprobe"):
        return "ffprobe"
    if shutil.which("ffprobe.exe"):
        return "ffprobe.exe"
    for candidate in (
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


async def _probe_duration(path: str) -> Optional[float]:
    """Run ffprobe to get duration in seconds. None if probe failed."""
    ffp = _ffprobe_path()
    if not ffp:
        log.warning("ffprobe not found on PATH; skipping duration check")
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            ffp,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except (asyncio.TimeoutError, FileNotFoundError, PermissionError) as e:
        log.warning("ffprobe failed on %s: %s", path, e)
        return None
    out = stdout.decode("utf-8", errors="replace").strip()
    try:
        return float(out)
    except ValueError:
        log.warning("ffprobe returned unparseable duration for %s: %r", path, out)
        return None


def _largest_video(target: str) -> Optional[Path]:
    """Find the largest video file under `target` (recursive)."""
    base = Path(target)
    if not base.exists():
        return None
    if base.is_file() and base.suffix.lower() in _VIDEO_EXTS:
        return base
    largest: Optional[Path] = None
    largest_size = 0
    try:
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in _VIDEO_EXTS:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > largest_size:
                largest_size = size
                largest = p
    except (PermissionError, OSError):
        pass
    return largest


async def run_qc(target: str, *,
                 min_duration_sec: int = _MIN_DURATION_SEC,
                 min_size_mib: int = _MIN_SIZE_MIB) -> QcResult:
    """Inspect a downloaded torrent's primary video and decide pass/fail."""
    largest = _largest_video(target)
    if largest is None:
        return QcResult(passed=False, reason=f"no video file found under {target}")

    size_mib = largest.stat().st_size / (1024 * 1024)
    if size_mib < min_size_mib:
        return QcResult(
            passed=False,
            reason=f"largest video {largest.name} is only {size_mib:.0f} MiB (< {min_size_mib})",
            largest_file=str(largest), size_mib=size_mib,
        )

    duration = await _probe_duration(str(largest))
    if duration is None:
        return QcResult(
            passed=True,
            reason="ffprobe unavailable; duration check skipped",
            largest_file=str(largest), size_mib=size_mib,
        )
    if duration < min_duration_sec:
        return QcResult(
            passed=False,
            reason=f"duration {duration / 60:.1f}min < required {min_duration_sec / 60:.0f}min "
                   f"(file: {largest.name})",
            largest_file=str(largest), duration_sec=duration, size_mib=size_mib,
        )
    return QcResult(
        passed=True,
        reason=f"OK: {duration / 60:.1f}min, {size_mib:.0f} MiB",
        largest_file=str(largest), duration_sec=duration, size_mib=size_mib,
    )
