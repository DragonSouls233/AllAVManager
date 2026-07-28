"""
统一爬虫适配器基类

参考 VaultX 的 JavBaseAdapter/PornBaseAdapter 抽象设计模式。
提供标准化的刮削生命周期，降低新增站点适配成本。

用法：
1. 继承 BaseCrawlAdapter 实现具体站点的适配器
2. 注册到 PROVIDER 注册表
3. 由引擎自动调度
"""
import abc
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class CrawlItem:
    """统一的刮削结果数据项"""
    code: str = ""
    title: str = ""
    original_title: str = ""
    actors: List[str] = field(default_factory=list)
    studio: str = ""
    maker: str = ""
    series: str = ""
    release_date: str = ""
    duration: str = ""
    rating: str = ""
    genres: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    cover_url: str = ""
    extrafanart: List[str] = field(default_factory=list)
    plot: str = ""
    year: str = ""
    source: str = "unknown"


@dataclass
class CrawlRequest:
    """统一爬取请求"""
    code: str
    url: Optional[str] = None
    file_path: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)


class CrawlAdapterError(Exception):
    """爬虫适配器基类异常"""
    pass


class BaseCrawlAdapter(abc.ABC):
    """
    统一爬虫适配器基类

    子类必须实现:
    - name: 适配器名称
    - scrape(): 核心爬取方法

    子类可覆盖:
    - setup() / teardown(): 生命周期钩子
    - batch_scrape(): 批量爬取（默认单次循环调用 scrape）
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """适配器名称（唯一标识）"""
        pass

    @property
    def priority(self) -> int:
        """优先级（数字越小越优先），默认 100"""
        return 100

    @property
    def supported_urls(self) -> List[str]:
        """支持的 URL 模式列表"""
        return []

    @property
    def supported_codes(self) -> List[str]:
        """支持的番号正则模式列表"""
        return []

    async def setup(self):
        """初始化钩子（如创建 HTTP 客户端）"""
        pass

    async def teardown(self):
        """清理钩子（如关闭连接池）"""
        pass

    async def can_handle(self, code: str) -> bool:
        """检查此适配器是否能处理指定番号"""
        if not self.supported_codes:
            return True
        import re
        for pattern in self.supported_codes:
            if re.match(pattern, code, re.I):
                return True
        return False

    @abc.abstractmethod
    async def scrape(self, request: CrawlRequest) -> Optional[CrawlItem]:
        """核心爬取方法"""
        pass

    async def batch_scrape(self, requests: List[CrawlRequest],
                           concurrency: int = 3) -> List[Optional[CrawlItem]]:
        """批量爬取（默认：信号量限制并发）"""
        import asyncio
        sem = asyncio.Semaphore(concurrency)

        async def _limited(req):
            async with sem:
                return await self.scrape(req)

        tasks = [_limited(req) for req in requests]
        return await asyncio.gather(*tasks)


class ResultMerger:
    """多源结果精选合并器

    参考 JavBoss 的多来源数据精选逻辑。
    当多个爬虫返回同一番号的元数据时，自动合并最优字段。
    """

    @staticmethod
    def merge(items: List[CrawlItem]) -> CrawlItem:
        """从多个结果中合并最优字段"""
        if not items:
            raise CrawlAdapterError("No items to merge")

        best = items[0]

        for item in items[1:]:
            if not best.title and item.title:
                best.title = item.title
            if not best.cover_url and item.cover_url:
                best.cover_url = item.cover_url
            if not best.studio and item.studio:
                best.studio = item.studio
            if not best.maker and item.maker:
                best.maker = item.maker
            if not best.series and item.series:
                best.series = item.series
            if not best.plot and item.plot:
                best.plot = item.plot
            if not best.release_date and item.release_date:
                best.release_date = item.release_date
            if not best.duration and item.duration:
                best.duration = item.duration
            if not best.rating and item.rating:
                best.rating = item.rating

            best.genres = list(dict.fromkeys(best.genres + item.genres))
            best.tags = list(dict.fromkeys(best.tags + item.tags))
            best.extrafanart = list(dict.fromkeys(best.extrafanart + item.extrafanart))

            best.actors = list(dict.fromkeys(best.actors + item.actors))

        return best


class AggregateSearchEngine:
    """聚合搜索引擎

    参考 javapi 的多源并发抓取 + 优雅降级设计。
    同时调度多个适配器搜索同一番号，自动合并最优结果。
    """

    def __init__(self, adapters: List[BaseCrawlAdapter] = None):
        self.adapters = adapters or []

    def register(self, adapter: BaseCrawlAdapter):
        self.adapters.append(adapter)

    def register_many(self, adapters: List[BaseCrawlAdapter]):
        self.adapters.extend(adapters)

    async def search(self, code: str, items: List[CrawlItem] = None) -> CrawlItem:
        """多源并发搜索，自动合并最优结果"""
        if items:
            return ResultMerger.merge(items)

        request = CrawlRequest(code=code)
        results = []

        for adapter in self.adapters:
            if not await adapter.can_handle(code):
                continue
            try:
                result = await adapter.scrape(request)
                if result and result.title:
                    results.append(result)
            except Exception as e:
                logger.warning(f"AggregateSearch: {adapter.name} failed for {code}: {e}")

        if not results:
            raise CrawlAdapterError(f"No adapter could scrape {code}")

        return ResultMerger.merge(results)

    async def search_all(self, codes: List[str],
                         concurrency: int = 5) -> Dict[str, CrawlItem]:
        """批量搜索多个番号"""
        import asyncio
        sem = asyncio.Semaphore(concurrency)

        async def _search(code):
            async with sem:
                try:
                    item = await self.search(code)
                    return code, item
                except Exception as e:
                    logger.warning(f"AggregateSearch: {code} failed: {e}")
                    return code, None

        tasks = [_search(code) for code in codes]
        results = await asyncio.gather(*tasks)
        return {code: item for code, item in results if item is not None}
