"""下载后自动处理管线 — 编排函数。

后处理管线流程：
  1. QC 质检（ffprobe 检查时长+大小）
  2. 多 CD 合并（ffmpeg concat 无损合并）
  3. BDMV/DVD 重封装
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .qc import run_qc, QcResult
from .merger import merge_parts, remux_disc, rename_parts_jellyfin, MergeResult

log = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".ts"}


def _strip_part_token(name: str) -> str:
    """移除多CD标记，提取基准文件名。"""
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


def _is_part_of(candidate: Path, reference: Path) -> bool:
    """检查 candidate 是否是 reference 的多 CD 一部分。"""
    base_stem = _strip_part_token(reference.name)
    cand_stem = _strip_part_token(candidate.name)
    return base_stem.upper() == cand_stem.upper() and candidate != reference


async def post_process_download(target_path: str, code: Optional[str] = None) -> dict:
    """下载完成后自动处理管线。

    Args:
        target_path: 下载完成后的文件/目录路径
        code: 番号（可选，用于日志和查重）

    Returns:
        {"qc": QcResult, "merge": MergeResult or None, "note": str}
    """
    # 1. QC 质检
    qc_result = await run_qc(target_path)
    log.info("[post-process] QC: %s", qc_result)

    if not qc_result.passed:
        return {"qc": qc_result, "merge": None, "note": "QC failed, skipping merge"}

    # 2. 查找多 CD 文件
    target = Path(target_path)
    parts: list[Path] = []

    if target.is_dir():
        for f in target.iterdir():
            if f.suffix.lower() in _VIDEO_EXTS:
                parts.append(f)
    elif target.is_file():
        parent = target.parent
        for f in parent.iterdir():
            if f.suffix.lower() in _VIDEO_EXTS and f.stem != target.stem and \
               _is_part_of(f, target):
                parts.append(f)
        if not parts:
            return {"qc": qc_result, "merge": None, "note": "single file, no multi-CD found"}

        parts.append(target)
    else:
        return {"qc": qc_result, "merge": None, "note": "target not found"}

    parts_sorted = sorted(parts, key=lambda p: p.name)

    # 3. 检查是否是 BDMV/DVD 结构
    if target.is_dir():
        if (target / "BDMV").is_dir() or (target / "VIDEO_TS").is_dir():
            remux_result_obj = await remux_disc(target)
            return {"qc": qc_result, "remux": remux_result_obj}

    # 4. 多 CD 合并
    merge_result = await merge_parts(parts_sorted)

    if not merge_result.merged_path and not merge_result.note:
        rename_parts_jellyfin(parts_sorted)
        merge_result.note = "merge skipped, renamed for Jellyfin compatibility"

    return {"qc": qc_result, "merge": merge_result}
