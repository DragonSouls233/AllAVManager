"""
FC2 系列扩展爬虫

支持站点：
- FC2 Fanclub (会员内容): https://fc2club.com
- FC2 Video: https://video.fc2.com
- FC2 Search API: 搜索功能
"""

import json
import re
import logging
from datetime import date
from typing import Optional
from urllib.parse import quote

from lxml import etree

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, CrawlerStatus, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


# ==========================================
# FC2 Fanclub 爬虫
# ==========================================

@register_crawler
class FC2FanclubCrawler(BaseCrawler):
    """
    FC2 Fanclub 爬虫

    FC2 会员内容平台
    搜索: https://fc2club.com/search/?kw={number}
    详情: https://fc2club.com/article/{id}/
    """

    name = "fc2fanclub"
    display_name = "FC2 Fanclub"
    base_url = "https://fc2club.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-PPV", "FC2PPV"]
    description = "FC2 Fanclub 会员内容"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 FC2 Fanclub"""
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        # 先搜索找到详情页
        search_url = f"{self.base_url}/search/?kw={number_id}"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(search_url)
                if not html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找详情页链接
                links = html.xpath('//a[contains(@href, "/article/")]/@href')
                detail_url = None
                for link in links:
                    if number_id in link:
                        detail_url = f"{self.base_url}{link}" if not link.startswith("http") else link
                        break

                # 取第一个结果
                if not detail_url and links:
                    detail_url = f"{self.base_url}{links[0]}" if not links[0].startswith("http") else links[0]

                if not detail_url:
                    self.mark_error()
                    return None

                # 获取详情页
                detail_text = await client.get_text(detail_url)
                if not detail_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(detail_text, etree.HTMLParser())
                result = self._parse_detail(html, code, number_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"FC2 Fanclub 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _extract_number_id(self, code: str) -> Optional[str]:
        """提取 FC2 ID"""
        code = code.upper()
        code = code.replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
        if code.isdigit():
            return code
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 FC2 内容"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, number_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//h2[@class="article-title"]//text()')
            if not title_elem:
                title_elem = html.xpath('//h1//text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="article-image"]//img/@src')
            if not cover_elem:
                cover_elem = html.xpath('//img[@class="thumb"]/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//time[@class="article-date"]/@datetime')
            release_date = None
            if date_elem:
                date_str = date_elem[0]
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[@class="tag"]/text()')
            for g in genre_elems:
                g = g.strip()
                if g:
                    genres.append(g)

            # 简介
            plot_elem = html.xpath('//div[@class="article-content"]//text()')
            plot = "".join(plot_elem).strip() if plot_elem else None

            return ScrapeResult(
                code=code,
                title=title,
                original_title=title,
                source=self.name,
                studio="FC2 Fanclub",
                release_date=release_date,
                plot=plot,
                genres=genres,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"FC2 Fanclub 解析失败 {code}: {e}")
            return None


# ==========================================
# FC2 Video 爬虫
# ==========================================

@register_crawler
class FC2VideoCrawler(BaseCrawler):
    """
    FC2 Video 爬虫

    FC2 视频平台（非PPV内容）
    详情: https://video.fc2.com/a/content/{id}
    """

    name = "fc2video"
    display_name = "FC2 Video"
    base_url = "https://video.fc2.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-PPV", "FC2PPV"]
    description = "FC2 Video 视频内容"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 FC2 Video"""
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        detail_url = f"{self.base_url}/a/content/{number_id}"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text or "不存在" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, number_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"FC2 Video 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _extract_number_id(self, code: str) -> Optional[str]:
        """提取 FC2 ID"""
        code = code.upper()
        code = code.replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
        if code.isdigit():
            return code
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 FC2 内容"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, number_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//h3[@class="items_article_Title"]/text()')
            if not title_elem:
                title_elem = html.xpath('//h1//text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="items_article_MainitemThumb"]/span/img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//span[contains(text(), "販売日")]/../text()')
            release_date = None
            if date_elem:
                date_str = date_elem[0].strip()
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 时长
            duration_elem = html.xpath('//span[contains(text(), "動画時間")]/../text()')
            duration = None
            if duration_elem:
                duration_str = duration_elem[0].strip()
                if match := re.search(r"(\d+)", duration_str):
                    duration = int(match.group(1))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[@class="tag tagTag"]/text()')
            for g in genre_elems:
                g = g.strip()
                if g and g != "無修正":
                    genres.append(g)

            # 简介
            plot_elem = html.xpath('//section[contains(@class, "items_article_Contents")]//text()')
            plot = " ".join([t.strip() for t in plot_elem if t.strip()]) if plot_elem else None

            # 评分
            rating = None
            rating_elem = html.xpath('//script[@type="application/ld+json"]/text()')
            if rating_elem:
                try:
                    data = json.loads(rating_elem[0])
                    if "aggregateRating" in data:
                        rating_value = data["aggregateRating"].get("ratingValue")
                        if rating_value:
                            rating = float(rating_value)
                except (json.JSONDecodeError, ValueError):
                    pass

            return ScrapeResult(
                code=code,
                title=title,
                original_title=title,
                source=self.name,
                studio="FC2",
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=genres,
                cover_url=cover_url,
                poster_url=cover_url,
                rating=rating,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"FC2 Video 解析失败 {code}: {e}")
            return None


