"""
媒体工具函数：收集媒体目录、搜索视频/图片文件等
供 movies.py、actors.py 等路由模块共用
"""

import logging
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)

# 视频文件扩展名集合（不含大写，比较前统一小写）
VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".webm"}

# 图片文件扩展名集合
IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# 标准封面图片文件名（按优先级排序）
STANDARD_COVER_NAMES: tuple = ("poster.jpg", "cover.jpg", "fanart.jpg", "thumb.jpg")

# 标准头像子目录名
AVATAR_SUB_DIRS: tuple = ("actors", "actor_avatars", "avatars", ".actors", ".avatars")

# 所有模块名
_ALL_MODULES: tuple = ("jav", "uncensored", "fc2", "chinese", "pornhub", "western")


def collect_media_dirs(cfg) -> list[str]:
    """
    收集所有可用的媒体目录：
    1. scraper.media_dirs（旧配置）
    2. 所有模块的 media_dirs（无论是否启用，用于封面/头像等文件搜索兜底）
    """
    dirs = []
    # 旧配置：scraper.media_dirs
    scraper_dirs = getattr(cfg.scraper, "media_dirs", None) or []
    dirs.extend(scraper_dirs)
    # 新配置：modules.*.media_dirs
    modules = getattr(cfg, "modules", None)
    if modules:
        for mod_name in _ALL_MODULES:
            mod = getattr(modules, mod_name, None)
            if mod:
                mod_dirs = getattr(mod, "media_dirs", None) or []
                dirs.extend(mod_dirs)
    # 去重并保留顺序
    seen: set = set()
    unique: list = []
    for d in dirs:
        normalized = d.rstrip("\\/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(d)
    return unique


def scan_media_dirs_for_cover(
    media_dirs: list[str],
    code: str,
    max_depth: int = 3,
) -> Optional[str]:
    """
    在 media_dirs 中搜索匹配番号的封面图片。

    搜索策略：
      1. 直接匹配 media_dir / <code> 目录下的标准封面图片
      2. 递归搜索（受 max_depth 限制）子目录名包含番号的目录
      3. 在上述目录中取第一张图片

    Args:
        media_dirs: 媒体目录列表
        code: 影片番号
        max_depth: 递归搜索最大深度（默认 3，避免全盘扫描）

    Returns:
        找到的封面文件路径（字符串）或 None
    """
    if not code:
        return None
    code_lower = code.lower()

    for d in media_dirs:
        d_path = Path(d)
        if not d_path.exists() or not d_path.is_dir():
            continue

        # 1) 直接匹配 d_path / code/
        code_dir = d_path / code
        if code_dir.exists() and code_dir.is_dir():
            result = _find_image_in_dir(code_dir)
            if result:
                return result
            continue  # 找到目录但无图片，跳过递归搜索

        # 2) 限制深度递归搜索
        code_dir = _find_code_subdir_depth_limited(d_path, code_lower, max_depth)
        if code_dir:
            result = _find_image_in_dir(code_dir)
            if result:
                return result
    return None


def scan_media_dirs_for_avatar(
    media_dirs: list[str],
    name: str,
    name_jp: Optional[str] = None,
) -> Optional[str]:
    """
    在 media_dirs 中搜索匹配演员名的头像文件。

    搜索模式：media_dir / (actors|actor_avatars|avatars|...) / {name}.jpg 等

    Args:
        media_dirs: 媒体目录列表
        name: 演员名
        name_jp: 演员日文名（可选）

    Returns:
        找到的头像文件路径（字符串）或 None
    """
    if not name:
        return None
    name_lower = name.lower()

    for d in media_dirs:
        base = Path(d)
        if not base.exists():
            continue
        for sub_dir_name in AVATAR_SUB_DIRS:
            actor_dir = base / sub_dir_name
            if not actor_dir.exists() or not actor_dir.is_dir():
                continue
            try:
                for fp in actor_dir.iterdir():
                    if fp.is_file() and fp.suffix.lower() in IMAGE_EXTENSIONS:
                        fname = fp.stem.lower()
                        if name_lower in fname or (name_jp and name_jp.lower() in fname):
                            return str(fp)
            except Exception:
                continue
    return None


def search_video_in_media_dirs(media_dirs: list[str], code_lower: str) -> Optional[str]:
    """
    在 media_dirs 中递归搜索匹配番号的视频文件。

    限制最大深度以避免全盘扫描。
    """
    for d in media_dirs:
        base = Path(d)
        if not base.exists():
            continue
        try:
            for f in _walk_depth_limited(base, max_depth=4):
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                    fname = f.stem.lower()
                    if code_lower in fname:
                        logger.info("在 media_dirs 中找到视频文件: %s", f)
                        return str(f)
        except Exception as e:
            logger.warning("搜索媒体目录 %s 时出错: %s", d, e)
            continue
    return None


# ==================== 内部辅助函数 ====================


def _walk_depth_limited(base: Path, max_depth: int):
    """
    限制深度的目录遍历生成器。
    生成 base 下深度不超过 max_depth 的所有文件/目录路径。
    """
    # 使用列表而非递归，避免深度递归的栈溢出
    stack = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            for child in current.iterdir():
                yield child
                if child.is_dir():
                    stack.append((child, depth + 1))
        except PermissionError:
            continue
        except OSError:
            continue


def _find_code_subdir_depth_limited(base: Path, code_lower: str, max_depth: int) -> Optional[Path]:
    """
    在 base 下搜索子目录名包含 code_lower 的目录，深度不超过 max_depth。
    """
    stack = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            for child in current.iterdir():
                if child.is_dir():
                    if code_lower in child.name.lower():
                        return child
                    stack.append((child, depth + 1))
        except PermissionError:
            continue
        except OSError:
            continue
    return None


def _find_image_in_dir(directory: Path) -> Optional[str]:
    """
    在目录中搜索标准封面图片，若无则取第一张图片文件。
    返回文件路径字符串或 None。
    """
    # 先搜索标准文件名
    for img_name in STANDARD_COVER_NAMES:
        img_path = directory / img_name
        if img_path.exists() and img_path.is_file():
            return str(img_path)
    # 再取任意第一张图片
    try:
        for fp in sorted(directory.iterdir()):
            if fp.is_file() and fp.suffix.lower() in IMAGE_EXTENSIONS:
                return str(fp)
    except Exception:
        pass
    return None
