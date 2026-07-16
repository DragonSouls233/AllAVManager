"""
无码内容爬虫

支持站点：
- Caribbeancom (加勒比): https://www.caribbeancom.com
- Heyzo (柚月): https://www.heyzo.com
- S1 NO.1 STYLE: https://www.s1s1s1.com
- 10musume (一本道): https://www.10musume.com
- Caribbeancompr: https://www.caribbeancompr.com
- Ragdoll: https://www.ragdoll.com
"""

import re
import logging
from datetime import date
from typing import Optional
from urllib.parse import urljoin, quote

from lxml import etree

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, CrawlerStatus, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


# ==========================================
# Caribbeancom (加勒比) 爬虫
# ==========================================

@register_crawler
class CaribbeancomCrawler(BaseCrawler):
    """
    Caribbeancom (加勒比) 爬虫

    主要的无码内容站点
    搜索: https://www.caribbeancom.com/moviepages/{number}/index.html
    详情: https://www.caribbeancom.com/moviepages/{number}/index.html
    """

    name = "caribbeancom"
    display_name = "Caribbeancom"
    base_url = "https://www.caribbeancom.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["1TEST", "CARIB"]
    description = "Caribbeancom 加勒比无码"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 Caribbeancom"""
        # 转换番号格式: CARIB-123456-123 -> 123456-123
        movie_id = self._convert_code(code)
        if not movie_id:
            return None

        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, movie_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"Caribbeancom 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _convert_code(self, code: str) -> Optional[str]:
        """转换番号格式"""
        code = code.upper()
        # CARIB-123456-123 -> 123456-123
        if match := re.match(r"CARIB-?(\d{6})-?(\d{3})", code):
            return f"{match.group(1)}-{match.group(2)}"
        # 1TEST-123456-123 -> 123456-123
        if match := re.match(r"1TEST-?(\d{6})-?(\d{3})", code):
            return f"{match.group(1)}-{match.group(2)}"
        # 直接格式 123456-123
        if match := re.match(r"(\d{6})-(\d{3})", code):
            return code
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, movie_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题: 先从 h1 获取，取最长的非空文本
            title_elem = html.xpath('//h1/text()')
            title = ""
            if title_elem:
                # 取第一个 h1 的文本，清理空白
                title = title_elem[0].strip()
                # 去掉尾部可能包含的演员名（以 - 或 — 分隔）
                for sep in [" - ", " — ", " – "]:
                    parts = title.split(sep, 1)
                    if len(parts) > 1 and len(parts[0]) > len(parts[1]):
                        title = parts[0].strip()
                        break
                title = title.strip()

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="movie"]//img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//td[contains(text(), "配信日")]/following-sibling::td/text()')
            release_date = None
            if date_elem:
                date_str = date_elem[0].strip()
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 时长
            duration_elem = html.xpath('//td[contains(text(), "再生時間")]/following-sibling::td/text()')
            duration = None
            if duration_elem:
                duration_str = duration_str = duration_elem[0].strip()
                if match := re.search(r"(\d+)", duration_str):
                    duration = int(match.group(1))

            # 演员
            actors = []
            actor_elems = html.xpath('//a[contains(@href, "/actor/")]')
            for elem in actor_elems:
                name = "".join(elem.xpath(".//text()")).strip()
                if name and name not in ["一覧", "ALL"]:
                    actors.append(ActorInfo(name=name))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[contains(@href, "/genre/")]')
            for elem in genre_elems:
                genre = "".join(elem.xpath(".//text()")).strip()
                if genre:
                    genres.append(genre)

            # 制作商
            studio = "Caribbeancom"

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio=studio,
                release_date=release_date,
                duration=duration,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"Caribbeancom 解析失败 {code}: {e}")
            return None


# ==========================================
# Heyzo (柚月) 爬虫
# ==========================================

@register_crawler
class HeyzoCrawler(BaseCrawler):
    """
    Heyzo (柚月) 爬虫

    知名无码内容站点
    搜索: https://www.heyzo.com/moviepages/{number}/index.html
    详情: https://www.heyzo.com/moviepages/{number}/index.html
    """

    name = "heyzo"
    display_name = "Heyzo"
    base_url = "https://www.heyzo.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["HEYZO", "HZ"]
    description = "Heyzo 柚月无码"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 Heyzo"""
        movie_id = self._convert_code(code)
        if not movie_id:
            return None

        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, movie_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"Heyzo 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _convert_code(self, code: str) -> Optional[str]:
        """转换番号格式"""
        code = code.upper()
        # HEYZO-1234 -> 1234
        if match := re.match(r"HEYZO-?(\d{4})", code):
            return match.group(1)
        # HZ-1234 -> 1234
        if match := re.match(r"HZ-?(\d{4})", code):
            return match.group(1)
        # 直接数字
        if code.isdigit():
            return code.zfill(4)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, movie_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题: 先从 h1 获取
            title_elem = html.xpath('//h1/text()')
            title = ""
            if title_elem:
                title = title_elem[0].strip()
                # 去掉尾部可能的演员名（以 - 分隔）
                for sep in [" - ", " — ", " – "]:
                    parts = title.split(sep, 1)
                    if len(parts) > 1 and len(parts[0]) > len(parts[1]):
                        title = parts[0].strip()
                        break
                title = title.strip()

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="movie"]//img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//td[contains(text(), "配信日")]/following-sibling::td/text()')
            release_date = None
            if date_elem:
                date_str = date_elem[0].strip()
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 时长
            duration_elem = html.xpath('//td[contains(text(), "再生時間")]/following-sibling::td/text()')
            duration = None
            if duration_elem:
                duration_str = duration_elem[0].strip()
                if match := re.search(r"(\d+)", duration_str):
                    duration = int(match.group(1))

            # 演员
            actors = []
            actor_elems = html.xpath('//a[contains(@href, "/actor/")]')
            for elem in actor_elems:
                name = "".join(elem.xpath(".//text()")).strip()
                if name and name not in ["一覧", "ALL"]:
                    actors.append(ActorInfo(name=name))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[contains(@href, "/genre/")]')
            for elem in genre_elems:
                genre = "".join(elem.xpath(".//text()")).strip()
                if genre:
                    genres.append(genre)

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio="Heyzo",
                release_date=release_date,
                duration=duration,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"Heyzo 解析失败 {code}: {e}")
            return None


