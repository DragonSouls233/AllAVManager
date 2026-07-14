"""
JAVDB 爬虫增强模块

在原 JavDBCrawler 基础上整合 SmartCache 增量更新 + DomainSwitcher 域名切换。
不修改原有 crawler.py，采用 Wrapper 模式包装。

参考来源:
- P1: PornSimilarityPlatform javdb.py smart_cache 集成
- P1: PSP javdb.py get_incremental_fetch_range / should_update_page

功能:
  - SmartCache 增量更新（演员/系列页增量抓取）
  - DomainSwitcher 域名切换（javdb.com / javdb36.com / javdb.org）
  - 演员批量抓取（遍历演员列表 + 增量更新所有作品）
  - 已下载/未下载对比（compare_with_directories）

使用方式:
  enhancer = JavDBEnhancer()
  result = await enhancer.search_incremental("ABP-123", force_full=False)
  result = await enhancer.fetch_actor_titles("actor_name")
  comparison = await enhancer.compare_downloaded("actor_name", ["D:/videos"])
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.crawlers.javdb import JavDBCrawler
from app.services.domain_switcher import DomainSwitcher, make_javdb_switcher
from app.services.smart_cache import SmartCache, get_smart_cache
from app.services.download_tracker import (
    VideoInfo,
    CompareResult,
    DownloadTracker,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IncrementalSearchResult:
    """增量搜索结果"""
    keyword: str
    results: list[dict]
    is_incremental: bool = False
    skipped_pages: list[int] = field(default_factory=list)
    total_pages: int = 0
    duration: float = 0.0


class JavDBEnhancer:
    """JAVDB 爬虫增强器

    包装 JavDBCrawler，增加 SmartCache + DomainSwitcher 功能。
    不修改原 crawler.py 任何代码。
    """

    def __init__(self):
        self.crawler = JavDBCrawler()
        self.switcher = make_javdb_switcher()
        self.cache = get_smart_cache()
        self.tracker = DownloadTracker()

    async def _ensure_domain(self) -> bool:
        """确保域名可用"""
        url = await self.switcher.get_working()
        if not url:
            logger.error("JAVDB 所有域名不可用")
            return False
        if url != self.switcher.current:
            self.crawler.base_url = url
            logger.info(f"JAVDB 域名切换: {url}")
        return True

    async def search_incremental(
        self,
        keyword: str,
        max_pages: int = 10,
        force_full: bool = False,
    ) -> IncrementalSearchResult:
        """增量搜索

        Args:
            keyword: 搜索关键词
            max_pages: 最大搜索页数
            force_full: 强制全量搜索（忽略缓存）

        Returns:
            IncrementalSearchResult
        """
        start_time = time.time()
        result = IncrementalSearchResult(keyword=keyword)

        if not await self._ensure_domain():
            return result

        # 计算增量范围
        cache_key = f"javdb_search_{keyword}"
        if force_full:
            start_page, effective_max = 1, max_pages
        else:
            start_page, effective_max = self.cache.get_incremental_fetch_range(cache_key, max_pages)
            result.is_incremental = start_page > 1

        if result.is_incremental:
            logger.info(f"JAVDB 增量模式: {keyword} start_page={start_page}")

        all_results = []
        for page in range(start_page, effective_max + 1):
            if not self.cache.should_update_page(cache_key, page):
                result.skipped_pages.append(page)
                logger.debug(f"跳过已缓存页: {keyword} page {page}")
                continue

            try:
                html_text = await self.crawler._fetch_with_cloudscraper(
                    f"{self.crawler.base_url}/search?q={keyword}&locale=zh&page={page}"
                )
                if not html_text:
                    break

                from parsel import Selector
                html = Selector(html_text)
                items = html.xpath("//a[@class='box']")
                if not items:
                    break

                page_titles = []
                for item in items:
                    href = item.xpath("@href").get()
                    title = item.xpath("div[@class='video-title']/strong/text()").get()
                    code_text = item.xpath("div[@class='video-title']/span/text()").get()
                    if title:
                        page_titles.append(title.strip())
                        all_results.append({
                            "href": href,
                            "title": title.strip(),
                            "code": code_text or "",
                            "page": page,
                        })

                self.cache.record_page(cache_key, page, page_titles)
                result.total_pages = page

            except Exception as e:
                logger.warning(f"JAVDB 搜索页失败 page {page}: {e}")
                continue

        if all_results:
            self.cache.record_full_scrape(
                cache_key, result.total_pages, [r["title"] for r in all_results]
            )

        result.results = all_results
        result.duration = round(time.time() - start_time, 2)

        logger.info(
            f"JAVDB 搜索完成: {keyword} -> {len(all_results)} results, "
            f"{'增量' if result.is_incremental else '全量'}, "
            f"duration={result.duration}s"
        )
        return result

    async def fetch_actor_titles(
        self,
        actor_name: str,
        max_pages: int = 20,
        force_full: bool = False,
    ) -> IncrementalSearchResult:
        """抓取演员所有作品标题

        等价于调用 search_incremental(actor_name, max_pages)，但使用不同缓存 key。
        """
        return await self.search_incremental(
            keyword=actor_name,
            max_pages=max_pages,
            force_full=force_full,
        )

    async def batch_fetch_actors(
        self,
        actor_names: list[str],
        max_pages_per_actor: int = 10,
        progress_callback=None,
    ) -> dict[str, IncrementalSearchResult]:
        """批量抓取多个演员

        Args:
            actor_names: 演员名列表
            max_pages_per_actor: 每个演员最大页数
            progress_callback: 进度回调 (current, total)

        Returns:
            {actor_name: IncrementalSearchResult}
        """
        results = {}
        total = len(actor_names)

        for idx, name in enumerate(actor_names, 1):
            logger.info(f"批量抓取 [{idx}/{total}]: {name}")
            try:
                result = await self.fetch_actor_titles(name, max_pages_per_actor)
                results[name] = result
            except Exception as e:
                logger.error(f"批量抓取失败 [{name}]: {e}")
                results[name] = IncrementalSearchResult(keyword=name)

            if progress_callback:
                try:
                    progress_callback(idx, total)
                except Exception:
                    pass

        return results

    async def compare_downloaded(
        self,
        actor_name: str,
        local_dirs: list[str],
        max_pages: int = 20,
    ) -> CompareResult:
        """对比线上/本地下载状态

        Args:
            actor_name: 演员名
            local_dirs: 本地视频目录列表
            max_pages: 在线搜索最大页数

        Returns:
            CompareResult (matched / missing / chinese_missing 等)
        """
        # 抓取在线数据
        search_result = await self.fetch_actor_titles(actor_name, max_pages)
        online_videos = [
            VideoInfo(
                code=r.get("code", ""),
                title=r["title"],
                actress_name=actor_name,
            )
            for r in search_result.results if r.get("title")
        ]

        # 扫描本地目录
        result = self.tracker.compare_with_directories(actor_name, online_videos, local_dirs)

        report = self.tracker.generate_report(result)
        logger.info(report)

        return result

    def stats(self) -> dict:
        """获取增强器统计"""
        cache_stats = self.cache.stats()
        switcher_report = self.switcher.get_status_report()
        return {
            "cache": cache_stats,
            "domain": switcher_report,
        }

    def clear_cache(self, keyword: Optional[str] = None) -> None:
        """清空缓存"""
        if keyword:
            cache_key = f"javdb_search_{keyword}"
            self.cache.clear(cache_key)
            logger.info(f"已清空 JAVDB 缓存: {keyword}")
        else:
            self.cache.clear()
            logger.info("已清空所有 JAVDB 缓存")


# 全局单例
_enhancer: Optional[JavDBEnhancer] = None


def get_javdb_enhancer() -> JavDBEnhancer:
    global _enhancer
    if _enhancer is None:
        _enhancer = JavDBEnhancer()
    return _enhancer
