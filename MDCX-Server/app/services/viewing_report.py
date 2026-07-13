"""
AI 观影报告服务

基于 PlayHistory 表生成观影分析报告：
- 总观看时长 / 总观看影片数 / 完成率
- 最常观看的演员 Top N
- 最常观看的标签 / 系列 / 厂商
- 观看时间分布（按小时/星期/月份）
- 评分分布
- 近期观看趋势
- AI 洞察文本（基于规则生成，可对接 LLM 插件）

设计要点：
- 不修改现有 Movie 模型
- 复用 PlayHistory 表（与 user_manager.py 共用）
- 报告生成纯查询，无副作用
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, cast, Date, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    PlayHistory, Movie, MovieActor, Actor, MovieTag, Tag,
    Studio, Series,
)

logger = logging.getLogger(__name__)


# ===== 观影历史记录 =====

async def record_play(
    movie_id: int,
    user_id: Optional[int],
    duration_watched: int,
    progress: float,
    completed: bool,
    total_duration: Optional[int],
    ip_address: Optional[str],
    session: AsyncSession,
) -> None:
    """记录一次播放"""
    # 取 movie_code 冗余存储
    movie = await session.get(Movie, movie_id)
    if movie is None:
        return
    record = PlayHistory(
        user_id=user_id,
        movie_id=movie_id,
        movie_code=movie.code,
        duration_watched=duration_watched,
        total_duration=total_duration or movie.duration,
        progress=progress,
        completed=completed,
        ip_address=ip_address,
    )
    session.add(record)
    await session.commit()


async def list_play_history(
    user_id: Optional[int],
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    movie_id: Optional[int] = None,
) -> dict:
    """查询观影历史"""
    base = select(PlayHistory)
    if user_id is not None:
        base = base.where((PlayHistory.user_id == user_id) | (PlayHistory.user_id.is_(None)))
    if movie_id is not None:
        base = base.where(PlayHistory.movie_id == movie_id)

    # 总数
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # 分页
    stmt = (
        base.order_by(PlayHistory.played_at.desc())
        .limit(limit).offset(offset)
    )
    result = await session.execute(stmt)
    items = []
    for h in result.scalars().all():
        items.append({
            "id": h.id,
            "user_id": h.user_id,
            "movie_id": h.movie_id,
            "movie_code": h.movie_code,
            "duration_watched": h.duration_watched,
            "total_duration": h.total_duration,
            "progress": h.progress,
            "completed": h.completed,
            "played_at": h.played_at.isoformat() if h.played_at else None,
            "ip_address": h.ip_address,
        })
    return {"total": total, "items": items}


# ===== 报告生成 =====

async def generate_report(
    user_id: Optional[int],
    session: AsyncSession,
    days: int = 30,
) -> dict:
    """
    生成观影报告

    Args:
        user_id: 用户 ID，None 表示全部
        days: 统计最近多少天

    Returns:
        报告 dict
    """
    since = datetime.utcnow() - timedelta(days=days)

    base_filter = [
        PlayHistory.played_at >= since,
    ]
    if user_id is not None:
        base_filter.append(
            (PlayHistory.user_id == user_id) | (PlayHistory.user_id.is_(None))
        )

    # ===== 基础统计 =====
    base_query = select(
        func.count(PlayHistory.id).label("play_count"),
        func.coalesce(func.sum(PlayHistory.duration_watched), 0).label("total_duration"),
        func.count(PlayHistory.movie_id.distinct()).label("unique_movies"),
        func.avg(PlayHistory.progress).label("avg_progress"),
    ).where(*base_filter)
    row = (await session.execute(base_query)).one()
    play_count = row.play_count or 0
    total_duration = int(row.total_duration or 0)
    unique_movies = row.unique_movies or 0
    avg_progress = float(row.avg_progress or 0)

    # 完成数
    completed_query = select(func.count(PlayHistory.id)).where(
        *base_filter, PlayHistory.completed.is_(True)
    )
    completed_count = (await session.execute(completed_query)).scalar_one() or 0

    # ===== Top 演员 =====
    actor_stmt = (
        select(
            Actor.name,
            func.count(PlayHistory.id).label("play_count"),
            func.coalesce(func.sum(PlayHistory.duration_watched), 0).label("duration"),
        )
        .join(Movie, PlayHistory.movie_id == Movie.id)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .join(Actor, MovieActor.actor_id == Actor.id)
        .where(*base_filter)
        .group_by(Actor.id, Actor.name)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(10)
    )
    top_actors = [
        {"name": r.name, "play_count": r.play_count, "duration": int(r.duration)}
        for r in (await session.execute(actor_stmt)).all()
    ]

    # ===== Top 标签 =====
    tag_stmt = (
        select(
            Tag.name,
            Tag.is_user,
            func.count(PlayHistory.id).label("play_count"),
        )
        .join(MovieTag, Tag.id == MovieTag.tag_id)
        .join(Movie, MovieTag.movie_id == Movie.id)
        .join(PlayHistory, PlayHistory.movie_id == Movie.id)
        .where(*base_filter)
        .group_by(Tag.id, Tag.name, Tag.is_user)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(15)
    )
    top_tags = [
        {
            "name": r.name,
            "is_user": r.is_user,
            "play_count": r.play_count,
        }
        for r in (await session.execute(tag_stmt)).all()
    ]

    # ===== Top 系列 =====
    series_stmt = (
        select(
            Series.name,
            func.count(PlayHistory.id).label("play_count"),
        )
        .join(Movie, PlayHistory.movie_id == Movie.id)
        .join(Series, Movie.series_id == Series.id)
        .where(*base_filter, Series.id.isnot(None))
        .group_by(Series.id, Series.name)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(10)
    )
    top_series = [
        {"name": r.name, "play_count": r.play_count}
        for r in (await session.execute(series_stmt)).all()
    ]

    # ===== Top 厂商 =====
    studio_stmt = (
        select(
            Studio.name,
            func.count(PlayHistory.id).label("play_count"),
        )
        .join(Movie, PlayHistory.movie_id == Movie.id)
        .join(Studio, Movie.studio_id == Studio.id)
        .where(*base_filter, Studio.id.isnot(None))
        .group_by(Studio.id, Studio.name)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(10)
    )
    top_studios = [
        {"name": r.name, "play_count": r.play_count}
        for r in (await session.execute(studio_stmt)).all()
    ]

    # ===== 时间分布 =====
    hour_dist = await _time_distribution(
        session, base_filter, extract("hour", PlayHistory.played_at), range(24)
    )
    weekday_dist = await _time_distribution(
        session, base_filter, extract("dow", PlayHistory.played_at), range(1, 8)
    )

    # ===== 评分分布 =====
    rating_stmt = (
        select(Movie.rating, func.count(PlayHistory.id).label("cnt"))
        .join(Movie, PlayHistory.movie_id == Movie.id)
        .where(*base_filter, Movie.rating.isnot(None))
        .group_by(Movie.rating)
        .order_by(Movie.rating)
    )
    rating_dist = [
        {"rating": float(r.rating), "count": r.cnt}
        for r in (await session.execute(rating_stmt)).all()
    ]

    # ===== 趋势（按天） =====
    # 修复:SQLite 的 CAST(x AS DATE) 不会截断日期,使用 func.date()
    day_expr = func.date(PlayHistory.played_at).label("day")
    daily_stmt = (
        select(
            day_expr,
            func.count(PlayHistory.id).label("play_count"),
            func.coalesce(func.sum(PlayHistory.duration_watched), 0).label("duration"),
        )
        .where(*base_filter)
        .group_by(day_expr)
        .order_by(day_expr)
    )
    daily_trend = [
        {
            "date": r.day if r.day else None,
            "play_count": r.play_count,
            "duration": int(r.duration),
        }
        for r in (await session.execute(daily_stmt)).all()
    ]

    # ===== AI 洞察文本（规则生成） =====
    insights = _generate_insights(
        play_count=play_count,
        total_duration=total_duration,
        unique_movies=unique_movies,
        completed_count=completed_count,
        avg_progress=avg_progress,
        top_actors=top_actors,
        top_tags=top_tags,
        hour_dist=hour_dist,
        days=days,
    )

    return {
        "period_days": days,
        "since": since.isoformat(),
        "summary": {
            "play_count": play_count,
            "total_duration_seconds": total_duration,
            "total_duration_human": _humanize_duration(total_duration),
            "unique_movies": unique_movies,
            "completed_count": completed_count,
            "completion_rate": round(completed_count / play_count, 2) if play_count else 0,
            "avg_progress": round(avg_progress, 2),
        },
        "top_actors": top_actors,
        "top_tags": top_tags,
        "top_series": top_series,
        "top_studios": top_studios,
        "time_distribution": {
            "by_hour": hour_dist,
            "by_weekday": weekday_dist,
        },
        "rating_distribution": rating_dist,
        "daily_trend": daily_trend,
        "insights": insights,
    }


async def _time_distribution(
    session: AsyncSession,
    base_filter,
    field,
    keys_range,
) -> dict:
    """通用时间分布查询"""
    stmt = (
        select(field.label("k"), func.count(PlayHistory.id).label("cnt"))
        .where(*base_filter)
        .group_by(field)
    )
    rows = (await session.execute(stmt)).all()
    result = {int(r.k) if r.k is not None else -1: r.cnt for r in rows}
    return {str(k): result.get(k, 0) for k in keys_range}


def _humanize_duration(seconds: int) -> str:
    """时长人性化"""
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    remain_minutes = minutes % 60
    if hours < 24:
        return f"{hours} 小时 {remain_minutes} 分钟"
    days = hours // 24
    remain_hours = hours % 24
    return f"{days} 天 {remain_hours} 小时"


def _generate_insights(
    play_count: int,
    total_duration: int,
    unique_movies: int,
    completed_count: int,
    avg_progress: float,
    top_actors: list,
    top_tags: list,
    hour_dist: dict,
    days: int,
) -> list[str]:
    """基于规则生成洞察文本"""
    insights: list[str] = []

    if play_count == 0:
        insights.append(f"最近 {days} 天没有观影记录，开始享受你的影片库吧。")
        return insights

    # 总览
    insights.append(
        f"最近 {days} 天你共观看了 {play_count} 次，"
        f"涉及 {unique_movies} 部不同影片，"
        f"总时长 {_humanize_duration(total_duration)}。"
    )

    # 完成率
    if play_count > 0:
        rate = completed_count / play_count
        if rate >= 0.7:
            insights.append(f"完成率 {rate*100:.0f}%，你倾向于把影片看完。")
        elif rate >= 0.3:
            insights.append(f"完成率 {rate*100:.0f}%，你看完了一部分影片，其余可能只是浏览。")
        else:
            insights.append(f"完成率 {rate*100:.0f}%，你更像在快速浏览而非完整观看。")

    # 偏好演员
    if top_actors:
        top3 = top_actors[:3]
        names = "、".join(a["name"] for a in top3)
        insights.append(f"你最喜欢的演员是 {names}。")

    # 偏好标签
    if top_tags:
        user_tags = [t for t in top_tags if t.get("is_user")]
        if user_tags:
            names = "、".join(t["name"] for t in user_tags[:5])
            insights.append(f"你添加的用户标签中，最常匹配的是：{names}。")
        scraped_tags = [t for t in top_tags if not t.get("is_user")]
        if scraped_tags:
            names = "、".join(t["name"] for t in scraped_tags[:5])
            insights.append(f"抓取标签中你常看的是：{names}。")

    # 观看时段
    if hour_dist:
        try:
            max_hour = max(hour_dist.items(), key=lambda x: x[1] if isinstance(x[1], int) else 0)
            hour = int(max_hour[0])
            if 0 <= hour < 6:
                period = "深夜"
            elif 6 <= hour < 12:
                period = "上午"
            elif 12 <= hour < 18:
                period = "下午"
            else:
                period = "晚上"
            insights.append(f"你最常在 {period}（{hour} 点前后）观看影片。")
        except Exception:
            pass

    # 平均进度
    if avg_progress < 0.3:
        insights.append("平均观看进度较低，你似乎更注重浏览筛选而非完整观看。")
    elif avg_progress > 0.8:
        insights.append("平均观看进度很高，你倾向于沉浸式观影。")

    return insights
