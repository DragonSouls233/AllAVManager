"""Metatube 兼容路由 - v3.1 第五批

实现 metatube-community/metatube-sdk-go 的 HTTP API 兼容层，
让 Jellyfin 可以直接调用 MDCX 作为元数据提供者。

参考：https://github.com/metatube-community/metatube-sdk-go

实现的端点（兼容 Jellyfin metatube 插件调用）：
- GET /metatube/          -> 插件信息
- GET /metatube/search    -> 搜索影片（按关键字）
- GET /metatube/movie/{provider}/{id} -> 获取影片详情
- GET /metatube/actor/{provider}/{id} -> 获取演员详情
- GET /metatube/image/primary/{provider}/{id} -> 主图（封面）
- GET /metatube/image/backdrop/{provider}/{id} -> 背景图
- GET /metatube/image/logo/{provider}/{id} -> Logo
- GET /metatube/image/thumb/{provider}/{id} -> 缩略图
- GET /metatube/image/actor/{provider}/{id} -> 演员头像

MDCX 作为 provider="mdcx"，id=数据库 movie_id 或 actor_id。
所有图片直接从本地数据库查询后返回。
"""

import base64
import logging
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, get_config_manager
from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor

logger = logging.getLogger(__name__)

# 兼容路由（不挂载到 /api/v1 前缀下，由 main.py 单独挂载到根路径 /metatube）
router = APIRouter()
# 配置路由（挂载到 /api/v1/metatube-config 下，供前端管理使用）
config_router = APIRouter()


# ============== Pydantic 模型 ==============

class MetatubeConfigUpdate(BaseModel):
    """Metatube 配置更新请求"""
    enabled: Optional[bool] = None
    base_path: Optional[str] = None
    plugin_name: Optional[str] = None
    token: Optional[str] = None
    image_quality: Optional[int] = None
    image_base64: Optional[bool] = None
    search_limit: Optional[int] = None
    allow_nsfw: Optional[bool] = None


class MetatubeSearchResult(BaseModel):
    """搜索结果项（兼容 Jellyfin）"""
    provider: str
    id: str
    title: str
    overview: Optional[str] = None
    release_date: Optional[str] = None
    cover_url: Optional[str] = None


class MetatubeMovie(BaseModel):
    """影片详情（兼容 Jellyfin）"""
    provider: str
    id: str
    number: str  # 番号
    title: str
    overview: Optional[str] = None
    release_date: Optional[str] = None
    runtime: Optional[int] = None  # 分钟
    director: Optional[str] = None
    maker: Optional[str] = None
    series: Optional[str] = None
    genres: list[str] = []
    actors: list[dict] = []  # [{id, name}]
    cover_url: Optional[str] = None
    poster_url: Optional[str] = None
    trailer_url: Optional[str] = None
    is_uncensored: Optional[bool] = None


class MetatubeActor(BaseModel):
    """演员详情（兼容 Jellyfin）"""
    provider: str
    id: str
    name: str
    overview: Optional[str] = None
    birthday: Optional[str] = None
    avatar_url: Optional[str] = None
    measurements: Optional[str] = None
    height: Optional[int] = None
    blood_type: Optional[str] = None


# ============== 鉴权辅助 ==============

def _check_token(request: Request):
    """检查访问令牌（若配置了 token）"""
    cfg = get_config().metatube
    if not cfg.token:
        return
    # 从 query 或 header 获取 token
    token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token != cfg.token:
        raise HTTPException(status_code=401, detail="Invalid token")


def _is_nsfw_allowed() -> bool:
    """检查是否允许 NSFW 内容"""
    return get_config().metatube.allow_nsfw


def _build_image_url(request: Request, path: str, params: dict = None) -> str:
    """构建图片 URL"""
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}{path}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    return url


# ============== 插件信息 ==============

