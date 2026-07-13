"""
翻译引擎插件加载器

将插件系统中的 TRANSLATOR 类型插件包装为 BaseTranslator 兼容实例，
使其能被 TranslateService 选择与调用。

设计要点：
- 不修改现有 translate.py 的 BaseTranslator 抽象基类
- 用适配器模式包装插件实例
- 提供按名称查找、批量翻译、回退到内置引擎的能力
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.plugin_manager import PluginManager, PluginType, get_plugin_manager
from app.utils.translate import BaseTranslator, TranslateConfig

logger = logging.getLogger(__name__)


class TranslatorPluginAdapter(BaseTranslator):
    """
    将翻译插件实例适配为 BaseTranslator

    插件需实现：
        async def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> Optional[str]
        async def translate_batch(self, texts: list[str]) -> list[Optional[str]]  # 可选
    """

    def __init__(self, plugin_instance, config: Optional[TranslateConfig] = None):
        self._plugin = plugin_instance
        self._config = config or TranslateConfig()

    async def translate(self, text: str) -> Optional[str]:
        try:
            return await self._plugin.translate(
                text,
                source_lang=self._config.source_lang,
                target_lang=self._config.target_lang,
            )
        except Exception as e:
            logger.error(f"翻译插件 {self._plugin.META.name} 失败: {e}")
            return None

    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        # 优先调用插件的批量方法（性能更好），否则回退到逐条
        if hasattr(self._plugin, "translate_batch"):
            try:
                return await self._plugin.translate_batch(texts)
            except Exception as e:
                logger.error(f"翻译插件 {self._plugin.META.name} 批量失败: {e}")
                return [None] * len(texts)
        return await super().translate_batch(texts)


# ===== 查询 =====

def list_translator_plugins(manager: Optional[PluginManager] = None) -> list[dict]:
    """列出所有翻译插件（含状态）"""
    manager = manager or get_plugin_manager()
    result = []
    for entry in manager.list_plugins(PluginType.TRANSLATOR):
        result.append({
            "name": entry.meta.name,
            "display_name": entry.meta.display_name or entry.meta.name,
            "version": entry.meta.version,
            "description": entry.meta.description,
            "enabled": entry.status.value == "enabled",
            "status": entry.status.value,
            "error": entry.error,
        })
    return result


def get_translator_adapter(
    name: str,
    config: Optional[TranslateConfig] = None,
    manager: Optional[PluginManager] = None,
) -> Optional[TranslatorPluginAdapter]:
    """根据名称获取翻译插件适配器（仅返回已启用的）"""
    manager = manager or get_plugin_manager()
    entry = manager.get_plugin(PluginType.TRANSLATOR, name)
    if entry is None or entry.status.value != "enabled":
        return None
    return TranslatorPluginAdapter(entry.instance, config)


def get_enabled_translators(
    config: Optional[TranslateConfig] = None,
    manager: Optional[PluginManager] = None,
) -> list[TranslatorPluginAdapter]:
    """获取所有已启用的翻译插件适配器"""
    manager = manager or get_plugin_manager()
    adapters = []
    for entry in manager.list_plugins(PluginType.TRANSLATOR):
        if entry.status.value != "enabled":
            continue
        adapters.append(TranslatorPluginAdapter(entry.instance, config))
    return adapters


async def translate_with_plugins(
    text: str,
    config: Optional[TranslateConfig] = None,
    prefer_plugins: bool = True,
) -> Optional[str]:
    """
    便捷函数：优先使用插件翻译，全部失败时回退到内置引擎

    Args:
        text: 待翻译文本
        config: 翻译配置（含 source_lang/target_lang）
        prefer_plugins: 是否优先使用插件

    Returns:
        译文，失败返回 None
    """
    config = config or TranslateConfig()

    if prefer_plugins:
        for adapter in get_enabled_translators(config):
            try:
                result = await adapter.translate(text)
                if result:
                    return result
            except Exception as e:
                logger.error(f"插件翻译失败: {e}")
                continue

    # 回退到内置引擎
    from app.utils.translate import TranslateService
    try:
        service = TranslateService(config)
        return await service.translate(text)
    except Exception as e:
        logger.error(f"内置翻译引擎失败: {e}")
        return None
