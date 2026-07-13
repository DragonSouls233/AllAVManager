"""
系列订阅 + 新片监控服务

提供：
- 订阅/取消订阅系列
- 列出订阅（含新片增量）
- 检测新片：对比 last_movie_count 与当前影片数
- 触发 Webhook 通知（订阅了 notify_new_movie 的）
- 自动下载配置（auto_download / preferred_quality）

设计要点（参考 actor_subscription.py 风格）：
- 不修改现有 Series 模型
- 用户级订阅（user_id）+ 全局订阅（user_id=NULL）
- 检测可由后台任务定期触发，也可手动调用
- 全异步，函数式风格
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Movie, Series, SeriesSubscription,
)

logger = logging.getLogger(__name__)


# ===== 订阅 CRUD =====

async def list_series_subscriptions(
    user_id: Optional[int],
    session: AsyncSession,
) -> list[dict]:
    """列出用户的所有系列订阅（含系列信息 + 新片数）"""
    stmt = (
        select(
            SeriesSubscription,
            Series.name,
        )
        .join(Series, SeriesSubscription.series_id == Series.id)
        .where(
            (SeriesSubscription.user_id == user_id)
            | (SeriesSubscription.user_id.is_(None))
        )
        .order_by(SeriesSubscription.created_at.desc())
    )
    result = await session.execute(stmt)
    items = []
    for sub, name in result.all():
        # 当前影片数
        cnt_stmt = select(func.count(Movie.id)).where(Movie.series_id == sub.series_id)
        current_count = (await session.execute(cnt_stmt)).scalar_one()
        new_count = max(0, current_count - sub.last_movie_count)
        items.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "series_id": sub.series_id,
            "series_name": name,
            "notify_new_movie": sub.notify_new_movie,
            "auto_download": sub.auto_download,
            "preferred_quality": sub.preferred_quality,
            "last_checked_at": sub.last_checked_at.isoformat() if sub.last_checked_at else None,
            "last_movie_count": sub.last_movie_count,
            "current_movie_count": current_count,
            "new_movie_count": new_count,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })
    return items


async def subscribe_series(
    user_id: Optional[int],
    series_id: int,
    notify_new_movie: bool,
    auto_download: bool,
    preferred_quality: str,
    session: AsyncSession,
) -> dict:
    """订阅系列（如已订阅则更新配置）"""
    # 查询是否已存在（user_id 为 NULL 时用 is_(None)）
    if user_id is None:
        stmt = select(SeriesSubscription).where(
            and_(
                SeriesSubscription.series_id == series_id,
                SeriesSubscription.user_id.is_(None),
            )
        )
    else:
        stmt = select(SeriesSubscription).where(
            and_(
                SeriesSubscription.series_id == series_id,
                SeriesSubscription.user_id == user_id,
            )
        )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    # 当前影片数
    cnt_stmt = select(func.count(Movie.id)).where(Movie.series_id == series_id)
    current_count = (await session.execute(cnt_stmt)).scalar_one()

    if existing:
        existing.notify_new_movie = notify_new_movie
        existing.auto_download = auto_download
        existing.preferred_quality = preferred_quality
        sub = existing
    else:
        sub = SeriesSubscription(
            user_id=user_id,
            series_id=series_id,
            notify_new_movie=notify_new_movie,
            auto_download=auto_download,
            preferred_quality=preferred_quality,
            last_movie_count=current_count,
        )
        session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return {
        "id": sub.id,
        "user_id": sub.user_id,
        "series_id": sub.series_id,
        "notify_new_movie": sub.notify_new_movie,
        "auto_download": sub.auto_download,
        "preferred_quality": sub.preferred_quality,
        "last_movie_count": sub.last_movie_count,
        "current_movie_count": current_count,
    }


async def unsubscribe_series(
    user_id: Optional[int],
    series_id: int,
    session: AsyncSession,
) -> bool:
    """取消订阅"""
    if user_id is None:
        stmt = select(SeriesSubscription).where(
            and_(
                SeriesSubscription.series_id == series_id,
                SeriesSubscription.user_id.is_(None),
            )
        )
    else:
        stmt = select(SeriesSubscription).where(
            and_(
                SeriesSubscription.series_id == series_id,
                SeriesSubscription.user_id == user_id,
            )
        )
    sub = (await session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        return False
    await session.delete(sub)
    await session.commit()
    return True


async def is_series_subscribed(
    user_id: Optional[int],
    series_id: int,
    session: AsyncSession,
) -> bool:
    """检查是否已订阅"""
    if user_id is None:
        stmt = select(SeriesSubscription.id).where(
            and_(
                SeriesSubscription.series_id == series_id,
                SeriesSubscription.user_id.is_(None),
            )
        )
    else:
        stmt = select(SeriesSubscription.id).where(
            and_(
                SeriesSubscription.series_id == series_id,
                SeriesSubscription.user_id == user_id,
            )
        )
    return (await session.execute(stmt)).first() is not None


# ===== 新片检测 =====

async def check_new_movies_for_series(
    series_id: int,
    session: AsyncSession,
) -> list[Movie]:
    """
    检查某系列的新片（自上次检查以来增加的影片）

    会更新 last_checked_at 和 last_movie_count。
    返回新片列表（最近添加的 N 部，N = current - last）。
    """
    # 找到该系列的所有订阅（任意用户 + 全局）
    stmt = select(SeriesSubscription).where(SeriesSubscription.series_id == series_id)
    subs = (await session.execute(stmt)).scalars().all()
    if not subs:
        return []

    # 当前影片数
    cnt_stmt = select(func.count(Movie.id)).where(Movie.series_id == series_id)
    current_count = (await session.execute(cnt_stmt)).scalar_one()

    # 取最早的 last_movie_count 作为基线
    baseline = min((s.last_movie_count for s in subs), default=current_count)
    new_count = max(0, current_count - baseline)

    # 取最近 new_count 部影片
    new_movies: list[Movie] = []
    if new_count > 0:
        movies_stmt = (
            select(Movie)
            .where(Movie.series_id == series_id)
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

    return new_movies


async def check_all_series_subscriptions(session: AsyncSession) -> dict:
    """
    检测所有订阅系列的新片，触发 Webhook 通知

    Returns:
        统计信息 {checked, with_new, total_new, notified}
    """
    # 找到所有订阅过的系列
    stmt = select(SeriesSubscription.series_id).distinct()
    series_ids = (await session.execute(stmt)).scalars().all()

    checked = 0
    with_new = 0
    total_new = 0
    notified = 0

    for series_id in series_ids:
        checked += 1
        try:
            new_movies = await check_new_movies_for_series(series_id, session)
            if not new_movies:
                continue
            with_new += 1
            total_new += len(new_movies)

            # 取系列名
            series = await session.get(Series, series_id)
            series_name = series.name if series else f"series#{series_id}"

            # 触发 Webhook 通知
            try:
                from app.services.webhook_manager import notify_event
                movie_list = "\n".join(
                    f"• {m.code} - {m.title or '未命名'}" for m in new_movies[:10]
                )
                await notify_event(
                    event="custom",
                    title=f"系列 {series_name} 有 {len(new_movies)} 部新片",
                    message=movie_list,
                    level="success",
                    data={
                        "series_id": series_id,
                        "series_name": series_name,
                        "new_movie_ids": [m.id for m in new_movies],
                        "new_movie_codes": [m.code for m in new_movies],
                    },
                )
                notified += 1
            except Exception as e:
                logger.error(f"Webhook 通知失败: {e}")
        except Exception as e:
            logger.error(f"检测系列 {series_id} 新片失败: {e}")

    return {
        "checked": checked,
        "with_new": with_new,
        "total_new": total_new,
        "notified": notified,
    }


# ===== 新片列表查询 =====

async def list_new_movies_for_series_subscription(
    user_id: Optional[int],
    session: AsyncSession,
    limit: int = 50,
) -> list[dict]:
    """
    列出用户订阅系列的新片（按 release_date 倒序）

    Returns:
        新片列表（含系列信息）
    """
    # 找到用户订阅的系列
    if user_id is None:
        stmt = select(SeriesSubscription.series_id).distinct()
    else:
        stmt = select(SeriesSubscription.series_id).where(
            (SeriesSubscription.user_id == user_id)
            | (SeriesSubscription.user_id.is_(None))
        ).distinct()
    series_ids = (await session.execute(stmt)).scalars().all()
    if not series_ids:
        return []

    # 查询这些系列的影片，按发布日期倒序
    movies_stmt = (
        select(
            Movie.id, Movie.code, Movie.title, Movie.cover_url,
            Movie.release_date, Movie.created_at,
            Series.name.label("series_name"),
        )
        .join(Series, Movie.series_id == Series.id)
        .where(Movie.series_id.in_(series_ids))
        .order_by(Movie.release_date.desc().nullslast(), Movie.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(movies_stmt)
    return [
        {
            "id": row.id,
            "code": row.code,
            "title": row.title,
            "cover_url": row.cover_url,
            "release_date": row.release_date,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "series_name": row.series_name,
        }
        for row in result.all()
    ]
