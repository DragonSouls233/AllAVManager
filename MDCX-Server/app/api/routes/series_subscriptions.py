"""系列订阅 + 新片监控路由（参考现有 subscriptions.py 风格）"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services import series_subscription as svc

router = APIRouter()


class SubscribeSeriesRequest(BaseModel):
    series_id: int
    notify_new_movie: bool = True
    auto_download: bool = False
    preferred_quality: str = "1080p"
    user_id: Optional[int] = None  # 可选，默认 None（全局订阅）


@router.get("")
async def list_subs(user_id: Optional[int] = None, session: AsyncSession = Depends(get_session)):
    """列出系列订阅"""
    items = await svc.list_series_subscriptions(user_id, session)
    return {"items": items}


@router.post("")
async def subscribe_series(body: SubscribeSeriesRequest, session: AsyncSession = Depends(get_session)):
    """订阅系列"""
    try:
        result = await svc.subscribe_series(
            user_id=body.user_id,
            series_id=body.series_id,
            notify_new_movie=body.notify_new_movie,
            auto_download=body.auto_download,
            preferred_quality=body.preferred_quality,
            session=session,
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{series_id}")
async def unsubscribe_series(
    series_id: int,
    user_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
):
    """取消订阅"""
    success = await svc.unsubscribe_series(user_id, series_id, session)
    return {"ok": success}


@router.get("/check/{series_id}")
async def check_series(series_id: int, session: AsyncSession = Depends(get_session)):
    """检查指定系列的新片"""
    new_movies = await svc.check_new_movies_for_series(series_id, session)
    return {
        "series_id": series_id,
        "new_count": len(new_movies),
        "new_movies": [
            {
                "id": m.id,
                "code": m.code,
                "title": m.title,
                "release_date": m.release_date,
                "cover_url": m.cover_url,
            }
            for m in new_movies
        ],
    }


@router.post("/check")
async def check_all(session: AsyncSession = Depends(get_session)):
    """手动触发检测所有系列订阅的新片"""
    result = await svc.check_all_series_subscriptions(session)
    return result


@router.get("/new-movies")
async def list_new_movies(
    user_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """列出订阅系列的新片"""
    items = await svc.list_new_movies_for_series_subscription(user_id, session, limit=limit)
    return {"items": items}
