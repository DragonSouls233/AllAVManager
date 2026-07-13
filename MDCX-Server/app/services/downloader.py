"""下载器统一抽象（§7.11）

定义统一的下载器抽象基类 DownloaderBase 与枚举，屏蔽 qBittorrent / Transmission /
Aria2 等不同下载器的 API 差异，对上层提供一致的接口。

子类需实现以下方法：
- async login() -> bool
- async add_torrent(torrent_url_or_magnet, download_dir=None, name=None) -> str
- async list_tasks(status=None) -> list[dict]
- async get_task(task_id) -> dict
- async cancel_task(task_id) -> bool
- async pause_task(task_id) -> bool
- async resume_task(task_id) -> bool
- async get_status() -> dict
- async close()

实现要点：
1. 子类通过 httpx.AsyncClient 与下载器交互（生命周期由本类管理）
2. 任务状态映射到统一的 TaskStatus 枚举
3. 任务字典字段统一为：id / name / status / progress / size / downloaded / upload_speed / download_speed / eta
"""

import abc
import enum
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TaskStatus(str, enum.Enum):
    """统一的任务状态枚举"""

    PENDING = "pending"          # 等待中（已加入队列但未开始下载）
    DOWNLOADING = "downloading"  # 下载中
    SEEDING = "seeding"          # 做种中（已完成下载，正在做种）
    COMPLETED = "completed"      # 已完成（停止做种或达到停止条件）
    PAUSED = "paused"            # 已暂停
    ERROR = "error"              # 错误
    UNKNOWN = "unknown"          # 未知状态


class DownloaderType(str, enum.Enum):
    """下载器类型枚举"""

    QBITTORRENT = "qbittorrent"
    TRANSMISSION = "transmission"
    ARIA2 = "aria2"
    # thunder 无公开 API，使用 aria2 作为通用替代


class DownloaderBase(abc.ABC):
    """下载器抽象基类

    所有具体下载器实现均继承此类，对外提供统一接口。
    """

    # 下载器类型标识，子类覆盖
    type: str = "base"

    def __init__(self, name: str = ""):
        self.name: str = name or self.type
        self._started: bool = False
        self._logged_in: bool = False

    # ============== 生命周期 ==============

    async def start(self) -> None:
        """启动下载器（在 lifespan 中调用）

        默认实现调用 login()。子类可覆盖以增加自定义启动逻辑。
        """
        try:
            ok = await self.login()
            self._logged_in = bool(ok)
            self._started = True
            if ok:
                logger.info(f"下载器 [{self.name}] 已登录成功")
            else:
                logger.warning(f"下载器 [{self.name}] 启动但未登录成功（仍允许后续重试）")
        except Exception as e:
            logger.warning(f"下载器 [{self.name}] 启动失败: {e}")
            # 即使登录失败也标记为已启动，允许后续手动重试
            self._started = True

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    # ============== 抽象接口 ==============

    @abc.abstractmethod
    async def login(self) -> bool:
        """登录下载器，返回是否成功"""
        raise NotImplementedError

    @abc.abstractmethod
    async def add_torrent(
        self,
        torrent_url_or_magnet: str,
        download_dir: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """添加种子任务（磁力链 / HTTP 种子 URL）

        Args:
            torrent_url_or_magnet: 磁力链接或 HTTP(S) 种子 URL
            download_dir: 下载目录（None 使用默认）
            name: 任务名称（可选，部分下载器支持）

        Returns:
            任务 ID
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def list_tasks(self, status: Optional[str] = None) -> list[dict]:
        """列出任务

        Args:
            status: 可选状态过滤（TaskStatus 值之一）

        Returns:
            任务字典列表，每项字段：id / name / status / progress / size / downloaded / download_speed / upload_speed / eta
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_task(self, task_id: str) -> dict:
        """获取单个任务详情"""
        raise NotImplementedError

    @abc.abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """取消（删除）任务，返回是否成功"""
        raise NotImplementedError

    @abc.abstractmethod
    async def pause_task(self, task_id: str) -> bool:
        """暂停任务，返回是否成功"""
        raise NotImplementedError

    @abc.abstractmethod
    async def resume_task(self, task_id: str) -> bool:
        """恢复任务，返回是否成功"""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_status(self) -> dict:
        """获取下载器连接状态/版本/速率等综合信息

        返回字段：connected / version / download_speed / upload_speed / active_tasks / 等
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        """关闭客户端，释放资源"""
        raise NotImplementedError


__all__ = ["DownloaderBase", "TaskStatus", "DownloaderType"]
