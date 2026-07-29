"""欧美场景聚合刮削器 — 一站覆盖所有欧美站点。

数据源（优先级链）：
1. IAFD 场景搜索 — 最全的欧美元数据库
2. ThePornDB API — 通用欧美元数据 API
3. Aylo API — Brazzers / Reality Kings / Mofos 等 20+ 品牌
4. Vixen GraphQL — Vixen / Blacked / Tushy / Deeper 等 9 品牌

使用方式：
  crawler = WesternAggregateCrawler()
  result = await crawler.scene_by_name(title, brand=None)
"""

import json
import re
from typing import Optional
from urllib.parse import quote_plus

from lxml import html as lxml_html

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.services.western_utils import (
    AYLO_BRANDS,
    VIXEN_SITES,
    is_scene_match,
    normalize_scene_url,
    extract_brand_from_url,
)
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# IAFD 场景搜索
# ---------------------------------------------------------------------------

_IAFD_BASE = "https://www.iafd.com"
_IAFD_SEARCH = f"{_IAFD_BASE}/results.asp?searchtype=comprehensive&searchstring={{query}}"


async def _search_iafd_scene(title: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    """通过 IAFD 搜索欧美场景。

    IAFD 是欧美最大的成人影像数据库，覆盖所有品牌。
    """
    try:
        url = _IAFD_SEARCH.format(query=quote_plus(title))
        html_text = await client.get_text(url, headers={"User-Agent": _USER_AGENT})
        if not html_text:
            return None

        doc = lxml_html.fromstring(html_text)

        # 搜索结果表
        rows = doc.xpath('//table[@class="maintableresults"]//tr')
        if not rows:
            return None

        # 找标题匹配的行
        best_row = None
        best_score = 0.0
        for row in rows:
            link = row.xpath('.//a[contains(@href, "title")]')
            if not link:
                link = row.xpath('.//a')
            if link:
                row_title = link[0].text_content().strip()
                score = sum(1 for w in title.lower().split() if w in row_title.lower())
                if score > best_score:
                    best_score = score
                    best_row = row

        if not best_row or best_score < 2:
            return None

        # 提取链接
        link_el = best_row.xpath('.//a[contains(@href, "title")]')
        if not link_el:
            link_el = best_row.xpath('.//a')
        if not link_el:
            return None

        href = link_el[0].get("href", "")
        if href:
            detail_url = _IAFD_BASE + "/" + href.lstrip("/")
            return await _parse_iafd_detail(detail_url, client)

    except Exception as e:
        logger.debug("iafd scene search failed: %s", e)
    return None


async def _parse_iafd_detail(url: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    """解析 IAFD 场景详情页。"""
    try:
        html_text = await client.get_text(url, headers={"User-Agent": _USER_AGENT})
        if not html_text:
            return None

        doc = lxml_html.fromstring(html_text)
        result = ScrapeResult()
        result.source = "iafd"

        # 标题
        h1 = doc.xpath("//h1/text()")
        result.title = h1[0].strip() if h1 else ""

        # 发行日期
        date_texts = doc.xpath(
            '//p[@class="bioheading"][contains(text(),"Release Date")]/'
            'following-sibling::p[@class="biodata"][1]/text()'
        )
        if date_texts:
            result.release_date = date_texts[0].strip()

        # 工作室
        studio_texts = doc.xpath(
            '//p[@class="bioheading"][contains(text(),"Studio")]/'
            'following-sibling::p[@class="biodata"][1]//text()'
        )
        if studio_texts:
            result.studio = "".join(studio_texts).strip()

        # 演员
        actor_links = doc.xpath(
            '//p[@class="bioheading"][contains(text(),"Performer")]/'
            'following-sibling::p[@class="biodata"][1]/a'
        )
        result.actors = []
        for a in actor_links:
            name = a.text_content().strip()
            if name and name.lower() not in ("n/a", "unknown", ""):
                result.actors.append(ActorInfo(name=name))

        # 时长
        duration_texts = doc.xpath(
            '//p[@class="bioheading"][contains(text(),"Running Time")]/'
            'following-sibling::p[@class="biodata"][1]/text()'
        )
        if duration_texts:
            m = re.search(r"(\d+)", duration_texts[0])
            if m:
                result.duration = int(m.group(1)) * 60  # 转为秒

        # 评分
        rating_texts = doc.xpath(
            '//p[@class="bioheading"][contains(text(),"Rating")]/'
            'following-sibling::p[@class="biodata"][1]/text()'
        )
        if rating_texts:
            m = re.search(r"([\d.]+)", rating_texts[0])
            if m:
                result.rating = float(m.group(1))

        # 封面（IAFD 的封面通过 CSS background-image 设置）
        cover_div = doc.xpath('//div[@id="headshot"]')
        if cover_div:
            style = cover_div[0].get("style", "")
            m = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
            if m:
                result.cover_url = _IAFD_BASE + "/" + m.group(1).lstrip("/")

        if result.title:
            return result
    except Exception as e:
        logger.debug("iafd detail parse failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# ThePornDB API 搜索
# ---------------------------------------------------------------------------

_TPDB_API = "https://api.theporndb.net"
_TPDB_SEARCH = f"{_TPDB_API}/scenes?q={{query}}"
_TPDB_DETAIL = f"{_TPDB_API}/scenes/{{slug}}"


async def _search_theporndb(title: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    """通过 ThePornDB API 搜索欧美场景。"""
    try:
        url = _TPDB_SEARCH.format(query=quote_plus(title))
        r = await client.get(url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT})
        if not r:
            return None
        try:
            data = r.json()
        except (json.JSONDecodeError, TypeError):
            return None

        scenes = data.get("data", []) if isinstance(data, dict) else []
        if not scenes:
            return None

        best_scene = scenes[0]

        result = ScrapeResult()
        result.source = "theporndb"
        result.title = best_scene.get("title", title)
        result.studio = best_scene.get("site", {}).get("name", "")
        result.release_date = best_scene.get("date", "")
        result.duration = best_scene.get("duration", 0)
        result.cover_url = best_scene.get("background", {}).get("large", "")
        result.poster_url = best_scene.get("posters", {}).get("large", "")

        actors_raw = best_scene.get("performers", [])
        result.actors = [
            ActorInfo(name=a.get("name", "")) for a in actors_raw if a.get("name")
        ]

        tags_raw = best_scene.get("tags", [])
        result.genres = [t.get("name", "") for t in tags_raw if t.get("name")]

        return result
    except Exception as e:
        logger.debug("theporndb search failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# 爬虫注册
# ---------------------------------------------------------------------------


@register_crawler
class WesternAggregateCrawler(BaseCrawler):
    """欧美聚合爬虫 — IAFD + ThePornDB + Aylo 聚合搜索。"""

    name = "western_aggregate"
    display_name = "欧美聚合"
    base_url = ""

    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    description = "欧美聚合爬虫（IAFD + ThePornDB + Aylo）"
    language = "en"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        from app.config.manager import get_config
        cfg = get_config()
        self._proxy = cfg.proxy.http or cfg.proxy.socks5 or None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """按标题/URL 刮削欧美场景。

        同时支持：
        - URL 格式: https://www.brazzers.com/video/12345
        - 标题搜索: "Busty Mom Seduces Son"
        """
        # 如果是 URL，提取品牌和标题
        brand = extract_brand_from_url(code)
        if brand:
            logger.info("western scrape: brand=%s from url=%s", brand, code)

        # 1. IAFD 搜索（最全数据库）
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            result = await _search_iafd_scene(code, client)
            if result:
                logger.info("western scrape %s: found via iafd", code)
                return result

        # 2. ThePornDB API 搜索
        async with AsyncHttpClient(timeout=15, proxy=self._proxy) as client:
            result = await _search_theporndb(code, client)
            if result:
                logger.info("western scrape %s: found via theporndb", code)
                return result

        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索欧美内容。"""
        results: list[ScrapeResult] = []
        r = await self.scrape(keyword)
        if r:
            results.append(r)
        return results


@register_crawler
class WesternBulkSearcher(BaseCrawler):
    """欧美批量搜索 — 同时搜索 IAFD 和 ThePornDB。"""

    name = "western_bulk"
    display_name = "欧美批量"
    base_url = ""

    priority = CrawlerPriority.LOW
    supported_types = ["western"]
    description = "欧美批量搜索（IAFD + ThePornDB 并行）"
    language = "en"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        import asyncio

        results: list[ScrapeResult] = []

        async def _try_iafd():
            async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
                return await _search_iafd_scene(keyword, client)

        async def _try_tpdb():
            async with AsyncHttpClient(timeout=15, proxy=self._proxy) as client:
                return await _search_theporndb(keyword, client)

        for future in asyncio.as_completed([_try_iafd(), _try_tpdb()]):
            try:
                r = await future
                if r:
                    results.append(r)
            except Exception:
                pass

        return results
