"""
插件系统核心

提供插件基类、注册表、加载器、生命周期管理。
所有大功能独立 .py 文件，避免臃肿。

插件目录布局：
    data/plugins/
        crawlers/        # 爬虫插件
        translators/     # 翻译引擎插件
        organizers/      # 整理规则插件
        notifiers/       # 通知器插件（可选，内置已够用）
        config.json      # 插件全局配置

每个插件是一个 .py 文件，必须导出 `Plugin` 类（继承自 PluginBase）。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ===== 插件类型枚举 =====

class PluginType(str, Enum):
    """插件类型"""
    CRAWLER = "crawler"          # 爬虫插件
    TRANSLATOR = "translator"    # 翻译引擎插件
    ORGANIZER = "organizer"      # 整理规则插件
    NOTIFIER = "notifier"        # 通知器插件


class PluginStatus(str, Enum):
    """插件状态"""
    LOADED = "loaded"            # 已加载
    ENABLED = "enabled"          # 已启用
    DISABLED = "disabled"        # 已禁用
    ERROR = "error"              # 加载/运行错误


# ===== 插件元数据 =====

@dataclass
class PluginMeta:
    """插件元数据"""
    name: str                            # 唯一标识（与文件名一致，不含 .py）
    plugin_type: PluginType              # 插件类型
    display_name: str = ""               # 显示名称
    version: str = "0.1.0"               # 版本
    author: str = ""                     # 作者
    description: str = ""                # 描述
    homepage: str = ""                   # 主页
    requires: list[str] = field(default_factory=list)  # 依赖的 Python 包

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "plugin_type": self.plugin_type.value,
        }


# ===== 插件基类 =====

class PluginBase(ABC):
    """
    所有插件的根基类

    子类必须设置类属性：
        META: PluginMeta

    可选重写：
        on_load(self) -> None       # 加载时调用
        on_unload(self) -> None     # 卸载时调用
        on_enable(self) -> None     # 启用时调用
        on_disable(self) -> None    # 禁用时调用
        get_config_schema(self) -> dict  # 返回配置 schema（JSON Schema 格式）
    """

    META: PluginMeta  # 子类必须定义

    def __init__(self):
        self._config: dict[str, Any] = {}
        self._manager: Optional["PluginManager"] = None

    # ===== 配置 =====

    def get_config(self, key: str = "", default: Any = None) -> Any:
        """获取配置项；key 为空时返回全部配置"""
        if not key:
            return self._config
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        """更新配置项（仅内存，持久化由管理器统一处理）"""
        self._config[key] = value

    def update_config(self, data: dict) -> None:
        """批量更新配置"""
        self._config.update(data or {})

    # ===== 生命周期钩子（子类可选实现） =====

    def on_load(self) -> None:
        """加载时调用（一次）"""

    def on_unload(self) -> None:
        """卸载时调用（一次）"""

    def on_enable(self) -> None:
        """启用时调用"""

    def on_disable(self) -> None:
        """禁用时调用"""

    def get_config_schema(self) -> dict:
        """返回 JSON Schema 格式的配置描述（用于前端动态表单）"""
        return {
            "type": "object",
            "properties": {},
        }

    # ===== 辅助 =====

    @property
    def meta(self) -> PluginMeta:
        return self.META

    @property
    def name(self) -> str:
        return self.META.name

    def __repr__(self) -> str:
        return f"<Plugin {self.META.name} v{self.META.version}>"


# ===== 已加载插件实例记录 =====

@dataclass
class PluginEntry:
    """插件注册表条目"""
    meta: PluginMeta
    instance: PluginBase
    status: PluginStatus = PluginStatus.LOADED
    error: str = ""                          # 错误信息
    loaded_at: float = field(default_factory=time.time)
    file_path: str = ""                      # 插件源文件路径
    module_name: str = ""                    # 加载时使用的模块名


# ===== 插件管理器 =====

class PluginManager:
    """
    插件管理器（单例）

    负责：
    - 扫描插件目录
    - 动态加载 .py 插件文件
    - 维护插件注册表
    - 启用/禁用/重载/卸载
    - 配置持久化
    """

    def __init__(self, plugins_root: Path):
        """
        Args:
            plugins_root: 插件根目录，例如 data/plugins/
        """
        self.root = Path(plugins_root)
        self.root.mkdir(parents=True, exist_ok=True)

        # 为每种类型创建子目录
        for t in PluginType:
            (self.root / t.value).mkdir(parents=True, exist_ok=True)

        # 注册表：{plugin_type: {plugin_name: PluginEntry}}
        self._registry: dict[PluginType, dict[str, PluginEntry]] = {
            t: {} for t in PluginType
        }

        # 全局配置文件：记录每个插件的 enabled 状态与 config 数据
        self._config_file = self.root / "config.json"
        self._plugin_configs: dict[str, dict] = self._load_configs()

    # ===== 目录结构 =====

    def get_type_dir(self, plugin_type: PluginType) -> Path:
        """获取某类插件的目录"""
        return self.root / plugin_type.value

    # ===== 配置持久化 =====

    def _load_configs(self) -> dict[str, dict]:
        """加载 config.json"""
        if not self._config_file.exists():
            return {}
        try:
            return json.loads(self._config_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读取插件配置失败: {e}")
            return {}

    def _save_configs(self) -> None:
        """保存 config.json"""
        try:
            self._config_file.write_text(
                json.dumps(self._plugin_configs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存插件配置失败: {e}")

    # ===== 加载 =====

    def discover_all(self) -> int:
        """扫描所有类型目录并加载插件，返回成功加载数量"""
        count = 0
        for plugin_type in PluginType:
            count += self._discover_type(plugin_type)
        return count

    def _discover_type(self, plugin_type: PluginType) -> int:
        """扫描某类插件目录"""
        type_dir = self.get_type_dir(plugin_type)
        count = 0
        for py_file in sorted(type_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                self._load_file(py_file, plugin_type)
                count += 1
            except Exception as e:
                logger.error(f"加载插件 {py_file} 失败: {e}")
        return count

    def _load_file(self, file_path: Path, plugin_type: PluginType) -> PluginEntry:
        """动态加载单个插件文件"""
        plugin_name = file_path.stem
        module_name = f"mdcx_plugin_{plugin_type.value}_{plugin_name}"

        # 如果之前已加载过，先卸载
        existing = self._registry[plugin_type].get(plugin_name)
        if existing is not None:
            self._unload_entry(existing)

        # 如果模块已在 sys.modules 中（重载场景），先移除
        if module_name in sys.modules:
            del sys.modules[module_name]

        # 使用 importlib 动态加载
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法创建模块 spec: {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # 查找 Plugin 类（约定：模块必须导出 Plugin）
        PluginCls = getattr(module, "Plugin", None)
        if PluginCls is None:
            raise RuntimeError(f"插件 {file_path} 未导出 Plugin 类")

        if not (inspect.isclass(PluginCls) and issubclass(PluginCls, PluginBase)):
            raise RuntimeError(f"插件 {file_path} 的 Plugin 类未继承 PluginBase")

        # 实例化
        instance = PluginCls()

        # 校验 META
        meta = getattr(instance, "META", None)
        if meta is None:
            raise RuntimeError(f"插件 {file_path} 未定义 META")
        if meta.plugin_type != plugin_type:
            raise RuntimeError(
                f"插件类型不匹配：期望 {plugin_type.value}，实际 {meta.plugin_type.value}"
            )
        # 强制 name 与文件名一致，避免冲突
        meta.name = plugin_name

        # 注入管理器引用与配置
        instance._manager = self
        saved_config = self._plugin_configs.get(plugin_name, {})
        instance.update_config(saved_config.get("config", {}))

        # 生命周期：on_load
        try:
            instance.on_load()
        except Exception as e:
            logger.error(f"插件 {plugin_name} on_load 失败: {e}")

        # 决定初始状态
        enabled = saved_config.get("enabled", True)
        status = PluginStatus.DISABLED if not enabled else PluginStatus.ENABLED
        if enabled:
            try:
                instance.on_enable()
            except Exception as e:
                logger.error(f"插件 {plugin_name} on_enable 失败: {e}")
                status = PluginStatus.ERROR

        entry = PluginEntry(
            meta=meta,
            instance=instance,
            status=status,
            file_path=str(file_path),
            module_name=module_name,
        )
        self._registry[plugin_type][plugin_name] = entry
        logger.info(f"已加载插件 [{plugin_type.value}] {plugin_name} v{meta.version}")
        return entry

    # ===== 卸载 =====

    def _unload_entry(self, entry: PluginEntry) -> None:
        """卸载单个插件条目"""
        try:
            if entry.status == PluginStatus.ENABLED:
                entry.instance.on_disable()
            entry.instance.on_unload()
        except Exception as e:
            logger.error(f"卸载插件 {entry.meta.name} 失败: {e}")
        # 从 sys.modules 移除
        if entry.module_name and entry.module_name in sys.modules:
            del sys.modules[entry.module_name]
        # 从注册表移除
        self._registry[entry.meta.plugin_type].pop(entry.meta.name, None)

    # ===== API =====

    def list_plugins(self, plugin_type: Optional[PluginType] = None) -> list[PluginEntry]:
        """列出插件"""
        result: list[PluginEntry] = []
        types = [plugin_type] if plugin_type else list(PluginType)
        for t in types:
            result.extend(self._registry[t].values())
        return result

    def get_plugin(self, plugin_type: PluginType, name: str) -> Optional[PluginEntry]:
        """获取单个插件"""
        return self._registry[plugin_type].get(name)

    def get_instance(self, plugin_type: PluginType, name: str) -> Optional[PluginBase]:
        """获取插件实例"""
        entry = self.get_plugin(plugin_type, name)
        return entry.instance if entry else None

    def get_enabled_instances(self, plugin_type: PluginType) -> list[PluginBase]:
        """获取某类型所有已启用的插件实例"""
        return [
            e.instance for e in self._registry[plugin_type].values()
            if e.status == PluginStatus.ENABLED
        ]

    def enable(self, plugin_type: PluginType, name: str) -> None:
        """启用插件"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            raise KeyError(f"插件不存在: {name}")
        if entry.status == PluginStatus.ENABLED:
            return
        try:
            entry.instance.on_enable()
            entry.status = PluginStatus.ENABLED
            entry.error = ""
        except Exception as e:
            entry.status = PluginStatus.ERROR
            entry.error = str(e)
            raise
        self._set_enabled_flag(name, True)

    def disable(self, plugin_type: PluginType, name: str) -> None:
        """禁用插件"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            raise KeyError(f"插件不存在: {name}")
        if entry.status == PluginStatus.DISABLED:
            return
        try:
            entry.instance.on_disable()
        except Exception as e:
            logger.error(f"on_disable 异常: {e}")
        entry.status = PluginStatus.DISABLED
        self._set_enabled_flag(name, False)

    def reload(self, plugin_type: PluginType, name: str) -> PluginEntry:
        """重载插件（先卸载，再从源文件加载）"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            raise KeyError(f"插件不存在: {name}")
        file_path = Path(entry.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"插件源文件已删除: {file_path}")
        self._unload_entry(entry)
        return self._load_file(file_path, plugin_type)

    def unload(self, plugin_type: PluginType, name: str) -> None:
        """卸载插件"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            return
        self._unload_entry(entry)

    def update_plugin_config(
        self, plugin_type: PluginType, name: str, config: dict
    ) -> None:
        """更新插件配置"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            raise KeyError(f"插件不存在: {name}")
        entry.instance.update_config(config)
        self._plugin_configs.setdefault(name, {})["config"] = config
        self._save_configs()

    def get_plugin_config(self, plugin_type: PluginType, name: str) -> dict:
        """获取插件配置"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            return {}
        return dict(entry.instance.get_config())

    def get_config_schema(self, plugin_type: PluginType, name: str) -> dict:
        """获取插件配置 schema（前端动态表单用）"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            return {}
        try:
            return entry.instance.get_config_schema()
        except Exception as e:
            logger.error(f"获取配置 schema 失败: {e}")
            return {}

    def _set_enabled_flag(self, name: str, enabled: bool) -> None:
        """更新持久化的 enabled 标记"""
        self._plugin_configs.setdefault(name, {})["enabled"] = enabled
        self._save_configs()

    # ===== 创建示例插件模板 =====

    def create_template(
        self, plugin_type: PluginType, name: str, force: bool = False
    ) -> Path:
        """
        在插件目录中创建一个示例插件文件，方便用户编辑

        Args:
            plugin_type: 插件类型
            name: 插件名（将成为文件名）
            force: 是否覆盖已存在文件

        Returns:
            创建的文件路径
        """
        safe_name = "".join(c for c in name if c.isalnum() or c in "_-").lower()
        if not safe_name:
            raise ValueError("插件名无效")
        type_dir = self.get_type_dir(plugin_type)
        file_path = type_dir / f"{safe_name}.py"
        if file_path.exists() and not force:
            raise FileExistsError(f"插件已存在: {file_path}")

        template = self._get_template(plugin_type, safe_name)
        file_path.write_text(template, encoding="utf-8")
        return file_path

    def delete_plugin_file(self, plugin_type: PluginType, name: str) -> None:
        """删除插件源文件（同时卸载）"""
        entry = self.get_plugin(plugin_type, name)
        if entry is None:
            return
        file_path = Path(entry.file_path)
        self._unload_entry(entry)
        if file_path.exists():
            file_path.unlink()
        # 清理配置
        self._plugin_configs.pop(name, None)
        self._save_configs()

    # ===== 模板 =====

    @staticmethod
    def _get_template(plugin_type: PluginType, name: str) -> str:
        """返回示例插件源码"""
        display_name = name.replace("_", " ").title()
        if plugin_type == PluginType.CRAWLER:
            return _CRAWLER_TEMPLATE.format(name=name, display_name=display_name)
        if plugin_type == PluginType.TRANSLATOR:
            return _TRANSLATOR_TEMPLATE.format(name=name, display_name=display_name)
        if plugin_type == PluginType.ORGANIZER:
            return _ORGANIZER_TEMPLATE.format(name=name, display_name=display_name)
        return _NOTIFIER_TEMPLATE.format(name=name, display_name=display_name)


