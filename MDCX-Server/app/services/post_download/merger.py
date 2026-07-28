"""Merge multi-part releases into a single file, and remux disc archives.

直接从 mp-relay 复制，仅将 import 改为 from .qc import _ffprobe_path。
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
    merged_via: str = ""
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
    """Best-effort: remove the CDx/PartN/letter suffix from a filename."""
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
    """Fallback: rename multi-part files to Jellyfin's ``<base>-cd1.ext`` pattern."""
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
