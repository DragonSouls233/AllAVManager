"""
无码聚合爬虫 — 一站覆盖所有无码站点。

动态检测番号前缀并路由到对应的无码数据源。
支持站点：
- AVSTAR (avstar.me) — 多无码源聚合
- AVSOX — 通用无码元数据
- JavDB (无码版) — 通过番号检测自动路由

数据流：
  code → is_uncensored → 匹配前缀 → 路由到对应刮削器 → 合并结果
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.services.uncensored_utils import is_uncensored_code
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 无码前缀 → 站点适配器映射
_UNCENSORED_ADAPTERS: dict[str, str] = {
    "HEYZO": "https://www.heyzo.com",
    "TOKYO-HOT": "https://my.tokyo-hot.com",
    "1PONDO": "https://www.1pondo.tv",
    "CARIBBEANCOM": "https://www.caribbeancom.com",
    "10MUSUME": "https://www.10musume.com",
    "PACOPACOMAMA": "https://www.pacopacomama.com",
    "MKD": "https://www.mkd-ko.com",
    "MGR": "https://www.mgstage.com",
    "DQ": "https://www.dogma.co.jp",
    "LAF": "https://www.laf.jp",
    "IK": "https://www.ideal-av.com",
    "SMD": "https://www.smd-av.com",
    "T28": "https://www.t28-tokyo.com",
    "TH101": "https://www.101tokyo.com",
    "XCITY": "https://www.xcity.jp",
    "GACHI": "https://www.gachinet.com",
    "KIN8TENGOKU": "https://www.kin8tengoku.com",
    "MKY": "https://www.mky.tv",
}

# JavDB 无码搜索基址
_JAVDB_SEARCH = "https://javdb.com/search"


@register_crawler
class UncensoredAggregateCrawler(BaseCrawler):
    """无码聚合爬虫 — 自动路由到对应站点。"""

    name = "uncensored_aggregate"
    display_name = "无码聚合"
    base_url = ""

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    description = "无码聚合爬虫（自动站点路由）"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削无码番号，自动路由到对应站点。"""
        # 1. 检测是否是无码番号
        uncensored = is_uncensored_code(code)
        prefix = uncensored.prefix.upper() if uncensored else ""

        # 2. 尝试 AVSOX 通用搜索
        result = await self._scrape_avsox(code)
        if result:
            return result

        # 3. 按前缀路由到专用站点
        if prefix:
            adapter_url = _UNCENSORED_ADAPTERS.get(prefix)
            if adapter_url:
                result = await self._scrape_prefix(code, prefix, adapter_url)
                if result:
                    return result

        # 4. JavDB 通用搜索兜底
        result = await self._scrape_javdb_generic(code)
        return result

    async def _scrape_avsox(self, code: str) -> Optional[ScrapeResult]:
        """通过 AVSOX 搜索无码元数据。"""
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                search_url = f"https://www.avsox.click/cn/search/{code}"
                html = await client.get_text(search_url, headers={"User-Agent": _USER_AGENT})
                if not html:
                    return None

                soup = BeautifulSoup(html, "html.parser")
                detail_link = soup.select_one("a.movie-box")
                if not detail_link or not detail_link.get("href"):
                    return None

                detail_url = detail_link["href"]
                if not detail_url.startswith("http"):
                    detail_url = f"https://www.avsox.click{detail_url}"

                detail_html = await client.get_text(detail_url, headers={"User-Agent": _USER_AGENT})
                if not detail_html:
                    return None

                return self._parse_avsox_detail(detail_html, code)
            except Exception as e:
                logger.debug("avsox scrape failed for %s: %s", code, e)
        return None

    def _parse_avsox_detail(self, html: str, code: str) -> Optional[ScrapeResult]:
        """解析 AVSOX 详情页。"""
        soup = BeautifulSoup(html, "html.parser")
        result = ScrapeResult()
        result.code = code.upper()

        title_el = soup.select_one("h3, .movie-title, title")
        result.title = title_el.text.strip() if title_el else code

        cover_el = soup.select_one("a.bigImage img, .bigImage img, img.video-cover")
        if cover_el:
            result.cover_url = cover_el.get("src") or cover_el.get("href", "")

        # 演员
        actors_section = soup.find(text=re.compile(r"出演|演員|演員"))
        if actors_section:
            parent = actors_section.parent or actors_section.find_parent()
            if parent:
                actor_links = parent.select("a[href*='actor'], a[href*='star'], a[href*='actress']")
                result.actors = [ActorInfo(name=a.text.strip()) for a in actor_links if a.text.strip()]

        # 标签
        tag_section = soup.find(text=re.compile(r"類別|类别|Tags|Genre"))
        if tag_section:
            parent = tag_section.parent or tag_section.find_parent()
            if parent:
                result.genres = [a.text.strip() for a in parent.select("a") if a.text.strip()]

        # 发行日期
        date_section = soup.find(text=re.compile(r"發行|发行|發售|Date"))
        if date_section:
            parent = date_section.parent or date_section.find_parent()
            if parent:
                date_match = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", parent.text)
                if date_match:
                    result.release_date = date_match.group()

        result.source = "avsox"
        return result

    async def _scrape_prefix(self, code: str, prefix: str, base_url: str) -> Optional[ScrapeResult]:
        """按前缀路由到专用站点。"""
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                # 通用站点搜索模式
                search_urls = [
                    f"{base_url}/search/{code}",
                    f"{base_url}/moviepages/{code}/index.html",
                    f"{base_url}/movies/{code}",
                ]
                for url in search_urls:
                    html = await client.get_text(url, headers={"User-Agent": _USER_AGENT})
                    if html and "404" not in html and len(html) > 500:
                        result = ScrapeResult()
                        result.code = code.upper()
                        result.source = prefix.lower()

                        soup = BeautifulSoup(html, "html.parser")
                        title_el = soup.select_one("h1, title, .title")
                        result.title = title_el.text.strip() if title_el else code

                        cover_el = soup.select_one(
                            "img.cover, img.poster, img[src*='cover'], "
                            "img[src*='poster'], img[src*='cap'], "
                            'meta[property="og:image"]'
                        )
                        if cover_el:
                            if cover_el.name == "meta":
                                result.cover_url = cover_el.get("content", "")
                            else:
                                result.cover_url = cover_el.get("src", "")

                        result.studio = prefix
                        return result
            except Exception as e:
                logger.debug("prefix scrape failed for %s: %s", code, e)
        return None

    async def _scrape_javdb_generic(self, code: str) -> Optional[ScrapeResult]:
        """JavDB 通用搜索兜底。"""
        from app.services.javdb_api_client import create_client_from_config
        client = await create_client_from_config()
        try:
            movie = await client.search_movie(code)
            if movie and movie.title:
                result = ScrapeResult()
                result.code = code.upper()
                result.title = movie.title
                result.title_cn = movie.title_cn
                result.cover_url = movie.cover_url
                result.release_date = movie.date
                result.duration = movie.duration
                result.actors = [ActorInfo(name=a) for a in movie.actors]
                result.genres = movie.genres
                result.studio = movie.maker or movie.publisher
                result.source = "javdb"
                return result
        except Exception as e:
            logger.debug("javdb scrape failed for %s: %s", code, e)
        finally:
            await client.close()
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索无码内容。"""
        results: list[ScrapeResult] = []
        r = await self.scrape(keyword)
        if r:
            results.append(r)
        return results


@register_crawler
class HeyzoEnhancedCrawler(BaseCrawler):
    """HEYZO 专用增强爬虫。"""

    name = "heyzo_enhanced"
    display_name = "HEYZO Enhanced"
    base_url = "https://www.heyzo.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["HEYZO"]
    description = "HEYZO 无码专用爬虫"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        movie_id = code.upper().replace("HEYZO-", "").replace("HEYZO", "")
        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html = await client.get_text(detail_url, headers={"User-Agent": _USER_AGENT})
                if not html or "404" in html:
                    return None

                from lxml import etree
                doc = etree.fromstring(html, etree.HTMLParser())

                result = ScrapeResult()
                result.code = f"HEYZO-{movie_id}"
                result.source = "heyzo"

                title_el = doc.xpath("//h1/text() | //title/text()")
                result.title = title_el[0].strip() if title_el else code

                cover_el = doc.xpath('//img[@class="movie_image"]/@src | //img[contains(@src,"cap")]/@src')
                if cover_el:
                    result.cover_url = cover_el[0]
                    if not result.cover_url.startswith("http"):
                        result.cover_url = self.base_url + result.cover_url

                actor_els = doc.xpath('//a[contains(@href,"actor")]/text() | //a[contains(@href,"star")]/text()')
                result.actors = [ActorInfo(name=a.strip()) for a in actor_els if a.strip()]

                genre_els = doc.xpath('//a[contains(@href,"genre")]/text() | //a[contains(@href,"category")]/text()')
                result.genres = [g.strip() for g in genre_els if g.strip()]

                date_els = doc.xpath('//span[@class="date"]/text() | //span[contains(@class,"release")]/text()')
                result.release_date = date_els[0].strip() if date_els else ""

                result.studio = "HEYZO"
                return result
            except Exception as e:
                logger.debug("heyzo scrape failed for %s: %s", code, e)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        results: list[ScrapeResult] = []
        r = await self.scrape(keyword)
        if r:
            results.append(r)
        return results


@register_crawler
class OnePondoCrawler(BaseCrawler):
    """1PONDO 专用爬虫。"""

    name = "1pondo"
    display_name = "1Pondo"
    base_url = "https://www.1pondo.tv"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["1PONDO"]
    description = "1Pondo 无码专用爬虫"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        # 格式: 1PONDO-111111-111 → 提取 111111-111
        m = re.search(r"(\d{6,8})-(\d{2,5})", code)
        if not m:
            return None
        movie_id = f"{m.group(1)}-{m.group(2)}"
        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html = await client.get_text(detail_url, headers={"User-Agent": _USER_AGENT})
                if not html:
                    return None

                result = ScrapeResult()
                result.code = f"1PONDO-{movie_id}"
                result.source = "1pondo"
                result.studio = "1Pondo"

                from lxml import etree
                doc = etree.fromstring(html, etree.HTMLParser())

                title_el = doc.xpath("//h1/text() | //title/text()")
                result.title = title_el[0].strip() if title_el else code

                cover_el = doc.xpath('//img[contains(@class,"movie_image")]/@src | //meta[@property="og:image"]/@content')
                result.cover_url = cover_el[0] if cover_el else ""

                actor_els = doc.xpath('//a[contains(@href,"actor")]/text() | //a[contains(@href,"model")]/text()')
                result.actors = [ActorInfo(name=a.strip()) for a in actor_els if a.strip()]

                return result
            except Exception as e:
                logger.debug("1pondo scrape failed for %s: %s", code, e)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        results: list[ScrapeResult] = []
        r = await self.scrape(keyword)
        if r:
            results.append(r)
        return results
