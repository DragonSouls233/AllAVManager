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
from app.utils.nfo_runtime import parse_runtime_minutes

logger = logging.getLogger(__name__)


# ==========================================
# 共用：时长抽取（DMM 系模板）
# ==========================================

def extract_moviepage_duration(html: etree._Element) -> Optional[int]:
    """从 DMM 系无码站详情页抽时长（分钟）。

    🔴 2026-10-04 新增：Caribbeancompr / Ragdoll / Kin8tengoku / Pacopacomama /
    Gachi / T28 这 6 个源此前**完全没解析 duration**（同文件另外 4 个源有），
    结果：无码模块一半的源产出条目 `duration=None`，NFO 里的 `<runtime>` 空缺。
    静默缺字段比解析错更难发现（不报错，只是少了东西）。

    这 6 家都是同一套 DMM `moviepages` 模板，所以共用本函数；
    多写几个 xpath 变体是因为模板字段位置有细微差异。
    解析统一走 `parse_runtime_minutes`（唯一真相源，契约=分钟）。
    """
    # 防御：`etree.HTML('')` 对空字符串返回 None（不是根元素）
    if html is None:
        return None
    # 变体1（主流）：<td>再生時間</td><td>01:52:37</td> —— DMM 标准详情表
    elems = html.xpath(
        '//td[contains(text(), "再生時間")]/following-sibling::td[1]/text()'
    )
    # 变体2：<span>再生時間</span>：01:52:37
    if not elems:
        elems = html.xpath('//span[contains(text(), "動画時間")]/../text()')
    # 变体3：<div class="info">再生時間：01:52:37</div>（同一节点内）
    if not elems:
        for node in html.xpath('//*[contains(text(), "再生時間")]'):
            raw = "".join(node.itertext()).strip()
            elems = [raw]
            break
    for raw in elems:
        if raw and raw.strip():
            parsed = parse_runtime_minutes(raw.strip())
            if parsed:
                return parsed
    return None



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

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
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
                elif cover_url.startswith("/"):
                    cover_url = urljoin(self.base_url, cover_url)

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
                duration = parse_runtime_minutes(duration_str)

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

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
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
                elif cover_url.startswith("/"):
                    cover_url = urljoin(self.base_url, cover_url)

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
                duration = parse_runtime_minutes(duration_str)

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

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
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
                elif cover_url.startswith("/"):
                    cover_url = urljoin(self.base_url, cover_url)

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
                duration = parse_runtime_minutes(duration_str)

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

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
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
                elif cover_url.startswith("/"):
                    cover_url = urljoin(self.base_url, cover_url)

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
                duration = parse_runtime_minutes(duration_str)

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

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
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
                elif cover_url.startswith("/"):
                    cover_url = urljoin(self.base_url, cover_url)

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
                duration=extract_moviepage_duration(html),
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

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
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
        """转换番号格式

        🔴 2026-10-04 修复：原正则 `RAGDOLL-?(\\d{3})` **硬编码只取 3 位数字**。
        真实 Ragdoll 番号是 4 位（站点 URL 就是 `/movie/0123/`、`/movie/1234/`），
        所以 `RAGDOLL-1234` 会被截成 `0123` ⇒ 去抓了**另一部影片**（张冠李戴），
        而且是静默的：能返回 200、标题也是真的，只是内容跟番号对不上。
        现在改成 `\\d{3,4}`，并按位数决定 zfill 目标。
        """
        code = code.upper().strip()
        # RAGDOLL-1234 -> 1234（4 位已是最终值）；RAGDOLL-123 -> 0123（3 位补零）
        if match := re.match(r"RAGDOLL-?(\d{3,4})\b", code):
            digits = match.group(1)
            return digits.zfill(4) if len(digits) == 3 else digits
        # RGD-1234 -> 同上（RGD 是 Ragdoll 的短前缀）
        if match := re.match(r"RGD-?(\d{3,4})\b", code):
            digits = match.group(1)
            return digits.zfill(4) if len(digits) == 3 else digits
        # 🔴 纯数字输入（如 1234 / 0123）也应能直接用，此前一律返 None
        if re.fullmatch(r"\d{3,4}", code):
            return code.zfill(4)
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
                elif cover_url.startswith("/"):
                    cover_url = urljoin(self.base_url, cover_url)

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
                duration=extract_moviepage_duration(html),
                is_uncensored=True,
                is_mosaic=False,
            )

        except Exception as e:
            logger.debug(f"Ragdoll 解析失败 {code}: {e}")
            return None


# ==========================================
# KIN8TENGOKU (金8天国) 爬虫
# ==========================================

