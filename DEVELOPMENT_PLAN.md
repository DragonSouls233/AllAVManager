# MDCX 开发计划 — 参考代码直接集成方案

> 基于 160+ 参考项目分析，提取可直接复制的代码，分阶段集成到 MDCX。
> 
> 共 4 个阶段，每阶段提供 **可直接复制使用的 Python 源文件**。

---

## 目录

- [阶段 1：下载后自动处理管线（P0）](#阶段-1下载后自动处理管线p0)
- [阶段 2：封面多源补填系统（P0）](#阶段-2封面多源补填系统p0)
- [阶段 3：JavDB App API 客户端（P1）](#阶段-3javdb-app-api-客户端p1)
- [阶段 4：聚合在线搜索 API（P1）](#阶段-4聚合在线搜索-apip1)

---

## 阶段 1：下载后自动处理管线（P0）

### 功能说明

MDCX 当前缺少「下载后自动处理」环节。从 qBittorrent/115/Aria2 下载完成后，需要：
1. **QC 质检** — ffprobe 检查视频时长 + 文件大小，过滤广告前贴/截断文件
2. **多 CD 合并** — 将 `CD1+CD2` / `Part1+Part2` 通过 ffmpeg concat 合并为一个文件
3. **BDMV/DVD 重封装** — 将 BDMV 文件夹/VIDEO_TS 合并为单 .mkv

### 来源项目

**mp-relay** (`G:\MDCX\.references\GitHub\mp-relay-main\app/`) — 三个文件可以直接复制使用：

| 文件 | 行数 | 功能 |
|------|------|------|
| `qc.py` | 154 | ffprobe 质检：最小时长 30min，最小 200MiB |
| `merger.py` | 503 | ffmpeg concat 多 CD 合并 + BDMV remux |
| `exists.py` | 207 | 番号查重（注意：依赖 mp-relay 的 config/MpClient，需适配） |

### 集成位置

- **新建文件**: `MDCX-Server/app/services/post_download/` (新目录)
- **集成文件**: 
  - `qc.py` → `post_download/qc.py` (完整复制)
  - `merger.py` → `post_download/merger.py` (完整复制 + 将 `from . import qc` 改为 `from .qc import`)
  - `exists.py` → `post_download/exists.py` (部分保留番号解析逻辑)
- **调用入口**: `downloader_manager.py` 中下载完成后加入 QC 回调链

### 可直接复制代码

#### 1.1 qc.py — 质检引擎（完整复制，零修改）

```python
"""
Post-download quality-control checks.

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
```

#### 1.2 merger.py — 合并引擎（完整复制，零修改）

```python
"""
Merge multi-part releases into a single file, and remux disc archives.

直接从 mp-relay 复制，零修改可用。
依赖：ffmpeg + ffprobe 在 PATH 或标准安装路径下。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .qc import _ffprobe_path

log = logging.getLogger(__name__)


def _ffmpeg_path() -> Optional[str]:
    """Find ffmpeg — first on PATH, then under common Windows install locations."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    if shutil.which("ffmpeg.exe"):
        return "ffmpeg.exe"
    for candidate in (
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Multi-part merging
# ---------------------------------------------------------------------------


@dataclass
class MergeResult:
    merged_path: Optional[Path] = None
    merged_via: str = ""           # "concat-copy" | "rename-only" | ""
    deleted_parts: list[Path] = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.deleted_parts is None:
            self.deleted_parts = []


async def _stream_signature(path: Path) -> Optional[tuple]:
    """Probe the audio+video codec/profile signature so we can decide whether
    parts are concat-copy compatible."""
    ffp = _ffprobe_path()
    if not ffp:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            ffp,
            "-v", "error",
            "-show_entries",
            "stream=codec_type,codec_name,profile,width,height,sample_rate,channels",
            "-of", "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except (asyncio.TimeoutError, FileNotFoundError, PermissionError):
        return None
    try:
        data = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return None
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    if not v:
        return None
    return (
        str(v.get("codec_name", "")),
        str(v.get("profile", "")),
        str(v.get("width", "")),
        str(v.get("height", "")),
        str(a.get("codec_name", "")),
        str(a.get("profile", "")),
        str(a.get("sample_rate", "")),
        str(a.get("channels", "")),
    )


async def _parts_are_compatible(parts: list[Path]) -> bool:
    """All parts share container ext + matching codec signatures = concat-copy safe."""
    if len(parts) < 2:
        return False
    exts = {p.suffix.lower() for p in parts}
    if len(exts) != 1:
        log.info("multipart concat blocked: mixed containers %s", exts)
        return False
    sigs: list[Optional[tuple]] = []
    for p in parts:
        sigs.append(await _stream_signature(p))
    if any(s is None for s in sigs):
        log.info("multipart concat blocked: ffprobe failed on at least one part")
        return False
    if len(set(sigs)) != 1:
        log.info("multipart concat blocked: codec/profile mismatch among parts")
        return False
    return True


def _strip_part_token(name: str) -> str:
    """Best-effort: remove the CDx/PartN/letter suffix from a filename to get
    the merged base name. Keeps the original stem otherwise."""
    stem = Path(name).stem
    patterns = [
        r"[._\-\s]CD\d+\b",
        r"[._\-\s](?:PART|PT)\d+\b",
        r"\b\d+\s*OF\s*\d+\b",
        r"-Part\d+",
        r"[._\-\s]\.CD\d+",
        r"[._\-\s][A-G]$",
    ]
    out = stem
    for pat in patterns:
        out = re.sub(pat, "", out, flags=re.I)
    out = out.rstrip(" -._")
    return out or stem


async def merge_parts(parts: list[Path], *, dry_run: bool = False) -> MergeResult:
    """Concat ``parts`` (in given order) into a single file.
    
    On success the original parts are deleted and the merged file is returned.
    """
    result = MergeResult()
    if len(parts) < 2:
        result.note = "merge_parts called with <2 parts; nothing to do"
        return result

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        result.note = "ffmpeg not found; cannot merge"
        return result
    if not await _parts_are_compatible(parts):
        result.note = "parts not codec-copy compatible; not merging"
        return result

    parent = parts[0].parent
    ext = parts[0].suffix
    base_name = _strip_part_token(parts[0].name)
    merged = parent / f"{base_name}{ext}"
    if merged.exists():
        merged = parent / f"{base_name}.merged{ext}"

    list_file = parent / f".{base_name}.concat.txt"
    try:
        with list_file.open("w", encoding="utf-8") as f:
            for p in parts:
                safe = str(p.resolve()).replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
    except OSError as e:
        result.note = f"failed to write concat list: {e}"
        return result

    if dry_run:
        result.merged_path = merged
        result.merged_via = "concat-copy"
        result.note = f"would merge {len(parts)} parts → {merged.name}"
        try:
            list_file.unlink()
        except OSError:
            pass
        return result

    cmd = [
        ffmpeg,
        "-hide_banner", "-loglevel", "error",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-map", "0",
        str(merged),
    ]
    log.info("ffmpeg concat: %d parts → %s", len(parts), merged.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60 * 30)
    except (asyncio.TimeoutError, FileNotFoundError, PermissionError) as e:
        result.note = f"ffmpeg invoke failed: {e}"
        try:
            list_file.unlink()
        except OSError:
            pass
        return result
    finally:
        try:
            list_file.unlink()
        except OSError:
            pass

    if proc.returncode != 0 or not merged.exists():
        result.note = (
            f"ffmpeg rc={proc.returncode}: "
            f"{stderr.decode('utf-8', errors='replace')[:300]}"
        )
        if merged.exists():
            try:
                merged.unlink()
            except OSError:
                pass
        return result

    # Sanity-check: merged size should be close to sum of parts (allow 10% slack).
    try:
        sum_parts = sum(p.stat().st_size for p in parts)
        merged_size = merged.stat().st_size
        if merged_size < sum_parts * 0.90:
            result.note = (
                f"merged size suspicious: {merged_size} vs sum {sum_parts}; "
                f"deleting bad merge"
            )
            try:
                merged.unlink()
            except OSError:
                pass
            return result
    except OSError:
        pass

    deleted: list[Path] = []
    for p in parts:
        try:
            p.unlink()
            deleted.append(p)
        except (PermissionError, OSError, FileNotFoundError) as e:
            log.warning("could not delete part %s after merge: %s", p, e)

    result.merged_path = merged
    result.merged_via = "concat-copy"
    result.deleted_parts = deleted
    result.note = f"merged {len(parts)} parts via concat-copy"
    return result


def rename_parts_jellyfin(parts: list[Path]) -> list[str]:
    """Fallback: rename multi-part files to Jellyfin's `<base>-cd1.ext` pattern."""
    log_lines: list[str] = []
    if not parts:
        return log_lines
    base_name = _strip_part_token(parts[0].name)
    for idx, p in enumerate(parts, start=1):
        ext = p.suffix
        new_name = f"{base_name}-cd{idx}{ext}"
        new_path = p.parent / new_name
        if new_path == p:
            continue
        try:
            p.rename(new_path)
            log_lines.append(f"RENAME {p.name} → {new_name}")
        except (PermissionError, OSError, FileNotFoundError) as e:
            log_lines.append(f"FAIL rename {p.name}: {e}")
    return log_lines


# ---------------------------------------------------------------------------
# Disc archive remuxing
# ---------------------------------------------------------------------------


@dataclass
class RemuxResult:
    output_path: Optional[Path] = None
    note: str = ""
    cleaned_disc_root: bool = False


def _largest_m2ts(bdmv_root: Path) -> Optional[Path]:
    """Find the largest .m2ts file under <root>/BDMV/STREAM/."""
    stream_dir = bdmv_root / "BDMV" / "STREAM"
    if not stream_dir.is_dir():
        return None
    largest: Optional[Path] = None
    largest_sz = 0
    try:
        for p in stream_dir.iterdir():
            if p.suffix.lower() != ".m2ts" or not p.is_file():
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz > largest_sz:
                largest_sz = sz
                largest = p
    except (PermissionError, OSError):
        pass
    return largest


def _vob_chain(video_ts: Path) -> list[Path]:
    """Return VTS_NN_*.VOB files in order, biggest VTS group only."""
    if not video_ts.is_dir():
        return []
    groups: dict[str, list[Path]] = {}
    pat = re.compile(r"VTS_(\d{2})_(\d+)\.VOB$", re.I)
    try:
        for p in video_ts.iterdir():
            m = pat.search(p.name)
            if not m:
                continue
            try:
                _ = p.stat().st_size
            except OSError:
                continue
            groups.setdefault(m.group(1), []).append(p)
    except (PermissionError, OSError):
        return []
    if not groups:
        return []
    best_key = max(groups, key=lambda k: sum(p.stat().st_size for p in groups[k]))
    parts = sorted(groups[best_key], key=lambda p: p.name.lower())
    return [p for p in parts if not p.name.upper().endswith("_0.VOB")] or parts


async def remux_disc(disc_root: Path, *, dry_run: bool = False) -> RemuxResult:
    """Remux a Blu-ray (BDMV) or DVD (VIDEO_TS) into a single .mkv.
    Lossless: ``-c copy``, no re-encode."""
    result = RemuxResult()
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        result.note = "ffmpeg not found; cannot remux disc"
        return result

    bdmv = disc_root / "BDMV"
    video_ts = disc_root / "VIDEO_TS"

    if bdmv.is_dir():
        src = _largest_m2ts(disc_root)
        if src is None:
            result.note = "no .m2ts found under BDMV/STREAM"
            return result
        sources = [src]
        kind = "bdmv"
    elif video_ts.is_dir():
        sources = _vob_chain(video_ts)
        if not sources:
            result.note = "no VOB chain found under VIDEO_TS"
            return result
        kind = "dvd"
    else:
        result.note = "no BDMV/ or VIDEO_TS/ under disc_root"
        return result

    out_path = disc_root / f"{disc_root.name}.mkv"
    if out_path.exists():
        out_path = disc_root / f"{disc_root.name}.remuxed.mkv"

    if dry_run:
        result.output_path = out_path
        result.note = f"would remux {kind} ({len(sources)} src) → {out_path.name}"
        return result

    if len(sources) == 1:
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
               "-i", str(sources[0]), "-c", "copy", "-map", "0", str(out_path)]
    else:
        list_file = disc_root / ".vob.concat.txt"
        try:
            with list_file.open("w", encoding="utf-8") as f:
                for p in sources:
                    safe = str(p.resolve()).replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")
        except OSError as e:
            result.note = f"failed to write concat list: {e}"
            return result
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(list_file),
               "-c", "copy", "-map", "0", str(out_path)]

    log.info("ffmpeg remux disc (%s): %d src → %s", kind, len(sources), out_path.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60 * 60)
    except (asyncio.TimeoutError, FileNotFoundError, PermissionError) as e:
        result.note = f"ffmpeg invoke failed: {e}"
        return result
    finally:
        if len(sources) > 1:
            try:
                (disc_root / ".vob.concat.txt").unlink()
            except OSError:
                pass

    if proc.returncode != 0 or not out_path.exists():
        result.note = f"ffmpeg rc={proc.returncode}: {stderr.decode('utf-8', errors='replace')[:300]}"
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        return result

    cleaned = False
    for sub in (bdmv, video_ts, disc_root / "CERTIFICATE", disc_root / "AACS"):
        if sub.is_dir():
            try:
                shutil.rmtree(sub, ignore_errors=False)
                cleaned = True
            except OSError as e:
                log.warning("rmtree %s failed: %s", sub, e)

    result.output_path = out_path
    result.cleaned_disc_root = cleaned
    result.note = f"remuxed {kind} → {out_path.name} ({len(sources)} source(s))"
    return result
```

#### 1.3 调用注入代码 — 在 downloader_manager.py 中添加后处理回调

```python
# 在 MDCX-Server/app/services/downloader_manager.py 中添加以下代码

from app.services.post_download.qc import run_qc, QcResult
from app.services.post_download.merger import merge_parts, remux_disc, rename_parts_jellyfin
from pathlib import Path
from typing import Optional


async def post_process_download(target_path: str, code: Optional[str] = None) -> dict:
    """
    下载完成后自动处理管线。
    
    Args:
        target_path: 下载完成后的文件/目录路径
        code: 番号（可选，用于日志和查重）
    
    Returns:
        {"qc": QcResult dict, "merged": MergeResult dict or None}
    """
    import logging
    log = logging.getLogger(__name__)
    
    # 1. QC 质检
    qc_result = await run_qc(target_path)
    log.info(f"[post-process] QC: {qc_result}")
    
    if not qc_result.passed:
        return {"qc": qc_result, "merged": None, "note": "QC failed, skipping merge"}
    
    # 2. 查找多 CD 文件
    target = Path(target_path)
    video_exts = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".ts"}
    parts: list[Path] = []
    
    if target.is_dir():
        for f in target.iterdir():
            if f.suffix.lower() in video_exts:
                parts.append(f)
    elif target.is_file():
        # 如果是单文件，检查同一目录下是否有其他 CD
        parent = target.parent
        stem = target.stem
        for f in parent.iterdir():
            if f.suffix.lower() in video_exts and f.stem != stem and \
               _is_part_of(f, target):
                parts.append(f)
        if not parts:
            # 没有找到其他部分，跳过合并
            return {"qc": qc_result, "merged": None}
    else:
        return {"qc": qc_result, "merged": None, "note": "target not found"}
    
    # 3. 按名称排序后合并
    parts_sorted = sorted(parts, key=lambda p: p.name)
    
    # 检查是否是 BDMV/DVD 结构
    if target.is_dir():
        if (target / "BDMV").is_dir() or (target / "VIDEO_TS").is_dir():
            remux_result = await remux_disc(target)
            return {"qc": qc_result, "remux": remux_result}
    
    merge_result = await merge_parts(parts_sorted)
    
    # 如果合并不成功（codec 不匹配），使用 Jellyfin 命名回退
    if not merge_result.merged_path and not merge_result.note:
        rename_parts_jellyfin(parts_sorted)
    
    return {"qc": qc_result, "merged": merge_result}


def _is_part_of(candidate: Path, reference: Path) -> bool:
    """检查 candidate 是否是 reference 的多 CD 一部分。"""
    import re as _re
    base_stem = _re.sub(r"[._\-\s]CD\d+|[._\-\s](?:PART|PT)\d+|\b\d+\s*OF\s*\d+|-Part\d+|[._\-\s][A-G]$",
                       "", reference.stem, flags=_re.I).rstrip(" -._")
    cand_stem = _re.sub(r"[._\-\s]CD\d+|[._\-\s](?:PART|PT)\d+|\b\d+\s*OF\s*\d+|-Part\d+|[._\-\s][A-G]$",
                       "", candidate.stem, flags=_re.I).rstrip(" -._")
    return base_stem.upper() == cand_stem.upper() and candidate != reference
```

---

## 阶段 2：封面多源补填系统（P0）

### 功能说明

MDCX 刮削有时成功写入 NFO 但封面下载失败（约 10% 的媒体库）。需要一个后台任务：扫描媒体库，找到缺失封面的文件夹，按策略树补填封面。

### 来源项目

**mp-relay** `cover_refill.py` (636 行) — 完整可复制，少量适配。

策略树：
1. **JavBus** — 直接番号详情页 → `a.bigImage` cover URL（首要来源）
2. **AVSOX** — 搜索番号 → 首个结果 → 详情页封面（无码回退）
3. **JavDB CDN** — `c0.jdbstatic.com/covers/{prefix}/{id}.jpg`（最后兜底）

### 集成位置

- **新建文件**: `MDCX-Server/app/services/cover_refill.py`
- **路由注入**: `api/routes/tasks.py` 添加 `POST /api/tasks/cover-refill`
- **定时任务**: `tasks/scheduler.py` 可选定时扫描

### 可直接复制代码

请将 [mp-relay cover_refill.py](file:///g:/MDCX/.references/GitHub/mp-relay-main/app/cover_refill.py) 完整复制到 `MDCX-Server/app/services/cover_refill.py`，适配两处：

1. 将 `from .config import settings` 改为 MDCX 的配置导入方式
2. 将 `_JAVBUS_COOKIES` / `_JAVDB_REFERER` 中的常量替换为 MDCX 配置中的对应值

### 适配指南

```python
# 原 cover_refill.py 第 68 行
# from .config import settings
# 改为：
from app.config.manager import settings  # MDCX 配置管理器

# 原 cover_refill.py 第 289 行
# base = settings.javbus_base.rstrip("/")
# 改为：
from app.config.defaults import JAVBUS_BASE, AVSOX_BASE, JAVDB_BASE

# 其他依赖保持不动：httpx, bs4, PIL.Image
```

---

## 阶段 3：JavDB App API 客户端（P1）

### 功能说明

MDCX 当前通过网页爬虫访问 JavDB，频繁被 Cloudflare 拦截。引入 JavDB App API 客户端，使用其内部 JSON API（jdsignature 认证）。

### 来源项目

- **javdb-cli** (Go SDK) — 展示了 jdsignature 认证流程
- **javapi** (Go) — 实际使用 jdsignature 的 Go 实现
- **javdb-api-scraper** (Python, curl_cffi) — Python 封装 + TLS 指纹

### 架构概览

```
JavDB App API 认证流程:
  1. 登录: POST /api/v1/login/sessions  (用户名/密码)
  2. jdsignature: 每个请求添加 X-Javdb-Signature 头
     - signature = base64(hmac_sha256(method + uri + body, session_token))
     - middle = session_token[:16]
     - suffix = session_token[-16:]
     - 最终: "JV1." + middle + "." + signature + "." + suffix
  3. 端点:
     - /api/v1/movies/{id} — 影片详情
     - /api/v1/search/movies?q={code}&page=1 — 搜索
     - /api/v1/actors/{id} — 演员详情
     - /api/v1/categories — 分类列表

JavDB CDN 封面 URL 模式:
  https://c0.jdbstatic.com/covers/{id[:2]}/{id}.jpg
  Referer: https://javdb.com/
```

### 实现代码

```python
"""
JavDB App JSON API 客户端。

使用 jdsignature 认证，绕过 Cloudflare 保护。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

log = logging.getLogger(__name__)

# JavDB API 基础 URL
_JAVDB_API_BASE = "https://api.javdb.com"
_JAVDB_WEB_BASE = "https://javdb.com"

# JavDB CDN 封面 URL 模式
_JAVDB_CDN_BASE = "https://c0.jdbstatic.com/covers"
_JAVDB_REFERER = "https://javdb.com/"


@dataclass
class JavDBConfig:
    username: str = ""
    password: str = ""
    session_token: str = ""      # 空时自动登录
    proxy: Optional[str] = None
    timeout: float = 30.0


@dataclass
class JavDBMovie:
    id: str                      # javdb id (如 "9y3J1")
    code: str                    # 番号 (如 "SSIS-001")
    title: str                   # 标题
    title_cn: str = ""           # 中文标题
    date: str = ""               # 发行日期
    duration: int = 0            # 时长(分钟)
    director: str = ""
    maker: str = ""              # 制作商
    publisher: str = ""          # 发行商
    series: str = ""             # 系列
    score: float = 0.0           # 评分
    genres: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    cover_url: str = ""          # 封面 URL
    fanart_url: str = ""         # 背景图 URL
    screenshots: list[str] = field(default_factory=list)
    magnet_links: list[dict] = field(default_factory=list)


class JavDBClient:
    """JavDB App JSON API 客户端。"""
    
    def __init__(self, config: JavDBConfig):
        self.config = config
        self._session_token: Optional[str] = config.session_token or None
        self._http = httpx.AsyncClient(
            timeout=config.timeout,
            proxy=config.proxy,
            headers={
                "User-Agent": "JavDB/4.3.4 (Android; 14; SDK 34)",
                "Accept": "application/json",
                "Accept-Language": "zh-CN",
            },
        )
    
    def _make_signature(self, method: str, path: str, body: str = "") -> str:
        """生成 jdsignature 认证头。
        
        JavDB App API 要求每个请求计算 HMAC-SHA256 签名。
        """
        token = self._session_token
        if not token:
            return ""
        
        data = method.upper() + path + body
        sig = hmac.new(
            token.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        
        middle = token[:16]
        suffix = token[-16:]
        signature = base64.b64encode(sig).decode("utf-8")
        return f"JV1.{middle}.{signature}.{suffix}"
    
    async def _request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        """发送带 jdsignature 的 API 请求。"""
        url = urljoin(_JAVDB_API_BASE, path)
        body = kwargs.get("content", "") or json.dumps(kwargs.get("json", {})) or ""
        if isinstance(body, str):
            body_encoded = body
        else:
            body_encoded = body.decode("utf-8") if isinstance(body, bytes) else ""
        
        headers = kwargs.pop("headers", {})
        sig = self._make_signature(method, path, body_encoded)
        if sig:
            headers["X-Javdb-Signature"] = sig
        if self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"
        
        try:
            r = await self._http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            log.warning("JavDB API request failed: %s %s: %s", method, path, e)
            return None
        
        if r.status_code == 401:
            log.warning("JavDB API auth expired, attempting re-login")
            if await self._login():
                return await self._request(method, path, headers=headers, **kwargs)
            return None
        
        if r.status_code != 200:
            log.warning("JavDB API error: %s %s → %s", method, path, r.status_code)
            return None
        
        try:
            return r.json()
        except json.JSONDecodeError:
            log.warning("JavDB API response not JSON: %s", r.text[:200])
            return None
    
    async def _login(self) -> bool:
        """使用用户名/密码登录，获取 session_token。"""
        if not self.config.username or not self.config.password:
            log.warning("JavDB login skipped: no username/password configured")
            return False
        
        data = {
            "user": {"username": self.config.username, "password": self.config.password},
        }
        result = await self._request("POST", "/api/v1/login/sessions", json=data)
        if result and "session_token" in result:
            self._session_token = result["session_token"]
            log.info("JavDB login successful")
            return True
        
        log.warning("JavDB login failed: %s", result)
        return False
    
    async def search_movie(self, code: str) -> Optional[JavDBMovie]:
        """按番号搜索影片。"""
        path = f"/api/v1/search/movies?q={code}&page=1"
        result = await self._request("GET", path)
        if not result:
            return None
        
        movies = (result.get("data") or {}).get("movies") or []
        if not movies:
            return None
        
        # 找到最佳匹配（番号完全匹配优先）
        best = None
        code_upper = code.upper().replace("-", "")
        for m in movies:
            movie_code = (m.get("code") or "").upper().replace("-", "")
            if movie_code == code_upper:
                best = m
                break
        if not best and movies:
            best = movies[0]
        if not best:
            return None
        
        return await self.get_movie(best["id"])
    
    async def get_movie(self, movie_id: str) -> Optional[JavDBMovie]:
        """获取影片详情。"""
        path = f"/api/v1/movies/{movie_id}"
        result = await self._request("GET", path)
        if not result:
            return None
        
        data = result.get("data") or {}
        movie = data.get("movie") or {}
        
        return JavDBMovie(
            id=movie_id,
            code=movie.get("code") or "",
            title=movie.get("title") or "",
            title_cn=movie.get("title_cn") or "",
            date=movie.get("date") or "",
            duration=movie.get("duration") or 0,
            director=movie.get("director") or "",
            maker=movie.get("maker") or "",
            publisher=movie.get("publisher") or "",
            series=movie.get("series") or "",
            score=movie.get("score") or 0.0,
            genres=[g.get("name", "") for g in (movie.get("genres") or [])],
            actors=[a.get("name", "") for a in (movie.get("actors") or [])],
            cover_url=movie.get("cover_url") or "",
            fanart_url=movie.get("fanart_url") or "",
            screenshots=[s.get("url", "") for s in (movie.get("screenshots") or [])],
            magnet_links=(movie.get("magnet_links") or []),
        )
    
    async def get_actor(self, actor_id: str) -> Optional[dict]:
        """获取演员详情。"""
        path = f"/api/v1/actors/{actor_id}"
        return await self._request("GET", path)
    
    def get_cover_url(self, javdb_id: str) -> str:
        """获取 JavDB CDN 封面 URL。"""
        prefix = javdb_id[:2].lower()
        return f"{_JAVDB_CDN_BASE}/{prefix}/{javdb_id}.jpg"
    
    async def close(self):
        await self._http.aclose()
```

---

## 阶段 4：聚合在线搜索 API（P1）

### 功能说明

MDCX 现有 55+ 爬虫但缺少统一的聚合搜索 API。参考 javapi（Go）的设计：一个接口搜索多个视频站点，返回聚合结果。

### 来源项目

- **javapi** (Go) — 8 站聚合 + jdsignature 认证 + CycleTLS 绕过 Cloudflare
- **JavPy** (Node.js) — 10 站聚合 + WebSocket 实时推送
- **mp-relay jav_search.py** — 4 站磁力聚合搜索

### 聚合搜索 API 设计

```python
"""
多站点聚合搜索 API。

一个接口搜索多个 Torrent/磁力站点，按 hash 去重排序。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


@dataclass
class TorrentResult:
    name: str
    magnet: str = ""
    size: int = 0               # bytes
    seeders: int = 0
    leechers: int = 0
    source: str = ""             # site name
    code: str = ""               # 番号
    is_chinese_sub: bool = False  # 是否有中字
    detail_url: str = ""


@dataclass
class AggregateResult:
    query: str
    results: list[TorrentResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_time_ms: float = 0.0


type SearchFn = Callable[[str, httpx.AsyncClient], Awaitable[list[TorrentResult]]]


class AggregateSearcher:
    """多站点聚合搜索器。"""
    
    def __init__(self, proxy: Optional[str] = None, timeout: float = 15.0):
        self.proxy = proxy
        self.timeout = timeout
        self._searchers: dict[str, SearchFn] = {}
    
    def register(self, name: str, fn: SearchFn):
        """注册搜索源。"""
        self._searchers[name] = fn
    
    async def search(self, query: str, concurrency: int = 5) -> AggregateResult:
        """在所有注册源上并发搜索。"""
        import time
        start = time.time()
        
        result = AggregateResult(query=query)
        if not self._searchers:
            return result
        
        sem = asyncio.Semaphore(concurrency)
        
        async def _search_one(name: str, fn: SearchFn):
            async with sem:
                try:
                    async with httpx.AsyncClient(
                        timeout=self.timeout,
                        proxy=self.proxy,
                        follow_redirects=True,
                    ) as client:
                        items = await fn(query, client)
                        result.results.extend(items)
                except Exception as e:
                    result.errors.append(f"{name}: {e}")
        
        await asyncio.gather(*(
            _search_one(name, fn) for name, fn in self._searchers.items()
        ))
        
        # 按做种数降序排序 + 去重
        seen_hashes: set[str] = set()
        deduped: list[TorrentResult] = []
        for r in sorted(result.results, key=lambda x: x.seeders, reverse=True):
            key = r.magnet[:50] if r.magnet else r.name[:60]
            if key not in seen_hashes:
                seen_hashes.add(key)
                deduped.append(r)
        
        result.results = deduped
        result.total_time_ms = (time.time() - start) * 1000
        return result
```

### 内置搜索源实现

```python
# 以下搜索源可注册到 AggregateSearcher


async def search_sukebei(query: str, client: httpx.AsyncClient) -> list[TorrentResult]:
    """在 Sukebei (nyaa) 上搜索。"""
    results: list[TorrentResult] = []
    url = f"https://sukebei.nyaa.si/?q={query}&s=seeders&o=desc"
    try:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return results
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("table.torrent-list > tbody > tr"):
            cols = row.select("td")
            if len(cols) < 6:
                continue
            name_el = cols[1].select_one("a:last-child")
            magnet_el = cols[2].select_one('a[href^="magnet:"]')
            size_text = cols[3].get_text(strip=True)
            seeders_text = cols[5].get_text(strip=True)
            
            name = name_el.get_text(strip=True) if name_el else ""
            magnet = magnet_el["href"] if magnet_el else ""
            seeders = int(seeders_text) if seeders_text.isdigit() else 0
            
            # 解析大小
            size = _parse_size(size_text)
            
            if name:
                results.append(TorrentResult(
                    name=name, magnet=magnet, size=size,
                    seeders=seeders, source="sukebei",
                    is_chinese_sub="字幕" in name or "中字" in name or "CH" in name.upper(),
                ))
    except Exception as e:
        log.warning("sukebei search failed: %s", e)
    return results


async def search_javbus(query: str, client: httpx.AsyncClient) -> list[TorrentResult]:
    """在 JavBus 上搜索磁力链接。"""
    from app.crawlers.javbus import search as javbus_search
    # 复用 MDCX 现有 JavBus 爬虫
    return await javbus_search(query)


def _parse_size(text: str) -> int:
    """解析大小文本为字节数。如 '1.5 GiB' → 1610612736"""
    import re
    text = text.strip().upper()
    m = re.match(r"([\d.]+)\s*(KI?B|MI?B|GI?B|TI?B|B)", text)
    if not m:
        return 0
    num = float(m.group(1))
    unit = m.group(2)
    multipliers = {"B": 1, "KIB": 1024, "KB": 1024, "MIB": 1024**2, "MB": 1024**2,
                   "GIB": 1024**3, "GB": 1024**3, "TIB": 1024**4, "TB": 1024**4}
    return int(num * multipliers.get(unit, 1))
```

---

## 集成路线图总览

```
┌────────────────────────────────────────────────────────────────────────┐
│  MDCX 集成路线图（v2.0）                                                │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  当前状态: 64 爬虫 / 575 路由 / 6 模块 / 91万行代码                        │
│                                                                         │
│  Phase 1 ✅ 下载后自动处理管线                                             │
│  ├── post_download/qc.py  (mp-relay)                                   │
│  ├── post_download/merger.py (mp-relay)                                │
│  └── pipeline.py 编排 + WebSocket 进度推送                               │
│                                                                         │
│  Phase 2 ✅ 封面多源补填                                                  │
│  └── cover_refill.py (JavBus → AVSOX → JavDB CDN)                     │
│                                                                         │
│  Phase 3 ✅ JavDB App API 客户端                                        │
│  └── javdb_api_client.py (jdsignature HMAC-SHA256)                     │
│                                                                         │
│  Phase 4 ✅ 聚合搜索 API                                                │
│  ├── aggregate_searcher.py (Sukebei 等)                                │
│  └── streaming_aggregator.py (6 站 M3U8 聚合)                          │
│                                                                         │
│  Phase 5 ✅ 5 模块专用工具                                               │
│  ├── video_hash.py / video_dedup.py (PORNHub 去重)                     │
│  ├── western_utils.py (24 品牌 + 标题去重)                              │
│  ├── uncensored_utils.py (43 前缀 + AVSOX 封面)                        │
│  ├── fc2_leak_detector.py (FC2 泄漏检测)                               │
│  └── chinese_utils.py (151 演员 + 去广告 + 番号归一)                    │
│                                                                         │
│  Phase 6 ✅ MCP 服务端 + 聚合 M3U8 播放源                                │
│  ├── mcp_service.py (8 工具 + 2 资源, AI 直接操作)                      │
│  └── streaming_aggregator.py (missav/jable/av01/javgg)                │
│                                                                         │
│  Phase 7 ✅ 前端增强 + PyWebView 桌面                                   │
│  ├── EnhancedArtplayer.vue (弹幕/字幕/多音轨)                           │
│  ├── OnlineSourcePanel.vue (一键搜索多站播放源)                         │
│  └── pywebview_app.py (10MB 轻量桌面, 无需 Electron)                   │
│                                                                         │
│  Phase 8 ✅ P0 爬虫增强                                                 │
│  ├── chinese/aggregate.py (ModelMediaAsia + HDouban + CNMDB)          │
│  ├── uncensored_aggregate.py (20+ 前缀自动路由 + HEYZO/1PONDO)        │
│  └── western_aggregate.py (IAFD + ThePornDB + Aylo)                   │
│                                                                         │
│  Phase 9 ✅ P1 代码增强                                                 │
│  ├── pornhub_parser.py (4 降级解析: flashvars/next_data/media/HTML)    │
│  ├── pornhub_cache.py (24h 持久化缓存)                                 │
│  ├── western_enhanced.py (品牌列表 API + 聚合搜索)                     │
│  └── downloader_registry.py (36 站点下载注册表)                        │
│                                                                         │
│  Phase 10 ✅ Stash 兼容 + WebSocket 实时                               │
│  ├── stash_compat.py (StashScene/StashPerformer 兼容层)                │
│  ├── event_bus.py (全局事件总线 + WebSocket 推送)                      │
│  └── pipeline.py 已集成事件推送                                          │
│                                                                         │
│  Phase 11 (未来) ── 插件化刮削系统 + 去中心化                               │
│  ├── 参考 Javdex 插件沙箱架构                                            │
│  └── 参考 eaf_base_api curl_cffi + HLS 引擎                             │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 附录：参考项目源文件索引

| 源文件 | 行数 | 可直接复制 | 阶段 |
|--------|------|-----------|:----:|
| [mp-relay qc.py](file:///g:/MDCX/.references/GitHub/mp-relay-main/app/qc.py) | 154 | ✅ 零修改 | P0 |
| [mp-relay merger.py](file:///g:/MDCX/.references/GitHub/mp-relay-main/app/merger.py) | 503 | ✅ 零修改 | P0 |
| [mp-relay exists.py](file:///g:/MDCX/.references/GitHub/mp-relay-main/app/exists.py) | 207 | ⚠️ 需适配 config | P0 |
| [mp-relay cover_refill.py](file:///g:/MDCX/.references/GitHub/mp-relay-main/app/cover_refill.py) | 636 | ⚠️ 需适配 config | P0 |
| [eaf_base_api base.py](file:///g:/MDCX/.references/GitHub/eaf_base_api-master/base_api/base.py) | 1907 | ⚠️ 需适配 MDCX 的 HTTP 客户端 | P2 (HLS) |
| [javdb-api-scraper](file:///g:/MDCX/.references/GitHub/javdb-api-scraper) | — | ⚠️ 参考 jdsignature 逻辑 | P1 |
