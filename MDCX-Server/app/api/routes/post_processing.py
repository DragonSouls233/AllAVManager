"""下载后处理和封面补填的新增路由。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.post_download import post_process_download
from app.services.cover_refill import refill_root

router = APIRouter()


class PostProcessRequest(BaseModel):
    target_path: str
    code: Optional[str] = None


class PostProcessResponse(BaseModel):
    qc_passed: bool
    qc_reason: str = ""
    merge_note: str = ""
    error: str = ""


@router.post("/post-process", response_model=PostProcessResponse)
async def api_post_process(req: PostProcessRequest):
    """下载完成后自动处理：QC 质检 + 多 CD 合并 + BDMV remux。"""
    if not Path(req.target_path).exists():
        raise HTTPException(status_code=404, detail=f"target_path not found: {req.target_path}")
    try:
        result = await post_process_download(req.target_path, req.code)
        qc = result.get("qc")
        merge = result.get("merge")
        return PostProcessResponse(
            qc_passed=qc.passed if qc else False,
            qc_reason=qc.reason if qc else "QC skipped",
            merge_note=merge.note if merge else (result.get("note") or "no merge needed"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cover-refill")
async def api_cover_refill(
    root: str = Query(..., description="Jellyfin 风格媒体库根目录"),
    dry_run: bool = Query(True, description="仅预览不实际写入"),
    limit: Optional[int] = Query(None, description="最多处理数"),
):
    """扫描媒体库目录，补填缺失的封面图片。"""
    if not Path(root).is_dir():
        raise HTTPException(status_code=404, detail=f"root directory not found: {root}")
    try:
        result = await refill_root(root, dry_run=dry_run, limit=limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
