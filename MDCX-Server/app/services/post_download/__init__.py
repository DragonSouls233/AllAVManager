"""下载后自动处理管线。

提供 QC 质检、多 CD 合并、BDMV/DVD 重封装功能。
"""
from .qc import run_qc, QcResult
from .merger import merge_parts, remux_disc, rename_parts_jellyfin, MergeResult, RemuxResult
from .pipeline import post_process_download

__all__ = [
    "run_qc", "QcResult",
    "merge_parts", "remux_disc", "rename_parts_jellyfin",
    "MergeResult", "RemuxResult",
    "post_process_download",
]
