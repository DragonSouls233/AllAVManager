"""演员订阅 + 新片监控路由"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import actor_subscription as svc
from app.utils.module_helper import get_module_session

router = APIRouter()


class SubscribeRequest(BaseModel):
    actor_id: int
    notify_new_movie: bool = True
    user_id: Optional[int] = None  # 可选，默认 None（全局订阅）


async def _subs_session(module: str = "jav") -> AsyncSession:
    """依赖：订阅数据按模块分库存放（jav.db / fc2.db ...），必须用模块会话而非系统库会话。

    路由原先注入的是 app.db.database.get_session()（系统库 system.db），
    而 actor_subscriptions 表定义在各模块的 Base（JAV_BASE 等）元数据里，
    挂在模块库（如 jav.db）中。用系统库会话查询会直接报 no such table。
    """
    return await get_module_session(module)


@router.get("")
async def list_subs(
    user_id: Optional[int] = None,
    module: str = "jav",
    session: AsyncSession = Depends(_subs_session),
):
    """列出订阅"""
    items = await svc.list_subscriptions(user_id, session, module=module)
    return {"items": items}


@router.post("")
async def subscribe_actor(
    body: SubscribeRequest,
    module: str = "jav",
    session: AsyncSession = Depends(_subs_session),
):
    """订阅演员"""
    try:
        result = await svc.subscribe(
            user_id=body.user_id,
            actor_id=body.actor_id,
            notify_new_movie=body.notify_new_movie,
            session=session,
            module=module,
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{actor_id}")
async def unsubscribe_actor(
    actor_id: int,
    user_id: Optional[int] = None,
    module: str = "jav",
    session: AsyncSession = Depends(_subs_session),
):
    """取消订阅"""
    success = await svc.unsubscribe(user_id, actor_id, session, module=module)
    return {"ok": success}


@router.get("/check/{actor_id}")
async def check_actor(
    actor_id: int,
    module: str = "jav",
    session: AsyncSession = Depends(_subs_session),
):
    """检查指定演员的新片"""
    new_movies = await svc.check_new_movies_for_actor(actor_id, session, module=module)
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
async def check_all(
    module: str = "jav",
    session: AsyncSession = Depends(_subs_session),
):
    """检测所有订阅的新片"""
    result = await svc.check_all_subscriptions(session, module=module)
    return result


@router.get("/new-movies")
async def list_new_movies(
    user_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    module: str = "jav",
    session: AsyncSession = Depends(_subs_session),
):
    """列出订阅演员的新片"""
    items = await svc.list_new_movies_for_subscription(user_id, session, limit=limit, module=module)
    return {"items": items}
