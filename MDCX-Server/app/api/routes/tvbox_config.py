"""TVBox/MacCMS 配置管理路由

走 /api/v1/tvbox-config 前缀，受 MDCX Bearer Token 保护。
注意：TVBox/MacCMS 协议本身的开放接口在 /tvbox/* 和 /maccms/* 下，
      不走 AuthMiddleware 认证，仅通过 query 参数 token 简单鉴权。
"""

import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager

router = APIRouter()


class TvboxConfigUpdate(BaseModel):
    """TVBox/MacCMS 配置更新请求"""
    enabled: Optional[bool] = None
    token: Optional[str] = None
    page_size: Optional[int] = None
    nsfw_hidden: Optional[bool] = None
    site_name: Optional[str] = None
    play_from: Optional[str] = None


@router.get("/config")
async def get_tvbox_config():
    """获取 TVBox/MacCMS 配置"""
    cfg = get_config().tvbox
    return {
        "enabled": cfg.enabled,
        "token": cfg.token or "",
        "page_size": cfg.page_size,
        "nsfw_hidden": cfg.nsfw_hidden,
        "site_name": cfg.site_name,
        "play_from": cfg.play_from,
    }


@router.put("/config")
async def update_tvbox_config(req: TvboxConfigUpdate):
    """更新 TVBox/MacCMS 配置"""
    cm = get_config_manager()
    current = cm.config
    cfg = current.tvbox

    if req.enabled is not None:
        cfg.enabled = req.enabled
    if req.token is not None:
        # 空字符串视为清除 token
        cfg.token = req.token.strip() or None
    if req.page_size is not None:
        if req.page_size < 1 or req.page_size > 100:
            raise HTTPException(status_code=400, detail="page_size 必须在 1-100 之间")
        cfg.page_size = req.page_size
    if req.nsfw_hidden is not None:
        cfg.nsfw_hidden = req.nsfw_hidden
    if req.site_name is not None:
        cfg.site_name = req.site_name.strip() or "MDCX 媒体库"
    if req.play_from is not None:
        cfg.play_from = req.play_from.strip() or "MDCX"

    cm.save()
    return {"status": "ok", "msg": "配置已保存"}


@router.post("/regenerate-token")
async def regenerate_tvbox_token():
    """重新生成访问令牌"""
    cm = get_config_manager()
    cm.config.tvbox.token = secrets.token_hex(16)
    cm.save()
    return {"status": "ok", "token": cm.config.tvbox.token}


@router.post("/test")
async def test_tvbox_endpoint():
    """自检 TVBox 接口是否正常响应"""
    import httpx
    cfg = get_config()
    port = cfg.server.port
    token_part = f"?token={cfg.tvbox.token}" if cfg.tvbox.token else ""
    url = f"http://localhost:{port}/tvbox/home.html{token_part}"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "status_code": resp.status_code,
                    "class_count": len(data.get("class", [])),
                    "endpoint": url,
                }
            return {
                "ok": False,
                "status_code": resp.status_code,
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/clients-guide")
async def tvbox_clients_guide():
    """获取客户端接入指南

    返回 TVBox 和 MacCMS 的接入 URL，供前端展示。
    """
    cfg = get_config()
    port = cfg.server.port
    server_addr = f"http://<your-server-ip>:{port}"
    token_part = f"?token={cfg.tvbox.token}" if cfg.tvbox.token else ""

    return {
        "server_address": server_addr,
        "token": cfg.tvbox.token or "",
        "tvbox": {
            "config_url": f"{server_addr}/tvbox/config.json{token_part}",
            "home_url": f"{server_addr}/tvbox/home.html{token_part}",
            "category_url": f"{server_addr}/tvbox/category.html{token_part}",
            "detail_url": f"{server_addr}/tvbox/detail.html{token_part}",
            "search_url": f"{server_addr}/tvbox/search.html{token_part}",
            "play_url": f"{server_addr}/tvbox/play.html{token_part}",
        },
        "maccms": {
            "api_url": f"{server_addr}/maccms/api.php/provide/vod/{token_part}",
            "list_url": f"{server_addr}/maccms/api.php/provide/vod/?ac=list{('&token=' + cfg.tvbox.token) if cfg.tvbox.token else ''}",
            "detail_url": f"{server_addr}/maccms/api.php/provide/vod/?ac=detail&ids=1{('&token=' + cfg.tvbox.token) if cfg.tvbox.token else ''}",
            "search_url": f"{server_addr}/maccms/api.php/provide/vod/?wd=xxx{('&token=' + cfg.tvbox.token) if cfg.tvbox.token else ''}",
        },
        "endpoints": [
            # TVBox 端点
            {"path": "/tvbox/config.json", "method": "GET", "auth": "Token", "desc": "TVBox 配置文件"},
            {"path": "/tvbox/home.html", "method": "GET", "auth": "Token", "desc": "TVBox 首页分类"},
            {"path": "/tvbox/category.html?t=all&pg=1", "method": "GET", "auth": "Token", "desc": "TVBox 分类列表"},
            {"path": "/tvbox/detail.html?code=xxx", "method": "GET", "auth": "Token", "desc": "TVBox 影片详情"},
            {"path": "/tvbox/search.html?wd=xxx", "method": "GET", "auth": "Token", "desc": "TVBox 搜索"},
            {"path": "/tvbox/play.html?id=1", "method": "GET", "auth": "Token", "desc": "TVBox 播放地址"},
            {"path": "/tvbox/stream/{id}", "method": "GET", "auth": "Token", "desc": "TVBox 视频流（直接播放）"},
            # MacCMS 端点
            {"path": "/maccms/api.php/provide/vod/?ac=list", "method": "GET", "auth": "Token", "desc": "MacCMS 影片列表"},
            {"path": "/maccms/api.php/provide/vod/?ac=detail&ids=1", "method": "GET", "auth": "Token", "desc": "MacCMS 影片详情"},
            {"path": "/maccms/api.php/provide/vod/?ac=videolist&ids=1", "method": "GET", "auth": "Token", "desc": "MacCMS 视频列表"},
            {"path": "/maccms/api.php/provide/vod/?wd=xxx", "method": "GET", "auth": "Token", "desc": "MacCMS 搜索"},
            {"path": "/maccms/api.php/provide/vod/?t=uncensored", "method": "GET", "auth": "Token", "desc": "MacCMS 分类筛选"},
            {"path": "/maccms/api.php/provide/vod/?h=24", "method": "GET", "auth": "Token", "desc": "MacCMS 24小时更新"},
        ],
    }


__all__ = ["router"]
