"""
JavDB 新版爬虫 - 从 MDCX 新式爬虫迁移

MDCX 的 JavdbCrawler 继承自其 BaseCrawler 类体系，
这里直接适配到我们的 BaseCrawler 接口。
"""

import asyncio
import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urljoin

from parsel import Selector

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@register_crawler
class JavdbNewCrawler(BaseCrawler):
    """JavDB 新版爬虫"""

    name = "javdb_new"
    display_name = "JavDB (新版)"
    base_url = "https://javdb.com"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "JavDB 新版爬虫，支持多语言"
    language = "zh"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        self._last_request_at = 0.0

    async def _throttle(self):
        """请求限流"""
        now = time.monotonic()
        if self._last_request_at > 0:
            wait = 1.5 - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        # 只走 JavDB App API 匿名通道（免登录、不绑定 IP、绕 CF）。
        # 不再降级 HTML+cookie 链：javdb.com 直连被 Cloudflare 403 拦截，
        # cookie 链实测全部 403 + 3 次重试，只会空转浪费时间。
        return await self._scrape_via_app_api(code, zone=self._infer_zone(code))

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    async def _scrape_via_app_api(self, code: str, zone: Optional[str] = None) -> Optional[ScrapeResult]:
        """通过 JavDB 匿名 App JSON API 刮削（免登录、绕过 Cloudflare）。

        zone 可选：按分区过滤搜索结果（censored/uncensored/western/fc2）。
        与 javdb.py 主爬虫的通道保持一致。
        """
        try:
            from app.services.javdb_app_client import JavDBAppClient
            client = JavDBAppClient()
            try:
                mv = await client.search_movie(code, zone=zone)
                if not mv:
                    logger.debug(f"JavDB App API {code}: 未找到")
                    return None
                # 反向校验：App API 返回的 number 若与目标番号强不等价，判定为抓错片，拒绝入库防串号。
                if mv.number:
                    from app.utils.code_verify import reverse_code_check
                    is_match, norm_e, norm_g = reverse_code_check(code, mv.number)
                    if not is_match:
                        logger.warning(
                            f"JavDB App API 番号反向校验失败，拒绝入库: 期望={norm_e} 实际={norm_g} title={mv.title[:30]!r}"
                        )
                        return None
                magnets = await client.get_magnets(mv.id)
                # v4 详情补全：搜索接口字段极少（无 studio/series/actors/tags/plot），
                # 2026-08-18 新增调 /api/v4/movies/{id} 补全，解决"NFO 系列只有小部分有"。
                fields = await client.build_scrape_fields(mv, magnets)
                fields["code"] = fields.get("code") or code
                fields["title"] = fields.get("title") or code
                fields["release_date"] = self._parse_date(fields.get("release_date") or "")
                fields["confidence"] = 0.9
                return ScrapeResult(source=self.name, **fields)
            finally:
                await client.close()
        except Exception as e:
            logger.debug(f"JavDB App API 兜底失败 {code}: {e}")
            return None

    @staticmethod
    def _infer_zone(code: str) -> Optional[str]:
        """按番号格式推断 JavDB 分区；无法确定返回 None（全分区搜索 + 精确匹配 + 反向校验防串号）。"""
        c = (code or "").upper().replace(" ", "")
        if c.startswith("FC2"):
            return "fc2"
        return None

    @staticmethod
    def _extract_text(html: Selector, *xpaths: str) -> str:
        for xpath in xpaths:
            result = html.xpath(xpath).get(default="")
            if result and result.strip():
                return result.strip()
        return ""

    @staticmethod
    def _parse_date(date_str: str):
        from datetime import date
        if not date_str:
            return None
        if match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str):
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
        return None
