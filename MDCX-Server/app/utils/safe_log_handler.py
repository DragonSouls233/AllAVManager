"""日志 handler 安全封装（防轮转自锁刷屏）。

背景（2026-09-24 服务端 192.168.10.110 排查）：
    E:\\MDCX-Server\\data\\logs\\app.log 长期刷屏 "--- Logging error ---"
        PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问。
        '...\\app.log' -> '...\\app.log.1'   (logging.handlers.doRollover)

    原因：同一进程内 app.log 被多个 RotatingFileHandler 同时持有
      - crash_logger.bootstrap_logging() 的引导 handler（run.py 最早期挂上）
      - log_config.LOGGING_CONFIG 的 "file" handler（uvicorn dictConfig 挂到
        app / uvicorn / root 等命名 logger 上）
      - logger.setup_logging() 在 lifespan 内又重建的 handler
    uvicorn 的 dictConfig 会先移除 root 上的引导 handler，导致
    logger.setup_logging() 里的「复用 bootstrap」判断失效，于是 dictConfig 的
    "file"(在命名 logger 上) 与 setup_logging 新建的 handler(root 上) 并存，
    两个句柄同时打开 app.log；任一 handler 到 5MB 触发轮转时 os.rename 被
    另一个句柄锁住 -> 每写一条日志就抛出完整堆栈（startup.log 实测 4.2 万+ 条）。

本模块提供两个工具：
    1. SafeRotatingFileHandler —— 轮转失败（文件被占用）时**不抛异常、不刷屏**，
       并保证 stream 仍然可用（超类在 rename 失败时不会重开 stream）。
    2. dedupe_file_handlers(path) —— 把同一路径上的多个 handler 归并为单实例，
       多余句柄从所属 logger 摘除并 close，从根本上消除自锁。
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SafeRotatingFileHandler(RotatingFileHandler):
    """轮转失败时安全退化，绝不因 Windows 文件占用而刷屏。"""

    def doRollover(self):  # noqa: D401
        try:
            super().doRollover()
        except OSError as exc:  # WinError 32 / 13 等
            # 超类在 os.rename 失败后不会重开 stream，必须补上，
            # 否则后续 emit 会因 self.stream is None 再次报错。
            if self.stream is None:
                try:
                    self.stream = self._open()
                except Exception:
                    pass
            # 同一处失败只提示一次，避免日志系统自身刷屏
            if not getattr(self, "_mdcx_rollover_warned", False):
                self._mdcx_rollover_warned = True
                try:
                    sys.stderr.write(
                        f"[logging] 日志轮转暂时失败，跳过本次并继续追加: {exc}\n"
                    )
                except Exception:
                    pass


def _iter_all_loggers():
    """遍历 root 与所有命名 logger（去重）。"""
    yield logging.getLogger()
    seen = set()
    for lg in list(logging.root.manager.loggerDict.values()):
        if isinstance(lg, logging.Logger) and id(lg) not in seen:
            seen.add(id(lg))
            yield lg


def _path_matches(handler, target: Path) -> bool:
    bf = getattr(handler, "baseFilename", None)
    if not bf:
        return False
    try:
        return Path(bf).resolve() == target
    except Exception:
        return False


def find_file_handler(path):
    """返回指向 path 的第一个文件 handler（不修改任何 logger），无则 None。"""
    target = Path(path).resolve()
    for lg in _iter_all_loggers():
        for h in list(lg.handlers):
            if _path_matches(h, target):
                return h
    return None


def dedupe_file_handlers(path):
    """归并指向 path 的所有文件 handler，返回保留的单实例（无则 None）。

    - 保留第一个找到的 handler；
    - 其余同路径 handler 从所有 logger 上摘除并 close（释放句柄）；
    - 保证保留的 handler 仍挂在「原本引用过同路径 handler」的所有 logger 上，
      避免因去重导致某命名 logger 丢失文件日志。
    """
    target = Path(path).resolve()
    refs = []  # [(logger, handler)]
    for lg in _iter_all_loggers():
        for h in list(lg.handlers):
            if _path_matches(h, target):
                refs.append((lg, h))
    if not refs:
        return None

    handlers = []
    seen = set()
    for _, h in refs:
        if id(h) not in seen:
            seen.add(id(h))
            handlers.append(h)
    keep = handlers[0]

    # 摘除并关闭多余句柄
    for h in handlers[1:]:
        for lg in _iter_all_loggers():
            if h in lg.handlers:
                lg.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    # 保证保留的 handler 仍覆盖所有原先引用同路径 handler 的 logger
    owners = []
    for lg, _ in refs:
        if lg not in owners:
            owners.append(lg)
    for lg in owners:
        if keep not in lg.handlers:
            lg.addHandler(keep)

    # 确定性关闭「已脱离所有 logger」的同路径陈旧 handler（典型：uvicorn dictConfig
    # 用 configure_root 从 root 移除、但未 close 的 bootstrap handler）。否则它残留的
    # 文件句柄仍会锁住 app.log，使后续轮转继续 PermissionError。
    try:
        from app.utils.crash_logger import get_bootstrap_handlers

        for h in get_bootstrap_handlers():
            if h is keep or not _path_matches(h, target):
                continue
            if any(h in lg.handlers for lg in _iter_all_loggers()):
                continue
            try:
                h.close()
            except Exception:
                pass
    except Exception:
        pass

    return keep
