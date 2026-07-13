"""
文件扫描器

扫描目录，识别视频文件
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# 视频文件扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v",
    ".rm", ".rmvb", ".mpg", ".mpeg", ".ts", ".m2ts", ".webm",
}


@dataclass
class VideoFile:
    """视频文件信息"""
    path: str                           # 文件路径
    size: int                           # 文件大小（字节）
    name: str                           # 文件名
    
    # 元信息
    extension: Optional[str] = None     # 扩展名
    directory: Optional[str] = None     # 所在目录
    
    # 刮削状态（需要额外查询）
    scraped: bool = False               # 是否已刮削
    has_nfo: bool = False               # 是否有NFO


class FileScanner:
    """
    文件扫描器
    
    扫描目录识别视频文件
    """
    
    def __init__(
        self,
        extensions: Optional[set[str]] = None,
        exclude_dirs: Optional[set[str]] = None,
    ):
        """
        初始化
        
        Args:
            extensions: 视频扩展名集合
            exclude_dirs: 排除的目录名
        """
        self.extensions = extensions or VIDEO_EXTENSIONS
        self.exclude_dirs = exclude_dirs or {"sample", "samples", ".git", ".idea"}
    
    def scan(
        self,
        directory: str,
        recursive: bool = True,
    ) -> list[VideoFile]:
        """
        扫描目录
        
        Args:
            directory: 目录路径
            recursive: 是否递归扫描
            
        Returns:
            视频文件列表
        """
        dir_path = Path(directory)
        
        if not dir_path.exists():
            logger.warning(f"Directory not found: {directory}")
            return []
        
        video_files = []
        
        # 扫描文件
        for file_path in dir_path.rglob("*") if recursive else dir_path.glob("*"):
            if not file_path.is_file():
                continue
            
            # 检查扩展名
            if file_path.suffix.lower() not in self.extensions:
                continue
            
            # 检查是否在排除目录
            if any(excluded in file_path.parts for excluded in self.exclude_dirs):
                continue
            
            # 创建视频文件对象
            video = VideoFile(
                path=str(file_path),
                size=file_path.stat().st_size,
                name=file_path.name,
                extension=file_path.suffix.lower(),
                directory=str(file_path.parent),
            )
            
            # 检查是否有NFO
            nfo_path = file_path.parent / "movie.nfo"
            video.has_nfo = nfo_path.exists()
            
            video_files.append(video)
        
        logger.info(f"Found {len(video_files)} video files in {directory}")
        
        return video_files
    
    def scan_unscraped(
        self,
        directory: str,
        recursive: bool = True,
    ) -> list[VideoFile]:
        """
        扫描未刮削的视频文件
        
        Args:
            directory: 目录路径
            recursive: 是否递归
            
        Returns:
            未刮削的视频文件列表
        """
        all_files = self.scan(directory, recursive)
        
        # 过滤未刮削的
        unscraped = [f for f in all_files if not f.has_nfo]
        
        logger.info(f"Found {len(unscraped)} unscraped video files")
        
        return unscraped
    
    def classify_by_directory(
        self,
        video_files: list[VideoFile],
    ) -> dict[str, list[VideoFile]]:
        """
        按目录分类
        
        Args:
            video_files: 视频文件列表
            
        Returns:
            目录 -> 文件列表 的映射
        """
        classified = {}
        
        for video in video_files:
            if video.directory not in classified:
                classified[video.directory] = []
            classified[video.directory].append(video)
        
        return classified
    
    def get_statistics(
        self,
        video_files: list[VideoFile],
    ) -> dict:
        """
        获取统计信息
        
        Args:
            video_files: 视频文件列表
            
        Returns:
            统计信息
        """
        total_size = sum(f.size for f in video_files)
        scraped_count = sum(1 for f in video_files if f.has_nfo)
        
        return {
            "total_count": len(video_files),
            "total_size": total_size,
            "total_size_gb": total_size / (1024**3),
            "scraped_count": scraped_count,
            "unscraped_count": len(video_files) - scraped_count,
            "scraped_percentage": (scraped_count / len(video_files) * 100) if video_files else 0,
        }


def scan_videos(
    directory: str,
    recursive: bool = True,
) -> list[VideoFile]:
    """
    扫描视频文件的便捷函数
    
    Args:
        directory: 目录路径
        recursive: 是否递归
        
    Returns:
        视频文件列表
    """
    scanner = FileScanner()
    return scanner.scan(directory, recursive)