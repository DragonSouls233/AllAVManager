"""
Prometheus 监控指标采集服务

提供应用级指标采集与 Prometheus exposition format 输出。
- HTTP 请求计数 / 延迟直方图（通过中间件自动采集）
- 数据库统计（影片 / 演员 / 任务数量）
- 刮削引擎统计（成功 / 失败 / 重试）
- 系统运行时指标（内存 / CPU / 运行时间）

端点：
- /api/v1/health/metrics — Prometheus 文本格式（供 ServiceMonitor 抓取）
- /metrics — 独立路径（无认证，便于 Prometheus 直连）
"""

import asyncio
import os
import sys
import time
from collections import defaultdict
from typing import Optional

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY as _GLOBAL_REGISTRY,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 应用启动时间（用于 uptime 计算）
_APP_START_TIME = time.time()


# ===== 指标定义（prometheus_client 可用时使用其原生对象）=====

if _HAS_PROMETHEUS:
    # 使用独立 Registry，避免全局污染
    _registry = CollectorRegistry()

    # --- HTTP 请求指标 ---
    http_requests_total = Counter(
        "mdcx_http_requests_total",
        "HTTP 请求总数",
        ["method", "endpoint", "status"],
        registry=_registry,
    )
    http_request_duration_seconds = Histogram(
        "mdcx_http_request_duration_seconds",
        "HTTP 请求延迟（秒）",
        ["method", "endpoint"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        registry=_registry,
    )
    http_requests_in_progress = Gauge(
        "mdcx_http_requests_in_progress",
        "当前处理中的 HTTP 请求数",
        registry=_registry,
    )

    # --- 数据库指标 ---
    db_movies_total = Gauge("mdcx_db_movies_total", "影片总数", ["status"], registry=_registry)
    db_actors_total = Gauge("mdcx_db_actors_total", "演员总数", registry=_registry)
    db_tasks_total = Gauge("mdcx_db_tasks_total", "任务总数", ["status"], registry=_registry)
    db_tags_total = Gauge("mdcx_db_tags_total", "标签总数", registry=_registry)
    db_studios_total = Gauge("mdcx_db_studios_total", "厂商总数", registry=_registry)
    db_series_total = Gauge("mdcx_db_series_total", "系列总数", registry=_registry)
    db_favorites_total = Gauge("mdcx_db_favorites_total", "收藏总数", registry=_registry)
    db_connection_pool_size = Gauge(
        "mdcx_db_connection_pool_size", "数据库连接池大小", registry=_registry
    )

    # --- 刮削引擎指标 ---
    scrape_total = Counter(
        "mdcx_scrape_total",
        "刮削请求总数",
        ["status"],  # success / failed / skipped
        registry=_registry,
    )
    scrape_duration_seconds = Histogram(
        "mdcx_scrape_duration_seconds",
        "单次刮削耗时（秒）",
        buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
        registry=_registry,
    )
    crawler_sites_enabled = Gauge(
        "mdcx_crawler_sites_enabled", "已启用的爬虫站点数", registry=_registry
    )
    crawler_requests_total = Counter(
        "mdcx_crawler_requests_total",
        "爬虫请求总数",
        ["site", "status"],  # status: 200/403/429/timeout/error
        registry=_registry,
    )

    # --- 文件系统指标 ---
    files_total_size_bytes = Gauge(
        "mdcx_files_total_size_bytes", "媒体文件总大小（字节）", registry=_registry
    )
    files_count = Gauge("mdcx_files_count", "媒体文件数量", registry=_registry)

    # --- 系统指标 ---
    app_info = Info(
        "mdcx",
        "MDCX 应用信息",
        registry=_registry,
    )
    app_uptime_seconds = Gauge(
        "mdcx_app_uptime_seconds", "应用运行时间（秒）", registry=_registry
    )
    process_memory_rss_bytes = Gauge(
        "mdcx_process_memory_rss_bytes", "进程常驻内存（字节）", registry=_registry
    )
    process_cpu_percent = Gauge(
        "mdcx_process_cpu_percent", "进程 CPU 使用率（%）", registry=_registry
    )
    python_version_info = Gauge(
        "mdcx_python_version_info",
        "Python 版本信息",
        ["version"],
        registry=_registry,
    )

    # --- 部署指标 ---
    deploy_tier = Gauge(
        "mdcx_deploy_tier_info",
        "部署档位信息",
        ["tier"],
        registry=_registry,
    )

    # 初始化静态信息
    app_info.info({
        "name": "MDCX",
        "version": "0.1.0",
        "python": sys.version.split()[0],
        "platform": sys.platform,
    })
    python_version_info.labels(version=sys.version.split()[0]).set(1)
else:
    # prometheus_client 未安装时降级为内存计数器
    logger.warning("prometheus-client 未安装，指标采集降级为内存模式（建议 pip install prometheus-client")
    _registry = None
    _fallback_counters: dict[str, float] = defaultdict(float)


# ===== 中间件：自动采集 HTTP 指标 =====

class MetricsMiddleware:
    """
    Starlette/FastAPI 兼容的 ASGI 中间件，自动采集 HTTP 请求指标。
    使用方式：app.add_middleware(MetricsMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")

        # 归一化路径（将 /movies/123 → /movies/:id），减少 label 基数爆炸
        normalized = self._normalize_path(path)

        if _HAS_PROMETHEUS:
            http_requests_in_progress.inc()

        start_time = time.time()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.time() - start_time
            status_str = str(status_code)

            if _HAS_PROMETHEUS:
                http_requests_in_progress.dec()
                http_requests_total.labels(method=method, endpoint=normalized, status=status_str).inc()
                http_request_duration_seconds.labels(method=method, endpoint=normalized).observe(duration)
            else:
                _fallback_counters[f"http_{method}_{normalized}_{status_str}"] += 1
                _fallback_counters[f"http_duration_{method}_{normalized}"] += duration

    @staticmethod
    def _normalize_path(path: str) -> str:
        """将路径中的数字 ID 替换为 :id，减少 Prometheus label 基数"""
        parts = path.strip("/").split("/")
        normalized_parts = []
        for part in parts:
            if part.isdigit():
                normalized_parts.append(":id")
            elif len(part) == 36 and "-" in part:  # UUID
                normalized_parts.append(":uuid")
            else:
                normalized_parts.append(part)
        return "/" + "/".join(normalized_parts) if normalized_parts else "/"


# ===== 数据库指标采集 =====

async def collect_db_metrics():
    """异步采集数据库统计指标（定时调用或按需调用）"""
    try:
        from sqlalchemy import select, func
        from app.db.database import get_database
        from app.db.models import Movie, Task, Actor, Tag, Studio, Series, Favorite

        db = get_database()
        async with db.session() as session:
            if _HAS_PROMETHEUS:
                # 影片按状态统计
                for status in ("completed", "pending", "failed", "scraping"):
                    count = await session.scalar(
                        select(func.count(Movie.id)).where(Movie.status == status)
                    ) or 0
                    db_movies_total.labels(status=status).set(count)

                # 其他表统计
                db_actors_total.set(await session.scalar(select(func.count(Actor.id))) or 0)
                db_tags_total.set(await session.scalar(select(func.count(Tag.id))) or 0)
                db_studios_total.set(await session.scalar(select(func.count(Studio.id))) or 0)
                db_series_total.set(await session.scalar(select(func.count(Series.id))) or 0)
                db_favorites_total.set(await session.scalar(select(func.count(Favorite.id))) or 0)

                # 任务按状态统计
                for status in ("pending", "running", "completed", "failed", "cancelled"):
                    count = await session.scalar(
                        select(func.count(Task.id)).where(Task.status == status)
                    ) or 0
                    db_tasks_total.labels(status=status).set(count)

            return True
    except Exception as e:
        logger.debug(f"采集数据库指标失败: {e}")
        return False


def collect_system_metrics():
    """采集系统运行时指标（同步）"""
    if not _HAS_PROMETHEUS:
        return

    try:
        import resource
        # RSS 内存（字节）
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux 返回 KB，macOS 返回字节
        if sys.platform == "linux":
            rss *= 1024
        process_memory_rss_bytes.set(rss)
    except Exception:
        pass

    try:
        import psutil
        proc = psutil.Process()
        process_memory_rss_bytes.set(proc.memory_info().rss)
        process_cpu_percent.set(proc.cpu_percent(interval=0.1))
    except ImportError:
        pass

    # 运行时间
    app_uptime_seconds.set(time.time() - _APP_START_TIME)

    # 部署档位
    try:
        from app.deploy_tiers import detect_deploy_tier
        tier = detect_deploy_tier()
        deploy_tier.labels(tier=tier).set(1)
    except Exception:
        pass


def collect_crawler_metrics():
    """采集爬虫站点指标"""
    if not _HAS_PROMETHEUS:
        return
    try:
        from app.services.plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        enabled = sum(1 for p in pm.list_plugins() if getattr(p, "enabled", True))
        crawler_sites_enabled.set(enabled)
    except Exception:
        pass


def collect_all_metrics():
    """同步采集所有指标（用于 /metrics 端点响应前刷新）"""
    collect_system_metrics()
    collect_crawler_metrics()
    # 数据库指标是异步的，在路由中单独 await
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(collect_db_metrics())
        else:
            loop.run_until_complete(collect_db_metrics())
    except RuntimeError:
        # 无事件循环时跳过
        pass


def generate_metrics_text() -> str:
    """生成 Prometheus exposition format 文本"""
    if _HAS_PROMETHEUS:
        collect_all_metrics()
        return generate_latest(_registry).decode("utf-8")
    else:
        # 降级输出
        lines = [
            "# HELP mdcx_app_info MDCX 应用信息",
            "# TYPE mdcx_app_info gauge",
            f'mdcx_app_info{{name="MDCX",python="{sys.version.split()[0]}"}} 1',
            "# HELP mdcx_app_uptime_seconds 应用运行时间",
            "# TYPE mdcx_app_uptime_seconds gauge",
            f"mdcx_app_uptime_seconds {time.time() - _APP_START_TIME}",
        ]
        for key, val in _fallback_counters.items():
            lines.append(f"# TYPE {key} counter")
            lines.append(f"{key} {val}")
        return "\n".join(lines) + "\n"


def get_content_type() -> str:
    """返回 Prometheus 文本格式的 Content-Type"""
    if _HAS_PROMETHEUS:
        return CONTENT_TYPE_LATEST
    return "text/plain; charset=utf-8"


def record_scrape(status: str, duration: float = 0):
    """记录单次刮削结果（供刮削引擎调用）"""
    if _HAS_PROMETHEUS:
        scrape_total.labels(status=status).inc()
        if duration > 0:
            scrape_duration_seconds.observe(duration)
    else:
        _fallback_counters[f"scrape_{status}"] += 1


def record_crawler_request(site: str, status: str):
    """记录爬虫请求（供爬虫模块调用）"""
    if _HAS_PROMETHEUS:
        crawler_requests_total.labels(site=site, status=status).inc()
    else:
        _fallback_counters[f"crawler_{site}_{status}"] += 1