# ==========================================
# FC2 Search API 爬虫
# ==========================================

@register_crawler
class FC2SearchCrawler(BaseCrawler):
    """
    FC2 搜索 API 爬虫

    通过 FC2 搜索 API 查找内容
    """

    name = "fc2search"
    display_name = "FC2 Search"
    base_url = "https://adult.contents.fc2.com"

    priority = CrawlerPriority.LOW
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-PPV", "FC2PPV"]
    description = "FC2 搜索API"
    language = "ja"
    requires_proxy = False

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 FC2 Search"""
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        # FC2 详情页
        detail_url = f"{self.base_url}/article/{number_id}/"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "not found" in html_text.lower():
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, number_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"FC2 Search 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _extract_number_id(self, code: str) -> Optional[str]:
        """提取 FC2 ID"""
        code = code.upper()
        code = code.replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
        if code.isdigit():
            return code
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 FC2 内容"""
        # 可通过 API 搜索，这里简化处理
        return []

    def _parse_detail(self, html: etree._Element, code: str, number_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//div[@data-section="userInfo"]//h3/span/../text()')
            if not title_elem:
                title_elem = html.xpath('//h3/text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//ul[@class="items_article_SampleImagesArea"]/li/a/@href')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//span[contains(text(), "販売日")]/../text()')
            release_date = None
            if date_elem:
                date_str = date_elem[0].strip()
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 时长
            duration_elem = html.xpath('//span[contains(text(), "動画時間")]/../text()')
            duration = None
            if duration_elem:
                duration_str = duration_elem[0].strip()
                if match := re.search(r"(\d+)", duration_str):
                    duration = int(match.group(1))

            # 演员
            actors = []
            actor_elems = html.xpath('//a[@class="tag tagActor"]/text()')
            for name in actor_elems:
                name = name.strip()
                if name:
                    actors.append(ActorInfo(name=name))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[@class="tag tagTag"]/text()')
            for g in genre_elems:
                g = g.strip()
                if g and g != "無修正":
                    genres.append(g)

            # 简介
            plot_elem = html.xpath('//section[contains(@class, "items_article_Contents")]//text()')
            plot = " ".join([t.strip() for t in plot_elem if t.strip()]) if plot_elem else None

            # 卖家
            studio_elem = html.xpath('//div[@class="items_article_headerInfo"]/ul/li[last()]/a/text()')
            studio = studio_elem[0].strip() if studio_elem else "FC2"

            return ScrapeResult(
                code=code,
                title=title,
                original_title=title,
                source=self.name,
                studio=studio,
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"FC2 Search 解析失败 {code}: {e}")
            return None
