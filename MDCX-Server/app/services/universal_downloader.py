"""全能下载器集成 — yt-dlp 驱动的多站点下载服务。

支持 1800+ 站点（通过 yt-dlp）：
- 91porn / 91porny
- 海角 haijiao.com
- 糖心 tangxinvlog
- YouTube / Bilibili
- 所有 yt-dlp 支持的站点

参考：特殊项目/全能下载器 的下载引擎
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.event_bus import get_event_bus

logger = logging.getLogger(__name__)

_DEFAULT_DOWNLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "downloads",
)


@dataclass
class DownloadTask:
    id: str = ""
    url: str = ""
    title: str = ""
    progress: float = 0.0
    speed: str = ""
    status: str = "pending"
    output_dir: str = ""
    module: str = ""
    error: str = ""


class UniversalDownloader:
    """全能下载器 — 基于 yt-dlp。"""

    def __init__(self, download_dir: str = _DEFAULT_DOWNLOAD_DIR):
        self.download_dir = download_dir
        os.makedirs(download_dir, exist_ok=True)
        self._tasks: dict[str, DownloadTask] = {}
        self._ytdlp_path = self._find_ytdlp()

    def _find_ytdlp(self) -> str:
        """查找 yt-dlp 可执行文件。"""
        # 优先查找本地 bin 目录
        local_bin = os.path.join(os.path.dirname(self.download_dir), "..", "bin", "yt-dlp_win", "yt-dlp.exe")
        if os.path.isfile(local_bin):
            return local_bin
        # 环境变量
        for p in os.environ.get("PATH", "").split(os.pathsep):
            yt = os.path.join(p, "yt-dlp.exe" if os.name == "nt" else "yt-dlp")
            if os.path.isfile(yt):
                return yt
        return "yt-dlp"

    def list_tasks(self) -> list[DownloadTask]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(task_id)

    async def add_download(self, url: str, output_dir: str | None = None,
                           module: str = "") -> DownloadTask:
        """添加下载任务。"""
        import uuid
        task = DownloadTask(
            id=uuid.uuid4().hex[:12],
            url=url,
            status="queued",
            output_dir=output_dir or os.path.join(self.download_dir, module or "general"),
            module=module,
        )
        self._tasks[task.id] = task
        return task

    async def start_download(self, task_id: str):
        """启动下载任务。"""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.status = "downloading"
        bus = get_event_bus()
        await bus.emit_progress(task_id, 0.0, f"开始下载: {task.url}", module="downloader")

        try:
            os.makedirs(task.output_dir, exist_ok=True)

            # yt-dlp 参数
            cmd = [
                self._ytdlp_path,
                "-o", os.path.join(task.output_dir, "%(title)s.%(ext)s"),
                "--no-playlist",
                "--no-mtime",
                "--no-cache-dir",
                task.url,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # 实时读取输出
            if proc.stdout:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()

                    # 提取进度: [download] 45.2% of 1.25GiB at 5.2MiB/s ETA 00:02:13
                    progress_m = re.search(r'(\d+\.?\d*)%', text)
                    if progress_m:
                        task.progress = float(progress_m.group(1)) / 100.0

                    speed_m = re.search(r'at\s+([\d.]+[KMGTP]?i?B/s)', text)
                    if speed_m:
                        task.speed = speed_m.group(1)

                    await bus.emit_progress(task_id, task.progress,
                                            f"下载中 {task.progress*100:.0f}% {task.speed}",
                                            module="downloader")

            await proc.wait()

            if proc.returncode == 0:
                task.status = "completed"
                task.progress = 1.0
                await bus.emit_progress(task_id, 1.0, "下载完成", status="success", module="downloader")
            else:
                task.status = "failed"
                task.error = f"yt-dlp exit code: {proc.returncode}"
                await bus.emit_progress(task_id, task.progress, task.error,
                                        status="failed", module="downloader")

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.exception("download failed for %s", task.url)
            await bus.emit_progress(task_id, task.progress, str(e),
                                    status="failed", module="downloader")

    async def start_all_queued(self):
        """启动所有排队任务。"""
        tasks_to_start = [t for t in self._tasks.values() if t.status == "queued"]
        for task in tasks_to_start:
            await self.start_download(task.id)


# 全局下载器
_downloader: Optional[UniversalDownloader] = None


def get_downloader() -> UniversalDownloader:
    global _downloader
    if _downloader is None:
        _downloader = UniversalDownloader()
    return _downloader
