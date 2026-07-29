"""
FC2 增强爬虫 — 多通道搜索 FC2 视频。

通道：
1. dmm.co.jp — 日本最大成人平台，FC2 官方通道
2. fc2ppvdb.com — 原已有，增加筛选
3. sukebei.nyaa.si — 磁力搜索增强
"""

import re
from typing import Optional
from urllib.parse import quote

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@register_crawler
class FC2DMMCrawler(BaseCrawler):
    """FC2 + DMM 双通道搜索爬虫。"""

    name = "fc2_enhanced"
    display_name = "FC2 Enhanced"
    base_url = "https://www.fc2.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["fc2"]
    supported_prefixes = ["FC2"]
    description = "FC2 增强搜索（DMM + Sukebei 双通道）"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        clean_code = code.upper().replace("FC2-PPV-", "").replace("FC2-", "").replace("FC2PPV", "").strip()

        # 通道1: DMM 搜索
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                dmm_url = f"https://www.dmm.co.jp/search/=/searchstr={quote(clean_code)}/"
                r = await client.get_text(dmm_url, headers={"User-Agent": _USER_AGENT})
                if r and "FC2" in r:
                    result = self._parse_dmm(r, code, clean_code)
                    if result:
                        return result
            except Exception as e:
                logger.debug("fc2 dmm search failed: %s", e)

        # 通道2: Sukebei 磁力搜索
        result = await self._scrape_sukebei(clean_code)
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        results: list[ScrapeResult] = []
        r = await self.scrape(f"FC2-PPV-{keyword}")
        if r:
            results.append(r)
        return results

    async def _scrape_sukebei(self, clean_code: str) -> Optional[ScrapeResult]:
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                url = f"https://sukebei.nyaa.si/?q=FC2-PPV-{clean_code}&s=seeders&o=desc"
                r = await client.get_text(url, headers={"User-Agent": _USER_AGENT})
                if not r:
                    return None

                result = ScrapeResult()
                result.code = f"FC2-PPV-{clean_code}"
                result.source = "fc2_enhanced"
                result.title = f"FC2-PPV-{clean_code}"
                result.studio = "FC2"

                # 提取标题
                title_m = re.search(r'<a[^>]*href="[^"]*view[^"]*"[^>]*>(.*?)</a>', r, re.DOTALL)
                if title_m:
                    result.title = title_m.group(1).strip()

                # 提取磁力链接
                magnet_m = re.findall(r'href="(magnet:\?xt=urn:btih:[^"]+)"', r)
                result.metadata["magnets"] = magnet_m[:3]

                return result
            except Exception as e:
                logger.debug("fc2 sukebei search failed: %s", e)
        return None

    def _parse_dmm(self, html: str, code: str, clean_code: str) -> Optional[ScrapeResult]:
        result = ScrapeResult()
        result.code = code.upper()
        result.source = "fc2_enhanced"
        result.studio = "FC2"

        title_m = re.search(r'<title>(.*?)</title>', html)
        result.title = title_m.group(1).strip() if title_m else code

        cover_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if cover_m:
            result.cover_url = cover_m.group(1)

        actors_m = re.findall(r'<a[^>]*href="[^"]*actor[^"]*"[^>]*>(.*?)</a>', html)
        result.actors = [ActorInfo(name=a.strip()) for a in actors_m if a.strip() and len(a.strip()) < 30]

        return result
