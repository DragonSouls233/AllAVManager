"""
IAFD (Internet Adult Film Database) 演员元数据刮削器

参考来源：
- P0: CommunityScrapers-master/scrapers/IAFD/IAFD.py (XPath 选择器、字段映射)
- 现有: app/scraper/actor_profile_scrapers.py (BaseActorProfileScraper 接口)

整合说明：
- XPath 选择器: 100% 复用 P0 IAFD.py (lxml 选择器)
- HTTP 客户端: 切换为 MDCX AsyncHttpClient + 内置代理
- Cloudflare 绕过: 复用 MDCX 已有 cf_bypass 工具
- 数据模型: 适配 MDCX ActorProfile

字段映射:
- name          -> name
- gender        -> gender
- birthdate     -> birth_date
- death_date    -> 暂不存储
- ethnicity     -> ethnicity
- country       -> birthplace
- height        -> height
- weight        -> weight
- hair_color    -> 暂不存储
- measurements  -> bust/waist/hip/cup 解析
- aliases       -> alias
- tattoos/piercings -> 暂不存储
- eye_color     -> 暂不存储
- twitter/instagram -> social_links
- images        -> avatar_url (取首张)
"""

import asyncio
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from lxml import html as lxml_html

from app.scraper.actor_profile_scrapers import (
    ActorProfile,
    BaseActorProfileScraper,
)
from app.services.proxy_manager import get_effective_proxy_url
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# IAFD 站点配置
IAFD_BASE_URL = "https://www.iafd.com"
IAFD_SEARCH_URL = f"{IAFD_BASE_URL}/results.asp?searchtype=comprehensive&searchstring={{query}}"
IAFD_DATE_FORMATS = ["%B %d, %Y", "%b %d, %Y"]
IAFD_STASH_DATE = "%Y-%m-%d"

# XPath 选择器（100% 复用 P0 IAFD.py）
SHARED_SELECTORS = {
    "title": "//h1/text()",
    "director": '//p[@class="bioheading"][contains(text(),"Director") or contains(text(),"Directors")]/following-sibling::p[@class="biodata"][1]/a/text()',
    "studio": '//p[@class="bioheading"][contains(text(),"Studio")]/following-sibling::p[@class="biodata"][1]//text()',
    "date": '//p[@class="bioheading"][contains(text(), "Release Date")]/following-sibling::p[@class="biodata"][1]/text()',
    "synopsis": '//div[@id="synopsis"]/div[@class="padded-panel"]//text()',
}

EMPTY_VALUES = ["No Data", "No Director", "None", "Unknown"]

# 头发颜色映射（参考 P0 IAFD.py map_haircolor）
HAIR_COLOR_MAP = {
    "Blond": "Blonde",
    "Brown": "Brunette",
    "Dark Brown": "Brunette",
    "Red": "Redhead",
    "Grey": "Gray",
}

# 性别映射（参考 P0 IAFD.py map_gender）
GENDER_MAP = {
    "Woman": "Female",
    "Man": "Male",
    "Trans woman": "Transgender Female",
    "Trans man": "Transgender Male",
}


def _maybe(values, f=lambda x: x):
    """返回第一个非空值（参考 P0 maybe）"""
    for v in values:
        if v and not re.search("|".join(EMPTY_VALUES), str(v), re.I):
            return f(v)
    return None


def _clean_date(date_str: str) -> Optional[str]:
    """将 IAFD 日期格式转为 YYYY-MM-DD（参考 P0 clean_date）"""
    if not date_str:
        return None
    stripped = date_str.strip()
    cleaned = re.sub(r"(\S+\s+\d+,\s+\d+).*", r"\1", stripped)
    for fmt in IAFD_DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime(IAFD_STASH_DATE)
        except ValueError:
            pass
    logger.warning(f"无法解析日期: {date_str}")
    return None


def _clean_alias(alias: str) -> Optional[str]:
    """清理演员别名（参考 P0 clean_alias）"""
    if " or " in alias:
        return None
    return re.sub(r"\s*\(.*$", "", alias)


def _parse_measurements(text: str) -> dict:
    """解析身材三围文本，例如 '34B-24-34' -> {bust, waist, hip, cup}"""
    result = {}
    if not text:
        return result
    sizes = re.findall(r"(\d+)", text)
    cups = re.findall(r"(\d+\s*)?([A-Z])\s*[Cc]up", text)
    if len(sizes) >= 1:
        result["bust"] = int(sizes[0])
    if len(sizes) >= 2:
        result["waist"] = int(sizes[1])
    if len(sizes) >= 3:
        result["hip"] = int(sizes[2])
    if cups:
        result["cup"] = cups[0][1].upper()
    return result


