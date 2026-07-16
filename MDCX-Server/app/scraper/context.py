"""单次刮削资源上下文（ScrapeContext）

为单次刮削（一个番号 / 一个文件）提供共享资源池，避免每个 scraper 各自
创建 AsyncHttpClient、TLS 握手、随机浏览器指纹、独立 cookie jar 等开销。

参考 Hazard804-mdcx 的"单次刮削资源上下文复用"思路。

核心特性：
- 共享 AsyncHttpClient（curl_cffi AsyncSession）- 复用 TLS 连接 + 浏览器指纹
- 共享代理配置 - 一次读取，所有 scraper 共用
- 按域名的 cookies 池 - 支持运行时动态注入（如 CookieCloud 同步后）
- 按域名的 headers 池 - 站点级 UA / Accept-Language 复用
- 跨 scraper 的域名级速率限制协调

使用方式：
    ctx = ScrapeContext.create()
    async with ctx:
        result = await scraper.scrape(code, ctx=ctx)

 scraper 内部：
    client = ctx.http_client if ctx else AsyncHttpClient()
    cookies = ctx.get_cookies("javdb.com") if ctx else None
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.utils.http_client import AsyncHttpClient, get_http_client

logger = logging.getLogger(__name__)


@dataclass
class ScrapeContext:
    """单次刮削共享上下文

    生命周期：通常与一次 scrape_number 调用绑定（毫秒到几十秒级），
    在 ScraperEngine.scrape_number 入口处创建，asyncio.gather 完成后释放。
    """

    # 共享 HTTP 客户端（复用 TLS session + 浏览器指纹 + 速率限制器）
    http_client: Optional[AsyncHttpClient] = None
    # 共享代理 URL（所有 scraper 共用同一代理）
    proxy_url: Optional[str] = None
    # 浏览器指纹标识（用于日志/调试，实际指纹由 http_client 内部管理）
    fingerprint: Optional[str] = None
    # 按域名的 cookies 池：{"javdb.com": "key=val; key2=val2", ...}
    cookies_pool: dict[str, str] = field(default_factory=dict)
    # 按域名的 headers 池：{"javdb.com": {"User-Agent": "...", ...}, ...}
    headers_pool: dict[str, dict] = field(default_factory=dict)
    # 创建时间戳（用于超时统计）
    created_at: float = 0.0
    # 是否由本上下文"拥有"http_client（决定是否在 __aexit__ 时关闭）
    _owns_client: bool = False

    @classmethod
    def create(cls, http_client: Optional[AsyncHttpClient] = None) -> "ScrapeContext":
        """创建一个刮削上下文

        Args:
            http_client: 可选的已有 HTTP 客户端。若不传则延迟到 __aenter__
                         内 await get_http_client() 拿全局单例。

        Returns:
            ScrapeContext 实例（需通过 `async with` 使用）
        """
        import time

        # 注意: 不在此处调用 get_http_client()——它是 async 函数,同步 classmethod
        # 里 await 不了。留空,由 __aenter__ 里 await 拿到。
        owns_client = False  # 全局单例永远不由本上下文关闭

        ctx = cls(
            http_client=http_client,
            _owns_client=owns_client,
            created_at=time.time(),
        )

        # 从全局配置读取代理（统一走内置 xray / 旧版 config.proxy 唯一定义源）
        try:
            from app.services.proxy_manager import get_effective_proxy_url
            ctx.proxy_url = get_effective_proxy_url()
        except Exception as e:
            logger.debug(f"ScrapeContext 读取代理配置失败: {e}")

        # 从 CrawlerConfig 读取已知站点的 cookies（按域名映射）
        try:
            from app.config.manager import get_config_manager
            crawler_cfg = get_config_manager().config.crawler
            if crawler_cfg.javdb_cookie:
                ctx.cookies_pool["javdb.com"] = crawler_cfg.javdb_cookie
            if crawler_cfg.javbus_cookie:
                ctx.cookies_pool["javbus.com"] = crawler_cfg.javbus_cookie
            if getattr(crawler_cfg, "fc2ppvdb_cookie", None):
                ctx.cookies_pool["fc2cmadb.com"] = crawler_cfg.fc2ppvdb_cookie
        except Exception as e:
            logger.debug(f"ScrapeContext 读取 cookies 配置失败: {e}")

        return ctx

    def get_cookies(self, domain: str) -> Optional[str]:
        """获取指定域名的 cookie 字符串

        Args:
            domain: 域名（如 "javdb.com"）

        Returns:
            cookie 字符串，未配置返回 None
        """
        return self.cookies_pool.get(domain)

    def get_headers(self, domain: str) -> dict:
        """获取指定域名的 headers（含 cookie）

        Args:
            domain: 域名

        Returns:
            headers 字典（至少包含 User-Agent，可能包含 cookie）
        """
        headers = dict(self.headers_pool.get(domain, {}))
        # 默认 UA
        if "User-Agent" not in headers:
            headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        # 注入 cookie
        cookie = self.get_cookies(domain)
        if cookie and "cookie" not in {k.lower() for k in headers}:
            headers["cookie"] = cookie
        return headers

    def set_cookies(self, domain: str, cookies: str) -> None:
        """运行时更新某域名的 cookies（如 CookieCloud 同步后）"""
        self.cookies_pool[domain] = cookies

    async def __aenter__(self) -> "ScrapeContext":
        """进入上下文：确保 http_client 已初始化"""
        if self.http_client is None:
            self.http_client = await get_http_client()
            self._owns_client = False
        # 确保 client session 已初始化
        try:
            await self.http_client.init_session()
        except Exception as e:
            logger.debug(f"ScrapeContext init_session 失败: {e}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出上下文：仅在自身拥有 client 时关闭（一般不关闭全局单例）"""
        if self._owns_client and self.http_client is not None:
            try:
                await self.http_client.close_session()
            except Exception:
                pass


__all__ = ["ScrapeContext"]
