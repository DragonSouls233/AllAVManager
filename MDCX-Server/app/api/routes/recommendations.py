"""AI 智能推荐路由"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_session
from app.db.system_models import FavoriteItem
# PlayHistory/Movie now per-module
from app.utils.module_helper import get_module_model, get_module_session
from app.services.recommendation_engine import recommendation_engine
from app.api.routes.auth import require_user

router = APIRouter()


@router.get("")
async def get_recommendations(
    limit: int = Query(20, ge=1, le=100),
    module: str = Query("jav", description="推荐所依据的模块库"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_user),
):
    """获取推荐列表"""
    user_id = current_user.get("id")
    items = await recommendation_engine.get_recommendations(user_id, limit, session, module)
    # 计算用户统计（用于前端个性化说明：观影/收藏/评分次数）
    # 2026-08-09 修复: PlayHistory/Movie 是模块库模型,用模块 session 统计
    try:
        mod_session = await get_module_session(module)
        PlayHistory = get_module_model(module, "play_history")
        Movie = get_module_model(module, "movie")
        total_viewed = await mod_session.scalar(select(func.count(PlayHistory.id)))
        total_ratings = await mod_session.scalar(
            select(func.count(Movie.id)).where(Movie.rating != None)
        )
    except Exception:
        total_viewed = 0
        total_ratings = 0
    total_favorites = await session.scalar(select(func.count(FavoriteItem.id)))
    return {
        "items": items,
        "stats": {
            "totalViewed": total_viewed or 0,
            "totalFavorites": total_favorites or 0,
            "totalRatings": total_ratings or 0,
        }
    }


@router.post("/refresh")
async def refresh(
    module: str = Query("jav"),
    session: AsyncSession = Depends(get_session),
):
    """刷新推荐"""
    result = await recommendation_engine.refresh_recommendations(None, session, module)
    return result


@router.post("/{movie_id}/dismiss")
async def dismiss(
    movie_id: int,
    module: str = Query("jav"),
    session: AsyncSession = Depends(get_session),
):
    """忽略推荐"""
    await recommendation_engine.dismiss_recommendation(None, movie_id, session, module)
    return {"status": "ok"}
