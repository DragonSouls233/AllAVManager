"""Stash 兼容的通用元数据插件接口。

参照 Stash (https://stashapp.cc) 的刮削器插件标准：
- 场景刮削 (scene scraper)
- 演员刮削 (performer scraper)
- 电影刮削 (movie scraper)

让外部 Stash 插件可以通过 MDCX 的开放接口刮削元数据。
同时让 MDCX 可以使用 Stash 社区的 30+ 刮削器。

参考项目：
- CommunityScrapers (Stash 刮削器标准)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Stash 数据模型
# ---------------------------------------------------------------------------


@dataclass
class StashScene:
    """Stash 刮削器场景数据模型。"""
    title: str = ""
    code: str = ""
    details: str = ""
    director: str = ""
    url: str = ""
    date: str = ""
    rating: str = ""
    image: str = ""
    studio: dict = field(default_factory=dict)
    tags: list[dict] = field(default_factory=list)
    performers: list[dict] = field(default_factory=list)
    movies: list[dict] = field(default_factory=list)


@dataclass
class StashPerformer:
    """Stash 演员数据模型。"""
    name: str = ""
    url: str = ""
    aliases: str = ""
    birthdate: str = ""
    ethnicity: str = ""
    country: str = ""
    eye_color: str = ""
    height: str = ""
    measurements: str = ""
    fake_tits: str = ""
    career_length: str = ""
    tattoos: str = ""
    piercings: str = ""
    weight: str = ""
    gender: str = ""
    image: str = ""


# ---------------------------------------------------------------------------
# MDCX 数据 → Stash 数据转换器
# ---------------------------------------------------------------------------


def scrape_result_to_stash(result: Any) -> Optional[StashScene]:
    """将 MDCX 的 ScrapeResult 转换为 StashScene。"""
    if not result:
        return None

    scene = StashScene()
    scene.title = getattr(result, 'title', '') or ''
    scene.code = getattr(result, 'code', '') or ''
    scene.details = getattr(result, 'plot', '') or ''
    scene.date = getattr(result, 'release_date', '') or ''
    scene.url = getattr(result, 'source_url', '') or ''
    scene.image = getattr(result, 'cover_url', '') or ''

    studio = getattr(result, 'studio', '') or ''
    if studio:
        scene.studio = {"name": studio}

    actors = getattr(result, 'actors', [])
    for a in actors:
        name = getattr(a, 'name', '') if hasattr(a, 'name') else (a if isinstance(a, str) else '')
        if name:
            scene.performers.append({"name": name, "alias_list": []})

    genres = getattr(result, 'genres', [])
    for g in genres:
        if g:
            scene.tags.append({"name": g})

    return scene


# ---------------------------------------------------------------------------
# Stash 兼容 API 工具
# ---------------------------------------------------------------------------


async def stash_scene_by_url(url: str) -> Optional[StashScene]:
    """Stash 标准接口：通过 URL 刮削场景。"""
    from app.services.western_utils import extract_brand_from_url, normalize_scene_url, AYLO_BRANDS, VIXEN_SITES

    normalized = normalize_scene_url(url)
    brand = extract_brand_from_url(normalized)

    if brand:
        logger.info("stash scene by url: brand=%s url=%s", brand, url)
        try:
            if any(b.name.lower() == brand.lower() for b in AYLO_BRANDS):
                from app.crawlers.western_aggregate import WesternAggregateCrawler
                crawler = WesternAggregateCrawler()
                result = await crawler.scrape(url)
                if result:
                    return scrape_result_to_stash(result)
            elif brand in VIXEN_SITES:
                from app.crawlers.western_aggregate import WesternAggregateCrawler
                crawler = WesternAggregateCrawler()
                result = await crawler.scrape(url)
                if result:
                    return scrape_result_to_stash(result)
        except Exception as e:
            logger.warning("stash scene by url failed: %s", e)

    return None


async def stash_scene_by_name(name: str, brand: str = "") -> Optional[StashScene]:
    """Stash 标准接口：通过名称搜索场景。"""
    from app.crawlers.western_aggregate import WesternBulkSearcher
    crawler = WesternBulkSearcher()
    results = await crawler.search(name)
    if results:
        return scrape_result_to_stash(results[0])
    return None


async def stash_performer_by_name(name: str) -> Optional[StashPerformer]:
    """Stash 标准接口：通过名称搜索演员。

    搜索优先级：
    1. ThePornDB API（通过配置文件中的 API Key）
    2. IAFD.com 网页搜索
    """
    try:
        from app.utils.http_client import AsyncHttpClient
        from app.config.manager import get_config

        cfg = get_config()

        # 1. ThePornDB API 搜索演员
        api_key = None
        try:
            api_key = cfg.western.theporndb_api_key
        except Exception:
            pass

        if not api_key:
            try:
                api_key = cfg.get('western', {}).get('theporndb_api_key', '')
            except Exception:
                pass

        if api_key:
            try:
                from urllib.parse import quote
                url = f"https://api.theporndb.net/v1/performers?q={quote(name)}"
                async with AsyncHttpClient(timeout=15, proxy=cfg.proxy.socks5 or None) as client:
                    resp = await client.get(url)
                    if resp and resp.status_code == 200:
                        data = resp.json()
                        items = data.get('data', []) if isinstance(data, dict) else []
                        if items:
                            p = items[0]
                            performer = StashPerformer()
                            performer.name = p.get('name', name)
                            performer.aliases = ', '.join(p.get('aliases', [])) if p.get('aliases') else ''
                            performer.image = p.get('image', '')
                            performer.birthdate = p.get('birthdate', '')[:10] if p.get('birthdate') else ''
                            performer.ethnicity = p.get('ethnicity', '')
                            performer.height = str(p.get('height', '')) if p.get('height') else ''
                            performer.weight = str(p.get('weight', '')) if p.get('weight') else ''
                            performer.gender = p.get('gender', 'Female')
                            return performer
            except Exception as e:
                logger.debug("theporndb performer search failed: %s", e)

        # 2. IAFD.com 网页搜索
        try:
            from app.crawlers.western_aggregate import IAFDScraper
            scraper = IAFDScraper()
            profile = await scraper.scrape(name)
            if profile:
                performer = StashPerformer()
                performer.name = getattr(profile, 'name', name)
                performer.aliases = getattr(profile, 'alias', '')
                performer.birthdate = getattr(profile, 'birth_date', '')[:10] if getattr(profile, 'birth_date', '') else ''
                performer.ethnicity = getattr(profile, 'ethnicity', '')
                performer.country = getattr(profile, 'birthplace', '')
                performer.height = str(getattr(profile, 'height', ''))
                performer.weight = str(getattr(profile, 'weight', ''))
                performer.image = getattr(profile, 'avatar_url', '')
                performer.gender = getattr(profile, 'gender', 'Female')
                return performer
        except ImportError:
            pass
        except Exception as e:
            logger.debug("iafd performer search failed: %s", e)

    except Exception as e:
        logger.debug("stash performer search failed: %s", e)
    return None
