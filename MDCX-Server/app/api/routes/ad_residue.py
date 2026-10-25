"""推广残留清理 API 路由（媒体目录广告插页判定 + 回收站）

POST /api/v1/ad-residue/scan          → 扫描判定（只读）
POST /api/v1/ad-residue/trash         → 移入回收站（软删，可恢复）
GET  /api/v1/ad-residue/trash         → 回收站列表
POST /api/v1/ad-residue/trash/restore → 恢复
POST /api/v1/ad-residue/trash/purge   → 永久删除（硬删，不可恢复）
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.services.ad_residue import ad_residue_service

router = APIRouter()


class ScanRequest(BaseModel):
    directories: Optional[list[str]] = None  # None = 用配置的 media_dirs


class TrashRequest(BaseModel):
    paths: list[str]


@router.post("/scan")
async def scan_residue(req: ScanRequest):
    """扫描媒体目录，产出推广残留候选（junk/review 两档）。只读。"""
    return await ad_residue_service.scan(directories=req.directories)


@router.post("/trash")
async def move_to_trash(req: TrashRequest):
    """移入回收站（软删：同卷 rename 到 .mdcx-trash/，manifest 记录可恢复）"""
    return await ad_residue_service.move_to_trash(req.paths)


@router.get("/trash")
async def list_trash():
    """回收站列表（按批次分组）"""
    return await ad_residue_service.list_trash()


@router.post("/trash/restore")
async def restore_from_trash(req: TrashRequest):
    """从回收站恢复（按 manifest 还回原路径，原位置有同名文件时不覆盖）"""
    return await ad_residue_service.restore_from_trash(req.paths)


@router.post("/trash/purge")
async def purge_trash(req: TrashRequest):
    """永久删除回收站里的文件（硬删，不可恢复）"""
    return await ad_residue_service.purge_trash(req.paths)


__all__ = ["router"]
