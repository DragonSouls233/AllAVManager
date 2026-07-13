"""
爬虫插件加载器

将插件系统中的 CRAWLER 类型插件包装为 BaseCrawler 适配器，
注册到 CrawlerProvider，使其能参与多源刮削流程。

设计要点：
- 不修改现有 BaseCrawler / CrawlerProvider 代码
- 用适配器模式包装插件实例
- 支持热重载（先注销旧实例，再注册新实例）
"""

from __future__ import annotations

import logging
from typing import Optional

from app.crawlers.base import (
    BaseCrawler,
    CrawlerInfo,
    CrawlerPriority,
    CrawlerStatus,
    ScrapeResult,
)
from app.crawlers.provider import get_provider
from app.services.plugin_manager import PluginManager, PluginType, get_plugin_manager

logger = logging.getLogger(__name__)


class CrawlerPluginAdapter(BaseCrawler):
    """
    将爬虫插件实例适配为 BaseCrawler

    插件需实现：
        async def scrape(self, code: str) -> Optional[ScrapeResult]
        async def search(self, keyword: str) -> list[ScrapeResult]

    可选实现：
        def get_config_schema() -> dict
        def on_load() / on_unload() / on_enable() / on_disable()
    """

    # 基类要求子类定义类属性，这里在 __init__ 中通过 type() 动态创建子类替代
    # 但为简化，我们直接在实例上设置属性

    def __init__(self, plugin_instance):
        # 从插件 META 派生类属性
        meta = plugin_instance.META
        self.name = meta.name
        self.display_name = meta.display_name or meta.name
        self.base_url = plugin_instance.get_config("base_url", "https://example.com")
        self.priority = CrawlerPriority.LOW  # 插件默认低优先级
        self.supported_types = ["jav"]
        self.supported_prefixes = []
        self.description = meta.description
        self.language = "ja"
        self.requires_proxy = bool(plugin_instance.get_config("requires_proxy", False))

        # 必须先调用基类 __init__（设置 _status/_error_count/_success_count）
        # 注意：基类 __init__ 不依赖类属性，可在设置完实例属性后调用
        BaseCrawler.__init__(self)

        self._plugin = plugin_instance

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """调用插件的 scrape 方法"""
        try:
            result = await self._plugin.scrape(code)
            if result is not None:
                self.mark_success()
            else:
                self.mark_error()
            return result
        except Exception as e:
            self.mark_error()
            logger.error(f"插件爬虫 {self.name} 抓取 {code} 失败: {e}")
            return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """调用插件的 search 方法"""
        try:
            return await self._plugin.search(keyword)
        except Exception as e:
            logger.error(f"插件爬虫 {self.name} 搜索 {keyword} 失败: {e}")
            return []

    def get_info(self) -> CrawlerInfo:
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


# ===== 注册/注销 =====

_registered_names: set[str] = set()


def register_crawler_plugins(manager: Optional[PluginManager] = None) -> int:
    """
    扫描所有已启用的爬虫插件，包装为适配器并注册到 CrawlerProvider

    Returns:
        成功注册的插件数量
    """
    manager = manager or get_plugin_manager()
    provider = get_provider()
    count = 0

    for entry in manager.list_plugins(PluginType.CRAWLER):
        if entry.status.value != "enabled":
            continue
        try:
            adapter = CrawlerPluginAdapter(entry.instance)
            # 如果已存在同名，先注销
            if adapter.name in _registered_names:
                provider.unregister(adapter.name)
            # 直接注册实例（不通过 register(crawler_class)），通过修改 _crawlers 字典
            # provider.register 期望传入类，这里我们绕过：直接注册实例
            provider._crawlers[adapter.name] = adapter
            # 维护类型映射，让 get_for_number 能找到它
            for type_name in adapter.supported_types:
                if type_name not in provider._type_map:
                    provider._type_map[type_name] = []
                if adapter.name not in provider._type_map[type_name]:
                    provider._type_map[type_name].append(adapter.name)
            _registered_names.add(adapter.name)
            count += 1
            logger.info(f"已注册爬虫插件: {adapter.name}")
        except Exception as e:
            logger.error(f"注册爬虫插件 {entry.meta.name} 失败: {e}")

    return count


def unregister_crawler_plugin(name: str) -> bool:
    """注销单个爬虫插件"""
    provider = get_provider()
    if name not in _registered_names:
        return False
    success = provider.unregister(name)
    if success:
        _registered_names.discard(name)
    return success


def unregister_all_crawler_plugins() -> None:
    """注销所有爬虫插件（用于热重载场景）"""
    provider = get_provider()
    for name in list(_registered_names):
        provider.unregister(name)
    _registered_names.clear()


def reload_crawler_plugins() -> int:
    """热重载所有爬虫插件"""
    unregister_all_crawler_plugins()
    return register_crawler_plugins()


def init_crawler_plugins() -> int:
    """应用启动时调用：注册所有爬虫插件"""
    try:
        return register_crawler_plugins()
    except Exception as e:
        logger.error(f"初始化爬虫插件失败: {e}")
        return 0
