"""CookieCloud API 路由"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.config.manager import get_config, get_config_manager
from app.services.cookiecloud import cookiecloud_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class CookieCloudConfigUpdate(BaseModel):
    """CookieCloud 配置更新请求"""
    enabled: Optional[bool] = None
    server_url: Optional[str] = None
    user_id: Optional[str] = None
    password: Optional[str] = None
    domain_mapping: Optional[dict[str, str]] = None
    auto_sync_interval: Optional[int] = None


@router.get("/config")
async def get_cookiecloud_config():
    """获取 CookieCloud 配置"""
    cfg = get_config().cookiecloud
    return {
        "enabled": cfg.enabled,
        "server_url": cfg.server_url,
        "user_id": cfg.user_id,
        "password": "",  # 不回显密码
        "domain_mapping": cfg.domain_mapping,
        "auto_sync_interval": cfg.auto_sync_interval,
        "last_sync_at": cfg.last_sync_at,
    }


@router.put("/config")
async def update_cookiecloud_config(req: CookieCloudConfigUpdate):
    """更新 CookieCloud 配置"""
    config = get_config()
    cfg = config.cookiecloud

    if req.enabled is not None:
        cfg.enabled = req.enabled
    if req.server_url is not None:
        cfg.server_url = req.server_url
    if req.user_id is not None:
        cfg.user_id = req.user_id
    if req.password:  # 空字符串不更新（保持原密码）
        cfg.password = req.password
    if req.domain_mapping is not None:
        cfg.domain_mapping = req.domain_mapping
    if req.auto_sync_interval is not None:
        cfg.auto_sync_interval = req.auto_sync_interval

    get_config_manager().save()
    return {"ok": True, "msg": "配置已保存"}


@router.post("/sync")
async def sync_now():
    """立即同步一次"""
    result = await cookiecloud_service.sync_once()
    return result


@router.get("/status")
async def get_status():
    """获取同步状态"""
    return cookiecloud_service.get_status()


__all__ = ["router"]