# ===== 全局单例 =====

_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """获取全局 PluginManager 单例"""
    global _manager
    if _manager is None:
        from app.config.manager import DATA_DIR
        plugins_root = Path(DATA_DIR) / "plugins"
        _manager = PluginManager(plugins_root)
        try:
            _manager.discover_all()
        except Exception as e:
            logger.error(f"插件初始化失败: {e}")
    return _manager


# ===== 插件模板字符串 =====

_CRAWLER_TEMPLATE = '''"""
爬虫插件：{display_name}

由插件系统动态加载，必须导出 `Plugin` 类，继承 CrawlerPlugin。
"""

from __future__ import annotations

from typing import Optional

from app.services.plugin_manager import PluginBase, PluginMeta, PluginType
from app.crawlers.base import ScrapeResult


class Plugin(PluginBase):
    META = PluginMeta(
        name="{name}",
        plugin_type=PluginType.CRAWLER,
        display_name="{display_name}",
        version="0.1.0",
        author="your-name",
        description="示例爬虫插件",
    )

    def on_load(self) -> None:
        # 初始化资源（HTTP client、会话等）
        pass

    def on_unload(self) -> None:
        # 释放资源
        pass

    def get_config_schema(self) -> dict:
        return {{
            "type": "object",
            "properties": {{
                "base_url": {{
                    "type": "string",
                    "title": "站点URL",
                    "default": "https://example.com",
                }},
            }},
        }}

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """实现抓取逻辑，返回 ScrapeResult 或 None"""
        logger.warning("[插件 %s] scrape() 方法未实现（骨架方法），请安装对应插件或自定义脚本", self.name)
        base_url = self.get_config("base_url", "https://example.com")
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """实现搜索逻辑"""
        return []
'''