@router.get("/")
@router.get("")
async def plugin_info():
    """插件元信息（Jellyfin 启动时调用）"""
    cfg = get_config().metatube
    return {
        "name": cfg.plugin_name,
        "version": "1.0.0",
        "description": "MDCX 元数据提供者",
        "provider": "mdcx",
        "supported_types": ["movie", "actor"],
        "endpoints": [
            "/search",
            "/movie/{provider}/{id}",
            "/actor/{provider}/{id}",
            "/image/primary/{provider}/{id}",
            "/image/backdrop/{provider}/{id}",
            "/image/thumb/{provider}/{id}",
            "/image/actor/{provider}/{id}",
        ],
    }


# ============== 配置管理（管理端 API，挂载到 /api/v1/metatube-config 下） ==============

@config_router.get("/config")
async def get_config_api():
    """获取 metatube 配置"""
    cfg = get_config().metatube
    return {
        "enabled": cfg.enabled,
        "base_path": cfg.base_path,
        "plugin_name": cfg.plugin_name,
        "token": "***" if cfg.token else "",
        "image_quality": cfg.image_quality,
        "image_base64": cfg.image_base64,
        "search_limit": cfg.search_limit,
        "allow_nsfw": cfg.allow_nsfw,
    }


@config_router.put("/config")
async def update_config_api(req: MetatubeConfigUpdate):
    """更新 metatube 配置"""
    cm = get_config_manager()
    cfg = cm.config.metatube

    if req.enabled is not None:
        cfg.enabled = req.enabled
    if req.base_path is not None:
        cfg.base_path = req.base_path
    if req.plugin_name is not None:
        cfg.plugin_name = req.plugin_name
    if req.token is not None and req.token != "" and req.token != "***":
        cfg.token = req.token
    if req.image_quality is not None:
        cfg.image_quality = req.image_quality
    if req.image_base64 is not None:
        cfg.image_base64 = req.image_base64
    if req.search_limit is not None:
        cfg.search_limit = req.search_limit
    if req.allow_nsfw is not None:
        cfg.allow_nsfw = req.allow_nsfw

    cm.save()
    return {"message": "配置已更新", "enabled": cfg.enabled}


# ============== 搜索 ==============

@router.get("/search")
async def search(
    request: Request,
    keyword: str = Query(..., description="搜索关键字"),
    session: AsyncSession = Depends(get_session),
):
    """搜索影片（关键字模糊匹配番号 / 标题）"""
    _check_token(request)
    cfg = get_config().metatube
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="Metatube 兼容未启用")

    if not keyword.strip():
        return {"results": []}

    # 数据库查询
    query = select(Movie).where(
        or_(
            Movie.code.startswith(keyword),
            Movie.title.contains(keyword),
        )
    ).limit(cfg.search_limit)

    # NSFW 过滤
    if not _is_nsfw_allowed():
        query = query.where(Movie.is_mosaic == True)  # 仅有码

    result = await session.execute(query)
    movies = result.scalars().all()

    items = []
    for m in movies:
        cover_url = _build_image_url(request, f"/metatube/image/primary/mdcx/{m.id}")
        items.append(MetatubeSearchResult(
            provider="mdcx",
            id=str(m.id),
            title=m.title or m.code,
            overview=m.plot or m.plot_short,
            release_date=m.release_date,
            cover_url=cover_url,
        ).model_dump())

    return {"results": items}


# ============== 影片详情 ==============

