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
        # 取 cookie + 代理（fix23：javdb_new 之前完全裸请求，必被 CF 挡）
        from app.utils.cookie_manager import get_cookie_headers
        cookie_headers = get_cookie_headers("javdb")

        async with AsyncHttpClient() as client:
            try:
                await self._throttle()

                # 搜索
                search_url = f"{self.base_url}/search?q={code}&locale=zh"
                html_text = await client.get_text(search_url, headers=cookie_headers)
                if not html_text:
                    return None

                html = Selector(html_text)
                html_text_lower = html_text.lower()

                # 检查封锁
                if "ray-id" in html_text_lower:
                    logger.warning("JavDB blocked by Cloudflare")
                    return None

                # 获取搜索结果
                res_list = html.xpath("//a[contains(@class,'box')]")
                if not res_list:
                    return None

                detail_url = None
                number_upper = code.upper()
                clean_number = number_upper.replace(".", "").replace("-", "").replace(" ", "")

                for each in res_list:
                    href = each.xpath("@href").get()
                    title = each.xpath("div[@class='video-title']/strong/text()").get()
                    meta = each.xpath("div[@class='meta']/text()").get()

                    if href and title:
                        # 精确匹配
                        if number_upper in title.upper():
                            detail_url = urljoin(self.base_url, href) + "?locale=zh"
                            break
                        # 模糊匹配
                        clean_content = (title + (meta or "")).upper().replace("-", "").replace(".", "").replace(" ", "")
                        if clean_number in clean_content:
                            detail_url = urljoin(self.base_url, href) + "?locale=zh"

                if not detail_url:
                    return None

                # 获取详情页
                await self._throttle()
                html_text = await client.get_text(detail_url, headers=cookie_headers)
                if not html_text:
                    return None

                html = Selector(html_text)

                # 解析字段
                title = self._extract_text(html, 'string(//h2[@class="title is-4"]/strong[@class="current-title"])')
                if not title:
                    return None

                original_title = self._extract_text(
                    html, 'string(//h2[@class="title is-4"]/span[@class="origin-title"])'
                )

                # 番号
                number = self._extract_text(
                    html, '//a[@class="button is-white copy-to-clipboard"]/@data-clipboard-text'
                ) or code

                # 演员
                actors = []
                for name in html.css("span:has(strong.female)").xpath(
                    "//strong[contains(@class, 'female')]/preceding-sibling::a/text()"
                ).getall():
                    name = name.strip()
                    if name:
                        actors.append(ActorInfo(name=name))

                # 制作商
                studio = self._extract_text(
                    html,
                    '//strong[contains(text(),"片商:")]/../span/a/text()',
                    '//strong[contains(text(),"Maker:")]/../span/a/text()',
                )

                # 发行商
                publisher = self._extract_text(
                    html,
                    '//strong[contains(text(),"發行:")]/../span/a/text()',
                    '//strong[contains(text(),"Publisher:")]/../span/a/text()',
                )

                # 时长
                runtime = self._extract_text(
                    html,
                    '//strong[contains(text(),"時長")]/../span/text()',
                    '//strong[contains(text(),"Duration:")]/../span/text()',
                )
                runtime = runtime.replace(" 分鍾", "").replace(" minute(s)", "").strip()

                # 系列
                series = self._extract_text(
                    html,
                    '//strong[contains(text(),"系列:")]/../span/a/text()',
                    '//strong[contains(text(),"Series:")]/../span/a/text()',
                )

                # 发行日期
                release = self._extract_text(
                    html,
                    '//strong[contains(text(),"日期:")]/../span/text()',
                    '//strong[contains(text(),"Released Date:")]/../span/text()',
                )

                # 标签
                genres = []
                for tag in html.xpath(
                    '//strong[contains(text(),"類別:")]/../span/a/text()'
                ).getall():
                    tag = tag.replace("\xa0", "").replace("'", "").replace(" ", "").strip()
                    if tag and tag not in genres:
                        genres.append(tag)

                # 封面
                cover = self._extract_text(html, "//img[@class='video-cover']/@src")
                poster = cover.replace("/covers/", "/thumbs/") if cover else None

                # 样图
                sample_images = html.xpath(
                    "//div[@class='tile-images preview-images']/a[@class='tile-item']/@href"
                ).getall()

                # 预告片
                trailer = self._extract_text(html, "//video[@id='preview-video']/source/@src")
                if trailer and trailer.startswith("//"):
                    trailer = "https:" + trailer

                # 评分
                score_text = self._extract_text(html, "//span[@class='score-stars']/../text()")
                rating = None
                if score_text:
                    if m := re.search(r"(\d+\.?\d*)", score_text):
                        rating = float(m.group(1))

                # 导演
                director = self._extract_text(
                    html,
                    '//strong[contains(text(),"導演:")]/../span/a/text()',
                    '//strong[contains(text(),"Director:")]/../span/a/text()',
                )

                # 判断有码/无码
                is_uncensored = any(kw in title for kw in ["無碼", "無修正", "Uncensored"])

                return ScrapeResult(
                    code=number,
                    title=title,
                    source=self.name,
                    studio=studio,
                    maker=publisher,
                    series=series,
                    release_date=self._parse_date(release),
                    duration=int(runtime) if runtime and runtime.isdigit() else None,
                    plot="",
                    genres=genres,
                    actors=actors,
                    cover_url=cover,
                    poster_url=poster,
                    trailer_url=trailer,
                    sample_images=sample_images,
                    rating=rating,
                    raw_data={"director": director, "original_title": original_title},
                )

            except Exception as e:
                logger.error(f"JavDB scrape error for {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

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
