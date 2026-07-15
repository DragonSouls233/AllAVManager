"""
Vixen Network 品牌站群通用刮削器

参考来源:
- P0: CommunityScrapers-master/scrapers/vixenNetwork/vixenNetwork.py (Stash scraper)
- P0: 多品牌 GraphQL 适配器模式 (vixen/blacked/blackedraw/deeper/tushy/tushyraw/milfy/wifey/slayed)

整合说明:
- 业务逻辑: 100% 复用 P0 GraphQL query + parse_scene + parse_search
- HTTP 客户端: 切换为 MDCX AsyncHttpClient + 内置代理
- 数据模型: 适配 MDCX ScrapeResult
- 9 个品牌统一通过 Site 类适配

支持的 Vixen 品牌:
  Vixen, Blacked, Blacked Raw, Deeper, Tushy, Tushy Raw,
  Milfy, Wifey, Slayed

API 端点（统一 GraphQL）:
  - 详情: POST {site}.com/graphql  query: getVideo($videoSlug, $site)
  - 搜索: POST {site}.com/graphql  query: getSearchResults($query, $site, $first)
"""

import re
from datetime import datetime, timedelta
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
MAX_SCENES = 6
MAX_403_REATTEMPTS = 3
USE_STUDIO_DEFAULT_TAGS = True

# GraphQL query 模板（100% 复用 P0 vixenNetwork.py）
GET_VIDEO_QUERY = """
query getVideo($videoSlug: String, $site: Site) {
    findOneVideo(input: {slug: $videoSlug, site: $site}) {
        title
        description
        releaseDate
        models {
            name
        }
        videoId
        directors {
            name
        }
        images {
            poster {
                src
                width
            }
        }
        categories {
            name
        }
        runLength
    }
}
"""

GET_SEARCH_QUERY = """
query getSearchResults($query: String!, $site: Site!, $first: Int) {
    searchVideos(input: { query: $query, site: $site, first: $first }) {
        edges {
            node {
                description
                title
                slug
                releaseDate
                modelsSlugged: models {
                    name
                }
                videoId
                images {
                    listing {
                        src
                        width
                    }
                }
            }
        }
    }
}
"""

# 9 个 Vixen Network 品牌配置
SITES = {
    "vixen": {"name": "Vixen", "deftags": []},
    "blacked": {"name": "Blacked", "deftags": ["Black Male"]},
    "blackedraw": {"name": "Blacked Raw", "deftags": ["Black Male"]},
    "deeper": {"name": "Deeper", "deftags": []},
    "tushy": {"name": "Tushy", "deftags": ["Anal Sex"]},
    "tushyraw": {"name": "Tushy Raw", "deftags": ["Anal Sex"]},
    "milfy": {"name": "Milfy", "deftags": ["MILF"]},
    "wifey": {"name": "Wifey", "deftags": []},
    "slayed": {"name": "Slayed", "deftags": ["Lesbian Sex"]},
}


def parse_duration_to_seconds(duration_str: str) -> int:
    """解析 HH:MM:SS 格式（参考 P0 parse_duration_to_seconds）"""
    try:
        t = datetime.strptime(duration_str, "%H:%M:%S")
        delta = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        return delta.seconds
    except Exception:
        return 0


def upgrade_image(image_url: str, candidate_url: str) -> str:
    """尝试升级图片分辨率（参考 P0 try_upgrade_image）"""
    high_res = re.sub(r"\d+x\d+", "5760x3240", image_url)
    return high_res if high_res != image_url else image_url


