"""
目录实时监听服务（双模：watchdog / polling）

支持两种监控模式：
1. watchdog（默认）：基于 inotify/FSEvents/ReadDirectoryChangesW，实时响应
2. polling（轮询）：兼容 NAS / 网络挂载盘 / SMB 共享场景
3. auto（推荐）：优先 watchdog，启动失败或检测到网络盘自动回退 polling

参考 mdc-ng 的双模目录监控设计。

设计要点：
- 监听 create/move 事件，提取番号后关联到数据库
- 防抖处理：短时间内的批量变化合并为一次扫描
- 删除事件仅清除 file_path 关联，不删 Movie 记录（零侵入）
- polling 模式基于 mtime 快照对比，兼容性最好
- 在 app lifespan 中启动/停止
"""
import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from app.config.manager import get_config

logger = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    # 提供占位基类,避免 _DebouncedScanner 类定义时 NameError
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    FileSystemEvent = object  # type: ignore[assignment,misc]
    logger.info("watchdog 未安装，目录实时监听将使用 polling 模式。pip install watchdog 启用实时模式")

# 默认视频扩展名（可被配置覆盖）
DEFAULT_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v",
    ".rm", ".rmvb", ".mpg", ".mpeg", ".ts", ".m2ts", ".webm",
}


def _is_network_path(path: str) -> bool:
    """检测路径是否为网络挂载盘（watchdog 可能不工作）"""
    p = str(path)
    # Windows 网络路径
    if p.startswith("\\\\") or p.startswith("//"):
        return True
    # Unix NFS/CIFS 挂载点检测（简化版）
    try:
        import subprocess
        result = subprocess.run(
            ["mount"] if os.name != "nt" else ["net", "use"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        return p in result.stdout
    except Exception:
        return False


class _DebouncedScanner(FileSystemEventHandler):
    """防抖的事件处理器，合并短时间内的批量变化（watchdog 模式使用）"""

    def __init__(self, media_dirs: list[str], video_exts: set, debounce_interval: float = 5.0):
        super().__init__()
        self.media_dirs = media_dirs
        self.video_exts = video_exts
        self.debounce_interval = debounce_interval
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._changed_dirs: set[str] = set()

    def _is_video(self, path: str) -> bool:
        return Path(path).suffix.lower() in self.video_exts

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self._is_video(event.src_path):
            self._schedule_scan(event.src_path)

    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory and self._is_video(getattr(event, 'dest_path', '')):
            self._schedule_scan(getattr(event, 'dest_path', ''))

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and self._is_video(event.src_path):
            self._schedule_scan(event.src_path, deleted=True)

    def _schedule_scan(self, file_path: str, deleted: bool = False):
        """防抖调度：收集变化，延迟批量处理"""
        with self._lock:
            parent = self._find_parent_dir(file_path)
            if parent:
                self._changed_dirs.add(parent)

            if self._timer:
                self._timer.cancel()

            self._timer = threading.Timer(self.debounce_interval, self._do_scan)
            self._timer.daemon = True
            self._timer.start()

    def _find_parent_dir(self, file_path: str) -> Optional[str]:
        """找到文件属于哪个配置的媒体目录"""
        p = Path(file_path)
        for d in self.media_dirs:
            try:
                p.relative_to(d)
                return d
            except ValueError:
                continue
        return None

    def trigger_scan(self, dirs: list[str]):
        """外部触发扫描（polling 模式发现变化时调用）"""
        with self._lock:
            for d in dirs:
                self._changed_dirs.add(d)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_interval, self._do_scan)
            self._timer.daemon = True
            self._timer.start()

    def _do_scan(self):
        """执行实际的扫描关联"""
        with self._lock:
            dirs_to_scan = list(self._changed_dirs)
            self._changed_dirs.clear()

        if not dirs_to_scan:
            return

        logger.info(f"目录监听触发扫描: {dirs_to_scan}")
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._async_scan_and_link(dirs_to_scan))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"目录监听扫描失败: {e}")

    async def _async_scan_and_link(self, directories: list[str]):
        """异步扫描并关联文件"""
        from app.db.database import get_database
        from app.scraper.number import extract_number, normalize_number
        from sqlalchemy import select
        from app.db.models import Movie

        db = get_database()
        async with db.session() as session:
            linked = 0
            for directory in directories:
                scan_dir = Path(directory)
                if not scan_dir.exists():
                    continue
                for f in scan_dir.rglob("*"):
                    if f.suffix.lower() not in self.video_exts or not f.is_file():
                        continue
                    try:
                        number_result = extract_number(f.name)
                    except Exception:
                        continue
                    if not number_result.number:
                        continue
                    normalized = normalize_number(number_result.number)
                    result = await session.execute(
                        select(Movie).where(Movie.code == normalized)
                    )
                    movie = result.scalar_one_or_none()
                    if movie and not movie.file_path:
                        movie.file_path = str(f)
                        try:
                            movie.file_size = f.stat().st_size
                        except OSError:
                            pass
                        linked += 1

            if linked > 0:
                await session.commit()
                logger.info(f"目录监听扫描完成，关联 {linked} 个文件")


