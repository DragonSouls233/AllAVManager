"""CloudDrive2 路由

对接 CloudDrive2 服务的 HTTP API，支持：
- 配置管理（服务器地址 / 凭据 / 视频扩展名）
- 登录测试与连接状态查询
- 浏览云端文件目录
- 递归扫描视频文件
- 生成流式播放 URL（可直接用于 mpv / HTML5 video）

参考 webdav.py 路由的实现风格。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config.manager import get_config, get_config_manager
from app.services.cloud_drive2 import cloud_drive2_client

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Pydantic 模型 ==============

class CloudDrive2ConfigUpdate(BaseModel):
    """CloudDrive2 配置更新请求"""
    enabled: Optional[bool] = None
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None  # 空字符串不更新
    base_path: Optional[str] = None
    video_extensions: Optional[list[str]] = None
    proxy_port: Optional[int] = None
    timeout: Optional[int] = None


class CloudDrive2LoginRequest(BaseModel):
    """手动登录请求（覆盖配置中的凭据）"""
    username: Optional[str] = None
    password: Optional[str] = None


class CloudDrive2StreamUrlRequest(BaseModel):
    """生成流式播放 URL 请求"""
    path: str = Field(..., description="云端文件路径")


# ============== 配置管理 ==============

@router.get("/config")
async def get_cd2_config():
    """获取 CloudDrive2 配置"""
    cfg = get_config().cloud_drive2
    return {
        "enabled": cfg.enabled,
        "url": cfg.url,
        "username": cfg.username,
        "password": "***" if cfg.password else "",
        "base_path": cfg.base_path,
        "video_extensions": cfg.video_extensions,
        "proxy_port": cfg.proxy_port,
        "timeout": cfg.timeout,
    }


@router.put("/config")
async def update_cd2_config(req: CloudDrive2ConfigUpdate):
    """更新 CloudDrive2 配置"""
    cm = get_config_manager()
    current = cm.config
    cfg = current.cloud_drive2

    if req.enabled is not None:
        cfg.enabled = req.enabled
    if req.url is not None:
        cfg.url = req.url
    if req.username is not None:
        cfg.username = req.username
    if req.password and req.password != "***":
        cfg.password = req.password
    if req.base_path is not None:
        cfg.base_path = req.base_path
    if req.video_extensions is not None:
        cfg.video_extensions = req.video_extensions
    if req.proxy_port is not None:
        cfg.proxy_port = req.proxy_port
    if req.timeout is not None:
        cfg.timeout = req.timeout

    cm.save()
    return {"ok": True, "msg": "配置已保存"}


# ============== 连接状态 & 登录 ==============

@router.get("/status")
async def get_cd2_status():
    """获取 CloudDrive2 连接状态"""
    return await cloud_drive2_client.get_status()


@router.post("/login")
async def cd2_login(req: CloudDrive2LoginRequest = None):
    """手动登录 CloudDrive2

    不传 body 时使用配置中的凭据。
    """
    # 如果请求体提供了凭据，临时覆盖配置
    if req and (req.username or req.password):
        cm = get_config_manager()
        current = cm.config
        if req.username:
            current.cloud_drive2.username = req.username
        if req.password:
            current.cloud_drive2.password = req.password
        cm.save()

    ok = await cloud_drive2_client.login()
    if not ok:
        raise HTTPException(status_code=401, detail="登录失败，请检查用户名/密码或服务器地址")
    return {"ok": True, "msg": "登录成功"}


# ============== 文件浏览 ==============

@router.get("/list")
async def cd2_list_dir(
    path: str = Query("/", description="云端路径"),
):
    """列出云端目录"""
    try:
        return await cloud_drive2_client.list_dir(path)
    except Exception as e:
        logger.error(f"CloudDrive2 列目录失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


@router.get("/file-info")
async def cd2_file_info(
    path: str = Query(..., description="云端文件路径"),
):
    """获取云端文件详情"""
    try:
        return await cloud_drive2_client.get_file_info(path)
    except Exception as e:
        logger.error(f"CloudDrive2 获取文件信息失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


# ============== 扫描视频 ==============

@router.get("/scan")
async def cd2_scan(
    path: str = Query("/", description="起始路径"),
    recursive: bool = Query(True, description="是否递归扫描子目录"),
    max_depth: int = Query(5, ge=1, le=20, description="最大递归深度"),
):
    """扫描云端目录下的所有视频文件"""
    try:
        items = await cloud_drive2_client.scan_directory(
            path=path,
            recursive=recursive,
            max_depth=max_depth,
        )
        return {
            "path": path,
            "recursive": recursive,
            "max_depth": max_depth,
            "total": len(items),
            "items": items,
        }
    except Exception as e:
        logger.error(f"CloudDrive2 扫描失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


# ============== 流式播放 URL ==============

@router.get("/stream-url")
async def cd2_stream_url(
    path: str = Query(..., description="云端文件路径"),
):
    """生成可直接播放的流式 URL

    返回的 URL 可直接用于 mpv / HTML5 video / VLC 等播放器。
    """
    url = cloud_drive2_client.get_stream_url(path)
    return {"path": path, "stream_url": url}


__all__ = ["router"]
