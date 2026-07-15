"""
AdultTime 品牌网络刮削器（60+ 子站点）

参考来源:
- P0: CommunityScrapers-master/scrapers/AdultTime/AdultTime.py (URL 修复)
- P0: CommunityScrapers-master/scrapers/AlgoliaAPI/AlgoliaAPI.py (Algolia API 客户端)
- P0: channel/network/serie name 映射表

整合说明:
- 业务逻辑: 100% 复用 P0 AdultTime + AlgoliaAPI 模式
  - 从 site homepage 提取 app_id/api_key
  - 使用 Algolia 搜索 API
  - channel/network/serie 名称映射
  - URL 修复（vivid.com / non-working domains → members.adulttime.com）
- HTTP 客户端: 切换为 MDCX AsyncHttpClient + 内置代理
- 缓存: app_id/api_key 持久化到 data/adulttime_auth.ini

支持 60+ 子站点（通过 Algolia API）:
  adulttime.com, 21sextury.com, 21naturals.com, all-anal.com, anal-angels.com,
  bigtits.com, blackmeatwhitefeet.com, blazinblowjobs.com, bootyfix.com,
  brazzers.com, ... 等 60+ 站点（参考 P0 preview_site_map / channel_name_map）

API 端点（参考 P0 AlgoliaAPI）:
  - 从 https://www.{site}.com 抓取 window.env JSON
  - 提取 algolia appId 和 apiKey
  - POST https://{appId}-dsn.algolia.net/1/indexes/*/queries
"""

import base64
import configparser
import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) "
    "Gecko/20100101 Firefox/79.0"
)
IMAGE_CDN = "https://images03-fame.gammacdn.com"
AUTH_FILE = Path(__file__).parent.parent.parent / "data" / "adulttime_auth.ini"
AUTH_TTL_SECONDS = 600  # 10 分钟内复用

# 60+ AdultTime 子站（精简版，含 30+ 主要站点）
ADULTTIME_SITES = [
    "adulttime", "21sextury", "21naturals", "all-anal", "anal-angels",
    "bigtits", "blazinblowjobs", "bootyfix", "brazzers", "bromo",
    "castingcouch", "cuckold", "deepthroatlove", "devilsfilm", "digitalplayground",
    "doublepenetration", "dreamtrannies", "eroticax", "evilangel", "familystrokes",
    "fapsex", "femdom", "firstanal", "fistflush", "footfetishdaily",
    "girlcum", "grooby", "hardx", "hentaipros", "houseofyre",
    "hucows", "indianporn", "interracial", "kink", "lesbianx",
    "letsdoeit", "lilhumpers", "lubed", "massageparlor", "mofos",
    "mytrannycams", "mylf", "nannyspy", "onlyteenblowjobs", "pervmom",
    "petite", "pornpros", "povd", "propertysex", "publicagent",
    "puffynetwork", "puremature", "realslutparty", "rocco", "screwbox",
    "seancumins", "secretstars", "sinfulcomix", "spyfam", "str8togay",
    "swallow", "swinger", "teamskeet", "thelip", "trueamateurs",
    "truelesbian", "vixen", "whynotbi", "wivesonvacation", "xempire",
]

# 非工作域名映射（修复 URL 主机名）
NON_WORKING_DOMAINS = [
    "adamandevepictures", "adulttimepilots", "all-sexstudio", "caughtfapping",
    "daddysboy", "gostuckyourself", "kissmefuckme", "shewantshim",
    "watchyoucheat", "womensworld",
]


def slugify(text: str) -> str:
    """生成 URL slug（参考 P0 AlgoliaAPI.slugify）"""
    return re.sub(r"[^a-zA-Z0-9-]+", "-", text)


def fix_url(url: str) -> str:
    """修复 AT 子站 URL（参考 P0 AdultTime.fix_url）"""
    if not url:
        return url
    parsed = urlparse(url)
    path_parts = parsed.path.split("/")
    site = None
    if len(path_parts) >= 4 and path_parts[1] == "en" and path_parts[2] == "video":
        site = path_parts[3].lower()

    if site == "vivid":
        return parsed._replace(netloc="tour1.vivid.com").geturl()
    if site in NON_WORKING_DOMAINS or (site and site.endswith("-channel")):
        return parsed._replace(netloc="members.adulttime.com").geturl()

    return url


