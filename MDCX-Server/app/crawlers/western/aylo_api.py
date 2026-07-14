"""
AyloAPI 品牌站群通用刮削器

参考来源：
- P0: CommunityScrapers-master/scrapers/AyloAPI/scrape.py (Stash scraper)
- P0: CommunityScrapers-master/scrapers/AyloAPI/domains.py (token 缓存)
- P0: CommunityScrapers-master/scrapers/AyloAPI/slugger.py (slug 工具)

整合说明：
- 业务逻辑: 100% 复用 P0 AyloAPI (token/headers/字段映射)
- HTTP 客户端: 切换为 MDCX AsyncHttpClient + 内置代理 (强制)
- 数据模型: 适配 MDCX ScrapeResult
- 缓存: 复用 P0 的 aylo_tokens.json 持久化方案
- 限流: 复用 P0 的 429 错误处理

支持的 Aylo 品牌（按 site-api.project1service.com API 覆盖范围）:
  Brazzers, BangBros, Reality Kings, Mofos, Digital Playground, Twistys, Babes,
  Vixen, Blacked, Tushy, Deeper, TushyRaw, Naughty America, MYLF, TeamSkeet,
  EvilAngel, etc.

API 端点:
  - 详情: https://site-api.project1service.com/v2/releases/{id}
  - 演员: https://site-api.project1service.com/v2/actors/{id}
  - 搜索: https://site-api.project1service.com/v2/releases?q={query}
"""

import asyncio
import json
import re
from datetime import datetime
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
from app.services.proxy_manager import get_proxy
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Aylo 统一 API 基础地址（参考 P0 AyloAPI scrape.py）
AYLO_API_BASE = "https://site-api.project1service.com/v2"

# 用户代理（参考 P0 AyloAPI 默认值）
AYLO_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) "
    "Gecko/20100101 Firefox/79.0"
)

# token 缓存文件
TOKENS_FILE = Path(__file__).parent.parent.parent / "data" / "aylo_tokens.json"


# ------------------------------------------------------------
# 字段映射表（100% 复用 P0 AyloAPI tags_map）
# ------------------------------------------------------------

# 中性标签 ID -> 性别相关标签名（参考 P0 AyloAPI tags_map）
TAGS_MAP = {
    90: "Athletic Woman",
    107: "White Woman",
    112: "Black Woman",
    113: "European Woman",
    121: "Latina Woman",
    125: "Black Hair (Female)",
    126: "Blond Hair (Female)",
    127: "Brown Hair (Female)",
    128: "Red Hair (Female)",
    215: "Rimming Him",
    274: "Rimming Her",
    374: "Black Man",
    376: "European Man",
    377: "Latino Man",
    378: "White Man",
    379: "Black Hair (Male)",
    380: "Blond Hair (Male)",
    381: "Brown Hair (Male)",
    383: "Red Hair (Male)",
    385: "Shaved Head",
    386: "Short Hair (Male)",
}

# Aylo 已知品牌域名（参考 P0 AyloAPI 默认 + 0.1.0 文档）
AYLO_BRANDS = [
    "brazzers", "bangbros", "realitykings", "mofos", "digitalplayground",
    "twistys", "babes", "vixen", "blacked", "tushy", "deeper", "tushyraw",
    "naughtyamerica", "mylf", "teamskeet", "evilangel", "prettydirty",
    "propertysex", "porndoepay", "sexmex", "brazzersexxtra", "brazzers-originals",
]


# ------------------------------------------------------------
# Token 缓存管理（参考 P0 domains.py）
# ------------------------------------------------------------

