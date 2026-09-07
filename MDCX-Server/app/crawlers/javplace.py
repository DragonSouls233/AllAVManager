"""JavPlace 爬虫 (有码)

详情页 URL: https://jav.place/video/{CODE_uppercase}
搜索 URL:  https://jav.place/search?q={keyword}

基于 Rust 参考: ref18-javm/src-tauri/src/resource_scrape/sources/javplace.rs
"""

import json
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


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _clean_title(raw: str, code: str) -> str:
    t = raw or ""
    for s in ["日本情色視頻", "JAV", "jav.place"]:
        t = t.replace(f"- {s}", "")
    for variant in [code.upper(), code.lower(), code]:
        t = t.replace(variant, "")
    t = t.strip("-| 　")
    return t.strip()


def _looks_like_code_token(text: str) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    if not cleaned:
        return False
    has_digit = False
    for ch in cleaned:
        if ch.isascii() and ch.isdigit():
            has_digit = True
        elif not (ch.isascii() and ch.isalpha()) and ch not in "-_." and not ch.isspace():
            return False
    return has_digit


def _parse_meta_desc_desc(text: str) -> dict[str, str]:
    """解析 og:description: 水咲ローラ...。番號:ABP-001。女優:瀧澤蘿拉。標籤:打手槍,單體作品,美容院。時長:120分鐘"""
    result: dict[str, str] = {}
    if not text:
        return result
    parts = re.split(r"[。．]", text)
    for part in parts:
        part = part.strip()
        if ":" not in part and "：" not in part:
            continue
        for sep in [":", "："]:
            if sep in part:
                key, _, val = part.partition(sep)
                key = key.strip()
                val = val.strip()
                if key in ("番號", "編號", "番号"):
                    result["code"] = val
                elif key in ("女優", "女优", "女優名"):
                    result["actors"] = val
                elif key in ("標籤", "标签", "標籤名"):
                    result["tags"] = val
                elif key in ("時長", "时长"):
                    result["duration"] = val
                elif key in ("出版日期", "發布日期", "发布日期"):
                    result["date"] = val
                break
    return result


