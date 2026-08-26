"""
模块演员个人资料刮削器

为各模块提供演员个人资料刮削（生日、身高、三围等）：
- uncensored: HEYZO actress 页面
- fc2: JavDB 演员页面 (fallback)
- western: ThePornDB API
- pornhub: JavDB 演员页面 (fallback)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

from lxml import etree

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@dataclass
class ModuleActorProfile:
    """模块演员个人资料"""
    name: str
    alias: Optional[str] = None
    avatar_url: Optional[str] = None
    birth_date: Optional[str] = None
    age: Optional[int] = None
    height: Optional[int] = None
    bust: Optional[int] = None
    waist: Optional[int] = None
    hip: Optional[int] = None
    cup: Optional[str] = None
    birthplace: Optional[str] = None
    country: Optional[str] = None
    ethnicity: Optional[str] = None
    measurements: Optional[str] = None
    weight: Optional[str] = None
    gender: Optional[str] = None
    twitter: Optional[str] = None
    instagram: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None


class ModuleActorProfileScraper:
    """模块演员个人资料刮削器"""

    def __init__(self, module_name: str):
        self.module_name = module_name
        self._proxy = None

        from app.config.manager import get_config
        config = get_config()
        try:
            proxy_config = config.proxy
            if proxy_config and getattr(proxy_config, "enabled", False):
                self._proxy = getattr(proxy_config, "http", None) or getattr(proxy_config, "https", None)
        except Exception:
            pass

    async def get_profile(self, actor_name: str) -> Optional[ModuleActorProfile]:
        """获取演员个人资料（按模块类型选择来源）"""
        if self.module_name == "uncensored":
            return await self._scrape_heyzo(actor_name)
        elif self.module_name == "western":
            return await self._scrape_western(actor_name)
        elif self.module_name in ("fc2", "pornhub"):
            return await self._scrape_javdb_actor(actor_name)
        return None

    # ==========================================
    # HEYZO 演员资料刮削 (uncensored)
    # ==========================================

    async def _scrape_heyzo(self, name: str) -> Optional[ModuleActorProfile]:
        """从 HEYZO 刮削演员资料

        HEYZO 演员页 URL 格式:
        https://www.heyzo.com/actress/{name}/
        """
        encoded = quote(name)
        profile_url = f"https://www.heyzo.com/actress/{encoded}/"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(profile_url, headers=headers)
                if not html_text or "404" in html_text:
                    # 尝试搜索
                    return await self._search_heyzo(name)
            except Exception as e:
                logger.debug(f"HEYZO 直接访问失败 {profile_url}: {e}")
                return await self._search_heyzo(name)

        return self._parse_heyzo_profile(html_text, name, profile_url)

    async def _search_heyzo(self, name: str) -> Optional[ModuleActorProfile]:
        """通过 HEYZO 搜索查找演员"""
        encoded = quote(name)
        search_url = f"https://www.heyzo.com/search/{encoded}/"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None
            except Exception as e:
                logger.debug(f"HEYZO 搜索失败 {search_url}: {e}")
                return None

        html = etree.fromstring(html_text, etree.HTMLParser())

        # 查找演员链接
        links = html.xpath('//a[contains(@href, "/actress/")]')
        for link in links[:3]:
            href = link.get("href", "")
            if not href or "/actress/" not in href:
                continue
            text = "".join(link.xpath(".//text()")).strip()
            if name.lower() in text.lower() or text.lower() in name.lower():
                actress_url = href if href.startswith("http") else f"https://www.heyzo.com{href}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "ja-JP,ja;q=0.9",
                }
                async with AsyncHttpClient(timeout=20) as client:
                    try:
                        html_text = await client.get_text(actress_url, headers=headers)
                        if html_text and "404" not in html_text:
                            return self._parse_heyzo_profile(html_text, name, actress_url)
                    except Exception:
                        continue

        # 第一个搜索结果
        if links:
            href = links[0].get("href", "")
            actress_url = href if href.startswith("http") else f"https://www.heyzo.com{href}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "ja-JP,ja;q=0.9",
            }
            async with AsyncHttpClient(timeout=20) as client:
                try:
                    html_text = await client.get_text(actress_url, headers=headers)
                    if html_text and "404" not in html_text:
                        return self._parse_heyzo_profile(html_text, name, actress_url)
                except Exception:
                    pass

        return None

    def _parse_heyzo_profile(self, html_text: str, name: str, url: str) -> Optional[ModuleActorProfile]:
        """解析 HEYZO 演员页面"""
        try:
            html = etree.fromstring(html_text, etree.HTMLParser())
        except Exception:
            return None

        # 获取页面中实际的演员名
        name_elem = html.xpath('//h1/text()')
        actual_name = name_elem[0].strip() if name_elem else name

        profile = ModuleActorProfile(
            name=actual_name,
            source="heyzo",
            source_url=url,
        )

        # 头像
        avatar_elem = html.xpath('//img[contains(@class, "actress")]/@src')
        if not avatar_elem:
            avatar_elem = html.xpath('//div[@class="actressPhoto"]//img/@src')
        if avatar_elem:
            avatar = avatar_elem[0]
            if avatar.startswith("//"):
                avatar = "https:" + avatar
            elif avatar.startswith("/"):
                avatar = "https://www.heyzo.com" + avatar
            profile.avatar_url = avatar

        # 从页面文本中提取资料
        page_text = "".join(html.xpath('//body//text()'))

        # 别名
        if match := re.search(r"別名[:：]\s*([^\n]+)", page_text):
            profile.alias = match.group(1).strip()

        # 出生日期
        if match := re.search(r"(?:誕生日|生年月日)[:：]\s*(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})", page_text):
            profile.birth_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

        # 身高
        if match := re.search(r"身長[:：]\s*T?(\d+)\s*cm", page_text):
            profile.height = int(match.group(1))
        elif match := re.search(r"身長[:：]\s*(\d+)", page_text):
            profile.height = int(match.group(1))

        # 三围
        if match := re.search(r"(?:スリーサイズ|サイズ)[:：]\s*B(\d+)\s*/\s*W(\d+)\s*/\s*H(\d+)", page_text):
            profile.bust = int(match.group(1))
            profile.waist = int(match.group(2))
            profile.hip = int(match.group(3))
            profile.measurements = f"B{match.group(1)}-W{match.group(2)}-H{match.group(3)}"

        # 罩杯
        if match := re.search(r"カップ[:：]\s*([A-Z])", page_text, re.I):
            profile.cup = match.group(1).upper()
        elif match := re.search(r"B\d+\(?\s*([A-Z])\s*\)?", page_text, re.I):
            profile.cup = match.group(1).upper()

        # 出身地
        if match := re.search(r"出身地[:：]\s*([^\n]+)", page_text):
            profile.birthplace = match.group(1).strip()

        # 血液型 (不存储，用来辅助确认页面)
        # 趣味/特技
        # デビュー (出道)

        return profile if profile.name else None

    # ==========================================
    # Western 演员资料刮削
    # ==========================================

    async def _scrape_western(self, name: str) -> Optional[ModuleActorProfile]:
        """刮削欧美演员资料（通过 ThePornDB API）"""
        # 尝试 theporndb 搜索
        profile = await self._scrape_theporndb_actor(name)
        if profile:
            return profile

        # 回退到 JavDB
        return await self._scrape_javdb_actor(name)

    async def _scrape_theporndb_actor(self, name: str) -> Optional[ModuleActorProfile]:
        """通过 ThePornDB API 搜索欧美演员"""
        encoded = quote(name)
        search_url = f"https://theporndb.net/performers?q={encoded}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员链接
                links = html.xpath('//a[contains(@href, "/performers/")]')
                for link in links[:3]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name.lower() in text.lower() or text.lower() in name.lower():
                        performer_url = href if href.startswith("http") else f"https://theporndb.net{href}"
                        return await self._parse_theporndb_actor(performer_url)

                if links:
                    href = links[0].get("href", "")
                    performer_url = href if href.startswith("http") else f"https://theporndb.net{href}"
                    return await self._parse_theporndb_actor(performer_url)

            except Exception as e:
                logger.debug(f"ThePornDB 搜索失败 {name}: {e}")

        return None

    async def _parse_theporndb_actor(self, url: str) -> Optional[ModuleActorProfile]:
        """解析 ThePornDB 演员详情页"""
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

                name_elem = html.xpath('//h1/text()')
                name = name_elem[0].strip() if name_elem else ""

                if not name:
                    return None

                profile = ModuleActorProfile(
                    name=name,
                    source="theporndb",
                    source_url=url,
                )

                # 头像
                avatar_elem = html.xpath('//img[@class="performer-image"]/@src')
                if not avatar_elem:
                    avatar_elem = html.xpath('//div[@class="performer-photo"]//img/@src')
                if avatar_elem:
                    avatar = avatar_elem[0]
                    if avatar.startswith("//"):
                        avatar = "https:" + avatar
                    profile.avatar_url = avatar

                # 从页面文本提取资料
                page_text = "".join(html.xpath('//body//text()'))

                # 生日
                if match := re.search(r"(?:Birthday|Born)[:：]\s*(\d{4}-\d{2}-\d{2})", page_text):
                    profile.birth_date = match.group(1)

                # 性别
                if match := re.search(r"Gender[:：]\s*(\w+)", page_text, re.I):
                    profile.gender = match.group(1).strip().lower()

                # 身高
                if match := re.search(r"(?:Height|身長)[:：]\s*(\d+)\s*(?:cm|in)", page_text, re.I):
                    profile.height = int(match.group(1))

                # 体重
                if match := re.search(r"(?:Weight|体重)[:：]\s*(\d+)\s*(?:kg|lbs)", page_text, re.I):
                    profile.weight = match.group(1)

                # 三围
                if match := re.search(r"Measurements[:：]\s*([\d\-A-Za-z]+)", page_text, re.I):
                    profile.measurements = match.group(1).strip()

                # 国家
                if match := re.search(r"(?:Country|国籍)[:：]\s*([^\n]+)", page_text, re.I):
                    profile.country = match.group(1).strip()

                # 种族
                if match := re.search(r"(?:Ethnicity|种族)[:：]\s*([^\n]+)", page_text, re.I):
                    profile.ethnicity = match.group(1).strip()

                # Twitter
                if match := re.search(r"Twitter[:：]\s*([^\s]+)", page_text, re.I):
                    profile.twitter = match.group(1).strip()

                # Instagram
                if match := re.search(r"Instagram[:：]\s*([^\s]+)", page_text, re.I):
                    profile.instagram = match.group(1).strip()

                return profile

            except Exception as e:
                logger.debug(f"ThePornDB 解析失败 {url}: {e}")

        return None

    # ==========================================
    # JavDB 演员资料刮削 (通用 fallback)
    # ==========================================

    async def _scrape_javdb_actor(self, name: str) -> Optional[ModuleActorProfile]:
        """从 JavDB 刮削演员资料"""
        encoded = quote(name)
        search_url = f"https://javdb.com/search?q={encoded}&f=actor"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with AsyncHttpClient(timeout=20) as client:
            try:
                html_text = await client.get_text(search_url, headers=headers)
                if not html_text:
                    return None

                html = etree.fromstring(html_text, etree.HTMLParser())

                # 查找演员链接
                links = html.xpath('//a[contains(@href, "/actors/")]')
                for link in links[:3]:
                    href = link.get("href", "")
                    text = "".join(link.xpath(".//text()")).strip()
                    if name.lower() in text.lower() or text.lower() in name.lower():
                        actor_url = href if href.startswith("http") else f"https://javdb.com{href}"
                        return await self._parse_javdb_actor(actor_url)

                if links:
                    href = links[0].get("href", "")
                    actor_url = href if href.startswith("http") else f"https://javdb.com{href}"
                    return await self._parse_javdb_actor(actor_url)

            except Exception as e:
                logger.debug(f"JavDB 演员搜索失败 {name}: {e}")

        return None

    async def _parse_javdb_actor(self, url: str) -> Optional[ModuleActorProfile]:
        """解析 JavDB 演员详情页"""
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

                name_elem = html.xpath('//h1/text()')
                name = name_elem[0].strip() if name_elem else ""

                if not name:
                    name_elem = html.xpath('//h2[@class="title"]/text()')
                    name = name_elem[0].strip() if name_elem else ""

                if not name:
                    return None

                profile = ModuleActorProfile(
                    name=name,
                    source="javdb",
                    source_url=url,
                )

                # 头像
                avatar_elem = html.xpath('//img[contains(@class, "actor")]/@src')
                if not avatar_elem:
                    avatar_elem = html.xpath('//div[@class="avatar"]//img/@src')
                if avatar_elem:
                    avatar_url = avatar_elem[0]
                    if avatar_url.startswith("//"):
                        avatar_url = "https:" + avatar_url
                    profile.avatar_url = avatar_url

                # 从页面文本提取资料
                page_text = "".join(html.xpath('//body//text()'))

                # 生日
                if match := re.search(r"(?:Birthday|誕生日)[:：\s]*(\d{4}-\d{2}-\d{2})", page_text):
                    profile.birth_date = match.group(1)

                return profile

            except Exception as e:
                logger.debug(f"JavDB 演员解析失败 {url}: {e}")

        return None


def get_module_actor_profile_scraper(module_name: str) -> ModuleActorProfileScraper:
    """获取模块演员资料刮削器实例"""
    return ModuleActorProfileScraper(module_name=module_name)