@register_crawler
class VixenNetworkCrawler(BaseCrawler):
    """Vixen Network 品牌站群通用刮削器

    通过统一的 GraphQL 端点刮削 9 个品牌。
    """

    name = "vixen_network"
    display_name = "Vixen Network (Vixen/Blacked/Tushy/etc.)"
    base_url = "https://www.vixen.com"
    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    supported_prefixes = ["vixen", "blacked", "tushy", "deeper", "milfy", "wifey", "slayed"]
    description = "Vixen Network 9 品牌统一 GraphQL 刮削器"
    language = "en"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "DNT": "1",
        }

    @staticmethod
    def _site_id(site_key: str) -> str:
        return site_key.upper()

    @staticmethod
    def _detect_site(url: str) -> Optional[str]:
        """从 URL 检测站点（参考 P0 Site.isValidURL）"""
        try:
            u = url.lower().rstrip("/")
            parsed = urlparse(u)
            if not parsed.hostname:
                return None
            host_parts = parsed.hostname.split(".")
            if len(host_parts) < 2:
                return None
            site_id = host_parts[-2]
            if site_id not in SITES:
                return None
            path_parts = parsed.path.split("/")
            if len(path_parts) < 3:
                return None
            return site_id if path_parts[-2] == "videos" else None
        except Exception:
            return None

    @staticmethod
    def _get_slug(url: str) -> str:
        """从 URL 提取 slug（参考 P0 Site.getSlug）"""
        return url.lower().rstrip("/").split("/")[-1]

    def _api_url(self, site_key: str) -> str:
        return f"https://www.{site_key}.com/graphql"

    async def _graphql(self, query: dict, site_key: str, referer: str) -> Optional[dict]:
        """执行 GraphQL 查询（参考 P0 Site.callGraphQL）"""
        url = self._api_url(site_key)
        headers = {**self._headers, "Referer": referer}
        proxy = get_effective_proxy_url()

        for attempt in range(MAX_403_REATTEMPTS):
            async with AsyncHttpClient(proxy=proxy, timeout=30) as client:
                try:
                    resp = await client.post(url, json=query, headers=headers)
                    if resp.status_code == 200:
                        return resp.json()
                    if resp.status_code == 403:
                        logger.debug(f"Vixen 403 错误，重试 {attempt + 1}/{MAX_403_REATTEMPTS}")
                        continue
                    logger.warning(f"Vixen GraphQL 错误: {resp.status_code}")
                    return None
                except Exception as e:
                    logger.error(f"Vixen GraphQL 失败: {e}")
                    return None
        return None

    def _parse_scene_data(self, data: dict, site_key: str) -> dict:
        """解析 scene 详情（参考 P0 Site.parse_scene）"""
        result: dict = {}
        if not data:
            return result

        site = SITES.get(site_key, {})
        result["title"] = data.get("title", "")
        result["details"] = data.get("description", "")
        result["studio"] = {"name": site.get("name", site_key.title())}
        result["code"] = str(data.get("videoId", ""))

        directors = data.get("directors") or []
        if directors:
            result["director"] = ", ".join(d.get("name", "") for d in directors)

        date = data.get("releaseDate")
        if date:
            try:
                result["date"] = date.split("T")[0]
            except Exception:
                pass

        performers = []
        for m in data.get("models") or []:
            performers.append({"name": m.get("name", "")})
        result["performers"] = performers

        tags = []
        for t in data.get("categories") or []:
            tags.append({"name": t.get("name", "")})
        if USE_STUDIO_DEFAULT_TAGS:
            for t in site.get("deftags", []):
                tags.append({"name": t})
        result["tags"] = tags

        # 封面（取最大 width）
        images = data.get("images") or {}
        if images.get("poster"):
            max_width = 0
            for img in images["poster"]:
                w = img.get("width", 0)
                if w > max_width:
                    result["image"] = img.get("src", "")
                    max_width = w
            if "image" in result:
                result["image"] = upgrade_image(result["image"], result["image"])

        # 时长
        if data.get("runLength"):
            result["runLength"] = parse_duration_to_seconds(data["runLength"])

        return result

    def _to_scrape_result(self, scene_data: dict, source_url: str) -> Optional[ScrapeResult]:
        if not scene_data:
            return None

        performers = scene_data.get("performers", [])
        actors = [
            ActorInfo(name=p.get("name", ""), japanese_name=None)
            for p in performers
            if p.get("name")
        ]
        tags = [t.get("name", "") for t in scene_data.get("tags", []) if t.get("name")]
        studio = scene_data.get("studio", {}).get("name") if scene_data.get("studio") else None
        duration = scene_data.get("runLength")

        result = ScrapeResult(
            code=str(scene_data.get("code", "")),
            title=scene_data.get("title", ""),
            source="vixen_network",
            original_title=scene_data.get("title", ""),
            studio=studio,
            director=scene_data.get("director"),
            release_date=scene_data.get("date"),
            plot=scene_data.get("details"),
            tags=tags,
            actors=actors,
            cover_url=scene_data.get("image"),
            duration=duration,
        )
        result.raw_data = scene_data
        result.source_url = source_url
        return result

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """刮削 scene

        Args:
            code: scene URL (https://www.vixen.com/videos/slug) 或 slug
        """
        # 解析 URL
        if code.startswith("http"):
            site_key = self._detect_site(code)
            if not site_key:
                logger.error(f"Vixen 不支持的 URL: {code}")
                self.mark_error()
                return None
            slug = self._get_slug(code)
            source_url = code
        else:
            # 纯 slug: 默认 vixen
            site_key = "vixen"
            slug = code
            source_url = f"https://www.vixen.com/videos/{code}"

        site_id = self._site_id(site_key)
        query = {
            "query": GET_VIDEO_QUERY,
            "operationName": "getVideo",
            "variables": {"site": site_id, "videoSlug": slug},
        }
        response = await self._graphql(query, site_key, referer=source_url)
        if not response or "data" not in response:
            self.mark_error()
            return None

        data = (response.get("data") or {}).get("findOneVideo")
        if not data:
            self.mark_error()
            return None

        scene_data = self._parse_scene_data(data, site_key)
        result = self._to_scrape_result(scene_data, source_url)
        if result:
            self.mark_success()
        else:
            self.mark_error()
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 Vixen Network 9 品牌"""
        results: list[ScrapeResult] = []
        for site_key, site in SITES.items():
            site_id = self._site_id(site_key)
            query = {
                "query": GET_SEARCH_QUERY,
                "operationName": "getSearchResults",
                "variables": {
                    "site": site_id,
                    "query": keyword,
                    "first": MAX_SCENES,
                },
            }
            home_url = f"https://www.{site_key}.com"
            response = await self._graphql(query, site_key, referer=home_url)
            if not response or "data" not in response:
                continue
            edges = (response.get("data") or {}).get("searchVideos", {}).get("edges", [])
            for edge in edges:
                node = edge.get("node")
                if not node or not node.get("slug"):
                    continue
                scene_data = {
                    "title": node.get("title", ""),
                    "details": node.get("description", ""),
                    "code": str(node.get("videoId", "")),
                    "releaseDate": node.get("releaseDate"),
                    "models": [{"name": m.get("name", "")} for m in node.get("modelsSlugged", []) or []],
                    "categories": [],
                }
                # 封面
                images = node.get("images") or {}
                if images.get("listing"):
                    max_w = 0
                    for img in images["listing"]:
                        if img.get("width", 0) > max_w:
                            scene_data["image"] = img.get("src", "")
                            max_w = img.get("width", 0)
                url = f"https://www.{site_key}.com/videos/{node['slug']}"
                result = self._to_scrape_result(scene_data, url)
                if result and result.is_valid():
                    results.append(result)
        return results


# 便捷函数
async def scrape_vixen_scene(url: str) -> Optional[ScrapeResult]:
    """便捷函数：从 Vixen Network scene URL 刮削"""
    crawler = VixenNetworkCrawler()
    return await crawler.scrape(url)
