"""
站点管理路由

API 端点：
- GET  /api/v1/crawlers              - 可用站点列表
- POST /api/v1/crawlers/ping         - 一键测速所有站点
- POST /api/v1/crawlers/priority     - 设置站点优先级
- GET  /api/v1/crawlers/stats        - 站点统计
- POST /api/v1/crawlers/{name}/test  - 测试站点刮削
- POST /api/v1/crawlers/{name}/ping  - 单站点测速
- GET  /api/v1/crawlers/{name}       - 获取站点详情
- POST /api/v1/crawlers/{name}/enable  - 启用站点
- POST /api/v1/crawlers/{name}/disable - 禁用站点

注意：固定路径（/ping, /priority, /stats）必须在动态路径（/{name}）之前注册，
否则 FastAPI 会把 "ping"、"priority"、"stats" 当作 name 参数匹配。
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawlers.provider import CrawlerProvider
from app.db.database import get_session
from app.db.models import Movie

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Response Models =====

class CrawlerInfo(BaseModel):
    """爬虫信息"""
    name: str
    display_name: str
    enabled: bool
    priority: int
    supported_types: list[str] = []
    description: Optional[str] = None


class CrawlerListResponse(BaseModel):
    """爬虫列表响应"""
    total: int
    items: list[CrawlerInfo]


class CrawlerTestResult(BaseModel):
    """爬虫测试结果"""
    name: str
    success: bool
    response_time: float  # 毫秒
    error_message: Optional[str] = None


class CrawlerPingResult(BaseModel):
    """站点网络测试结果"""
    name: str
    url: str
    direct: Optional[dict] = None
    proxy: Optional[dict] = None


class CrawlerBatchPingResponse(BaseModel):
    """批量站点测速响应"""
    results: list[CrawlerPingResult]
    proxy_enabled: bool


class CrawlerStatsResponse(BaseModel):
    """爬虫统计响应"""
    name: str
    total_scraped: int
    success_rate: float
    avg_response_time: float


# ===== 测速辅助函数 =====

async def _test_url(url: str, proxy: str | None = None, timeout: float = 10.0) -> dict:
    """
    使用 curl_cffi 测试 URL 可达性

    使用 async with 确保 session 正确关闭，避免连接泄漏。
    """
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

    start = time.time()
    session = None
    try:
        kwargs = {
            "timeout": timeout,
            "verify": False,
        }
        if proxy:
            kwargs["proxy"] = proxy

        session = CurlAsyncSession(**kwargs)
        resp = await session.get(url, impersonate="chrome124")
        elapsed = (time.time() - start) * 1000
        return {
            "success": resp.status_code < 500,
            "status_code": resp.status_code,
            "time_ms": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        error_msg = str(e)
        if len(error_msg) > 80:
            error_msg = error_msg[:80] + "..."
        return {
            "success": False,
            "status_code": None,
            "time_ms": round(elapsed, 1),
            "error": error_msg,
        }
    finally:
        if session:
            try:
                await session.close()
            except Exception:
                pass


async def _ping_one_crawler(name: str, base_url: str, proxy_url: str | None, proxy_enabled: bool) -> CrawlerPingResult:
    """测速单个站点（直连+代理并发）"""
    if not base_url:
        return CrawlerPingResult(name=name, url="", direct=None, proxy=None)

    # 直连和代理并发测试
    tasks = [_test_url(base_url)]
    if proxy_enabled and proxy_url:
        tasks.append(_test_url(base_url, proxy=proxy_url))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    direct_result = results[0] if not isinstance(results[0], Exception) else {"success": False, "error": str(results[0])}
    proxy_result = None
    if len(results) > 1:
        proxy_result = results[1] if not isinstance(results[1], Exception) else {"success": False, "error": str(results[1])}

    return CrawlerPingResult(
        name=name,
        url=base_url,
        direct=direct_result,
        proxy=proxy_result,
    )


# ===== API Endpoints =====
# 注意：固定路径必须在动态路径（/{name}）之前！

@router.get("", response_model=CrawlerListResponse)
async def list_crawlers(
    session: AsyncSession = Depends(get_session),
):
    """
    获取可用站点列表

    返回所有已注册的爬虫信息（从数据库读取启用状态和优先级）
    """
    from app.db.models import Setting
    from sqlalchemy import select

    provider = CrawlerProvider()
    crawlers = provider.get_all()

    # 批量读取所有爬虫配置
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

    items = []
    for name, crawler in crawlers.items():
        enabled_str = settings.get(f"crawler_{name}_enabled")
        priority_str = settings.get(f"crawler_{name}_priority")

        info = CrawlerInfo(
            name=name,
            display_name=getattr(crawler, "display_name", name),
            enabled=enabled_str != "false" if enabled_str else True,
            priority=int(priority_str) if priority_str else getattr(crawler, "priority", 5),
            supported_types=getattr(crawler, "supported_types", []),
            description=getattr(crawler, "description", None),
        )
        items.append(info)

    # 按优先级排序
    items.sort(key=lambda x: x.priority, reverse=True)

    return CrawlerListResponse(total=len(items), items=items)


@router.post("/ping", response_model=CrawlerBatchPingResponse)
async def ping_crawlers():
    """
    批量站点测速（并发执行）

    测试所有站点的连通性和响应时间（直连和代理）
    """
    from app.config.manager import get_config_manager

    config_manager = get_config_manager()
    config = config_manager.config
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()
    proxy_enabled = bool(proxy_url)

    provider = CrawlerProvider()
    crawlers = provider.get_all()

    # 并发测速所有站点
    tasks = []
    for name, crawler in crawlers.items():
        base_url = getattr(crawler, "base_url", None) or ""
        tasks.append(_ping_one_crawler(name, base_url, proxy_url, proxy_enabled))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常结果
    final_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            name = list(crawlers.keys())[i]
            final_results.append(CrawlerPingResult(name=name, url="", direct=None, proxy=None))
        else:
            final_results.append(r)

    return CrawlerBatchPingResponse(
        results=final_results,
        proxy_enabled=proxy_enabled,
    )


@router.post("/priority")
async def set_crawler_priority(
    priorities: dict[str, int],
    session: AsyncSession = Depends(get_session),
):
    """
    设置站点优先级

    - priorities: {站点名: 优先级}
    """
    provider = CrawlerProvider()

    for name, priority in priorities.items():
        if not provider.get(name):
            logger.warning(f"站点不存在: {name}")
            continue

        await _save_crawler_setting(session, f"crawler_{name}_priority", str(priority))

    return {"status": "ok", "message": f"已更新 {len(priorities)} 个站点的优先级"}


@router.get("/stats")
async def get_crawler_stats(
    session: AsyncSession = Depends(get_session),
):
    """
    获取站点统计

    - 各站点刮削数量
    - 成功率
    """
    # 按来源统计
    query = (
        select(
            Movie.source,
            func.count(Movie.id).label("count")
        )
        .where(Movie.source.isnot(None))
        .group_by(Movie.source)
        .order_by(func.count(Movie.id).desc())
    )

    result = await session.execute(query)
    stats = [
        {"source": row[0], "count": row[1]}
        for row in result.fetchall()
    ]

    return {
        "total_movies": sum(s["count"] for s in stats),
        "sources": stats,
    }


# ===== 动态路径（/{name}）必须放在固定路径之后 =====

@router.post("/{name}/test", response_model=CrawlerTestResult)
async def test_crawler(
    name: str,
    test_code: str = Query("ABC-123", description="测试番号"),
):
    """
    测试站点刮削

    - name: 站点名称
    - test_code: 测试番号（默认 ABC-123）
    """
    provider = CrawlerProvider()
    crawler = provider.get(name)

    if not crawler:
        raise HTTPException(status_code=404, detail=f"站点不存在: {name}")

    # 测试
    start_time = time.time()

    try:
        result = await crawler.scrape(test_code)
        response_time = (time.time() - start_time) * 1000  # 毫秒

        return CrawlerTestResult(
            name=name,
            success=result is not None,
            response_time=response_time,
            error_message=None,
        )

    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        logger.error(f"Crawler test failed: {name} - {e}")

        return CrawlerTestResult(
            name=name,
            success=False,
            response_time=response_time,
            error_message=str(e),
        )


@router.post("/{name}/ping", response_model=CrawlerPingResult)
async def ping_single_crawler(
    name: str,
):
    """
    单站点网络测试

    测试指定站点的连通性和响应时间（直连和代理）
    """
    from app.config.manager import get_config_manager

    provider = CrawlerProvider()
    crawler = provider.get(name)

    if not crawler:
        raise HTTPException(status_code=404, detail=f"站点不存在: {name}")

    base_url = getattr(crawler, "base_url", "") or ""
    if not base_url:
        return CrawlerPingResult(name=name, url="", direct=None, proxy=None)

    config_manager = get_config_manager()
    config = config_manager.config
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()
    proxy_enabled = bool(proxy_url)

    return await _ping_one_crawler(name, base_url, proxy_url, proxy_enabled)


@router.get("/{name}")
async def get_crawler_info(name: str):
    """
    获取单个站点信息

    - 详细配置
    - 支持的番号类型
    """
    provider = CrawlerProvider()
    crawler = provider.get(name)

    if not crawler:
        raise HTTPException(status_code=404, detail=f"站点不存在: {name}")

    return {
        "name": name,
        "display_name": getattr(crawler, "display_name", name),
        "enabled": crawler.status.value == "enabled" if hasattr(crawler, "status") else True,
        "priority": getattr(crawler, "priority", 5) if not callable(getattr(crawler, "priority", 5)) else 50,
        "supported_types": getattr(crawler, "supported_types", []),
        "description": getattr(crawler, "description", None),
        "base_url": getattr(crawler, "base_url", None),
    }


@router.post("/{name}/enable")
async def enable_crawler(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """
    启用站点

    - name: 站点名称
    """
    provider = CrawlerProvider()

    if not provider.get(name):
        raise HTTPException(status_code=404, detail=f"站点不存在: {name}")

    provider.enable(name)
    await _save_crawler_setting(session, f"crawler_{name}_enabled", "true")

    return {"status": "ok", "message": f"站点 {name} 已启用"}


@router.post("/{name}/disable")
async def disable_crawler(
    name: str,
    session: AsyncSession = Depends(get_session),
):
    """
    禁用站点

    - name: 站点名称
    """
    provider = CrawlerProvider()

    if not provider.get(name):
        raise HTTPException(status_code=404, detail=f"站点不存在: {name}")

    provider.disable(name)
    await _save_crawler_setting(session, f"crawler_{name}_enabled", "false")

    return {"status": "ok", "message": f"站点 {name} 已禁用"}


# ===== 内部辅助函数 =====

async def _save_crawler_setting(session, key: str, value: str):
    """保存爬虫配置到数据库"""
    from app.db.models import Setting
    from sqlalchemy import select

    existing = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = existing.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.commit()


async def _get_crawler_setting(session, key: str) -> Optional[str]:
    """从数据库获取爬虫配置"""
    from app.db.models import Setting
    from sqlalchemy import select

    existing = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = existing.scalar_one_or_none()
    return setting.value if setting else None
