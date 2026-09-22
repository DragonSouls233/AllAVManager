"""
FC2 JavBus 爬虫 — 通过 javbus FC2 页面补全 FC2 影片的演员与高清封面。

背景：
- FC2 官方直连页（app/crawlers/fc2.py）几乎不提供演员名，且封面仅为缩略图。
- FC2PPVDB（fc2ppvdb.py）虽能补演员，但是单一第三方数据库，一旦不可用 FC2 就丢失演员信息。
- JavBus 有完整的 FC2 分站（https://www.javbus.com/fc2/{id}），演员与封面质量高，且由
  引擎 merger 对 actors 做并集去重，可与 fc2 / fc2ppvdb / fc2_enhanced(DMM) 多源合并。

参考：ref107-garage/garage_jav/javbus.go 的 JavBus 解析（h3 标题、.screencap 封面、star-name 演员）。
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
from app.utils.cf_bypass import get_cf_bypass

logger = logging.getLogger(__name__)

_JAVBUS_FC2_URL = "https://www.javbus.com/fc2/{number_id}"


@register_crawler
class FC2JavbusCrawler(BaseCrawler):
    """FC2 JavBus 补全爬虫 — 提供演员与高清封面（多源合并中的一员）。"""

    name = "fc2_javbus"
    display_name = "FC2 JavBus"
    base_url = "https://www.javbus.com"

    # 低于直连页(HIGH)，高于其它补充源；演员由 merger 并集，封面按策略择优
    priority = CrawlerPriority.NORMAL
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-"]
    description = "FC2 JavBus 补全（演员/高清封面），参考 garage javbus 解析"
    language = "ja"
    requires_proxy = False

    def _extract_number_id(self, code: str) -> Optional[str]:
        """从番号中提取纯数字 ID（如 FC2-123456 → 123456）"""
        if not code:
            return None
        m = re.search(r"(\d{5,7})", code.strip())
        return m.group(1) if m else None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """FC2 JavBus 补全源不做关键词搜索，仅按番号补全。"""
        return []

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        url = _JAVBUS_FC2_URL.format(number_id=number_id)

        html_text = None
        try:
            # JavBus 位于 Cloudflare 之后，复用 cf_bypass 多级反爬
            bypass = await get_cf_bypass().fetch(url, timeout=30, max_retries=2)
            if bypass.success and bypass.html:
                html_text = bypass.html
            else:
                logger.warning(f"FC2 JavBus cf_bypass 失败 [{code}]: {bypass.error}")
        except Exception as e:
            logger.warning(f"FC2 JavBus 请求异常 [{code}]: {e}")

        if not html_text:
            self.mark_error()
            return None

        try:
            html = etree.fromstring(html_text.encode("utf-8"), etree.HTMLParser())
        except Exception:
            self.mark_error()
            return None

        result = self._parse(html, code, url)
        if result:
            self.mark_success()
        else:
            self.mark_error()
        return result

    def _parse(
        self, html: etree._Element, code: str, source_url: str
    ) -> Optional[ScrapeResult]:
        # 标题（h3）缺失则视为页面未命中
        title = self._text(html, "//h3/text()")
        if not title:
            return None

        cover_url = self._attr(html, '//div[@class="screencap"]/a/img/@src')
        if not cover_url:
            cover_url = self._attr(html, '//a[@class="bigImage"]/img/@src')
        if cover_url and cover_url.startswith("//"):
            cover_url = "https:" + cover_url

        actors = [
            ActorInfo(name=n.strip())
            for n in self._texts(html, '//span[contains(@class, "star-name")]/a/text()')
            if n.strip()
        ]

        release_date = self._parse_date(html)
        duration = self._parse_duration(html)
        _UNCENSORED_MARKERS = {"無修正", "无修正", "uncensored", "Uncensored"}
        genres = [
            g.strip()
            for g in self._texts(
                html,
                '//p[contains(., "類別") or contains(., "类别") '
                'or contains(., "Genre") or contains(., "Category")]//a/text()',
            )
            if g.strip() and g.strip() not in _UNCENSORED_MARKERS
        ]

        return ScrapeResult(
            code=code,
            title=title,
            original_title=title,
            source=self.name,
            source_url=source_url,
            cover_url=cover_url,
            poster_url=cover_url,
            release_date=release_date,
            duration=duration,
            genres=genres,
            actors=actors,
            is_uncensored=True,  # FC2-PPV 默认无码
        )

    # ── 小工具 ──
    @staticmethod
    def _text(html: etree._Element, xpath: str) -> Optional[str]:
        r = html.xpath(xpath)
        return r[0].strip() if r and r[0] and r[0].strip() else None

    @staticmethod
    def _texts(html: etree._Element, xpath: str) -> list[str]:
        return [t.strip() for t in html.xpath(xpath) if isinstance(t, str)]

    @staticmethod
    def _attr(html: etree._Element, xpath: str) -> Optional[str]:
        r = html.xpath(xpath)
        return r[0].strip() if r and r[0] else None

    @staticmethod
    def _parse_date(html: etree._Element) -> Optional[date]:
        # JavBus: <p><span>發行日期:</span> 2021-01-01</p>
        for p in html.xpath('//div[@class="info"]//p'):
            txt = " ".join(p.xpath(".//text()"))
            if "發行日期" in txt or "发行日期" in txt:
                if m := re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", txt):
                    try:
                        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError:
                        return None
        return None

    @staticmethod
    def _parse_duration(html: etree._Element) -> Optional[int]:
        # JavBus: <p><span>長度:</span> 120分鐘</p>
        for p in html.xpath('//div[@class="info"]//p'):
            txt = " ".join(p.xpath(".//text()"))
            if "長度" in txt or "长度" in txt:
                if m := re.search(r"(\d+)", txt):
                    return int(m.group(1))
        return None