@router.get("/movie/{provider}/{item_id}")
async def get_movie(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取影片详情"""
    _check_token(request)
    if provider != "mdcx":
        raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")

    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid movie id")

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    # 获取演员列表
    actor_query = (
        select(Actor.id, Actor.name)
        .join(MovieActor, Actor.id == MovieActor.actor_id)
        .where(MovieActor.movie_id == movie_id)
    )
    actor_result = await session.execute(actor_query)
    actors = [{"id": str(a_id), "name": a_name} for a_id, a_name in actor_result.fetchall()]

    # 解析标签
    genres = []
    if movie.genre:
        try:
            import json
            parsed = json.loads(movie.genre)
            if isinstance(parsed, list):
                genres = [str(g) for g in parsed]
            else:
                genres = [g.strip() for g in str(movie.genre).split(",") if g.strip()]
        except Exception:
            genres = [g.strip() for g in str(movie.genre).split(",") if g.strip()]

    cover_url = _build_image_url(request, f"/metatube/image/primary/mdcx/{movie.id}")
    poster_url = _build_image_url(request, f"/metatube/image/backdrop/mdcx/{movie.id}") if movie.poster_url else None

    return MetatubeMovie(
        provider="mdcx",
        id=str(movie.id),
        number=movie.code,
        title=movie.title or movie.code,
        overview=movie.plot or movie.plot_short,
        release_date=movie.release_date,
        runtime=movie.duration,
        director=movie.director,
        maker=movie.maker,
        series=movie.series if hasattr(movie, "series") else None,
        genres=genres,
        actors=actors,
        cover_url=cover_url,
        poster_url=poster_url,
        trailer_url=movie.trailer_url,
        is_uncensored=movie.is_uncensored,
    ).model_dump()


# ============== 演员详情 ==============

@router.get("/actor/{provider}/{item_id}")
async def get_actor(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取演员详情"""
    _check_token(request)
    if provider != "mdcx":
        raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")

    try:
        actor_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid actor id")

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    avatar_url = _build_image_url(request, f"/metatube/image/actor/mdcx/{actor.id}")

    return MetatubeActor(
        provider="mdcx",
        id=str(actor.id),
        name=actor.name,
        overview=getattr(actor, "bio", None) or getattr(actor, "description", None),
        birthday=getattr(actor, "birthday", None),
        avatar_url=avatar_url,
    ).model_dump()


# ============== 图片代理 ==============

async def _fetch_image(url: str) -> bytes:
    """获取图片字节"""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def _return_image(request: Request, url: Optional[str], content_type: str = "image/jpeg"):
    """返回图片（base64 或重定向）"""
    cfg = get_config().metatube
    if not url:
        raise HTTPException(status_code=404, detail="Image not available")

    if cfg.image_base64:
        # 返回 Base64
        try:
            content = await _fetch_image(url)
            encoded = base64.b64encode(content).decode("ascii")
            return {"base64": encoded, "content_type": content_type}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Image fetch failed: {e}")
    else:
        # 直接重定向
        return RedirectResponse(url=url, status_code=302)


@router.get("/image/primary/{provider}/{item_id}")
async def get_primary_image(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取主图（封面）"""
    _check_token(request)
    if provider != "mdcx":
        raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")

    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid movie id")

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    cover_url = movie.cover_url or movie.poster_url
    return await _return_image(request, cover_url)


@router.get("/image/backdrop/{provider}/{item_id}")
async def get_backdrop_image(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取背景图（海报）"""
    _check_token(request)
    if provider != "mdcx":
        raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")

    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid movie id")

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    return await _return_image(request, movie.poster_url or movie.cover_url)


@router.get("/image/logo/{provider}/{item_id}")
async def get_logo_image(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取 Logo（MDCX 暂无 Logo 概念，返回 404）"""
    _check_token(request)
    raise HTTPException(status_code=404, detail="Logo not supported")


@router.get("/image/thumb/{provider}/{item_id}")
async def get_thumb_image(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取缩略图"""
    _check_token(request)
    if provider != "mdcx":
        raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")

    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid movie id")

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    return await _return_image(request, movie.thumb_url or movie.cover_url)


@router.get("/image/actor/{provider}/{item_id}")
async def get_actor_image(
    request: Request,
    provider: str,
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取演员头像"""
    _check_token(request)
    if provider != "mdcx":
        raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")

    try:
        actor_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid actor id")

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    return await _return_image(request, getattr(actor, "avatar_url", None))