# ==========================================
# S1 NO.1 STYLE 爬虫
# ==========================================

@register_crawler
class S1StyleCrawler(BaseCrawler):
    """
    S1 NO.1 STYLE 爬虫

    大型无码制作商
    搜索: https://www.s1s1s1.com/moviepages/{number}/index.html
    详情: https://www.s1s1s1.com/moviepages/{number}/index.html
    """

    name = "s1style"
    display_name = "S1 NO.1 STYLE"
    base_url = "https://www.s1s1s1.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["S1", "SQS"]
    description = "S1 NO.1 STYLE 无码"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 S1"""
        movie_id = self._convert_code(code)
        if not movie_id:
            return None

        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, movie_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"S1 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _convert_code(self, code: str) -> Optional[str]:
        """转换番号格式"""
        code = code.upper()
        # S1-1234 -> 1234
        if match := re.match(r"S1-?(\d{4})", code):
            return match.group(1)
        # SQS-123 -> 0123
        if match := re.match(r"SQS-?(\d{3})", code):
            return match.group(1).zfill(4)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, movie_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//h1[@class="tag01"]//text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="movie"]//img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//td[contains(text(), "配信日")]/following-sibling::td/text()')
            release_date = None
            if date_elem:
                date_str = date_elem[0].strip()
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 时长
            duration_elem = html.xpath('//td[contains(text(), "再生時間")]/following-sibling::td/text()')
            duration = None
            if duration_elem:
                duration_str = duration_elem[0].strip()
                if match := re.search(r"(\d+)", duration_str):
                    duration = int(match.group(1))

            # 演员
            actors = []
            actor_elems = html.xpath('//a[contains(@href, "/actor/")]')
            for elem in actor_elems:
                name = "".join(elem.xpath(".//text()")).strip()
                if name and name not in ["一覧", "ALL"]:
                    actors.append(ActorInfo(name=name))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[contains(@href, "/genre/")]')
            for elem in genre_elems:
                genre = "".join(elem.xpath(".//text()")).strip()
                if genre:
                    genres.append(genre)

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio="S1 NO.1 STYLE",
                release_date=release_date,
                duration=duration,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"S1 解析失败 {code}: {e}")
            return None


# ==========================================
# 10musume (一本道) 爬虫
# ==========================================

@register_crawler
class TenMusumeCrawler(BaseCrawler):
    """
    10musume (一本道) 爬虫

    经典无码系列
    搜索: https://www.10musume.com/moviepages/{number}/index.html
    详情: https://www.10musume.com/moviepages/{number}/index.html
    """

    name = "10musume"
    display_name = "10musume"
    base_url = "https://www.10musume.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["10MUSUME", "1POND"]
    description = "10musume 一本道无码"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 10musume"""
        movie_id = self._convert_code(code)
        if not movie_id:
            return None

        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, movie_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"10musume 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _convert_code(self, code: str) -> Optional[str]:
        """转换番号格式"""
        code = code.upper()
        # 10MUSUME-1234 -> 1234
        if match := re.match(r"10MUSUME-?(\d{4})", code):
            return match.group(1)
        # 1POND-1234 -> 1234
        if match := re.match(r"1POND-?(\d{4})", code):
            return match.group(1)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, movie_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//h1[@class="tag01"]//text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="movie"]//img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 发行日期
            date_elem = html.xpath('//td[contains(text(), "配信日")]/following-sibling::td/text()')
            release_date = None
            if date_elem:
                date_str = date_elem[0].strip()
                if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str):
                    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

            # 时长
            duration_elem = html.xpath('//td[contains(text(), "再生時間")]/following-sibling::td/text()')
            duration = None
            if duration_elem:
                duration_str = duration_elem[0].strip()
                if match := re.search(r"(\d+)", duration_str):
                    duration = int(match.group(1))

            # 演员
            actors = []
            actor_elems = html.xpath('//a[contains(@href, "/actor/")]')
            for elem in actor_elems:
                name = "".join(elem.xpath(".//text()")).strip()
                if name and name not in ["一覧", "ALL"]:
                    actors.append(ActorInfo(name=name))

            # 标签
            genres = []
            genre_elems = html.xpath('//a[contains(@href, "/genre/")]')
            for elem in genre_elems:
                genre = "".join(elem.xpath(".//text()")).strip()
                if genre:
                    genres.append(genre)

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio="10musume",
                release_date=release_date,
                duration=duration,
                genres=genres,
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"10musume 解析失败 {code}: {e}")
            return None