@register_crawler
class JavplaceCrawler(BaseCrawler):
    name = "javplace"
    display_name = "JavPlace"
    base_url = "https://jav.place"

    priority = CrawlerPriority.VERY_HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "JavPlace JAV 数据库站点"
    language = "zh"
    requires_proxy = False

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        if ctx and ctx.http_client is not None:
            return await self._scrape_with_client(code, ctx.http_client, ctx)
        async with AsyncHttpClient() as client:
            return await self._scrape_with_client(code, client, ctx)

    async def _scrape_with_client(
        self, code: str, client: AsyncHttpClient, ctx=None
    ) -> Optional[ScrapeResult]:
        code_upper = code.strip().upper()
        detail_url = f"https://jav.place/video/{code_upper}"

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if ctx:
            user_headers = ctx.get_headers("jav.place")
            if user_headers:
                headers.update(user_headers)

        try:
            html_text = await client.get_text(detail_url, headers=headers)

            if not html_text:
                self.mark_error()
                return None

            code_variant = code_upper.replace("-", "")
            if code_upper not in html_text and code_variant not in html_text:
                logger.debug(f"JavPlace {code_upper}: 页面中未找到编号，可能不存在")
                self.mark_error()
                return None

            html = etree.fromstring(
                html_text.encode() if isinstance(html_text, str) else html_text,
                etree.HTMLParser(),
            )

            og_image = self._get_meta(html, "og:image")
            og_title = self._get_meta(html, "og:title")
            og_desc = self._get_meta(html, "og:description")
            page_url = self._get_meta(html, "og:url")
            meta_desc = self._get_meta_by_name(html, "description")

            desc_fields = _parse_meta_desc_desc(og_desc)
            if not desc_fields.get("actors") and meta_desc:
                desc_fields.update(_parse_meta_desc_desc(meta_desc))

            raw_title = og_title
            if not raw_title:
                h1 = html.xpath("//h1/text()")
                raw_title = h1[0].strip() if h1 else ""
            if not raw_title:
                title_tag = html.xpath("//title/text()")
                raw_title = title_tag[0].strip() if title_tag else ""
            title = _clean_title(raw_title, code_upper)

            cover_url = og_image
            if not cover_url:
                poster = html.xpath('//img[contains(@class, "poster")]/@src')
                if poster:
                    cover_url = poster[0]
            if not cover_url:
                lazy = html.xpath('//img[contains(@class, "lazyimage")]/@src')
                if lazy:
                    cover_url = lazy[0]

            table_data = self._extract_table_fields(html)

            premiered = (
                table_data.get("日期")
                or desc_fields.get("date")
                or self._first_date_in_html(html_text)
            )
            release_date = _parse_date(premiered or "")

            duration_raw = table_data.get("時長") or desc_fields.get("duration")
            duration = self._parse_duration(duration_raw)

            studio = (
                table_data.get("製作")
                or table_data.get("制作")
                or table_data.get("出版")
                or ""
            )

            director = table_data.get("導演") or table_data.get("导演") or ""

            series = table_data.get("系列") or ""

            actor_names = _dedup(self._split_pipe_or_comma(desc_fields.get("actors", "")))
            if not actor_names:
                actor_names = self._collect_links_by_href(html, "/actors/")

            tag_names = _dedup(self._split_pipe_or_comma(desc_fields.get("tags", "")))
            if not tag_names:
                tag_names = _dedup(
                    t for t in self._collect_links_by_href(html, "/q/")
                    if not _looks_like_code_token(t)
                )

            thumbs = _dedup(
                self._collect_attr(
                    html,
                    '//img[contains(@class, "lazyimage")]/@src',
                )
            )
            thumbs = [u for u in thumbs if self._is_preview_image(u)]

            plot = ""
            if og_desc:
                m = re.search(r"^[^。．]*[。．]", og_desc)
                if m:
                    plot = m.group(0).strip()

            if not title and not cover_url:
                self.mark_error()
                return None

            actor_infos = [ActorInfo(name=n) for n in actor_names]
            directors_list = _dedup(d.strip() for d in director.split(",") if d.strip()) if director else []

            return ScrapeResult(
                code=code_upper,
                title=title,
                source=self.name,
                source_url=page_url or detail_url,
                studio=studio,
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=tag_names,
                tags=tag_names,
                actors=actor_infos,
                all_actors=actor_names,
                directors=directors_list,
                cover_url=cover_url,
                poster_url=cover_url,
                thumb_url=thumbs[0] if thumbs else "",
                sample_images=thumbs,
                is_mosaic=None,
                is_uncensored=None,
                is_chinese=None,
                raw_data={"series": series} if series else {},
            )

        except Exception as e:
            self.mark_error()
            logger.debug(f"JavPlace {code_upper} 刮削失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = "https://jav.place/search"
        params = {"q": keyword}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url, params=params, headers=headers)
                if not html_text:
                    return []

                html = etree.fromstring(
                    html_text.encode() if isinstance(html_text, str) else html_text,
                    etree.HTMLParser(),
                )

                results: list[ScrapeResult] = []
                seen: set[str] = set()

                links = html.xpath('//a[contains(@href, "/video/")]')
                for a in links:
                    href = a.get("href", "")
                    match = re.search(r"/video/([A-Za-z0-9_-]+)", href)
                    if not match:
                        continue
                    c = match.group(1).strip().upper()
                    if c in seen:
                        continue
                    seen.add(c)
                    title = " ".join(a.xpath(".//text()")).strip()
                    if not title:
                        title = c
                    full_url = href if href.startswith("http") else f"https://jav.place{href}"
                    results.append(ScrapeResult(
                        code=c,
                        title=title,
                        source=self.name,
                        source_url=full_url,
                        is_exact_match=False,
                    ))

                return results[:20]

            except Exception as e:
                logger.debug(f"JavPlace 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _get_meta(self, html: etree._Element, prop: str) -> str:
        texts = html.xpath(f'//meta[@property="{prop}"]/@content')
        return texts[0].strip() if texts else ""

    def _get_meta_by_name(self, html: etree._Element, name: str) -> str:
        texts = html.xpath(f'//meta[@name="{name}"]/@content')
        return texts[0].strip() if texts else ""

    def _first_date_in_html(self, html_text: str) -> str:
        m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", html_text)
        return m.group(1).replace("/", "-") if m else ""

    def _parse_duration(self, text: str) -> Optional[int]:
        if not text:
            return None
        text = text.replace("分钟", "").replace("分鐘", "").replace("分", "").strip()
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else None

    def _extract_table_fields(self, html: etree._Element) -> dict[str, str]:
        result: dict[str, str] = {}
        for tr in html.xpath("//table[contains(@class, 'table')]//tr"):
            ths = tr.xpath("./th/text()")
            tds = tr.xpath("./td/text()")
            if not ths:
                continue
            key = ths[0].strip()
            if not key:
                continue
            val = " ".join(t.strip() for t in tds if t.strip())
            if val:
                result[key] = val
        return result

    def _collect_links_by_href(self, html: etree._Element, href_contains: str) -> list[str]:
        results: list[str] = []
        for a in html.xpath("//a"):
            href = a.get("href", "")
            if href_contains in href:
                text = " ".join(a.xpath(".//text()"))
                cleaned = " ".join(text.split())
                if cleaned:
                    results.append(cleaned)
        return results

    def _collect_attr(self, html: etree._Element, xpath: str) -> list[str]:
        results = html.xpath(xpath)
        return [r.strip() for r in results if isinstance(r, str) and r.strip()]

    def _split_pipe_or_comma(self, text: str) -> list[str]:
        if not text:
            return []
        parts = re.split(r"[|,，、]", text)
        return [p.strip() for p in parts if p.strip()]

    def _is_preview_image(self, url: str) -> bool:
        if not url:
            return False
        path_hint = any(p in url for p in ["/images/image/", "/screenshot/", "/sample/"])
        ext_hint = url.endswith((".jpg", ".png", ".webp")) or ".avif" in url
        return path_hint and ext_hint
