"""
MDCX 旧式爬虫适配器基类

将 MDCX 的 async def main() 风格爬虫适配到我们的 BaseCrawler 接口。
每个旧式爬虫的 main() 函数接收 (number, appoint_url, **kwargs) 参数，
返回 {website_name: {language: {...}}} 格式的字典。

适配器负责：
1. 调用 main() 获取原始数据
2. 将原始 dict 映射到我们的 ScrapeResult
3. 处理异常和错误
"""

import logging
from datetime import date
from typing import Any, Optional

from app.crawlers.base import ActorInfo, BaseCrawler, ScrapeResult
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


class LegacyCrawlerAdapter(BaseCrawler):
    """
    旧式爬虫适配器基类

    子类只需定义：
    - name / display_name / base_url / supported_types
    - _main_func: 指向 MDCX 的 main 函数
    - _parse_result(): 将 main() 返回的 dict 转为 ScrapeResult
    """

    # 子类必须定义
    _main_func: Any = None  # MDCX 的 main 函数

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """
        调用 MDCX 的 main 函数并适配结果

        Args:
            code: 番号
            ctx: 单次刮削共享上下文（旧式爬虫暂不使用，保留参数以兼容接口）

        Returns:
            ScrapeResult 刮削结果
        """
        if not self._main_func:
            logger.error(f"Crawler {self.name} has no _main_func defined")
            return None

        try:
            # 调用 MDCX main 函数（旧式接口，不接受 ctx）
            raw_result = await self._main_func(number=code)

            if not raw_result:
                return None

            # 解析结果
            return self._parse_result(raw_result, code)

        except Exception as e:
            logger.error(f"{self.name} scrape error for {code}: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索（旧式爬虫不支持搜索）"""
        return []

    def _parse_result(self, raw_result: dict, code: str) -> Optional[ScrapeResult]:
        """
        解析 MDCX 格式的结果为 ScrapeResult

        MDCX 返回格式: {website_name: {language: {field: value, ...}}}

        字段映射:
        - number -> code
        - title -> title
        - originaltitle -> title (备用)
        - actor -> actors (逗号分隔字符串)
        - outline -> plot
        - originalplot -> plot (备用)
        - tag -> genres (逗号分隔字符串)
        - release -> release_date
        - year -> year
        - runtime -> duration
        - score -> rating
        - studio -> studio
        - publisher -> maker
        - series -> series
        - director -> director
        - thumb -> cover_url
        - poster -> poster_url
        - trailer -> trailer_url
        - extrafanart -> sample_images
        - source -> source
        """
        try:
            # 获取第一个语言的数据
            site_data = None
            for lang_data in raw_result.values():
                if isinstance(lang_data, dict):
                    for data in lang_data.values():
                        if isinstance(data, dict) and data.get("title"):
                            site_data = data
                            break
                elif isinstance(lang_data, dict) and lang_data.get("title"):
                    site_data = lang_data
                if site_data:
                    break

            if not site_data:
                return None

            title = site_data.get("title", "") or site_data.get("originaltitle", "")
            if not title:
                return None

            # 解析演员
            actors = self._parse_actors(site_data)

            # 解析标签
            genres = self._parse_genres(site_data)

            # 解析发行日期
            release_date = self._parse_release_date(site_data)

            # 解析时长
            duration = self._parse_duration(site_data)

            # 解析评分
            rating = self._parse_rating(site_data)

            # 解析样图
            sample_images = self._parse_sample_images(site_data)

            # 解析简介
            plot = site_data.get("outline", "") or site_data.get("originalplot", "")

            return ScrapeResult(
                code=site_data.get("number", code),
                title=title,
                source=self.name,
                studio=site_data.get("studio"),
                maker=site_data.get("publisher"),
                series=site_data.get("series"),
                release_date=release_date,
                duration=duration,
                plot=plot,
                genres=genres,
                actors=actors,
                cover_url=site_data.get("thumb") or site_data.get("cover"),
                poster_url=site_data.get("poster"),
                trailer_url=site_data.get("trailer"),
                sample_images=sample_images,
                rating=rating,
            )

        except Exception as e:
            logger.error(f"Parse result error for {self.name}: {e}")
            return None

    def _parse_actors(self, data: dict) -> list[ActorInfo]:
        """解析演员列表"""
        actors = []
        actor_str = data.get("actor", "")
        if actor_str:
            for name in actor_str.split(","):
                name = name.strip()
                if name:
                    actors.append(ActorInfo(name=name))

        # 尝试从 actor_photo 获取更多信息
        actor_photo = data.get("actor_photo", {})
        if actor_photo and not actors:
            for name in actor_photo.keys():
                if name:
                    actors.append(ActorInfo(name=name))

        return actors

    def _parse_genres(self, data: dict) -> list[str]:
        """解析标签列表"""
        tag_str = data.get("tag", "")
        if isinstance(tag_str, str):
            return [t.strip() for t in tag_str.split(",") if t.strip()]
        elif isinstance(tag_str, list):
            return tag_str
        return []

    def _parse_release_date(self, data: dict) -> Optional[date]:
        """解析发行日期"""
        import re

        release = data.get("release", "")
        if not release:
            return None

        # 尝试匹配 YYYY-MM-DD
        if match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(release)):
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        return None

    def _parse_duration(self, data: dict) -> Optional[int]:
        """解析时长"""
        import re

        runtime = data.get("runtime", "")
        if not runtime:
            return None

        if match := re.search(r"(\d+)", str(runtime)):
            return int(match.group(1))

        return None

    def _parse_rating(self, data: dict) -> Optional[float]:
        """解析评分"""
        score = data.get("score", "")
        if not score:
            return None

        try:
            return float(score)
        except (ValueError, TypeError):
            return None

    def _parse_sample_images(self, data: dict) -> list[str]:
        """解析样图列表"""
        extrafanart = data.get("extrafanart", [])
        if isinstance(extrafanart, list):
            return extrafanart
        return []
