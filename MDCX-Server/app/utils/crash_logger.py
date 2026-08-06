"""
崩溃日志与启动引导日志(全周期可追溯)

解决的问题
----------
此前排查"启动闪退"极其困难，原因有三:

1. `setup_logging()` 写在 `app/main.py` 的 lifespan 内部，进程启动到那一行
   之前的所有崩溃(import 失败、配置解析失败、uvicorn 自身启动失败)
   全都不会落盘。
2. `app/utils/log_config.py` 的 `LOGGING_CONFIG` 里 handler 全是
   `StreamHandler`，一个文件 handler 都没有；且 `app` logger 设了
   `propagate: False`，导致即使 root 挂了文件 handler，应用日志也传不过去。
   于是 `data/logs/app.log` 长期近乎空文件。
3. uvicorn 的 `Application startup failed. Exiting.` 与完整 traceback
   走的是 stderr，控制台窗口一关就彻底丢失。

本模块的定位是"最后一道防线": 不依赖任何项目配置即可工作，
在进程最早期就把文件日志拉起来，并接管所有未捕获异常。

设计原则
--------
- **零依赖**: 只用标准库。配置加载失败正是要捕获的崩溃场景之一，
  因此绝不能反过来依赖 `app.config`。
- **永不因自身出错拖垮服务**: 所有对外函数内部自带兜底。
- **crash.log 只追加不覆盖**: 崩溃现场是最宝贵的证据，宁可文件大也不能丢。
"""

from __future__ import annotations

import atexit
import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional, TextIO

# 崩溃日志文件名(与轮转的 app.log 分开，便于一眼定位)
CRASH_LOG_NAME = "crash.log"
BOOTSTRAP_LOG_NAME = "startup.log"

_installed = False
_log_dir: Optional[Path] = None
_stderr_mirror: Optional[TextIO] = None


