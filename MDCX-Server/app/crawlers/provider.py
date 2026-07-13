"""
刮削器注册中心
"""

import logging
from typing import Optional, Type

from app.crawlers.base import BaseCrawler, CrawlerInfo, CrawlerStatus
from app.scraper.number import NumberType, get_number_type

logger = logging.getLogger(__name__)


class CrawlerProvider:
    """
    刮削器注册中心
    
    管理所有站点刮削器的注册、路由和调用。
    """
    
    _instance: Optional["CrawlerProvider"] = None
    
    def __new__(cls) -> "CrawlerProvider":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._crawlers: dict[str, BaseCrawler] = {}
            cls._instance._crawler_classes: dict[str, Type[BaseCrawler]] = {}
            cls._instance._prefix_map: dict[str, list[str]] = {}
            cls._instance._type_map: dict[str, list[str]] = {}
        return cls._instance
    
    def register(self, crawler_class: Type[BaseCrawler]) -> None:
        """
        注册刮削器类
        
        Args:
            crawler_class: 刮削器类（未实例化）
        """
        # 创建实例
        crawler = crawler_class()
        name = crawler.name
        
        if name in self._crawlers:
            logger.warning(f"Crawler '{name}' already registered, replacing...")
        
        # 存储实例和类
        self._crawlers[name] = crawler
        self._crawler_classes[name] = crawler_class
        
        # 构建前缀映射
        for prefix in crawler.supported_prefixes:
            if prefix not in self._prefix_map:
                self._prefix_map[prefix] = []
            if name not in self._prefix_map[prefix]:
                self._prefix_map[prefix].append(name)
        
        # 构建类型映射
        for type_name in crawler.supported_types:
            if type_name not in self._type_map:
                self._type_map[type_name] = []
            if name not in self._type_map[type_name]:
                self._type_map[type_name].append(name)
        
        logger.info(
            f"Registered crawler: {name} "
            f"(types={crawler.supported_types}, prefixes={crawler.supported_prefixes})"
        )
    
    def unregister(self, name: str) -> bool:
        """
        注销刮削器
        
        Args:
            name: 刮削器名称
            
        Returns:
            是否成功注销
        """
        if name not in self._crawlers:
            return False
        
        crawler = self._crawlers[name]
        
        # 清理前缀映射
        for prefix in crawler.supported_prefixes:
            if prefix in self._prefix_map and name in self._prefix_map[prefix]:
                self._prefix_map[prefix].remove(name)
        
        # 清理类型映射
        for type_name in crawler.supported_types:
            if type_name in self._type_map and name in self._type_map[type_name]:
                self._type_map[type_name].remove(name)
        
        # 删除刮削器
        del self._crawlers[name]
        del self._crawler_classes[name]
        
        logger.info(f"Unregistered crawler: {name}")
        return True
    
    def get(self, name: str) -> Optional[BaseCrawler]:
        """
        获取刮削器实例
        
        Args:
            name: 刮削器名称
            
        Returns:
            刮削器实例，不存在返回 None
        """
        return self._crawlers.get(name)
    
    def get_all(self) -> dict[str, BaseCrawler]:
        """获取所有刮削器"""
        return self._crawlers.copy()
    
    def get_for_number(self, number: str) -> list[BaseCrawler]:
        """
        根据番号获取适用的刮削器列表（按优先级排序）
        
        Args:
            number: 番号
            
        Returns:
            刮削器列表
        """
        # 1. 根据番号前缀匹配
        number_upper = number.upper()
        matched_names: set[str] = set()
        
        for prefix, names in self._prefix_map.items():
            if number_upper.startswith(prefix.upper()):
                matched_names.update(names)
        
        # 2. 根据番号类型匹配
        number_type = get_number_type(number)
        type_key = number_type.value
        
        if type_key in self._type_map:
            matched_names.update(self._type_map[type_key])
        
        # 3. 如果没有匹配，返回所有启用的刮削器
        if not matched_names:
            matched_names = set(
                name for name, crawler in self._crawlers.items()
                if crawler.status == CrawlerStatus.ENABLED
            )
        
        # 4. 获取实例并按优先级排序
        crawlers = [
            self._crawlers[name]
            for name in matched_names
            if name in self._crawlers and self._crawlers[name].status == CrawlerStatus.ENABLED
        ]
        
        # 按优先级排序（数字越小优先级越高）
        crawlers.sort(key=lambda c: c.priority)
        
        return crawlers
    
    def list_crawlers(self, status: Optional[CrawlerStatus] = None) -> list[CrawlerInfo]:
        """
        列出所有刮削器信息
        
        Args:
            status: 过滤状态，None 表示不过滤
            
        Returns:
            刮削器信息列表
        """
        crawlers = [
            crawler.get_info()
            for crawler in self._crawlers.values()
            if status is None or crawler.status == status
        ]
        
        # 按优先级排序
        crawlers.sort(key=lambda c: c.priority)
        return crawlers
    
    def enable(self, name: str) -> bool:
        """启用刮削器"""
        if name not in self._crawlers:
            return False
        self._crawlers[name].enable()
        return True
    
    def disable(self, name: str) -> bool:
        """禁用刮削器"""
        if name not in self._crawlers:
            return False
        self._crawlers[name].disable()
        return True
    
    def clear(self) -> None:
        """清空所有刮削器"""
        self._crawlers.clear()
        self._crawler_classes.clear()
        self._prefix_map.clear()
        self._type_map.clear()
        logger.info("Cleared all crawlers")


# ============================================
# 全局便捷函数
# ============================================

_provider = CrawlerProvider()


def register_crawler(crawler_class: Type[BaseCrawler]) -> Type[BaseCrawler]:
    """
    注册刮削器（装饰器用法）
    
    用法:
        @register_crawler
        class JavBusCrawler(BaseCrawler):
            ...
    """
    _provider.register(crawler_class)
    return crawler_class


def get_crawler(name: str) -> Optional[BaseCrawler]:
    """获取刮削器实例"""
    return _provider.get(name)


def get_crawlers_for_number(number: str) -> list[BaseCrawler]:
    """根据番号获取适用的刮削器列表"""
    return _provider.get_for_number(number)


def list_crawlers(status: Optional[CrawlerStatus] = None) -> list[CrawlerInfo]:
    """列出所有刮削器信息"""
    return _provider.list_crawlers(status)


def get_provider() -> CrawlerProvider:
    """获取全局 Provider 实例"""
    return _provider