_TRANSLATOR_TEMPLATE = '''"""
翻译引擎插件：{display_name}

由插件系统动态加载，必须导出 `Plugin` 类，继承 PluginBase。
实现 translate(text) 方法返回译文。
"""

from __future__ import annotations

from typing import Optional

from app.services.plugin_manager import PluginBase, PluginMeta, PluginType


class Plugin(PluginBase):
    META = PluginMeta(
        name="{name}",
        plugin_type=PluginType.TRANSLATOR,
        display_name="{display_name}",
        version="0.1.0",
        author="your-name",
        description="示例翻译引擎插件",
    )

    def get_config_schema(self) -> dict:
        return {{
            "type": "object",
            "properties": {{
                "api_key": {{"type": "string", "title": "API Key"}},
                "endpoint": {{"type": "string", "title": "API 端点"}},
            }},
        }}

    async def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> Optional[str]:
        """翻译文本，返回译文，失败返回 None"""
        logger.warning("[插件 %s] translate() 方法未实现（骨架方法），请安装对应翻译插件", self.name)
        return None

    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译（默认逐条调用，性能敏感可重写）"""
        results = []
        for t in texts:
            results.append(await self.translate(t))
        return results
'''

_ORGANIZER_TEMPLATE = '''"""
整理规则插件：{display_name}

由插件系统动态加载，必须导出 `Plugin` 类，继承 PluginBase。
实现 organize(file_path, metadata) -> new_path 方法。
"""

from __future__ import annotations

from typing import Optional

from app.services.plugin_manager import PluginBase, PluginMeta, PluginType


class Plugin(PluginBase):
    META = PluginMeta(
        name="{name}",
        plugin_type=PluginType.ORGANIZER,
        display_name="{display_name}",
        version="0.1.0",
        author="your-name",
        description="示例整理规则插件",
    )

    def get_config_schema(self) -> dict:
        return {{
            "type": "object",
            "properties": {{
                "output_dir": {{"type": "string", "title": "输出目录"}},
                "rename_format": {{"type": "string", "title": "重命名格式", "default": "{{code}}"}},
            }},
        }}

    def organize(
        self,
        file_path: str,
        metadata: dict,
    ) -> Optional[str]:
        """
        根据元数据整理文件，返回新路径，失败返回 None

        Args:
            file_path: 原文件路径
            metadata: 元数据 dict（含 code/title/actors/studio/release_date 等）
        """
        logger.warning("[插件 %s] organize() 方法未实现（骨架方法），请安装对应整理插件", self.name)
        return file_path
'''

_NOTIFIER_TEMPLATE = '''"""
通知器插件：{display_name}

由插件系统动态加载，必须导出 `Plugin` 类，继承 PluginBase。
实现 send(title, message, level, data) -> bool 方法。
"""

from __future__ import annotations

from app.services.plugin_manager import PluginBase, PluginMeta, PluginType


class Plugin(PluginBase):
    META = PluginMeta(
        name="{name}",
        plugin_type=PluginType.NOTIFIER,
        display_name="{display_name}",
        version="0.1.0",
        author="your-name",
        description="示例通知器插件",
    )

    def get_config_schema(self) -> dict:
        return {{
            "type": "object",
            "properties": {{
                "webhook_url": {{"type": "string", "title": "Webhook URL"}},
            }},
        }}

    async def send(self, title: str, message: str, level: str = "info", data: dict | None = None) -> bool:
        """发送通知，返回是否成功"""
        logger.warning("[插件 %s] send() 方法未实现（骨架方法），请安装对应通知插件", self.name)
        return False
'''
