"""
FC2Club 爬虫 - 从 fc2club.top 刮削 FC2 内容
"""

import re
from typing import Optional

from lxml import etree

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient


@register_crawler
class FC2ClubCrawler(BaseCrawler):
    """FC2Club 爬虫"""

    name = "fc2club"
    display_name = "FC2Club"
    base_url = "https://fc2club.top"

    priority = CrawlerPriority.NORMAL
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-"]
    description = "FC2Club FC2 PPV 内容站点"
    language = "zh"
    requires_proxy = False

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        Args:
            code: 番号（如 FC2-123456）

        Returns:
            ScrapeResult 刮削结果
        """
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        async with AsyncHttpClient() as client:
            try:
                detail_url = f"{self.base_url}/html/FC2-{number_id}.html"

                html_text = await client.get_text(detail_url)
                html = etree.fromstring(html_text, etree.HTMLParser())

                # 检查是否找到页面
                title = self._get_title(html, number_id)
                if not title:
                    return None

                # 解析详情页
                result = self._parse_detail_page(html, code, number_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                self.mark_error()
                raise e

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        搜索番号

        Args:
            keyword: 搜索关键词

        Returns:
            搜索结果列表
        """
        # FC2Club 搜索功能暂不实现
        return []

    def _extract_number_id(self, code: str) -> Optional[str]:
        """从番号提取纯数字ID"""
        code = code.upper()
        code = code.replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()

        if code.isdigit():
            return code

        return None

    def _get_title(self, html: etree._Element, number_id: str) -> str:
        """获取标题，移除 FC2-{number} 前缀"""
        result = html.xpath("//h3/text()")
        if result:
            title = result[0].strip()
            title = title.replace(f"FC2-{number_id} ", "").replace(f"FC2-{number_id}", "")
            return title.strip()
        return ""

    def _parse_detail_page(
        self,
        html: etree._Element,
        code: str,
        number_id: str,
    ) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            title = self._get_title(html, number_id)
            if not title:
                return None

            # 封面和额外剧照
            cover_url, extrafanart = self._get_cover_and_extrafanart(html)

            # 厂商（卖家信息）
            studio = self._get_studio(html)

            # 演员
            actors = self._get_actors(html)

            # 标签
            genres = self._get_genres(html)

            # 评分
            rating = self._get_score(html)

            # 是否无码
            is_uncensored = self._get_mosaic(html)

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio=studio,
                publisher=studio,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                extrafanart=extrafanart,
                rating=rating,
                is_uncensored=is_uncensored,
                series="FC2系列",
            )

        except Exception:
            return None

    def _get_cover_and_extrafanart(self, html: etree._Element) -> tuple[Optional[str], list[str]]:
        """获取封面和额外剧照"""
        result = html.xpath('//img[@class="responsive"]/@src')
        if not result:
            return None, []

        extrafanart = []
        for res in result:
            url = res.replace("../uploadfile", f"{self.base_url}/uploadfile")
            extrafanart.append(url)

        cover_url = extrafanart[0] if extrafanart else None
        return cover_url, extrafanart

    def _get_studio(self, html: etree._Element) -> Optional[str]:
        """获取卖家信息作为厂商"""
        result = html.xpath('//strong[contains(text(), "卖家信息")]/../a/text()')
        if result:
            studio = result[0].strip()
            studio = studio.replace("本资源官网地址", "")
            return studio if studio else None
        return None

    def _get_actors(self, html: etree._Element) -> list[ActorInfo]:
        """获取演员列表"""
        results = html.xpath('//strong[contains(text(), "女优名字")]/../a/text()')
        actors = []
        for name in results:
            name = name.strip()
            if name:
                actors.append(ActorInfo(name=name))
        return actors

    def _get_genres(self, html: etree._Element) -> list[str]:
        """获取标签"""
        results = html.xpath('//strong[contains(text(), "影片标签")]/../a/text()')
        return [r.strip() for r in results if r.strip()]

    def _get_score(self, html: etree._Element) -> Optional[float]:
        """获取评分"""
        try:
            result = html.xpath('//strong[contains(text(), "影片评分")]/../text()')
            if result:
                numbers = re.findall(r"\d+", result[0])
                if numbers:
                    return float(numbers[0])
        except Exception:
            pass
        return None

    def _get_mosaic(self, html: etree._Element) -> Optional[bool]:
        """获取是否有码（无码=True）"""
        result = html.xpath('//h5/strong[contains(text(), "资源参数")]/../text()')
        if result:
            text = str(result)
            return "无码" in text
        return None