# =============================================================================
# 日志目录解析(零依赖)
# =============================================================================
def resolve_log_dir() -> Path:
    """解析日志目录，不依赖 app.config(配置加载失败时也要能写日志)。

    优先级与 `app.config.manager.DATA_DIR` 保持一致:
        1. 环境变量 MDCX_DATA_DIR
        2. 项目根目录下的 data/
        3. 当前工作目录下的 data/ (最后兜底)
    """
    candidates: list[Path] = []

    env_dir = os.environ.get("MDCX_DATA_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))

    # 本文件位于 <project_root>/app/utils/crash_logger.py
    project_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(project_root / "data")
    candidates.append(Path.cwd() / "data")

    for base in candidates:
        try:
            log_dir = base / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir
        except Exception:
            continue

    # 全部失败时退回临时目录，保证永远有地方写
    import tempfile

    fallback = Path(tempfile.gettempdir()) / "mdcx-logs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_log_dir() -> Path:
    """获取(并缓存)日志目录"""
    global _log_dir
    if _log_dir is None:
        _log_dir = resolve_log_dir()
    return _log_dir


def get_crash_log_path() -> Path:
    return get_log_dir() / CRASH_LOG_NAME


# =============================================================================
# 环境快照
# =============================================================================
def _env_snapshot() -> str:
    """采集崩溃时的环境信息，便于复现"""
    try:
        rows = [
            ("时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("Python", f"{platform.python_version()} ({sys.executable})"),
            ("平台", f"{platform.system()} {platform.release()} [{platform.machine()}]"),
            ("进程 PID", str(os.getpid())),
            ("命令行", " ".join(sys.argv)),
            ("工作目录", str(Path.cwd())),
            ("数据目录", os.environ.get("MDCX_DATA_DIR", "(未设置，使用项目根 data/)")),
            ("日志目录", str(get_log_dir())),
        ]
        return "\n".join(f"  {k:<10}: {v}" for k, v in rows)
    except Exception as e:  # pragma: no cover - 快照失败不能影响主流程
        return f"  (环境快照采集失败: {e})"


# =============================================================================
# 崩溃写入
# =============================================================================
def log_crash(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: Any,
    context: str = "未捕获异常",
) -> Optional[Path]:
    """把一次崩溃完整写入 crash.log(追加模式，永不覆盖)。

    Returns:
        崩溃日志路径; 写入失败返回 None。
    """
    try:
        crash_path = get_crash_log_path()
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        block = (
            "\n"
            + "=" * 78 + "\n"
            + f"崩溃记录 [{context}]  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            + "=" * 78 + "\n"
            + "【环境】\n" + _env_snapshot() + "\n\n"
            + f"【异常】{exc_type.__name__}: {exc_value}\n\n"
            + "【调用栈】\n" + tb_text
            + "-" * 78 + "\n"
        )

        with open(crash_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(block)
            f.flush()
            os.fsync(f.fileno())

        return crash_path
    except Exception:
        # 崩溃日志本身失败时，至少保证 traceback 打到 stderr
        try:
            traceback.print_exception(exc_type, exc_value, exc_tb)
        except Exception:
            pass
        return None


def _print_crash_banner(context: str, exc_value: BaseException, crash_path: Optional[Path]) -> None:
    """在控制台打印醒目的崩溃提示，指明日志位置"""
    try:
        line = "!" * 78
        msg = (
            f"\n{line}\n"
            f"  服务启动/运行失败: {context}\n"
            f"  错误: {type(exc_value).__name__}: {exc_value}\n"
        )
        if crash_path:
            msg += f"  完整堆栈已写入: {crash_path}\n"
        msg += f"{line}\n"
        # 直接写底层 stderr，避免 logging 尚未就绪
        sys.__stderr__.write(msg)
        sys.__stderr__.flush()
    except Exception:
        pass


# =============================================================================
# 异常钩子安装
# =============================================================================
def _excepthook(exc_type, exc_value, exc_tb):
    """主线程未捕获异常"""
    # Ctrl+C 属正常退出，不当作崩溃记录
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    path = log_crash(exc_type, exc_value, exc_tb, context="主线程未捕获异常")
    _print_crash_banner("主线程未捕获异常", exc_value, path)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_excepthook(args) -> None:
    """子线程未捕获异常(Python 3.8+)"""
    if issubclass(args.exc_type, SystemExit):
        return
    thread_name = getattr(args.thread, "name", "unknown")
    log_crash(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
        context=f"子线程未捕获异常 [{thread_name}]",
    )


def _asyncio_exception_handler(loop, context: dict) -> None:
    """asyncio 事件循环内未处理异常"""
    exc = context.get("exception")
    message = context.get("message", "")
    if exc is not None:
        log_crash(
            type(exc),
            exc,
            exc.__traceback__,
            context=f"asyncio 未处理异常: {message}",
        )
    else:
        try:
            with open(get_crash_log_path(), "a", encoding="utf-8", errors="replace") as f:
                f.write(
                    f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"asyncio 异常(无 exception 对象): {context}\n"
                )
        except Exception:
            pass
    # 保留默认行为(打印到控制台)
    try:
        loop.default_exception_handler(context)
    except Exception:
        pass


def install_crash_handlers(install_asyncio: bool = True) -> None:
    """安装全部未捕获异常钩子(幂等)"""
    global _installed
    if _installed:
        return

    try:
        sys.excepthook = _excepthook
    except Exception:
        pass

    try:
        threading.excepthook = _thread_excepthook  # type: ignore[assignment]
    except Exception:
        pass

    if install_asyncio:
        try:
            import asyncio

            loop = asyncio.get_event_loop_policy().get_event_loop()
            loop.set_exception_handler(_asyncio_exception_handler)
        except Exception:
            # 事件循环尚未创建时忽略，稍后由 attach_asyncio_handler 补挂
            pass

    _installed = True


def attach_asyncio_handler(loop=None) -> None:
    """给指定事件循环挂上异常处理器(供 lifespan 内调用)"""
    try:
        import asyncio

        loop = loop or asyncio.get_running_loop()
        loop.set_exception_handler(_asyncio_exception_handler)
    except Exception:
        pass


# =============================================================================
# stderr 镜像: uvicorn 的 traceback 直接写 stderr，必须同步落盘
# =============================================================================
class _TeeStream:
    """把写入 stderr 的内容同时复制一份到文件"""

    def __init__(self, original: TextIO, mirror_path: Path):
        self._original = original
        self._mirror_path = mirror_path
        self._lock = threading.Lock()

    def write(self, data: str) -> int:
        try:
            self._original.write(data)
        except Exception:
            pass
        if data and data.strip():
            try:
                with self._lock:
                    with open(self._mirror_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self._original.fileno()

    def __getattr__(self, item):
        return getattr(self._original, item)


def mirror_stderr_to_file(path: Optional[Path] = None) -> Optional[Path]:
    """把 stderr 镜像到文件(幂等)。

    uvicorn 启动失败时的 traceback 走 stderr 而非 logging，
    不镜像就会随控制台窗口一起消失。
    """
    global _stderr_mirror
    if _stderr_mirror is not None:
        return None
    try:
        target = path or (get_log_dir() / BOOTSTRAP_LOG_NAME)
        tee = _TeeStream(sys.stderr, target)
        sys.stderr = tee  # type: ignore[assignment]
        _stderr_mirror = tee  # type: ignore[assignment]
        return target
    except Exception:
        return None


# =============================================================================
# 启动引导日志
# =============================================================================
def bootstrap_logging(
    level: str = "INFO",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    mirror_stderr: bool = True,
) -> Path:
    """在进程最早期建立文件日志(必须早于任何 app.* 模块导入)。

    与 `app.utils.logger.setup_logging` 的分工:
    - 本函数只保证"有文件可写"，让 import 阶段的崩溃有迹可循;
    - 后续 `setup_logging` 会按用户配置重建 handler，两者不冲突
      (本函数挂的 handler 带标记，重建时会被识别并保留)。

    Returns:
        主日志文件路径。
    """
    import logging

    log_dir = get_log_dir()
    log_path = log_dir / "app.log"

    try:
        root = logging.getLogger()
        root.setLevel(getattr(logging, level.upper(), logging.INFO))

        # 避免重复挂载
        for h in root.handlers:
            if getattr(h, "_mdcx_bootstrap", False):
                return log_path

        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=False,  # 立即建文件，便于确认日志系统已就绪
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        handler._mdcx_bootstrap = True  # type: ignore[attr-defined]
        root.addHandler(handler)

        logging.getLogger("mdcx.bootstrap").info(
            "=== 启动引导日志已就绪 (PID=%s, 日志目录=%s) ===", os.getpid(), log_dir
        )
    except Exception as e:  # pragma: no cover
        try:
            sys.__stderr__.write(f"[bootstrap_logging] 初始化失败: {e}\n")
        except Exception:
            pass

    if mirror_stderr:
        mirror_stderr_to_file()

    return log_path


def init_early_logging() -> Path:
    """一站式初始化: 引导日志 + 崩溃钩子 + stderr 镜像。

    在 `run.py` 的最开头调用即可。
    """
    log_path = bootstrap_logging()
    install_crash_handlers()

    # 进程正常退出时留一条尾记录，便于区分"崩溃退出"与"正常退出"
    def _on_exit() -> None:
        try:
            import logging

            logging.getLogger("mdcx.bootstrap").info("=== 进程退出 (PID=%s) ===", os.getpid())
        except Exception:
            pass

    try:
        atexit.register(_on_exit)
    except Exception:
        pass

    return log_path
