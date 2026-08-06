"""
扫描器基类
所有模块扫描器的公共基类
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
