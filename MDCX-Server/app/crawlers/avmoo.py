"""
Avmoo 爬虫 — 新私有 JSON API（2026-08 逆向确认）

站点 avmoo.shop 已改版为 SPA，旧版 /api/v1/* 接口全部失效（403/HTML 壳）。
新协议（Playwright 网络监听逆向）：
- 所有 API 请求前先 GET https://avmoo.shop/cn 拿 CSRF token（<meta name="csrf-token">）
- 请求头必须带 X-CSRF-Token + X-Requested-With + Content-Type: application/json + Referer
- 搜索番号： POST /jav/data/api/search   BODY: [{"search": "<番号>", "lang": "cn"}, 60, 1]
- 影片详情： POST /jav/data/api/getMovie  BODY: ["<movieId>", "cn"]
- 影片列表： POST /jav/data/api/getMovies BODY: [{"lang":"cn","starId":"<starId>"}, 60, 1]（按演员过滤作品）
- 演员详情： POST /jav/data/api/getStar    BODY: ["<starId>", "cn"]

纯 httpx + CSRF 已验证可用（无需浏览器渲染），本爬虫基于 AsyncHttpClient 实现。
"""
import asyncio
import logging
import re
import time
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
    """Avmoo 爬虫（新私有 JSON API，多语言标题）"""

    name = "avmoo"
    display_name = "Avmoo"
    base_url = "https://avmoo.shop"

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "Avmoo 数据库，新私有 JSON API，多语言标题"
    language = "zh"
    requires_proxy = True  # 大陆直连超时/被拒，需走代理

    # CSRF 会话缓存（模块级，带过期时间，避免每个请求都 GET 首页）
    _csrf_token: str = ""
    _csrf_time: float = 0.0
    _csrf_ttl: float = 3600.0

    # 请求间隔（秒）
    _last_request_time: float = 0.0
    _request_interval: float = 1.0

    # ------------------------------------------------------------------
    # 内部：CSRF 会话 + API 调用
    # ------------------------------------------------------------------
    async def _ensure_csrf(self, client: AsyncHttpClient) -> str:
        """获取 CSRF token（缓存 1 小时，过期重新 GET /cn）"""
        if self._csrf_token and (time.time() - self._csrf_time) < self._csrf_ttl:
            return self._csrf_token
        html = await client.get_text(
            f"{self.base_url}/cn",
            headers={"Accept": "text/html", "Accept-Language": "zh-CN,zh;q=0.9"},
        )
        token = ""
        if html:
            m = re.search(r'csrf-token"\s+content="([^"]+)', html)
            if m:
                token = m.group(1)
        if token:
            self._csrf_token = token
            self._csrf_time = time.time()
        return token

    def _api_headers(self, csrf: str) -> dict:
        """新 API 必需请求头"""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf,
            "Referer": f"{self.base_url}/cn",
        }

    async def _api_post(
        self, path: str, body: list, max_retries: int = 2
    ) -> Optional[dict]:
        """POST JSON 到私有 API，返回响应 dict（自动处理 CSRF 过期重取）"""
        for attempt in range(max_retries + 1):
            async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
                await self._rate_limit()
                csrf = await self._ensure_csrf(client)
                if not csrf:
                    logger.warning(f"Avmoo 无法获取 CSRF token: {path}")
                    return None
                try:
                    resp = await client.post(
                        f"{self.base_url}{path}",
                        json=body,
                        headers=self._api_headers(csrf),
                    )
                    data = resp.json()
                    if data and data.get("code") == 200:
                        return data
                    # CSRF 失效（403）时强制刷新一次再试
                    if attempt < max_retries and (resp.status_code == 403 or data is None):
                        self._csrf_token = ""
                        self._csrf_time = 0.0
                        await asyncio.sleep(0.5)
                        continue
                    return None
                except Exception as e:
                    logger.debug(f"Avmoo API 失败 {path} 尝试 {attempt + 1}: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                    else:
                        return None
        return None

    async def _rate_limit(self):
        """限流：确保请求间隔"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # 刮削入口
    # ------------------------------------------------------------------
    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号：search 精确匹配番号 → getMovie 详情"""
        data = await self._api_post(
            "/jav/data/api/search", [{"search": code, "lang": "cn"}, 60, 1]
        )
        if not data:
            self.mark_error()
            return None

        items = data.get("data") or []
        movie_id = None
        if isinstance(items, list):
            code_norm = code.replace("_", "-").upper()
            for it in items:
                fanhao = (it.get("movieFanHao") or "").replace("_", "-").upper()
                if fanhao == code_norm or fanhao == code.upper():
                    movie_id = it.get("movieId")
                    break
            # 未精确命中 → 取第一条
            if not movie_id and items:
                movie_id = items[0].get("movieId")

        if not movie_id:
            logger.debug(f"Avmoo {code}: 搜索无结果")
            self.mark_error()
            return None

        detail = await self._api_post(
            "/jav/data/api/getMovie", [movie_id, "cn"]
        )
        if not detail:
            self.mark_error()
            return None

        movie = detail.get("data") or {}
        result = self._parse_api_data(movie, code)
        if result:
            self.mark_success()
        else:
            self.mark_error()
        return result

    # ------------------------------------------------------------------
    # 搜索入口（抽象方法）
    # ------------------------------------------------------------------
    async def search(self, keyword: str) -> list[ScrapeResult]:
        """按关键词搜索番号"""
        data = await self._api_post(
            "/jav/data/api/search", [{"search": keyword, "lang": "cn"}, 60, 1]
        )
        results: list[ScrapeResult] = []
        if not data:
            return results
        items = data.get("data") or []
        if not isinstance(items, list):
            return results
        # 列表条目已含大部分字段，直接解析；如需完整字段可再 getMovie（这里解析列表字段足够）
        for item in items[:20]:
            result = self._parse_api_data(item, item.get("movieFanHao") or keyword)
            if result:
                results.append(result)
        return results

    # ------------------------------------------------------------------
    # 演员能力（演员作品对比 / 演员页 URL 探测用）
    # ------------------------------------------------------------------
    async def fetch_actress_movies(
        self, star_id: str, max_pages: int = 5, page_size: int = 60
    ) -> list[dict]:
        """按 starId 抓取某演员的全部作品列表（getMovies 过滤）

        Returns:
            [{"title": str, "code": str, "date": str, "url": str, "movieId": str}, ...]
        """
        movies: list[dict] = []
        for page in range(1, max_pages + 1):
            data = await self._api_post(
                "/jav/data/api/getMovies",
                [{"lang": "cn", "starId": star_id}, page_size, page],
            )
            if not data:
                break
            items = data.get("data") or []
            if not isinstance(items, list) or not items:
                break
            for it in items:
                movie_id = it.get("movieId") or ""
                movies.append({
                    "title": it.get("title_cn") or it.get("title") or "",
                    "code": it.get("movieFanHao") or "",
                    "date": it.get("releaseDate") or "",
                    "url": f"{self.base_url}/cn/movies/{movie_id}" if movie_id else f"{self.base_url}/star/{star_id}",
                    "movieId": movie_id,
                })
            if len(items) < page_size:
                break
            await self._rate_limit()
        return movies

    async def search_star_id(self, actor_name: str) -> Optional[str]:
        """按演员名搜索 → 返回第一个命中作品的 starId（探测演员页用）"""
        data = await self._api_post(
            "/jav/data/api/search", [{"search": actor_name, "lang": "cn"}, 60, 1]
        )
        if not data:
            return None
        items = data.get("data") or []
        if not isinstance(items, list) or not items:
            return None
        # 优先取 starId 非空的条目
        for it in items:
            sid = it.get("starId")
            if sid:
                return sid
        return None

    # ------------------------------------------------------------------
    # 数据解析
    # ------------------------------------------------------------------
    def _parse_api_data(self, data: dict, code: str) -> Optional[ScrapeResult]:
        """解析新 API 返回数据（字段：movieFanHao/title_ja/cn/tw/releaseDate/length/...）"""
        if not data:
            return None

        # 番号（以数据为准）
        real_code = data.get("movieFanHao") or code

        # 多语言标题
        title_cn = data.get("title_cn") or data.get("title_tw") or ""
        title_ja = data.get("title_ja") or data.get("title") or ""
        title = title_cn or title_ja or code

        # 发行日期
        release_date = None
        date_str = data.get("releaseDate")
        if date_str:
            try:
                release_date = date.fromisoformat(str(date_str)[:10])
            except (ValueError, TypeError):
                pass

        # 时长
        duration = None
        duration_str = data.get("length")
        if duration_str:
            try:
                duration = int(re.search(r"\d+", str(duration_str)).group())
            except (AttributeError, ValueError):
                pass

        # 演员（star 为对象数组：starName_ja/cn/tw + avatar）
        actors: list[ActorInfo] = []
        star_list = data.get("star") or []
        if isinstance(star_list, list):
            for s in star_list:
                if not isinstance(s, dict):
                    continue
                name_ja = s.get("starName_ja") or ""
                name_cn = s.get("starName_cn") or s.get("starName") or ""
                name = name_cn or name_ja
                if not name:
                    continue
                actors.append(ActorInfo(
                    name=name,
                    japanese_name=name_ja or None,
                    avatar_url=s.get("avatar") or s.get("avatarUrl") or None,
                ))

        # 类别（genre 为对象数组：genreName_ja/cn）
        genres: list[str] = []
        genre_list = data.get("genre") or []
        if isinstance(genre_list, list):
            for g in genre_list:
                if not isinstance(g, dict):
                    continue
                gname = g.get("genreName_cn") or g.get("genreName_ja") or g.get("genreName") or ""
                if gname:
                    genres.append(gname)

        # 制作商 / 导演 / 发行商 / 系列（均为对象）
        studio = self._obj_name(data.get("studio"), ("studioName_ja", "studioName_cn", "studioName"))
        director = self._obj_name(data.get("director"), ("directorName_ja", "directorName_cn", "directorName"))
        label = self._obj_name(data.get("label"), ("labelName_ja", "labelName_cn", "labelName"))
        series = self._obj_name(data.get("series"), ("seriesName_ja", "seriesName_cn", "seriesName"))

        # 封面 / 样图
        cover_url = data.get("posterLarge") or data.get("posterSmall")
        samples = data.get("sampleLarge") or data.get("sampleSmall") or []
        sample_images = [u for u in samples if isinstance(u, str) and u] if isinstance(samples, list) else []

        return ScrapeResult(
            code=real_code,
            title=title,
            source=self.name,
            original_title=title_ja or None,
            studio=studio,
            label=label,
            series=series,
            release_date=release_date,
            duration=duration,
            genres=genres,
            actors=actors,
            directors=[director] if director else [],
            cover_url=cover_url,
            poster_url=cover_url,
            sample_images=sample_images,
            raw_data=data,
            confidence=0.9,
        )

    @staticmethod
    def _obj_name(obj, keys: tuple) -> Optional[str]:
        """从对象中取第一个非空字段值（studio/director 等为 dict）"""
        if not isinstance(obj, dict):
            return obj if isinstance(obj, str) and obj else None
        for k in keys:
            v = obj.get(k)
            if v:
                return v
        return None