class _PollingWatcher:
    """轮询监控器（polling 模式）

    定期扫描目录，对比文件 mtime 快照发现变化。
    兼容 NAS / SMB / CIFS 等网络挂载盘。
    """

    def __init__(self, media_dirs: list[str], video_exts: set, poll_interval: int = 60,
                 debounce_interval: float = 5.0, callback=None):
        self.media_dirs = media_dirs
        self.video_exts = video_exts
        self.poll_interval = poll_interval
        self.debounce_interval = debounce_interval
        self.callback = callback  # 发现变化时调用 callback(dirs: list[str])
        self._snapshots: dict[str, dict[str, float]] = {}  # dir → {path → mtime}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _take_snapshot(self, directory: str) -> dict[str, float]:
        """扫描目录，返回 {file_path: mtime} 快照"""
        snapshot = {}
        scan_dir = Path(directory)
        if not scan_dir.exists():
            return snapshot
        try:
            for f in scan_dir.rglob("*"):
                if f.suffix.lower() in self.video_exts and f.is_file():
                    try:
                        snapshot[str(f)] = f.stat().st_mtime
                    except OSError:
                        continue
        except Exception as e:
            logger.warning(f"扫描目录 {directory} 失败: {e}")
        return snapshot

    def _diff_snapshots(self, old: dict, new: dict) -> bool:
        """对比两个快照，返回是否有变化"""
        if set(old.keys()) != set(new.keys()):
            return True
        for path, mtime in new.items():
            if path not in old or abs(old[path] - mtime) > 1.0:
                return True
        return False

    def _poll_once(self):
        """执行一次轮询"""
        changed_dirs = []
        for d in self.media_dirs:
            new_snapshot = self._take_snapshot(d)
            old_snapshot = self._snapshots.get(d, {})
            if self._diff_snapshots(old_snapshot, new_snapshot):
                changed_dirs.append(d)
                logger.info(f"polling 检测到 {d} 有变化（{len(new_snapshot)} 个文件）")
            self._snapshots[d] = new_snapshot

        if changed_dirs and self.callback:
            self.callback(changed_dirs)

    def _poll_loop(self):
        """轮询主循环"""
        # 首次扫描建立基线快照
        logger.info(f"polling 模式首次扫描建立基线...")
        for d in self.media_dirs:
            self._snapshots[d] = self._take_snapshot(d)
            logger.info(f"基线快照: {d} ({len(self._snapshots[d])} 个视频文件)")

        while not self._stop_event.is_set():
            # 等待轮询间隔（可被 stop_event 唤醒）
            if self._stop_event.wait(self.poll_interval):
                break
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"polling 轮询异常: {e}")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="polling-watcher")
        self._thread.start()
        logger.info(f"polling 监控已启动（间隔 {self.poll_interval}s，监控 {len(self.media_dirs)} 个目录）")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._thread = None
        logger.info("polling 监控已停止")


