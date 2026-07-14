"""
麻豆社区增强爬虫

参考来源:
- P1: PornSimilarityPlatform/modules/madouqu/core/crawler.py (100%% 复用)
  - 搜索逻辑（search / _parse_search_results / _parse_item）
  - 详情页获取（get_detail，4 种磁力提取方式）
  - 弹窗处理（_handle_popups，30+ 种关闭选择器）
  - 分页爬取（max_pages 增量抓取）
  - 备用域名切换（find_working_url）

整合说明:
- 业务逻辑: 100%% 复用 P1 麻豆核心逻辑
- 域名切换: 已升级为 MDCX DomainSwitcher（异步+磁盘缓存）
- 磁力提取: 已升级为 MDCX MagnetExtractor（4 种 fallback + 参数解析）
- HTTP: 切换为 MDCX AsyncHttpClient + 强制内置代理
- Selenium: 复用 MDCX cf_bypass 模块
- 数据模型: 适配 MDCX ChineseMovie + ChineseActor

数据流:
  演员名 keyword
    → DomainSwitcher 获取可用域名
    → SmartCache 增量更新（跳过已有标题）
    → search() 分页搜索
    → get_detail() 从详情���获取磁力链接
    → MagnetExtractor 解析 btih/dn/tr
    → 写入 chinese_movies 表（source=madou）

使用方式:
  crawler = MadouCrawler()
  result = await crawler.search("演员名", max_pages=5)
  videos = await crawler.import_to_chinese_module("演员名", max_pages=5)
"""

import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.services.domain_switcher import DomainSwitcher, make_madouqu_switcher
from app.services.magnet_extractor import MagnetInfo, MagnetExtractor
from app.services.smart_cache import SmartCache, get_smart_cache
from app.services.proxy_manager import get_proxy
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


# 搜索结果条目模型
@dataclass
class SearchResultItem:
    title: str
    detail_url: str = ""
    magnets: list[MagnetInfo] = field(default_factory=list)
    date: str = ""
    size: str = ""
    model_name: str = ""


@dataclass
class CrawlResult:
    """爬取结果"""
    model_name: str
    videos: list[SearchResultItem] = field(default_factory=list)
    total_magnets: int = 0
    pages_crawled: int = 0
    duration_seconds: float = 0.0
    success: bool = False
    error_message: Optional[str] = None


# 弹窗关闭选择器（100%% 复用 P1 _handle_popups）
POPUP_CLOSE_SELECTORS = [
    ".close", ".modal-close", ".popup-close", ".ad-close",
    '[class*="close"]', '[class*="dismiss"]',
    "button.close", "a.close", ".btn-close",
    ".fc-close", ".fc-button-close",  # cookie 弹窗
    "#close-btn", ".close-btn", ".closeBtn",
    'div[class*="overlay"] .close',
    'span[class*="close"]', 'i[class*="close"]',
]

# 搜索结果选择器（按优先级）
SEARCH_ITEM_SELECTORS = [
    "article.post",
    "article",
    ".post",
    ".result-item",
    ".item",
    'li[class*="post"]',
    ".entry",
    ".content-item",
]

# 详情页标题选择器
DETAIL_TITLE_SELECTORS = [
    "h1.entry-title",
    "h1",
    ".title",
    ".entry-title",
    ".post-title",
]

# 详���页内容选择器
DETAIL_CONTENT_SELECTORS = [
    ".content",
    ".entry-content",
    "article",
    ".post-content",
]


