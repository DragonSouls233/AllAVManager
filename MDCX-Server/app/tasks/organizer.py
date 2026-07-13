"""
智能文件整理

重命名、分类、移动视频文件
"""

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.scraper.number import extract_number

logger = logging.getLogger(__name__)


@dataclass
class OrganizeConfig:
    """整理配置"""
    # 重命名格式
    # 可用变量: {code}, {title}, {actor}, {studio}, {year}, {month}, {day}
    rename_format: str = "{code}"
    
    # 目录结构
    # 可用变量: {code}, {first_actor}, {studio}, {year}
    directory_format: str = "{code}"
    
    # 是否移动文件
    move_files: bool = True
    
    # 目标目录
    output_dir: str = ""
    
    # 是否覆盖已存在的文件
    overwrite: bool = False
    
    # 失败文件目录
    failed_dir: str = "failed"


class FileOrganizer:
    """
    文件整理器
    
    根据刮削结果重命名和移动文件
    """
    
    # 非法文件名字符
    ILLEGAL_CHARS = '<>:"/\\|?*'
    
    def __init__(self, config: Optional[OrganizeConfig] = None):
        """
        初始化
        
        Args:
            config: 整理配置
        """
        self.config = config or OrganizeConfig()
    
    def organize(
        self,
        file_path: str,
        code: Optional[str] = None,
        title: Optional[str] = None,
        actors: Optional[list[str]] = None,
        studio: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
    ) -> Optional[str]:
        """
        整理单个文件
        
        Args:
            file_path: 原文件路径
            code: 番号
            title: 标题
            actors: 演员列表
            studio: 制作商
            year: 年份
            month: 月份
            day: 日期
            
        Returns:
            新文件路径，失败返回 None
        """
        src_path = Path(file_path)
        
        if not src_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        
        # 提取番号（如果未提供）
        if not code:
            result = extract_number(src_path.name)
            code = result.number if result.number else "UNKNOWN"
        
        # 构建变量
        variables = {
            "code": code or "UNKNOWN",
            "title": title or "",
            "actor": actors[0] if actors else "",
            "first_actor": actors[0] if actors else "",
            "studio": studio or "",
            "year": str(year) if year else "",
            "month": f"{month:02d}" if month else "",
            "day": f"{day:02d}" if day else "",
        }
        
        # 生成新文件名
        new_name = self._format_string(self.config.rename_format, variables)
        new_name = self._sanitize_filename(new_name)
        
        # 保留原扩展名
        new_name = new_name + src_path.suffix.lower()
        
        # 生成新目录
        new_dir = self._format_string(self.config.directory_format, variables)
        new_dir = self._sanitize_filename(new_dir)
        
        # 构建目标路径
        if self.config.output_dir:
            base_dir = Path(self.config.output_dir)
        else:
            base_dir = src_path.parent
        
        dest_dir = base_dir / new_dir
        dest_path = dest_dir / new_name
        
        # 检查目标是否已存在
        if dest_path.exists() and not self.config.overwrite:
            logger.warning(f"Target already exists: {dest_path}")
            return None
        
        # 创建目录
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # 移动或复制文件
        try:
            if self.config.move_files:
                shutil.move(str(src_path), str(dest_path))
                logger.info(f"Moved: {src_path} -> {dest_path}")
            else:
                shutil.copy2(str(src_path), str(dest_path))
                logger.info(f"Copied: {src_path} -> {dest_path}")
            
            return str(dest_path)
        
        except Exception as e:
            logger.error(f"Organize error: {e}")
            return None
    
    def move_to_failed(self, file_path: str) -> Optional[str]:
        """
        移动到失败目录
        
        Args:
            file_path: 文件路径
            
        Returns:
            新文件路径
        """
        src_path = Path(file_path)
        
        if not src_path.exists():
            return None
        
        # 创建失败目录
        failed_dir = src_path.parent / self.config.failed_dir
        failed_dir.mkdir(parents=True, exist_ok=True)
        
        # 目标路径
        dest_path = failed_dir / src_path.name
        
        # 避免重名
        counter = 1
        while dest_path.exists():
            stem = src_path.stem
            dest_path = failed_dir / f"{stem}_{counter}{src_path.suffix}"
            counter += 1
        
        try:
            shutil.move(str(src_path), str(dest_path))
            logger.info(f"Moved to failed: {src_path} -> {dest_path}")
            return str(dest_path)
        
        except Exception as e:
            logger.error(f"Move to failed error: {e}")
            return None
    
    def organize_with_nfo(
        self,
        file_path: str,
        nfo_data: dict,
    ) -> Optional[str]:
        """
        根据 NFO 数据整理文件
        
        Args:
            file_path: 文件路径
            nfo_data: NFO 数据
            
        Returns:
            新文件路径
        """
        return self.organize(
            file_path=file_path,
            code=nfo_data.get("code"),
            title=nfo_data.get("title"),
            actors=nfo_data.get("actors", []),
            studio=nfo_data.get("studio"),
            year=nfo_data.get("year"),
            month=nfo_data.get("month"),
            day=nfo_data.get("day"),
        )
    
    def _format_string(self, template: str, variables: dict) -> str:
        """格式化字符串"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result
    
    def _sanitize_filename(self, name: str) -> str:
        """清理文件名"""
        # 移除非法字符
        for char in self.ILLEGAL_CHARS:
            name = name.replace(char, "")
        
        # 移除多余空格
        name = re.sub(r"\s+", " ", name)
        
        # 去除首尾空格和点
        name = name.strip(" .")
        
        # 限制长度
        if len(name) > 200:
            name = name[:200]
        
        return name


def organize_file(
    file_path: str,
    code: Optional[str] = None,
    title: Optional[str] = None,
    actors: Optional[list[str]] = None,
    studio: Optional[str] = None,
    year: Optional[int] = None,
    config: Optional[OrganizeConfig] = None,
) -> Optional[str]:
    """
    整理文件的便捷函数
    
    Args:
        file_path: 文件路径
        code: 番号
        title: 标题
        actors: 演员列表
        studio: 制作商
        year: 年份
        config: 配置
        
    Returns:
        新文件路径
    """
    organizer = FileOrganizer(config)
    return organizer.organize(
        file_path=file_path,
        code=code,
        title=title,
        actors=actors,
        studio=studio,
        year=year,
    )