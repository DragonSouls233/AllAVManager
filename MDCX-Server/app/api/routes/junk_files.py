"""垃圾文件检测 API 路由

POST /api/v1/junk-files/scan  → 只读扫描媒体目录，按原因分组返回垃圾文件候选
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.services import junk_files as junk_files_service

router = APIRouter()


class ScanRequest(BaseModel):
    directories: Optional[list[str]] = None  # None = 用配置的 media_dirs


@router.post("/scan")
async def scan_junk(req: ScanRequest):
    """扫描媒体目录，产出垃圾文件候选（sample/trailer/ad/system）。只读。"""
    return await junk_files_service.scan(directories=req.directories)
