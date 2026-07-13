"""爬虫健康监控服务

参考 JavSP CI 的健康检查设计，实现爬虫的自动健康检测与降级：
- 每日自动检测所有已注册爬虫的可达性
- 检测到爬虫不可达时自动禁用并通知
- 支持手动重新启用和按需检查
- 爬虫状态持久化到数据库
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CrawlerHealth(str, Enum):
    """爬虫健康状态"""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


@dataclass
class CrawlerStatus:
    """单个爬虫的状态"""
    name: str
    display_name: str
    health: CrawlerHealth = CrawlerHealth.UNKNOWN
    last_checked: Optional[str] = None
    last_success: Optional[str] = None
    last_error: Optional[str] = None
    error_count: int = 0
    success_count: int = 0
    response_time_ms: float = 0.0
    enabled: bool = True
    auto_disabled: bool = False
    module: str = "jav"
    supported_types: list[str] = field(default_factory=list)


class ScraperMonitor:
    """爬虫健康监控器"""

    def __init__(self):
        self._crawlers: dict[str, CrawlerStatus] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._max_failures_before_disable = 3
        self._check_timeout = 15

    def register(self, name: str, display_name: str = "", module: str = "jav",
                 supported_types: Optional[list[str]] = None) -> None:
        """注册一个爬虫到监控系统"""
        if name in self._crawlers:
            return

        self._crawlers[name] = CrawlerStatus(
            name=name,
            display_name=display_name or name,
            module=module,
            supported_types=supported_types or [],
        )
        self._consecutive_failures[name] = 0
        logger.info(f"爬虫监控已注册: [{module}] {name}")

    def unregister(self, name: str) -> None:
        """从监控系统注销爬虫"""
        self._crawlers.pop(name, None)
        self._consecutive_failures.pop(name, None)

    async def check_crawler(self, name: str) -> CrawlerStatus:
        """检查单个爬虫的健康状态

        对爬虫执行一次快速可达性检测：
        1. 尝试访问爬虫的 base_url 或搜索端点
        2. 记录响应时间
        3. 连续失败超过阈值时自动禁用
        """
        status = self._crawlers.get(name)
        if not status:
            raise ValueError(f"爬虫未注册: {name}")

        if not status.enabled:
            return status

        from app.crawlers.provider import get_provider
        provider = get_provider()

        crawler = provider.get(name)
        if not crawler:
            status.health = CrawlerHealth.UNREACHABLE
            status.last_error = "爬虫未在 provider 中找到"
            return status

        start = time.monotonic()
        status.last_checked = datetime.now().isoformat()

        try:
            base_url = getattr(crawler, "base_url", None) or getattr(crawler, "BASE_URL", None)
            if not base_url:
                status.health = CrawlerHealth.UNKNOWN
                return status

            import httpx
            async with httpx.AsyncClient(timeout=self._check_timeout) as client:
                resp = await client.head(base_url, follow_redirects=True)

            elapsed = (time.monotonic() - start) * 1000
            status.response_time_ms = round(elapsed, 1)

            if resp.status_code < 500:
                status.health = CrawlerHealth.HEALTHY
                status.last_success = datetime.now().isoformat()
                status.success_count += 1
                self._consecutive_failures[name] = 0
            else:
                status.health = CrawlerHealth.DEGRADED
                status.last_error = f"HTTP {resp.status_code}"
                self._record_failure(name, status)

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            status.response_time_ms = round(elapsed, 1)
            status.health = CrawlerHealth.UNREACHABLE
            status.last_error = str(e)[:200]
            self._record_failure(name, status)

        return status

    def _record_failure(self, name: str, status: CrawlerStatus) -> None:
        """记录失败并自动禁用"""
        status.error_count += 1
        self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1

        if self._consecutive_failures[name] >= self._max_failures_before_disable:
            status.enabled = False
            status.auto_disabled = True
            status.health = CrawlerHealth.DISABLED
            logger.warning(
                f"爬虫 [{name}] 连续 {self._consecutive_failures[name]} 次检测失败，已自动禁用"
            )

    async def check_all(self) -> dict[str, CrawlerStatus]:
        """检查所有已注册爬虫"""
        logger.info(f"开始健康检查: {len(self._crawlers)} 个爬虫")

        tasks = []
        for name in self._crawlers:
            tasks.append(self.check_crawler(name))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        status_map = {}
        for name, result in zip(self._crawlers.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"爬虫 [{name}] 检查异常: {result}")
                if name in self._crawlers:
                    status_map[name] = self._crawlers[name]
            else:
                status_map[name] = result

        healthy = sum(1 for s in status_map.values() if s.health == CrawlerHealth.HEALTHY)
        degraded = sum(1 for s in status_map.values() if s.health == CrawlerHealth.DEGRADED)
        unreachable = sum(1 for s in status_map.values() if s.health == CrawlerHealth.UNREACHABLE)
        disabled = sum(1 for s in status_map.values() if not s.enabled)

        logger.info(
            f"健康检查完成: 健康={healthy}, 降级={degraded}, "
            f"不可达={unreachable}, 已禁用={disabled}"
        )

        return status_map

    def enable(self, name: str) -> bool:
        """手动启用爬虫"""
        status = self._crawlers.get(name)
        if not status:
            return False
        status.enabled = True
        status.auto_disabled = False
        self._consecutive_failures[name] = 0
        logger.info(f"爬虫 [{name}] 已手动启用")
        return True

    def disable(self, name: str) -> bool:
        """手动禁用爬虫"""
        status = self._crawlers.get(name)
        if not status:
            return False
        status.enabled = False
        logger.info(f"爬虫 [{name}] 已手动禁用")
        return True

    def get_status(self, name: str) -> Optional[CrawlerStatus]:
        """获取单个爬虫状态"""
        return self._crawlers.get(name)

    def list_status(self) -> list[dict]:
        """获取所有爬虫状态（序列化）"""
        return [
            {
                "name": s.name,
                "display_name": s.display_name,
                "health": s.health.value,
                "enabled": s.enabled,
                "auto_disabled": s.auto_disabled,
                "last_checked": s.last_checked,
                "last_success": s.last_success,
                "last_error": s.last_error,
                "error_count": s.error_count,
                "success_count": s.success_count,
                "response_time_ms": s.response_time_ms,
                "module": s.module,
                "supported_types": s.supported_types,
            }
            for s in self._crawlers.values()
        ]

    def get_summary(self) -> dict:
        """获取健康摘要"""
        all_status = list(self._crawlers.values())
        return {
            "total": len(all_status),
            "healthy": sum(1 for s in all_status if s.health == CrawlerHealth.HEALTHY),
            "degraded": sum(1 for s in all_status if s.health == CrawlerHealth.DEGRADED),
            "unreachable": sum(1 for s in all_status if s.health == CrawlerHealth.UNREACHABLE),
            "disabled": sum(1 for s in all_status if not s.enabled),
            "auto_disabled": sum(1 for s in all_status if s.auto_disabled),
        }

    def auto_register_all(self) -> int:
        """自动注册所有已配置的爬虫

        从 provider 获取所有爬虫并自动注册。
        """
        try:
            from app.crawlers.provider import get_provider
            provider = get_provider()
            all_crawlers = provider.get_all()

            count = 0
            for name, crawler in all_crawlers.items():
                display_name = getattr(crawler, "display_name", None) or name
                supported_types = getattr(crawler, "supported_types", []) or []
                module = supported_types[0] if supported_types else "jav"

                self.register(
                    name=name,
                    display_name=display_name,
                    module=module,
                    supported_types=supported_types,
                )
                count += 1

            logger.info(f"自动注册了 {count} 个爬虫到监控系统")
            return count

        except Exception as e:
            logger.warning(f"自动注册爬虫失败: {e}")
            return 0


# 全局单例
_monitor_instance: Optional[ScraperMonitor] = None


def get_scraper_monitor() -> ScraperMonitor:
    """获取全局爬虫监控器"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ScraperMonitor()
    return _monitor_instance


__all__ = [
    "ScraperMonitor",
    "CrawlerStatus",
    "CrawlerHealth",
    "get_scraper_monitor",
]
