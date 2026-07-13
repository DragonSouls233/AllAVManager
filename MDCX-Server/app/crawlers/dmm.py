"""
DMM/FANZA 网页爬虫

通过直接爬取 dmm.co.jp 网页获取数据，作为 GraphQL API 爬虫的补充。
支持多种 URL 模式（digital/videoa、mono/dvd、digital/anime、digital/videoc）。

参考: AVDC-master/Getter/dmm.py
"""

import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import quote

from lxml import etree

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

# DMM 详情页 URL 模板列表（按优先级排序）
DMM_URL_TEMPLATES = [
    "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={cid}",
    "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid={cid}",
    "https://www.dmm.co.jp/digital/anime/-/detail/=/cid={cid}",
    "https://www.dmm.co.jp/digital/videoc/-/detail/=/cid={cid}",
]

# 年龄验证页面前缀
AGE_CHECK_PREFIX = "https://www.dmm.co.jp/age_check/=/declared=yes/?rurl="


def _convert_to_cid(number: str) -> str:
    """
    将番号转换为 DMM content_id (cid)

    规则: 前缀小写 + 数字部分零填充至5位
    例: SONE-290 -> sone00290, ABP-001 -> abp00001
    特殊: h-前缀转为 h_ (如 h_test123456789)
    """
    fanza_number = number
    # h- 前缀特殊处理
    if fanza_number.lower().startswith("h-"):
        fanza_number = fanza_number.replace("h-", "h_", 1)

    # 只保留字母、数字和下划线
    fanza_number = re.sub(r"[^0-9a-zA-Z_]", "", fanza_number)

    # 分离字母前缀和数字部分
    match = re.match(r"^([a-zA-Z_]+)(\d+)$", fanza_number)
    if not match:
        return fanza_number.lower()

    prefix = match.group(1).lower()
    digits = match.group(2).zfill(5)
    return prefix + digits


def _build_age_check_url(url: str) -> str:
    """构建年龄验证 URL"""
    return AGE_CHECK_PREFIX + quote(url, safe="")


