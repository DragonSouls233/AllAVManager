"""
Avmoo 爬虫 — 基于 JSON API

参考 JavBoss 的 avmoo provider：
- 端点: https://avmoo.shop/api/v1/movies/{code}
- 返回多语言标题 (ja/en/cn/tw)
- 1500ms 限流、3 次重试
- 支持 CSRF session 缓存
"""
import asyncio
import logging
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
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


@register_crawler
class AvmooCrawler(BaseCrawler):
    """Avmoo 爬虫（JSON API）"""

    name = "avmoo"
    display_name = "Avmoo"
    base_url = "https://avmoo.shop"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav", "jav_uncensored"]
    supported_prefixes = []
    description = "Avmoo 数据库，JSON API，多语言标题"
    language = "zh"
    requires_proxy = False

    # 请求间隔（秒）
    _last_request_time: float = 0
    _request_interval: float = 1.5

    async def _rate_limit(self):
        """限流：确保请求间隔"""
        import time
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        通过 JSON API 获取影片信息，支持多语言标题。
        """
        await self._rate_limit()

        api_url = f"{self.base_url}/api/v1/movies/{code}"

        async with AsyncHttpClient() as client:
            for attempt in range(3):
                try:
                    data = await client.get_json(api_url, headers={
                        "Accept": "application/json",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    })

                    if not data:
                        if attempt < 2:
                            await asyncio.sleep(1)
                            continue
                        return None

                    # 检查是否有数据
                    movie_data = data.get("data") or data
                    if not movie_data or (isinstance(movie_data, dict) and movie_data.get("code") != code.upper()):
                        # 尝试模糊匹配
                        if isinstance(movie_data, dict) and code.upper() not in (movie_data.get("code", "") or "").upper():
                            return None

                    result = self._parse_api_data(movie_data, code)
                    if result:
                        self.mark_success()
                    else:
                        self.mark_error()
                    return result

                except Exception as e:
                    logger.debug(f"Avmoo {code} 尝试 {attempt+1}/3 失败: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1.5)
                    else:
                        self.mark_error()
                        return None

        return None

    def _parse_api_data(self, data: dict, code: str) -> Optional[ScrapeResult]:
        """解析 JSON API 返回数据"""
        if not data:
            return None

        # 多语言标题
        title_cn = data.get("title_cn") or data.get("title_zh") or ""
        title_jp = data.get("title_jp") or data.get("title_original") or ""
        title_en = data.get("title_en") or ""
        title = title_cn or title_jp or title_en or code

        # 发行日期
        release_date = None
        date_str = data.get("release_date") or data.get("date")
        if date_str:
            try:
                release_date = date.fromisoformat(str(date_str)[:10])
            except (ValueError, TypeError):
                pass

        # 时长
        duration = None
        duration_str = data.get("duration") or data.get("runtime")
        if duration_str:
            try:
                duration = int(re.search(r"\d+", str(duration_str)).group())
            except (AttributeError, ValueError):
                pass

        # 演员
        actors = []
        actor_list = data.get("actors") or data.get("actresses") or []
        if isinstance(actor_list, list):
            for a in actor_list:
                if isinstance(a, dict):
                    actors.append(ActorInfo(
                        name=a.get("name_cn") or a.get("name") or "",
                        japanese_name=a.get("name_jp") or a.get("name") or None,
                        avatar_url=a.get("avatar_url") or a.get("thumb_url"),
                    ))
                elif isinstance(a, str):
                    actors.append(ActorInfo(name=a))

        # 标签
        genres = []
        genre_list = data.get("genres") or data.get("tags") or []
        if isinstance(genre_list, list):
            genres = [g if isinstance(g, str) else g.get("name", "") for g in genre_list]

        # 封面
        cover_url = data.get("cover_url") or data.get("cover") or data.get("poster")
        if cover_url and not cover_url.startswith("http"):
            cover_url = f"{self.base_url}{cover_url}"

        # 样图
        sample_images = []
        samples = data.get("sample_images") or data.get("images") or []
        if isinstance(samples, list):
            for img in samples:
                url = img if isinstance(img, str) else img.get("url", "")
                if url and not url.startswith("http"):
                    url = f"{self.base_url}{url}"
                if url:
                    sample_images.append(url)

        # 制作商/系列
        studio = data.get("studio") or data.get("maker")
        if isinstance(studio, dict):
            studio = studio.get("name")
        series = data.get("series")
        if isinstance(series, dict):
            series = series.get("name")

        # 是否有码
        is_uncensored = data.get("is_uncensored")
        if is_uncensored is None:
            is_uncensored = None
        else:
            is_uncensored = bool(is_uncensored)

        # 是否中字
        is_chinese = None
        if data.get("has_chinese_subtitle") is not None:
            is_chinese = bool(data.get("has_chinese_subtitle"))
        elif title_cn and ("中字" in title_cn or "中文字幕" in title_cn):
            is_chinese = True

        return ScrapeResult(
            code=code,
            title=title,
            source=self.name,
            original_title=title_jp or title_en or None,
            studio=studio,
            series=series,
            release_date=release_date,
            duration=duration,
            plot=data.get("plot") or data.get("description"),
            genres=genres,
            actors=actors,
            cover_url=cover_url,
            sample_images=sample_images,
            is_uncensored=is_uncensored,
            is_chinese=is_chinese,
            rating=data.get("rating") or data.get("score"),
            votes=data.get("votes") or data.get("score_count"),
            raw_data=data,
            confidence=0.9,
        )

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索番号"""
        await self._rate_limit()

        search_url = f"{self.base_url}/api/v1/search?q={keyword}"
        results = []

        async with AsyncHttpClient() as client:
            try:
                data = await client.get_json(search_url, headers={
                    "Accept": "application/json",
                })
                items = data.get("data") or data.get("results") or []
                if isinstance(items, list):
                    for item in items[:20]:
                        result = self._parse_api_data(item, item.get("code", keyword))
                        if result:
                            results.append(result)
            except Exception as e:
                logger.debug(f"Avmoo 搜索 {keyword} 失败: {e}")

        return results
