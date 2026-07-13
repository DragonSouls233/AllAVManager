"""演员订阅 + 新片监控路由"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services import actor_subscription as svc

router = APIRouter()


class SubscribeRequest(BaseModel):
    actor_id: int
    notify_new_movie: bool = True
    user_id: Optional[int] = None  # 可选，默认 None（全局订阅）


@router.get("")
async def list_subs(user_id: Optional[int] = None, session: AsyncSession = Depends(get_session)):
    """列出订阅"""
    items = await svc.list_subscriptions(user_id, session)
    return {"items": items}


@router.post("")
async def subscribe_actor(body: SubscribeRequest, session: AsyncSession = Depends(get_session)):
    """订阅演员"""
    try:
        result = await svc.subscribe(
            user_id=body.user_id,
            actor_id=body.actor_id,
            notify_new_movie=body.notify_new_movie,
            session=session,
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{actor_id}")
async def unsubscribe_actor(
    actor_id: int,
    user_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
):
    """取消订阅"""
    success = await svc.unsubscribe(user_id, actor_id, session)
    return {"ok": success}


@router.get("/check/{actor_id}")
async def check_actor(actor_id: int, session: AsyncSession = Depends(get_session)):
    """检查指定演员的新片"""
    new_movies = await svc.check_new_movies_for_actor(actor_id, session)
    return {
        "actor_id": actor_id,
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


@router.post("/check-all")
async def check_all(session: AsyncSession = Depends(get_session)):
    """检测所有订阅的新片"""
    result = await svc.check_all_subscriptions(session)
    return result


@router.get("/new-movies")
async def list_new_movies(
    user_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """列出订阅演员的新片"""
    items = await svc.list_new_movies_for_subscription(user_id, session, limit=limit)
    return {"items": items}
