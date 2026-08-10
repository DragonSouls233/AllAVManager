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
    ALL_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub", "anime"]
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
            async with mod_db.session_scope() as mod_session:
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
    获取电影统计（跨全部模块聚合）

    - 按状态分布
    - 按来源分布
    - 按日期刮削趋势
    """
    from app.db.module_db import ModuleDatabase
    from sqlalchemy import text

    ALL_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub", "anime"]
    status_dist: dict = {}
    source_counter: dict = {}
    trend: dict = {}

    start_date = datetime.now() - timedelta(days=days)
    for mod in ALL_MODULES:
        try:
            mod_db = ModuleDatabase.get_instance(mod)
            async with mod_db.session_scope() as ms:
                rows = (await ms.execute(
                    text("SELECT status, COUNT(*) FROM movies GROUP BY status")
                )).fetchall()
                for status, cnt in rows:
                    status_dist[status] = status_dist.get(status, 0) + cnt

                rows = (await ms.execute(
                    text("SELECT source, COUNT(*) FROM movies WHERE source IS NOT NULL GROUP BY source")
                )).fetchall()
                for src, cnt in rows:
                    source_counter[src] = source_counter.get(src, 0) + cnt

                rows = (await ms.execute(
                    text(
                        "SELECT date(scraped_at), COUNT(*) FROM movies "
                        "WHERE scraped_at >= :sd GROUP BY date(scraped_at)"
                    ),
                    {"sd": start_date},
                )).fetchall()
                for d, cnt in rows:
                    key = str(d)
                    trend[key] = trend.get(key, 0) + cnt
        except Exception as e:
            logger.warning(f"stats/movies 模块[{mod}]统计失败: {e}")

    source_dist = sorted(
        [{"source": k, "count": v} for k, v in source_counter.items()],
        key=lambda x: -x["count"],
    )[:10]
    trend_list = [{"date": k, "count": v} for k, v in sorted(trend.items())]

    return {
        "status_distribution": status_dist,
        "source_distribution": source_dist,
        "scraping_trend": trend_list,
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
    获取存储统计（跨全部模块聚合）

    - 数据库大小
    - 图片数量
    - NFO 文件数量
    """
    from app.db.module_db import ModuleDatabase
    from sqlalchemy import text

    ALL_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub", "anime"]
    with_cover = with_poster = with_plot = with_actors = 0
    for mod in ALL_MODULES:
        try:
            mod_db = ModuleDatabase.get_instance(mod)
            async with mod_db.session_scope() as ms:
                with_cover += await ms.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE cover_url IS NOT NULL")
                ) or 0
                with_poster += await ms.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE poster_url IS NOT NULL")
                ) or 0
                with_plot += await ms.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE plot IS NOT NULL")
                ) or 0
                # movie_actors 关联表全模块为空，按 movies.actor 文本非空统计有演员的影片
                with_actors += await ms.scalar(
                    text("SELECT COUNT(*) FROM movies WHERE actor IS NOT NULL AND actor != ''")
                ) or 0
        except Exception as e:
            logger.warning(f"stats/storage 模块[{mod}]统计失败: {e}")

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