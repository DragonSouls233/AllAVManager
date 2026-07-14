"""
下载管理 API 路由

提供多引擎下载的 RESTful API：
- POST /download/start         提交下载任务
- GET /download/status/{id}    查询任务状态
- GET /download/list           任务列表
- POST /download/cancel/{id}   取消任务
- GET /download/engines        查询可用引擎
- GET /download/info           获取 URL 信息（不下��）
"""

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.download.temp_download_manager import get_download_manager
from app.services.download.downloader_factory import get_downloader_factory
from app.services.download.download_cache import get_download_cache
from app.services.download.download_models import DownloadTask
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/download", tags=["下载管理"])


class DownloadRequest(BaseModel):
    url: str
    output_path: Optional[str] = None
    engine: Optional[str] = None  # auto / ytdlp / m3u8 / http
    metadata: Optional[dict] = None


class ScanRequest(BaseModel):
    """���描目录请求"""
    path: str
    module: Optional[str] = "western"


@router.post("/start")
async def start_download(req: DownloadRequest):
    """提交下载任务"""
    manager = get_download_manager()
    task_id = await manager.submit(
        url=req.url,
        output_path=req.output_path,
        metadata=req.metadata,
    )
    return {"task_id": task_id, "status": "queued"}


@router.get("/status/{task_id}")
async def get_download_status(task_id: str):
    """查询任务状态"""
    manager = get_download_manager()
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": task.task_id,
        "url": task.url,
        "engine": task.engine,
        "status": task.status,
        "progress": task.progress,
        "error": task.error,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
    }


@router.get("/list")
async def list_downloads(status: Optional[str] = None):
    """任务列表"""
    manager = get_download_manager()
    tasks = manager.get_all_tasks()

    if status:
        tasks = [t for t in tasks if t.status == status]

    return {
        "total": len(tasks),
        "tasks": [
            {
                "task_id": t.task_id,
                "url": t.url,
                "engine": t.engine,
                "status": t.status,
                "progress": t.progress,
                "error": t.error,
                "created_at": t.created_at,
            }
            for t in tasks[-50:]  # 最多返回最近 50 条
        ],
    }


@router.post("/cancel/{task_id}")
async def cancel_download(task_id: str):
    """取消任务（暂未实现真正的取消，仅标记）"""
    manager = get_download_manager()
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.status = "cancelled"
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/engines")
async def list_engines():
    """查询可用引擎"""
    return {
        "engines": [
            {
                "id": "ytdlp",
                "name": "YtDlp (1000+ 站点)",
                "type": "general",
                "description": "通过 yt-dlp 支持 1000+ 视频网站的通用下载",
            },
            {
                "id": "m3u8",
                "name": "M3U8 Engine (HLS 流)",
                "type": "streaming",
                "description": "m3u8/HLS 视频流下载",
            },
            {
                "id": "http",
                "name": "HTTP Engine (多线程分片)",
                "type": "direct",
                "description": "HTTP Range 分片下载，支持断点续传",
            },
        ]
    }


@router.get("/info")
async def get_url_info(url: str = Query(..., description="要查询的 URL")):
    """获取 URL 信息（不下载）"""
    factory = get_downloader_factory()
    info = await factory.get_info(url)
    if not info:
        raise HTTPException(status_code=400, detail="无法获取 URL 信息")
    return info


@router.get("/cache/stats")
async def get_cache_stats():
    """下载缓存统计"""
    cache = get_download_cache()
    return cache.stats()


@router.get("/stats")
async def get_manager_stats():
    """下载管理器统计"""
    manager = get_download_manager()
    return manager.stats()
