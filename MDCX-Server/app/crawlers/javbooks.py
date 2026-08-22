"""
JavBooks 爬虫 — 台湾有码磁力站（繁体中文）

- 搜索: https://javbooks.com/serchinfo_censored/{前缀}/serialbt_1.htm（按番号前缀分组）
- 详情: https://javbooks.com/content_censored/{id}.htm
  - 完整元数据：番号/标题/发行时间/时长/导演/制作商/发行商/系列/类别/女优/封面
- 女优: https://javbooks.com/serchinfo_censored/{performer_id}/performerbt_1.htm
  - 可列出该女优全部历史作品 → 用于演员作品对比/查重
- 磁力: 详情页内嵌（reurl 混淆编码，本爬虫解析名称/容量/日期，不做解码）

实测：大陆直连超时，需走代理。
"""
import logging
import re
from datetime import date
from typing import Optional

from parsel import Selector

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

# 常见番号前缀（用于搜索页跳转兜底）
_CODE_PREFIX_RE = re.compile(r"^([A-Za-z]{2,8})[-_ ]?(\d+)", re.I)


@register_crawler
class JavBooksCrawler(BaseCrawler):
    """JavBooks 爬虫（HTML 解析，台湾有码磁力站）"""

    name = "javbooks"
    display_name = "JavBooks"
    base_url = "https://javbooks.com"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "JavBooks 台湾有码磁力站，含完整元数据 + 女优作品列表"
    language = "zh"
    requires_proxy = True  # 大陆直连超时，需走代理

    # ------------------------------------------------------------------
    # 刮削入口
    # ------------------------------------------------------------------
    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号：搜索页 → 精确匹配番号 → 详情页解析"""
        # 1) 从番号提取前缀（FNS-238 → FNS），用于搜索页
        prefix = self._extract_prefix(code)
        if not prefix:
            return None

        # 2) 搜索页找精确匹配的详情页 URL
        detail_url = await self._find_detail_url(prefix, code)
        if not detail_url:
            logger.debug(f"JavBooks {code}: 搜索页未找到匹配条目")
            self.mark_error()
            return None

        # 3) 抓详情页
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            html_text = await client.get_text(detail_url, headers=self._headers())
            if not html_text:
                self.mark_error()
                return None

        result = self._parse_detail_page(html_text, code, detail_url)
        if result:
            self.mark_success()
        else:
            self.mark_error()
        return result

    # ------------------------------------------------------------------
    # 搜索入口（抽象方法）
    # ------------------------------------------------------------------
    async def search(self, keyword: str) -> list[ScrapeResult]:
        """按关键词搜索：优先按番号前缀搜索页，返回匹配结果"""
        keyword = keyword.strip()
        if not keyword:
            return []
        results: list[ScrapeResult] = []

        # 番号带前缀（FNS-238）→ 走前缀搜索页
        prefix = self._extract_prefix(keyword)
        code_upper = keyword.replace("_", "-").upper()
        if prefix:
            detail_url = await self._find_detail_url(prefix, code_upper)
            if detail_url:
                async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
                    html_text = await client.get_text(detail_url, headers=self._headers())
                if html_text:
                    result = self._parse_detail_page(html_text, code_upper, detail_url)
                    if result:
                        results.append(result)
            return results

        # 无前缀番号 / 普通关键词 → 遍历 A-Z 前缀搜索页模糊匹配（最多试 3 个前缀）
        tried = 0
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if tried >= 3:
                break
            detail_url = await self._find_detail_url(ch, code_upper)
            if not detail_url:
                continue
            tried += 1
            async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
                html_text = await client.get_text(detail_url, headers=self._headers())
            if html_text:
                result = self._parse_detail_page(html_text, code_upper, detail_url)
                if result:
                    results.append(result)
            break
        return results

    # ------------------------------------------------------------------
    # 搜索页 → 详情 URL
    # ------------------------------------------------------------------
    async def _find_detail_url(self, prefix: str, code: str) -> Optional[str]:
        """在搜索页中查找番号精确匹配的详情页 URL。

        搜索页按番号前缀组织：serchinfo_censored/{prefix}/serialbt_N.htm
        （serialbt 磁力列表页条目最全；若找不到再试 serialall 全部影片页）
        支持翻页，最多翻 5 页，确保 IPZZ 等靠后的番号也能找到。
        """
        code_norm = code.replace("_", "-").upper()
        max_pages = 20
        for page_kind in ("serialbt", "serialall"):
            for page_num in range(1, max_pages + 1):
                search_url = (
                    f"{self.base_url}/serchinfo_censored/{prefix}/{page_kind}_{page_num}.htm"
                )
                try:
                    async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
                        html_text = await client.get_text(
                            search_url, headers=self._headers()
                        )
                    if not html_text:
                        continue
                    sel = Selector(html_text)
                    found_any = False
                    for topic in sel.css("div.Po_topic"):
                        found_any = True
                        date_serial = topic.css(
                            "div.Po_topic_Date_Serial font ::text"
                        ).get() or ""
                        topic_code = date_serial.split("/")[0].strip().upper()
                        if topic_code and topic_code != code_norm:
                            continue
                        href = topic.css(
                            "div.Po_topic_title a::attr(href)"
                        ).get() or topic.css("div.Po_topicCG a::attr(href)").get()
                        if href and "/content_censored/" in href:
                            if not href.startswith("http"):
                                href = self.base_url + href
                            return href
                    # 本页无任何条目，停止翻页
                    if not found_any:
                        break
                except Exception as e:
                    logger.debug(f"JavBooks 搜索页失败 [{search_url}]: {e}")
                    break
        return None

    # ------------------------------------------------------------------
    # 详情页解析
    # ------------------------------------------------------------------
    def _parse_detail_page(
        self, html_text: str, code: str, source_url: str
    ) -> Optional[ScrapeResult]:
        """解析详情页 HTML → ScrapeResult"""
        sel = Selector(html_text)

        title = (
            sel.css("#title b ::text").get()
            or sel.css("#title ::text").get()
            or code
        ).strip()

        # 番号（以详情页为准，兜底用传入 code）
        page_code = (
            sel.xpath(
                '//div[@class="infobox"]/b[contains(text(),"番號")]/following-sibling::*[1]//text()'
            ).get("")
            or sel.xpath(
                '//div[@class="infobox"]/b[contains(text(),"番號")]/following-sibling::text()'
            ).get("")
            or code
        )
        page_code = re.sub(r"\s+", "", str(page_code)).strip() or code

        # 发行时间
        release_date = self._extract_info_text(
            sel, "發行時間"
        )
        parsed_date = None
        if release_date:
            try:
                parsed_date = date.fromisoformat(release_date.strip()[:10])
            except (ValueError, TypeError):
                pass

        # 时长
        duration = None
        duration_text = self._extract_info_text(sel, "影片時長")
        if duration_text:
            m = re.search(r"(\d+)", duration_text)
            if m:
                duration = int(m.group(1))

        # 导演 / 制作商 / 发行商 / 系列
        director = self._extract_link_text(sel, "導演")
        maker = self._extract_link_text(sel, "製作商")
        issuer = self._extract_link_text(sel, "發行商")
        series_raw = self._extract_info_raw(sel, "系列")
        series = None
        if series_raw and series_raw.strip() != "----":
            series = series_raw.strip()

        # 类别
        genres = self._extract_category_links(sel, "影片類別")
        genres = [g for g in genres if g and g != "0"]

        # 女优
        actors = self._extract_performers(sel)

        # 封面
        cover_url = sel.css("div.info_cg img::attr(src)").get() or None

        # 磁力列表（名称/容量/日期）
        magnets = self._extract_magnets(sel)

        result = ScrapeResult(
            code=page_code,
            title=title,
            source=self.name,
            source_url=source_url,
            studio=maker,          # 制作商
            label=issuer,          # 发行商（javbooks 的"發行商"≈ label）
            series=series,
            release_date=parsed_date,
            duration=duration,
            genres=genres,
            actors=actors,
            directors=[director] if director else [],
            cover_url=cover_url,
            poster_url=cover_url,
        )
        if magnets:
            result.raw_data["magnets"] = magnets
        return result

    # ------------------------------------------------------------------
    # 女优作品列表（演员作品对比用）
    # ------------------------------------------------------------------
    async def fetch_actress_movies(
        self, performer_id: str, max_pages: int = 1
    ) -> list[dict]:
        """抓取指定女优的全部作品列表（performerbt 页）。

        Args:
            performer_id: 女优 ID（详情页女优链接中的数字，如 38330）
            max_pages: 最多抓几页（每页约 50 部）

        Returns:
            [{"title": str, "code": str, "date": str, "url": str}, ...]
        """
        movies: list[dict] = []
        for page in range(1, max_pages + 1):
            url = (
                f"{self.base_url}/serchinfo_censored/{performer_id}/"
                f"performerbt_{page}.htm"
            )
            try:
                async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
                    html_text = await client.get_text(url, headers=self._headers())
                if not html_text:
                    break
                sel = Selector(html_text)
                found = 0
                for topic in sel.css("div.Po_topic"):
                    title = (
                        topic.css("div.Po_topic_title b ::text").get() or ""
                    ).strip()
                    href = topic.css(
                        "div.Po_topic_title a::attr(href)"
                    ).get() or ""
                    date_serial = (
                        topic.css(
                            "div.Po_topic_Date_Serial font ::text"
                        ).get()
                        or ""
                    )
                    parts = [p.strip() for p in date_serial.split("/")]
                    code = parts[0] if parts else ""
                    movie_date = parts[1] if len(parts) > 1 else ""
                    if not title and not code:
                        continue
                    movies.append(
                        {
                            "title": title,
                            "code": code,
                            "date": movie_date,
                            "url": href,
                        }
                    )
                    found += 1
                if found == 0:
                    break
            except Exception as e:
                logger.debug(f"JavBooks 女优作品页失败 [{url}]: {e}")
                break
        return movies

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _headers() -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        }

    @staticmethod
    def _extract_prefix(code: str) -> Optional[str]:
        """从番号提取字母前缀（FNS-238 → FNS；纯数字返回 None）"""
        m = _CODE_PREFIX_RE.match(code.strip())
        if m:
            return m.group(1).upper()
        return None

    @staticmethod
    def _extract_info_text(sel: Selector, label: str) -> Optional[str]:
        """提取 infobox 中某标签后的纯文本（无链接，如 發行時間/影片時長）"""
        text = sel.xpath(
            f'//div[@class="infobox"]/b[contains(text(),"{label}")]/following-sibling::text()[1]'
        ).get("")
        return text.strip() if text else None

    @staticmethod
    def _extract_link_text(sel: Selector, label: str) -> Optional[str]:
        """提取 infobox 中某标签后的链接文本（如 導演/製作商/發行商）"""
        text = sel.xpath(
            f'//div[@class="infobox"]/b[contains(text(),"{label}")]/following-sibling::a[1]//text()'
        ).get("")
        return text.strip() if text else None

    @staticmethod
    def _extract_info_raw(sel: Selector, label: str) -> Optional[str]:
        """提取 infobox 中某标签后的原始 HTML 文本（含 <br> 后内容）"""
        node = sel.xpath(
            f'//div[@class="infobox"]/b[contains(text(),"{label}")]/..'
        )
        if not node:
            return None
        raw = node.get()
        # 去掉开头的 "<b>标签：</b>" 部分
        raw = re.sub(rf"^.*<b>.*?</b>\s*", "", raw, flags=re.S)
        # 去掉链接标签，保留文本
        text = re.sub(r"<[^>]+>", "", raw)
        return text.strip() if text.strip() else None

    @staticmethod
    def _extract_category_links(sel: Selector, label: str) -> list[str]:
        """提取类别链接文本（影片類別 后的所有 <a> 文本）"""
        texts = sel.xpath(
            f'//div[@class="infobox"]/b[contains(text(),"{label}")]/following-sibling::a//text()'
        ).getall()
        return [t.strip() for t in texts if t.strip()]

    @staticmethod
    def _extract_performers(sel: Selector) -> list[ActorInfo]:
        """提取女优（头像 + 名字 + performer 链接）"""
        actors: list[ActorInfo] = []
        for box in sel.css("div.av_performer_cg_box"):
            name = (
                box.css("div.av_performer_name_box a ::text").get() or ""
            ).strip()
            avatar = box.css("img::attr(src)").get() or None
            if name:
                actors.append(
                    ActorInfo(
                        name=name,
                        japanese_name=name,
                        avatar_url=avatar,
                    )
                )
        return actors

    @staticmethod
    def _extract_magnets(sel: Selector) -> list[dict]:
        """提取磁力列表（名称/容量/日期；链接为混淆编码，不做解码）"""
        magnets: list[dict] = []
        title_nodes = sel.css("div.dht_dl_title_content span.content_bt_url")
        size_nodes = sel.css("div.dht_dl_size_content ::text").getall()
        date_nodes = sel.css("div.dht_dl_date_content ::text").getall()
        for idx, node in enumerate(title_nodes):
            name = (
                node.css("a ::text").get() or ""
            ).strip()
            size = size_nodes[idx].strip() if idx < len(size_nodes) else ""
            share_date = (
                date_nodes[idx].strip() if idx < len(date_nodes) else ""
            )
            if name:
                magnets.append(
                    {"name": name, "size": size, "date": share_date}
                )
        return magnets
