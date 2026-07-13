"""
ThePornDB Movies 爬虫 - 从 MDCX 迁移

原始文件: theporndb_movies.py
通过文件哈希或文件名搜索电影元数据。
"""

import logging
import re
import time
from difflib import SequenceMatcher
from typing import Optional

from app.crawlers.base import CrawlerPriority, ScrapeResult
from app.crawlers.legacy_adapter import LegacyCrawlerAdapter
from app.crawlers.md.compat import LogBuffer, manager
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


# ===== MDCX 原始解析函数 =====

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def read_data(data):
    """解析 theporndb movies API 返回的数据"""
    number = data.get("date") or ""
    title = data.get("title") or ""
    outline = data.get("description") or ""
    actor = ""
    all_actor = ""
    if data.get("performers"):
        actors_list = []
        for p in data["performers"]:
            if isinstance(p, dict):
                name = p.get("name", "")
                if name:
                    actors_list.append(name)
            elif isinstance(p, str):
                actors_list.append(p)
        actor = ",".join(actors_list)
        all_actor = actor
    cover_url = ""
    poster_url = ""
    if data.get("posters"):
        for p in data["posters"]:
            if isinstance(p, dict):
                cover_url = p.get("url", "")
                if cover_url:
                    break
    trailer = ""
    release = data.get("date") or ""
    year = release[:4] if release else ""
    runtime = str(data.get("duration") or "")
    tag = ""
    if data.get("tags"):
        tags_list = []
        for t in data["tags"]:
            if isinstance(t, dict):
                name = t.get("name", "")
                if name:
                    tags_list.append(name)
            elif isinstance(t, str):
                tags_list.append(t)
        tag = ",".join(tags_list)
    director = ""
    series = ""
    studio = data.get("studio") or ""
    if isinstance(studio, dict):
        studio = studio.get("name", "")
    publisher = studio
    real_url = ""
    return number, title, outline, actor, all_actor, cover_url, poster_url, trailer, release, year, runtime, tag, director, series, studio, publisher, real_url


# ===== 爬虫类 =====

@register_crawler
class ThePornDBMoviesCrawler(LegacyCrawlerAdapter):
    """ThePornDB Movies 爬虫"""

    name = "theporndb_movies"
    display_name = "ThePornDB Movies"
    base_url = "https://theporndb.net"

    priority = CrawlerPriority.LOW
    supported_types = ['jav']
    supported_prefixes = []
    description = "ThePornDB 电影版，通过文件哈希匹配"
    language = "en"

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        async with AsyncHttpClient() as client:
            try:
                raw_result = await self._call_mdcx_main(code, client)
                if not raw_result:
                    return None
                return self._parse_result(raw_result, code)
            except Exception as e:
                logger.error(f"{self.name} scrape error for {code}: {e}")
                return None

    async def _call_mdcx_main(self, code: str, client: AsyncHttpClient) -> Optional[dict]:
        """调用 MDCX 的 main 函数逻辑"""
        try:
            # 通过番号搜索电影
            search_url = f"https://api.theporndb.net/movies/search?q={code}"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            resp = await client.get(search_url)
            if not resp:
                return None

            import json as _json
            data = resp.json()
            if not data or not data.get("data"):
                return None

            movies = data["data"]
            if isinstance(movies, list) and len(movies) > 0:
                movie = movies[0]
            else:
                return None

            number, title, outline, actor, all_actor, cover_url, poster_url, trailer, release, year, runtime, tag, director, series, studio, publisher, real_url = read_data(movie)

            if not title:
                return None

            dic = {
                "number": number or code,
                "title": title,
                "originaltitle": title,
                "actor": actor,
                "all_actor": all_actor,
                "outline": outline,
                "originalplot": outline,
                "tag": tag,
                "release": release,
                "year": year,
                "runtime": runtime,
                "score": "",
                "series": series,
                "director": director,
                "studio": studio,
                "publisher": publisher,
                "source": "theporndb_movies",
                "website": real_url,
                "actor_photo": {},
                "thumb": cover_url,
                "poster": poster_url,
                "extrafanart": [],
                "trailer": trailer,
                "image_download": False,
                "image_cut": "",
                "mosaic": "无码",
                "wanted": "",
            }
            return {"theporndb_movies": {"zh_cn": dic, "zh_tw": dic, "jp": dic}}

        except Exception as e:
            logger.error(f"ThePornDB Movies scrape error for {code}: {e}")
            return None


async def main(
    number: str,
    appoint_url: str = "",
    file_path: str = "",
    **kwargs,
) -> Optional[dict]:
    """
    MDCX main 接口（供 theporndb.py 的回退逻辑调用）。

    按番号搜索 ThePornDB 电影库（movies API 无需 API Token 即可访问），
    返回 MDCX 字典格式 {"theporndb_movies": {language: {...}}}。
    若搜索失败或无匹配则返回 None，由调用方决定如何降级。
    """
    try:
        async with AsyncHttpClient() as client:
            crawler = ThePornDBMoviesCrawler()
            raw = await crawler._call_mdcx_main(number, client)
            if not raw:
                return None
            return raw
    except Exception as e:
        logger.error(f"ThePornDBMovies main fallback error for {number}: {e}")
        return None

