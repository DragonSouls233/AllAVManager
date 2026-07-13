"""
fanart.tv 集成爬虫（C1）

调用 fanart.tv API 获取影片的 Fanart 背景图、海报、清晰艺术图等资源。

fanart.tv API 文档：https://fanart.tv/api/
- 端点：https://webservice.fanart.tv/v3/movies/{tmdb_id}?api_key={api_key}
- 需要 Personal API Key（在 https://fanart.tv/personal/ 注册获取）
- 返回 JSON，包含 hdmovieclearart / moviebackground / movieposter / moviethumb / moviebanner / movielogo 等字段

本模块为独立类（不继承 BaseCrawler），因为 fanart.tv 的查询基于 TMDB ID 而非番号，
与 BaseCrawler 的 scrape(code) 接口不匹配。
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.models import Movie

logger = logging.getLogger(__name__)


# fanart.tv 返回的字段名 → 统一中文描述映射
FANART_FIELD_MAP = {
    "hdmovieclearart": "高清清晰艺术图",
    "moviebackground": "电影背景图",
    "movieposter": "电影海报",
    "moviethumb": "电影缩略图",
    "moviebanner": "电影横幅",
    "movielogo": "电影 Logo",
    "hdmovielogo": "高清电影 Logo",
    "moviedisc": "光盘艺术图",
    "movieart": "电影艺术图",
}


class FanartCrawler:
    """
    fanart.tv API 爬虫

    用法：
        crawler = FanartCrawler()
        result = await crawler.search_fanarts("12345")  # tmdb_id
        await crawler.download_fanart("https://example.com/bg.jpg", "/path/to/save/bg.jpg")
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """初始化

        Args:
            api_key: fanart.tv Personal API Key（留空则从配置读取）
            base_url: API 基础地址（留空则从配置读取）
            timeout: 请求超时秒数（留空则从配置读取）
        """
        config = get_config()
        fanart_cfg = config.fanart
        self.api_key = api_key or fanart_cfg.api_key
        self.base_url = (base_url or fanart_cfg.base_url).rstrip("/")
        self.timeout = timeout or fanart_cfg.timeout
        self.enabled = fanart_cfg.enabled and bool(self.api_key)

    async def search_fanarts(self, tmdb_id: str) -> dict:
        """调用 fanart.tv API 搜索指定 TMDB ID 的 Fanart 资源

        Args:
            tmdb_id: TMDB 影片 ID（字符串或整数均可）

        Returns:
            整理后的资源字典，结构：
            {
                "tmdb_id": "12345",
                "name": "电影名称",
                "moviebackground": [{"id": ..., "url": ..., "likes": ...}, ...],
                "movieposter": [...],
                "hdmovieclearart": [...],
                ...
            }
            请求失败时抛出 RuntimeError。

        Raises:
            RuntimeError: API key 未配置 / 请求失败 / API 返回错误
        """
        if not self.api_key:
            raise RuntimeError("fanart.tv API key 未配置，请在系统设置中填写")

        tmdb_id_str = str(tmdb_id).strip()
        if not tmdb_id_str or tmdb_id_str == "0":
            raise RuntimeError(f"无效的 TMDB ID: {tmdb_id}")

        url = f"{self.base_url}/movies/{tmdb_id_str}"
        params = {"api_key": self.api_key}
        headers = {
            "Accept": "application/json",
            "User-Agent": "MDCX/4.1 (https://github.com/MDCX)",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.info(f"fanart.tv 未找到 TMDB ID {tmdb_id_str} 的资源")
                    return {"tmdb_id": tmdb_id_str, "name": "", "not_found": True}
                logger.error(f"fanart.tv API 返回错误状态码: {e.response.status_code}")
                raise RuntimeError(f"fanart.tv API 请求失败: HTTP {e.response.status_code}") from e
            except httpx.RequestError as e:
                logger.error(f"fanart.tv API 请求异常: {e}")
                raise RuntimeError(f"fanart.tv API 请求异常: {e}") from e

        try:
            data = response.json()
        except ValueError as e:
            logger.error(f"fanart.tv 返回非 JSON 数据: {e}")
            raise RuntimeError(f"fanart.tv 返回数据解析失败: {e}") from e

        # 整理返回数据：每个字段提取 id/url/likes
        result: dict = {
            "tmdb_id": tmdb_id_str,
            "name": data.get("name", ""),
        }

        for field_name, _ in FANART_FIELD_MAP.items():
            items = data.get(field_name)
            if not items or not isinstance(items, list):
                continue
            normalized = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                url_value = item.get("url")
                if not url_value:
                    continue
                normalized.append({
                    "id": item.get("id"),
                    "url": url_value,
                    "likes": item.get("likes", 0),
                    "lang": item.get("lang", ""),
                })
            if normalized:
                result[field_name] = normalized

        return result

    async def download_fanart(self, url: str, save_path: str) -> str:
        """下载 fanart 图片到本地

        Args:
            url: 图片 URL
            save_path: 本地保存绝对路径

        Returns:
            实际保存的绝对路径

        Raises:
            RuntimeError: 下载失败
        """
        save_path_obj = Path(save_path)
        save_path_obj.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.error(f"下载 fanart 图片失败 {url}: {e}")
                raise RuntimeError(f"下载图片失败: {e}") from e

        try:
            save_path_obj.write_bytes(response.content)
        except OSError as e:
            logger.error(f"保存 fanart 图片失败 {save_path}: {e}")
            raise RuntimeError(f"保存图片失败: {e}") from e

        logger.info(f"fanart 图片已保存: {save_path_obj}")
        return str(save_path_obj)

    async def get_fanarts_for_movie(self, movie_id: int, session: AsyncSession) -> dict:
        """根据影片的 tmdb_id 获取 fanart 资源

        Args:
            movie_id: 影片 ID（数据库 movies.id）
            session: 异步数据库会话

        Returns:
            search_fanarts 的返回结果，附加 movie_id / code 字段

        Raises:
            RuntimeError: 影片不存在 / 未配置 TMDB ID / 调用 API 失败
        """
        result = await session.execute(select(Movie).where(Movie.id == movie_id))
        movie = result.scalar_one_or_none()
        if movie is None:
            raise RuntimeError(f"影片不存在: id={movie_id}")

        if not movie.tmdb_id:
            raise RuntimeError(
                f"影片 {movie.code} 未配置 TMDB ID，无法查询 fanart.tv"
                "（请在影片详情页设置 TMDB ID 后重试）"
            )

        fanarts = await self.search_fanarts(str(movie.tmdb_id))
        fanarts["movie_id"] = movie.id
        fanarts["code"] = movie.code
        return fanarts

    async def download_and_apply_background(
        self,
        movie_id: int,
        session: AsyncSession,
        image_url: Optional[str] = None,
    ) -> dict:
        """下载 fanart 背景图并应用到影片

        流程：
        1. 若未指定 image_url，先调用 get_fanarts_for_movie 获取候选列表
        2. 选择第一个 moviebackground 资源（或已有的指定 URL）
        3. 下载到影片文件所在目录的 extrafanart 子目录
        4. 将路径写入 movie.sample_images 字段（追加到现有列表）

        Args:
            movie_id: 影片 ID
            session: 异步数据库会话
            image_url: 指定要下载的图片 URL（留空则自动选择第一个背景图）

        Returns:
            dict: {movie_id, code, saved_path, image_url, applied_field}

        Raises:
            RuntimeError: 影片不存在 / 无 TMDB ID / 无可用背景图 / 下载失败
        """
        result = await session.execute(select(Movie).where(Movie.id == movie_id))
        movie = result.scalar_one_or_none()
        if movie is None:
            raise RuntimeError(f"影片不存在: id={movie_id}")

        # 自动选择背景图
        if not image_url:
            fanarts = await self.get_fanarts_for_movie(movie_id, session)
            backgrounds = fanarts.get("moviebackground") or []
            if not backgrounds:
                raise RuntimeError(f"影片 {movie.code} 无可用的 moviebackground 资源")
            image_url = backgrounds[0]["url"]

        # 决定保存路径
        config = get_config()
        subdir = config.fanart.image_subdir or "extrafanart"
        if movie.file_path:
            movie_dir = Path(movie.file_path).parent
        else:
            # 无文件路径时，保存到 output_dir 下的 {code}/extrafanart
            output_dir = Path(config.scraper.output_dir)
            movie_dir = output_dir / (movie.code or str(movie.id))
        save_dir = movie_dir / subdir
        save_dir.mkdir(parents=True, exist_ok=True)

        # 从 URL 推断扩展名
        ext = ".jpg"
        for ext_candidate in (".png", ".jpg", ".jpeg", ".webp"):
            if ext_candidate in image_url.lower():
                ext = ext_candidate
                break
        save_path = save_dir / f"fanart_background{ext}"

        # 下载
        await self.download_fanart(image_url, str(save_path))

        # 应用到影片：追加到 sample_images JSON 数组
        import json
        existing: list[str] = []
        if movie.sample_images:
            try:
                parsed = json.loads(movie.sample_images)
                if isinstance(parsed, list):
                    existing = [str(x) for x in parsed if x]
            except (json.JSONDecodeError, TypeError):
                existing = []
        if str(save_path) not in existing:
            existing.append(str(save_path))
            movie.sample_images = json.dumps(existing, ensure_ascii=False)
            await session.commit()

        return {
            "movie_id": movie.id,
            "code": movie.code,
            "saved_path": str(save_path),
            "image_url": image_url,
            "applied_field": "sample_images",
        }
