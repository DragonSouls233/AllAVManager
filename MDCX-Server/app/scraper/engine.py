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
from app.scraper import canon as _canon
from app.scraper.breaker import get_breaker
from app.scraper.failure_reason import FailureAggregator
from app.scraper.number import extract_number, NumberResult
from app.scraper.recorder import get_recorder

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
        # 2026-10-04：失败原因分级聚合。此前所有异常统一 return None，
        # 只留一行日志，上层无法区分「网络抖动（该重试）」与
        # 「站点无此资源（换源即可）」，也无法按原因给失败源降权。
        self.failures = FailureAggregator()
        # 2026-10-04：把每次尝试（含成功）落到 scrape_attempts 表。
        # 此前 failures 只在内存里，failure_summary() 全仓零调用方，
        # 且**成功次数压根没记** ⇒ 无法算成功率，也就看不出「哪个源在拖后腿」。
        self.recorder = get_recorder()

    def failure_summary(self) -> dict:
        """任务级失败健康度（按源 × 原因），供 API / 日志 / 运维查看。"""
        return self.failures.as_dict()

    def reset_failures(self) -> None:
        self.failures.reset()
    
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
                    valid_results += await self._gather_all([crawler], number, ctx, module)
                    merged = self._merge_results(valid_results, crawlers, number)
                    if merged is not None and self._is_complete(merged):
                        return merged

            # 第 1 层：备用源池 —— 主力全部未命中时才启用
            fallback, tier2 = self._split_fallback(rest)
            if fallback:
                valid_results += await self._gather_all(fallback, number, ctx, module)
                merged_fb = self._merge_results(valid_results, crawlers, number)
                if merged_fb is not None and self._is_complete(merged_fb):
                    return merged_fb

            # 第 2 层：其余源兜底
            if tier2:
                valid_results += await self._gather_all(tier2, number, ctx, module)

        # 过滤有效结果
        # 🔴 2026-10-04：原来只判 `isinstance(r, ScrapeResult)` —— 任何**非 None 的
        # 对象**都被当成有效结果，包括「有对象但无实质内容」的空壳：
        # 实测里番 DV-109，源返回 title="猜你喜欢"（推荐区块文案）+
        # duration=67（页面里别的条目的时长）⇒ 一路返回并落库，库里出现
        # 标题为「猜你喜欢」的垃圾记录，且该源被记为健康、永不熔断。
        # `is_valid()` = code + source + has_content()，与 patcher 侧同口径。
        # 这里过滤掉，engine 才会继续尝试后续源，而不是把垃圾当命中返回。
        valid_results = [
            r for r in valid_results
            if isinstance(r, ScrapeResult) and r.is_valid()
        ]

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
    #
    # 🔴 2026-10-05 用户指定：**主力源 = JavDB API**。
    #   ⚠️ 命名陷阱：`javdb` 才是 JavDB **官方 App API**（内部 `_scrape_via_app_api`，
    #   匿名 jdsignature 绕 CF）；`thejavdb` 是第三方 api.thejavdb.net，与官方无关。
    #   所以主力池首位是 `javdb`（官方 API），`thejavdb` 回备用池首位。
    #   实测依据：带数字的素人番号（200GANA-3426 / 259LUXU-1602 / 300MIUM-1437 /
    #   348NTR-059）经官方 API 命中，series/studio/label 齐全。
    #   `_rotate_primary` 会按番号轮换首选源，放首位≠每片都只打它，仍能摊薄限流。
    #
    # 🔴 2026-10-05 用户决定：**DMM/FANZA 加入主力**（数据已实测打通，
    #   端点 `api.video.dmm.co.jp/graphql`，真实番号 6/6 命中）。
    #   但它**固定排在尾部、不参与首选轮换**（见 `JP_TAIL_CRAWLERS`）：
    #   前 4 个源命中即返回，走不到它；只有主力全未命中才付这 ~70s 的日本节点时延。
    #   若让它进轮换池，按番号错开后会有 ~1/5 的片子**首选就打 DMM**，
    #   白等 70s 换一份与 javdb 重叠的数据。
    PRIMARY_CRAWLERS = ("javdb", "javmenu", "javmost", "javbus", "dmm_web")

    #: 主力池内但**固定排尾部**的源：不参与 `_rotate_primary` 的首选轮换，
    #: 只在主力前序全部未给出完整结果时才被调用。
    #: 判定标准 = 走昂贵/高时延链路（需日本出口），而字段与前序源高度重叠。
    JP_TAIL_CRAWLERS = ("dmm_web",)

    #: 备用源池 = canon 的 ``AUX_SOURCE_ORDER``。
    #:
    #: 🔴 2026-10-05 起**直接复用 canon**，不再在这里写死第二份。旧实现写死
    #:    6 源元组，与 canon 各维护一份，漂移出两类问题：
    #:      ① canon 序里有而这里没有的（avmoo）→ 被降级到 tier2，canon 把它排在
    #:         辅助序前列、engine 却最后才试，源序意图被抵消；
    #:      ② 这里有而 canon 没有的（javplace / javdb_new / javdatabase）
    #:         → canon 序（缺口补全页、NFO 缓存重建页）根本看不到这些源。
    #:    实测（SSIS-001 逐源真跑）已剔除死源 **javbooks / mmtv**：
    #:    ``scrape()`` 返回 None（既非超时也非 CF 403），留着只会让未命中的
    #:    片子白等两次超时。
    #:
    #: canon 是纯常量模块（只定义顺序元组与两个纯函数），此处 import 无循环依赖。
    FALLBACK_CRAWLERS = _canon.AUX_SOURCE_ORDER

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

        🔴 2026-10-05：**素人走素人源序**（canon.source_order_for）。
        实测 javbus 对素人 0/5 命中（它只做有码大厂），而 javmenu 素人 5/5 ——
        统一源序会让素人片白跑一轮再落到低覆盖的源。素人/有码各用各的顺序。
        """
        from app.scraper.canon import source_order_for

        by_name = {c.name: c for c in primary}
        # 🔴 2026-10-08 回归缺陷：**轮换完全失效**。
        # 旧实现 `ordered = preferred + rotated + tail`，而 `preferred` 是 canon
        # 的**完整源序**（如 javdb/javbus/javmenu 全部）—— 它永远排在 rotated 之前，
        # 执行到 `ordered[0]` 时恰好始终是 preferred[0]（=javdb）。
        # 实测：20 个不同番号全部首选 javdb（应分散到 3 个源）
        # ↳ javdb 承受 100% 请求，容易被限流；轮换的负载均衡目的不到达。
        #
        # 修法：preferred 只用作「轮换池成员集合」，不再直接置顶。
        # 轮换序由 PRIMARY_CRAWLERS 按番号哈希决定，所有主力源都有机会当首选。
        preferred = [n for n in source_order_for(number) if n in by_name]
        # 哈希基础用 preferred 的长度（保持与 canon 序一致的均摊算法）
        _pool = [n for n in self.PRIMARY_CRAWLERS if n not in self.JP_TAIL_CRAWLERS]
        _base = preferred if len(preferred) == len(_pool) else _pool
        _base = [n for n in _base if n in by_name]
        # 🔴 固定尾部源（JP_TAIL_CRAWLERS）**不进轮换池**：轮换是「按番号错开
        # 首选源」的负载均衡手段，而日本节点单部 ~70s，让它参与轮换等于有 1/N
        # 的片子第一枪就打在最慢的源上。它只应作为前序全未命中后的兜底。
        rest_names = _base
        n = max(1, len(rest_names))
        start = sum(ord(ch) for ch in str(number or "")) % n
        rotated = [
            rest_names[(start + i) % n]
            for i in range(n)
            if rest_names[(start + i) % n] in by_name
        ]
        # 尾部源永远接在轮换序列之后
        tail = [n2 for n2 in source_order_for(number)
                if n2 in self.JP_TAIL_CRAWLERS and n2 in by_name]
        ordered: list = []
        # 🔴 轮换序列在前（负载均衡的实际执行序），preferred 只用于**补齐**
        # 轮换池没覆盖到的源，避免遗漏；两者用 seen 去重。
        for name in rotated + preferred + tail:
            if name in by_name and name not in [c.name for c in ordered]:
                ordered.append(by_name[name])
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

    async def _gather_all(
        self, crawlers: list, number: str, ctx, module: Optional[str] = None
    ) -> list:
        """并发执行一批爬虫，返回有效结果列表"""
        try:
            results = await asyncio.gather(
                *[self._scrape_with_crawler(c, number, ctx, module) for c in crawlers],
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
        module: Optional[str] = None,
    ) -> Optional[ScrapeResult]:
        """使用指定爬虫刮削

        信号量获取改为可超时（wait_for acquire）：curl_cffi 原生阻塞等无法协作
        取消的调用可能让僵尸协程长期占着并发名额，导致后续 scrape 在
        `async with self._semaphore` 永久等待（表现为批量任务运行一段时间后
        进度冻结且无任何日志）。这里最多等 sem_wait_timeout 秒即放弃该源。
        """
        # 🔴 熔断检查必须在**信号量 acquire 之前**。
        # 放在之后的话，熔断虽然省了网络请求，却仍占着并发名额等满
        # sem_wait_timeout 秒 —— 并发 24 时若前排全是熔断源，整批照样卡死。
        # 命中熔断 = 零开销返回，不占名额、不发请求、不写观测记录
        # （写记录会让熔断器把自己的短路当成"又失败一次"，冷却期无限延长）。
        breaker = get_breaker()
        verdict = await breaker.check_persisted(crawler.name)
        if verdict.should_skip:
            logger.info(
                f"爬虫 {crawler.name} 处于熔断中（{verdict.reason}，"
                f"剩余 {verdict.cooldown:.0f}s），跳过刮削 {number}"
            )
            return None

        try:
            await asyncio.wait_for(
                self._semaphore.acquire(), timeout=self.sem_wait_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"信号量等待超时 {self.sem_wait_timeout}s，放弃爬虫 "
                f"{crawler.name} 刮削 {number}"
            )
            # 本地并发问题，不是源的锅⇒ 记local 类原因，不降权该源
            self.recorder.record_failure(
                TimeoutError(
                    f"信号量等待超时 {self.sem_wait_timeout}s（本地并发耗尽）"
                ),
                source=crawler.name,
                number=number,
                module=module,
                duration_ms=int(self.sem_wait_timeout * 1000),
            )
            self.failures.record_any(
                f"semaphore wait timeout after {self.sem_wait_timeout}s",
                source=crawler.name,
                number=number,
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
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if result is None:
                    # 无异常但无结果：部分源对不存在的资源会返回「非常抱歉…」页面并
                    # 当成功解析（见 fc2 源），这类必须记为 no_resource 而不是 unknown，
                    # 否则会把「站点确认没有」和「站点临时挂了」混在一起统计。
                    info = self.failures.record_any(
                        None, source=crawler.name, number=number
                    )
                    self.recorder.record_failure(
                        None, source=crawler.name, number=number,
                        module=module, duration_ms=elapsed_ms,
                    )
                    breaker.record_failure(
                        crawler.name, info.reason.value
                    )
                else:
                    # 🔴 成功也必须记：只有失败数就算不出成功率，
                    # 「试了10次成1次」与「试了1000次成900次」在统计上无法区分。
                    self.recorder.record_success(
                        crawler.name, number,
                        module=module, duration_ms=elapsed_ms,
                    )
                    # 半开闭合：源确认恢复，清零退避
                    breaker.record_success(crawler.name)
                return result

            except asyncio.TimeoutError:
                logger.warning(
                    f"爬虫 {crawler.name} 刮削 {number} 超时 "
                    f"({self.timeout}s，耗时 {time.monotonic() - started:.1f}s)"
                )
                tinfo = self.failures.record_any(
                    f"scrape timeout after {self.timeout}s",
                    source=crawler.name,
                    number=number,
                )
                self.recorder.record_failure(
                    TimeoutError(f"scrape timeout after {self.timeout}s"),
                    source=crawler.name, number=number, module=module,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                # 超时属瞬时故障 ⇒ 短冷却，避免一次网络抖动就下线好源
                breaker.record_failure(crawler.name, tinfo.reason.value)
                return None

            except Exception as e:
                logger.error(
                    f"爬虫 {crawler.name} 刮削 {number} 出错: "
                    f"{type(e).__name__}: {e}"
                )
                self.recorder.record_failure(
                    e, source=crawler.name, number=number, module=module,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                info = self.failures.record_any(
                    e, source=crawler.name, number=number
                )
                breaker.record_failure(crawler.name, info.reason.value)
                # 拦截类与永久失败要显式提示：这类重试同一源无意义，应换源
                if info.is_blocking or info.is_permanent:
                    logger.warning(
                        f"爬虫 {crawler.name} 对 {number} 判定为 "
                        f"{info.reason.value}（{info.matched_rule}），"
                        f"换源继续；本源建议降权"
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
