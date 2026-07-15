"""
欧美模块刮削器 - ThePornDB API

参考来源：
- P0: mdcx-master/mdcx/crawlers/theporndb.py (MIT License, ~310行)
- P0: CommunityScrapers-master/scrapers/py_common/types.py (数据类型)

整合说明：
- API 调用逻辑: 参考 P0 theporndb.py 的 read_data() 解析逻辑
- 代理集成: 通过 MDCX 内置代理 (强制)
- 数据模型: 适配 MDCX ScrapeResult
- 认证: 支持 ThePornDB API Key (从配置读取)
"""

import re
from datetime import date
from typing import Optional

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ThePornDB API 端点
THEPORNDB_API_BASE = "https://api.theporndb.net"
THEPORNDB_SEARCH = f"{THEPORNDB_API_BASE}/scenes?q={{query}}"
THEPORNDB_DETAIL = f"{THEPORNDB_API_BASE}/scenes/{{slug}}"


def _parse_theporndb_response(data: dict) -> Optional[ScrapeResult]:
    """解析 ThePornDB API 响应（参考 mdcx theporndb.py read_data）"""
    if not data:
        return None

    title = data.get("title") or ""
    outline = data.get("description") or ""
    outline = outline.replace("<p>", "").replace("</p>", "")

    release = data.get("date") or ""
    release_date = None
    if release:
        try:
            release_date = date.fromisoformat(release[:10]).strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            pass

    # 封面（参考 mdcx: data["background"]["large"] -> fallback data["image"]）
    cover_url = ""
    try:
        cover_url = data["background"]["large"]
    except (KeyError, TypeError):
        cover_url = data.get("image") or ""

    # 海报
    poster_url = ""
    try:
        poster_url = data["posters"]["large"]
    except (KeyError, TypeError):
        poster_url = data.get("poster") or ""

    # 时长（参考 mdcx: duration / 60 转分钟）
    duration = None
    try:
        duration = int(data.get("duration", 0)) // 60
    except (ValueError, TypeError):
        pass

    # 站点和品牌网络（参考 mdcx: data["site"]["name"] / data["site"]["network"]["name"]）
    site = ""
    try:
        site = data["site"]["name"]
    except (KeyError, TypeError):
        pass

    studio = ""
    try:
        studio = data["site"]["network"]["name"]
    except (KeyError, TypeError):
        pass

    # 标签
    tags = []
    try:
        tags = [t["name"] for t in data.get("tags", [])]
    except (KeyError, TypeError):
        pass

    # 演员
    actors = []
    try:
        for performer in data.get("performers", []):
            name = performer.get("name") or ""
            if name:
                actor = ActorInfo(name=name)
                try:
                    actor.image = performer.get("image") or ""
                    actor.extra = {"id": performer.get("id"), "slug": performer.get("slug")}
                except Exception:
                    pass
                actors.append(actor)
    except (KeyError, TypeError):
        pass

    # 编码（参考 mdcx: slug 作为 code）
    slug = data.get("slug") or ""
    code = slug or title

    # trailer
    trailer = data.get("trailer") or ""

    result = ScrapeResult(
        code=code,
        title=title,
        source="theporndb",
        original_title=title,
        studio=studio,
        release_date=release_date,
        duration=duration if duration and duration > 0 else None,
        genres=[],  # ThePornDB 不区分类别
        tags=tags,
        actors=actors,
        cover_url=cover_url,
    )
    result.raw_data = data

    return result


@register_crawler
class ThePornDBCrawler(BaseCrawler):
    """ThePornDB 欧美刮削器

    参考: mdcx-master/mdcx/crawlers/theporndb.py (P0)
    使用 ThePornDB API 获取欧美影片元数据。
    所有请求通过 MDCX 内置代理。
    """

    name = "theporndb"
    display_name = "ThePornDB"
    base_url = THEPORNDB_API_BASE

    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    supported_prefixes = []
    description = "ThePornDB API 欧美影片元数据刮削"
    language = "en"
    requires_proxy = True  # 强制使用内置代理

    def _get_api_key(self) -> str:
        """从配置获取 API Key"""
        try:
            from app.config.manager import get_config
            config = get_config()
            return getattr(config.modules.western, "theporndb_api_key", "") or ""
        except Exception:
            return ""

    def _get_headers(self) -> dict:
        """构建请求头"""
        headers = {
            "Accept": "application/json",
            "User-Agent": "MDCX/3.0",
        }
        api_key = self._get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定影片

        Args:
            code: 影片 slug 或标题
        """
        from app.services.proxy_manager import get_proxy
        from app.utils.http_client import AsyncHttpClient

        proxy = get_effective_proxy_url()
        headers = self._get_headers()

        async with AsyncHttpClient(proxy=proxy) as client:
            try:
                # 先搜索
                search_url = THEPORNDB_SEARCH.format(query=code)
                resp = await client.get_json(search_url, headers=headers)

                scenes = resp.get("data", []) if resp else []
                if not scenes:
                    logger.info(f"ThePornDB 无搜索结果: {code}")
                    self.mark_error()
                    return None

                # 取第一个结果
                scene_data = scenes[0]
                result = _parse_theporndb_response(scene_data)
                if not result:
                    self.mark_error()
                    return None

                self.mark_success()
                return result

            except Exception as e:
                logger.error(f"ThePornDB 刮削失败 [{code}]: {e}")
                self.mark_error()
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索欧美影片"""
        from app.services.proxy_manager import get_effective_proxy_url
        from app.utils.http_client import AsyncHttpClient

        results = []
        proxy = get_effective_proxy_url()
        headers = self._get_headers()

        async with AsyncHttpClient(proxy=proxy) as client:
            try:
                search_url = THEPORNDB_SEARCH.format(query=keyword)
                resp = await client.get_json(search_url, headers=headers)

                scenes = resp.get("data", []) if resp else []
                for scene_data in scenes[:20]:  # 最多 20 条
                    result = _parse_theporndb_response(scene_data)
                    if result:
                        results.append(result)
            except Exception as e:
                logger.error(f"ThePornDB 搜索失败 [{keyword}]: {e}")

        return results
