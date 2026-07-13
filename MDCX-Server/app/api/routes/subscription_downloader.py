"""订阅自动下载路由（v4.1）

提供手动触发检查 / 下载 / 查询服务状态的端点。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config.manager import get_config
from app.services.subscription_downloader import subscription_downloader_service

router = APIRouter()


class DownloadRequest(BaseModel):
    code: str
    quality: str = "1080p"


@router.get("/status")
async def get_status():
    """获取订阅自动下载服务状态"""
    return {
        "running": subscription_downloader_service.is_running,
        "enabled": get_config().subscription_downloader.enabled,
    }


@router.post("/check")
async def manual_check():
    """手动触发检查所有订阅（演员 + 系列 + 自动下载）"""
    await subscription_downloader_service.check_all_subscriptions()
    return {"status": "ok"}


@router.post("/download")
async def manual_download(req: DownloadRequest):
    """手动触发搜索并下载指定番号"""
    result = await subscription_downloader_service.manual_download(req.code, req.quality)
    return result
