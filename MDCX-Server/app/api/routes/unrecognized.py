"""未识别文件处理 API 路由"""

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from app.services.unrecognized_files import unrecognized_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class ScanRequest(BaseModel):
    """扫描请求"""
    directories: Optional[list[str]] = None  # None = 使用配置的 media_dirs
    scan_mode: str = "all"  # all / no_number / no_match


class ManualLinkRequest(BaseModel):
    """手动关联请求"""
    file_path: str
    movie_id: int


class ManualSetNumberRequest(BaseModel):
    """手动指定番号请求"""
    file_path: str
    number: str
    create_if_missing: bool = True


class RenameRequest(BaseModel):
    """重命名请求"""
    old_path: str
    new_filename: str


class DeleteRequest(BaseModel):
    """删除请求"""
    file_path: str


@router.post("/scan")
async def scan_unrecognized(req: ScanRequest):
    """扫描未识别的文件"""
    result = await unrecognized_service.scan_unrecognized(
        directories=req.directories,
        scan_mode=req.scan_mode,
    )
    return result


@router.post("/manual-link")
async def manual_link(req: ManualLinkRequest):
    """手动关联文件到现有 Movie"""
    return await unrecognized_service.manual_link(req.file_path, req.movie_id)


@router.post("/manual-set-number")
async def manual_set_number(req: ManualSetNumberRequest):
    """手动指定文件番号（可创建新 Movie）"""
    return await unrecognized_service.manual_set_number(
        req.file_path, req.number, req.create_if_missing
    )


@router.post("/rename")
async def rename_file(req: RenameRequest):
    """重命名文件"""
    return await unrecognized_service.rename_file(req.old_path, req.new_filename)


@router.post("/delete")
async def delete_file(req: DeleteRequest):
    """删除孤立文件"""
    return await unrecognized_service.delete_file(req.file_path)


__all__ = ["router"]
