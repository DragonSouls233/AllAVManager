"""
日志配置模块 - uvicorn 日志中文化 + 日志格式定制
"""

import logging

# =============================================================================
# uvicorn 默认日志配置的中文定制版
# =============================================================================

# 标准时间格式
_TIME_FMT = "%Y-%m-%d %H:%M:%S"

# 自定义格式：时间 级别  消息
_CONSOLE_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_ACCESS_FMT = "%(asctime)s - %(levelname)s - %(client_addr)s ← %(request_line)s → %(status_code)s"

# =============================================================================
# 日志文件路径解析
# =============================================================================
# 2026-08-05 修复: 此前 LOGGING_CONFIG 的 handler 全部是 StreamHandler(控制台),
# 一个文件 handler 都没有; 且 "app" logger 设了 propagate=False, 导致即使
# root logger 挂了文件 handler, 应用日志也传不过去 —— 结果就是 app.log 长期
# 近乎空文件, 启动闪退时完全查不到原因。
# 这里为所有 logger 补上文件 handler, 让 uvicorn 的 traceback 和应用日志
# 都能落盘。
def _resolve_log_paths():
    """解析 app.log / error.log 的绝对路径(零依赖, 配置不可用时也能工作)"""
    try:
        from app.utils.crash_logger import get_log_dir

        log_dir = get_log_dir()
    except Exception:
        import os
        from pathlib import Path

        env_dir = os.environ.get("MDCX_DATA_DIR", "").strip()
        base = Path(env_dir) if env_dir else Path(__file__).resolve().parent.parent.parent / "data"
        log_dir = base / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            import tempfile

            log_dir = Path(tempfile.gettempdir()) / "mdcx-logs"
            log_dir.mkdir(parents=True, exist_ok=True)

    return str(log_dir / "app.log"), str(log_dir / "error.log")


_APP_LOG_PATH, _ERROR_LOG_PATH = _resolve_log_paths()

# 文件日志格式(不带 ANSI 颜色, 避免日志文件里全是转义码)
_FILE_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 控制台 + 文件的组合(应用与 uvicorn 错误都需要两者)
_BOTH = ["default", "file", "error_file"]

# uvicorn 默认使用 LOGGING_CONFIG 字典
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": _CONSOLE_FMT,
            "datefmt": _TIME_FMT,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": _ACCESS_FMT,
            "datefmt": _TIME_FMT,
        },
        # 文件专用: 纯文本, 无颜色转义
        "plain": {
            "format": _FILE_FMT,
            "datefmt": _TIME_FMT,
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        # ---- 文件 handler(追加模式 + 轮转, 崩溃现场不丢) ----
        "file": {
            "formatter": "plain",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": _APP_LOG_PATH,
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "level": "INFO",
        },
        # ---- 错误单独成文件, 排查时优先看这个 ----
        "error_file": {
            "formatter": "plain",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": _ERROR_LOG_PATH,
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "level": "ERROR",
        },
    },
    "loggers": {
        # ---- uvicorn 自身日志 ----
        # uvicorn.error 承载 "Application startup failed" 及完整 traceback,
        # 必须写文件, 否则控制台一关就永久丢失。
        "uvicorn": {"handlers": _BOTH, "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": _BOTH, "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access", "file"], "level": "INFO", "propagate": False},
        # ---- 应用日志 ----
        "app": {"handlers": _BOTH, "level": "INFO", "propagate": False},
        # ---- 启动引导日志(crash_logger 使用) ----
        "mdcx": {"handlers": _BOTH, "level": "INFO", "propagate": False},
        # ---- 第三方日志（降低噪音, 但错误仍需落盘） ----
        "apscheduler": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "httpx": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "httpcore": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "urllib3": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "selenium": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "PIL": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "pystray": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        # ---- SQLAlchemy 错误必须落盘(启动期 OperationalError 常出自这里) ----
        "sqlalchemy.engine": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
        "sqlalchemy.pool": {"handlers": _BOTH, "level": "WARNING", "propagate": False},
    },
    # root 也挂上文件, 兜住所有未单独配置的模块
    "root": {"handlers": _BOTH, "level": "INFO"},
}


# =============================================================================
# uvicorn 启动日志翻译过滤器
# =============================================================================
UVICORN_START_TRANSLATIONS = {
    "Started server process": "服务进程已启动",
    "Waiting for application startup": "正在启动应用...",
    "Application startup complete": "应用启动完成",
    "Uvicorn running on": "服务运行在",
    "Shutting down": "正在关闭服务",
    "Finished server process": "服务进程已结束",
    "Waiting for application shutdown": "正在关闭应用...",
    "Application shutdown complete": "应用已关闭",
}


class UvicornLogFilter(logging.Filter):
    """将 uvicorn 的英文启动日志翻译为中文"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for eng, chn in UVICORN_START_TRANSLATIONS.items():
            if eng in msg:
                record.msg = record.msg.replace(eng, chn)
                if record.args:
                    # 保持参数格式
                    record.msg = record.msg % record.args if isinstance(record.args, dict) else record.msg
                    record.args = ()
                break
        return True


# =============================================================================
# 应用日志过滤：标记重要/不重要的消息
# =============================================================================
IMPORTANT_TAGS = {
    "ERROR": "【错误】",
    "WARNING": "【警告】",
    "CRITICAL": "【严重】",
    "startup": "【启动】",
    "shutdown": "【关闭】",
}


# =============================================================================
# 应用配置函数
# =============================================================================
def setup_logging():
    """应用中文日志配置"""
    import logging.config
    logging.config.dictConfig(LOGGING_CONFIG)

    # 添加翻译过滤器到 uvicorn 日志器
    for logger_name in ["uvicorn", "uvicorn.error"]:
        logger = logging.getLogger(logger_name)
        logger.addFilter(UvicornLogFilter())

    # 设置根日志器级别
    # 2026-08-05 修复: 此前写死 WARNING, 把所有未单独配置模块的 INFO 日志
    # 全部压掉, 排查启动问题时看不到关键步骤。改为 INFO(错误仍会额外进
    # error.log)。
    root = logging.getLogger()
    root.setLevel(logging.INFO)
