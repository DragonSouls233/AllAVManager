"""
NaughtyAmerica 多子站点刮削器

参考来源:
- P0: CommunityScrapers-master/scrapers/NaughtyAmerica/NaughtyAmerica.py (Stash scraper)
- P0: NA 统一 API (api.naughtyapi.com) + 子站列表 (8 个域名)

整合说明:
- 业务逻辑: 100% 复用 P0 API 端点 + scene_from_id + scene_from_webpage 双模式
- HTTP 客户端: 切换为 MDCX AsyncHttpClient + 内置代理
- 数据模型: 适配 MDCX ScrapeResult
- 重试策略: 复用 P0 405 错误指数退避（8 次重试）

支持的 NaughtyAmerica 子站:
  naughtyamerica.com, naughtyamericavr.com, tonightsgirlfriend.com,
  myfriendshotmom.com, mysistershotfriend.com, thundercock.com,
  tonightsts.com, dorm room, dressing room, gym, office, spa 等

API 端点:
  - GET https://api.naughtyapi.com/tools/scenes/scenes?id={scene_id}
  - 包含 trailer/promo_video_data → 反推封面 URL
"""

import re
import time
from typing import Any, Optional

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.services.proxy_manager import get_effective_proxy_url
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) "
    "Gecko/20100101 Firefox/141.0"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.naughtyamerica.com/",
}

# 性别映射
GENDERS_MAP = {
    "female_trans": "transgender_female",
    "shemale": "transgender_female",
}

# 工作室名称映射（参考 P0 NA）
SITE_NAME_TO_STUDIO_NAME_MAP = {
    "Dorm Room": "The Dorm Room",
    "Dressing Room": "The Dressing Room",
    "Gym": "The Gym",
    "Office": "The Office",
    "Spa": "The Spa",
}

# NA 子站域名（用于场景 URL 识别）
NA_SUBDOMAINS = [
    "naughtyamerica.com",
    "naughtyamericavr.com",
    "tonightsgirlfriend.com",
    "myfriendshotmom.com",
    "mysistershotfriend.com",
    "thundercock.com",
    "tonightsts.com",
    "naughtyamerica.org",
    "dormroom.com",
    "dressingroom.com",
    "thegym.com",
    "theoffice.com",
    "thespa.com",
]

# 分辨率映射
RESOLUTION_MAP = {
    "www.naughtyamerica.com": "1279x852",
    "www.naughtyamericavr.com": "1000x563",
    "www.tonightsgirlfriend.com": "1499x944",
}
RESOLUTION_DEFAULT = "1279x852"
RESOLUTION_ALT_DOMAINS = [
    "www.myfriendshotmom.com",
    "www.mysistershotfriend.com",
    "www.thundercock.com",
    "www.tonightsts.com",
]
RESOLUTION_ALT = "1279x719"


def mapped_gender(gender: str) -> str:
    return GENDERS_MAP.get(gender, gender)


def mapped_studio(site_name: str) -> str:
    return SITE_NAME_TO_STUDIO_NAME_MAP.get(site_name, site_name)


def clean_text(details: str) -> str:
    """清理文本（参考 P0 NA clean_text）"""
    if not details:
        return ""
    details = details.replace("\\", "")
    details = re.sub(r"<\s*\/?br\s*\/?\s*>", "\n", details)
    from bs4 import BeautifulSoup
    return BeautifulSoup(details, "html.parser").get_text("", strip=False)


def construct_image_url(trailer_url: str, scene_url: str) -> Optional[str]:
    """从 trailer/promo 视频 URL 推导封面图（参考 P0 NA 复杂的正则）"""
    if not trailer_url:
        return None
    m = re.match(
        r".+(?:promo|\.com)/(?:nonsecure/)?([^/]+)/(?:trailers(?:/vr)?/)?([^/_]+).*",
        trailer_url,
    )
    if not m:
        return None
    prefix = m.group(1)
    name = m.group(2)
    if name.startswith(prefix):
        name = name[len(prefix):]
    name = re.sub(r"(teaser|trailer)$", "", name)

    # 分辨率
    resolution = RESOLUTION_DEFAULT
    if "www.naughtyamericavr.com" in scene_url:
        resolution = "1000x563"
    elif "www.tonightsgirlfriend.com" in scene_url:
        resolution = "1499x944"
    elif any(d in scene_url for d in RESOLUTION_ALT_DOMAINS):
        resolution = RESOLUTION_ALT

    return f"https://images4.naughtycdn.com/cms/nacmscontent/v1/scenes/{prefix}/{name}/scene/horizontal/{resolution}c.jpg"


