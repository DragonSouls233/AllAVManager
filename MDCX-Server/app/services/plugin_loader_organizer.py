"""
整理规则插件加载器

将插件系统中的 ORGANIZER 类型插件暴露给整理流程使用。
插件实现 organize(file_path, metadata) -> new_path 方法。

设计要点：
- 不修改现有 FileOrganizer 代码
- 提供链式调用：内置整理器 → 插件整理器
- 优先级由插件加载顺序决定
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.services.plugin_manager import PluginManager, PluginType, get_plugin_manager

logger = logging.getLogger(__name__)


def list_organizer_plugins(manager: Optional[PluginManager] = None) -> list[dict]:
    """列出所有整理规则插件"""
    manager = manager or get_plugin_manager()
    result = []
    for entry in manager.list_plugins(PluginType.ORGANIZER):
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


def get_organizer_instance(name: str, manager: Optional[PluginManager] = None):
    """根据名称获取整理插件实例（仅返回已启用的）"""
    manager = manager or get_plugin_manager()
    entry = manager.get_plugin(PluginType.ORGANIZER, name)
    if entry is None or entry.status.value != "enabled":
        return None
    return entry.instance


def get_enabled_organizers(manager: Optional[PluginManager] = None) -> list:
    """获取所有已启用的整理插件实例"""
    manager = manager or get_plugin_manager()
    return [
        e.instance for e in manager.list_plugins(PluginType.ORGANIZER)
        if e.status.value == "enabled"
    ]


def organize_with_plugins(
    file_path: str,
    metadata: dict,
    plugin_name: Optional[str] = None,
    manager: Optional[PluginManager] = None,
) -> Optional[str]:
    """
    使用整理插件整理文件

    Args:
        file_path: 原文件路径
        metadata: 元数据 dict
        plugin_name: 指定插件名，None 则依次尝试所有已启用插件

    Returns:
        新文件路径，全部失败返回 None
    """
    manager = manager or get_plugin_manager()

    if plugin_name:
        instance = get_organizer_instance(plugin_name, manager)
        if instance is None:
            logger.warning(f"整理插件不存在或未启用: {plugin_name}")
            return None
        instances = [instance]
    else:
        instances = get_enabled_organizers(manager)

    if not instances:
        logger.info("无已启用的整理插件，跳过")
        return None

    current_path = file_path
    for inst in instances:
        try:
            new_path = inst.organize(current_path, metadata)
            if new_path:
                current_path = new_path
                logger.info(f"插件 {inst.META.name} 整理完成: {current_path}")
            else:
                logger.warning(f"插件 {inst.META.name} 整理失败（返回 None）")
        except Exception as e:
            logger.error(f"插件 {inst.META.name} 整理异常: {e}")

    return current_path if current_path != file_path else None
