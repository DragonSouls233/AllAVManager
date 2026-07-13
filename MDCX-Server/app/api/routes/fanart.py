"""
fanart.tv 集成路由（C1）

提供 fanart.tv 资源搜索、获取、下载应用功能。前缀 /fanart。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawlers.fanart import FanartCrawler
from app.db.database import get_session
from app.db.models import Movie

router = APIRouter()
logger = logging.getLogger(__name__)


class DownloadRequest(BaseModel):
    """下载 fanart 请求"""
    model_config = ConfigDict(extra="forbid")

    image_url: str | None = Field(
        default=None,
        description="指定要下载的图片 URL（留空则自动选择第一个 moviebackground）",
    )


class UpdateTmdbIdRequest(BaseModel):
    """更新影片 TMDB ID 请求"""
    model_config = ConfigDict(extra="forbid")

    tmdb_id: int = Field(..., description="TMDB 影片 ID")


@router.get("/search/{tmdb_id}")
async def search_fanarts(tmdb_id: str):
    """根据 TMDB ID 搜索 fanart.tv 资源

    返回整理后的资源列表（按类型分组：moviebackground / movieposter / ...）。
    """
    crawler = FanartCrawler()
    if not crawler.enabled:
        raise HTTPException(
            status_code=400,
            detail="fanart.tv 集成未启用或 API key 未配置",
        )
    try:
        result = await crawler.search_fanarts(tmdb_id)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/movie/{movie_id}")
async def get_movie_fanarts(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取指定影片的 fanart 资源（按影片的 tmdb_id 查询）"""
    crawler = FanartCrawler()
    if not crawler.enabled:
        raise HTTPException(
            status_code=400,
            detail="fanart.tv 集成未启用或 API key 未配置",
        )
    try:
        result = await crawler.get_fanarts_for_movie(movie_id, session)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/download/{movie_id}")
async def download_movie_fanart(
    movie_id: int,
    payload: DownloadRequest,
    session: AsyncSession = Depends(get_session),
):
    """下载 fanart 背景图并应用到影片

    - 若 payload.image_url 为空，自动获取影片的 moviebackground 列表并选择第一个
    - 下载到影片文件所在目录的 extrafanart 子目录（或 output_dir/{code}/extrafanart）
    - 将路径写入 movie.sample_images 字段（追加，不覆盖现有数据）
    """
    crawler = FanartCrawler()
    if not crawler.enabled:
        raise HTTPException(
            status_code=400,
            detail="fanart.tv 集成未启用或 API key 未配置",
        )
    try:
        result = await crawler.download_and_apply_background(
            movie_id,
            session,
            image_url=payload.image_url,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", **result}


@router.put("/movie/{movie_id}/tmdb-id")
async def update_movie_tmdb_id(
    movie_id: int,
    payload: UpdateTmdbIdRequest,
    session: AsyncSession = Depends(get_session),
):
    """设置影片的 TMDB ID（用于后续 fanart 查询）"""
    result = await session.execute(select(Movie).where(Movie.id == movie_id))
    movie = result.scalar_one_or_none()
    if movie is None:
        raise HTTPException(status_code=404, detail="影片不存在")

    movie.tmdb_id = payload.tmdb_id
    await session.commit()
    return {
        "status": "ok",
        "movie_id": movie.id,
        "code": movie.code,
        "tmdb_id": movie.tmdb_id,
    }


@router.get("/config")
async def get_fanart_config():
    """获取 fanart.tv 集成配置（隐藏 api_key 尾部）"""
    from app.config.manager import get_config
    cfg = get_config().fanart
    api_key_display = ""
    if cfg.api_key:
        api_key_display = cfg.api_key[:4] + "*" * (len(cfg.api_key) - 4) if len(cfg.api_key) > 4 else "****"
    return {
        "enabled": cfg.enabled,
        "api_key": api_key_display,
        "api_key_configured": bool(cfg.api_key),
        "base_url": cfg.base_url,
        "timeout": cfg.timeout,
        "image_subdir": cfg.image_subdir,
        "auto_download": cfg.auto_download,
    }
