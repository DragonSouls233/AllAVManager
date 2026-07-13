"""
日志工具(统一版本)

特性:
- 控制台彩色输出
- 文件轮转(RotatingFileHandler,5MB × 5 份)
- 错误日志单独文件(error.log)
- 兼容 server.py 和 app/main.py 调用

设计参考 mnamer(单一日志系统)+ Medusa(per-file-ignores 思想)。
本模块是项目唯一的日志初始化入口,server.py 应从此导入,
避免双轨制(server.py 豪华版 vs app/main.py 简陋版)。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# === 彩色日志格式 ===

class ColorFormatter(logging.Formatter):
    """控制台彩色格式化器"""

    # ANSI 颜色码
    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    BLUE = "\x1b[36;20m"
    RESET = "\x1b[0m"

    # 格式模板
    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # 级别 → 颜色 映射
    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.GREY)
        fmt = color + self.FORMAT + self.RESET
        formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def setup_logging(
    level: str = "INFO",
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_file: Optional[Path] = None,
    console: bool = True,
    error_log_file: Optional[Path] = None,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 5,
    use_color: bool = True,
) -> None:
    """
    统一日志初始化(项目唯一入口)

    Args:
        level: 日志级别("DEBUG"/"INFO"/"WARNING"/"ERROR"/"CRITICAL")
        log_format: 文件日志格式
        log_file: 主日志文件路径(若提供,启用轮转)
        console: 是否输出到控制台
        error_log_file: 错误日志单独文件(若提供,仅记录 ERROR+)
        max_bytes: 单文件最大字节数(默认 5MB)
        backup_count: 保留备份数(默认 5 份)
        use_color: 控制台是否彩色输出
    """
    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除现有处理器(避免重复)
    root_logger.handlers.clear()

    # 控制台处理器(彩色)
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        if use_color:
            console_handler.setFormatter(ColorFormatter())
        else:
            console_handler.setFormatter(logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))
        root_logger.addHandler(console_handler)

    # 主文件处理器(轮转)
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        file_handler.setFormatter(logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))
        root_logger.addHandler(file_handler)

    # 错误日志处理器(单独文件,仅 ERROR+)
    if error_log_file:
        error_log_file = Path(error_log_file)
        error_log_file.parent.mkdir(parents=True, exist_ok=True)
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))
        root_logger.addHandler(error_handler)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志器

    Args:
        name: 日志器名称(通常用 __name__)

    Returns:
        Logger 实例
    """
    return logging.getLogger(name)


class LogWriter:
    """
    日志写入器 - 可用于重定向 stdout/stderr
    """

    def __init__(self, logger: logging.Logger, level: int = logging.INFO):
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, message: str) -> None:
        if message.strip():
            self.logger.log(self.level, message.strip())

    def flush(self) -> None:
        pass
