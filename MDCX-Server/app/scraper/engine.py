"""
刮削引擎 - 异步执行器
"""

import asyncio
import inspect
import logging
import time
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
        max_concurrent: int = 8,
        timeout: int = 60,
        retry_count: int = 3,
        sem_wait_timeout: int = 40,
        tiered: bool = True,
    ):
        """
        初始化刮削引擎
        
        Args:
            max_concurrent: 最大并发数
            timeout: 单个任务超时时间（秒）
            retry_count: 失败重试次数
            sem_wait_timeout: 等待并发信号量的超时时间（秒）。
                若 curl_cffi 等原生阻塞调用导致僵尸协程长期占着并发名额，
                后续任务最多等这么久即放弃该源，避免整批被信号量饿死。
        """
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.retry_count = retry_count
        self.sem_wait_timeout = sem_wait_timeout
        self.tiered = tiered
        
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
                logger.error(f"进度回调错误: {e}")
    
    async def scrape_number(
        self,
        number: str,
        sources: Optional[list[str]] = None,
        module: Optional[str] = None,
    ) -> Optional[ScrapeResult]:
        """
        刮削单个番号

        Args:
            number: 番号
            sources: 指定站点列表（None表示自动选择）
            module: 模块名（jav/fc2/uncensored/chinese/western/pornhub）。
                    传入时优先按模块维度选爬虫（与 sources 取交集），
                    保证 western/pornhub 模块不会误用 JAV 有码爬虫。

        Returns:
            ScrapeResult 刮削结果
        """
        # 获取适用的爬虫（延迟导入避免循环引用）
        from app.crawlers.provider import get_crawlers_for_number, get_crawlers_for_module

        if module:
            # 模块优先：只在该模块的爬虫集合内选择，避免按番号格式
            # 匹配不到时 fallback 到全部 enabled 爬虫（含 JAV）的历史 bug。
            crawlers = get_crawlers_for_module(module)
            if sources:
                allowed = set(sources)
                crawlers = [c for c in crawlers if c.name in allowed]
        else:
            crawlers = get_crawlers_for_number(number)
            if sources:
                # 过滤指定站点
                crawlers = [c for c in crawlers if c.name in sources]

        if not crawlers:
            logger.warning(f"未找到适用于番号 {number} 的爬虫（module={module}, sources={sources}）")
            return None

        # 创建单次刮削共享上下文（复用 HTTP session / cookies / proxy / 指纹）
        from app.scraper.context import ScrapeContext
        async with ScrapeContext.create() as ctx:
            valid_results = []

            # 第 0 层：主力源池轮换 —— 按番号错开首选源，命中即返回。
            # 多数番号只需 1 个请求 → 各主站请求量摊薄到约 1/N，避免被限流。
            # 依次补试其余主力：不牺牲成功率，只是把「主力全未命中」留给备用池。
            primary, rest = self._split_primary(crawlers)
            if primary:
                for crawler in self._rotate_primary(primary, number):
                    valid_results += await self._gather_all([crawler], number, ctx)
                    merged = self._merge_results(valid_results, crawlers, number)
                    if merged is not None and self._is_complete(merged):
                        return merged

            # 第 1 层：备用源池 —— 主力全部未命中时才启用
            fallback, tier2 = self._split_fallback(rest)
            if fallback:
                valid_results += await self._gather_all(fallback, number, ctx)
                merged_fb = self._merge_results(valid_results, crawlers, number)
                if merged_fb is not None and self._is_complete(merged_fb):
                    return merged_fb

            # 第 2 层：其余源兜底
            if tier2:
                valid_results += await self._gather_all(tier2, number, ctx)

        # 过滤有效结果
        valid_results = [r for r in valid_results if isinstance(r, ScrapeResult)]

        if not valid_results:
            return None

        # 多站点结果合并（使用 merger 模块）
        if len(valid_results) > 1:
            merged = self._merge_results(valid_results, crawlers, number)
            if merged is not None:
                return merged

        return valid_results[0]

    # ── 源池分层（2026-09-30 依据【真实数据实测】选定，非拍脑袋）──────────────
    # 实测方法：从 jav.db（9380 部）按前缀随机抽 40 个真实番号
    #   （素人 SIRO/GANA/MAAN/LUXU/MIUM + 有码大厂 SSIS/SONE/MIDV 各 5 个），
    #   逐源真跑 scrape() 记录「命中率 + 字段完整度 + 耗时」。
    #
    # ① 主力源池 4 个 —— **轮换错开使用**：按番号分散首选源，使每站只承担约 1/4
    #    请求量，避免任一站点被限流；四者互为独立上游，互不牵连。实测命中率：
    #      javdb   40/40 (官方 App 协议, jdforrepam.com, 匿名 jdsignature, 绕 CF) ★官方
    #      javmenu 40/40 (素人 5/5 满分 —— 本轮实测新发现的最佳源)
    #      javmost 36/40
    #      javbus  25/40 (有码大厂专精；素人 GANA/LUXU/MIUM 全场 0/5 → 故不入首选)
    # ② 备用源池 6 个 —— 主力全部未命中时才启用，偏素人 + 字段完整度补齐。
    #    实测：thejavdb / javplace 命中即「标题+封面+演员+简介」全齐(avgW 4.0)，
    #    但覆盖率偏低（26/40、21/40）→ 适合做补字段而非首选。
    #
    # ⚠️ 命名陷阱（易踩）：`javdbapi`（display_name=TheJavDB (API)）**不是** JavDB App 的 API，
    #    它是第三方开放 JSON API（https://api.thejavdb.net/v1，移植自 Kesuy/mdcx ref42），
    #    与 JavDB 官方 App 无关；`dmm_api` 也挂在同一第三方站点。
    #
    # ⚠️ 曾把 10 个源全塞进 TIER1 → 每片至少并发 10 源，与补刮并发(12)相乘
    #    远超全局爬虫名额 → 信号量饥饿丢源。
    PRIMARY_CRAWLERS = ("javdb", "javmenu", "javmost", "javbus")

    FALLBACK_CRAWLERS = (
        "thejavdb",      # 第三方开放 API —— 命中即字段全(avgW 4.0)
        "javplace",      # JavPlace —— 命中即字段全(avgW 4.0)，覆盖率低
        "javdb_new",     # JavDB (新版) —— 同一 App 通道，App 侧兜底
        "freejavbt",     # FreeJavBT —— 31/40
        "mmtv",          # MMTV —— 素人有覆盖
        "javdatabase",   # JavDatabase 权威数据库 —— 有码专精
    )

    # 兼容保留：旧「第一梯队」概念已由 PRIMARY / FALLBACK 池取代
    TIER1_CRAWLERS = set(PRIMARY_CRAWLERS) | set(FALLBACK_CRAWLERS)

    def _split_primary(self, crawlers: list) -> tuple[list, list]:
        """拆出主力源池与其余源"""
        if not self.tiered:
            return [], list(crawlers)
        p = [c for c in crawlers if c.name in self.PRIMARY_CRAWLERS]
        rest = [c for c in crawlers if c.name not in self.PRIMARY_CRAWLERS]
        return p, rest

    def _split_fallback(self, crawlers: list) -> tuple[list, list]:
        """拆出备用源池与其余源"""
        if not self.tiered:
            return [], list(crawlers)
        fb = [c for c in crawlers if c.name in self.FALLBACK_CRAWLERS]
        rest = [c for c in crawlers if c.name not in self.FALLBACK_CRAWLERS]
        return fb, rest

    def _rotate_primary(self, primary: list, number: str) -> list:
        """主力源轮换排序：按番号错开首选源。

        同一起点 → 同一番号总是先试同一个源（可复现、便于排查）；
        不同番号分散到不同主站，使每站请求量约为总量的 1/3，避免被限流。
        """
        names = list(self.PRIMARY_CRAWLERS)
        by_name = {c.name: c for c in primary}
        n = max(1, len(names))
        start = sum(ord(ch) for ch in str(number or "")) % n
        ordered = [
            by_name[names[(start + i) % n]]
            for i in range(n)
            if names[(start + i) % n] in by_name
        ]
        return ordered or list(primary)

    def _split_tiers(self, crawlers: list) -> tuple[list, list]:
        """按命中率把爬虫分为 (第一梯队, 其余)"""
        if not self.tiered:
            return [], list(crawlers)
        t1 = [c for c in crawlers if c.name in self.TIER1_CRAWLERS]
        t2 = [c for c in crawlers if c.name not in self.TIER1_CRAWLERS]
        if not t1 or not t2:
            return [], list(crawlers)
        return t1, t2

    async def _gather_all(self, crawlers: list, number: str, ctx) -> list:
        """并发执行一批爬虫，返回有效结果列表"""
        try:
            results = await asyncio.gather(
                *[self._scrape_with_crawler(c, number, ctx) for c in crawlers],
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"刮削 {number} 失败: {e}")
            return []
        return [r for r in results if isinstance(r, ScrapeResult)]

    @staticmethod
    def _is_complete(result) -> bool:
        """结果是否足够完整（标题 + 封面 + 演员）：完整即可跳过剩余低命中源"""
        return bool(result.title and result.cover_url and result.actors)

    def _merge_results(self, valid_results: list, crawlers: list, number: str):
        """按实际生效的爬虫优先级合并结果

        用实际生效的爬虫优先级动态构建合并优先级，使「站点优先级」界面
        保存的设置真实作用于最终来源选择（默认表仅兜底未注册来源）。
        """
        if not valid_results:
            return None
        if len(valid_results) == 1:
            return valid_results[0]

        from app.scraper.merger import MergeConfig, merge_results
        from app.crawlers.provider import get_provider

        provider = get_provider()
        base_cfg = MergeConfig()
        source_priority = dict(base_cfg.source_priority)
        for crawler in crawlers:
            source_priority[crawler.name] = provider.effective_priority(crawler)

        merged = merge_results(valid_results, config=MergeConfig(source_priority=source_priority))
        if merged:
            logger.info(f"已合并 {len(valid_results)} 个爬虫结果为番号 {number}")
            return merged
        return None

    async def _scrape_with_crawler(
        self,
        crawler,
        number: str,
        ctx=None,
    ) -> Optional[ScrapeResult]:
        """使用指定爬虫刮削

        信号量获取改为可超时（wait_for acquire）：curl_cffi 原生阻塞等无法协作
        取消的调用可能让僵尸协程长期占着并发名额，导致后续 scrape 在
        `async with self._semaphore` 永久等待（表现为批量任务运行一段时间后
        进度冻结且无任何日志）。这里最多等 sem_wait_timeout 秒即放弃该源。
        """
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(), timeout=self.sem_wait_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"信号量等待超时 {self.sem_wait_timeout}s，放弃爬虫 "
                f"{crawler.name} 刮削 {number}"
            )
            return None
        try:
            started = time.monotonic()
            logger.info(f"爬虫 {crawler.name} 开始刮削 {number}")
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
                logger.info(
                    f"爬虫 {crawler.name} 刮削 {number} 完成，耗时 "
                    f"{time.monotonic() - started:.1f}s"
                )
                return result

            except asyncio.TimeoutError:
                logger.warning(
                    f"爬虫 {crawler.name} 刮削 {number} 超时 "
                    f"({self.timeout}s，耗时 {time.monotonic() - started:.1f}s)"
                )
                return None

            except Exception as e:
                logger.error(
                    f"爬虫 {crawler.name} 刮削 {number} 出错: "
                    f"{type(e).__name__}: {e}"
                )
                return None
        finally:
            self._semaphore.release()
    
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
            logger.warning(f"无法从文件名中提取番号: {filename}")
            return None
        
        logger.info(f"已提取番号: {number_result.number} (类型={number_result.number_type})")
        
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
        started = time.monotonic()
        logger.info(f"批量刮削开始: 共 {len(numbers)} 个番号 (sources={sources})")
        
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

        ok = sum(1 for v in results.values() if v is not None)
        logger.info(
            f"批量刮削完成: 共 {len(numbers)} 个，成功 {ok}，失败 {len(numbers) - ok}，"
            f"耗时 {time.monotonic() - started:.1f}s"
        )
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
        started = time.monotonic()
        logger.info(f"批量刮削文件开始: 共 {len(file_paths)} 个文件 (sources={sources})")
        
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

        ok = sum(1 for v in results.values() if v is not None)
        logger.info(
            f"批量刮削文件完成: 共 {len(file_paths)} 个，成功 {ok}，失败 {len(file_paths) - ok}，"
            f"耗时 {time.monotonic() - started:.1f}s"
        )
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
