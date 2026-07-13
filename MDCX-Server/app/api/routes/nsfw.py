"""NSFW 模式与马赛克识别路由（管理 API）

走 /api/v1/nsfw 和 /api/v1/mosaic 前缀，受 MDCX Bearer Token 保护。
"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager
from app.services import mosaic as mosaic_service

router = APIRouter()


# ===== NSFW 配置 =====

class NsfwConfigUpdate(BaseModel):
    """NSFW 配置更新"""
    enabled: Optional[bool] = None
    hide_cover: Optional[bool] = None
    hide_title: Optional[bool] = None
    hide_actor_avatar: Optional[bool] = None
    blur_thumbnails: Optional[bool] = None
    blur_intensity: Optional[int] = None


@router.get("/config")
async def get_nsfw_config():
    """获取 NSFW 配置"""
    cfg = get_config().nsfw
    return {
        "enabled": cfg.enabled,
        "hide_cover": cfg.hide_cover,
        "hide_title": cfg.hide_title,
        "hide_actor_avatar": cfg.hide_actor_avatar,
        "blur_thumbnails": cfg.blur_thumbnails,
        "blur_intensity": cfg.blur_intensity,
    }


@router.put("/config")
async def update_nsfw_config(req: NsfwConfigUpdate):
    """更新 NSFW 配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.nsfw.enabled = req.enabled
    if req.hide_cover is not None:
        current.nsfw.hide_cover = req.hide_cover
    if req.hide_title is not None:
        current.nsfw.hide_title = req.hide_title
    if req.hide_actor_avatar is not None:
        current.nsfw.hide_actor_avatar = req.hide_actor_avatar
    if req.blur_thumbnails is not None:
        current.nsfw.blur_thumbnails = req.blur_thumbnails
    if req.blur_intensity is not None:
        current.nsfw.blur_intensity = max(1, min(50, req.blur_intensity))

    cm.save()
    return {"status": "ok"}


@router.post("/toggle")
async def toggle_nsfw_mode():
    """快速切换 NSFW 模式"""
    cm = get_config_manager()
    cm.config.nsfw.enabled = not cm.config.nsfw.enabled
    cm.save()
    return {"status": "ok", "enabled": cm.config.nsfw.enabled}
