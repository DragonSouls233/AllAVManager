"""Cloudflare 绕过策略

参考 javm (隐藏 WebView) + jav-scrapy (curl-cffi) + Emby.Plugins.JavScraper (CF Worker) 的设计：
- 第一层：curl_cffi 指纹模拟（Chrome 120+ 指纹）
- 第二层：Cloudflare Worker 代理转发
- 第三层：FlareSolverr 服务（兜底）
- 第四层：静态 HTML 缓存回退（最终回退）
"""

import asyncio
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BypassResult:
    """绕过结果"""
    html: Optional[str] = None
    text: Optional[str] = None
    headers: dict = field(default_factory=dict)
    status_code: int = 0
    strategy: str = ""
    success: bool = False
    elapsed_ms: float = 0.0
    error: Optional[str] = None


class BaseBypassStrategy(ABC):
    """绕过策略基类"""

    @abstractmethod
    async def fetch(self, url: str, headers: Optional[dict] = None, timeout: int = 30) -> BypassResult:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class CurlCffiStrategy(BaseBypassStrategy):
    """第一层：curl_cffi 指纹模拟

    模拟真实 Chrome 浏览器的 TLS 指纹和 HTTP 头。
    """

    @property
    def name(self) -> str:
        return "curl_cffi"

    async def fetch(self, url: str, headers: Optional[dict] = None, timeout: int = 30) -> BypassResult:
        start = time.monotonic()
        try:
            # 尝试使用 curl_cffi（如果可用）
            try:
                from curl_cffi import requests as curl_requests
            except ImportError:
                return BypassResult(
                    success=False, strategy=self.name,
                    error="curl_cffi 未安装", elapsed_ms=(time.monotonic() - start) * 1000,
                )

            default_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
            if headers:
                default_headers.update(headers)

            session = curl_requests.Session()
            session.impersonate = "chrome120"

            resp = session.get(
                url,
                headers=default_headers,
                timeout=timeout,
                verify=False,
            )

            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                html=resp.text,
                text=resp.text,
                headers=dict(resp.headers),
                status_code=resp.status_code,
                strategy=self.name,
                success=resp.status_code < 500,
                elapsed_ms=round(elapsed, 1),
            )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                success=False, strategy=self.name,
                error=str(e)[:200], elapsed_ms=round(elapsed, 1),
            )


class CfWorkerProxyStrategy(BaseBypassStrategy):
    """第二层：Cloudflare Worker 代理转发

    通过自部署的 CF Worker 代理请求，利用 Worker 的 Cloudflare 网络绕过 WAF。
    需要用户自行部署 Worker 脚本并提供 URL。
    """

    @property
    def name(self) -> str:
        return "cf_worker_proxy"

    async def fetch(self, url: str, headers: Optional[dict] = None, timeout: int = 30) -> BypassResult:
        start = time.monotonic()
        try:
            import httpx

            worker_url = os.environ.get("MDCX_CF_WORKER_URL", "")
            if not worker_url:
                return BypassResult(
                    success=False, strategy=self.name,
                    error="CF_WORKER_URL 未配置（设置 MDCX_CF_WORKER_URL 环境变量）",
                    elapsed_ms=(time.monotonic() - start) * 1000,
                )

            target_url = f"{worker_url}?url={url}"

            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                resp = await client.get(target_url, headers=headers or {})

            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                html=resp.text,
                text=resp.text,
                headers=dict(resp.headers),
                status_code=resp.status_code,
                strategy=self.name,
                success=resp.status_code < 500,
                elapsed_ms=round(elapsed, 1),
            )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                success=False, strategy=self.name,
                error=str(e)[:200], elapsed_ms=round(elapsed, 1),
            )


class FlareSolverrStrategy(BaseBypassStrategy):
    """第三层：FlareSolverr 服务

    通过 FlareSolverr 服务使用真实浏览器渲染页面，解决 JS 挑战。
    FlareSolverr 是一个独立的 Docker 服务。
    """

    @property
    def name(self) -> str:
        return "flare_solverr"

    async def fetch(self, url: str, headers: Optional[dict] = None, timeout: int = 60) -> BypassResult:
        start = time.monotonic()
        try:
            import httpx

            solver_url = os.environ.get("MDCX_FLARESOLVERR_URL", "http://localhost:8191/v1")
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": timeout * 1000,
            }
            if headers:
                payload["headers"] = headers

            async with httpx.AsyncClient(timeout=timeout + 10, verify=False) as client:
                resp = await client.post(solver_url, json=payload)

            data = resp.json()
            solution = data.get("solution", {})
            elapsed = (time.monotonic() - start) * 1000

            return BypassResult(
                html=solution.get("response", ""),
                text=solution.get("response", ""),
                headers=solution.get("headers", {}),
                status_code=solution.get("status", 0),
                strategy=self.name,
                success=data.get("status", "") == "ok",
                elapsed_ms=round(elapsed, 1),
            )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                success=False, strategy=self.name,
                error=str(e)[:200], elapsed_ms=round(elapsed, 1),
            )