@register_crawler
class DmmWebCrawler(BaseCrawler):
    """DMM/FANZA 网页爬虫"""

    name = "dmm_web"
    display_name = "DMM Web"
    base_url = "https://www.dmm.co.jp"

    priority = CrawlerPriority.LOW
    supported_types = ["normal"]
    supported_prefixes = []
    description = "DMM/FANZA 网页爬虫，直接解析 dmm.co.jp 页面"
    language = "ja"
    requires_proxy = False

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        依次尝试多种 URL 模式，找到有效页面后解析数据。

        Args:
            code: 番号

        Returns:
            ScrapeResult 刮削结果
        """
        cid = _convert_to_cid(code)

        async with AsyncHttpClient() as client:
            for url_template in DMM_URL_TEMPLATES:
                detail_url = url_template.format(cid=cid)
                age_check_url = _build_age_check_url(detail_url)

                try:
                    html_text = await client.get_text(age_check_url)

                    if "404 Not Found" in html_text:
                        continue

                    html = etree.fromstring(html_text, etree.HTMLParser())
                    result = self._parse_detail_page(html, html_text, code, detail_url)

                    if result:
                        self.mark_success()
                        return result

                except Exception as e:
                    logger.debug(f"DMM Web {code} URL {detail_url} 失败: {e}")
                    continue

            self.mark_error()
            logger.debug(f"DMM Web {code}: 所有 URL 模式均未找到")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail_page(
        self,
        html: etree._Element,
        raw_html: str,
        code: str,
        detail_url: str,
    ) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            title = self._get_title(html)
            if not title:
                return None

            # 获取页面上的实际番号（可能与输入不同，如零填充差异）
            page_number = self._get_number(html) or code

            cover_url = self._get_cover(html, page_number)
            actors = self._get_actors(html)
            studio = self._get_studio(html)
            runtime = self._get_runtime(html)
            label = self._get_label(html)
            release_date = self._get_release_date(html)
            genres = self._get_genres(html)
            director = self._get_director(html)
            series = self._get_series(html)
            outline = self._get_outline(html)
            extrafanart = self._get_extrafanart(raw_html)
            score = self._get_score(html)

            # 判断是否为动画类型
            is_anime = "/anime/" in detail_url

            return ScrapeResult(
                code=code,
                title=title.strip(),
                source=self.name,
                studio=studio,
                maker=label,
                label=label,
                series=series,
                release_date=release_date,
                duration=runtime,
                plot=outline,
                genres=genres,
                actors=actors if not is_anime else [],
                directors=[director] if director and not is_anime else [],
                cover_url=cover_url,
                extrafanart=extrafanart,
                rating=score,
                raw_data={
                    "detail_url": detail_url,
                    "page_number": page_number,
                },
            )

        except Exception as e:
            logger.debug(f"DMM Web 解析失败: {e}")
            return None

    # ==========================================
    # 字段提取方法
    # ==========================================

    def _get_title(self, html: etree._Element) -> Optional[str]:
        """获取标题"""
        result = html.xpath('//*[starts-with(@id, "title")]/text()')
        return result[0].strip() if result else None

    def _get_actors(self, html: etree._Element) -> list[ActorInfo]:
        """获取演员列表"""
        results = html.xpath(
            "//td[contains(text(),'出演者')]/following-sibling::td/span/a/text()"
        )
        actors = []
        for name in results:
            name = name.strip()
            if name:
                actors.append(ActorInfo(name=name))
        return actors

    def _get_studio(self, html: etree._Element) -> Optional[str]:
        """获取制作商 (メーカー)"""
        try:
            result = html.xpath(
                "//td[contains(text(),'メーカー')]/following-sibling::td/a/text()"
            )
            return result[0].strip() if result else None
        except (IndexError, TypeError):
            result = html.xpath(
                "//td[contains(text(),'メーカー')]/following-sibling::td/text()"
            )
            return result[0].strip() if result else None

    def _get_runtime(self, html: etree._Element) -> Optional[int]:
        """获取时长（分钟）"""
        result = html.xpath(
            "//td[contains(text(),'収録時間')]/following-sibling::td/text()"
        )
        if result:
            match = re.search(r"\d+", str(result[0]))
            if match:
                return int(match.group())
        return None

    def _get_label(self, html: etree._Element) -> Optional[str]:
        """获取标签/厂牌 (レーベル)"""
        try:
            result = html.xpath(
                "//td[contains(text(),'レーベル')]/following-sibling::td/a/text()"
            )
            return result[0].strip() if result else None
        except (IndexError, TypeError):
            result = html.xpath(
                "//td[contains(text(),'レーベル')]/following-sibling::td/text()"
            )
            return result[0].strip() if result else None

    def _get_number(self, html: etree._Element) -> Optional[str]:
        """获取页面上的实际番号 (品番)"""
        try:
            result = html.xpath(
                "//td[contains(text(),'品番')]/following-sibling::td/a/text()"
            )
            return result[0].strip() if result else None
        except (IndexError, TypeError):
            result = html.xpath(
                "//td[contains(text(),'品番')]/following-sibling::td/text()"
            )
            return result[0].strip() if result else None

    def _get_release_date(self, html: etree._Element) -> Optional[date]:
        """获取发行日期"""
        date_str = None

        # 优先尝试 発売日
        try:
            result = html.xpath(
                "//td[contains(text(),'発売日')]/following-sibling::td/a/text()"
            )
            date_str = result[0].strip().lstrip("\n") if result else None
        except (IndexError, TypeError):
            try:
                result = html.xpath(
                    "//td[contains(text(),'発売日')]/following-sibling::td/text()"
                )
                date_str = result[0].strip().lstrip("\n") if result else None
            except (IndexError, TypeError):
                pass

        # 如果没有発売日，尝试配信開始日
        if not date_str or date_str == "----":
            try:
                result = html.xpath(
                    "//td[contains(text(),'配信開始日')]/following-sibling::td/a/text()"
                )
                date_str = result[0].strip().lstrip("\n") if result else None
            except (IndexError, TypeError):
                try:
                    result = html.xpath(
                        "//td[contains(text(),'配信開始日')]/following-sibling::td/text()"
                    )
                    date_str = result[0].strip().lstrip("\n") if result else None
                except (IndexError, TypeError):
                    pass

        if not date_str or date_str == "----":
            return None

        date_str = date_str.replace("/", "-")
        match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
        if match:
            try:
                return date(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                )
            except ValueError:
                return None
        return None

    def _get_genres(self, html: etree._Element) -> list[str]:
        """获取标签/类型 (ジャンル)"""
        try:
            results = html.xpath(
                "//td[contains(text(),'ジャンル')]/following-sibling::td/a/text()"
            )
        except Exception:
            results = html.xpath(
                "//td[contains(text(),'ジャンル')]/following-sibling::td/text()"
            )
        return [r.strip() for r in results if r.strip()]

    def _get_cover(self, html: etree._Element, number: str) -> Optional[str]:
        """获取封面 URL"""
        # 先用原始番号尝试
        try:
            result = html.xpath(f'//*[@id="{number}"]/@href')
            if result:
                return result[0]
        except Exception:
            pass

        # 处理下划线转义: DMM 有时将 _ 替换为 \u005f
        if "_" in number:
            escaped_number = number.replace("_", "\u005f")
            try:
                result = html.xpath(f'//*[@id="{escaped_number}"]/@href')
                if result:
                    return result[0]
            except Exception:
                pass

        return None

    def _get_director(self, html: etree._Element) -> Optional[str]:
        """获取导演 (監督)"""
        try:
            result = html.xpath(
                "//td[contains(text(),'監督')]/following-sibling::td/a/text()"
            )
            return result[0].strip() if result else None
        except (IndexError, TypeError):
            try:
                result = html.xpath(
                    "//td[contains(text(),'監督')]/following-sibling::td/text()"
                )
                return result[0].strip() if result else None
            except (IndexError, TypeError):
                return None

    def _get_series(self, html: etree._Element) -> Optional[str]:
        """获取系列 (シリーズ)"""
        try:
            result = html.xpath(
                "//td[contains(text(),'シリーズ')]/following-sibling::td/a/text()"
            )
            return result[0].strip() if result else None
        except (IndexError, TypeError):
            try:
                result = html.xpath(
                    "//td[contains(text(),'シリーズ')]/following-sibling::td/text()"
                )
                return result[0].strip() if result else None
            except (IndexError, TypeError):
                return None

    def _get_outline(self, html: etree._Element) -> Optional[str]:
        """获取简介"""
        try:
            result = html.xpath("//div[@class='mg-b20 lh4']/text()")
            if result:
                text = result[0].replace("\n", "").strip()
                if text:
                    return text
            # 回退到 p 标签
            result = html.xpath("//div[@class='mg-b20 lh4']//p/text()")
            if result:
                return result[0].replace("\n", "").strip()
        except (IndexError, TypeError):
            pass
        return None

    def _get_extrafanart(self, raw_html: str) -> list[str]:
        """获取额外剧照（从 sample-image-block 中提取，替换为全尺寸图片）"""
        html_pattern = re.compile(
            r'<div id=\"sample-image-block\"[\s\S]*?<br></div></div>'
        )
        match = html_pattern.search(raw_html)
        if not match:
            return []

        block = match.group()
        img_pattern = re.compile(r'<img.*?src=\"(.*?)\"')
        img_urls = img_pattern.findall(block)

        result = []
        for img_url in img_urls:
            # 将缩略图后缀 -jp- 替换为全尺寸: xxx-jp-xxx -> xxxjp-xxx
            parts = img_url.rsplit("-", 1)
            if len(parts) == 2:
                full_url = parts[0] + "jp-" + parts[1]
                result.append(full_url)
            else:
                result.append(img_url)

        return result

    def _get_score(self, html: etree._Element) -> Optional[float]:
        """获取评分"""
        try:
            result = html.xpath("//p[@class='d-review__average']/strong/text()")
            if result:
                score_str = result[0].replace("\n", "").replace("点", "").strip()
                return float(score_str)
        except (IndexError, TypeError, ValueError):
            pass
        return None
