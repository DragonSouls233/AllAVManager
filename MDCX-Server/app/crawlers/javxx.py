"""JavXX 爬虫

详情页 URL: https://javxx.to/cn/v/{CODE_lowercase}
搜索 URL:  https://javxx.to/zh/search/{keyword}

基于 Rust 参考: ref18-javm/src-tauri/src/resource_scrape/sources/javxx.rs
"""

import logging
import re
from datetime import date
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

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    m = _DATE_RE.search(s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@register_crawler
class JavxxCrawler(BaseCrawler):
    name = "javxx"
    display_name = "JavXX"
    base_url = "https://javxx.to/cn/v"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav"]
    supported_prefixes = []
    description = "JavXX JAV 数据库站点"
    language = "zh"
    requires_proxy = False

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        code_upper = code.strip().upper()
        code_lower = code_upper.lower()
        detail_url = f"https://javxx.to/cn/v/{code_lower}"

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if ctx:
            user_headers = ctx.get_headers("javxx.to")
            if user_headers:
                headers.update(user_headers)

        try:
            async with AsyncHttpClient() as client:
                html_text = await client.get_text(detail_url, headers=headers)

                if not html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text.encode() if isinstance(html_text, str) else html_text,
                                        etree.HTMLParser())

                title_el = html.xpath("//h1[@class='title']/text()")
                if not title_el:
                    self.mark_error()
                    return None

                title = title_el[0].strip()
                title = title.replace(code_upper, "").strip("-_ ,，　：:")

                result = self._parse_detail_section(html)
                if result:
                    self.mark_success()
                return result

        except Exception as e:
            self.mark_error()
            logger.debug(f"JavXX {code_upper} 刮削失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = f"https://javxx.to/zh/search/{keyword}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return []

                html = etree.fromstring(html_text.encode() if isinstance(html_text, str) else html_text,
                                        etree.HTMLParser())
                results: list[ScrapeResult] = []

                search_result_items = html.xpath('//a[contains(@href, "/cn/v/") or contains(@href, "/zh/v/")]')
                for a in search_result_items:
                    href = a.get("href", "")
                    match = re.search(r"/(?:cn|zh)/v/([A-Za-z0-9_-]+)", href)
                    if not match:
                        continue
                    code = match.group(1).strip().upper()
                    title = " ".join(a.xpath(".//text()")).strip()
                    title = title.replace(code, "").strip("-_")
                    if not title:
                        continue
                    results.append(ScrapeResult(
                        code=code,
                        title=title,
                        source=self.name,
                        is_exact_match=False,
                    ))

                return results[:20]

            except Exception as e:
                logger.debug(f"JavXX 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _parse_detail_section(self, html: etree._Element) -> Optional[ScrapeResult]:
        detail_el = self._find_detail_root(html)
        if detail_el is None:
            return None

        title_el = html.xpath("//h1[@class='title']/text()")
        title = title_el[0].strip() if title_el else ""
        code_upper = self._normalize_code(title)

        premiere = self._get_field_value(detail_el, ["发布日期", "发行日期"])
        release_date = _parse_date(premiere or "")

        duration = self._parse_duration(self._get_field_value(detail_el, ["时长"]))

        actress_links = detail_el.xpath(
            ".//a[contains(@href, '/actresses/') or contains(@href, '/stars/')]/text()"
        )
        actress_names = [t.strip() for t in actress_links if t.strip()]

        director_links = detail_el.xpath(
            ".//a[contains(@href, '/directors/')]/text()"
        )
        director_names = [t.strip() for t in director_links if t.strip()]

        studio_links = detail_el.xpath(
            ".//a[contains(@href, '/makers/')]/text()"
        )
        studio = studio_links[0].strip() if studio_links else ""

        series_links = detail_el.xpath(
            ".//a[contains(@href, '/series/')]/text()"
        )
        series = series_links[0].strip() if series_links else ""

        censored = "censored" in title
        uncensored = "uncensored" in title

        tag_links = detail_el.xpath(
            ".//a[contains(@href, '/genres/') or contains(@href, '/tags/')]"
        )
        tag_names = []
        for a in tag_links:
            href = a.get("href", "")
            if "censored" in href or "uncensored" in href:
                continue
            text = " ".join(a.xpath(".//text()")).strip()
            if text and text not in tag_names:
                tag_names.append(text)

        if not code_upper and not title:
            return None

        actor_infos = [ActorInfo(name=n) for n in actress_names]

        extra_data = {}
        if series:
            extra_data["series"] = series

        return ScrapeResult(
            code=code_upper,
            title=title,
            source=self.name,
            source_url=f"https://javxx.to/cn/v/{code_upper.lower()}",
            studio=studio,
            directors=director_names,
            release_date=release_date,
            duration=duration,
            plot="",
            genres=tag_names,
            tags=tag_names,
            actors=actor_infos,
            all_actors=actress_names,
            cover_url="",
            poster_url="",
            is_mosaic=None if not (censored or uncensored) else True,
            is_uncensored=uncensored,
            is_chinese=None,
            raw_data=extra_data,
        )

    def _normalize_code(self, raw: str) -> str:
        parts = re.split(r"[-_/\\、]", raw)
        for part in parts:
            p = part.upper()
            if re.fullmatch(r"[A-Z]+\d+", p):
                return p
        return raw.upper()

    def _parse_duration(self, text: str) -> Optional[int]:
        if not text:
            return None
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else None

    def _get_field_value(self, detail_el: etree._Element, labels: list[str]) -> Optional[str]:
        for label in labels:
            rows = detail_el.xpath(".//tr")
            for row in rows:
                text = " ".join(row.xpath(".//text()")).strip()
                if label in text:
                    val = text.split(label)[-1].strip("-_ :,，：")
                    return val or None
        return None

    def _find_detail_root(self, html: etree._Element) -> Optional[etree._Element]:
        detail_sections = html.xpath(
            "//div[contains(@class, 'detail')] | "
            "//div[contains(@class, 'details')] | "
            "//section[contains(@class, 'detail')] | "
            "//section[contains(@class, 'details')]"
        )

        candidates: list[tuple[float, etree._Element]] = []
        for el in detail_sections:
            content = " ".join(el.xpath(".//text()")).lower()
            score = 0.0
            if "详情" in content:
                score += 2.0
            if "发布日期" in content:
                score += 3.0
            if "时长" in content:
                score += 1.5
            if "演员" in content:
                score += 0.8
            if score >= 3.0:
                candidates.append((score, el))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1] if candidates else None
