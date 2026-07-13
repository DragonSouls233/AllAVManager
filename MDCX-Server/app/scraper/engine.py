"""
刮削引擎 - 异步执行器
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Callable

from app.crawlers.base import ScrapeResult
from app.scraper.number import extract_number, NumberResult

logger = logging.getLogger(__name__)


# 缓存：crawler 类是否接受 ctx 参数（避免每次调用都 inspect）
_CTX_SUPPORT_CACHE: dict[type, bool] = {}


def _scrape_accepts_ctx(crawler) -> bool:
    """检测 crawler.scrape 方法是否接受 ctx 参数

    用于向后兼容：已迁移到新接口的 scraper 会接受 ctx，
    未迁移的旧式 scraper 会回退到无 ctx 调用。
    """
    cls = type(crawler)
    if cls not in _CTX_SUPPORT_CACHE:
        try:
            sig = inspect.signature(crawler.scrape)
            params = sig.parameters
            _CTX_SUPPORT_CACHE[cls] = "ctx" in params
        except (ValueError, TypeError):
            _CTX_SUPPORT_CACHE[cls] = False
    return _CTX_SUPPORT_CACHE[cls]


class ScrapeStatus(str, Enum):
    """刮削状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # 部分成功
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScrapeTask:
    """刮削任务"""
    id: str
    number: str
    file_path: Optional[str] = None
    status: ScrapeStatus = ScrapeStatus.PENDING
    result: Optional[ScrapeResult] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    source: Optional[str] = None  # 成功的站点


@dataclass
class ScrapeProgress:
    """刮削进度"""
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_number: Optional[str] = None
    current_source: Optional[str] = None


