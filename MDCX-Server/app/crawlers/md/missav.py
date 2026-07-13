"""
MissAV 爬虫 - 从 MDCX 新式爬虫迁移

MDCX 的 MissavCrawler 继承自其 BaseCrawler 类体系，
这里直接适配到我们的 BaseCrawler 接口。
"""

import logging
import re
from typing import Optional
from urllib.parse import quote, urljoin, urlparse

from parsel import Selector

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@register_crawler
class MissavCrawler(BaseCrawler):
    """MissAV 爬虫"""

    name = "missav"
    display_name = "MissAV"
    base_url = "https://missav.ws"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "MissAV 多语言JAV站点"
    language = "zh"
    requires_proxy = False

    CODE_PATTERN = re.compile(r"(?i)([a-z]{2,10})[-_ ]?(\d{2,6})")
    UNCENSORED_DIGIT_PATTERN = re.compile(r"^\d{6}[-_]\d{2,4}$")
    URL_LANG_SUFFIXES = {"cn", "en", "jp", "ja", "tw", "hk"}
    SEARCH_BLACKLIST_PREFIXES = {
        "search", "genres", "genre", "makers", "maker", "actresses", "actress",
        "actors", "actor", "directors", "director", "series", "tags", "tag",
        "label", "labels", "studio", "studios", "faq", "privacy", "terms",
        "about", "contact", "login", "register", "assets", "api", "cdn-cgi",
    }

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        async with AsyncHttpClient() as client:
            try:
                number = code.strip()
                if not number:
                    return None

                # 先尝试直达详情页
                detail_url = self._build_direct_detail_url(number)
                html_text = await client.get_text(detail_url)

                if not html_text:
                    return None

                html = Selector(html_text)

                # 检查是否是 404
                if self._is_soft_404_page(html):
                    # 尝试搜索
                    search_url = self._build_search_url(number)
                    html_text = await client.get_text(search_url)
                    if not html_text:
                        return None
                    html = Selector(html_text)
                    detail_url = self._extract_first_detail_url_from_search(html)
                    if not detail_url:
                        return None
                    html_text = await client.get_text(detail_url)
                    if not html_text:
                        return None
                    html = Selector(html_text)

                # 解析详情页
                result = await self._parse_detail(html, number)
                return result

            except Exception as e:
                logger.error(f"MissAV scrape error for {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    async def _parse_detail(self, html: Selector, code: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        # 标题
        title = self._extract_text(
            html,
            "//meta[@property='og:title']/@content",
            "normalize-space(//h1)",
        )
        if not title:
            # 从信息行获取
            title = self._find_info_value(html, {"標題", "标题", "title"})

        if not title:
            return None

        # 番号
        number = self._find_info_value(html, {"番號", "番号", "code"}) or code

        # 演员
        actors = []
        actress_names = self._extract_names_by_labels(html, {"女優", "女优", "actress"})
        for name in actress_names:
            if name:
                actors.append(ActorInfo(name=name))

        if not actors:
            neutral_names = self._extract_names_by_labels(html, {"演員", "演员", "cast", "performer", "performers"})
            for name in neutral_names:
                if name:
                    actors.append(ActorInfo(name=name))

        if not actors:
            for name in html.xpath("//meta[@property='og:video:actor']/@content").getall():
                name = name.strip()
                if name:
                    actors.append(ActorInfo(name=name))

        # 标签
        genres = []
        tag_value, tag_links = self._find_info_value_with_links(html, {"類型", "类型", "genre", "genres", "tags"})
        if tag_links:
            genres = [t.strip() for t in tag_links if t.strip()]
        elif tag_value:
            genres = [t.strip() for t in re.split(r"[|｜,，/／、]", tag_value) if t.strip()]

        if not genres:
            for tag in html.xpath("//div[contains(@class,'text-secondary')][span]//a[contains(@href,'/genres/')]/text()").getall():
                tag = tag.strip()
                if tag and tag not in genres:
                    genres.append(tag)

        # 发行日期
        release = self._find_info_value(html, {"發行日期", "发行日期", "release date", "releasedate"})
        if not release:
            release = self._extract_text(html, "//meta[@property='og:video:release_date']/@content")

        # 时长
        duration_raw = self._find_info_value(html, {"時長", "时长", "duration", "runtime"})
        duration = None
        if duration_raw:
            if m := re.search(r"\d+", duration_raw):
                num = int(m.group())
                if num >= 300:
                    duration = max(1, round(num / 60))
                else:
                    duration = num

        if not duration:
            og_duration = self._extract_text(html, "//meta[@property='og:video:duration']/@content")
            if og_duration and (m := re.search(r"\d+", og_duration)):
                num = int(m.group())
                duration = max(1, round(num / 60)) if num >= 300 else num

        # 制作商
        publisher = self._find_info_value(html, {"發行商", "发行商", "maker", "publisher", "studio"})

        # 系列
        series = self._find_info_value(html, {"系列", "series"})

        # 导演
        director = self._find_info_value(html, {"導演", "导演", "director"})

        # 封面
        cover = self._extract_text(html, "//meta[@property='og:image']/@content")

        # 简介
        outline = self._extract_text(html, "//meta[@property='og:description']/@content", "//meta[@name='description']/@content")
        if outline and self._is_site_generic_outline(outline):
            outline = ""

        return ScrapeResult(
            code=number,
            title=title,
            source=self.name,
            studio="",
            maker=publisher,
            series=series,
            release_date=self._parse_date(release),
            duration=duration,
            plot=outline,
            genres=genres,
            actors=actors,
            cover_url=cover,
            poster_url=cover,
            raw_data={"director": director} if director else {},
        )

    # ===== 辅助方法 =====

    @staticmethod
    def _extract_text(html: Selector, *xpaths: str) -> str:
        for xpath in xpaths:
            result = html.xpath(xpath).get(default="")
            if result and result.strip():
                return result.strip()
        return ""

    @classmethod
    def _normalize_label(cls, label: str) -> str:
        return re.sub(r"[:：\s]+", "", label or "").strip().lower()

    @classmethod
    def _iter_info_rows(cls, html: Selector):
        rows = html.xpath("//div[contains(@class,'text-secondary')][span]")
        for row in rows:
            label = cls._normalize_label(cls._extract_text(row, "string(span[1])"))
            if not label:
                continue
            value = cls._extract_text(row, "string(span[@class='font-medium'])", "string(time)")
            links = [item.strip() for item in row.xpath(".//a/text()").getall() if item and item.strip()]
            if not value and links:
                value = " | ".join(links)
            yield label, value, links

    @classmethod
    def _find_info_value(cls, html: Selector, labels: set[str]) -> str:
        normalized = {cls._normalize_label(l) for l in labels}
        for label, value, _ in cls._iter_info_rows(html):
            if label in normalized:
                return value
        return ""

    @classmethod
    def _find_info_value_with_links(cls, html: Selector, labels: set[str]):
        normalized = {cls._normalize_label(l) for l in labels}
        for label, value, links in cls._iter_info_rows(html):
            if label in normalized:
                return value, links
        return "", []

    @classmethod
    def _extract_names_by_labels(cls, html: Selector, labels: set[str]) -> list[str]:
        _, links = cls._find_info_value_with_links(html, labels)
        if links:
            return list(dict.fromkeys(links))
        value, _ = cls._find_info_value_with_links(html, labels)
        if value:
            names = [n.strip() for n in re.split(r"[|｜,，/／、]", value) if n.strip()]
            return list(dict.fromkeys(names))
        return []

    @staticmethod
    def _is_site_generic_outline(value: str) -> bool:
        normalized = re.sub(r"\s+", "", (value or "")).replace("\u3000", "").lower()
        if not normalized:
            return True
        markers = [
            "免費高清日本av在線看", "免费高清日本av在线看", "無需下載", "无需下载",
            "開始播放後不會再有廣告", "开始播放后不会再有广告",
            "支援任何裝置包括手機", "支持任何装置包括手机",
            "可以番號", "可以番号",
            "加入會員後可任意收藏影片供日後觀賞", "加入会员后可任意收藏影片供日后观赏",
        ]
        return sum(1 for m in markers if m in normalized) >= 2

    def _build_direct_detail_url(self, number: str) -> str:
        raw = number.strip()
        detail_url = f"{self.base_url}/{quote(raw)}"
        return self._ensure_cn_detail_url(detail_url)

    def _build_search_url(self, number: str) -> str:
        return f"{self.base_url}/search/{quote(number.strip())}"

    @classmethod
    def _ensure_cn_detail_url(cls, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return url
        path_parts = [p for p in parsed.path.split("/") if p]
        while path_parts and path_parts[-1].lower() in cls.URL_LANG_SUFFIXES:
            path_parts.pop()
        if not path_parts:
            return url
        path = "/" + "/".join(path_parts + ["cn"])
        return parsed._replace(path=path, params="", query="", fragment="").geturl()

    @classmethod
    def _extract_slug(cls, url: str) -> str:
        path_parts = [p for p in urlparse(url).path.split("/") if p]
        while path_parts and path_parts[-1].lower() in cls.URL_LANG_SUFFIXES:
            path_parts.pop()
        return path_parts[-1] if path_parts else ""

    @classmethod
    def _is_soft_404_page(cls, html: Selector) -> bool:
        og_title = cls._extract_text(html, "//meta[@property='og:title']/@content", "normalize-space(//title)").lower()
        og_image = cls._extract_text(html, "//meta[@property='og:image']/@content").lower()
        h1_texts = [t.strip().lower() for t in html.xpath("//h1//text()").getall() if t and t.strip()]
        p_texts = [t.strip().lower() for t in html.xpath("//p//text()").getall() if t and t.strip()]
        text_blob = " ".join(h1_texts + p_texts)
        has_404 = bool(re.search(r"(^|\s)404(\s|$)", text_blob))
        has_not_found = any(m.lower() in text_blob for m in {"找不到頁面", "找不��页面", "page not found", "not found"})
        is_generic_title = any(m in og_title for m in {
            "missav | 免費高清av在線看", "missav | 免费高清av在线看",
            "missav | free jav online streaming", "missav | 無料エロ動画見放題",
        })
        is_logo_thumb = "logo-square.png" in og_image
        if has_not_found and has_404:
            return True
        return is_generic_title and is_logo_thumb and has_404

    def _extract_first_detail_url_from_search(self, html: Selector) -> Optional[str]:
        hrefs = html.xpath("//a[@href]/@href").getall()
        candidates = []
        seen = set()
        for href in hrefs:
            href = href.strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            detail_url = urljoin(self.base_url, href)
            parsed = urlparse(detail_url)
            if parsed.scheme not in {"http", "https"}:
                continue
            if parsed.query or parsed.fragment:
                continue
            path_parts = [p for p in parsed.path.split("/") if p]
            if not path_parts:
                continue
            first = path_parts[0].lower()
            if first in self.SEARCH_BLACKLIST_PREFIXES:
                continue
            if len(path_parts) > 2:
                continue
            if len(path_parts) == 2 and not path_parts[0].lower().startswith("dm"):
                continue
            if not re.search(r"\d", path_parts[-1]):
                continue
            detail_url = self._ensure_cn_detail_url(detail_url)
            if detail_url not in seen:
                seen.add(detail_url)
                candidates.append(detail_url)
        return candidates[0] if candidates else None

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
