"""
临时下载管理器

管理下载队列、并发控制、断点续传、下载历史。
整合 3 个下载引擎 + 缓存去重。

核心功能:
  - 任务队列（FIFO）
  - 并发限制（最多 N 个同时下载）
  - 引擎自动选择
  - 缓存去重（URL + 哈希）
  - 进度追踪 + 回调
  - 暂停/恢复/取消
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.services.download.download_models import (
    DownloadResult,
    DownloadTask,
    ProgressInfo,
)
from app.services.download.download_cache import DownloadCacheDB, get_download_cache
from app.services.download.downloader_factory import DownloaderFactory, get_downloader_factory
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TempDownloadConfig:
    """临时下载管理器配置"""
    max_concurrent: int = 3
    output_dir: str = "./downloads"
    use_cache: bool = True
    cache_dir: str = "./data"


class TempDownloadManager:
    """临时下载管理器

    上层接口，供 API/Frontend 调用。
    """

    def __init__(
        self,
        config: Optional[TempDownloadConfig] = None,
        downloader_factory: Optional[DownloaderFactory] = None,
        cache: Optional[DownloadCacheDB] = None,
    ):
        self.config = config or TempDownloadConfig()
        self.factory = downloader_factory or get_downloader_factory()
        self.cache = cache or get_download_cache()
        self._tasks: dict[str, DownloadTask] = {}
        self._active_count = 0
        self._queue: list[str] = []
        self._callbacks: dict[str, list[Callable]] = {}
        self._lock = asyncio.Lock()
        self._max_concurrent = self.config.max_concurrent

    async def submit(
        self,
        url: str,
        output_path: Optional[str] = None,
        metadata: Optional[dict] = None,
        progress_callback: Optional[Callable[[ProgressInfo], None]] = None,
    ) -> str:
        """提交下载任务

        Args:
            url: 下载 URL
            output_path: 输出路径���可选）
            metadata: 附加元数据
            progress_callback: 进度回调

        Returns:
            task_id: 任务唯一标识
        """
        # 缓存去重
        if self.config.use_cache:
            if self.cache.exists(url):
                entry = self.cache.get(url)
                if entry and entry.file_path and Path(entry.file_path).exists():
                    logger.info(f"跳过已下载: {url} -> {entry.file_path}")
                    return url

        task_id = str(uuid.uuid4())[:8]
        task = DownloadTask(
            task_id=task_id,
            url=url,
            output_path=output_path or "",
            engine=self.factory.select_engine(url),
            status="queued",
            created_at=time.time(),
            metadata=metadata or {},
        )
        self._tasks[task_id] = task

        if progress_callback:
            if task_id not in self._callbacks:
                self._callbacks[task_id] = []
            self._callbacks[task_id].append(progress_callback)

        # 加入队列
        self._queue.append(task_id)
        asyncio.create_task(self._process_queue())
        logger.info(f"下载任务已提交: {task_id} -> {url}")
        return task_id

    async def _process_queue(self) -> None:
        """处理下载队列"""
        async with self._lock:
            while self._queue and self._active_count < self._max_concurrent:
                task_id = self._queue.pop(0)
                if task_id in self._tasks:
                    self._active_count += 1
                    asyncio.create_task(self._execute(task_id))

    def _progress_wrapper(self, task_id: str) -> Callable:
        """创建进度回调包装器"""
        def wrapper(downloaded_bytes: int, total_bytes: int, speed: float, eta: float, percent: float):
            progress = ProgressInfo(
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                speed=speed,
                eta=eta,
                percent=percent,
                status="downloading",
                url=self._tasks.get(task_id, DownloadTask()).url,
            )
            if task_id in self._callbacks:
                for cb in self._callbacks[task_id]:
                    try:
                        cb(progress)
                    except Exception as e:
                        logger.warning(f"进度回调异常: {e}")
        return wrapper

    async def _execute(self, task_id: str) -> None:
        """执行单个下载任务"""
        task = self._tasks.get(task_id)
        if not task:
            self._active_count -= 1
            return

        task.status = "downloading"
        logger.info(f"开始下载 [{task_id}]: {task.url}")

        try:
            result = await self.factory.download(task.url, task.output_path)

            if result.success and result.file_path:
                task.status = "completed"
                task.progress = 100.0
                task.completed_at = time.time()
                logger.info(f"下载完成 [{task_id}]: {result.file_path}")

                # 写入缓存
                if self.config.use_cache:
                    self.cache.mark_completed(
                        url=task.url,
                        file_path=result.file_path,
                        file_size=result.file_size,
                        file_hash=result.hash or "",
                    )
            else:
                task.status = "failed"
                task.error = result.error
                logger.warning(f"下载失败 [{task_id}]: {result.error}")

                if self.config.use_cache:
                    self.cache.set_status(task.url, "failed", result.error)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.exception(f"下载异常 [{task_id}]: {e}")
            if self.config.use_cache:
                self.cache.set_status(task.url, "failed", str(e))

        finally:
            self._active_count -= 1
            # 继续处理队列
            asyncio.create_task(self._process_queue())

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """获取任务状态"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[DownloadTask]:
        """获取所有任务"""
        return list(self._tasks.values())

    def get_active_tasks(self) -> list[DownloadTask]:
        """获取活跃任务"""
        return [t for t in self._tasks.values() if t.status in ("queued", "downloading")]

    def get_history(self) -> list[DownloadTask]:
        """获取历史（已完成 + 失败）"""
        return [t for t in self._tasks.values() if t.status in ("completed", "failed")]

    def stats(self) -> dict:
        """统计信息"""
        return {
            "active_count": self._active_count,
            "queue_length": len(self._queue),
            "total_tasks": len(self._tasks),
            "max_concurrent": self._max_concurrent,
        }


# 全局单例
_manager: Optional[TempDownloadManager] = None


def get_download_manager() -> TempDownloadManager:
    global _manager
    if _manager is None:
        _manager = TempDownloadManager()
    return _manager
