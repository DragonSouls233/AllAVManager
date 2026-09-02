"""
MyJAV 爬虫

详情页 URL: https://cn.myjav.tv/video/{CODE_uppercase}
基于 Rust 参考实现: ref18-javm/src-tauri/src/resource_scrape/sources/myjav.rs
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
    normalized = s.replace("/", "-").replace(".", "-")
    try:
        return date(*map(int, normalized.split("-")[:3]))
    except (ValueError, TypeError):
        return None


@register_crawler
class MyJavCrawler(BaseCrawler):
    name = "myjav"
    display_name = "MyJAV"
    base_url = "https://cn.myjav.tv"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "MyJAV JAV 数据库站点（含无码）"
    language = "zh"
    requires_proxy = False

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
        detail_url = f"{self.base_url}/video/{code_upper}"

        headers = None
        if ctx:
            headers = ctx.get_headers("myjav.tv")

        try:
            html_text = await client.get_text(detail_url, headers=headers)

            if "cloudflare" in html_text.lower() or "driver-verify" in html_text.lower():
                logger.debug(f"MyJAV {code_upper}: 遇到验证拦截，跳过")
                self.mark_error()
                return None

            html = etree.fromstring(html_text, etree.HTMLParser())
            result = self._parse_detail_page(html, code_upper)

            if result:
                self.mark_success()
            return result

        except Exception as e:
            self.mark_error()
            logger.debug(f"MyJAV {code_upper} 刮削失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = f"{self.base_url}/search/?s={keyword}"

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url)

                if "cloudflare" in html_text.lower():
                    self.mark_error()
                    return []

                html = etree.fromstring(html_text, etree.HTMLParser())
                results = []
                seen_codes: set[str] = set()

                items = html.xpath('//a[contains(@href, "/video/")]')
                for a in items:
                    href = a.get("href", "")
                    title = "".join(a.xpath(".//text()")).strip()
                    code_match = re.search(r"/video/([a-z0-9]+)", href, re.IGNORECASE)
                    if not code_match:
                        continue
                    code = code_match.group(1).upper()
                    if code in seen_codes or not title:
                        continue
                    seen_codes.add(code)
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    results.append(ScrapeResult(
                        code=code,
                        title=title,
                        source=self.name,
                        source_url=full_url,
                        confidence=0.75,
                        is_exact_match=False,
                    ))

                return results[:20]

            except Exception as e:
                logger.debug(f"MyJAV 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _parse_detail_page(self, html: etree._Element, code: str) -> Optional[ScrapeResult]:
        try:
            cover_url = self._get_og_image(html)
            page_url = self._get_canonical(html)
            raw_title = self._get_og_title(html)
            raw_desc = self._get_og_description(html)

            title = self._clean_title(raw_title, code)
            plot = self._clean_description(raw_desc, code) if raw_desc else None

            detail = self._extract_detail_fields(html)

            premiered = (
                detail.get_text("发布日")
                or detail.get_text("發佈日")
                or detail.get_text("Release")
            ) or ""

            duration_raw = (
                detail.get_text("时长")
                or detail.get_text("時長")
                or detail.get_text("Duration")
            ) or ""
            duration = self._parse_duration(duration_raw)

            actors_raw = (
                detail.get_links("演员")
                or detail.get_links("演員")
                or detail.get_links("Actress")
            )
            actor_names = self._dedup(actors_raw)

            studio = (
                (detail.get_links("片商") or detail.get_links("Maker") or detail.get_links("Studio"))[0]
                if (detail.get_links("片商") or detail.get_links("Maker") or detail.get_links("Studio"))
                else None
            )

            director = (
                (detail.get_links("导演") or detail.get_links("導演") or detail.get_links("Director"))[0]
                if (detail.get_links("导演") or detail.get_links("導演") or detail.get_links("Director"))
                else None
            )

            tags_vec = detail.get_links("标签") or detail.get_links("標籤") or detail.get_links("Tags") or []
            tags_vec = self._dedup(tags_vec)

            category = detail.get_text("类别") or detail.get_text("類別") or ""

            set_name = (
                (detail.get_links("系列") or detail.get_links("Series"))[0]
                if (detail.get_links("系列") or detail.get_links("Series"))
                else None
            )

            label = (
                (detail.get_links("厂牌") or detail.get_links("Label"))[0]
                if (detail.get_links("厂牌") or detail.get_links("Label"))
                else None
            )

            if not title and not cover_url:
                return None

            is_uncensored = None
            is_mosaic = None
            if category:
                if "无码" in category or "無碼" in category:
                    is_uncensored = True
                    is_mosaic = False

            actor_infos = [ActorInfo(name=n) for n in actor_names]

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
                genres=[t for t in tags_vec if t],
                tags=[],
                actors=actor_infos,
                all_actors=actor_names,
                directors=[director] if director else [],
                cover_url=cover_url,
                poster_url=cover_url,
                is_mosaic=is_mosaic,
                is_uncensored=is_uncensored,
                is_chinese=None,
                raw_data={
                    "page_url": page_url,
                    "premiered_raw": premiered,
                    "duration_raw": duration_raw,
                    "studio": studio or "",
                    "category": category,
                    "set_name": set_name or "",
                    "label": label or "",
                    "director": director or "",
                },
            )

        except Exception as e:
            logger.debug(f"MyJAV {code} 详情页解析异常: {e}")
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

    def _get_og_description(self, html: etree._Element) -> Optional[str]:
        prop = html.xpath('//meta[@property="og:description"]/@content')
        if prop and prop[0].strip():
            return prop[0].strip()
        desc = html.xpath('//meta[@name="description"]/@content')
        return desc[0].strip() if desc else None

    def _clean_title(self, raw: str, code_upper: str) -> str:
        text = (raw or "").strip()
        lower = text.lower()
        for suffix in ["- myjav", "| myjav", "- my jav"]:
            if suffix in lower:
                idx = lower.index(suffix)
                text = text[:idx].rstrip()
                break
        if text.upper().startswith(code_upper):
            text = text[len(code_upper):]
            text = text.lstrip("-:  \u3000")
            text = text.strip()
        return text.strip()

    def _clean_description(self, raw: str, code_upper: str) -> Optional[str]:
        text = (raw or "").strip()
        if text.upper().startswith(code_upper):
            text = text[len(code_upper):]
            text = text.lstrip("-: \u3000,")
            text = text.strip()
        lower = text.lower()
        for suffix in ["- myjav", "| myjav"]:
            if suffix in lower:
                idx = lower.index(suffix)
                text = text[:idx].strip()
                break
        text = text.strip()
        return text if text else None

    def _extract_detail_fields(self, html: etree._Element) -> "DetailFields":
        rows: list[tuple[str, str, list[str]]] = []

        lines = html.xpath('//div[contains(@class, "detail-line")]')
        for line in lines:
            labels = line.xpath('.//span[contains(@class, "detail-label")]')
            if not labels:
                continue
            label_text = "".join(labels[0].xpath(".//text()"))
            label = label_text.strip().rstrip(":").rstrip("：").strip()
            if not label:
                continue

            value_els = line.xpath('.//span[contains(@class, "detail-value")]')
            if not value_els:
                value_els = line.xpath(".//span")
                value_els = value_els[1:] if len(value_els) > 1 else []

            if not value_els:
                rows.append((label, "", []))
                continue

            value_el = value_els[0]
            text_value = " ".join(value_el.xpath(".//text()"))
            text_value = " ".join(text_value.split())
            text_value = text_value.strip("/, ")

            link_texts: list[str] = []
            for a in value_el.xpath(".//a"):
                t = " ".join(a.xpath(".//text()"))
                t = " ".join(t.split())
                if t:
                    link_texts.append(t)

            rows.append((label, text_value, link_texts))

        return DetailFields(rows)

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


class DetailFields:
    def __init__(self, rows: list[tuple[str, str, list[str]]]):
        self._rows = rows

    def get_text(self, label: str) -> Optional[str]:
        for l, text, _ in self._rows:
            if label in l:
                if text.strip():
                    return text.strip()
        return None

    def get_links(self, label: str) -> list[str]:
        for l, _, links in self._rows:
            if label in l:
                if links:
                    return links
        return []
