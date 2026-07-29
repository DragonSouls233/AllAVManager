"""下载后自动处理管线 — 编排函数。

后处理管线流程：
  1. QC 质检（ffprobe 检查时长+大小）
  2. 多 CD 合并（ffmpeg concat 无损合并）
  3. BDMV/DVD 重封装

支持事件推送 — 进度实时通过 WebSocket 推送到前端。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .qc import run_qc, QcResult
from .merger import merge_parts, remux_disc, rename_parts_jellyfin, MergeResult
from app.services.event_bus import get_event_bus

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


async def post_process_download(target_path: str, code: Optional[str] = None,
                                task_id: str = "") -> dict:
    """下载完成后自动处理管线。

    Args:
        target_path: 下载完成后的文件/目录路径
        code: 番号（可选，用于日志和查重）
        task_id: 任务 ID（用于事件推送）

    Returns:
        {"qc": QcResult, "merge": MergeResult or None, "note": str}
    """
    bus = get_event_bus()
    tid = task_id or target_path[-20:]

    await bus.emit_progress(tid, 0.0, f"开始后处理: {target_path}", module="post_process")

    # 1. QC 质检
    await bus.emit_progress(tid, 0.1, "QC 质检中...", module="post_process")
    qc_result = await run_qc(target_path)
    log.info("[post-process] QC: %s", qc_result)

    if not qc_result.passed:
        reason = qc_result.reason
        await bus.emit_progress(tid, 1.0, f"QC 失败: {reason}", status="failed", module="post_process")
        return {"qc": qc_result, "merge": None, "note": "QC failed, skipping merge"}

    await bus.emit_progress(tid, 0.2, f"QC 通过: {qc_result.reason}", module="post_process")

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
            await bus.emit_progress(tid, 1.0, "单文件，无需合并", status="success", module="post_process")
            return {"qc": qc_result, "merge": None, "note": "single file, no multi-CD found"}

        parts.append(target)
    else:
        await bus.emit_progress(tid, 1.0, "目标路径不存在", status="failed", module="post_process")
        return {"qc": qc_result, "merge": None, "note": "target not found"}

    parts_sorted = sorted(parts, key=lambda p: p.name)

    # 3. 检查是否是 BDMV/DVD 结构
    if target.is_dir():
        if (target / "BDMV").is_dir() or (target / "VIDEO_TS").is_dir():
            await bus.emit_progress(tid, 0.4, "检测到 BDMV/DVD 结构，开始重封装...", module="post_process")
            remux_result_obj = await remux_disc(target)
            note = f"BDMV remux: {remux_result_obj.note}"
            await bus.emit_progress(tid, 1.0, note, status="success", module="post_process")
            return {"qc": qc_result, "remux": remux_result_obj}

    # 4. 多 CD 合并
    if len(parts_sorted) >= 2:
        await bus.emit_progress(tid, 0.5, f"发现 {len(parts_sorted)} 个分段，开始合并...", module="post_process")
    merge_result = await merge_parts(parts_sorted)

    if not merge_result.merged_path and not merge_result.note:
        rename_parts_jellyfin(parts_sorted)
        merge_result.note = "merge skipped, renamed for Jellyfin compatibility"

    if merge_result.merged_path:
        await bus.emit_progress(tid, 1.0, f"合并完成: {merge_result.merged_path.name}",
                                status="success", module="post_process")
    else:
        await bus.emit_progress(tid, 1.0, merge_result.note or "处理完成",
                                status="success", module="post_process")

    return {"qc": qc_result, "merge": merge_result}
