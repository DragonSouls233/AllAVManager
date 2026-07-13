"""
演员资料刮削器核心实现

支持多个来源抓取演员资料：
- DMM Actress: https://www.dmm.co.jp/idol/
- JavWiki: https://javwiki.com/
- AV Open: https://avopen.com/
- AVWikiDB: https://avwikidb.com/
- TheMovieDB: https://www.themoviedb.org/
- Gfriends: GitHub 头像库
"""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

from lxml import etree
from parsel import Selector

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


# 星座计算表（月,日 -> 星座名）
_ZODIAC_RANGES = [
    ((3, 21), (4, 19), "白羊座"),
    ((4, 20), (5, 20), "金牛座"),
    ((5, 21), (6, 21), "双子座"),
    ((6, 22), (7, 22), "巨蟹座"),
    ((7, 23), (8, 22), "狮子座"),
    ((8, 23), (9, 22), "处女座"),
    ((9, 23), (10, 23), "天秤座"),
    ((10, 24), (11, 22), "天蝎座"),
    ((11, 23), (12, 21), "射手座"),
    ((12, 22), (1, 19), "摩羯座"),
    ((1, 20), (2, 18), "水瓶座"),
    ((2, 19), (3, 20), "双鱼座"),
]


def compute_zodiac(birth_date: Optional[str]) -> Optional[str]:
    """根据出生日期计算星座

    支持格式：YYYY-MM-DD / YYYY/MM/DD / YYYY年MM月DD日
    """
    if not birth_date:
        return None
    try:
        digits = re.findall(r"\d+", birth_date)
        if len(digits) < 3:
            return None
        month, day = int(digits[1]), int(digits[2])
    except (ValueError, IndexError):
        return None
    for start, end, name in _ZODIAC_RANGES:
        if start <= end:
            if start <= (month, day) <= end:
                return name
        else:  # 跨年（摩羯座）
            if (month, day) >= start or (month, day) <= end:
                return name
    return None


