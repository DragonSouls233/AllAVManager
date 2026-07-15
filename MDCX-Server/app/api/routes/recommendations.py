"""AI 智能推荐路由"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_session
from app.db.models import PlayHistory, FavoriteItem, Movie
from app.services.recommendation_engine import recommendation_engine
from app.api.routes.auth import require_user

router = APIRouter()


@router.get("")
async def get_recommendations(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_user),
):
    """获取推荐列表"""
    user_id = current_user.get("id")
    items = await recommendation_engine.get_recommendations(user_id, limit, session)
    # 计算用户统计（用于前端个性化说明：观影/收藏/评分次数）
    total_viewed = await session.scalar(select(func.count(PlayHistory.id)))
    total_favorites = await session.scalar(select(func.count(FavoriteItem.id)))
    total_ratings = await session.scalar(
        select(func.count(Movie.id)).where(Movie.rating != None)
    )
    return {
        "items": items,
        "stats": {
            "totalViewed": total_viewed or 0,
            "totalFavorites": total_favorites or 0,
            "totalRatings": total_ratings or 0,
        }
    }


@router.post("/refresh")
async def refresh(session: AsyncSession = Depends(get_session)):
    """刷新推荐"""
    result = await recommendation_engine.refresh_recommendations(None, session)
    return result


@router.post("/{movie_id}/dismiss")
async def dismiss(movie_id: int, session: AsyncSession = Depends(get_session)):
    """忽略推荐"""
    await recommendation_engine.dismiss_recommendation(None, movie_id, session)
    return {"status": "ok"}
