"""
系统统计路由

API 端点：
- GET  /api/v1/stats/dashboard - 仪表盘概览
- GET  /api/v1/stats/movies    - 电影统计
- GET  /api/v1/stats/tasks     - 任务统计
- GET  /api/v1/stats/storage   - 存储统计
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.system_models import Task
# Module stats use ModuleDatabase directly

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== API Endpoints =====

@router.get("/dashboard")
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_session),
):
    """仪表盘概览 - 聚合所有模块数据库的统计"""
    from app.db.module_db import ModuleDatabase
    from sqlalchemy import text

    # 汇总所有模块的影片和演员数
    ALL_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub"]
    movie_total = 0
    movie_pending = 0
    movie_completed = 0
    movie_failed = 0
    actor_total = 0
    recent_scraped = 0
    today_scraped = 0
    module_stats = {}

    recent_date = datetime.now() - timedelta(days=7)
    today_start = datetime.now().replace(hour=0, minute=0, second=0)

    for mod_name in ALL_MODULES:
        try:
            mod_db = ModuleDatabase.get_instance(mod_name)
            mod_session = await mod_db.get_session()
            try:
                mc = await mod_session.scalar(text("SELECT COUNT(*) FROM movies")) or 0
                mp = await mod_session.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE status = 'pending'")
                ) or 0
                mok = await mod_session.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE status IN ('completed', 'scraped')")
                ) or 0
                mf = await mod_session.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE status = 'failed'")
                ) or 0
                ac = await mod_session.scalar(text("SELECT COUNT(*) FROM actors")) or 0
                
                movie_total += mc
                movie_pending += mp
                movie_completed += mok
                movie_failed += mf
                actor_total += ac
                module_stats[mod_name] = {"movies": mc, "actors": ac}
            finally:
                await mod_session.close()
        except Exception as e:
            logger.warning(f"仪表盘: 模块 [{mod_name}] 统计失败: {e}")
            module_stats[mod_name] = {"movies": 0, "actors": 0}

    # 任务统计（system.db）
    task_total = await session.scalar(select(func.count(Task.id))) or 0
    task_running = await session.scalar(
        select(func.count(Task.id)).where(Task.status == "running")
    ) or 0
    task_pending = await session.scalar(
        select(func.count(Task.id)).where(Task.status == "pending")
    ) or 0
    task_failed = await session.scalar(
        select(func.count(Task.id)).where(Task.status == "failed")
    ) or 0

    return {
        "movies": {
            "total": movie_total,
            "completed": movie_completed,
            "pending": movie_pending,
            "failed": movie_failed,
        },
        "tasks": {
            "total": task_total,
            "running": task_running,
            "pending": task_pending,
            "failed": task_failed,
        },
        "actors": {
            "total": actor_total,
        },
        "activity": {
            "recent_scraped": recent_scraped,
            "today_scraped": today_scraped,
        },
        "modules": module_stats,
    }


@router.get("/movies")
async def get_movie_stats(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    session: AsyncSession = Depends(get_session),
):
    """
    获取电影统计
    
    - 按状态分布
    - 按来源分布
    - 按日期刮削趋势
    """
    # 按状态分布
    status_query = (
        select(Movie.status, func.count(Movie.id))
        .group_by(Movie.status)
    )
    status_result = await session.execute(status_query)
    status_dist = {row[0]: row[1] for row in status_result.fetchall()}
    
    # 按来源分布
    source_query = (
        select(Movie.source, func.count(Movie.id))
        .where(Movie.source.isnot(None))
        .group_by(Movie.source)
        .order_by(func.count(Movie.id).desc())
        .limit(10)
    )
    source_result = await session.execute(source_query)
    source_dist = [{"source": row[0], "count": row[1]} for row in source_result.fetchall()]
    
    # 按日期刮削趋势
    start_date = datetime.now() - timedelta(days=days)
    date_query = (
        select(
            func.date(Movie.scraped_at).label("date"),
            func.count(Movie.id).label("count")
        )
        .where(Movie.scraped_at >= start_date)
        .group_by(func.date(Movie.scraped_at))
        .order_by(func.date(Movie.scraped_at))
    )
    date_result = await session.execute(date_query)
    trend = [{"date": str(row[0]), "count": row[1]} for row in date_result.fetchall()]
    
    return {
        "status_distribution": status_dist,
        "source_distribution": source_dist,
        "scraping_trend": trend,
    }


@router.get("/tasks")
async def get_task_stats(
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    session: AsyncSession = Depends(get_session),
):
    """
    获取任务统计
    
    - 按类型分布
    - 按状态分布
    - 按日期任务趋势
    """
    # 按类型分布
    type_query = (
        select(Task.type, func.count(Task.id))
        .group_by(Task.type)
    )
    type_result = await session.execute(type_query)
    type_dist = {row[0]: row[1] for row in type_result.fetchall()}
    
    # 按状态分布
    status_query = (
        select(Task.status, func.count(Task.id))
        .group_by(Task.status)
    )
    status_result = await session.execute(status_query)
    status_dist = {row[0]: row[1] for row in status_result.fetchall()}
    
    # 按日期任务趋势
    start_date = datetime.now() - timedelta(days=days)
    date_query = (
        select(
            func.date(Task.created_at).label("date"),
            func.count(Task.id).label("count")
        )
        .where(Task.created_at >= start_date)
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at))
    )
    date_result = await session.execute(date_query)
    trend = [{"date": str(row[0]), "count": row[1]} for row in date_result.fetchall()]
    
    return {
        "type_distribution": type_dist,
        "status_distribution": status_dist,
        "task_trend": trend,
    }


@router.get("/storage")
async def get_storage_stats(
    session: AsyncSession = Depends(get_session),
):
    """
    获取存储统计
    
    - 数据库大小
    - 图片数量
    - NFO 文件数量
    """
    # 统计有封面的电影
    with_cover = await session.scalar(
        select(func.count(Movie.id)).where(Movie.cover_url.isnot(None))
    ) or 0
    
    # 统计有海报的电影
    with_poster = await session.scalar(
        select(func.count(Movie.id)).where(Movie.poster_url.isnot(None))
    ) or 0
    
    # 统计有简介的电影
    with_plot = await session.scalar(
        select(func.count(Movie.id)).where(Movie.plot.isnot(None))
    ) or 0
    
    # 统计有演员的电影
    with_actors_query = (
        select(func.count(func.distinct(MovieActor.movie_id)))
    )
    with_actors = await session.scalar(with_actors_query) or 0
    
    return {
        "images": {
            "with_cover": with_cover,
            "with_poster": with_poster,
        },
        "metadata": {
            "with_plot": with_plot,
            "with_actors": with_actors,
        },
    }


@router.get("/health")
async def get_system_health(
    session: AsyncSession = Depends(get_session),
):
    """
    获取系统健康状态
    
    - 数据库连接
    - 最近错误率
    - 系统负载
    """
    # 数据库连接测试
    try:
        await session.execute(select(1))
        db_healthy = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_healthy = False
    
    # 最近失败率（24小时内）
    recent_date = datetime.now() - timedelta(hours=24)
    recent_tasks = await session.scalar(
        select(func.count(Task.id)).where(Task.created_at >= recent_date)
    ) or 0
    failed_tasks = await session.scalar(
        select(func.count(Task.id)).where(
            Task.created_at >= recent_date,
            Task.status == "failed"
        )
    ) or 0
    
    error_rate = failed_tasks / recent_tasks if recent_tasks > 0 else 0
    
    return {
        "database": {
            "healthy": db_healthy,
        },
        "tasks": {
            "error_rate": error_rate,
            "recent_failed": failed_tasks,
        },
    }