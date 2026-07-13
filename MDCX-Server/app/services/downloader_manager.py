"""下载器管理器（§7.11）

管理多个下载器实例（qBittorrent / Transmission / Aria2），统一对外提供：
- get_downloader(name)：按名称获取下载器实例
- get_active()：获取当前激活的下载器
- list_available()：列出所有可用下载器名称
- start_all() / close_all()：批量启动/关闭

生命周期由 app.main lifespan 管理。
"""

from typing import Optional

from app.config.manager import get_config
from app.services.downloader import DownloaderBase, DownloaderType
from app.services.qb_downloader import QBDownloader
from app.services.tr_downloader import TRDownloader
from app.services.aria2_downloader import Aria2Downloader
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DownloaderManager:
    """下载器管理器

    维护一份按类型分组的下载器单例，根据配置 active 字段切换激活实例。
    """

    # 支持的下载器名称
    SUPPORTED = (
        DownloaderType.QBITTORRENT.value,
        DownloaderType.TRANSMISSION.value,
        DownloaderType.ARIA2.value,
    )

    def __init__(self):
        self._instances: dict[str, DownloaderBase] = {}
        self._started: bool = False

    # ============== 内部辅助 ==============

    def _create(self, name: str) -> Optional[DownloaderBase]:
        """按名称创建下载器实例"""
        if name == DownloaderType.QBITTORRENT.value:
            return QBDownloader()
        if name == DownloaderType.TRANSMISSION.value:
            return TRDownloader()
        if name == DownloaderType.ARIA2.value:
            return Aria2Downloader()
        logger.warning(f"未知的下载器类型: {name}")
        return None

    # ============== 对外接口 ==============

    def get_downloader(self, name: str) -> Optional[DownloaderBase]:
        """按名称获取下载器实例（懒加载，已创建则复用）"""
        if not name:
            return None
        if name not in self._instances:
            inst = self._create(name)
            if inst is None:
                return None
            self._instances[name] = inst
        return self._instances[name]

    def get_active(self) -> Optional[DownloaderBase]:
        """获取当前激活的下载器

        优先使用配置 downloader.active；若未配置则返回首个 enabled 的下载器。
        """
        cfg = get_config().downloader
        active_name = cfg.active or ""
        if active_name:
            inst = self.get_downloader(active_name)
            if inst is not None:
                return inst
            logger.warning(f"配置的激活下载器 [{active_name}] 不存在，尝试回退")
        # 回退：寻找首个 enabled 的下载器
        for name in self.SUPPORTED:
            sub_cfg = self._get_sub_cfg(name)
            if sub_cfg and getattr(sub_cfg, "enabled", False):
                return self.get_downloader(name)
        return None

    def list_available(self) -> list[str]:
        """列出所有已启用的下载器名称"""
        result: list[str] = []
        for name in self.SUPPORTED:
            sub_cfg = self._get_sub_cfg(name)
            if sub_cfg and getattr(sub_cfg, "enabled", False):
                result.append(name)
        return result

    def _get_sub_cfg(self, name: str):
        cfg = get_config().downloader
        return getattr(cfg, name, None)

    # ============== 生命周期 ==============

    async def start_all(self) -> None:
        """启动所有已启用的下载器"""
        if self._started:
            return
        for name in self.list_available():
            inst = self.get_downloader(name)
            if inst is None:
                continue
            try:
                await inst.start()
            except Exception as e:
                logger.warning(f"启动下载器 [{name}] 失败: {e}")
        self._started = True
        logger.info(f"下载器管理器已启动，激活下载器: {self._active_name()}")

    async def close_all(self) -> None:
        """关闭所有已创建的下载器"""
        for name, inst in list(self._instances.items()):
            try:
                await inst.close()
            except Exception as e:
                logger.warning(f"关闭下载器 [{name}] 失败: {e}")
        self._instances.clear()
        self._started = False
        logger.info("下载器管理器已关闭所有实例")

    @property
    def is_started(self) -> bool:
        return self._started

    def _active_name(self) -> str:
        cfg = get_config().downloader
        return cfg.active or "(未设置)"


# 全局单例
downloader_manager = DownloaderManager()

__all__ = ["DownloaderManager", "downloader_manager"]