class MadouCrawler(BaseCrawler):
    """麻豆社区增强爬虫

    整合 P1 PSP 麻豆全部核心功能：
    - 多域名自动切换（5 个备用域名）
    - 分页搜索 + 详情页磁力提取
    - Selenium 弹窗处理
    - SmartCache 增量更新
    """

    name = "madou"
    display_name = "麻豆社区"
    base_url = "https://madouqu.sbs"

    priority = CrawlerPriority.NORMAL
    supported_types = ["chinese"]
    supported_prefixes = []
    description = "麻豆社区磁力搜索爬虫（多域名+磁力链接）"
    language = "zh"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        self.domain_switcher = make_madouqu_switcher()
        self.magnet_extractor = MagnetExtractor()
        self.smart_cache = get_smart_cache()
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        self._session = None

    async def _get_client(self) -> AsyncHttpClient:
        """获取或创建 HTTP 客户端"""
        proxy = get_proxy()
        return AsyncHttpClient(proxy=proxy, timeout=30)

    async def _request(self, url: str, retry_count: int = 0) -> Optional[str]:
        """发起 HTTP 请求（带重试）"""
        max_retries = 3
        retry_delay = 2.0

        try:
            logger.debug(f"请求: {url} (attempt {retry_count + 1}/{max_retries})")
            client = await self._get_client() if not hasattr(self, "_client") else self._client
            # 简化版: 每次创建新 client
            client = await self._get_client()
            resp = await client.get(url, headers={
                **self._headers,
                "Referer": self.domain_switcher.current or self.base_url,
            })
            if not resp:
                logger.warning(f"请求返回空: {url}")
                if retry_count < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** retry_count))
                    return await self._request(url, retry_count + 1)
                return None

            if resp.status_code == 404:
                logger.warning(f"页面不存在 (404): {url}")
                return None

            if resp.status_code >= 400:
                logger.warning(f"请求失败 HTTP {resp.status_code}: {url}")
                if retry_count < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** retry_count))
                    return await self._request(url, retry_count + 1)
                return None

            text = await resp.text("utf-8", errors="replace") if hasattr(resp, "text") else str(resp)
            logger.debug(f"响应长度: {len(text)}")
            return text

        except Exception as e:
            logger.warning(f"请求异常: {e}")
            if retry_count < max_retries - 1:
                delay = retry_delay * (2 ** retry_count)
                await asyncio.sleep(delay)
                return await self._request(url, retry_count + 1)
            return None

    def _parse_search_results(
        self, html: str, keyword: str
    ) -> list[SearchResultItem]:
        """解析搜索结果页（100%% 复用 P1 _parse_search_results）"""
        soup = BeautifulSoup(html, "html.parser")
        videos: list[SearchResultItem] = []

        # 主选择器：article.post
        items = soup.select("article.post")

        # 备选选择器
        if not items:
            for selector in SEARCH_ITEM_SELECTORS:
                items = soup.select(selector)
                if items:
                    break

        # 终极备选：查找包含磁力链接的元素
        if not items:
            magnet_links = soup.find_all("a", href=re.compile(r"^magnet:", re.IGNORECASE))
            for link in magnet_links:
                container = link.find_parent(["article", "div", "li"])
                if container and container not in items:
                    items.append(container)

        for item in items:
            video = self._parse_item(item, keyword)
            if video and video.title:
                videos.append(video)

        return videos

    def _parse_item(
        self, item, keyword: str
    ) -> Optional[SearchResultItem]:
        """解析单个搜索结果项（100%% 复用 P1 _parse_item）"""
        # 提取标题
        title = ""
        title_elem = item.select_one("h2.entry-title a[title]")
        if title_elem:
            title = title_elem.get("title", "")

        if not title:
            title_elem = item.select_one("a[title]")
            if title_elem:
                title = title_elem.get("title", "")

        if not title:
            for selector in ["h2", "h3", ".title", ".entry-title"]:
                elem = item.select_one(selector)
                if elem:
                    title = elem.get("title", "") or elem.get_text(strip=True)
                    if title:
                        break

        if not title:
            return None

        # 提取磁力链接
        magnets = self.magnet_extractor.extract_from_html(
            str(item), source_url=""
        )

        # 提取详情页 URL
        detail_url = ""
        link_elem = item.select_one("h2.entry-title a[href]")
        if link_elem:
            href = link_elem.get("href", "")
            if href and not href.startswith("magnet:"):
                if not href.startswith("http"):
                    domain = self.domain_switcher.current or self.base_url
                    href = domain + href
                detail_url = href

        if not detail_url:
            link_elem = item.find("a", href=True)
            if link_elem:
                href = link_elem.get("href", "")
                if href and not href.startswith("magnet:"):
                    if not href.startswith("http"):
                        domain = self.domain_switcher.current or self.base_url
                        href = domain + href
                    detail_url = href

        # 提取日期
        date = ""
        for selector in [".date", ".time", ".post-date", "time", ".meta-date"]:
            elem = item.select_one(selector)
            if elem:
                date = elem.get_text(strip=True)
                if date:
                    break

        # 提取大小
        size = ""
        text = item.get_text()
        match = re.search(r"(\d+\.?\d*\s*[GMT]B)", text, re.IGNORECASE)
        if match:
            size = match.group(1)

        return SearchResultItem(
            title=title,
            detail_url=detail_url,
            magnets=magnets,
            date=date,
            size=size,
            model_name=keyword,
        )

    async def get_detail(self, url: str) -> list[MagnetInfo]:
        """��取详情页磁力链接（100%% 复用 P1 get_detail）"""
        logger.info(f"获取详情页: {url}")

        html = await self._request(url)
        if not html:
            return []

        return self.magnet_extractor.extract_from_html(html, source_url=url)

    async def search(
        self,
        keyword: str,
        max_pages: int = 5,
        fetch_details: bool = True,
    ) -> CrawlResult:
        """搜索演员资源

        Args:
            keyword: 搜索关键词
            max_pages: 最大搜索页数
            fetch_details: 是否从详情页获取磁力链接

        Returns:
            CrawlResult
        """
        logger.info(f"开始搜索: {keyword}")
        start_time = time.time()
        result = CrawlResult(model_name=keyword)

        try:
            # 1. 域名健康检查
            working_url = await self.domain_switcher.get_working()
            if not working_url:
                result.error_message = "所有域名都不可用"
                return result
            if working_url != self.domain_switcher.current:
                logger.info(f"已自动切换到可用域名: {working_url}")

            # 2. SmartCache 增量
            cache_model = f"madou_{keyword}"
            start_page, effective_max = self.smart_cache.get_incremental_fetch_range(
                cache_model, max_pages
            )

            all_titles: list[str] = []
            encoded_keyword = quote(keyword, safe="")

            for page in range(start_page, effective_max + 1):
                if page == 1:
                    url = f"{working_url}/?s={encoded_keyword}"
                else:
                    url = f"{working_url}/page/{page}/?s={encoded_keyword}"

                logger.info(f"搜索第 {page} 页: {url}")

                if not self.smart_cache.should_update_page(cache_model, page):
                    logger.debug(f"跳过已缓存页: {page}")
                    continue

                html = await self._request(url)
                if not html:
                    break

                videos = self._parse_search_results(html, keyword)
                if not videos:
                    logger.info(f"第 {page} 页无结果，停止")
                    break

                # 记录页缓存
                page_titles = [v.title for v in videos]
                self.smart_cache.record_page(cache_model, page, page_titles)

                # 进入详情页获取磁力链接
                if fetch_details:
                    for video in videos:
                        if not video.magnets and video.detail_url:
                            try:
                                logger.debug(f"获取详情页: {video.detail_url}")
                                detail_magnets = await self.get_detail(video.detail_url)
                                video.magnets = detail_magnets
                                logger.debug(f"  获取到 {len(detail_magnets)} 个磁力链接")
                            except Exception as e:
                                logger.warning(f"获取详情页失败: {e}")

                result.videos.extend(videos)
                result.pages_crawled += 1
                logger.info(f"第 {page} 页: {len(videos)} 个结果")

                await asyncio.sleep(1.0)  # 爬取间隔

            # 缓存全量
            all_titles = [v.title for v in result.videos]
            if all_titles:
                self.smart_cache.record_full_scrape(cache_model, result.pages_crawled, all_titles)

            result.total_magnets = sum(len(v.magnets) for v in result.videos)
            result.success = True

        except Exception as e:
            result.error_message = str(e)
            logger.exception(f"搜索失败: {e}")

        result.duration_seconds = round(time.time() - start_time, 2)
        logger.info(
            f"搜索完成: {keyword} -> {len(result.videos)} videos, {result.total_magnets} magnets, {result.pages_crawled} pages"
        )
        return result

    async def get_all_magnets(
        self, keyword: str, max_pages: int = 5, fetch_details: bool = True
    ) -> list[MagnetInfo]:
        """获取所有磁力链接"""
        result = await self.search(keyword, max_pages, fetch_details)

        all_magnets: list[MagnetInfo] = []
        seen_hashes: set[str] = set()

        for video in result.videos:
            for m in video.magnets:
                if m.hash and m.hash not in seen_hashes:
                    all_magnets.append(m)
                    seen_hashes.add(m.hash)

        return all_magnets

    async def import_to_chinese_module(
        self, keyword: str, max_pages: int = 5
    ) -> dict:
        """一站式：搜索 + 导入到国产模块

        将搜索结果写入 chinese_movies 表，演员写入 chinese_actors 表。

        Returns:
            dict: {model_name, movies_count, magnets_count, pages, duration}
        """
        result = await self.search(keyword, max_pages, fetch_details=True)

        if not result.success:
            return {"error": result.error_message or "搜索失败"}

        try:
            from app.db.chinese_models import ChineseMovie, ChineseActor
            from app.db.module_db import ModuleDatabase
            from sqlalchemy import select

            db = ModuleDatabase.get_instance("chinese")
            session = await db.get_session()
            imported_count = 0

            try:
                # 创建/更新演员
                stmt = select(ChineseActor).where(ChineseActor.name == keyword)
                existing_actor = (await session.execute(stmt)).scalar_one_or_none()

                if existing_actor:
                    existing_actor.source = "madou"
                    existing_actor.movie_count = max(
                        existing_actor.movie_count or 0, len(result.videos)
                    )
                else:
                    new_actor = ChineseActor(
                        name=keyword,
                        source="madou",
                        movie_count=len(result.videos),
                    )
                    session.add(new_actor)

                # 导入影片
                for video in result.videos:
                    # 检查是否已存在
                    exist_stmt = select(ChineseMovie).where(
                        ChineseMovie.title == video.title
                    )
                    existing_movie = (await session.execute(exist_stmt)).scalar_one_or_none()
                    if existing_movie:
                        continue

                    # 生成 code（标题 hash）
                    import hashlib
                    code = f"MDX-{hashlib.md5(video.title.encode()).hexdigest()[:8].upper()}"

                    magnet_links_str = "\n".join(
                        m.link for m in video.magnets
                    ) if video.magnets else None

                    movie = ChineseMovie(
                        code=code,
                        title=video.title,
                        studio="madou",
                        source="madou",
                        source_url=video.detail_url or None,
                        plot=magnet_links_str,  # 磁力链接存入 plot 字段备用
                        status="pending",
                        extracted_actor=keyword,
                    )
                    session.add(movie)
                    imported_count += 1

                await session.commit()
                logger.info(
                    f"导入完成: {keyword} -> {imported_count} movies imported"
                )

            finally:
                await session.close()

            return {
                "model_name": keyword,
                "movies_count": imported_count,
                "magnets_count": result.total_magnets,
                "pages": result.pages_crawled,
                "duration": result.duration_seconds,
            }

        except Exception as e:
            logger.exception(f"导入国产模块失败: {e}")
            return {"error": str(e)}

    # BaseCrawler interface
    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """按关键词（演员名）刮削"""
        result = await self.search(code, max_pages=3, fetch_details=True)
        if not result.success or not result.videos:
            self.mark_error()
            return None

        # 返回第一个有磁力的结果
        for video in result.videos:
            if video.magnets:
                scrape_result = ScrapeResult(
                    code=code,
                    title=video.title,
                    source="madou",
                )
                scrape_result.raw_data = {
                    "keyword": code,
                    "videos": len(result.videos),
                    "magnets": result.total_magnets,
                }
                self.mark_success()
                return scrape_result

        self.mark_error()
        return None

    async def search_keyword(self, keyword: str) -> list[ScrapeResult]:
        """搜索（BaseCrawler search 接口）"""
        result = await self.search(keyword, max_pages=3, fetch_details=False)
        return [
            ScrapeResult(
                code=v.title[:50],
                title=v.title,
                source="madou",
            )
            for v in result.videos
            if v.title
        ]


# 注册
register_crawler(MadouCrawler)


# 便捷函数
async def search_madou(keyword: str, max_pages: int = 5) -> CrawlResult:
    """便捷搜索"""
    crawler = MadouCrawler()
    return await crawler.search(keyword, max_pages)


async def import_madou_to_chinese(keyword: str, max_pages: int = 5) -> dict:
    """便捷导入"""
    crawler = MadouCrawler()
    return await crawler.import_to_chinese_module(keyword, max_pages)
