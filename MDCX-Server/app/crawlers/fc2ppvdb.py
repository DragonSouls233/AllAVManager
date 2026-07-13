"""
FC2PPVDB 爬虫 - 从 fc2ppvdb.com 刮削 FC2 视频信息
"""

import json
import re
from datetime import date
from typing import Optional

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    CrawlerStatus,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.config.manager import get_config
from app.utils.http_client import AsyncHttpClient


def _cookie_str_to_dict(cookie_str: str) -> dict:
    """将 cookie 字符串转为字典"""
    cookies = {}
    for item in cookie_str.split("; "):
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key] = value
    return cookies


@register_crawler
class FC2PPVDBCrawler(BaseCrawler):
    """FC2PPVDB 爬虫 - 从 fc2ppvdb.com 获取 FC2 视频信息"""

    name = "fc2ppvdb"
    display_name = "FC2PPVDB"
    base_url = "https://fc2ppvdb.com"

    priority = CrawlerPriority.HIGH
    supported_types = ["fc2"]
    supported_prefixes = ["FC2", "FC2-"]
    description = "FC2 PPV 数据库站点 (fc2ppvdb.com)"
    language = "ja"
    requires_proxy = False

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        Args:
            code: 番号（如 FC2-1234567）

        Returns:
            ScrapeResult 刮削结果
        """
        number_id = self._extract_number_id(code)
        if not number_id:
            return None

        # 从配置读取 cookie
        config = get_config()
        cookie_str = config.crawler.fc2ppvdb_cookie or ""
        cookies = _cookie_str_to_dict(cookie_str) if cookie_str else None

        async with AsyncHttpClient() as client:
            try:
                # 先访问详情页以建立 session cookie
                detail_url = f"{self.base_url}/articles/{number_id}"
                await client.get_text(detail_url, cookies=cookies)

                # 通过 XHR API 获取 JSON 数据
                xhr_url = f"{self.base_url}/articles/article-info?videoid={number_id}"
                xhr_text = await client.get_text(xhr_url, cookies=cookies)

                data = json.loads(xhr_text)

                result = self._parse_xhr_data(data, code, number_id)

                if result:
                    self.mark_success()
                else:
                    self.mark_error()

                return result

            except Exception as e:
                self.mark_error()
                raise e

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        搜索番号

        Args:
            keyword: 搜索关键词

        Returns:
            搜索结果列表
        """
        # FC2PPVDB 搜索功能暂不实现
        return []

    def _extract_number_id(self, code: str) -> Optional[str]:
        """从番号提取纯数字ID"""
        code = code.upper()
        code = (
            code.replace("FC2PPV", "")
            .replace("FC2-PPV-", "")
            .replace("FC2-", "")
            .replace("-", "")
            .strip()
        )

        if code.isdigit():
            return code

        return None

    def _parse_xhr_data(
        self,
        data: dict,
        code: str,
        number_id: str,
    ) -> Optional[ScrapeResult]:
        """解析 XHR API 返回的 JSON 数据"""
        article = data.get("article", {})
        if not article:
            return None

        # 标题
        title = article.get("title", "")
        if not title:
            return None

        # 封面
        cover_url = self._get_cover(article)

        # 发行日期
        release_date = self._get_release_date(article)

        # 演员
        actors = self._get_actors(article)

        # 标签
        genres = self._get_tags(article)

        # 厂商（卖家）
        studio = self._get_studio(article)

        # 是否有码
        is_mosaic, is_uncensored = self._get_censored_status(article)

        # 时长
        duration = self._get_duration(article)

        return ScrapeResult(
            code=code,
            title=title,
            source=self.name,
            release_date=release_date,
            duration=duration,
            genres=genres,
            actors=actors,
            cover_url=cover_url,
            studio=studio,
            is_mosaic=is_mosaic,
            is_uncensored=is_uncensored,
        )

    def _get_cover(self, article: dict) -> Optional[str]:
        """获取封面 URL"""
        image_url = article.get("image_url", "")
        if image_url and "no-image" not in image_url:
            return image_url
        return None

    def _get_release_date(self, article: dict) -> Optional[date]:
        """获取发行日期"""
        date_str = article.get("release_date", "")
        if not date_str:
            return None

        date_str = date_str.replace("/", "-").replace(".", "-")

        if match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str):
            try:
                return date(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                )
            except ValueError:
                return None

        return None

    def _get_actors(self, article: dict) -> list[ActorInfo]:
        """获取演员列表"""
        actresses = article.get("actresses", [])
        actors = []
        for actress in actresses:
            name = actress.get("name", "")
            if name:
                actors.append(ActorInfo(name=name))
        return actors

    def _get_tags(self, article: dict) -> list[str]:
        """获取标签列表"""
        tags = article.get("tags", [])
        result = []
        for tag in tags:
            name = tag.get("name", "")
            if name and name != "無修正":
                result.append(name)
        return result

    def _get_studio(self, article: dict) -> Optional[str]:
        """获取厂商（卖家名称）"""
        writer = article.get("writer", {})
        name = writer.get("name", "")
        return name if name else None

    def _get_censored_status(self, article: dict) -> tuple[Optional[bool], Optional[bool]]:
        """获取是否有码/无码状态"""
        censored = article.get("censored")
        if censored == "無":
            return False, True   # 无码
        elif censored == "有":
            return True, False   # 有码
        return None, None

    def _get_duration(self, article: dict) -> Optional[int]:
        """获取时长（分钟）"""
        duration_str = article.get("duration", "")
        if not duration_str:
            return None

        # 格式: HH:MM:SS 或 MM:SS
        if ":" in str(duration_str):
            parts = str(duration_str).split(":")
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 2:
                    return int(parts[0])
            except ValueError:
                pass

        # 格式: 纯数字（秒或分钟）
        if match := re.search(r"(\d+)", str(duration_str)):
            val = int(match.group(1))
            # 如果值大于 300，假设是秒，转为分钟
            if val > 300:
                return val // 60
            return val

        return None
