"""
演员订阅 + 新片监控服务

提供：
- 订阅/取消订阅演员
- 列出订阅（含新片增量）
- 检测新片：对比 last_movie_count 与当前影片数
- 新片中字标记：is_chinese + upgrade_candidate（中字新片且本地有旧版，2026-10-25）
- 触发 Webhook 通知（订阅了 notify_new_movie 的）

设计要点：
- 不修改现有 Actor 模型
- 用户级订阅（user_id）+ 全局订阅（user_id=NULL）
- 检测可由后台任务定期触发，也可手动调用
- upgrade_candidate 判定：新片 is_chinese=True，且同 base 番号存在
  **磁盘上真实存在**的非中文版（os.path.isfile 实测，不是只看库记录）
  ——对应「出了中字版可以替换本地旧版」的场景
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.wants import base_code
from app.utils.module_helper import get_module_model, get_module_session

logger = logging.getLogger(__name__)


def _get_subs_models(module: str):
    """获取演员订阅所需的模块模型"""
    return {
        "Actor": get_module_model(module, "actor"),
        "ActorSubscription": get_module_model(module, "actor_subscription"),
        "MovieActor": get_module_model(module, "movie_actor"),
        "Movie": get_module_model(module, "movie"),
    }


# ===== 订阅 CRUD =====

async def list_subscriptions(
    user_id: Optional[int],
    session: AsyncSession,
    module: str = "jav",
) -> list[dict]:
    """列出用户的所有订阅（含演员信息 + 新片数）"""
    Actor = get_module_model(module, "actor")
    ActorSubscription = get_module_model(module, "actor_subscription")
    MovieActor = get_module_model(module, "movie_actor")
    stmt = (
        select(
            ActorSubscription,
            Actor.name,
            Actor.avatar_url,
        )
        .join(Actor, ActorSubscription.actor_id == Actor.id)
        .where(
            (ActorSubscription.user_id == user_id)
            | (ActorSubscription.user_id.is_(None))
        )
        .order_by(ActorSubscription.created_at.desc())
    )
    result = await session.execute(stmt)
    items = []
    for sub, name, avatar in result.all():
        # 当前影片数
        cnt_stmt = select(func.count(MovieActor.id)).where(MovieActor.actor_id == sub.actor_id)
        current_count = (await session.execute(cnt_stmt)).scalar_one()
        new_count = max(0, current_count - sub.last_movie_count)
        items.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "actor_id": sub.actor_id,
            "actor_name": name,
            "actor_avatar": avatar,
            "notify_new_movie": sub.notify_new_movie,
            "last_checked_at": sub.last_checked_at.isoformat() if sub.last_checked_at else None,
            "last_movie_count": sub.last_movie_count,
            "current_movie_count": current_count,
            "new_movie_count": new_count,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })
    return items


async def subscribe(
    user_id: Optional[int],
    actor_id: int,
    notify_new_movie: bool,
    session: AsyncSession,
    module: str = "jav",
) -> dict:
    """订阅演员（如已订阅则更新配置）"""
    ActorSubscription = get_module_model(module, "actor_subscription")
    MovieActor = get_module_model(module, "movie_actor")
    # 查询是否已存在（user_id 为 NULL 时用 is_(None)）
    if user_id is None:
        stmt = select(ActorSubscription).where(
            and_(
                ActorSubscription.actor_id == actor_id,
                ActorSubscription.user_id.is_(None),
            )
        )
    else:
        stmt = select(ActorSubscription).where(
            and_(
                ActorSubscription.actor_id == actor_id,
                ActorSubscription.user_id == user_id,
            )
        )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    # 当前影片数
    cnt_stmt = select(func.count(MovieActor.id)).where(MovieActor.actor_id == actor_id)
    current_count = (await session.execute(cnt_stmt)).scalar_one()

    if existing:
        existing.notify_new_movie = notify_new_movie
        sub = existing
    else:
        sub = ActorSubscription(
            user_id=user_id,
            actor_id=actor_id,
            notify_new_movie=notify_new_movie,
            last_movie_count=current_count,
        )
        session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return {
        "id": sub.id,
        "user_id": sub.user_id,
        "actor_id": sub.actor_id,
        "notify_new_movie": sub.notify_new_movie,
        "last_movie_count": sub.last_movie_count,
        "current_movie_count": current_count,
    }


async def unsubscribe(
    user_id: Optional[int],
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
) -> bool:
    """取消订阅"""
    ActorSubscription = get_module_model(module, "actor_subscription")
    if user_id is None:
        stmt = select(ActorSubscription).where(
            and_(
                ActorSubscription.actor_id == actor_id,
                ActorSubscription.user_id.is_(None),
            )
        )
    else:
        stmt = select(ActorSubscription).where(
            and_(
                ActorSubscription.actor_id == actor_id,
                ActorSubscription.user_id == user_id,
            )
        )
    sub = (await session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        return False
    await session.delete(sub)
    await session.commit()
    return True


async def is_subscribed(
    user_id: Optional[int],
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
) -> bool:
    """检查是否已订阅"""
    ActorSubscription = get_module_model(module, "actor_subscription")
    if user_id is None:
        stmt = select(ActorSubscription.id).where(
            and_(
                ActorSubscription.actor_id == actor_id,
                ActorSubscription.user_id.is_(None),
            )
        )
    else:
        stmt = select(ActorSubscription.id).where(
            and_(
                ActorSubscription.actor_id == actor_id,
                ActorSubscription.user_id == user_id,
            )
        )
    return (await session.execute(stmt)).first() is not None


# ===== 新片检测 =====

def _entry_field(entry, key: str, default=None):
    """从 ORM 对象或 dict 取字段（新片列表两种形态都要支持）"""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


async def annotate_upgrade_flags(
    session: AsyncSession,
    Movie,
    entries: list,
) -> dict:
    """给新片列表标注中字/可替换标记（只读，不写库）。

    Args:
        entries: 新片列表，ORM Movie 或 dict 均可（需有 id/code/is_chinese）
    Returns:
        {movie_id: {"is_chinese": bool, "upgrade_candidate": bool}}
        - is_chinese: 该片是中字版（-C 后缀；pornhub 等无此概念的模块恒 False）
        - upgrade_candidate: 中字片且同 base 番号有**磁盘上真实存在**的非中文版

    实现：一次 LIKE 批量查所有 base 候选，Python 侧精确 base 比对 + os.path.isfile
    实测（口径：文件必须在磁盘上，库里记着但文件没了不算旧版）。
    """
    flags: dict[int, dict] = {}
    if not entries:
        return flags

    # is_chinese 只有 JAV/FC2 模型有（中字是 -C 后缀概念）；没有该列的模块
    # （pornhub/uncensored/chinese/western）不算中字升级，直接返回基础标记
    if not hasattr(Movie, "is_chinese"):
        for e in entries:
            flags[_entry_field(e, "id")] = {"is_chinese": False, "upgrade_candidate": False}
        return flags

    # 中字新片的 base 番号集合（只对中字片算 upgrade）
    chinese_entries = []
    bases: set[str] = set()
    for e in entries:
        is_cn = bool(_entry_field(e, "is_chinese", False))
        eid = _entry_field(e, "id")
        flags[eid] = {"is_chinese": is_cn, "upgrade_candidate": False}
        if is_cn:
            code = _entry_field(e, "code") or ""
            bc = base_code(code)
            if bc:
                chinese_entries.append((eid, bc))
                bases.add(bc)

    if not bases:
        return flags

    # 批量查同 base 的影片（upper+LIKE 前缀；SQLite ASCII 大小写转换对番号够用）
    conds = [func.upper(Movie.code).like(bc + "%") for bc in bases]
    rows = (await session.execute(
        select(Movie.code, Movie.file_path, Movie.is_chinese).where(or_(*conds))
    )).all()

    # 有本地旧版（磁盘实测）的 base 集合
    local_old_bases: set[str] = set()
    for code, file_path, is_cn in rows:
        if not code or is_cn or not file_path:
            continue
        bc = base_code(code)
        if bc in bases and os.path.isfile(str(file_path)):
            local_old_bases.add(bc)

    for eid, bc in chinese_entries:
        if bc in local_old_bases:
            flags[eid]["upgrade_candidate"] = True
    return flags


async def check_new_movies_for_actor(
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
) -> list[Movie]:
    """
    检查某演员的新片（自上次检查以来增加的影片）

    会更新 last_checked_at 和 last_movie_count。
    返回新片列表（最近添加的 N 部，N = current - last）。
    """
    Actor = get_module_model(module, "actor")
    ActorSubscription = get_module_model(module, "actor_subscription")
    MovieActor = get_module_model(module, "movie_actor")
    Movie = get_module_model(module, "movie")
    # 找到该演员的所有订阅（任意用户 + 全局）
    stmt = select(ActorSubscription).where(ActorSubscription.actor_id == actor_id)
    subs = (await session.execute(stmt)).scalars().all()
    if not subs:
        return []

    # 当前影片数
    cnt_stmt = select(func.count(MovieActor.id)).where(MovieActor.actor_id == actor_id)
    current_count = (await session.execute(cnt_stmt)).scalar_one()

    # 取最早的 last_movie_count 作为基线
    baseline = min((s.last_movie_count for s in subs), default=current_count)
    new_count = max(0, current_count - baseline)

    # 取最近 new_count 部影片
    new_movies: list[Movie] = []
    if new_count > 0:
        movies_stmt = (
            select(Movie)
            .join(MovieActor, Movie.id == MovieActor.movie_id)
            .where(MovieActor.actor_id == actor_id)
            .order_by(Movie.created_at.desc())
            .limit(new_count)
        )
        new_movies = list((await session.execute(movies_stmt)).scalars().all())

    # 更新所有订阅
    now = datetime.utcnow()
    for sub in subs:
        sub.last_checked_at = now
        sub.last_movie_count = current_count
    await session.commit()

    # 标注中字/可替换（commit 后挂实例属性，不持久化；路由层 getattr 读取）
    if new_movies:
        flags = await annotate_upgrade_flags(session, Movie, new_movies)
        for m in new_movies:
            f = flags.get(m.id) or {}
            m.is_chinese_flag = bool(f.get("is_chinese", False))
            m.upgrade_candidate = bool(f.get("upgrade_candidate", False))

    return new_movies


async def check_all_subscriptions(session: AsyncSession, module: str = "jav") -> dict:
    """
    检测所有订阅演员的新片，触发 Webhook 通知

    Returns:
        统计信息 {checked, with_new, total_new, notified}
    """
    Actor = get_module_model(module, "actor")
    ActorSubscription = get_module_model(module, "actor_subscription")
    MovieActor = get_module_model(module, "movie_actor")
    Movie = get_module_model(module, "movie")
    # 找到所有订阅过的演员
    stmt = select(ActorSubscription.actor_id).distinct()
    actor_ids = (await session.execute(stmt)).scalars().all()

    checked = 0
    with_new = 0
    total_new = 0
    notified = 0

    for actor_id in actor_ids:
        checked += 1
        try:
            new_movies = await check_new_movies_for_actor(actor_id, session)
            if not new_movies:
                continue
            with_new += 1
            total_new += len(new_movies)

            # 取演员名
            actor = await session.get(Actor, actor_id)
            actor_name = actor.name if actor else f"actor#{actor_id}"

            # 触发 Webhook 通知
            try:
                from app.services.webhook_manager import notify_event
                movie_list = "\n".join(
                    f"• {m.code} - {m.title or '未命名'}" for m in new_movies[:10]
                )
                await notify_event(
                    event="custom",
                    title=f"演员 {actor_name} 有 {len(new_movies)} 部新片",
                    message=movie_list,
                    level="success",
                    data={
                        "actor_id": actor_id,
                        "actor_name": actor_name,
                        "new_movie_ids": [m.id for m in new_movies],
                        "new_movie_codes": [m.code for m in new_movies],
                    },
                )
                notified += 1
            except Exception as e:
                logger.error(f"Webhook 通知失败: {e}")
        except Exception as e:
            logger.error(f"检测演员 {actor_id} 新片失败: {e}")

    return {
        "checked": checked,
        "with_new": with_new,
        "total_new": total_new,
        "notified": notified,
    }


# ===== 新片列表查询 =====

async def list_new_movies_for_subscription(
    user_id: Optional[int],
    session: AsyncSession,
    limit: int = 50,
    module: str = "jav",
) -> list[dict]:
    """
    列出用户订阅演员的新片（按 release_date 倒序）

    Returns:
        新片列表（含演员信息）
    """
    Actor = get_module_model(module, "actor")
    ActorSubscription = get_module_model(module, "actor_subscription")
    MovieActor = get_module_model(module, "movie_actor")
    Movie = get_module_model(module, "movie")
    # 找到用户订阅的演员
    if user_id is None:
        stmt = select(ActorSubscription.actor_id).distinct()
    else:
        stmt = select(ActorSubscription.actor_id).where(
            (ActorSubscription.user_id == user_id)
            | (ActorSubscription.user_id.is_(None))
        ).distinct()
    actor_ids = (await session.execute(stmt)).scalars().all()
    if not actor_ids:
        return []

    # 查询这些演员的影片，按发布日期倒序
    has_cn = hasattr(Movie, "is_chinese")
    select_cols = [
        Movie.id, Movie.code, Movie.title, Movie.cover_url,
        Movie.release_date, Movie.created_at,
        Actor.name.label("actor_name"),
    ]
    if has_cn:
        select_cols.append(Movie.is_chinese)
    movies_stmt = (
        select(*select_cols)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .join(Actor, MovieActor.actor_id == Actor.id)
        .where(MovieActor.actor_id.in_(actor_ids))
        .order_by(Movie.release_date.desc().nullslast(), Movie.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(movies_stmt)).all()

    # 组装 + 中字/可替换标注（is_chinese 列没有的模块恒 False）
    entries = [
        {
            "id": r.id, "code": r.code, "title": r.title,
            "cover_url": r.cover_url, "release_date": r.release_date,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor_name": r.actor_name,
            "is_chinese": bool(r[-1]) if has_cn else False,
        }
        for r in rows
    ]
    flags = await annotate_upgrade_flags(session, Movie, entries)
    for e in entries:
        f = flags.get(e["id"]) or {}
        e["is_chinese"] = bool(f.get("is_chinese", False))
        e["upgrade_candidate"] = bool(f.get("upgrade_candidate", False))
    return entries
