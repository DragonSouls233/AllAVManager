"""
扫描器基类
所有模块扫描器的公共基类
"""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseScanner(ABC):
    """扫描器基类"""

    def __init__(self, module_name: str, media_dirs: list[str]):
        self.module_name = module_name
        self.media_dirs = [Path(d) for d in media_dirs if Path(d).exists()]
        self.video_extensions = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"}

    @abstractmethod
    async def scan(self) -> dict:
        """扫描媒体目录，返回扫描结果"""
        ...

    def find_video_files(self, directory: Path) -> list[Path]:
        """递归查找目录下的所有视频文件"""
        videos = []
        try:
            for f in directory.rglob("*"):
                if f.is_file() and f.suffix.lower() in self.video_extensions:
                    videos.append(f)
        except PermissionError:
            pass
        return videos

    def get_relative_path(self, file_path: Path) -> str:
        """获取相对于媒体目录的路径"""
        for media_dir in self.media_dirs:
            try:
                return str(file_path.relative_to(media_dir))
            except ValueError:
                continue
        return str(file_path)
