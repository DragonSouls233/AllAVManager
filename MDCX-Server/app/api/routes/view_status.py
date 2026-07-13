"""
三态视频标记 API 路由（v3.0）

提供影片观看状态（browsed/watched/wanted）的 CRUD 接口。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Movie
from app.services.view_status import (
    view_status_service,
    VALID_STATUSES,
    VIEW_STATUS_BROWSED,
    VIEW_STATUS_WATCHED,
    VIEW_STATUS_WANTED,
)

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class ViewStatusRequest(BaseModel):
    """设置观看状态请求"""
    status: str | None = Field(..., description="browsed/watched/wanted，None 清除")


class BatchViewStatusRequest(BaseModel):
    """批量设置观看状态请求"""
    movie_ids: list[int] = Field(..., min_length=1, max_length=500)
    status: str = Field(..., description="browsed/watched/wanted")


class ViewStatusResponse(BaseModel):
    movie_id: int
    code: str | None = None
    view_status: str | None = None


class ViewStatusStatsResponse(BaseModel):
    browsed: int
    watched: int
    wanted: int
    unmarked: int


# ============================================
# 路由
# ============================================

@router.get("/stats", response_model=ViewStatusStatsResponse, summary="统计各状态影片数量")
async def get_view_status_stats(session: AsyncSession = Depends(get_session)):
    """统计 browsed/watched/wanted/unmarked 各状态影片数量"""
    counts = await view_status_service.count_by_status(session)
    return ViewStatusStatsResponse(**counts)


@router.get("/{movie_id}", response_model=ViewStatusResponse, summary="获取单部影片观看状态")
async def get_movie_view_status(movie_id: int, session: AsyncSession = Depends(get_session)):
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(404, f"影片 {movie_id} 不存在")
    return ViewStatusResponse(
        movie_id=movie.id, code=movie.code, view_status=movie.view_status
    )


@router.put("/{movie_id}", response_model=ViewStatusResponse, summary="设置单部影片观看状态")
async def set_movie_view_status(
    movie_id: int,
    body: ViewStatusRequest,
    session: AsyncSession = Depends(get_session),
):
    """设置单部影片观看状态

    status 取值：
    - `browsed`：浏览过
    - `watched`：已观看
    - `wanted`：想看
    - `null`：清除标记
    """
    try:
        movie = await view_status_service.set_status(session, movie_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not movie:
        raise HTTPException(404, f"影片 {movie_id} 不存在")

    return ViewStatusResponse(
        movie_id=movie.id, code=movie.code, view_status=movie.view_status
    )


@router.post("/batch", summary="批量设置观看状态")
async def batch_set_view_status(
    body: BatchViewStatusRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量设置影片观看状态"""
    try:
        updated = await view_status_service.batch_set_status(
            session, body.movie_ids, body.status
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"updated": updated, "status": body.status, "total_requested": len(body.movie_ids)}


@router.get("/", summary="按状态列出影片")
async def list_movies_by_status(
    status: str = Query(..., description="browsed/watched/wanted"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """按观看状态列出影片"""
    try:
        movies = await view_status_service.list_by_status(session, status, limit, offset)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "status": status,
        "total": len(movies),
        "items": [
            {
                "id": m.id,
                "code": m.code,
                "title": m.title,
                "cover_url": m.cover_url,
                "view_status": m.view_status,
                "last_played_at": m.last_played_at.isoformat() if m.last_played_at else None,
            }
            for m in movies
        ],
    }
