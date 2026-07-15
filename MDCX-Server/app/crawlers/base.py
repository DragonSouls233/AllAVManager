"""
刮削器基类和数据结构
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.scraper.context import ScrapeContext


class CrawlerStatus(str, Enum):
    """刮削器状态"""
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"  # 连续错误后自动禁用


class CrawlerPriority(int, Enum):
    """刮削器优先级（数字越小优先级越高）"""
    HIGHEST = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100
    LOWEST = 200


@dataclass
class ActorInfo:
    """演员信息"""
    name: str                           # 演员名（显示名）
    japanese_name: Optional[str] = None # 日文名
    avatar_url: Optional[str] = None    # 头像URL


@dataclass
class ScrapeResult:
    """刮削结果"""
    # 必填字段
    code: str                           # 番号
    title: str                          # 标题
    source: str                         # 来源站点名
    
    # 可选元数据
    original_title: Optional[str] = None  # 原始标题（日文/英文）
    studio: Optional[str] = None        # 制作商
    maker: Optional[str] = None         # 发行商
    label: Optional[str] = None         # 标签/系列
    series: Optional[str] = None         # 系列
    release_date: Optional[date] = None # 发行日期
    duration: Optional[int] = None      # 时长（分钟）
    
    # 内容信息
    plot: Optional[str] = None          # 简介
    genres: list[str] = field(default_factory=list)  # 类型/标签
    tags: list[str] = field(default_factory=list)    # 额外标签（区别于 genres）
    actors: list[ActorInfo] = field(default_factory=list)  # 演员列表
    all_actors: list[str] = field(default_factory=list)    # 所有演员（含男演员）
    directors: list[str] = field(default_factory=list)     # 导演列表
    is_mosaic: Optional[bool] = None    # 是否有码
    is_uncensored: Optional[bool] = None  # 是否无码
    is_chinese: Optional[bool] = None   # 是否中文字幕
    wanted: Optional[str] = None        # 想看人数
    
    # 图片资源
    cover_url: Optional[str] = None     # 封面URL
    poster_url: Optional[str] = None    # 海报URL
    trailer_url: Optional[str] = None   # 预告片URL
    sample_images: list[str] = field(default_factory=list)  # 样图URL列表
    extrafanart: list[str] = field(default_factory=list)    # 额外剧照URL列表
    
    # 评分
    rating: Optional[float] = None      # 评分 (0-10)
    votes: Optional[int] = None        # 评分人数
    
    # 原始数据（用于调试）
    raw_data: dict = field(default_factory=dict)
    
    # 元信息
    confidence: float = 1.0             # 结果置信度 (0-1)
    is_exact_match: bool = True         # 是否精确匹配
    
    def is_valid(self) -> bool:
        """检查结果是否有效"""
        return bool(self.code and self.title and self.source)
    
    def get_missing_fields(self) -> list[str]:
        """获取缺失的字段名"""
        missing = []
        if not self.plot:
            missing.append("plot")
        if not self.cover_url:
            missing.append("cover_url")
        if not self.poster_url:
            missing.append("poster_url")
        if not self.actors:
            missing.append("actors")
        if not self.genres:
            missing.append("genres")
        if not self.release_date:
            missing.append("release_date")
        if not self.duration:
            missing.append("duration")
        return missing


@dataclass
class CrawlerInfo:
    """刮削器信息"""
    name: str                           # 站点名称（唯一标识）
    display_name: str                   # 显示名称
    base_url: str                       # 站点基础URL
    priority: CrawlerPriority = CrawlerPriority.NORMAL
    status: CrawlerStatus = CrawlerStatus.ENABLED
    
    # 支持的番号类型
    supported_types: list[str] = field(default_factory=lambda: ["jav"])
    
    # 支持的番号前缀（用于自动路由）
    supported_prefixes: list[str] = field(default_factory=list)
    
    # 元信息
    description: Optional[str] = None
    language: str = "ja"                # 站点语言
    requires_proxy: bool = False        # 是否需要代理
    
    # 统计信息
    success_count: int = 0
    error_count: int = 0
    last_success: Optional[float] = None  # timestamp
    last_error: Optional[float] = None
    avg_response_time: float = 0.0


class BaseCrawler(ABC):
    """
    刮削器基类
    
    所有站点刮削器必须继承此类并实现 scrape 方法。
    """
    
    # 子类必须定义的类属性
    name: str                           # 站点名称（唯一标识）
    display_name: str                   # 显示名称
    base_url: str                       # 站点基础URL
    
    # 可选类属性
    priority: CrawlerPriority = CrawlerPriority.NORMAL
    supported_types: list[str] = ["jav"]
    supported_prefixes: list[str] = []
    description: Optional[str] = None
    language: str = "ja"
    requires_proxy: bool = False
    
    def __init__(self):
        """初始化刮削器"""
        self._status = CrawlerStatus.ENABLED
        self._error_count = 0
        self._success_count = 0
    
    @abstractmethod
    async def scrape(
        self,
        code: str,
        ctx: Optional["ScrapeContext"] = None,
    ) -> Optional[ScrapeResult]:
        """
        刮削指定番号

        Args:
            code: 番号
            ctx: 单次刮削共享上下文（可选）。若传入，scraper 应优先使用
                 ctx.http_client 而非自建 AsyncHttpClient，以复用 TLS
                 会话、浏览器指纹、cookie 池和速率限制器。

        Returns:
            ScrapeResult 刮削结果，失败返回 None
        """
        pass
    
    @abstractmethod
    async def search(self, keyword: str) -> list[ScrapeResult]:
        """
        搜索番号
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            搜索结果列表
        """
        pass
    
    async def health_check(self) -> bool:
        """
        健康检查

        Returns:
            是否健康
        """
        test_code = getattr(self, "health_check_code", None) or "TEST-001"
        try:
            result = await self.scrape(test_code)
            return True  # 能返回结果或 None 都算健康
        except Exception:
            return False
    
    def get_info(self) -> CrawlerInfo:
        """获取刮削器信息"""
        return CrawlerInfo(
            name=self.name,
            display_name=self.display_name,
            base_url=self.base_url,
            priority=self.priority,
            status=self._status,
            supported_types=self.supported_types,
            supported_prefixes=self.supported_prefixes,
            description=self.description,
            language=self.language,
            requires_proxy=self.requires_proxy,
            success_count=self._success_count,
            error_count=self._error_count,
        )
    
    def mark_success(self) -> None:
        """标记成功"""
        import time
        self._success_count += 1
        self._status = CrawlerStatus.ENABLED
    
    def mark_error(self) -> None:
        """标记错误"""
        import time
        self._error_count += 1
        # 连续错误超过阈值自动禁用
        if self._error_count >= 10 and self._success_count == 0:
            self._status = CrawlerStatus.ERROR
    
    @property
    def status(self) -> CrawlerStatus:
        """获取状态"""
        return self._status
    
    def enable(self) -> None:
        """启用"""
        self._status = CrawlerStatus.ENABLED
    
    def disable(self) -> None:
        """禁用"""
        self._status = CrawlerStatus.DISABLED