class ScraperEngine:
    """
    刮削引擎
    
    负责协调多个爬虫完成刮削任务：
    - 番号识别
    - 多站点并发查询
    - 结果合并
    - 失败重试
    """
    
    def __init__(
        self,
        max_concurrent: int = 5,
        timeout: int = 60,
        retry_count: int = 3,
    ):
        """
        初始化刮削引擎
        
        Args:
            max_concurrent: 最大并发数
            timeout: 单个任务超时时间（秒）
            retry_count: 失败重试次数
        """
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.retry_count = retry_count
        
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._progress = ScrapeProgress()
        self._callbacks: list[Callable] = []
    
    def add_progress_callback(self, callback: Callable) -> None:
        """添加进度回调"""
        self._callbacks.append(callback)
    
    async def _notify_progress(self) -> None:
        """通知进度更新"""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self._progress)
                else:
                    callback(self._progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    async def scrape_number(
        self,
        number: str,
        sources: Optional[list[str]] = None,
    ) -> Optional[ScrapeResult]:
        """
        刮削单个番号

        Args:
            number: 番号
            sources: 指定站点列表（None表示自动选择）

        Returns:
            ScrapeResult 刮削结果
        """
        # 获取适用的爬虫（延迟导入避免循环引用）
        from app.crawlers.provider import get_crawlers_for_number
        crawlers = get_crawlers_for_number(number)

        if sources:
            # 过滤指定站点
            crawlers = [c for c in crawlers if c.name in sources]

        if not crawlers:
            logger.warning(f"No crawler found for number: {number}")
            return None

        # 创建单次刮削共享上下文（复用 HTTP session / cookies / proxy / 指纹）
        from app.scraper.context import ScrapeContext
        async with ScrapeContext.create() as ctx:
            # 并发执行多个爬虫，共享同一 ctx
            tasks = [
                self._scrape_with_crawler(crawler, number, ctx)
                for crawler in crawlers
            ]

            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Scrape error for {number}: {e}")
                return None

        # 过滤有效结果
        valid_results = [r for r in results if isinstance(r, ScrapeResult)]

        if not valid_results:
            return None

        # 多站点结果合并（使用 merger 模块）
        if len(valid_results) > 1:
            from app.scraper.merger import merge_results
            merged = merge_results(valid_results)
            if merged:
                logger.info(f"Merged {len(valid_results)} results for {number}")
                return merged

        return valid_results[0]

    async def _scrape_with_crawler(
        self,
        crawler,
        number: str,
        ctx=None,
    ) -> Optional[ScrapeResult]:
        """使用指定爬虫刮削

        Args:
            crawler: BaseCrawler 实例
            number: 番号
            ctx: 单次刮削共享上下文（可选，向后兼容）
        """
        async with self._semaphore:
            try:
                # 检测 crawler 是否支持 ctx 参数（已迁移的 scraper 复用共享 client）
                if ctx is not None and _scrape_accepts_ctx(crawler):
                    result = await asyncio.wait_for(
                        crawler.scrape(number, ctx=ctx),
                        timeout=self.timeout,
                    )
                else:
                    # 旧式 scraper 不支持 ctx，回退到原接口
                    result = await asyncio.wait_for(
                        crawler.scrape(number),
                        timeout=self.timeout,
                    )
                return result

            except asyncio.TimeoutError:
                logger.warning(f"Crawler {crawler.name} timeout for {number}")
                return None

            except Exception as e:
                logger.error(f"Crawler {crawler.name} error for {number}: {e}")
                return None
    
    async def scrape_file(
        self,
        file_path: str,
        sources: Optional[list[str]] = None,
    ) -> Optional[ScrapeResult]:
        """
        刮削单个文件
        
        Args:
            file_path: 文件路径
            sources: 指定站点列表
            
        Returns:
            ScrapeResult 刮削结果
        """
        import os
        
        # 从文件名提取番号
        filename = os.path.basename(file_path)
        number_result = extract_number(filename)
        
        if not number_result.number:
            logger.warning(f"Cannot extract number from: {filename}")
            return None
        
        logger.info(f"Extracted number: {number_result.number} (type={number_result.number_type})")
        
        # 刮削番号
        result = await self.scrape_number(number_result.number, sources)
        
        if result:
            result.raw_data["file_path"] = file_path
            result.raw_data["number_result"] = {
                "number": number_result.number,
                "type": number_result.number_type.value,
                "confidence": number_result.confidence,
            }
        
        return result
    
    async def scrape_batch(
        self,
        numbers: list[str],
        sources: Optional[list[str]] = None,
    ) -> dict[str, Optional[ScrapeResult]]:
        """
        批量刮削番号
        
        Args:
            numbers: 番号列表
            sources: 指定站点列表
            
        Returns:
            番号 -> 结果 的映射
        """
        self._progress = ScrapeProgress(total=len(numbers))
        
        results = {}
        
        async def process_one(number: str) -> tuple[str, Optional[ScrapeResult]]:
            self._progress.current_number = number
            await self._notify_progress()
            
            result = await self.scrape_number(number, sources)
            
            self._progress.completed += 1
            if result is None:
                self._progress.failed += 1
            
            await self._notify_progress()
            
            return number, result
        
        tasks = [process_one(number) for number in numbers]
        task_results = await asyncio.gather(*tasks)
        
        for number, result in task_results:
            results[number] = result
        
        return results
    
    async def scrape_files(
        self,
        file_paths: list[str],
        sources: Optional[list[str]] = None,
    ) -> dict[str, Optional[ScrapeResult]]:
        """
        批量刮削文件
        
        Args:
            file_paths: 文件路径列表
            sources: 指定站点列表
            
        Returns:
            文件路径 -> 结果 的映射
        """
        self._progress = ScrapeProgress(total=len(file_paths))
        
        results = {}
        
        async def process_one(file_path: str) -> tuple[str, Optional[ScrapeResult]]:
            self._progress.current_number = file_path
            await self._notify_progress()
            
            result = await self.scrape_file(file_path, sources)
            
            self._progress.completed += 1
            if result is None:
                self._progress.failed += 1
            
            await self._notify_progress()
            
            return file_path, result
        
        tasks = [process_one(file_path) for file_path in file_paths]
        task_results = await asyncio.gather(*tasks)
        
        for file_path, result in task_results:
            results[file_path] = result
        
        return results
    
    @property
    def progress(self) -> ScrapeProgress:
        """获取当前进度"""
        return self._progress


# 全局引擎实例
_engine: Optional[ScraperEngine] = None


def get_scraper_engine() -> ScraperEngine:
    """获取全局刮削引擎实例"""
    global _engine
    
    if _engine is None:
        from app.config.manager import get_config
        config = get_config()
        
        _engine = ScraperEngine(
            max_concurrent=config.scraper.concurrent_limit,
            timeout=config.scraper.timeout,
            retry_count=config.scraper.retry_count,
        )
    
    return _engine
