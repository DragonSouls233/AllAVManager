"""
站点管理路由

API 端点：
- GET  /api/v1/crawlers              - 可用站点列表
- POST /api/v1/crawlers/ping         - 一键测速所有站点
- POST /api/v1/crawlers/priority     - 设置站点优先级
- GET  /api/v1/crawlers/stats        - 站点统计（仅成功入库的来源分布）
- GET  /api/v1/crawlers/health       - 源健康度：逐源成功率/失败原因/是否该降权
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
from app.utils.module_helper import get_module_model, get_module_session

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
        # 若命中 curl_cffi 原生层致命错误，顺带置位**进程级**降级标志，
        # 让后续刮削请求提前走 httpx（此处不 re-raise，仍返回错误 dict）。
        try:
            from app.utils.http_client import is_fatal_curl_error, mark_curl_unavailable
            if is_fatal_curl_error(e):
                mark_curl_unavailable(f"爬虫连通性测试命中 curl_cffi 致命错误: {e!r}")
        except Exception:
            pass
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
    from app.db.system_models import Setting
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

    # 保存后即时应用到爬虫实例（无需重启即生效）
    provider.apply_saved_settings({
        f"crawler_{name}_priority": str(p)
        for name, p in priorities.items()
        if provider.get(name)
    })

    return {"status": "ok", "message": f"已更新 {len(priorities)} 个站点的优先级"}


@router.get("/stats")
async def get_crawler_stats(module: str = "jav"):
    """
    获取站点统计

    - 各站点刮削数量
    - 成功率
    """
    session = await get_module_session(module)
    MovieModel = get_module_model(module, "movie")

    # 按来源统计
    query = (
        select(
            MovieModel.source,
            func.count(MovieModel.id).label("count")
        )
        .where(MovieModel.source.isnot(None))
        .group_by(MovieModel.source)
        .order_by(func.count(MovieModel.id).desc())
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


@router.get("/health")
async def get_source_health(
    hours: int = Query(24, ge=1, le=720, description="统计时间窗（小时）"),
    module: Optional[str] = Query(None, description="按模块过滤，如 jav / uncensored"),
    prune: bool = Query(False, description="是否顺带清理过期记录"),
):
    """源健康度：谁在拖后腿

    与上面的 `/stats` 区别在于：`/stats` 统计的是**最终入库来源**
    （只反映成功结果，看不到抓不到的那些），本端点统计**每一次尝试**
    （含失败），因此能算出真实成功率。

    这是判断「某个源还该不该留在源池里」的唯一依据 ——
    只看失败数会把「量大但命中率高」和「几乎全败」混为一谈。

    返回按成功率升序，最差的排最前。
    """
    from app.scraper.recorder import (
        failure_breakdown,
        get_recorder,
        source_health,
    )

    # 顺带把内存缓冲落库，否则刚跑完的任务数据看不到
    recorder = get_recorder()
    flushed = await recorder.flush()

    rows = await source_health(hours=hours, module=module)
    breakdown = await failure_breakdown(hours=hours)

    pruned = 0
    if prune:
        pruned = await recorder.prune()

    # 🔴 2026-10-04：熔断状态必须一并暴露。
    # 只看"历史成功率"看不出"现在正在跳过哪些源" —— 熔断是即时状态，
    # 运维需要知道「这个源现在没在干活」而不是「它最近成功率低」。
    from app.scraper.breaker import get_breaker

    breakers = get_breaker().snapshot()

    return {
        "window_hours": hours,
        "module": module,
        "sources": rows,
        "failure_reasons": breakdown,
        "recorder": recorder.stats,
        "flushed_now": flushed,
        "pruned": pruned,
        "demote_candidates": [r["source"] for r in rows if r["demote"]],
        "circuit_open": breakers,
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
    from app.db.system_models import Setting
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
    from app.db.system_models import Setting
    from sqlalchemy import select

    existing = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = existing.scalar_one_or_none()
    return setting.value if setting else None
