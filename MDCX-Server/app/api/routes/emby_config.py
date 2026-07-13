"""Emby 兼容配置管理路由

走 /api/v1/emby-config 前缀，受 MDCX Bearer Token 保护。
注意：Emby 协议本身的兼容路由在 /emby/* 下，由 AuthMiddleware._check_emby_auth 单独认证。
"""

import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager

router = APIRouter()


class EmbyConfigUpdate(BaseModel):
    """Emby 配置更新"""
    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    server_name: Optional[str] = None
    version: Optional[str] = None
    play_protocol: Optional[str] = None
    nsfw_hidden: Optional[bool] = None
    page_size: Optional[int] = None


@router.get("/config")
async def get_emby_config():
    """获取 Emby 兼容配置"""
    cfg = get_config().emby_compat
    return {
        "enabled": cfg.enabled,
        "api_key": cfg.api_key,
        "server_name": cfg.server_name,
        "version": cfg.version,
        "play_protocol": cfg.play_protocol,
        "nsfw_hidden": cfg.nsfw_hidden,
        "page_size": cfg.page_size,
    }


@router.put("/config")
async def update_emby_config(req: EmbyConfigUpdate):
    """更新 Emby 兼容配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.emby_compat.enabled = req.enabled
    if req.api_key is not None:
        current.emby_compat.api_key = req.api_key
    if req.server_name is not None:
        current.emby_compat.server_name = req.server_name
    if req.version is not None:
        current.emby_compat.version = req.version
    if req.play_protocol is not None:
        if req.play_protocol not in ("http", "https"):
            raise HTTPException(status_code=400, detail="play_protocol 必须是 http 或 https")
        current.emby_compat.play_protocol = req.play_protocol
    if req.nsfw_hidden is not None:
        current.emby_compat.nsfw_hidden = req.nsfw_hidden
    if req.page_size is not None:
        current.emby_compat.page_size = max(10, min(500, req.page_size))

    cm.save()
    return {"status": "ok"}


@router.post("/regenerate-key")
async def regenerate_api_key():
    """重新生成 API Key"""
    cm = get_config_manager()
    cm.config.emby_compat.api_key = secrets.token_hex(16)
    cm.save()
    return {"status": "ok", "api_key": cm.config.emby_compat.api_key}


@router.post("/test")
async def test_emby_endpoint():
    """自检 Emby 协议是否正常响应"""
    import httpx
    from app.config.manager import get_config

    cfg = get_config()
    port = cfg.server.port
    url = f"http://localhost:{port}/emby/System/Info/Public"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "status_code": resp.status_code,
                    "server_name": data.get("ServerName"),
                    "version": data.get("Version"),
                }
            return {
                "ok": False,
                "status_code": resp.status_code,
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/clients-guide")
async def clients_guide():
    """获取客户端接入指南"""
    cfg = get_config()
    port = cfg.server.port
    server_addr = f"http://<your-server-ip>:{port}"

    return {
        "server_address": server_addr,
        "api_key": cfg.emby_compat.api_key,
        "username": "admin",
        "password": "",
        "clients": [
            {
                "name": "Infuse",
                "platform": "iOS / macOS / tvOS",
                "setup": "添加服务器 → 选择 Emby → 填入地址和 API Key",
                "notes": "Infuse Pro 自动匹配元数据，无需配置 MDCX 也可播放",
            },
            {
                "name": "VidHub",
                "platform": "iOS / macOS / tvOS",
                "setup": "添加 Emby 服务器 → 填入地址、用户名（admin）",
                "notes": "原生支持 HDR / 杜比视界播放",
            },
            {
                "name": "SenPlayer",
                "platform": "iOS / tvOS",
                "setup": "添加媒体服务器 → Emby → 填入地址和 API Key",
                "notes": "免费 Emby 客户端，性能优秀",
            },
            {
                "name": "Fileball",
                "platform": "iOS / macOS / tvOS",
                "setup": "添加 SMB/FTP/Emby 服务器 → 填入地址和 API Key",
                "notes": "支持本地与远程媒体库管理",
            },
            {
                "name": "Kodi + Emby 插件",
                "platform": "全平台",
                "setup": "安装 Emby for Kodi 插件 → 配置服务器地址和凭据",
                "notes": "全功能客户端，支持插件扩展",
            },
        ],
        "endpoints": [
            {"path": "/emby/System/Info/Public", "method": "GET", "auth": "无", "desc": "服务器公共信息"},
            {"path": "/emby/Users/Public", "method": "GET", "auth": "无", "desc": "公共用户列表"},
            {"path": "/emby/Users/AuthenticateByName", "method": "POST", "auth": "Body", "desc": "用户名密码认证"},
            {"path": "/emby/Users/{id}/Items", "method": "GET", "auth": "API Key", "desc": "用户媒体库"},
            {"path": "/emby/Items/{id}/Images/Primary", "method": "GET", "auth": "无", "desc": "主图（海报）"},
            {"path": "/emby/Videos/{id}/stream", "method": "GET", "auth": "API Key", "desc": "视频流"},
        ],
    }