@register_crawler
class Kin8tengokuCrawler(BaseCrawler):
    """KIN8TENGOKU (金8天国) 爬虫"""

    name = "kin8tengoku"
    display_name = "KIN8TENGOKU"
    base_url = "https://www.kin8tengoku.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["KIN8TENGOKU", "KIN8"]
    description = "KIN8TENGOKU 金8天国无码"
    language = "ja"
    requires_proxy = True

    def _convert_code(self, code: str) -> Optional[str]:
        code = code.upper().replace("KIN8TENGOKU-", "").replace("KIN8-", "").replace("KIN8", "")
        return code.strip() if code else None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        movie_id = self._convert_code(code)
        if not movie_id:
            return None
        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    return None
                html = etree.fromstring(html_text)
                return self._parse_detail(html, code, movie_id)
            except Exception as e:
                logger.debug(f"kin8tengoku 刮削失败 {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    def _parse_detail(self, html, code: str, movie_id: str) -> Optional[ScrapeResult]:
        try:
            title = html.xpath('//h1/text()')[0].strip() if html.xpath('//h1/text()') else ""
            if not title:
                return None
            cover = html.xpath('//img[contains(@src,"cap") or contains(@class,"movie_image")]/@src')
            cover_url = cover[0] if cover else None
            actors = [ActorInfo(name=a.strip()) for a in html.xpath('//a[contains(@href,"actor")]/text()') if a.strip()]
            return ScrapeResult(
                code=code, title=title, source=self.name, studio="KIN8TENGOKU",
                cover_url=cover_url, actors=actors,
                duration=extract_moviepage_duration(html),
                is_uncensored=True, is_mosaic=False,
            )
        except Exception as e:
            logger.debug(f"kin8tengoku 解析失败 {code}: {e}")
            return None


# ==========================================
# PACOPACOMAMA 爬虫
# ==========================================

@register_crawler
class PacopacomamaCrawler(BaseCrawler):
    """PACOPACOMAMA 爬虫"""

    name = "pacopacomama"
    display_name = "Pacopacomama"
    base_url = "https://www.pacopacomama.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["PACOPACOMAMA", "PPM"]
    description = "Pacopacomama 无码"
    language = "ja"
    requires_proxy = True

    def _convert_code(self, code: str) -> Optional[str]:
        code = code.upper().replace("PACOPACOMAMA-", "").replace("PPM-", "")
        return code.strip() if code else None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        movie_id = self._convert_code(code)
        if not movie_id:
            return None
        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    return None
                html = etree.fromstring(html_text)
                return self._parse_detail(html, code, movie_id)
            except Exception as e:
                logger.debug(f"pacopacomama 刮削失败 {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    def _parse_detail(self, html, code: str, movie_id: str) -> Optional[ScrapeResult]:
        try:
            title = "".join(html.xpath('//h1//text()')).strip()
            if not title:
                return None
            cover = html.xpath('//img[contains(@class,"movie_image")]/@src')
            cover_url = cover[0] if cover else None
            return ScrapeResult(
                code=code, title=title, source=self.name, studio="PACOPACOMAMA",
                cover_url=cover_url, duration=extract_moviepage_duration(html),
                is_uncensored=True, is_mosaic=False,
            )
        except Exception as e:
            logger.debug(f"pacopacomama 解析失败 {code}: {e}")
            return None


# ==========================================
# GACHI (ガチ) 爬虫
# ==========================================

@register_crawler
class GachiCrawler(BaseCrawler):
    """GACHI (ガチネット) 爬虫"""

    name = "gachi"
    display_name = "GACHI"
    base_url = "https://www.gachinet.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["GACHI", "GACHINET"]
    description = "GACHI ガチネット无码"
    language = "ja"
    requires_proxy = True

    def _convert_code(self, code: str) -> Optional[str]:
        return code.upper().replace("GACHI-", "").replace("GACHINET-", "").replace("GACHI", "").strip() or None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        movie_id = self._convert_code(code)
        if not movie_id:
            return None
        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    return None
                html = etree.fromstring(html_text)
                return self._parse_detail(html, code, movie_id)
            except Exception as e:
                logger.debug(f"gachi 刮削失败 {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    def _parse_detail(self, html, code: str, movie_id: str) -> Optional[ScrapeResult]:
        try:
            title = "".join(html.xpath('//h1//text()')).strip()
            if not title:
                return None
            cover = html.xpath('//img[contains(@src,"cap") or contains(@class,"movie_image")]/@src')
            cover_url = cover[0] if cover else None
            actors = [ActorInfo(name=a.strip()) for a in html.xpath('//a[contains(@href,"actor")]/text()') if a.strip()]
            return ScrapeResult(
                code=code, title=title, source=self.name, studio="GACHI",
                cover_url=cover_url, actors=actors,
                duration=extract_moviepage_duration(html),
                is_uncensored=True, is_mosaic=False,
            )
        except Exception as e:
            logger.debug(f"gachi 解析失败 {code}: {e}")
            return None


# ==========================================
# T28 (T28-TOKYO) 爬虫
# ==========================================

@register_crawler
class T28Crawler(BaseCrawler):
    """T28 (T28-TOKYO) 爬虫"""

    name = "t28"
    display_name = "T28-TOKYO"
    base_url = "https://www.t28-tokyo.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["jav_uncensored"]
    supported_prefixes = ["T28"]
    description = "T28-TOKYO 无码"
    language = "ja"
    requires_proxy = True

    def _convert_code(self, code: str) -> Optional[str]:
        return code.upper().replace("T28-", "").replace("T28", "").strip() or None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        movie_id = self._convert_code(code)
        if not movie_id:
            return None
        detail_url = f"{self.base_url}/moviepages/{movie_id}/index.html"
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html_text = await client.get_text(detail_url)
                if not html_text or "404" in html_text:
                    return None
                html = etree.fromstring(html_text)
                return self._parse_detail(html, code, movie_id)
            except Exception as e:
                logger.debug(f"t28 刮削失败 {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    def _parse_detail(self, html, code: str, movie_id: str) -> Optional[ScrapeResult]:
        try:
            title = "".join(html.xpath('//h1//text()')).strip()
            if not title:
                return None
            cover = html.xpath('//img[contains(@src,"cap")]/@src')
            cover_url = cover[0] if cover else None
            return ScrapeResult(
                code=code, title=title, source=self.name, studio="T28",
                cover_url=cover_url, duration=extract_moviepage_duration(html),
                is_uncensored=True, is_mosaic=False,
            )
        except Exception as e:
            logger.debug(f"t28 解析失败 {code}: {e}")
            return None