@register_crawler
class NaughtyAmericaCrawler(BaseCrawler):
    """NaughtyAmerica 多子站点统一刮削器

    通过统一的 NA API（api.naughtyapi.com）按 scene_id 刮削，覆盖所有 NA 旗下子站。
    API 失败时自动降级为直接抓取 webpage（参考 P0 NA scene_from_webpage）。
    """

    name = "naughtyamerica"
    display_name = "NaughtyAmerica (NA Group)"
    base_url = "https://www.naughtyamerica.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    supported_prefixes = []
    description = "NaughtyAmerica 多子站点统一 API 刮削器"
    language = "en"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        self._headers = HEADERS.copy()

    @staticmethod
    def _is_na_url(url: str) -> bool:
        """检测是否 NA 子站 URL"""
        url_lower = url.lower()
        return any(d in url_lower for d in NA_SUBDOMAINS)

    @staticmethod
    def _id_from_url(url: str) -> Optional[str]:
        """从 URL 提取 scene_id（参考 P0 NA id_from_url）"""
        m = re.search(r"/.*?(\d+)(?:\?|#|$)", url)
        if m:
            return m.group(1)
        return None

    async def _api_scene_from_id(self, scene_id: str) -> Optional[dict]:
        """API 抓取（参考 P0 NA api_scene_from_id）"""
        api_url = f"https://api.naughtyapi.com/tools/scenes/scenes?id={scene_id}"
        proxy = get_effective_proxy_url()
        max_retries = 8
        backoff = 0.5

        for attempt in range(1, max_retries + 1):
            async with AsyncHttpClient(proxy=proxy, timeout=15) as client:
                try:
                    resp = await client.get(api_url, headers=self._headers)
                    if resp.status_code == 405:
                        logger.debug(f"NA 405 错误 (attempt {attempt}/{max_retries})")
                        time.sleep(backoff)
                        backoff *= 1.2
                        continue
                    if resp.status_code == 200:
                        data = await resp.json()
                        items = data.get("data", [])
                        if not items:
                            logger.warning(f"NA scene {scene_id} 未找到")
                            return None
                        if len(items) == 1:
                            return items[0]
                        return items[0]
                    logger.warning(f"NA API 状态码: {resp.status_code}")
                    return None
                except Exception as e:
                    logger.error(f"NA API 失败: {e}")
                    return None
        return None

    async def _scene_from_webpage(self, url: str) -> Optional[dict]:
        """直接抓取 webpage（参考 P0 NA scene_from_webpage）"""
        from bs4 import BeautifulSoup

        scene: dict = {}
        scene_id = self._id_from_url(url)
        if scene_id:
            scene["code"] = str(scene_id)

        proxy = get_effective_proxy_url()
        async with AsyncHttpClient(proxy=proxy, timeout=15) as client:
            try:
                resp = await client.get(url, headers=self._headers)
            except Exception as e:
                logger.error(f"NA webpage 请求失败: {e}")
                return None

        if resp.status_code != 200:
            logger.warning(f"NA webpage 状态码: {resp.status_code}")
            return None

        html_text = resp.text if hasattr(resp, "text") else str(resp)
        soup = BeautifulSoup(html_text, "html.parser")

        # 标题
        title_elem = soup.select_one("div.scenepage-info > h1")
        if title_elem:
            scene["title"] = title_elem.get_text(strip=True)

        # 日期 (MM-DD-YY 格式)
        date_elem = soup.select_one("span.scenepage-date")
        if date_elem:
            date_text = date_elem.get_text(strip=True)
            m = re.match(r"(\d{2})-(\d{2})-(\d{2})", date_text)
            if m:
                month, day, year = m.group(1), m.group(2), int(m.group(3))
                year = year + 2000 if year < 70 else year + 1900
                scene["date"] = f"{year:04d}-{month}-{day}"

        # 封面
        image_elem = soup.select_one("img.playcard")
        if image_elem:
            img_src = image_elem.get("src", "")
            if img_src.startswith("//"):
                img_src = "https:" + img_src
            scene["image"] = img_src

        # 简介
        description_elem = soup.select_one("div.scenepage-description")
        if description_elem:
            scene["details"] = description_elem.get_text(strip=True)

        # 标签
        tags = []
        for tag_elem in soup.select("div.scenepage-categories > a"):
            tags.append({"name": tag_elem.get_text(strip=True)})
        scene["tags"] = tags

        # URL
        url_elem = soup.select_one('link[rel="canonical"]')
        if url_elem:
            scene["url"] = url_elem.get("href")

        # 演员
        performers: list[dict] = []
        for p_elem in soup.select("div.scenepage-info > p > a"):
            names = re.sub(r"Added:.*$", "", p_elem.get_text(strip=True)).strip()
            for name in names.split(","):
                name = name.strip()
                if name:
                    performers.append({"name": name})
        scene["performers"] = performers

        return scene

    def _to_scrape_result(self, scene_data: dict) -> Optional[ScrapeResult]:
        """转换 API 数据 → ScrapeResult（参考 P0 NA to_scraped_scene）"""
        if not scene_data:
            return None

        result_kwargs = {
            "code": str(scene_data.get("code", scene_data.get("id", ""))),
            "title": scene_data.get("title", "").strip() if scene_data.get("title") else "",
            "source": "naughtyamerica",
            "original_title": scene_data.get("title", "").strip() if scene_data.get("title") else "",
        }

        # 日期
        if pub := scene_data.get("published_date") or scene_data.get("date"):
            try:
                result_kwargs["release_date"] = str(pub)[:10]
            except Exception:
                pass

        # URL
        if url := scene_data.get("scene_url") or scene_data.get("url"):
            result_kwargs["source_url"] = url

        # 简介
        if syn := scene_data.get("synopsis") or scene_data.get("details"):
            result_kwargs["plot"] = clean_text(syn)

        # 标签
        tags = scene_data.get("tags") or []
        if scene_data.get("pov") and ("Virtual Reality" in tags or "VR Porn" in tags):
            tags.append(f"{scene_data['pov']} POV")
        if scene_data.get("degrees") and ("Virtual Reality" in tags or "VR Porn" in tags):
            tags.append(f"{scene_data['degrees']}°")
        result_kwargs["tags"] = [t for t in tags if t] if isinstance(tags, list) else []

        # 演员
        performers_data = scene_data.get("performers") or []
        actors = []
        if isinstance(performers_data, dict):
            for gender, names in performers_data.items():
                for n in names:
                    if n:
                        actors.append(ActorInfo(name=n, japanese_name=None))
        elif isinstance(performers_data, list):
            for p in performers_data:
                if isinstance(p, dict) and p.get("name"):
                    actors.append(ActorInfo(name=p["name"], japanese_name=None))
        result_kwargs["actors"] = actors

        # 工作室
        site_name = scene_data.get("site_name")
        if site_name:
            result_kwargs["studio"] = mapped_studio(site_name)

        # 封面（API 模式：trailer → 推导；webpage 模式：直接取）
        cover = scene_data.get("image")
        if not cover:
            trailers = scene_data.get("trailers", {}) or {}
            promo = scene_data.get("promo_video_data", {}) or {}
            combined = {**(trailers or {}), **(promo or {})}
            if combined:
                first_url = next(iter(combined.values()), None)
                if first_url:
                    scene_url = scene_data.get("scene_url", "")
                    cover = construct_image_url(first_url, scene_url)
        result_kwargs["cover_url"] = cover

        return ScrapeResult(**{k: v for k, v in result_kwargs.items() if v is not None})

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """刮削 scene

        Args:
            code: scene_id (数字) 或 NA 子站 URL
        """
        if code.startswith("http"):
            url = code
            scene_id = self._id_from_url(url)
            if not scene_id:
                logger.error(f"NA URL 解析失败: {url}")
                self.mark_error()
                return None
            # 优先 API，失败回退 webpage
            api_data = await self._api_scene_from_id(scene_id)
            scene_data = None
            if api_data:
                scene_data = self._to_scrape_result(api_data)
            if not scene_data:
                web_data = await self._scene_from_webpage(url)
                scene_data = self._to_scrape_result(web_data) if web_data else None
        else:
            # 纯 scene_id
            api_data = await self._api_scene_from_id(code)
            scene_data = self._to_scrape_result(api_data) if api_data else None

        if scene_data:
            self.mark_success()
        else:
            self.mark_error()
        return scene_data

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """NA 暂无公开搜索 API（仅靠 scene_id 抓取）"""
        return []


# 便捷函数
async def scrape_na_scene(scene_id_or_url: str) -> Optional[ScrapeResult]:
    """便捷函数：按 scene_id 或 URL 刮削"""
    crawler = NaughtyAmericaCrawler()
    return await crawler.scrape(scene_id_or_url)
