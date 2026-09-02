"""
123AV 爬虫

详情页 URL: https://123av.com/zh/v/{code_lowercase}
基于 Rust 参考实现: ref18-javm/src-tauri/src/resource_scrape/sources/av123.rs
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


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            normalized = s.replace("/", "-").replace(".", "-")
            return date(*map(int, normalized.split("-")[:3]))
        except (ValueError, TypeError):
            continue
    return None


@register_crawler
class Av123Crawler(BaseCrawler):
    name = "av123"
    display_name = "123AV"
    base_url = "https://123av.com"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "123AV JAV 数据库站点"
    language = "zh"
    requires_proxy = True

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        if ctx and getattr(ctx, "http_client", None) is not None:
            return await self._scrape_with_client(code, ctx.http_client, ctx)

        async with AsyncHttpClient() as client:
            return await self._scrape_with_client(code, client, ctx)

    async def _scrape_with_client(
        self,
        code: str,
        client: AsyncHttpClient,
        ctx=None,
    ) -> Optional[ScrapeResult]:
        code_upper = code.strip().upper()
        detail_url = f"{self.base_url}/zh/v/{code.lower()}"

        headers = None
        if ctx:
            headers = ctx.get_headers("123av.com")

        try:
            html_text = await client.get_text(detail_url, headers=headers)

            if "cloudflare" in html_text.lower() or "driver-verify" in html_text.lower():
                logger.debug(f"123AV {code_upper}: 遇到验证拦截，跳过")
                self.mark_error()
                return None

            html = etree.fromstring(html_text, etree.HTMLParser())
            result = self._parse_detail_page(html, code_upper)

            if result:
                self.mark_success()
            return result

        except Exception as e:
            self.mark_error()
            logger.debug(f"123AV {code_upper} 刮削失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = f"{self.base_url}/zh/search/{keyword}/"

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url)

                if "cloudflare" in html_text.lower():
                    self.mark_error()
                    return []

                html = etree.fromstring(html_text, etree.HTMLParser())
                results = []

                items = html.xpath('//a[contains(@href, "/zh/v/")]')
                seen_codes: set[str] = set()

                for a in items:
                    href = a.get("href", "")
                    title = "".join(a.xpath(".//text()")).strip()
                    code_match = re.search(r"/zh/v/([a-z0-9]+)", href)
                    if not code_match:
                        continue
                    code = code_match.group(1).upper()
                    if code in seen_codes or not title:
                        continue
                    seen_codes.add(code)
                    results.append(ScrapeResult(
                        code=code,
                        title=title,
                        source=self.name,
                        source_url=href if href.startswith("http") else f"{self.base_url}{href}",
                        confidence=0.75,
                        is_exact_match=False,
                    ))

                return results[:20]

            except Exception as e:
                logger.debug(f"123AV 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _parse_detail_page(self, html: etree._Element, code: str) -> Optional[ScrapeResult]:
        try:
            cover_url = self._get_og_image(html)
            page_url = self._get_canonical(html)
            raw_title = self._get_og_title(html)
            meta_desc = self._get_og_description(html)

            title_from_head, actors_from_head = self._parse_og_title(raw_title, code)

            detail_fields = self._extract_detail_fields(html)

            body_plot = self._get_body_description(html)
            plot = body_plot or self._clean_description(meta_desc, code)

            title = title_from_head

            premiered = detail_fields.get("发布日期") or detail_fields.get("發佈日期") or detail_fields.get("Release Date") or ""

            duration_raw = detail_fields.get("时长") or detail_fields.get("時長") or detail_fields.get("Duration") or ""
            duration = self._parse_duration(duration_raw)

            actors_from_detail = self._extract_detail_link_texts(html, ["女演员", "女優", "Actress", "演员"])
            if actors_from_detail:
                actor_names = self._dedup(actors_from_detail)
            else:
                actors_from_body = self._collect_link_texts_by_href(html, ["/actresses/", "/actress/"])
                if actors_from_body:
                    actor_names = self._dedup(actors_from_body)
                else:
                    actor_names = [a.strip() for a in actors_from_head.split(",") if a.strip()]

            genres_from_detail = self._extract_detail_link_texts(html, ["类型", "類型", "Genre", "Genres"])
            tags_from_detail = self._extract_detail_link_texts(html, ["标签", "標籤", "Tag", "Tags"])
            all_tags = genres_from_detail + tags_from_detail
            if not all_tags:
                all_tags = self._collect_link_texts_by_href(html, ["/genres/", "/genre/", "/tags/", "/tag/"])
            all_tags = self._dedup(all_tags)

            studio = self._extract_first_detail_link(
                html, ["制作人", "製作人", "制作商", "Maker", "Studio"]
            ) or self._extract_first_link_by_href(html, ["/makers/", "/maker/", "/studios/", "/studio/"])

            set_name = self._extract_first_detail_link(html, ["系列", "Series"]) or self._extract_first_link_by_href(
                html, ["/series/"]
            )

            directors = self._extract_detail_link_texts(html, ["导演", "導演", "Director"])
            if not directors:
                directors = self._collect_link_texts_by_href(html, ["/directors/", "/director/"])
                if len(directors) > 1:
                    directors = [directors[0]]

            actor_infos = [ActorInfo(name=n) for n in actor_names]

            if not title and not cover_url:
                return None

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                source_url=page_url,
                studio=studio,
                series=set_name,
                release_date=_parse_date(premiered) if premiered else None,
                duration=duration,
                plot=plot or None,
                genres=[t for t in all_tags if t],
                tags=[],
                actors=actor_infos,
                all_actors=actor_names,
                directors=[d.strip() for d in directors if d.strip()],
                cover_url=cover_url,
                poster_url=cover_url,
                is_mosaic=None,
                is_uncensored=None,
                is_chinese=None,
                raw_data={
                    "page_url": page_url,
                    "premiered_raw": premiered,
                    "duration_raw": duration_raw,
                    "studio": studio or "",
                    "set_name": set_name or "",
                    "label": "",
                },
            )

        except Exception as e:
            logger.debug(f"123AV {code} 详情页解析异常: {e}")
            return None

    def _get_og_image(self, html: etree._Element) -> Optional[str]:
        prop = html.xpath('//meta[@property="og:image"]/@content')
        return prop[0].strip() if prop else None

    def _get_canonical(self, html: etree._Element) -> Optional[str]:
        link = html.xpath('//link[@rel="canonical"]/@href')
        if link:
            return link[0].strip()
        prop = html.xpath('//meta[@property="og:url"]/@content')
        return prop[0].strip() if prop else None

    def _get_og_title(self, html: etree._Element) -> str:
        prop = html.xpath('//meta[@property="og:title"]/@content')
        if prop:
            return prop[0].strip()
        title = html.xpath("//title/text()")
        return title[0].strip() if title else ""

    def _get_og_description(self, html: etree._Element) -> str:
        prop = html.xpath('//meta[@property="og:description"]/@content')
        if prop:
            return prop[0].strip()
        desc = html.xpath('//meta[@name="description"]/@content')
        return desc[0].strip() if desc else ""

    def _get_body_description(self, html: etree._Element) -> Optional[str]:
        p = html.xpath('//div[contains(@class, "description")]/p/text()')
        if p:
            text = " ".join(p).replace("更多..", "").strip()
            return text if text else None
        p = html.xpath('//div[contains(@class, "description")]/text()')
        if p:
            text = " ".join(p).replace("更多..", "").strip()
            return text if text else None
        return None

    def _parse_og_title(self, raw: str, code_upper: str) -> tuple[str, str]:
        lower = raw.lower()
        cleaned = raw
        if "- 123av" in lower:
            idx = lower.index("- 123av")
            cleaned = raw[:idx].rstrip()
        elif "| 123av" in lower:
            idx = lower.index("| 123av")
            cleaned = raw[:idx].rstrip()
        else:
            cleaned = raw.strip()

        parts = [p.strip() for p in cleaned.split(",")]
        if len(parts) < 2:
            title = self._strip_code_and_suffix(cleaned, code_upper)
            return title, ""

        title = parts[-1].strip()
        if len(parts) == 2:
            title = self._strip_code_and_suffix(parts[1], code_upper)
            return title, ""

        actors_str = ", ".join(p for p in parts[1:-1] if p.strip())
        return title, actors_str

    @staticmethod
    def _strip_code_and_suffix(text: str, code_upper: str) -> str:
        result = text.upper().replace(code_upper, "").replace("在线观看", "").replace("在線觀看", "")
        result = result.lstrip("-  、,")
        return result.strip()

    @staticmethod
    def _clean_description(raw: str, code_upper: str) -> str:
        text = (raw or "").strip()
        patterns = [
            f"{code_upper} 在线观看并免费下载 {code_upper}。",
            f"{code_upper} 在线观看并免费下载 {code_upper.lower()}。",
            f"{code_upper} 在线观看",
        ]
        for pattern in patterns:
            idx = text.find(pattern)
            if idx >= 0:
                text = text[idx + len(pattern):].strip()
                break
        lower = text.lower()
        if "- 123av" in lower:
            idx = lower.index("- 123av")
            text = text[:idx].strip()
        elif "| 123av" in lower:
            idx = lower.index("| 123av")
            text = text[:idx].strip()
        return text.strip()

    def _extract_detail_fields(self, html: etree._Element) -> dict[str, str]:
        fields: dict[str, str] = {}
        rows = html.xpath('//div[contains(@class, "detail-item")]/div')
        for row in rows:
            spans = row.xpath(".//span")
            if len(spans) < 2:
                continue
            label_text = "".join(spans[0].xpath(".//text()"))
            label = label_text.strip().rstrip(":").rstrip("：").strip()
            value = " ".join(spans[1].xpath(".//text()")).split()
            value_str = " ".join(value)
            if label and value_str:
                fields[label] = value_str
        return fields

    def _extract_detail_link_texts(self, html: etree._Element, labels: list[str]) -> list[str]:
        rows = html.xpath('//div[contains(@class, "detail-item")]/div')
        result: list[str] = []
        for row in rows:
            spans = row.xpath(".//span")
            if not spans:
                continue
            label_text = "".join(spans[0].xpath(".//text()"))
            label = label_text.strip().rstrip(":").rstrip("：").strip()
            if not any(l in label for l in labels):
                continue
            links = row.xpath(".//a")
            link_texts = []
            for a in links:
                t = " ".join(a.xpath(".//text()")).split()
                t = " ".join(t)
                if t:
                    link_texts.append(t)
            if not link_texts and len(spans) >= 2:
                v = " ".join(spans[1].xpath(".//text()")).split()
                v = " ".join(v)
                if v:
                    link_texts.append(v)
            result.extend(link_texts)
        return result

    def _extract_first_detail_link(self, html: etree._Element, labels: list[str]) -> Optional[str]:
        texts = self._extract_detail_link_texts(html, labels)
        if texts:
            return texts[0]
        return None

    def _collect_link_texts_by_href(self, html: etree._Element, href_patterns: list[str]) -> list[str]:
        values: list[str] = []
        links = html.xpath('//a')
        for a in links:
            href = a.get("href", "")
            if not any(p in href for p in href_patterns):
                continue
            text = " ".join(a.xpath(".//text()")).split()
            text = " ".join(text)
            if text:
                values.append(text)
        return self._dedup(values)

    def _extract_first_link_by_href(self, html: etree._Element, href_patterns: list[str]) -> Optional[str]:
        values = self._collect_link_texts_by_href(html, href_patterns)
        return values[0] if values else None

    @staticmethod
    def _parse_duration(s: str) -> Optional[int]:
        if not s:
            return None
        m = re.search(r"(\d+)", s)
        return int(m.group(1)) if m else None

    @staticmethod
    def _dedup(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result