class FallbackCacheStrategy(BaseBypassStrategy):
    """第四层（兜底）：静态 HTML 缓存

    如果所有绕过方式都失败，尝试从本地缓存返回上次成功获取的 HTML。
    无缓存时使用 httpx 直接请求（适用于无 Cloudflare 保护的站点）。
    """

    def __init__(self):
        self._cache: dict[str, BypassResult] = {}

    @property
    def name(self) -> str:
        return "fallback_cache"

    async def fetch(self, url: str, headers: Optional[dict] = None, timeout: int = 30) -> BypassResult:
        start = time.monotonic()

        # 检查缓存
        if url in self._cache:
            cached = self._cache[url]
            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                html=cached.html, text=cached.text,
                headers=cached.headers, status_code=cached.status_code,
                strategy=f"{self.name}(cached)", success=True,
                elapsed_ms=round(elapsed, 1),
            )

        # 直接请求
        try:
            import httpx

            async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers or {})

            elapsed = (time.monotonic() - start) * 1000
            result = BypassResult(
                html=resp.text, text=resp.text,
                headers=dict(resp.headers), status_code=resp.status_code,
                strategy=self.name,
                success=resp.status_code < 500,
                elapsed_ms=round(elapsed, 1),
            )

            # 缓存成功的结果
            if result.success:
                self._cache[url] = result

            return result

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return BypassResult(
                success=False, strategy=self.name,
                error=str(e)[:200], elapsed_ms=round(elapsed, 1),
            )

    def clear_cache(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        return count


class CloudflareBypass:
    """Cloudflare 绕过管理器

    按优先级执行多级绕过策略：
    1. curl_cffi 指纹模拟
    2. Cloudflare Worker 代理
    3. FlareSolverr 浏览器渲染
    4. 静态缓存 / 直接请求（兜底）
    """

    def __init__(self):
        self._strategies: list[BaseBypassStrategy] = [
            CurlCffiStrategy(),
            CfWorkerProxyStrategy(),
            FlareSolverrStrategy(),
            FallbackCacheStrategy(),
        ]
        self._fallback_cache: Optional[FallbackCacheStrategy] = None
        for s in self._strategies:
            if isinstance(s, FallbackCacheStrategy):
                self._fallback_cache = s
                break

    def set_strategies(self, strategies: list[BaseBypassStrategy]) -> None:
        """自定义策略顺序和列表"""
        self._strategies = strategies

    def get_fallback(self) -> FallbackCacheStrategy:
        if self._fallback_cache is None:
            self._fallback_cache = FallbackCacheStrategy()
            self._strategies.append(self._fallback_cache)
        return self._fallback_cache

    async def fetch(
        self,
        url: str,
        headers: Optional[dict] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> BypassResult:
        """逐级尝试所有绕过策略

        Args:
            url: 目标 URL
            headers: 自定义请求头
            timeout: 超时秒数
            max_retries: 每级最大重试次数

        Returns:
            BypassResult
        """
        last_result = BypassResult(success=False)

        for strategy in self._strategies:
            logger.debug(f"CF 绕过: 尝试 {strategy.name} ...")

            for attempt in range(max_retries):
                result = await strategy.fetch(url, headers, timeout)

                if result.success:
                    logger.info(
                        f"CF 绕过成功: {strategy.name} "
                        f"(status={result.status_code}, {result.elapsed_ms}ms)"
                    )
                    return result

                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 2
                    logger.debug(f"{strategy.name} 失败，{wait}s 后重试: {result.error}")
                    await asyncio.sleep(wait)

            last_result = result
            logger.warning(f"CF 绕过策略 {strategy.name} 失败: {result.error}")

        logger.error(f"所有 CF 绕过策略均失败 [{url[:100]}]")
        return last_result

    async def fetch_with_cache(
        self,
        url: str,
        headers: Optional[dict] = None,
        timeout: int = 30,
    ) -> BypassResult:
        """带缓存回退的获取

        先尝试绕过 -> 成功则缓存结果 -> 下次直接返回缓存。
        """
        cache = self.get_fallback()

        result = await self.fetch(url, headers, timeout)

        if result.success:
            cache._cache[url] = result

        return result

    def clear_cache(self) -> int:
        return self.get_fallback().clear_cache()


# 全局单例
_bypass_instance: Optional[CloudflareBypass] = None


def get_cf_bypass() -> CloudflareBypass:
    """获取全局 CloudflareBypass 实例"""
    global _bypass_instance
    if _bypass_instance is None:
        _bypass_instance = CloudflareBypass()
    return _bypass_instance


async def cf_fetch(url: str, **kwargs) -> BypassResult:
    """便捷函数：使用 Cloudflare 绕过获取 URL"""
    bypass = get_cf_bypass()
    return await bypass.fetch(url, **kwargs)


__all__ = [
    "CloudflareBypass",
    "BypassResult",
    "BaseBypassStrategy",
    "CurlCffiStrategy",
    "CfWorkerProxyStrategy",
    "FlareSolverrStrategy",
    "FallbackCacheStrategy",
    "get_cf_bypass",
    "cf_fetch",
]
