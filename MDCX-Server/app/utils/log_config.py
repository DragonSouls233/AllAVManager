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
    },
    "loggers": {
        # ---- uvicorn 自身日志 ----
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        # ---- 应用日志 ----
        "app": {"handlers": ["default"], "level": "INFO", "propagate": False},
        # ---- 第三方日志（降低噪音） ----
        "apscheduler": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "httpx": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "httpcore": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "urllib3": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "selenium": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "PIL": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "pystray": {"handlers": ["default"], "level": "WARNING", "propagate": False},
    },
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
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