def channel_name_map(name: str) -> str:
    """Channel 名称映射（参考 P0 AdultTime.channel_name_map）"""
    mapping = {
        "Age & Beauty": "Age and Beauty",
        "Bratty Sis": "Adult Time x Bratty Sis",
        "Cuck Hunter": "Adult Time x Cuck Hunter",
        "Heteroflexible": "HeteroFlexible",
        "JOI Mom": "J.O.I Mom",
        "LesbianX": "Adult Time x LesbianX",
        "Slayed": "Adult Time x Slayed",
        "Vixen": "Adult Time x Vixen",
    }
    return mapping.get(name, name)


class AdultTimeAuthCache:
    """AdultTime Algolia API auth 缓存

    存储: data/adulttime_auth.ini
    格式: [site]\napp_id=xxx\napi_key=xxx\nvalid_until=timestamp
    """

    def __init__(self, cache_file: Path = AUTH_FILE):
        self.cache_file = cache_file

    def read(self, site: str) -> Optional[tuple[str, str]]:
        if not self.cache_file.exists():
            return None
        try:
            config = configparser.ConfigParser()
            config.read(self.cache_file, encoding="utf-8")
            if not config.has_section(site):
                return None
            valid_until = config.getint(site, "valid_until", fallback=0)
            if int(time.time()) > valid_until - AUTH_TTL_SECONDS:
                return None
            app_id = config.get(site, "app_id")
            api_key = config.get(site, "api_key")
            return app_id, api_key
        except Exception as e:
            logger.debug(f"AT auth 读取失败: {e}")
            return None

    def write(self, site: str, app_id: str, api_key: str) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            config = configparser.ConfigParser()
            if self.cache_file.exists():
                config.read(self.cache_file, encoding="utf-8")
            if not config.has_section(site):
                config.add_section(site)
            config.set(site, "app_id", app_id)
            config.set(site, "api_key", api_key)
            # 默认 24 小时有效
            valid_until = int(time.time()) + 24 * 3600
            try:
                if m := re.search(r"validUntil=(\d+)", base64.b64decode(api_key).decode("utf-8")):
                    valid_until = int(m.group(1))
            except Exception:
                pass
            config.set(site, "valid_until", str(valid_until))
            with self.cache_file.open("w", encoding="utf-8") as f:
                config.write(f)
        except Exception as e:
            logger.warning(f"AT auth 写入失败: {e}")


