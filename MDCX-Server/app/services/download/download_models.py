"""
下载模块通用数据模型
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DownloadResult:
    """通⽤下载结果"""
    success: bool = False
    file_path: Optional[str] = None
    file_size: int = 0
    title: Optional[str] = None
    url: Optional[str] = None
    duration: Optional[int] = None
    hash: Optional[str] = None
    error: Optional[str] = None
    engine: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class DownloadConfig:
    """通用下载配置"""
    output_dir: str = "./downloads"
    max_concurrent: int = 3
    max_retries: int = 3
    timeout: int = 300
    use_proxy: bool = True
    rate_limit: Optional[str] = None
    headers: dict = field(default_factory=dict)
    cookies: Optional[str] = None


@dataclass
class ProgressInfo:
    """下载进度信息"""
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0
    eta: float = 0.0
    percent: float = 0.0
    status: str = "downloading"
    engine: str = ""
    url: str = ""


@dataclass
class DownloadTask:
    """下载任务"""
    task_id: str = ""
    url: str = ""
    output_path: str = ""
    engine: str = ""
    status: str = "pending"
    progress: float = 0.0
    error: Optional[str] = None
    created_at: float = 0.0
    completed_at: Optional[float] = None
    metadata: dict = field(default_factory=dict)
