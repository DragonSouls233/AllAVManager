"""海报增强路由

提供 4K/8K 高清海报下载、水印标签（马赛克/无码/中字/字幕等）能力。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, get_config_manager
from app.db.database import get_session
from app.db.models import Movie
from app.services.poster_enhancer import poster_enhancer_service

router = APIRouter()


class EnhanceRequest(BaseModel):
    """单个海报增强请求"""
    movie_id: int
    enable_watermark: bool = True
    watermark_position: str = "bottom-right"


class BatchEnhanceRequest(BaseModel):
    """批量海报增强请求"""
    movie_ids: list[int]


class PosterEnhancerConfigUpdate(BaseModel):
    """海报增强配置更新"""
    enabled: bool | None = None
    enable_watermark: bool | None = None
    watermark_position: str | None = None
    watermark_opacity: float | None = None
    watermark_font_size: int | None = None
    watermark_color: str | None = None
    enable_4k_upscale: bool | None = None
    amazon_japan_source: bool | None = None


@router.post("/enhance")
async def enhance_poster(
    req: EnhanceRequest,
    session: AsyncSession = Depends(get_session),
):
    """增强单个海报"""
    movie = await session.get(Movie, req.movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")
    if not movie.poster_url:
        raise HTTPException(status_code=400, detail="影片无海报 URL，无法增强")

    movie_type = poster_enhancer_service._derive_movie_type(movie)

    result = await poster_enhancer_service.enhance_poster(
        req.movie_id,
        movie.poster_url,
        ",".join(movie_type),
        req.enable_watermark,
        req.watermark_position,
        session,
    )

    if result != movie.poster_url:
        movie.poster_url = result
        await session.commit()

    return {"status": "ok", "poster_url": result}


@router.post("/batch-enhance")
async def batch_enhance(
    req: BatchEnhanceRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量增强海报"""
    if not req.movie_ids:
        raise HTTPException(status_code=400, detail="影片 ID 列表不能为空")

    results = await poster_enhancer_service.batch_enhance(req.movie_ids, session)
    return {"status": "ok", "results": results}


@router.get("/labels")
async def list_watermark_labels():
    """获取可用标签"""
    return {"labels": poster_enhancer_service.WATERMARK_LABELS}


@router.get("/positions")
async def list_positions():
    """获取水印位置"""
    return {"positions": list(poster_enhancer_service.WATERMARK_POSITIONS.keys())}


@router.get("/config")
async def get_poster_enhancer_config():
    """获取海报增强配置"""
    cfg = get_config().poster_enhancer
    return {
        "enabled": cfg.enabled,
        "enable_watermark": cfg.enable_watermark,
        "watermark_position": cfg.watermark_position,
        "watermark_opacity": cfg.watermark_opacity,
        "watermark_font": cfg.watermark_font,
        "watermark_font_size": cfg.watermark_font_size,
        "watermark_color": cfg.watermark_color,
        "watermark_template": cfg.watermark_template,
        "enable_4k_upscale": cfg.enable_4k_upscale,
        "amazon_japan_source": cfg.amazon_japan_source,
    }


@router.put("/config")
async def update_poster_enhancer_config(req: PosterEnhancerConfigUpdate):
    """更新海报增强配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.poster_enhancer.enabled = req.enabled
    if req.enable_watermark is not None:
        current.poster_enhancer.enable_watermark = req.enable_watermark
    if req.watermark_position is not None:
        if req.watermark_position not in poster_enhancer_service.WATERMARK_POSITIONS:
            raise HTTPException(
                status_code=400,
                detail=f"watermark_position 必须是 {list(poster_enhancer_service.WATERMARK_POSITIONS.keys())}",
            )
        current.poster_enhancer.watermark_position = req.watermark_position
    if req.watermark_opacity is not None:
        current.poster_enhancer.watermark_opacity = max(0.0, min(1.0, req.watermark_opacity))
    if req.watermark_font_size is not None:
        current.poster_enhancer.watermark_font_size = max(8, min(72, req.watermark_font_size))
    if req.watermark_color is not None:
        current.poster_enhancer.watermark_color = req.watermark_color
    if req.enable_4k_upscale is not None:
        current.poster_enhancer.enable_4k_upscale = req.enable_4k_upscale
    if req.amazon_japan_source is not None:
        current.poster_enhancer.amazon_japan_source = req.amazon_japan_source

    cm.save()
    return {"status": "ok"}