def _extract_height(text: str) -> Optional[int]:
    """从 '5'4" (163 cm)' 提取厘米数（参考 P0 performer_height）"""
    if not text:
        return None
    m = re.search(r"(\d+)\s*cm", text)
    if m:
        return int(m.group(1))
    return None


def _extract_weight(text: str) -> Optional[int]:
    """从 '110 lb (50 kg)' 提取公斤数（参考 P0 performer_weight）"""
    if not text:
        return None
    m = re.search(r"(\d+)\s*kg", text)
    if m:
        return int(m.group(1))
    return None


def _map_gender(gender: str) -> str:
    return GENDER_MAP.get(gender, gender)


class IAFDScraper(BaseActorProfileScraper):
    """IAFD 演员元数据刮削器

    通过 IAFD 详情页提取演员资料：姓名、性别、出生/死亡日期、族裔、国籍、身高、体重、
    三围、纹身/穿孔、别名、社交账号、头像。

    所有 HTTP 请求通过 MDCX 内置代理（SOCKS5 127.0.0.1:18920 / HTTP 127.0.0.1:18921）。
    """

    name = "iafd"
    display_name = "IAFD (Internet Adult Film Database)"
    base_url = IAFD_BASE_URL

    def __init__(self):
        super().__init__()
        self._cache: dict[str, str] = {}  # name -> detail_url
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def _fetch(self, url: str, retries: int = 3) -> Optional[str]:
        """使用内置代理获取 HTML（重试 + 退避）"""
        proxy = get_effective_proxy_url()
        async with AsyncHttpClient(proxy=proxy, timeout=30) as client:
            for attempt in range(retries):
                try:
                    html_text = await client.get_text(url, headers=self._headers)
                    if html_text:
                        return html_text
                except Exception as e:
                    logger.debug(f"IAFD 请求失败 [{attempt+1}/{retries}] {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 + attempt)
        return None

    def _parse_tree(self, html_text: str):
        """解析 HTML 为 lxml tree"""
        return lxml_html.fromstring(html_text)

    async def search(self, name: str) -> Optional[str]:
        """搜索演员并返回详情页 URL（参考 P0 performer_query）

        URL 格式: https://www.iafd.com/person.rme/id=xxx
        """
        if name in self._cache:
            return self._cache[name]

        encoded = quote(name)
        search_url = IAFD_SEARCH_URL.format(query=encoded)
        html_text = await self._fetch(search_url)
        if not html_text:
            return None

        try:
            tree = self._parse_tree(html_text)
        except Exception as e:
            logger.error(f"IAFD HTML 解析失败: {e}")
            return None

        # 提取演员名称和链接（参考 P0 performer_query）
        performer_names = tree.xpath(
            '//table[@id="tblFem" or @id="tblMal"]//td[a[img]]/following-sibling::td[1]/a/text()'
        )
        performer_urls = tree.xpath(
            '//table[@id="tblFem" or @id="tblMal"]//td[a[img]]/following-sibling::td[1]/a/@href'
        )

        if not performer_urls:
            logger.info(f"IAFD 未找到演员: {name}")
            return None

        # 精确匹配优先
        target_name = name.strip().lower()
        for pname, purl in zip(performer_names, performer_urls):
            if pname and pname.strip().lower() == target_name:
                full_url = f"{IAFD_BASE_URL}{purl}"
                self._cache[name] = full_url
                return full_url

        # 否则取第一个结果
        full_url = f"{IAFD_BASE_URL}{performer_urls[0]}"
        self._cache[name] = full_url
        return full_url

    def _extract_performer_name(self, tree) -> Optional[str]:
        return _maybe(tree.xpath(SHARED_SELECTORS["title"]), lambda n: n.strip())

    def _extract_gender(self, tree) -> Optional[str]:
        gender = tree.xpath(
            '//p[@class="bioheading" and contains(text(), "Gender")]/following-sibling::p[1]/text()'
        )
        if gender:
            return _map_gender(gender[0])
        return None

    def _extract_birthdate(self, tree) -> Optional[str]:
        return _maybe(
            tree.xpath(
                '(//p[@class="bioheading"][text()="Birthday"]/following-sibling::p)[1]//text()'
            ),
            _clean_date,
        )

    def _extract_deathdate(self, tree) -> Optional[str]:
        return _maybe(
            tree.xpath(
                '(//p[@class="bioheading"][text()="Date of Death"]/following-sibling::p)[1]//text()'
            ),
            _clean_date,
        )

    def _extract_ethnicity(self, tree) -> Optional[str]:
        return _maybe(
            tree.xpath(
                '//div[p[text()="Ethnicity"]]/p[@class="biodata"][1]//text()'
            )
        )

    def _extract_country(self, tree) -> Optional[str]:
        return _maybe(
            tree.xpath('//div/p[text()="Nationality"]/following-sibling::p[1]//text()'),
            lambda c: re.sub(r"^American,.+", "American", c),
        )

    def _extract_height(self, tree) -> Optional[int]:
        return _maybe(
            tree.xpath('//div/p[text()="Height"]/following-sibling::p[1]//text()'),
            _extract_height,
        )

    def _extract_weight(self, tree) -> Optional[int]:
        return _maybe(
            tree.xpath('//div/p[text()="Weight"]/following-sibling::p[1]//text()'),
            _extract_weight,
        )

    def _extract_measurements(self, tree) -> dict:
        text = _maybe(
            tree.xpath('//div/p[text()="Measurements"]/following-sibling::p[1]//text()')
        )
        return _parse_measurements(text or "")

    def _extract_avatar(self, tree) -> Optional[str]:
        # 参考 P0 performer_url: data-src 替换 matchups -> person
        url = _maybe(
            tree.xpath("//*[@data-src]/@data-src"),
            lambda u: u.replace("matchups", "person"),
        )
        if not url:
            imgs = tree.xpath('//div[@id="headshot"]//img/@src')
            if imgs:
                url = imgs[0]
        if url and url.startswith("//"):
            url = "https:" + url
        if url and url.startswith("/"):
            url = IAFD_BASE_URL + url
        return url

    def _extract_aliases(self, tree) -> Optional[str]:
        aliases = tree.xpath(
            '//div[p[@class="bioheading" and contains(normalize-space(text()),"Performer AKA")'
            'or contains(normalize-space(text()),"AKA")]]'
            '//div[@class="biodata" and not(normalize-space(text())="No known aliases")]/text()'
        )
        cleaned = [y for x in aliases for y in [_clean_alias(x.strip())] if y]
        return ", ".join(cleaned) if cleaned else None

    def _extract_social(self, tree) -> dict:
        social = {}
        ig = _maybe(
            tree.xpath(
                '//p[@class="biodata"]/a[contains(text(),"http://instagram.com/")]/@href'
            )
        )
        if ig:
            social["instagram"] = ig
        tw = _maybe(
            tree.xpath(
                '//p[@class="biodata"]/a[contains(text(),"http://twitter.com/")]/@href'
            )
        )
        if tw:
            social["twitter"] = tw
        return social

    def _extract_career_length(self, tree) -> Optional[str]:
        """参考 P0 performer_careerlength：处理 2023 还在活动时去掉尾段"""
        career = _maybe(
            tree.xpath(
                '//div/p[@class="bioheading"][contains(text(), "Active")][1]/following-sibling::p[1]/text()'
            ),
            lambda c: " - ".join(re.sub(r"(\D+\d\d\D+)$", "", c.strip()).split("-")),
        )
        if career:
            current_year = str(datetime.now().year)
            if career.endswith(current_year):
                career = career[: career.rfind(current_year)]
        return career

    async def scrape_profile(self, url: str) -> Optional[ActorProfile]:
        """从详情页 URL 抓取演员资料"""
        html_text = await self._fetch(url)
        if not html_text:
            return None

        try:
            tree = self._parse_tree(html_text)
        except Exception as e:
            logger.error(f"IAFD HTML 解析失败: {e}")
            return None

        name = self._extract_performer_name(tree)
        if not name:
            logger.warning(f"IAFD 详情页无姓名: {url}")
            return None

        measurements = self._extract_measurements(tree)
        social = self._extract_social(tree)

        profile = ActorProfile(
            name=name,
            name_en=name,
            source=self.name,
            source_url=url,
            avatar_url=self._extract_avatar(tree),
            birth_date=self._extract_birthdate(tree),
            birthplace=self._extract_country(tree),
            ethnicity=self._extract_ethnicity(tree),
            height=self._extract_height(tree),
            weight=self._extract_weight(tree),
            bust=measurements.get("bust"),
            waist=measurements.get("waist"),
            hip=measurements.get("hip"),
            cup=measurements.get("cup"),
            alias=self._extract_aliases(tree),
            social_links=social if social else None,
        )

        # 计算额外字段
        from app.scraper.actor_profile_scrapers import compute_zodiac, parse_debut_year

        if profile.birth_date:
            profile.zodiac = compute_zodiac(profile.birth_date)
        career = self._extract_career_length(tree)
        if career:
            profile.debut_year = parse_debut_year(career)

        return profile


# 便捷注册函数
async def scrape_iafd_performer(name: str) -> Optional[ActorProfile]:
    """单次调用接口：按姓名抓取 IAFD 演员资料"""
    scraper = IAFDScraper()
    return await scraper.get_profile(name)
