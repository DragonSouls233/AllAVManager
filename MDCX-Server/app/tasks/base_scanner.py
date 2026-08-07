"""
扫描器基类
所有模块扫描器的公共基类
"""

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


# 视频目录中常见的资源文件名 → 数据中心标准名
_VIDEO_DIR_ASSETS = {
    # (源文件名, 目标相对名)
    "movie.nfo":      "movie.nfo",
    "poster.jpg":     "poster.jpg",
    "poster.png":     "poster.jpg",
    "fanart.jpg":     "fanart.jpg",
    "fanart.png":     "fanart.jpg",
    "cover.jpg":      "cover.jpg",
    "cover.png":      "cover.jpg",
    "thumb.jpg":      "thumb.jpg",
    "thumb.png":      "thumb.jpg",
    "landscape.jpg":  "cover.jpg",
    "backdrop.jpg":   "fanart.jpg",
    "background.jpg": "fanart.jpg",
    "folder.jpg":     "poster.jpg",
}

_MIN_ASSET_BYTES = 1024  # 小于 1KB 的视为无效文件


async def copy_video_assets_to_data_dir(
    video_file_path: str | Path,
    code: str,
    module_name: str = "jav",
) -> int:
    """将视频文件所在目录的 NFO + 封面资源复制到数据中心目录。

    触发时机：扫描器发现新视频并写入 DB 后立即调用（无需等网络刮削）。

    Args:
        video_file_path: 视频文件完整路径
        code: 番号（如 CJOD-507）
        module_name: 模块名（jav/fc2/...）

    Returns:
        成功复制的文件数
    """
    video_dir = Path(video_file_path).parent
    if not video_dir.exists():
        logger.debug(f"视频目录不存在: {video_dir}")
        return 0

    try:
        from app.config.manager import get_config_manager
        data_dir = get_config_manager().computed.data_dir
    except Exception:
        logger.warning("无法获取 data_dir，跳过视频资源复制")
        return 0

    target_dir = Path(data_dir) / "movies" / module_name / code
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src_name, dst_name in _VIDEO_DIR_ASSETS.items():
        src = video_dir / src_name
        if not src.exists():
            continue
        size = src.stat().st_size
        if src_name.endswith(".nfo"):
            # NFO 是文本元数据，通常很小（几百字节~数 KB），只看是否有内容，
            # 不能用图片的最小体积阈值，否则会被误判为「残缺文件」跳过
            if size == 0:
                logger.debug(f"跳过空 NFO: {src}")
                continue
        else:
            # 图片要求最小体积，避免复制残缺/无效文件
            if size < _MIN_ASSET_BYTES:
                logger.debug(f"跳过无效文件 (<1KB): {src}")
                continue
        dst = target_dir / dst_name
        try:
            shutil.copy2(src, dst)
            copied += 1
            logger.info(f"[{module_name}] 复制视频资源: {src_name} → {dst}")
        except Exception as e:
            logger.debug(f"复制失败 {src} → {dst}: {e}")

    return copied


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

    async def cleanup_orphans(self) -> int:
        """删除磁盘上已不存在影片的数据库记录，返回删除数量。

        扫描只做增量新增，这里用于同步"文件删除"事件：磁盘文件已消失但 DB 记录仍在，
        应将其删除并计入 removed，使统计反映真实净变化（新增 - 删除）。
        仅处理本模块 media_dirs 前缀下的记录，避免误删其它来源数据。
        """
        from app.db.module_db import ModuleDatabase
        from sqlalchemy import text

        db = ModuleDatabase.get_instance(self.module_name)
        session = await db.get_session()
        removed = 0
        try:
            result = await session.execute(text("SELECT id, file_path FROM movies"))
            rows = result.fetchall()
            if not rows:
                return 0
            dir_prefixes = [
                os.path.normcase(os.path.normpath(str(d))) for d in self.media_dirs
            ]
            to_delete = []
            for row in rows:
                fp = row[1]
                if not fp:
                    continue
                norm_fp = os.path.normcase(os.path.normpath(str(fp)))
                if not any(norm_fp.startswith(p) for p in dir_prefixes):
                    continue
                if not os.path.exists(norm_fp):
                    to_delete.append(row[0])
            for rid in to_delete:
                await session.execute(text("DELETE FROM movies WHERE id = :id"), {"id": rid})
                removed += 1
            if to_delete:
                await session.commit()
                logger.info(
                    f"模块 [{self.module_name}] 孤儿清理: 删除 {removed} 条已移除文件的记录"
                )
        except Exception as e:
            logger.warning(f"模块 [{self.module_name}] 孤儿清理失败: {e}")
        finally:
            await session.close()
        return removed
