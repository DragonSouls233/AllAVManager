"""
图片识别器

扫描目录，识别已有的图片文件：
- poster.jpg / poster.png
- fanart.jpg / fanart.png
- thumb.jpg
- extrafanart/*.jpg
- actors/*.jpg
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MovieImages:
    """电影图片信息"""
    # 主要图片
    poster: Optional[str] = None       # 封面
    fanart: Optional[str] = None       # 背景图
    thumb: Optional[str] = None        # 缩略图
    
    # 样图
    extrafanart: list[str] = field(default_factory=list)  # 额外剧照
    
    # 演员头像
    actors: dict[str, str] = field(default_factory=dict)  # 演员名 -> 头像路径
    
    # 目录路径
    directory: Optional[str] = None
    
    def has_images(self) -> bool:
        """是否有图片"""
        return bool(self.poster or self.fanart or self.extrafanart or self.actors)


class ImageScanner:
    """
    图片识别器
    
    扫描目录识别已有的图片文件
    """
    
    # 图片扩展名
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    
    # 封面文件名模式
    POSTER_NAMES = {"poster", "cover", "folder"}
    
    # 背景图文件名模式
    FANART_NAMES = {"fanart", "backdrop", "background", "art"}
    
    # 缩略图文件名模式
    THUMB_NAMES = {"thumb", "thumbnail", "landscape"}
    
    def scan(self, directory: str) -> MovieImages:
        """
        扫描目录
        
        Args:
            directory: 目录路径
            
        Returns:
            MovieImages 图片信息
        """
        dir_path = Path(directory)
        
        if not dir_path.exists():
            logger.warning(f"Directory not found: {directory}")
            return MovieImages(directory=directory)
        
        images = MovieImages(directory=directory)
        
        # 扫描主要图片
        self._scan_main_images(dir_path, images)
        
        # 扫描额外剧照
        self._scan_extrafanart(dir_path, images)
        
        # 扫描演员头像
        self._scan_actors(dir_path, images)
        
        return images
    
    def _scan_main_images(self, dir_path: Path, images: MovieImages) -> None:
        """扫描主要图片"""
        try:
            items = list(dir_path.iterdir())
        except (PermissionError, OSError):
            return

        # 第一遍：按语义命名精确匹配（poster/cover/folder、fanart、thumb 等）
        fallback_candidates: list[Path] = []
        for file_path in items:
            if not file_path.is_file():
                continue

            # 检查扩展名
            if file_path.suffix.lower() not in self.IMAGE_EXTENSIONS:
                continue

            stem = file_path.stem.lower()

            # 封面
            if stem in self.POSTER_NAMES:
                if images.poster is None:
                    images.poster = str(file_path)
                continue

            # 背景图
            if stem in self.FANART_NAMES:
                if images.fanart is None:
                    images.fanart = str(file_path)
                continue

            # 缩略图
            if stem in self.THUMB_NAMES:
                if images.thumb is None:
                    images.thumb = str(file_path)
                continue

            # 备用：如果文件名包含 "poster" 或 "fanart"
            if "poster" in stem and images.poster is None:
                images.poster = str(file_path)
            elif "fanart" in stem and images.fanart is None:
                images.fanart = str(file_path)
            else:
                # 未匹配到任何语义名：留作兜底候选（如 {番号}.jpg）
                fallback_candidates.append(file_path)

        # 第二遍（兜底）：若仍未找到封面，从目录里挑选最佳候选
        # 许多 JAV 目录的封面命名为 {番号}.jpg（如 GANA-2232.jpg），不含 poster 字样，
        # 旧逻辑会漏判导致 cover_url 为空 -> 前端显示占位图。这里兜底补上。
        if images.poster is None and fallback_candidates:
            code = self._extract_code(dir_path.name)
            best = None
            for fp in fallback_candidates:
                s = fp.stem.upper()
                if code and code.upper() in s:
                    best = fp
                    break
            if best is None:
                # 仍无精确匹配：取第一个图片（排除明显是剧照/演员图的，这里仅主目录层级）
                best = fallback_candidates[0]
            images.poster = str(best)

    @staticmethod
    def _extract_code(name: str) -> Optional[str]:
        """从目录名/文件名中提取番号（如 [2020-01-30][GANA-2232]... -> GANA-2232）"""
        import re
        m = re.search(r'([A-Za-z]{2,6})[-_ ]?(\d{2,5})', name)
        if m:
            return f"{m.group(1).upper()}-{m.group(2)}"
        return None
    
    def _scan_extrafanart(self, dir_path: Path, images: MovieImages) -> None:
        """扫描额外剧照"""
        extrafanart_dir = dir_path / "extrafanart"
        
        if extrafanart_dir.exists():
            try:
                for file_path in extrafanart_dir.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in self.IMAGE_EXTENSIONS:
                        images.extrafanart.append(str(file_path))
            except (PermissionError, OSError):
                pass
        
        # 也检查根目录下的 extrafanart*.jpg
        try:
            for file_path in dir_path.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in self.IMAGE_EXTENSIONS:
                    stem = file_path.stem.lower()
                    if stem.startswith("extrafanart") and stem not in self.FANART_NAMES:
                        images.extrafanart.append(str(file_path))
        except (PermissionError, OSError):
            pass
    
    def _scan_actors(self, dir_path: Path, images: MovieImages) -> None:
        """扫描演员头像"""
        actors_dir = dir_path / "actors"
        
        if not actors_dir.exists():
            return
        
        try:
            items = list(actors_dir.iterdir())
        except (PermissionError, OSError):
            return
        
        for file_path in items:
            if not file_path.is_file():
                continue
            
            if file_path.suffix.lower() not in self.IMAGE_EXTENSIONS:
                continue
            
            # 文件名作为演员名
            actor_name = file_path.stem
            
            # 清理文件名
            actor_name = self._clean_actor_name(actor_name)
            
            if actor_name:
                images.actors[actor_name] = str(file_path)
    
    def _clean_actor_name(self, name: str) -> str:
        """清理演员名"""
        # 移除常见后缀
        name = name.strip()
        
        # 移除括号内容
        import re
        name = re.sub(r"\([^)]*\)", "", name)
        name = re.sub(r"\[[^\]]*\]", "", name)
        
        return name.strip()


def scan_movie_images(directory: str) -> MovieImages:
    """
    扫描目录图片的便捷函数
    
    Args:
        directory: 目录路径
        
    Returns:
        MovieImages 图片信息
    """
    scanner = ImageScanner()
    return scanner.scan(directory)