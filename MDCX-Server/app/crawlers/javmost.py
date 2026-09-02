"""JavMost 爬虫 (有码)

详情页 URL: https://www.javmost.ws/{CODE}/
页面结构:
  - 标题: card-block > h2.card-title (2nd 个, 第一个是 code)
  - 元信息: card-block > p.card-text 内嵌 Release/Time/Star/Genre/Director/Maker
  - 封面: og:image / og:image:secure_url / video_thumbnail 的 source data-srcset
  - 演员: Star 后的 a[href*="/star/"]
  - 类别: Genre 后的 a[href*="/category/"]
  - 导演: Director 后的 a[href*="/director/"]
  - 片商: Maker 后的 a[href*="/maker/"]
  - 时长: video:duration (秒) 或 card-text 中 Time 后的数字
  - 日期: video:release_date 或 JSON-LD uploadDate 或 card-text 中 Release 后的 YYYY-MM-DD
  - 补充标题: twitter:title (含番号和真实标题)
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


@register_crawler
class JavMostCrawler(BaseCrawler):
    name = "javmost"
    display_name = "JavMost"
    base_url = "https://www.javmost.ws"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "JavMost JAV 数据库站点"
    language = "en"
    requires_proxy = False

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        code_upper = code.strip().upper()
        detail_url = f"{self.base_url}/{code_upper}/"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        if ctx:
            user_headers = ctx.get_headers("javmost.ws")
            if user_headers:
                headers.update(user_headers)

        try:
            async with AsyncHttpClient() as client:
                html_text = await client.get_text(detail_url, headers=headers)
        except Exception as e:
            self.mark_error()
            logger.debug(f"JavMost {code_upper} 请求失败: {e}")
            return None

        if not html_text:
            self.mark_error()
            return None

        if "cloudflare" in html_text.lower() or "driver-verify" in html_text.lower():
            self.mark_error()
            logger.debug(f"JavMost {code_upper}: 遇到验证拦截")
            return None

        code_variant = code_upper.replace("-", "")
        if code_upper not in html_text and code_variant not in html_text:
            self.mark_error()
            logger.debug(f"JavMost {code_upper}: 页面中未找到编号")
            return None

        try:
            html = etree.fromstring(html_text.encode() if isinstance(html_text, str) else html_text, etree.HTMLParser())
        except Exception as e:
            self.mark_error()
            logger.debug(f"JavMost {code_upper} HTML 解析失败: {e}")
            return None

        result = self._parse_detail_page(html, html_text, code_upper)
        if result:
            self.mark_success()
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        search_url = f"{self.base_url}/search/{keyword}/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        async with AsyncHttpClient() as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text or "cloudflare" in html_text.lower():
                    return []
                html = etree.fromstring(
                    html_text.encode() if isinstance(html_text, str) else html_text,
                    etree.HTMLParser(),
                )
                results: list[ScrapeResult] = []
                seen_codes: set[str] = set()
                items = html.xpath('//a[contains(@href, "/")]')
                for a in items:
                    href = a.get("href", "")
                    match = re.search(r"/([A-Z]{1,6}-?\d{2,5})(?:/|$)", href, re.IGNORECASE)
                    if not match:
                        continue
                    code = match.group(1).upper()
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    title = " ".join(a.xpath(".//text()")).strip()
                    if not title:
                        title = code
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    results.append(ScrapeResult(
                        code=code,
                        title=title,
                        source=self.name,
                        source_url=full_url,
                        is_exact_match=False,
                    ))
                return results[:20]
            except Exception as e:
                logger.debug(f"JavMost 搜索 '{keyword}' 失败: {e}")
                return []

    async def health_check(self) -> bool:
        return True

    def _parse_detail_page(self, html: etree._Element, html_text: str, code: str) -> Optional[ScrapeResult]:
        try:
            cover_url = self._get_cover_url(html)
            page_url = self._get_canonical(html) or f"{self.base_url}/{code}/"
            raw_title = self._get_title(html)
            cleaned_title = self._clean_title(raw_title, code)

            card_texts = html.xpath('//div[contains(@class, "card-block")]//p[contains(@class, "card-text")]/descendant-or-self::node()/text()')
            card_text_joined = "".join(card_texts) if card_texts else ""

            actor_names = self._extract_actors(html)
            director_name = self._extract_director(html)
            maker_name = self._extract_maker(html)
            genre_names = self._extract_genres(html)

            release_date = self._extract_release_date(html)
            duration = self._extract_duration(html, html_text)

            description = self._extract_description(html, html_text)

            if not cleaned_title and not cover_url:
                return None

            actor_infos = [ActorInfo(name=n) for n in _dedup(actor_names)]

            result = ScrapeResult(
                code=code,
                title=cleaned_title,
                source=self.name,
                source_url=page_url,
                studio=maker_name,
                release_date=release_date,
                duration=duration,
                plot=description,
                genres=_dedup(genre_names),
                tags=_dedup(genre_names),
                actors=actor_infos,
                all_actors=_dedup(actor_names),
                directors=_dedup([d.strip() for d in director_name.split(",") if d.strip()]) if director_name else [],
                cover_url=cover_url,
                poster_url=cover_url,
                is_mosaic=None,
                is_uncensored=None,
                is_chinese=None,
                raw_data={
                    "page_url": page_url,
                    "actor_names": actor_names,
                    "genre_names": genre_names,
                },
            )
            return result

        except Exception as e:
            logger.debug(f"JavMost {code} 解析异常: {e}")
            return None

    def _get_cover_url(self, html: etree._Element) -> Optional[str]:
        # og:image:secure_url > og:image
        for prop in ["og:image:secure_url", "og:image"]:
            vals = html.xpath(f'//meta[@property="{prop}"]/@content')
            if vals and vals[0].strip():
                return vals[0].strip()
        # twitter:image:src > twitter:image
        for name in ["twitter:image:src", "twitter:image"]:
            vals = html.xpath(f'//meta[@name="{name}"]/@content')
            if vals and vals[0].strip():
                return vals[0].strip()
        # JSON-LD thumbnailUrl
        json_ld = self._extract_json_ld(html)
        if json_ld and json_ld.get("thumbnailUrl"):
            return json_ld["thumbnailUrl"]
        return None

    def _get_canonical(self, html: etree._Element) -> Optional[str]:
        link = html.xpath('//link[@rel="canonical"]/@href')
        if link:
            return link[0].strip()
        prop = html.xpath('//meta[@property="og:url"]/@content')
        return prop[0].strip() if prop else None

    def _get_title(self, html: etree._Element) -> str:
        # 1) twitter:title: "SSNI-587  Intersecting Body Fluids..."
        vals = html.xpath('//meta[@name="twitter:title"]/@content')
        if vals:
            return vals[0].strip()
        # 2) card-block 第二个 h2.card-title（第一个是 code）
        h2s = html.xpath('//div[contains(@class, "card-block")]//h2[contains(@class, "card-title")]')
        if len(h2s) >= 2:
            texts = h2s[1].xpath(".//text()")
            title = " ".join(t.strip() for t in texts if t.strip())
            if title:
                return title
        if len(h2s) >= 1:
            texts = h2s[0].xpath(".//text()")
            title = " ".join(t.strip() for t in texts if t.strip())
            if title:
                return title
        # 3) JSON-LD name
        json_ld = self._extract_json_ld(html)
        if json_ld and json_ld.get("name"):
            return json_ld["name"]
        # 4) og:title
        vals = html.xpath('//meta[@property="og:title"]/@content')
        if vals:
            return vals[0].strip()
        return ""

    def _clean_title(self, raw: str, code: str) -> str:
        t = raw or ""
        code_lower = code.lower()
        for variant in [code, code_lower, code.replace("-", "")]:
            t = t.replace(variant, "")
        t = t.replace("JAVMOST", "").replace("JavMost", "").replace("javmost", "")
        t = t.replace("Watch JAV Online Free Streaming", "").replace("Full HD Japanese porn video", "")
        t = t.strip("-| :　")
        return t.strip()

    def _extract_actors(self, html: etree._Element) -> list[str]:
        results: list[str] = []
        for star_link in html.xpath('//a[contains(@href, "/star/")]'):
            text = " ".join(star_link.xpath(".//text()"))
            cleaned = " ".join(text.split())
            if cleaned:
                results.append(cleaned)
        return results

    def _extract_director(self, html: etree._Element) -> str:
        links = html.xpath('//a[contains(@href, "/director/")]')
        for link in links:
            text = " ".join(link.xpath(".//text()"))
            cleaned = " ".join(text.split())
            if cleaned:
                return cleaned
        return ""

    def _extract_maker(self, html: etree._Element) -> str:
        links = html.xpath('//a[contains(@href, "/maker/")]')
        for link in links:
            text = " ".join(link.xpath(".//text()"))
            cleaned = " ".join(text.split())
            if cleaned:
                return cleaned
        return ""

    def _extract_genres(self, html: etree._Element) -> list[str]:
        results: list[str] = []
        for link in html.xpath('//a[contains(@href, "/category/")]'):
            text = " ".join(link.xpath(".//text()"))
            cleaned = " ".join(text.split())
            if cleaned:
                results.append(cleaned)
        return results

    def _extract_release_date(self, html: etree._Element) -> Optional[date]:
        # 1) video:release_date
        vals = html.xpath('//meta[@property="video:release_date"]/@content')
        if vals:
            d = _parse_date(vals[0])
            if d:
                return d
        # 2) JSON-LD uploadDate
        json_ld = self._extract_json_ld(html)
        if json_ld:
            d = _parse_date(json_ld.get("uploadDate", ""))
            if d:
                return d
        # 3) card-block 中 Release 后的日期
        vals = html.xpath('//div[contains(@class, "card-block")]//text()')
        for v in vals:
            if "Release" in v:
                m = _DATE_RE.search(v)
                if m:
                    try:
                        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError:
                        pass
        return None

    def _extract_duration(self, html: etree._Element, html_text: str) -> Optional[int]:
        # 1) video:duration (秒)
        vals = html.xpath('//meta[@property="video:duration"]/@content')
        if vals:
            m = re.search(r"(\d+)", vals[0])
            if m:
                return int(m.group(1))
        # 2) JSON-LD duration: PT7800M (ISO 8601)
        json_ld = self._extract_json_ld(html)
        if json_ld:
            dur_str = json_ld.get("duration", "")
            m = re.search(r"PT(\d+)", dur_str)
            if m:
                return int(m.group(1))
        # 3) card-block 中 Time 后的数字 (分钟)
        for v in html.xpath('//div[contains(@class, "card-block")]//text()'):
            if "Time" in v:
                m = re.search(r"(\d+)", v)
                if m:
                    return int(m.group(1)) * 60
        return None

    def _extract_description(self, html: etree._Element, html_text: str) -> str:
        # JSON-LD description
        json_ld = self._extract_json_ld(html)
        if json_ld:
            desc = json_ld.get("description", "")
            if desc:
                return desc
        # og:description
        vals = html.xpath('//meta[@property="og:description"]/@content')
        if vals:
            return vals[0].strip()
        return ""

    def _extract_json_ld(self, html: etree._Element) -> Optional[dict]:
        scripts = html.xpath('//script[@type="application/ld+json"]')
        for script in scripts:
            text = "".join(script.xpath(".//text()")).strip()
            if text:
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and data.get("@type") == "VideoObject":
                        return data
                except (json.JSONDecodeError, TypeError):
                    continue
        return None