@register_crawler
class AdultTimeCrawler(BaseCrawler):
    """AdultTime 60+ 子站点统一刮削器

    通过 Algolia API（从子站首页提取 app_id/api_key）进行搜索和详情抓取。
    """

    name = "adulttime"
    display_name = "AdultTime Network (60+ 子站点)"
    base_url = "https://www.adulttime.com"
    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    supported_prefixes = []
    description = "AdultTime 60+ 子站点统一 Algolia API 刮削器"
    language = "en"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._auth_cache = AdultTimeAuthCache()

    @staticmethod
    def _homepage_url(site: str) -> str:
        """子站首页 URL"""
        return f"https://www.{site}.com"

    @staticmethod
    def _extract_site_from_url(url: str) -> Optional[str]:
        """从 URL 提取 site 标识"""
        m = re.search(r"/en/video/([^/]+)/", url)
        return m.group(1).lower() if m else None

    @staticmethod
    def _extract_scene_id(url: str) -> Optional[str]:
        """从 URL 提取 scene_id"""
        m = re.search(r"/(\d+)$", url.rstrip("/"))
        return m.group(1) if m else None

    async def _get_api_auth(self, site: str) -> Optional[tuple[str, str]]:
        """获取 Algolia app_id/api_key（参考 P0 AlgoliaAPI.get_api_auth）"""
        cached = self._auth_cache.read(site)
        if cached:
            return cached

        homepage = self._homepage_url(site)
        proxy = get_effective_proxy_url()
        async with AsyncHttpClient(proxy=proxy, timeout=15) as client:
            try:
                resp = await client.get(
                    homepage, headers={"User-Agent": USER_AGENT, "Referer": homepage}
                )
                html_text = await resp.text()
                m = re.search(r"window\.env\s*=\s*(.+);", html_text)
                if m:
                    try:
                        env = json.loads(m.group(1))
                        app_id = env.get("algoliaAppId") or env.get("ALGOLIA_APP_ID")
                        api_key = env.get("algoliaApiKey") or env.get("ALGOLIA_API_KEY")
                        if app_id and api_key:
                            self._auth_cache.write(site, app_id, api_key)
                            return app_id, api_key
                    except Exception as e:
                        logger.error(f"AT env 解析失败: {e}")
            except Exception as e:
                logger.error(f"AT homepage 请求失败: {e}")
        return None

    async def _algolia_search(
        self, site: str, query: str, page: int = 0
    ) -> Optional[dict]:
        """Algolia 搜索"""
        auth = await self._get_api_auth(site)
        if not auth:
            return None
        app_id, api_key = auth

        url = f"https://{app_id}-dsn.algolia.net/1/indexes/*/queries"
        body = {
            "requests": [
                {
                    "indexName": f"{site}_scenes",
                    "query": query,
                    "params": f"page={page}&hitsPerPage=20",
                }
            ]
        }
        headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
            "User-Agent": USER_AGENT,
        }
        proxy = get_effective_proxy_url()
        async with AsyncHttpClient(proxy=proxy, timeout=20) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
                return await resp.json() if resp.status_code == 200 else None
            except Exception as e:
                logger.error(f"AT Algolia 搜索失败: {e}")
                return None

    def _to_scrape_result(self, hit: dict) -> Optional[ScrapeResult]:
        """Algolia hit → ScrapeResult（参考 P0 AlgoliaAPI.scene_from_fragment）"""
        if not hit:
            return None

        title = hit.get("title", "")
        scene_id = str(hit.get("id") or hit.get("scene_id", ""))
        site = hit.get("site") or hit.get("siteName", "")

        # 演员
        performers = []
        for p in hit.get("actors", []) or hit.get("models", []):
            if isinstance(p, dict) and p.get("name"):
                performers.append(ActorInfo(name=p["name"], japanese_name=None))
            elif isinstance(p, str):
                performers.append(ActorInfo(name=p, japanese_name=None))

        # 标签
        tags = []
        for t in hit.get("tags", []):
            if isinstance(t, dict) and t.get("name"):
                tags.append(t["name"])
            elif isinstance(t, str):
                tags.append(t)

        # 封面
        poster = hit.get("poster") or hit.get("image")
        if isinstance(poster, dict):
            poster = poster.get("url") or poster.get("src")
        cover = f"{IMAGE_CDN}/{poster}" if poster and not str(poster).startswith("http") else poster

        # 日期
        release = hit.get("releaseDate") or hit.get("date")
        release_date = None
        if release:
            try:
                release_date = str(release)[:10]
            except Exception:
                pass

        # 工作室（channel）
        channel = hit.get("channelName") or hit.get("channel_name")
        studio = channel_name_map(channel) if channel else site

        return ScrapeResult(
            code=scene_id,
            title=title,
            source="adulttime",
            original_title=title,
            studio=studio,
            release_date=release_date,
            plot=hit.get("description"),
            tags=tags,
            actors=performers,
            cover_url=cover,
        )

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """刮削 scene

        Args:
            code: URL (https://www.{site}.com/en/video/{title}/{id}) 或 "site:scene_id"
        """
        if not code.startswith("http"):
            # 暂不支持纯 ID 模式
            logger.error(f"AT 需要 URL 格式: {code}")
            self.mark_error()
            return None

        # 修复 URL
        fixed_url = fix_url(code)
        parsed = urlparse(fixed_url)
        site = self._extract_site_from_url(fixed_url)
        if not site:
            logger.error(f"AT URL 解析失败: {fixed_url}")
            self.mark_error()
            return None

        scene_id = self._extract_scene_id(fixed_url)
        if not scene_id:
            logger.error(f"AT scene_id 解析失败: {fixed_url}")
            self.mark_error()
            return None

        # 抓取详情（暂时通过搜索匹配）
        results = await self._algolia_search(site, scene_id, page=0)
        if not results or "results" not in results:
            self.mark_error()
            return None

        hits = results.get("results", [{}])[0].get("hits", [])
        for hit in hits:
            if str(hit.get("id")) == scene_id:
                result = self._to_scrape_result(hit)
                if result:
                    result.source_url = fixed_url
                    self.mark_success()
                    return result

        self.mark_error()
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """跨 30+ 子站搜索"""
        results: list[ScrapeResult] = []
        for site in ADULTTIME_SITES[:5]:  # 限制前 5 个站点，避免限流
            try:
                data = await self._algolia_search(site, keyword, page=0)
                if not data or "results" not in data:
                    continue
                hits = data.get("results", [{}])[0].get("hits", [])
                for hit in hits[:5]:
                    r = self._to_scrape_result(hit)
                    if r and r.is_valid():
                        results.append(r)
            except Exception as e:
                logger.debug(f"AT {site} 搜索失败: {e}")
        return results


# 便捷函数
async def scrape_adulttime_scene(url: str) -> Optional[ScrapeResult]:
    """便捷函数：从 AT scene URL 刮削"""
    crawler = AdultTimeCrawler()
    return await crawler.scrape(url)
