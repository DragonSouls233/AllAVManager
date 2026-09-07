"""JavMenu 爬虫 (有码)

详情页 URL: https://javmenu.com/zh/{code}
搜索 URL:  https://javmenu.com/zh/search?keyword={keyword}

基于 Rust 参考: ref18-javm/src-tauri/src/resource_scrape/sources/javmenu.rs
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
    for s in [
        "世界上最齊全的日本AV資料庫",
        "世界上最齐全的日本AV资料库",
        "JAV目錄大全",
        "JAV目录大全",
        "免费AV在线看",
    ]:
        t = t.replace(s, "")
    for variant in [code.upper(), code.lower(), code]:
        t = t.replace(variant, "")
    t = t.strip("-| 　")
    return t.strip()


def _extract_between(text: str, start: str, end: str) -> str:
    if not text:
        return ""
    pos = text.find(start)
    if pos < 0:
        return ""
    after = text[pos + len(start):]
    end_pos = after.find(end)
    if end_pos >= 0:
        val = after[:end_pos]
    else:
        val = after
    val = val.strip()
    return val if val else ""


def _extract_after(text: str, label: str) -> str:
    if not text:
        return ""
    pos = text.find(label)
    if pos < 0:
        return ""
    after = text[pos + len(label):].strip()
    val = after.split()[0] if after else ""
    return val


def _extract_labeled_span_value(html_text: str, label: str) -> str:
    pattern = re.escape(label)
    pattern = re.compile(
        r'<div class="[^"]*d-flex[^"]*">.*?<span[^>]*>\s*'
        + pattern
        + r':(?:&nbsp;|\s)*</span>\s*<span[^>]*>\s*([^<]+?)\s*</span>',
        re.DOTALL,
    )
    m = pattern.search(html_text)
    if not m:
        return ""
    return _clean_html_text(m.group(1))


def _extract_anchor_texts_by_class(html_text: str, class_name: str) -> list[str]:
    pattern = re.compile(
        r'<a[^>]*class="[^"]*' + re.escape(class_name) + r'[^"]*"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    return _dedup(
        m.group(1).strip()
        for m in pattern.finditer(html_text)
        if m.group(1).strip()
    )


def _extract_block_anchor_text(html_text: str, class_name: str) -> str:
    pattern = re.compile(
        r'<div class="[^"]*' + re.escape(class_name) + r'[^"]*">.*?<a[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    m = pattern.search(html_text)
    if not m:
        return ""
    return _clean_html_text(m.group(1))


def _clean_html_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    cleaned = " ".join(text.split())
    return cleaned


def _parse_duration(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.replace("分钟", "").replace("分鐘", "").replace("分", "").strip()
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


@register_crawler
class JavmenuCrawler(BaseCrawler):
    name = "javmenu"
    display_name = "JavMenu"
    base_url = "https://javmenu.com"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "JavMenu JAV 目录大全"
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
        detail_url = f"https://javmenu.com/zh/{code_upper}"

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if ctx:
            user_headers = ctx.get_headers("javmenu.com")
            if user_headers:
                headers.update(user_headers)

        try:
            html_text = await client.get_text(detail_url, headers=headers)

            if not html_text:
                self.mark_error()
                return None

            if code_upper not in html_text.upper():
                logger.debug(f"JavMenu {code_upper}: 页面中未找到编号，可能不存在")
                self.mark_error()
                return None

            html = etree.fromstring(
                html_text.encode() if isinstance(html_text, str) else html_text,
                etree.HTMLParser(),
            )

            card_text = ""
            card_bodies = html.xpath('//div[contains(@class, "card-body")]//text()')
            card_text = " ".join(card_bodies)

            desc = self._get_desc_meta(html)
            og_title = self._get_og_title_with_code(html, code_upper)
            cover_url = self._get_cover_url(html)

            raw_title = _extract_between(desc, "影片名是", "，")
            if not raw_title and og_title:
                raw_title = _clean_title(og_title, code_upper)
            if not raw_title:
                h1 = html.xpath("//h1[contains(@class, 'display-5') and contains(@class, 'strong')]/text()")
                if h1:
                    raw_title = _clean_title(h1[0], code_upper)
            if not raw_title:
                title_tag = html.xpath("//title/text()")
                raw_title = _clean_title(title_tag[0] if title_tag else "", code_upper)
            title = raw_title

            premiered = (
                _extract_between(desc, "发佈日期为", "，")
                or _extract_after(card_text, "发佈于:")
                or _extract_labeled_span_value(html_text, "发佈于")
            )
            release_date = _parse_date(premiered)

            duration_text = (
                _extract_between(desc, "影片时长", "，")
                or _extract_between(desc, "影片时长", "。")
                or _extract_after(card_text, "时长:")
                or _extract_labeled_span_value(html_text, "时长")
            )
            duration = _parse_duration(duration_text)

            tag_text = _extract_between(desc, "主题为", "。")
            if tag_text:
                tag_text = tag_text.replace("、", ",")
                tag_names = _dedup([t.strip() for t in tag_text.split(",") if t.strip()])
            else:
                tag_names = _dedup(html.xpath("//a[contains(@class, 'genre')]/text()"))
                if not tag_names:
                    tag_names = _extract_anchor_texts_by_class(html_text, "genre")

            actor_text = _extract_between(desc, "主演女优是", "，")
            if actor_text:
                actor_text = actor_text.replace("、", ",")
                actor_names = _dedup([n.strip() for n in actor_text.split(",") if n.strip()])
            else:
                actor_names = _dedup(html.xpath("//a[contains(@class, 'actress')]/text()"))
                if not actor_names:
                    actor_names = _extract_anchor_texts_by_class(html_text, "actress")

            studio = ""
            makers = html.xpath("//a[contains(@class, 'maker')]/text()")
            if makers:
                studio = makers[0].strip()
            else:
                studio = _extract_block_anchor_text(html_text, "maker")

            director_text = ""
            directors = html.xpath("//div[contains(@class, 'director')]//a/text()")
            if directors:
                director_text = directors[0].strip()
            else:
                director_text = _extract_block_anchor_text(html_text, "director")

            thumbs = html.xpath('//a[@data-fancybox="gallery"]/@href')

            if not title and not cover_url:
                self.mark_error()
                return None

            actor_infos = [ActorInfo(name=n) for n in actor_names]
            directors_list = _dedup([d.strip() for d in director_text.split(",") if d.strip()]) if director_text else []

            return ScrapeResult(
                code=code_upper,
                title=title,
                source=self.name,
                source_url=detail_url,
                studio=studio,
                release_date=release_date,
                duration=duration,
                plot="",
                genres=tag_names,
                tags=tag_names,
                actors=actor_infos,
                all_actors=actor_names,
                directors=directors_list,
                cover_url=cover_url,
                poster_url=cover_url,
                sample_images=list(thumbs),
                is_mosaic=True,
                is_uncensored=False,
                is_chinese=None,
                raw_data={"page_url": detail_url},
            )

        except Exception as e:
            self.mark_error()
            logger.debug(f"JavMenu {code_upper} 刮削失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = f"https://javmenu.com/zh/search"
        params = {"keyword": keyword}
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

                links = html.xpath('//a[contains(@href, "/zh/")]')
                for a in links:
                    href = a.get("href", "")
                    match = re.search(r"/zh/([A-Za-z0-9_-]+?)(?:$|/)", href)
                    if not match:
                        continue
                    code = match.group(1).strip().upper()
                    if not re.match(r"^[A-Z]+\d+", code):
                        continue
                    if code in seen:
                        continue
                    seen.add(code)
                    title = " ".join(a.xpath(".//text()")).strip()
                    title = _clean_title(title, code)
                    if not title:
                        title = code
                    full_url = href if href.startswith("http") else f"https://javmenu.com{href}"
                    results.append(ScrapeResult(
                        code=code,
                        title=title,
                        source=self.name,
                        source_url=full_url,
                        is_exact_match=False,
                    ))

                return results[:20]

            except Exception as e:
                logger.debug(f"JavMenu 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _get_desc_meta(self, html: etree._Element) -> str:
        descs = html.xpath('//meta[@name="description"]/@content')
        for d in descs:
            if "影片番号为" in d or "影片名是" in d:
                return d.strip()
        if descs:
            return descs[0].strip()
        return ""

    def _get_og_title_with_code(self, html: etree._Element, code_upper: str) -> str:
        og_titles = html.xpath('//meta[@property="og:title"]/@content')
        for t in og_titles:
            if code_upper in t.upper():
                return t.strip()
        return ""

    def _get_cover_url(self, html: etree._Element) -> str:
        og_images = html.xpath('//meta[@property="og:image"]/@content')
        for img in og_images:
            if img.strip():
                return img.strip()
        twitter_images = html.xpath('//meta[@name="twitter:image"]/@content')
        for img in twitter_images:
            if img.strip():
                return img.strip()
        return ""
