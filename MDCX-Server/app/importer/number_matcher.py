"""
番号匹配器

从 NFO 或目录名推断番号
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.importer.nfo_parser import ImportedMovie
from app.scraper.number import extract_number, NumberType

logger = logging.getLogger(__name__)


class NumberMatcher:
    """
    番号匹配器
    
    从多种来源推断番号：
    1. NFO 文件中的 id 字段
    2. 目录名
    3. 文件名
    """
    
    def match(
        self,
        nfo_data: Optional[ImportedMovie] = None,
        directory: Optional[str] = None,
        video_file: Optional[str] = None,
    ) -> tuple[Optional[str], float]:
        """
        匹配番号
        
        Args:
            nfo_data: NFO 数据
            directory: 目录路径
            video_file: 视频文件路径
            
        Returns:
            (番号, 置信度) 元组
        """
        candidates = []
        
        # 1. 从 NFO 提取
        if nfo_data and nfo_data.code:
            candidates.append((nfo_data.code, 0.95, "nfo_id"))
        
        # 2. 从目录名提取
        if directory:
            dir_name = os.path.basename(directory)
            result = extract_number(dir_name)
            if result.number and result.confidence > 0.5:
                candidates.append((result.number, result.confidence * 0.9, "directory"))
        
        # 3. 从视频文件名提取
        if video_file:
            file_name = os.path.basename(video_file)
            result = extract_number(file_name)
            if result.number and result.confidence > 0.5:
                candidates.append((result.number, result.confidence * 0.85, "file"))
        
        # 如果没有候选，返回 None
        if not candidates:
            return None, 0.0
        
        # 选择置信度最高的
        candidates.sort(key=lambda x: x[1], reverse=True)

        best_number, best_confidence, source = candidates[0]

        # 最终标准化：统一大写和分隔符
        if best_number:
            best_number = best_number.strip().upper().replace('_', '-')

        logger.debug(f"Matched number: {best_number} (confidence={best_confidence:.2f}, source={source})")

        return best_number, best_confidence
    
    def match_from_nfo(self, nfo_data: ImportedMovie) -> tuple[Optional[str], float]:
        """
        从 NFO 数据匹配番号
        
        Args:
            nfo_data: NFO 数据
            
        Returns:
            (番号, 置信度) 元组
        """
        # 直接使用 NFO 中的 id
        if nfo_data.code:
            return nfo_data.code, 0.95
        
        # 从标题推断
        if nfo_data.title:
            result = extract_number(nfo_data.title)
            if result.number:
                return result.number, result.confidence * 0.8
        
        return None, 0.0
    
    def match_from_directory(self, directory: str) -> tuple[Optional[str], float]:
        """
        从目录名匹配番号
        
        Args:
            directory: 目录路径
            
        Returns:
            (番号, 置信度) 元组
        """
        dir_name = os.path.basename(directory)
        result = extract_number(dir_name)
        
        if result.number:
            return result.number, result.confidence * 0.9
        
        return None, 0.0
    
    def match_from_file(self, file_path: str) -> tuple[Optional[str], float]:
        """
        从文件名匹配番号
        
        Args:
            file_path: 文件路径
            
        Returns:
            (番号, 置信度) 元组
        """
        file_name = os.path.basename(file_path)
        result = extract_number(file_name)
        
        if result.number:
            return result.number, result.confidence * 0.85
        
        return None, 0.0


def match_number_from_nfo(
    nfo_data: Optional[ImportedMovie] = None,
    directory: Optional[str] = None,
    video_file: Optional[str] = None,
) -> tuple[Optional[str], float]:
    """
    匹配番号的便捷函数
    
    Args:
        nfo_data: NFO 数据
        directory: 目录路径
        video_file: 视频文件路径
        
    Returns:
        (番号, 置信度) 元组
    """
    matcher = NumberMatcher()
    return matcher.match(nfo_data, directory, video_file)