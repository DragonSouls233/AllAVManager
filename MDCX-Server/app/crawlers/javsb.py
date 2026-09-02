"""JavSB 爬虫 (无码)

详情页 URL: https://jav.sb/jav/{CODE_lowercase}-1-1.html
搜索 URL:  https://jav.sb/search?keyword={keyword}

基于 Rust 参考: ref18-javm/src-tauri/src/resource_scrape/sources/javsb.rs
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
_ACTRESS_TEXT_RE = re.compile(r"(?:出演|女優|演员|Actress|Star)\s*[:：]?\s*(.+)")
_GENRES_TEXT_RE = re.compile(r"(?:題材有|類別有|Tags?)\s*[:：]?\s*(.+)")

_JAVSB_ACTORS_RE = re.compile(r"[\[\]\d,.，、；;:\s]")
_JAVSB_CATEGORIES_RE = re.compile(r"[\[\],.，、；;]")


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


def _is_valid_code(s: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9]{1,16}$", s.strip()))


def _split_tags(text: str) -> list[str]:
    if not text:
        return []
    text = text.strip(" []\t\n\r ,，、")
    parts = re.split(r"[ ,，、；;\n\t]+", text)
    return [p.strip() for p in parts if p.strip()]


@register_crawler
class JavsbCrawler(BaseCrawler):
    name = "javsb"
    display_name = "JavSB"
    base_url = "https://jav.sb"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = []
    description = "JavSB 无码视频站点"
    language = "zh"
    requires_proxy = False

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        code_upper = code.strip().upper()
        code_lower = code_upper.lower()
        detail_url = f"https://jav.sb/jav/{code_lower}-1-1.html"

        headers = {"User-Agent": "Mozilla/5.0"}
        if ctx:
            user_headers = ctx.get_headers("jav.sb")
            if user_headers:
                headers.update(user_headers)

        try:
            async with AsyncHttpClient() as client:
                html_text = await client.get_text(detail_url, headers=headers)

                if not html_text:
                    self.mark_error()
                    return None

                if "cloudflare" in html_text.lower() or "verify your browser" in html_text.lower():
                    logger.debug(f"JavSB {code_upper}: Cloudflare 验证拦截，跳过")
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text.encode() if isinstance(html_text, str) else html_text,
                                        etree.HTMLParser())

                meta_desc = _get_meta_content(html, "description")
                og_desc = _get_og(html, "og:description")
                og_title = _get_og(html, "og:title") or _get_title(html)
                og_image = _get_og(html, "og:image")

                raw_title = (og_desc or meta_desc or og_title or "").strip()
                description = _parse_meta_desc(raw_title)

                body_title = ""
                parsed_title = self._parse_intro_panel_title(html)
                if parsed_title:
                    body_title = parsed_title
                else:
                    candidates = html.xpath("//h1//text() | //div[contains(@class, 'title')]//text()")
                    for t in candidates:
                        cleaned = t.strip()
                        if cleaned:
                            body_title = cleaned
                            break

                title = body_title or og_title or ""
                if not title.strip():
                    title = code_upper

                release_date = _parse_date(description.date)

                duration = _parse_duration(description.duration)

                actress_names = _dedup(description.actors)
                genre_names = _dedup(description.categories)

                actress_link_names = _collect_actress_links(html)
                actress_names = _dedup(actress_names + actress_link_names)

                actor_infos = [ActorInfo(name=n) for n in actress_names]

                extra = {}
                if description.director:
                    extra["directors"] = [description.director]
                if description.manufacturer:
                    extra["manufacturer"] = description.manufacturer
                if description.tags:
                    extra["tags"] = _dedup(description.tags)

                if not title:
                    return None

                return ScrapeResult(
                    code=code_upper,
                    title=title,
                    source=self.name,
                    source_url=detail_url,
                    studio=description.manufacturer or "",
                    release_date=release_date,
                    duration=duration,
                    plot=description.other_info,
                    genres=genre_names,
                    tags=[],
                    actors=actor_infos,
                    all_actors=actress_names,
                    cover_url=og_image,
                    poster_url=og_image,
                    is_mosaic=True,
                    is_uncensored=True,
                    is_chinese=None,
                    raw_data=extra,
                )

        except Exception as e:
            self.mark_error()
            logger.debug(f"JavSB {code_upper} 刮削失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = "https://jav.sb/search"
        params = {"keyword": keyword}
        headers = {"User-Agent": "Mozilla/5.0"}

        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url, params=params, headers=headers)
                if not html_text:
                    return []

                html = etree.fromstring(html_text.encode() if isinstance(html_text, str) else html_text,
                                        etree.HTMLParser())

                results: list[ScrapeResult] = []
                search_items = html.xpath(
                    '//a[contains(@href, "/jav/") and contains(@href, ".html")]'
                )
                seen = set()

                for a in search_items:
                    href = a.get("href", "")
                    match = re.search(r"/jav/([a-zA-Z0-9]+)-", href)
                    if not match:
                        continue
                    code = match.group(1).strip().upper()
                    if code in seen:
                        continue
                    seen.add(code)
                    title = " ".join(a.xpath(".//text()")).strip()
                    title = re.sub(rf"\[{re.escape(code)}\]", "", title).strip()
                    if not title:
                        title = code
                    full_url = href if href.startswith("http") else f"https://jav.sb{href}"
                    results.append(ScrapeResult(
                        code=code,
                        title=title,
                        source=self.name,
                        source_url=full_url,
                        is_exact_match=False,
                    ))

                return results[:20]

            except Exception as e:
                logger.debug(f"JavSB 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _parse_intro_panel_title(self, html: etree._Element) -> str:
        items = html.xpath(
            '//div[@data-tab-panel="intro"]//div[contains(@class, "space-y-2")]'
        )
        for item in items:
            text = " ".join(item.xpath(".//text()")).strip()
            if " " not in text and len(text) < 50:
                return text
        return ""


def _get_meta_content(html: etree._Element, name: str) -> str:
    texts = html.xpath(f'//meta[@name="{name}"]/@content')
    return texts[0].strip() if texts else ""


def _get_og(html: etree._Element, prop: str) -> str:
    texts = html.xpath(f'//meta[@property="{prop}"]/@content')
    return texts[0].strip() if texts else ""


def _get_title(html: etree._Element) -> str:
    texts = html.xpath("//title/text()")
    return texts[0].strip() if texts else ""


def _parse_duration(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.replace("分钟", "").replace("分鐘", "").replace("分", "").strip()
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _split_multi(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[/\s]+", text) if p.strip()]


def _collect_actress_links(html: etree._Element) -> list[str]:
    results: list[str] = []
    star_links = html.xpath('//a[contains(@href, "/star/")]')
    seen: set[str] = set()
    for a in star_links:
        href = a.get("href", "")
        text = " ".join(a.xpath(".//text()")).strip()
        id_match = re.search(r"/star/([^?#/]+)(?:[?#/])?", href)
        key = f"{href}|{text}"
        if key in seen:
            continue
        seen.add(key)
        if not text:
            text = id_match.group(1).strip() if id_match else ""
        if text:
            results.append(text)
    return results


class _DescFields:
    def __init__(self):
        self.date: str = ""
        self.duration: str = ""
        self.actors: list[str] = []
        self.director: str = ""
        self.manufacturer: str = ""
        self.categories: list[str] = []
        self.other_info: str = ""
        self.tags: list[str] = []
        self._seen: set[str] = set()

    def add(self, text: str, source: str):
        t = text.strip()
        if not t or t in self._seen:
            return
        self._seen.add(t)

        date_matches = list(_DATE_RE.finditer(t))
        has_date = len(date_matches) > 0 and t.lower().count("date") <= 1

        if has_date:
            m = date_matches[0]
            self.date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            self._append(t.replace(self.date, "").strip(" [].、，,："), source)
            return

        if re.fullmatch(r"\d+", t):
            self.duration = t
            return
        if "min" in t.lower():
            self.duration = t
            return

        actress_m = _ACTRESS_TEXT_RE.search(t)
        if actress_m:
            names = actress_m.group(1).strip(" []")
            names = _JAVSB_ACTORS_RE.split(names)
            self.actors.extend(
                n.strip() for n in names if len(n.strip()) >= 1
            )
            return

        if t.startswith("导演"):
            director_part = re.sub(r"^导演[:：\s]*", "", t).strip(" []")
            parts = _JAVSB_ACTORS_RE.split(director_part)
            if parts:
                self.director = parts[0].strip()
            return

        if t.startswith("厂商"):
            mfr_part = re.sub(r"^厂商[:：\s]*", "", t).strip(" []")
            parts = _JAVSB_ACTORS_RE.split(mfr_part)
            if parts:
                self.manufacturer = parts[0].strip()
            return

        genre_m = _GENRES_TEXT_RE.search(t)
        if genre_m:
            tags_part = genre_m.group(1).strip(" []")
            tags = _JAVSB_CATEGORIES_RE.split(tags_part)
            self.tags.extend(
                tag.strip() for tag in tags if tag.strip()
            )
            return

        self.other_info = f"{self.other_info} {t}".strip()


def _parse_meta_desc(text: str) -> _DescFields:
    result = _DescFields()
    if not text:
        return result

    parts = re.split(r"\s{2,}|(?<=\.)(?=[A-Z])", text)
    parts = [p.strip() for p in parts if p.strip()]

    for p in parts:
        p = re.sub(r"jav\.sb.*$", "", p, flags=re.IGNORECASE).strip()
        if not p:
            continue

        p_clean = re.sub(r"\s+", " ", p)
        if len(p_clean) < 100:
            result.add(p_clean, "direct")
        else:
            segments = [s.strip() for s in re.split(r"[；;]", p_clean) if s.strip()]
            if len(segments) > 1:
                for seg in segments:
                    seg = re.sub(r"\s+", " ", seg)
                    if len(seg) < 100:
                        result.add(seg, "semicolon_split")
            else:
                result.add(p_clean, "direct")

    return result