class AyloTokenStore:
    """Aylo instance_token 持久化

    每个域名缓存当天的 token，过期重新获取。
    """

    def __init__(self, cache_file: Path = TOKENS_FILE):
        self.cache_file = cache_file
        self._tokens: dict = self._load()

    def _load(self) -> dict:
        if not self.cache_file.exists():
            return {}
        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(self._tokens, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存 Aylo tokens 失败: {e}")

    def get(self, domain: str) -> Optional[str]:
        today = datetime.now().strftime("%Y-%m-%d")
        entry = self._tokens.get(domain)
        if entry and entry.get("date") == today and entry.get("token"):
            return entry["token"]
        return None

    def set(self, domain: str, token: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._tokens[domain] = {"token": token, "date": today}
        self.save()


# ------------------------------------------------------------
# 数据转换（参考 P0 AyloAPI scrape.py）
# ------------------------------------------------------------

def _dig(obj: dict, *keys) -> Optional[object]:
    """安全地深度取值"""
    cur = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(k, (list, tuple)):
            cur = cur.get(k[0]) if isinstance(cur, dict) else None
            for kk in k[1:]:
                if cur is None:
                    return None
                if isinstance(cur, dict):
                    cur = cur.get(kk)
                elif isinstance(cur, list):
                    try:
                        cur = cur[kk]
                    except (IndexError, TypeError):
                        return None
                else:
                    return None
        elif isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def _slugify(text: str) -> str:
    """生成 URL slug（参考 P0 AyloAPI slugger）"""
    if not text:
        return ""
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower())
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s


def _construct_scene_url(api_result: dict) -> Optional[str]:
    """构造 scene 公开 URL（参考 P0 _construct_url）"""
    brand = api_result.get("brand")
    if brand in ("leviproductions",):
        return None
    type_ = api_result.get("type")
    id_ = api_result.get("id")
    slug = _slugify(api_result.get("title") or "")
    if not (brand and type_ and id_):
        return None
    return f"https://www.{brand}.com/{type_}/{id_}/{slug}"


def _to_tag(api_object: dict) -> str:
    """标签转换（参考 P0 to_tag）"""
    tag_id = api_object.get("id")
    name = (api_object.get("name") or "").strip()
    if tag_id in TAGS_MAP:
        return TAGS_MAP[tag_id]
    return name


def _to_tags(api_object: dict) -> list[str]:
    """标签列表转换（参考 P0 to_tags）"""
    tags = api_object.get("tags", []) or []
    result = []
    for x in tags:
        if "name" in x or x.get("id") in TAGS_MAP:
            result.append(_to_tag(x))
    return result


def _to_actor(performer_from_api: dict, site: Optional[str] = None) -> ActorInfo:
    """演员数据转换（参考 P0 to_scraped_performer）"""
    name = performer_from_api.get("name") or ""
    actor = ActorInfo(name=name, japanese_name=None)

    # 别名
    aliases = performer_from_api.get("aliases", []) or []
    other_aliases = ", ".join(
        a for a in aliases if isinstance(a, str) and a.lower() != name.lower()
    )
    if other_aliases:
        actor.extra = actor.extra or {}
        actor.extra["aliases"] = other_aliases

    # 简介
    if bio := performer_from_api.get("bio"):
        actor.extra = actor.extra or {}
        actor.extra["bio"] = bio

    # 身高（inch -> cm；过滤异常值）
    if height := performer_from_api.get("height"):
        try:
            h = int(height)
            if h > 5:  # 排除异常值
                actor.extra = actor.extra or {}
                actor.extra["height_cm"] = round(h * 2.54)
        except (ValueError, TypeError):
            pass

    # 体重（lb -> kg）
    if weight := performer_from_api.get("weight"):
        try:
            w = int(weight)
            actor.extra = actor.extra or {}
            actor.extra["weight_kg"] = round(w / 2.205)
        except (ValueError, TypeError):
            pass

    # 出生日期
    if birthday := performer_from_api.get("birthday"):
        try:
            dt = datetime.strptime(birthday[:19], "%Y-%m-%dT%H:%M:%S")
            actor.extra = actor.extra or {}
            actor.extra["birthdate"] = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # 国籍
    if birth_place := performer_from_api.get("birthPlace"):
        actor.extra = actor.extra or {}
        actor.extra["country"] = birth_place

    # 三围
    if measurements := performer_from_api.get("measurements"):
        actor.extra = actor.extra or {}
        actor.extra["measurements"] = measurements

    # 头像（取最大版本）
    images = performer_from_api.get("images", {}).get("master_profile", {}) or {}
    for size in ("xx", "xl", "lg", "md", "sm"):
        img_url = images.get(size, {}).get("url") if isinstance(images.get(size), dict) else None
        if img_url:
            actor.avatar_url = re.sub(r"/m=[^/]+", "", img_url)
            break

    return actor


def _to_performers(scene_from_api: dict) -> list[ActorInfo]:
    """提取演员列表（参考 P0 to_scraped_scene.performers）"""
    brand = _dig(scene_from_api, "brand") or ""
    actors_data = scene_from_api.get("actors", []) or []
    return [_to_actor(p, brand) for p in actors_data]


def _get_studio(api_object: dict) -> Optional[dict]:
    """提取制作商（参考 P0 get_studio）"""
    studio_name = _dig(api_object, "collections", 0, "name")
    parent_name = _dig(api_object, "brandMeta", ("displayName", "name", "shortName"))
    if studio_name:
        if parent_name and parent_name.lower() != studio_name.lower():
            return {"name": studio_name, "parent": {"name": parent_name}}
        return {"name": studio_name}
    elif parent_name:
        return {"name": parent_name}
    return None


def _parse_scene(scene_from_api: dict, site: Optional[str] = None) -> Optional[ScrapeResult]:
    """解析 scene 数据（参考 P0 to_scraped_scene）"""
    if scene_from_api.get("type") != "scene":
        return None

    title = scene_from_api.get("title") or ""
    scene_id = scene_from_api.get("id") or ""
    code = str(scene_id)

    release_date = None
    date_str = scene_from_api.get("dateReleased")
    if date_str:
        try:
            release_date = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    performers = _to_performers(scene_from_api)
    tags = _to_tags(scene_from_api)
    studio_info = _get_studio(scene_from_api)

    # 简介
    details = _dig(scene_from_api, "description") or _dig(scene_from_api, "parent", "description") or ""
    if details:
        details = re.sub(r"<\/?p>", "", str(details))
        details = "\n".join(" ".join([s for s in line.strip().split() if s]) for line in str(details).split("\n"))

    # 封面
    cover_url = None
    for path in [
        ("images", "poster", 0, ("xx", "xl", "lg", "md", "sm", "xs"), "url"),
        ("images", "poster_fallback", 0, ("xx", "xl", "lg", "md", "sm", "xs"), "url"),
    ]:
        url = _dig(scene_from_api, *path)
        if url:
            cover_url = re.sub(r"/m=[^/]+", "", str(url))
            break

    scene_url = _construct_scene_url(scene_from_api)

    result = ScrapeResult(
        code=code,
        title=title,
        source="aylo",
        original_title=title,
        studio=(studio_info or {}).get("name") if isinstance(studio_info, dict) else None,
        release_date=release_date,
        plot=details or None,
        tags=tags,
        actors=performers,
        cover_url=cover_url,
    )
    result.raw_data = scene_from_api
    if scene_url:
        result.source_url = scene_url

    return result


def _parse_performer(performer_from_api: dict, site: Optional[str] = None) -> Optional[ScrapeResult]:
    """将演员包装为 ScrapeResult（用于搜索演员）"""
    if (type_ := performer_from_api.get("brand")) and type_ not in ("actorsandtags", "phpactors"):
        return None

    name = performer_from_api.get("name") or ""
    if not name:
        return None

    actor = _to_actor(performer_from_api, site)
    result = ScrapeResult(
        code=str(performer_from_api.get("id", name)),
        title=name,
        source="aylo",
        original_title=name,
    )
    result.actors = [actor]
    result.raw_data = performer_from_api
    return result


# ------------------------------------------------------------
# 刮削器主类
# ------------------------------------------------------------

@register_crawler
class AyloAPICrawler(BaseCrawler):
    """AyloAPI 品牌站群通用刮削器

    覆盖 Aylo 旗下所有品牌: Brazzers / BangBros / Reality Kings / Vixen / Blacked / Tushy /
    Naughty America / MYLF / TeamSkeet / EvilAngel / Mofos / Twistys / Babes / Digital Playground 等。

    通过 site-api.project1service.com 统一 API 获取数据。
    instance_token 从站点根域 cookie 中获取，按天缓存。

    所有请求通过 MDCX 内置代理。
    """

    name = "aylo"
    display_name = "AyloAPI (Brazzers/BangBros/Vixen/etc.)"
    base_url = AYLO_API_BASE

    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    supported_prefixes = []
    description = "Aylo 品牌站群统一 API 刮削器"
    language = "en"
    requires_proxy = True  # 强制使用内置代理

    def __init__(self):
        super().__init__()
        self._token_store = AyloTokenStore()
        self._headers_base = {
            "User-Agent": AYLO_USER_AGENT,
            "Origin": "",
            "Referer": "",
        }

    @staticmethod
    def _site_name(url: str) -> str:
        """从 URL 提取 site name（参考 P0 domains.site_name）"""
        try:
            netloc = urlparse(url).netloc
            return netloc.split(".")[-2]
        except Exception:
            return ""

    def _domain_to_url(self, domain: str) -> str:
        """domain -> 完整 URL（参考 P0 domains.get_token_for）"""
        return f"https://www.{domain}.com"

    async def _get_instance_token(self, domain: str) -> Optional[str]:
        """获取 instance_token（先查缓存，否则请求站点根域）"""
        token = self._token_store.get(domain)
        if token:
            return token

        # 请求站点根域获取 token（参考 P0 _create_headers_for.get_instance_token）
        url = self._domain_to_url(domain)
        proxy = get_proxy()
        async with AsyncHttpClient(proxy=proxy, timeout=20) as client:
            try:
                resp = await client.get(url, headers={"User-Agent": AYLO_USER_AGENT})
                if resp and resp.cookies:
                    token = resp.cookies.get("instance_token")
                    if token:
                        self._token_store.set(domain, token)
                        logger.info(f"Aylo 缓存 token: {domain}")
                        return token
            except Exception as e:
                logger.warning(f"获取 Aylo token 失败 [{domain}]: {e}")

        return None

    def _build_headers(self, domain: str, instance_token: str) -> dict:
        """构建 API 请求头（参考 P0 _create_headers_for.api_headers）"""
        return {
            "Instance": instance_token,
            "User-Agent": AYLO_USER_AGENT,
            "Origin": f"https://{domain}",
            "Referer": f"https://{domain}",
        }

    async def _api_request(self, url: str, domain: str) -> Optional[dict]:
        """发送 API 请求（参考 P0 __api_request）"""
        token = await self._get_instance_token(domain)
        if not token:
            logger.error(f"无法获取 Aylo token: {domain}")
            return None

        headers = self._build_headers(domain, token)
        proxy = get_proxy()
        async with AsyncHttpClient(proxy=proxy, timeout=30) as client:
            try:
                resp = await client.get(url, headers=headers)
                if resp is None:
                    return None
                if resp.status_code == 429:
                    logger.error("Aylo 429 限流")
                    return None
                data = await resp.json() if hasattr(resp, "json") else None
                if not data:
                    return None
                if isinstance(data, list):
                    logger.error(f"Aylo API 错误: {data}")
                    return None
                return data.get("result") if isinstance(data, dict) else None
            except Exception as e:
                logger.error(f"Aylo API 请求失败 [{url}]: {e}")
                return None

    async def _extract_scene_id(self, url: str) -> Optional[tuple[str, str]]:
        """从 URL 提取 (scene_id, domain)（参考 P0 scene_from_url）"""
        m = re.search(r"/(\d+)/", url)
        if not m:
            return None
        scene_id = m.group(1)
        domain = self._site_name(url)
        if not domain:
            return None
        return scene_id, domain

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """刮削指定 scene

        Args:
            code: scene URL (https://www.brazzers.com/scene/12345/title) 或纯 ID
        """
        # 解析 URL
        if code.startswith("http"):
            extracted = await self._extract_scene_id(code)
            if not extracted:
                logger.error(f"Aylo 无效 URL: {code}")
                self.mark_error()
                return None
            scene_id, domain = extracted
        else:
            # 纯 ID: 尝试通用 releases 端点
            scene_id = code
            domain = AYLO_BRANDS[0]  # 默认

        url = f"{AYLO_API_BASE}/releases/{scene_id}"
        data = await self._api_request(url, domain)
        if not data:
            self.mark_error()
            return None

        # 排除 trailer（参考 P0 scene_from_url）
        if data.get("type") != "scene":
            parent = data.get("parent")
            if isinstance(parent, dict) and parent.get("type") == "scene":
                data = parent

        result = _parse_scene(data, domain)
        if result:
            self.mark_success()
        else:
            self.mark_error()
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 Aylo 内容（按品牌范围）"""
        results = []
        for domain in AYLO_BRANDS[:3]:  # 限制最多 3 个品牌，避免限流
            url = f"{AYLO_API_BASE}/releases?q={keyword}"
            data = await self._api_request(url, domain)
            if not data:
                continue
            # API 返回可能是 releases 列表
            items = data if isinstance(data, list) else [data]
            for item in items[:10]:
                r = _parse_scene(item, domain)
                if r and r.is_valid():
                    results.append(r)
            await asyncio.sleep(0.5)  # 限流保护
        return results


# 便捷函数
async def scrape_aylo_scene(url: str) -> Optional[ScrapeResult]:
    """便捷函数：从 Aylo scene URL 刮削"""
    crawler = AyloAPICrawler()
    return await crawler.scrape(url)
