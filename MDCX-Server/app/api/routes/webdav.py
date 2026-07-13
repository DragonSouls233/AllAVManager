"""WebDAV 路由

包含两部分：
1. WebDAV 客户端：从远程 WebDAV 服务器扫描并导入影片
2. WebDAV 服务端：暴露本地媒体库给外部客户端（虚拟目录布局）

参考 JavdBviewed / MediaStationGo / nexus-media 的 WebDAV 集成方案。
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, get_config_manager
from app.db.database import get_session
from app.db.models import Movie, MovieActor, Actor
from app.services.webdav_client import WebDAVClient, scan_webdav_for_movies, import_webdav_movies

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Pydantic 模型 ==============

class WebDAVTestRequest(BaseModel):
    url: str
    username: Optional[str] = None
    password: Optional[str] = None


class WebDAVScanRequest(BaseModel):
    url: Optional[str] = None  # None=用配置
    username: Optional[str] = None
    password: Optional[str] = None
    base_path: str = "/"
    max_depth: int = 5


class WebDAVImportRequest(BaseModel):
    movies: list[dict]  # 扫描结果
    link_mode: str = "link"  # link / copy / move
    local_dir: Optional[str] = None


class WebDAVConfigUpdate(BaseModel):
    """WebDAV 配置更新"""
    # 客户端
    client_enabled: Optional[bool] = None
    client_url: Optional[str] = None
    client_username: Optional[str] = None
    client_password: Optional[str] = None
    client_base_path: Optional[str] = None
    client_link_mode: Optional[str] = None
    # 服务端
    server_enabled: Optional[bool] = None
    server_mount_path: Optional[str] = None
    server_username: Optional[str] = None
    server_password: Optional[str] = None
    server_virtual_layout: Optional[str] = None


# ============== 工具函数 ==============

def _get_client_from_config_or_params(
    url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> WebDAVClient:
    """从参数或配置获取 WebDAV 客户端"""
    cfg = get_config().webdav_client
    final_url = url or cfg.url
    final_user = username if username is not None else cfg.username
    final_pass = password if password is not None else cfg.password

    if not final_url:
        raise HTTPException(status_code=400, detail="未提供 WebDAV 服务器地址")

    return WebDAVClient(
        url=final_url,
        username=final_user,
        password=final_pass,
        timeout=30,
    )


# ============== WebDAV 客户端路由 ==============

@router.post("/test")
async def test_webdav_connection(req: WebDAVTestRequest):
    """测试 WebDAV 连接"""
    client = WebDAVClient(
        url=req.url,
        username=req.username,
        password=req.password,
        timeout=10,
    )
    try:
        ok, msg = await client.test_connection()
        return {"connected": ok, "message": msg, "url": req.url}
    finally:
        await client.close()


@router.post("/scan")
async def scan_webdav(req: WebDAVScanRequest):
    """扫描 WebDAV 目录，返回所有影片文件"""
    client = _get_client_from_config_or_params(
        url=req.url, username=req.username, password=req.password,
    )
    try:
        # 调整 base_path
        cfg = get_config().webdav_client
        base_path = req.base_path or cfg.base_path or "/"

        task_id = f"webdav-scan-{datetime.now().strftime('%H%M%S')}"
        movies = await scan_webdav_for_movies(
            client, base_path=base_path, max_depth=req.max_depth, task_id=task_id,
        )

        parsed_count = sum(1 for m in movies if m["parsed"])
        return {
            "total": len(movies),
            "parsed": parsed_count,
            "unparsed": len(movies) - parsed_count,
            "items": movies,
        }
    except Exception as e:
        logger.error(f"WebDAV 扫描失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.post("/import")
async def import_from_webdav(req: WebDAVImportRequest):
    """导入扫描结果到数据库"""
    if not req.movies:
        raise HTTPException(status_code=400, detail="影片列表不能为空")

    cfg = get_config().webdav_client
    client = _get_client_from_config_or_params()
    link_mode = req.link_mode or cfg.link_mode
    local_dir = req.local_dir

    if link_mode in ("copy", "move") and not local_dir:
        local_dir = cfg.base_path if cfg.base_path else None
        if not local_dir:
            raise HTTPException(
                status_code=400,
                detail="copy/move 模式必须提供 local_dir",
            )

    try:
        task_id = f"webdav-import-{datetime.now().strftime('%H%M%S')}"
        result = await import_webdav_movies(
            client, req.movies,
            link_mode=link_mode,
            local_dir=local_dir,
            task_id=task_id,
        )
        return result
    finally:
        await client.close()


# ============== WebDAV 配置 ==============

@router.get("/config")
async def get_webdav_config():
    """获取 WebDAV 配置"""
    cfg = get_config()
    return {
        "client": {
            "enabled": cfg.webdav_client.enabled,
            "url": cfg.webdav_client.url,
            "username": cfg.webdav_client.username,
            "password": "***" if cfg.webdav_client.password else None,
            "base_path": cfg.webdav_client.base_path,
            "link_mode": cfg.webdav_client.link_mode,
        },
        "server": {
            "enabled": cfg.webdav_server.enabled,
            "mount_path": cfg.webdav_server.mount_path,
            "username": cfg.webdav_server.username,
            "password": "***" if cfg.webdav_server.password else None,
            "virtual_layout": cfg.webdav_server.virtual_layout,
        },
    }


@router.put("/config")
async def update_webdav_config(req: WebDAVConfigUpdate):
    """更新 WebDAV 配置"""
    cm = get_config_manager()
    current = cm.config

    # 更新客户端配置
    if req.client_enabled is not None:
        current.webdav_client.enabled = req.client_enabled
    if req.client_url is not None:
        current.webdav_client.url = req.client_url
    if req.client_username is not None:
        current.webdav_client.username = req.client_username
    if req.client_password is not None and req.client_password != "***":
        current.webdav_client.password = req.client_password
    if req.client_base_path is not None:
        current.webdav_client.base_path = req.client_base_path
    if req.client_link_mode is not None:
        if req.client_link_mode not in ("copy", "move", "link"):
            raise HTTPException(status_code=400, detail="link_mode 必须是 copy/move/link")
        current.webdav_client.link_mode = req.client_link_mode

    # 更新服务端配置
    if req.server_enabled is not None:
        current.webdav_server.enabled = req.server_enabled
    if req.server_mount_path is not None:
        current.webdav_server.mount_path = req.server_mount_path
    if req.server_username is not None:
        current.webdav_server.username = req.server_username
    if req.server_password is not None and req.server_password != "***":
        current.webdav_server.password = req.server_password
    if req.server_virtual_layout is not None:
        if req.server_virtual_layout not in ("flat", "by_actor", "by_studio", "by_code"):
            raise HTTPException(status_code=400, detail="virtual_layout 非法")
        current.webdav_server.virtual_layout = req.server_virtual_layout

    cm.save()
    return {"status": "ok"}


# ============== WebDAV 服务端（虚拟文件系统） ==============

@router.get("/server/files")
async def list_webdav_server_files(
    layout: Optional[str] = Query(None, description="目录布局"),
    session: AsyncSession = Depends(get_session),
):
    """列出本地媒体库的虚拟目录结构（用于前端浏览）"""
    cfg = get_config().webdav_server
    layout = layout or cfg.virtual_layout

    # 查询所有有文件路径的影片
    result = await session.execute(
        select(Movie).where(Movie.file_path.is_not(None)).order_by(Movie.code)
    )
    movies = result.scalars().all()

    if layout == "flat":
        # 扁平布局：所有影片在同一层
        items = []
        for m in movies:
            items.append({
                "name": f"{m.code}{os.path.splitext(m.file_path or '')[-1]}",
                "path": f"/{m.code}",
                "is_dir": False,
                "size": m.file_size or 0,
                "movie_id": m.id,
                "code": m.code,
                "title": m.title,
            })
        return {"layout": "flat", "items": items}

    elif layout == "by_code":
        # 按番号首字母分组
        groups: dict[str, list] = {}
        for m in movies:
            first = (m.code[:1] or "#").upper()
            if first.isdigit():
                first = "0-9"
            groups.setdefault(first, []).append(m)

        items = []
        for letter, ms in sorted(groups.items()):
            items.append({
                "name": letter,
                "path": f"/{letter}",
                "is_dir": True,
                "count": len(ms),
                "children": [
                    {
                        "name": f"{m.code}{os.path.splitext(m.file_path or '')[-1]}",
                        "path": f"/{letter}/{m.code}",
                        "is_dir": False,
                        "size": m.file_size or 0,
                        "movie_id": m.id,
                        "code": m.code,
                        "title": m.title,
                    }
                    for m in ms
                ],
            })
        return {"layout": "by_code", "items": items}

    elif layout == "by_actor":
        # 按演员分组
        # 查询每个影片的演员
        items = []
        for m in movies:
            actors_result = await session.execute(
                select(Actor.name)
                .join(MovieActor, Actor.id == MovieActor.actor_id)
                .where(MovieActor.movie_id == m.id)
                .order_by(Actor.name)
            )
            actors = [r[0] for r in actors_result.fetchall()]
            items.append({
                "name": f"{m.code}{os.path.splitext(m.file_path or '')[-1]}",
                "path": f"/{'/'.join(actors[:1]) or 'unknown'}/{m.code}",
                "is_dir": False,
                "size": m.file_size or 0,
                "movie_id": m.id,
                "code": m.code,
                "title": m.title,
                "actors": actors,
            })
        return {"layout": "by_actor", "items": items}

    elif layout == "by_studio":
        # 按厂商分组
        items = []
        for m in movies:
            studio = m.maker or "未知"
            items.append({
                "name": f"{m.code}{os.path.splitext(m.file_path or '')[-1]}",
                "path": f"/{studio}/{m.code}",
                "is_dir": False,
                "size": m.file_size or 0,
                "movie_id": m.id,
                "code": m.code,
                "title": m.title,
                "studio": studio,
            })
        return {"layout": "by_studio", "items": items}

    return {"layout": layout, "items": []}
