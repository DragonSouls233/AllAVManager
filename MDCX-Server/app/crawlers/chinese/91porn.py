"""
91porn 爬虫 — 国产模块的通用聚合搜索源。

91porn 是最大的中文成人视频平台之一。
支持按演员名搜索，自动提取视频标题、封面、标签。

参考：pornSpider 的 91porn 爬虫模式。
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
class Chinese91pornCrawler(BaseCrawler):
    """91porn 爬虫 — 国产通用搜索源。"""

    name = "91porn_chinese"
    display_name = "91porn 国产"
    base_url = "https://91porn.com"

    priority = CrawlerPriority.LOW
    supported_types = ["chinese"]
    description = "91porn 国产通用搜索"
    language = "zh"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        # 搜索关键词
        search_url = f"{self.base_url}/search_result.php?search_type=search_videos&search_id={quote(code)}&page=1"
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html = await client.get_text(search_url, headers={"User-Agent": _USER_AGENT})
                if not html:
                    return None

                # 提取视频链接
                links = re.findall(r'href="(/v\.php\?viewkey=\w+)"', html)
                if not links:
                    return None

                # 取第一个结果
                detail_url = f"{self.base_url}{links[0]}"
                detail_html = await client.get_text(detail_url, headers={"User-Agent": _USER_AGENT})
                if not detail_html:
                    return None

                return self._parse_detail(detail_html, code)
            except Exception as e:
                logger.debug("91porn scrape failed for %s: %s", code, e)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        results: list[ScrapeResult] = []
        r = await self.scrape(keyword)
        if r:
            results.append(r)
        return results

    def _parse_detail(self, html: str, code: str) -> Optional[ScrapeResult]:
        result = ScrapeResult()
        result.code = code.upper()
        result.source = "91porn"
        result.studio = "91porn"

        title_m = re.search(r'<title>(.*?)</title>', html)
        result.title = title_m.group(1).strip() if title_m else code

        cover_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if cover_m:
            result.cover_url = cover_m.group(1)

        duration_m = re.search(r'(\d+):(\d+)', html)
        if duration_m:
            result.duration = int(duration_m.group(1)) * 60 + int(duration_m.group(2))

        actors = re.findall(r'<a[^>]*href="[^"]*viewkey[^"]*"[^>]*>(.*?)</a>', html)
        seen = set()
        result.actors = []
        for a in actors:
            name = a.strip()
            if name and name not in seen and len(name) < 30:
                seen.add(name)
                result.actors.append(ActorInfo(name=name))

        tags = re.findall(r'<a[^>]*href="[^"]*tag[^"]*"[^>]*>(.*?)</a>', html)
        result.genres = [t.strip() for t in tags if t.strip() and len(t.strip()) < 30]

        return result
