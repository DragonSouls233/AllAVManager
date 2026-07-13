"""
常量定义
"""

from enum import Enum


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """任务类型"""
    SCRAPE = "scrape"  # 全量刮削
    IMPORT = "import"  # 导入已有刮削
    PATCH = "patch"    # 补刮
    SCAN = "scan"      # 目录扫描


class MovieStatus(str, Enum):
    """视频状态"""
    SCRAPED = "scraped"      # 已刮削
    PENDING = "pending"     # 待刮削
    FAILED = "failed"        # 刮削失败
    IMPORTED = "imported"    # 已导入
    PATCHED = "patched"      # 已补刮


class PatchType(str, Enum):
    """补刮类型"""
    IMAGES_ONLY = "images_only"       # 只补图片
    METADATA_ONLY = "metadata_only"   # 只补元数据
    FULL = "full"                     # 完整补刮
    CUSTOM = "custom"                  # 自定义字段


class ImportStatus(str, Enum):
    """导入状态"""
    PENDING = "pending"
    IMPORTED = "imported"
    CONFLICT = "conflict"
    FAILED = "failed"


# 默认配置
DEFAULT_PORT = 8420
DEFAULT_HOST = "0.0.0.0"
DEFAULT_LOG_LEVEL = "INFO"

# 目录名
CONFIG_DIR = "config"
DATABASE_DIR = "database"
CACHE_DIR = "cache"
LOGS_DIR = "logs"
BACKUPS_DIR = "backups"
