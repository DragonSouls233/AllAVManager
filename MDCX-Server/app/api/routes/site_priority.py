"""站点优先级可视化路由

聚合多源数据，为前端拖拽排序组件提供完整可视化数据：
- 站点基本信息（名称、显示名、base_url、启用状态、当前优先级）
- 最近测速结果（直连 + 代理）
- 刮削统计（影片数、占比）
- 字段覆盖能力（哪些字段该站点最擅长提供，用于字段级合并参考）

参考 PornBoss-mdcx 的字段级合并策略与可视化设计。
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.crawlers import _test_url, _ping_one_crawler
from app.config.manager import get_config_manager
from app.crawlers.provider import CrawlerProvider
from app.db.database import get_session
from app.db.models import Movie, Setting

logger = logging.getLogger(__name__)

router = APIRouter()


class SitePriorityItem(BaseModel):
    """站点优先级可视化条目"""
    name: str
    display_name: str
    base_url: str
    enabled: bool
    priority: int
    supported_types: list[str] = []
    description: Optional[str] = None
    # 刮削统计
    scraped_count: int = 0
    scraped_percent: float = 0.0
    # 最近测速
    last_ping: Optional[dict] = None
    # 字段覆盖能力评分（0-100，基于 supported_types 与历史成功率粗略估算）
    field_coverage_score: int = 0


class SitePriorityVisualization(BaseModel):
    """站点优先级可视化数据"""
    items: list[SitePriorityItem]
    total_movies: int
    proxy_enabled: bool


class PriorityOrderUpdate(BaseModel):
    """优先级顺序更新请求"""
    order: list[str]  # 站点名列表，按从高到低排序


@router.get("/visualization", response_model=SitePriorityVisualization)
async def get_priority_visualization(
    session: AsyncSession = Depends(get_session),
):
    """获取站点优先级可视化数据（聚合优先级 + 测速 + 统计）"""
    config = get_config_manager().config
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()
    proxy_enabled = bool(proxy_url)

    provider = CrawlerProvider()
    crawlers = provider.get_all()

    # 1. 批量读取站点配置（启用状态、优先级）
    setting_keys = []
    for name in crawlers:
        setting_keys.extend([f"crawler_{name}_enabled", f"crawler_{name}_priority"])
    settings = {}
    if setting_keys:
        result = await session.execute(
            select(Setting).where(Setting.key.in_(setting_keys))
        )
        for row in result.scalars().all():
            settings[row.key] = row.value

    # 2. 各站点刮削数量统计
    count_query = (
        select(Movie.source, func.count(Movie.id).label("cnt"))
        .where(Movie.source.isnot(None))
        .group_by(Movie.source)
    )
    count_result = await session.execute(count_query)
    source_counts = {row[0]: row[1] for row in count_result.fetchall()}
    total_movies = sum(source_counts.values())

    # 3. 构建可视化条目
    items: list[SitePriorityItem] = []
    for name, crawler in crawlers.items():
        enabled_str = settings.get(f"crawler_{name}_enabled")
        priority_str = settings.get(f"crawler_{name}_priority")

        enabled = enabled_str != "false" if enabled_str else True
        priority = int(priority_str) if priority_str else getattr(crawler, "priority", 5)
        supported_types = getattr(crawler, "supported_types", []) or []
        base_url = getattr(crawler, "base_url", "") or ""

        scraped_count = source_counts.get(name, 0)
        scraped_percent = (
            round(scraped_count * 100.0 / total_movies, 2) if total_movies else 0.0
        )

        # 字段覆盖能力评分（基于 supported_types 数量 + 启用状态）
        field_coverage_score = min(100, len(supported_types) * 15 + (10 if enabled else 0))

        items.append(SitePriorityItem(
            name=name,
            display_name=getattr(crawler, "display_name", name),
            base_url=base_url,
            enabled=enabled,
            priority=priority,
            supported_types=supported_types,
            description=getattr(crawler, "description", None),
            scraped_count=scraped_count,
            scraped_percent=scraped_percent,
            last_ping=None,
            field_coverage_score=field_coverage_score,
        ))

    # 4. 按优先级降序排列
    items.sort(key=lambda x: x.priority, reverse=True)

    return SitePriorityVisualization(
        items=items,
        total_movies=total_movies,
        proxy_enabled=proxy_enabled,
    )


@router.post("/visualization/ping-all")
async def ping_all_for_visualization():
    """对可视化列表中所有站点执行测速（直连 + 代理），返回最新数据"""
    config = get_config_manager().config
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()
    proxy_enabled = bool(proxy_url)

    provider = CrawlerProvider()
    crawlers = provider.get_all()

    tasks = []
    for name, crawler in crawlers.items():
        base_url = getattr(crawler, "base_url", "") or ""
        tasks.append(_ping_one_crawler(name, base_url, proxy_url, proxy_enabled))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    final_results = []
    for i, r in enumerate(results):
        name = list(crawlers.keys())[i]
        if isinstance(r, Exception):
            final_results.append({
                "name": name,
                "url": "",
                "direct": None,
                "proxy": None,
                "error": str(r),
            })
        else:
            final_results.append({
                "name": r.name,
                "url": r.url,
                "direct": r.direct,
                "proxy": r.proxy,
            })

    return {
        "results": final_results,
        "proxy_enabled": proxy_enabled,
    }


@router.put("/order")
async def update_priority_order(
    req: PriorityOrderUpdate,
    session: AsyncSession = Depends(get_session),
):
    """按拖拽顺序批量更新站点优先级

    入参 order 为站点名列表（从高到低），后端按列表位置自动赋优先级：
        order[0] = priority 1000, order[1] = 999, ...
    """
    if not req.order:
        raise HTTPException(status_code=400, detail="order 不能为空")

    provider = CrawlerProvider()
    base_priority = 1000
    for idx, name in enumerate(req.order):
        if not provider.get(name):
            logger.warning(f"站点不存在: {name}，跳过")
            continue
        priority = base_priority - idx
        await _save_setting(session, f"crawler_{name}_priority", str(priority))

    return {"status": "ok", "updated": len(req.order)}


@router.post("/{name}/toggle")
async def toggle_site(
    name: str,
    enabled: bool,
    session: AsyncSession = Depends(get_session),
):
    """快捷启用/禁用站点"""
    provider = CrawlerProvider()
    if not provider.get(name):
        raise HTTPException(status_code=404, detail=f"站点不存在: {name}")

    if enabled:
        provider.enable(name)
        await _save_setting(session, f"crawler_{name}_enabled", "true")
    else:
        provider.disable(name)
        await _save_setting(session, f"crawler_{name}_enabled", "false")

    return {"status": "ok", "name": name, "enabled": enabled}


# ===== 内部辅助 =====

async def _save_setting(session: AsyncSession, key: str, value: str):
    """保存配置到 settings 表"""
    existing = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = existing.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.commit()