# ==========================================
# Caribbeancompr 爬虫
# ==========================================

@register_crawler
class CaribbeancomprCrawler(BaseCrawler):
    """
    Caribbeancompr (加勒比 Premium) 爬虫

    Caribbeancom 的高清版
    """

    name = "caribbeancompr"
    display_name = "Caribbeancompr"
    base_url = "https://www.caribbeancompr.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["CARIBPR"]
    description = "Caribbeancompr 加勒比Premium无码"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 Caribbeancompr"""
        # 使用与 Caribbeancom 相同的格式
        movie_id = self._convert_code(code)
        if not movie_id:
            return None

        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, movie_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"Caribbeancompr 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _convert_code(self, code: str) -> Optional[str]:
        """转换番号格式"""
        code = code.upper()
        # CARIBPR-123456-123 -> 123456-123
        if match := re.match(r"CARIBPR-?(\d{6})-?(\d{3})", code):
            return f"{match.group(1)}-{match.group(2)}"
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, movie_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//h1[@class="tag01"]//text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="movie"]//img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 演员
            actors = []
            actor_elems = html.xpath('//a[contains(@href, "/actor/")]')
            for elem in actor_elems:
                name = "".join(elem.xpath(".//text()")).strip()
                if name and name not in ["一覧", "ALL"]:
                    actors.append(ActorInfo(name=name))

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio="Caribbeancompr",
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"Caribbeancompr 解析失败 {code}: {e}")
            return None


# ==========================================
# Ragdoll 爬虫
# ==========================================

@register_crawler
class RagdollCrawler(BaseCrawler):
    """
    Ragdoll 爬虫

    知名无码制作商
    """

    name = "ragdoll"
    display_name = "Ragdoll"
    base_url = "https://www.ragdoll.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["RAGDOLL", "RGD"]
    description = "Ragdoll 无码"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削 Ragdoll"""
        movie_id = self._convert_code(code)
        if not movie_id:
            return None

        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"

        async with AsyncHttpClient(timeout=30) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    self.mark_error()
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())
                result = self._parse_detail(html, code, movie_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                logger.debug(f"Ragdoll 刮削失败 {code}: {e}")
                self.mark_error()
                return None

    def _convert_code(self, code: str) -> Optional[str]:
        """转换番号格式"""
        code = code.upper()
        # RAGDOLL-123 -> 0123
        if match := re.match(r"RAGDOLL-?(\d{3})", code):
            return match.group(1).zfill(4)
        # RGD-123 -> 0123
        if match := re.match(r"RGD-?(\d{3})", code):
            return match.group(1).zfill(4)
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索功能暂不实现"""
        return []

    def _parse_detail(self, html: etree._Element, code: str, movie_id: str) -> Optional[ScrapeResult]:
        """解析详情页"""
        try:
            # 标题
            title_elem = html.xpath('//h1[@class="tag01"]//text()')
            title = "".join(title_elem).strip() if title_elem else ""

            if not title:
                return None

            # 封面
            cover_elem = html.xpath('//div[@class="movie"]//img/@src')
            cover_url = None
            if cover_elem:
                cover_url = cover_elem[0]
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url

            # 演员
            actors = []
            actor_elems = html.xpath('//a[contains(@href, "/actor/")]')
            for elem in actor_elems:
                name = "".join(elem.xpath(".//text()")).strip()
                if name and name not in ["一覧", "ALL"]:
                    actors.append(ActorInfo(name=name))

            return ScrapeResult(
                code=code,
                title=title,
                source=self.name,
                studio="Ragdoll",
                actors=actors,
                cover_url=cover_url,
                poster_url=cover_url,
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"Ragdoll 解析失败 {code}: {e}")
            return None
