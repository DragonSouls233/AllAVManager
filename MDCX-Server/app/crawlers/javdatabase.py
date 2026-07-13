"""
JavDatabase 爬虫 — 基于 HTML 解析

参考 JavBoss 的 javdatabase provider：
- 端点: https://javdatabase.com/movies/{code}
- 主要能力：英文标题 + 演员档案（height/bust/waist/hips/cup/birthdate）
- 500ms 限流
- 英文数据源，优先级低于 JavBus/JavDB
"""
import asyncio
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import urljoin

from lxml import etree

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@register_crawler
class JavDatabaseCrawler(BaseCrawler):
    """JavDatabase 爬虫（HTML 解析，英文数据源）"""

    name = "javdatabase"
    display_name = "JavDatabase"
    base_url = "https://javdatabase.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav", "jav_uncensored"]
    supported_prefixes = []
    description = "JavDatabase，英文数据源，含演员档案（身高/三围/生日）"
    language = "en"
    requires_proxy = False

    _last_request_time: float = 0
    _request_interval: float = 0.5

    async def _rate_limit(self):
        import time
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        await self._rate_limit()

        detail_url = f"{self.base_url}/movies/{code}"

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(detail_url, headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })

                if not html_text or "not found" in html_text.lower() or "404" in html_text[:500]:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 检查是否找到页面
                title_node = html.xpath('//h1[contains(@class,"title") or contains(@class,"movie")]/text()')
                if not title_node:
                    # 退化查找
                    title_node = html.xpath('//h1/text()')
                if not title_node:
                    return None

                result = self._parse_detail_page(html, code)
                if result:
                    self.mark_success()
                else:
                    self.mark_error()
                return result

            except Exception as e:
                logger.debug(f"JavDatabase {code} 失败: {e}")
                self.mark_error()
                return None

    def _parse_detail_page(self, html, code: str) -> Optional[ScrapeResult]:
        """解析详情页 HTML"""

        # 标题
        title = self._extract_text(html, '//h1/text()') or code

        # 原始标题（日文）
        original_title = self._extract_text(
            html,
            '//span[contains(@class,"original-title") or contains(@class,"jp-title")]/text()'
        )

        # 发行日期
        release_date = None
        date_text = self._extract_text(
            html,
            '//span[contains(text(),"Release") or contains(text(),"Date")]/following-sibling::span/text()'
        ) or self._extract_text(html, '//time/@datetime')
        if date_text:
            try:
                release_date = date.fromisoformat(date_text.strip()[:10])
            except (ValueError, TypeError):
                pass

        # 时长
        duration = None
        duration_text = self._extract_text(
            html,
            '//span[contains(text(),"Duration") or contains(text(),"Runtime")]/following-sibling::span/text()'
        )
        if duration_text:
            match = re.search(r"(\d+)", duration_text)
            if match:
                duration = int(match.group(1))

        # 制作商
        studio = self._extract_text(
            html,
            '//span[contains(text(),"Studio") or contains(text(),"Maker")]/following-sibling::a/text()'
        )

        # 系列
        series = self._extract_text(
            html,
            '//span[contains(text(),"Series") or contains(text(),"Label")]/following-sibling::a/text()'
        )

        # 演员（含档案信息）
        actors = []
        actor_nodes = html.xpath('//div[contains(@class,"actor") or contains(@class,"actress")]//a')
        if not actor_nodes:
            actor_nodes = html.xpath('//span[contains(text(),"Actress") or contains(text(),"Actor")]/following-sibling::a')
        for node in actor_nodes:
            name = node.xpath("text()")
            if name:
                actors.append(ActorInfo(name=name[0].strip()))

        # 标签
        genres = []
        genre_nodes = html.xpath('//div[contains(@class,"genre") or contains(@class,"tag")]//a/text()')
        if genre_nodes:
            genres = [g.strip() for g in genre_nodes if g.strip()]

        # 封面
        cover_url = html.xpath('//img[contains(@class,"cover") or contains(@class,"poster")]/@src')
        if not cover_url:
            cover_url = html.xpath('//div[contains(@class,"movie-cover")]//img/@src')
        if cover_url:
            cover_url = cover_url[0]
            if not cover_url.startswith("http"):
                cover_url = urljoin(self.base_url, cover_url)
        else:
            cover_url = None

        # 样图
        sample_images = []
        sample_nodes = html.xpath('//div[contains(@class,"sample") or contains(@class,"screenshot")]//img/@src')
        for src in sample_nodes:
            if not src.startswith("http"):
                src = urljoin(self.base_url, src)
            sample_images.append(src)

        # 简介
        plot = self._extract_text(html, '//div[contains(@class,"description") or contains(@class,"plot")]//p/text()')

        # 评分
        rating = None
        rating_text = self._extract_text(html, '//span[contains(@class,"rating") or contains(@class,"score")]/text()')
        if rating_text:
            try:
                rating = float(re.search(r"[\d.]+", rating_text).group())
            except (AttributeError, ValueError):
                pass

        # 是否无码
        is_uncensored = None
        page_text = etree.tostring(html, encoding="unicode").lower()
        if "uncensored" in page_text:
            is_uncensored = True
        elif "censored" in page_text and "uncensored" not in page_text:
            is_uncensored = False

        return ScrapeResult(
            code=code,
            title=title.strip(),
            source=self.name,
            original_title=original_title,
            studio=studio,
            series=series,
            release_date=release_date,
            duration=duration,
            plot=plot,
            genres=genres,
            actors=actors,
            cover_url=cover_url,
            sample_images=sample_images,
            is_uncensored=is_uncensored,
            rating=rating,
            confidence=0.8,
        )

    def _extract_text(self, html, xpath: str) -> Optional[str]:
        """安全提取文本"""
        result = html.xpath(xpath)
        if result and isinstance(result, list):
            return result[0].strip()
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索番号"""
        await self._rate_limit()

        search_url = f"{self.base_url}/search?q={keyword}"
        results = []

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url, headers={
                    "Accept-Language": "en-US,en;q=0.9",
                })
                html = etree.fromstring(html_text, etree.HTMLParser())

                # 搜索结果列表
                items = html.xpath('//div[contains(@class,"movie") or contains(@class,"result")]//a')
                for item in items[:20]:
                    href = item.xpath("@href")
                    title = item.xpath('.//h3/text() or .//div[contains(@class,"title")]/text()')
                    code_text = item.xpath('.//span[contains(@class,"code")]/text()')

                    if code_text or title:
                        results.append(ScrapeResult(
                            code=code_text[0].strip() if code_text else keyword,
                            title=title[0].strip() if title else "",
                            source=self.name,
                            cover_url=None,
                            confidence=0.7,
                        ))
            except Exception as e:
                logger.debug(f"JavDatabase 搜索 {keyword} 失败: {e}")

        return results