def parse_debut_year(text: str) -> Optional[int]:
    """从文本中解析出道年份（支持"2018年出道"/"debut: 2018"/"出道: 2018"等）"""
    if not text:
        return None
    patterns = [
        r"出道[：:\s]*(\d{4})",
        r"デビュー[：:\s]*(\d{4})",
        r"debut[：:\s]*(\d{4})",
        r"(\d{4})\s*年\s*出道",
        r"(\d{4})\s*年\s*デビュー",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            if 1980 <= year <= 2030:
                return year
    return None


@dataclass
class ActorProfile:
    """演员资料"""
    name: str                           # 姓名
    name_jp: Optional[str] = None       # 日文名
    name_en: Optional[str] = None        # 英文名
    alias: Optional[str] = None          # 别名
    avatar_url: Optional[str] = None     # 头像URL
    birth_date: Optional[str] = None     # 出生日期
    age: Optional[int] = None            # 年龄
    height: Optional[int] = None         # 身高
    bust: Optional[int] = None           # 胸围
    waist: Optional[int] = None          # 腰围
    hip: Optional[int] = None            # 臀围
    cup: Optional[str] = None            # 罩杯
    birthplace: Optional[str] = None      # 出生地
    hobby: Optional[str] = None          # 爱好
    intro: Optional[str] = None         # 简介
    zodiac: Optional[str] = None         # 星座（v3.4 新增）
    debut_year: Optional[int] = None     # 出道年份（v3.4 新增）
    social_links: Optional[dict] = None  # 社交账号（v3.4 新增，{twitter/instagram/blog/...: url}）
    source: str = ""                     # 来源站点
    source_url: Optional[str] = None     # 来源URL


class BaseActorProfileScraper(ABC):
    """演员资料刮削器基类"""

    name: str = "base"
    display_name: str = "Base"
    base_url: str = ""

    @abstractmethod
    async def search(self, name: str) -> Optional[str]:
        """
        搜索演员并返回详情页URL

        Args:
            name: 演员姓名

        Returns:
            详情页URL，未找到返回None
        """
        pass

    @abstractmethod
    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """
        抓取演员资料

        Args:
            url: 演员详情页URL

        Returns:
            演员资料，未抓取到返回None
        """
        pass

    async def get_profile(self, name: str, name_jp: Optional[str] = None) -> Optional[ActorProfile]:
        """
        获取演员资料（搜索+抓取）

        Args:
            name: 演员姓名
            name_jp: 日文名

        Returns:
            演员资料
        """
        # 优先使用日文名搜索
        search_name = name_jp or name
        url = await self.search(search_name)
        if not url and name != search_name:
            url = await self.search(name)

        if not url:
            return None

        return await self.scrape_profile(url)


# ==========================================
# DMM Actress 刮削器
# ==========================================

class DMMActressScraper(BaseActorProfileScraper):
    """
    DMM Actress 刮削器

    DMM 是日本最大的成人内容平台，演员资料非常全面
    搜索: https://www.dmm.co.jp/idol/-/list/=/keyword={name}/
    详情: https://www.dmm.co.jp/idol/-/detail/=/id={id}/
    """

    name = "dmm_actress"
    display_name = "DMM Actress"
    base_url = "https://www.dmm.co.jp/idol"

    async def search(self, name: str) -> Optional[str]:
        """搜索 DMM Actress"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        encoded_name = quote(name)
        search_url = f"{self.base_url}/-/list/=/keyword={encoded_name}/"

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员列表中的第一个结果
                # 格式: <a href="/idol/-/detail/=/id=xxx/">
                links = html.xpath('//a[contains(@href, "/idol/-/detail/=/id=")]')
                for link in links[:5]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name in text or text in name:
                        return f"https://www.dmm.co.jp{href}"

                # 取第一个结果
                if links:
                    href = links[0].get("href", "")
                    return f"https://www.dmm.co.jp{href}"

            except Exception as e:
                logger.debug(f"DMM Actress 搜索失败 {name}: {e}")

        return None

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """抓取 DMM Actress 详情"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 姓名
                name_elem = html.xpath('//*[contains(@class, "mntl-item-title")]/text()')
                name = name_elem[0].strip() if name_elem else ""

                if not name:
                    # 备用选择器
                    name_elem = html.xpath('//h1[@class="heading"]//text()')
                    name = "".join(name_elem).strip()

                # 头像
                avatar = None
                avatar_elems = html.xpath('//img[contains(@class, "lazyload")]/@data-src')
                if avatar_elems:
                    avatar = avatar_elems[0]
                else:
                    avatar_elems = html.xpath('//img[@class="pics"]/@src')
                    if avatar_elems:
                        avatar = avatar_elems[0]

                # 资料表格
                profile = ActorProfile(name=name, source=self.name, source_url=url)

                # 解析表格
                table_rows = html.xpath('//table[@class="d-table table-spacing-m"]//tr')
                for row in table_rows:
                    th = "".join(row.xpath('.//th//text()')).strip()
                    td = "".join(row.xpath('.//td//text()')).strip()

                    if "誕生日" in th or "生年月日" in th:
                        if match := re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", td):
                            profile.birth_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
                        elif match := re.search(r"(\d{4})-(\d{2})-(\d{2})", td):
                            profile.birth_date = td
                    elif "年齢" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.age = int(match.group(1))
                    elif "身長" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.height = int(match.group(1))
                    elif "サイズ" in th or "三圍" in th or "スリーサイズ" in th:
                        # 格式: B86 W58 H85 (C Cup)
                        sizes = re.findall(r"(\d+)", td)
                        cups = re.findall(r"([A-Z])[\s-]?Cup", td, re.I)
                        if len(sizes) >= 1:
                            profile.bust = int(sizes[0])
                        if len(sizes) >= 2:
                            profile.waist = int(sizes[1])
                        if len(sizes) >= 3:
                            profile.hip = int(sizes[2])
                        if cups:
                            profile.cup = cups[0].upper()
                    elif "出身地" in th:
                        profile.birthplace = td
                    elif "血液型" in th:
                        pass  # 暂不存储
                    elif "趣味" in th or "特技" in th:
                        profile.hobby = td

                if avatar and avatar.startswith("//"):
                    avatar = "https:" + avatar
                profile.avatar_url = avatar

                return profile

            except Exception as e:
                logger.debug(f"DMM Actress 抓取失败 {url}: {e}")

        return None


# ==========================================
# JavWiki 刮削器
# ==========================================

class JavWikiScraper(BaseActorProfileScraper):
    """
    JavWiki 刮削器

    JavWiki 是一个 JAV 演员百科站
    搜索: https://javwiki.com/search?q={name}
    详情: https://javwiki.com/actress/{id}
    """

    name = "javwiki"
    display_name = "JavWiki"
    base_url = "https://javwiki.com"

    async def search(self, name: str) -> Optional[str]:
        """搜索 JavWiki"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        encoded_name = quote(name)
        search_url = f"{self.base_url}/search?q={encoded_name}"

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员链接
                links = html.xpath('//a[contains(@href, "/actress/")]')
                for link in links[:5]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name.lower() in text.lower() or text.lower() in name.lower():
                        return href if href.startswith("http") else f"{self.base_url}{href}"

                # 取第一个结果
                if links:
                    href = links[0].get("href", "")
                    return href if href.startswith("http") else f"{self.base_url}{href}"

            except Exception as e:
                logger.debug(f"JavWiki 搜索失败 {name}: {e}")

        return None

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """抓取 JavWiki 详情"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 姓名
                name_elem = html.xpath('//h1[@class="actress-name"]//text()')
                if not name_elem:
                    name_elem = html.xpath('//h1//text()')
                name = "".join(name_elem).strip() if name_elem else ""

                if not name:
                    return None

                profile = ActorProfile(name=name, source=self.name, source_url=url)

                # 头像
                avatar_elems = html.xpath('//img[@class="actress-photo"]/@src')
                if not avatar_elems:
                    avatar_elems = html.xpath('//div[@class="actress-info"]//img/@src')
                if avatar_elems:
                    avatar = avatar_elems[0]
                    if avatar.startswith("//"):
                        avatar = "https:" + avatar
                    profile.avatar_url = avatar

                # 资料
                info_items = html.xpath('//div[@class="actress-detail"]//tr')
                for item in info_items:
                    th = "".join(item.xpath('.//th//text()')).strip()
                    td = "".join(item.xpath('.//td//text()')).strip()

                    if "Birthday" in th or "生日" in th:
                        if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", td):
                            profile.birth_date = match.group(0)
                    elif "Age" in th or "年龄" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.age = int(match.group(1))
                    elif "Height" in th or "身高" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.height = int(match.group(1))
                    elif "Bust" in th or "胸围" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.bust = int(match.group(1))
                    elif "Waist" in th or "腰围" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.waist = int(match.group(1))
                    elif "Hip" in th or "臀围" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.hip = int(match.group(1))
                    elif "Cup" in th or "罩杯" in th:
                        if match := re.search(r"([A-Z])", td, re.I):
                            profile.cup = match.group(1).upper()
                    elif "Birthplace" in th or "出生地" in th:
                        profile.birthplace = td

                return profile

            except Exception as e:
                logger.debug(f"JavWiki 抓取失败 {url}: {e}")

        return None


# ==========================================
# AV Open 刮削器
# ==========================================

class AVOpenScraper(BaseActorProfileScraper):
    """
    AV Open 刮削器

    AV Open 提供演员详细资料
    搜索: https://avopen.com/search?q={name}
    详情: https://avopen.com/actress/{id}
    """

    name = "avopen"
    display_name = "AV Open"
    base_url = "https://avopen.com"

    async def search(self, name: str) -> Optional[str]:
        """搜索 AV Open"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        encoded_name = quote(name)
        search_url = f"{self.base_url}/search?q={encoded_name}"

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员链接
                links = html.xpath('//a[contains(@href, "/actress/")]')
                for link in links[:5]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name in text or text in name:
                        return href if href.startswith("http") else f"{self.base_url}{href}"

                if links:
                    href = links[0].get("href", "")
                    return href if href.startswith("http") else f"{self.base_url}{href}"

            except Exception as e:
                logger.debug(f"AV Open 搜索失败 {name}: {e}")

        return None

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """抓取 AV Open 详情"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 姓名
                name_elem = html.xpath('//h2[@class="actress-name"]/text()')
                if not name_elem:
                    name_elem = html.xpath('//h1//text()')
                name = "".join(name_elem).strip() if name_elem else ""

                if not name:
                    return None

                profile = ActorProfile(name=name, source=self.name, source_url=url)

                # 头像
                avatar_elems = html.xpath('//img[@class="actress-image"]/@src')
                if avatar_elems:
                    avatar = avatar_elems[0]
                    if avatar.startswith("//"):
                        avatar = "https:" + avatar
                    profile.avatar_url = avatar

                # 资料表
                info_items = html.xpath('//table[@class="actress-table"]//tr')
                for item in info_items:
                    th = "".join(item.xpath('.//th//text()')).strip()
                    td = "".join(item.xpath('.//td//text()')).strip()

                    if "誕生日" in th:
                        if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", td):
                            profile.birth_date = match.group(0)
                    elif "年齢" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.age = int(match.group(1))
                    elif "身長" in th:
                        if match := re.search(r"(\d+)", td):
                            profile.height = int(match.group(1))
                    elif "サイズ" in th:
                        sizes = re.findall(r"(\d+)", td)
                        cups = re.findall(r"([A-Z])", td)
                        if len(sizes) >= 1:
                            profile.bust = int(sizes[0])
                        if len(sizes) >= 2:
                            profile.waist = int(sizes[1])
                        if len(sizes) >= 3:
                            profile.hip = int(sizes[2])
                        if cups:
                            profile.cup = cups[0].upper()
                    elif "出身地" in th:
                        profile.birthplace = td

                return profile

            except Exception as e:
                logger.debug(f"AV Open 抓取失败 {url}: {e}")

        return None


# ==========================================
# AVWikiDB 刮削器
# ==========================================

class AVWikiDBSraper(BaseActorProfileScraper):
    """
    AVWikiDB 刮削器

    AVWikiDB 提供详细的演员资料
    搜索: https://avwikidb.com/actor/search/?q={name}
    详情: https://avwikidb.com{id}
    """

    name = "avwikidb"
    display_name = "AVWikiDB"
    base_url = "https://avwikidb.com"

    async def search(self, name: str) -> Optional[str]:
        """搜索 AVWikiDB"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        encoded_name = quote(name)
        search_url = f"{self.base_url}/actor/search/?q={encoded_name}"

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员链接
                links = html.xpath('//a[contains(@href, "/actor/") and not contains(@href, "/search")]')
                for link in links[:5]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name.lower() in text.lower() or text.lower() in name.lower():
                        return href if href.startswith("http") else f"{self.base_url}{href}"

                if links:
                    href = links[0].get("href", "")
                    return href if href.startswith("http") else f"{self.base_url}{href}"

            except Exception as e:
                logger.debug(f"AVWikiDB 搜索失败 {name}: {e}")

        return None

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """抓取 AVWikiDB 详情"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 姓名
                name_elem = html.xpath('//h1[@class="title"]//text()')
                if not name_elem:
                    name_elem = html.xpath('//div[@class="mt-2 mb-3 h1"]//text()')
                name = "".join(name_elem).strip() if name_elem else ""

                if not name:
                    return None

                profile = ActorProfile(name=name, source=self.name, source_url=url)

                # 头像
                avatar_elems = html.xpath('//img[@class="rounded-lg"]/@src')
                if not avatar_elems:
                    avatar_elems = html.xpath('//div[@class="mt-2 mb-3 img"]/@src')
                if avatar_elems:
                    avatar = avatar_elems[0]
                    if avatar.startswith("//"):
                        avatar = "https:" + avatar
                    profile.avatar_url = avatar

                # 资料 - 从文本中解析
                page_text = "".join(html.xpath('//body//text()'))

                # 身高 T160
                if match := re.search(r"身高[:：]?\s*T(\d+)", page_text):
                    profile.height = int(match.group(1))
                elif match := re.search(r"T(\d+)\s*cm", page_text):
                    profile.height = int(match.group(1))

                # 三围 B88-W59-H87 (C)
                if match := re.search(r"B(\d+)", page_text):
                    profile.bust = int(match.group(1))
                if match := re.search(r"W(\d+)", page_text):
                    profile.waist = int(match.group(1))
                if match := re.search(r"H(\d+)", page_text):
                    profile.hip = int(match.group(1))
                if match := re.search(r"B\d+\(?([A-Z])\)?", page_text, re.I):
                    profile.cup = match.group(1).upper()

                # 别名
                if match := re.search(r"別名[:：]\s*(.+?)(?=身高|$)", page_text):
                    profile.alias = match.group(1).strip()

                return profile

            except Exception as e:
                logger.debug(f"AVWikiDB 抓取失败 {url}: {e}")

        return None


# ==========================================
# TheMovieDB 刮削器
# ==========================================

class TheMovieDBScraper(BaseActorProfileScraper):
    """
    TheMovieDB 刮削器

    国际通用的演员数据库
    搜索: https://www.themoviedb.org/search/person?query={name}
    详情: https://www.themoviedb.org/person/{id}
    """

    name = "themoviedb"
    display_name = "TheMovieDB"
    base_url = "https://www.themoviedb.org"

    async def search(self, name: str) -> Optional[str]:
        """搜索 TheMovieDB"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        encoded_name = quote(name)
        search_url = f"{self.base_url}/search/person?query={encoded_name}"

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员链接
                links = html.xpath('//a[contains(@href, "/person/")]')
                for link in links[:5]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name.lower() in text.lower() or text.lower() in name.lower():
                        return f"https://www.themoviedb.org{href}"

                if links:
                    href = links[0].get("href", "")
                    return f"https://www.themoviedb.org{href}"

            except Exception as e:
                logger.debug(f"TheMovieDB 搜索失败 {name}: {e}")

        return None

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """抓取 TheMovieDB 详情"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 姓名
                name_elem = html.xpath('//h2[@class="title"]//text()')
                if not name_elem:
                    name_elem = html.xpath('//h1//text()')
                name = "".join(name_elem).strip() if name_elem else ""

                if not name:
                    return None

                profile = ActorProfile(name=name, source=self.name, source_url=url)

                # 头像
                avatar_elems = html.xpath('//img[@class="profile"]/@src')
                if avatar_elems:
                    avatar = avatar_elems[0]
                    if avatar.startswith("//"):
                        avatar = "https:" + avatar
                    profile.avatar_url = avatar

                # 生日
                birthday_elems = html.xpath('//p[contains(@class, "birthday")]/text()')
                if birthday_elems:
                    date_text = birthday_elems[0].strip()
                    if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", date_text):
                        profile.birth_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

                # 简介
                intro_elems = html.xpath('//div[@class="biography"]//p/text()')
                if intro_elems:
                    profile.intro = "".join(intro_elems).strip()

                return profile

            except Exception as e:
                logger.debug(f"TheMovieDB 抓取失败 {url}: {e}")

        return None


# ==========================================
# Gfriends 头像库
# ==========================================

class GfriendsScraper(BaseActorProfileScraper):
    """
    Gfriends 头像库

    GitHub 上的演员头像集合
    API: https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json
    """

    name = "gfriends"
    display_name = "Gfriends"
    base_url = "https://github.com/gfriends/gfriends"

    _index: Optional[dict] = None
    _index_loaded: bool = False

    async def _load_index(self) -> dict:
        """加载头像索引"""
        if self._index_loaded and self._index is not None:
            return self._index or {}

        self._index_loaded = True

        try:
            import json
            from urllib.request import Request, urlopen

            # 使用代理下载
            from app.config.manager import get_config
            from app.services.proxy_manager import get_effective_proxy_url
            proxy_url = get_effective_proxy_url()

            url = "https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json"

            if proxy_url:
                proxy_handler = __import__("urllib.request").request.ProxyHandler({
                    "http": proxy_url,
                    "https": proxy_url,
                })
                opener = __import__("urllib.request").build_opener(proxy_handler)
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                response = opener.open(req, timeout=30)
            else:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                response = urlopen(req, timeout=30)

            data = json.loads(response.read().decode())
            index = {}

            for folder, files in data.get("Content", {}).items():
                if isinstance(files, dict):
                    for fname in files:
                        name = fname.rsplit(".", 1)[0] if "." in fname else fname
                        index[name.lower()] = f"{folder}/{fname}"

            self._index = index
            logger.info(f"Gfriends 加载了 {len(index)} 个演员头像")
            return index

        except Exception as e:
            logger.debug(f"Gfriends 索引加载失败: {e}")
            self._index = {}
            return {}

    async def search(self, name: str) -> Optional[str]:
        """搜索 Gfriends 头像"""
        index = await self._load_index()

        name_lower = name.lower()
        if name_lower in index:
            return f"https://raw.githubusercontent.com/gfriends/gfriends/master/{index[name_lower]}"

        # 模糊匹配
        for actor_name, path in index.items():
            if name.lower() in actor_name or actor_name in name.lower():
                return f"https://raw.githubusercontent.com/gfriends/gfriends/master/{path}"

        return None

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """Gfriends 只返回头像URL"""
        profile = ActorProfile(name="", source=self.name, source_url=url)
        profile.avatar_url = url
        return profile

    async def get_profile(self, name: str, name_jp: Optional[str] = None) -> Optional[ActorProfile]:
        """获取头像URL"""
        url = await self.search(name_jp or name)
        if not url:
            url = await self.search(name)

        if url:
            profile = ActorProfile(name=name, name_jp=name_jp, source=self.name, source_url=url)
            profile.avatar_url = url
            return profile

        return None


# ==========================================
# 统一刮削器
# ==========================================

class ActorProfileScraper:
    """
    统一演员资料刮削器

    自动尝试多个来源获取演员资料
    """

    def __init__(self):
        # 延迟导入避免循环依赖
        from app.scraper.wikipedia_scraper import WikidataScraper, WikipediaScraper
        self._scrapers: list[BaseActorProfileScraper] = [
            DMMActressScraper(),
            JavWikiScraper(),
            AVOpenScraper(),
            AVWikiDBSraper(),
            WikidataScraper(),   # Wikidata SPARQL 查询（结构化权威数据）
            WikipediaScraper(),  # Wikipedia 兜底（轻量级摘要）
            GfriendsScraper(),   # 头像库放最后
        ]

    async def get_profile(
        self,
        name: str,
        name_jp: Optional[str] = None,
        preferred_sources: Optional[list[str]] = None,
    ) -> Optional[ActorProfile]:
        """
        获取演员资料（自动尝试多个来源）

        Args:
            name: 演员姓名
            name_jp: 日文名
            preferred_sources: 优先使用的来源列表

        Returns:
            演员资料，未找到返回None
        """
        # 按优先级尝试
        scrapers_to_use = []

        if preferred_sources:
            for src in preferred_sources:
                for scraper in self._scrapers:
                    if scraper.name == src:
                        scrapers_to_use.append(scraper)
                        break

        for scraper in self._scrapers:
            if scraper not in scrapers_to_use:
                scrapers_to_use.append(scraper)

        last_error = None
        for scraper in scrapers_to_use:
            try:
                profile = await scraper.get_profile(name, name_jp)
                if profile and profile.name:
                    logger.info(f"演员 {name} 资料获取成功: {scraper.name}")
                    # 后处理：根据出生日期补算星座（v3.4 新增）
                    if not profile.zodiac and profile.birth_date:
                        profile.zodiac = compute_zodiac(profile.birth_date)
                    # 尝试从简介中解析出道年份
                    if not profile.debut_year and profile.intro:
                        profile.debut_year = parse_debut_year(profile.intro)
                    return profile
            except Exception as e:
                last_error = e
                logger.debug(f"来源 {scraper.name} 获取失败: {e}")

        if last_error:
            logger.debug(f"所有来源获取失败: {last_error}")

        return None

    async def get_avatar(self, name: str, name_jp: Optional[str] = None) -> Optional[str]:
        """
        获取演员头像URL（优先使用头像库）

        Args:
            name: 演员姓名
            name_jp: 日文名

        Returns:
            头像URL
        """
        # 优先从 Gfriends 获取
        gfriends = GfriendsScraper()
        avatar_url = await gfriends.search(name_jp or name)
        if avatar_url:
            return avatar_url

        # 其他来源
        for scraper in self._scrapers:
            if scraper.name == "gfriends":
                continue
            try:
                profile = await scraper.get_profile(name, name_jp)
                if profile and profile.avatar_url:
                    return profile.avatar_url
            except Exception:
                continue

        return None


def get_actor_profile_scraper() -> ActorProfileScraper:
    """获取统一刮削器实例"""
    return ActorProfileScraper()
