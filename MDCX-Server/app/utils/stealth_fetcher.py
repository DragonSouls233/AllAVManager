"""
Stealth Fetcher - 绕过 Cloudflare 的隐身请求器

使用 Scrapling StealthyFetcher 自动绕过 Cloudflare 保护。
在 asyncio 中通过线程池运行同步 API。

可选依赖:scrapling 未安装时 is_available() 返回 False,stealth_fetch 返回 None,
调用方应回退到降级链中的下一级(见 requirements-optional.txt)。
"""
import asyncio
import logging
from functools import partial
from typing import Optional

logger = logging.getLogger(__name__)

_fetcher_instance = None


def _get_fetcher():
    """Lazy init StealthyFetcher"""
    global _fetcher_instance
    if _fetcher_instance is None:
        try:
            from scrapling.fetchers import StealthyFetcher
            _fetcher_instance = StealthyFetcher
        except ImportError:
            logger.debug("scrapling 未安装，StealthyFetcher 不可用")
            return None
    return _fetcher_instance


def _sync_fetch(url: str, headless: bool = True, timeout: int = 30) -> Optional[dict]:
    """Synchronous fetch using StealthyFetcher"""
    Fetcher = _get_fetcher()
    if not Fetcher:
        return None

    try:
        page = Fetcher.fetch(
            url,
            headless=headless,
            bypass_cloudflare=True,
        )
        if page and page.status == 200:
            return {
                "html": page.text,
                "status": page.status,
                "url": page.url,
            }
        return None
    except Exception as e:
        logger.debug(f"StealthyFetcher 请求失败 {url}: {e}")
        return None


async def stealth_fetch(url: str, headless: bool = True, timeout: int = 30) -> Optional[dict]:
    """Async wrapper for StealthyFetcher"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        partial(_sync_fetch, url, headless, timeout),
    )
    return result


def is_available() -> bool:
    """Check if StealthyFetcher is available"""
    return _get_fetcher() is not None