class DirectoryWatcher:
    """目录监听管理器（双模：watchdog / polling）"""

    def __init__(self):
        self._observer: Optional[Observer] = None
        self._polling: Optional[_PollingWatcher] = None
        self._handler: Optional[_DebouncedScanner] = None
        self._running = False
        self._active_mode: str = "none"  # watchdog / polling / none

    @property
    def active_mode(self) -> str:
        return self._active_mode

    def start(self, media_dirs: list[str]):
        """启动目录监听（根据配置选择模式）"""
        if self._running:
            self.stop()

        if not media_dirs:
            logger.info("未配置媒体目录，跳过目录监听")
            return

        # 读取配置
        try:
            cfg = get_config().watcher
            mode = cfg.mode
            debounce = cfg.debounce_interval
            poll_interval = cfg.poll_interval
            recursive = cfg.recursive
            video_exts = set(cfg.video_extensions) if cfg.video_extensions else DEFAULT_VIDEO_EXTENSIONS
        except Exception:
            mode = "auto"
            debounce = 5.0
            poll_interval = 60
            recursive = True
            video_exts = DEFAULT_VIDEO_EXTENSIONS

        # 创建统一的事件处理器（两种模式共用）
        self._handler = _DebouncedScanner(media_dirs, video_exts, debounce)

        # 检测是否有网络路径
        has_network = any(_is_network_path(d) for d in media_dirs)
        if has_network and mode == "watchdog":
            logger.warning("检测到网络路径但配置为 watchdog 模式，建议改为 auto 或 polling")

        # 根据模式启动
        if mode == "polling":
            self._start_polling(media_dirs, video_exts, poll_interval, debounce)
        elif mode == "watchdog":
            self._start_watchdog(media_dirs, video_exts, recursive)
        else:  # auto
            # 优先 watchdog，失败回退 polling
            if WATCHDOG_AVAILABLE and not has_network:
                try:
                    self._start_watchdog(media_dirs, video_exts, recursive)
                except Exception as e:
                    logger.warning(f"watchdog 启动失败，回退到 polling: {e}")
                    self._start_polling(media_dirs, video_exts, poll_interval, debounce)
            else:
                logger.info("使用 polling 模式（watchdog 不可用或检测到网络路径）")
                self._start_polling(media_dirs, video_exts, poll_interval, debounce)

        self._running = True

    def _start_watchdog(self, media_dirs: list[str], video_exts: set, recursive: bool):
        """启动 watchdog 模式"""
        if not WATCHDOG_AVAILABLE:
            raise RuntimeError("watchdog 未安装")

        self._observer = Observer()
        for d in media_dirs:
            dir_path = Path(d)
            if dir_path.exists() and dir_path.is_dir():
                self._observer.schedule(self._handler, str(dir_path), recursive=recursive)
                logger.info(f"watchdog 监听: {d}")
            else:
                logger.warning(f"媒体目录不存在，跳过监听: {d}")

        self._observer.daemon = True
        self._observer.start()
        self._active_mode = "watchdog"
        logger.info(f"watchdog 模式已启动，监控 {len(media_dirs)} 个目录")

    def _start_polling(self, media_dirs: list[str], video_exts: set, poll_interval: int, debounce: float):
        """启动 polling 模式"""
        self._polling = _PollingWatcher(
            media_dirs=media_dirs,
            video_exts=video_exts,
            poll_interval=poll_interval,
            debounce_interval=debounce,
            callback=self._handler.trigger_scan,
        )
        self._polling.start()
        self._active_mode = "polling"

    def stop(self):
        """停止目录监听"""
        if self._observer and self._running:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception as e:
                logger.warning(f"watchdog 停止异常: {e}")
            self._observer = None

        if self._polling and self._running:
            try:
                self._polling.stop()
            except Exception as e:
                logger.warning(f"polling 停止异常: {e}")
            self._polling = None

        self._handler = None
        self._running = False
        self._active_mode = "none"
        logger.info("目录监听服务已停止")

    def get_status(self) -> dict:
        """获取监控状态"""
        try:
            cfg = get_config().watcher
            config_mode = cfg.mode
            poll_interval = cfg.poll_interval
            debounce = cfg.debounce_interval
        except Exception:
            config_mode = "auto"
            poll_interval = 60
            debounce = 5.0

        return {
            "running": self._running,
            "active_mode": self._active_mode,
            "config_mode": config_mode,
            "poll_interval": poll_interval,
            "debounce_interval": debounce,
            "watchdog_available": WATCHDOG_AVAILABLE,
            "media_dirs": get_config().scraper.media_dirs if self._running else [],
        }


# 全局单例
_watcher: Optional[DirectoryWatcher] = None


def get_directory_watcher() -> DirectoryWatcher:
    global _watcher
    if _watcher is None:
        _watcher = DirectoryWatcher()
    return _watcher
