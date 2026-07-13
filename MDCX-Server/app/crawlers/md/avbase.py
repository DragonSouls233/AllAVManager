"""
Avbase 爬虫 - 从 MDCX 新式爬虫迁移

MDCX 的 AvbaseCrawler 继承自其 BaseCrawler 类体系，
这里直接适配到我们的 BaseCrawler 接口。
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import quote, urljoin

from parsel import Selector

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@register_crawler
class AvbaseCrawler(BaseCrawler):
    """Avbase 爬虫"""

    name = "avbase"
    display_name = "Avbase"
    base_url = "https://www.avbase.net"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav"]
    supported_prefixes = []
    description = "Avbase JAV数据库站点"
    language = "ja"

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        async with AsyncHttpClient() as client:
            try:
                # 搜索
                search_url = f"{self.base_url}/works?q={quote(code)}"
                html_text = await client.get_text(search_url)
                if not html_text:
                    return None

                html = Selector(html_text)

                # 获取详情页 URL
                first_result_id = html.xpath(
                    "normalize-space(/html/body/div/div/main/div/div[2]/div[2]/div/div/div[1]/div[1]/div[1]/div)"
                ).get(default="").strip()

                detail_url = None
                if first_result_id and ":" in first_result_id:
                    detail_url = f"{self.base_url}/works/{first_result_id}"
                else:
                    href = html.xpath(
                        '(//a[starts-with(@href, "/works/") and not(starts-with(@href, "/works/date"))])[1]/@href'
                    ).get(default="")
                    if href:
                        detail_url = urljoin(self.base_url, href)

                if not detail_url:
                    return None

                # 获取详情页
                html_text = await client.get_text(detail_url)
                if not html_text:
                    return None

                html = Selector(html_text)
                next_data_text = html.xpath('//script[@id="__NEXT_DATA__"]/text()').get(default="")
                if not next_data_text:
                    return None

                next_data = json.loads(next_data_text)
                work = ((next_data.get("props") or {}).get("pageProps") or {}).get("work") or {}
                if not work:
                    return None

                products = [p for p in (work.get("products") or []) if isinstance(p, dict)]
                product = self._pick_product(products) if products else {}

                number = (work.get("work_id") or code).strip()
                title = (work.get("title") or product.get("title") or "").strip()
                outline = str(work.get("note") or "").strip()

                # 演员
                actors = []
                for cast_item in work.get("casts") or []:
                    if isinstance(cast_item, dict):
                        actor = cast_item.get("actor")
                        if isinstance(actor, dict):
                            name = str(actor.get("name") or "").strip()
                            if name:
                                actors.append(ActorInfo(name=name))

                # 标签
                genres = []
                for key in ("genres", "tags"):
                    for item in work.get(key) or []:
                        if isinstance(item, dict):
                            name = str(item.get("name") or "").strip()
                            if name and name not in genres:
                                genres.append(name)

                # 发行日期
                release = self._parse_release_date(product.get("date") or work.get("min_date") or "")

                # 时长
                runtime = self._parse_runtime((product.get("iteminfo") or {}).get("volume") or "")

                # 制作商
                studio = self._extract_nested_name(product, "maker")
                publisher = self._extract_nested_name(product, "label")
                series = self._extract_nested_name(product, "series")

                # 封面
                thumb = self._to_absolute_url(product.get("image_url") or "")
                poster = self._to_poster_url(thumb)

                # 样图
                sample_images = []
                for item in product.get("sample_image_urls") or []:
                    url = ""
                    if isinstance(item, dict):
                        url = str(item.get("l") or item.get("s") or "").strip()
                    elif isinstance(item, str):
                        url = item.strip()
                    if url:
                        abs_url = self._to_absolute_url(url)
                        if abs_url not in sample_images:
                            sample_images.append(abs_url)

                # 预告片
                trailer = self._to_absolute_url(product.get("trailer_url") or "")

                return ScrapeResult(
                    code=number,
                    title=title,
                    source=self.name,
                    studio=studio,
                    maker=publisher or studio,
                    series=series,
                    release_date=self._parse_date(release),
                    duration=int(runtime) if runtime and runtime.isdigit() else None,
                    plot=outline,
                    genres=genres,
                    actors=actors,
                    cover_url=thumb,
                    poster_url=poster,
                    trailer_url=trailer,
                    sample_images=sample_images,
                )

            except Exception as e:
                logger.error(f"Avbase scrape error for {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    def _pick_product(self, products: list[dict]) -> dict:
        if not products:
            return {}
        return max(products, key=self._product_score)

    def _product_score(self, product: dict) -> int:
        score = 0
        source = str(product.get("source") or "").lower()
        if "dmm.co.jp" in source or "fanza" in source:
            score += 20
        if product.get("image_url"):
            score += 5
        if (product.get("iteminfo") or {}).get("volume"):
            score += 2
        score += len(product.get("sample_image_urls") or [])
        return score

    @staticmethod
    def _extract_nested_name(product: dict, field: str) -> str:
        value = product.get(field)
        if isinstance(value, dict):
            return str(value.get("name") or "").strip()
        return ""

    def _to_absolute_url(self, url: str) -> str:
        if not url:
            return ""
        return urljoin(self.base_url, url)

    @staticmethod
    def _to_poster_url(thumb: str) -> str:
        if not thumb:
            return ""
        if thumb.endswith("pl.jpg"):
            return thumb[:-6] + "ps.jpg"
        return thumb

    @staticmethod
    def _parse_release_date(raw: str) -> str:
        raw = str(raw).strip()
        if not raw:
            return ""
        if match := re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw):
            return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        return raw

    @staticmethod
    def _parse_runtime(raw: str) -> str:
        raw = str(raw).strip()
        if not raw:
            return ""
        if match := re.search(r"(\d{1,2})[:：](\d{1,2})[:：](\d{1,2})", raw):
            hours, minutes = int(match.group(1)), int(match.group(2))
            total = hours * 60 + minutes
            return str(total) if total > 0 else "1"
        if match := re.search(r"\d+", raw):
            return match.group()
        return raw

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
