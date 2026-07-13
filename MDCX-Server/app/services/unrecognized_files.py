"""未识别文件处理服务

扫描媒体目录中的视频文件，识别以下两类：
1. 无法提取番号的文件（文件名不符合番号规范）
2. 提取到番号但数据库中无对应记录的文件

支持的操作：
- 手动指定番号关联到现有 Movie
- 重命名文件（修正文件名后重新识别）
- 删除孤立文件

参考 nexus-media 的未识别文件处理 UI。
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, or_

from app.config.manager import get_config
from app.db.database import get_database
from app.db.models import Movie
from app.scraper.number import extract_number, normalize_number
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 视频扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v",
    ".rm", ".rmvb", ".mpg", ".mpeg", ".ts", ".m2ts", ".webm",
}

# 忽略的文件名模式（小写匹配）
IGNORE_PATTERNS = {
    "thumbs.db", "desktop.ini", ".ds_store", "__macosx",
}


class UnrecognizedFileService:
    """未识别文件处理服务"""

    def _should_ignore(self, filename: str) -> bool:
        """判断文件是否应忽略"""
        lower = filename.lower()
        for pattern in IGNORE_PATTERNS:
            if pattern in lower:
                return True
        return False

    async def scan_unrecognized(
        self,
        directories: Optional[list[str]] = None,
        scan_mode: str = "all",  # all / no_number / no_match
    ) -> dict:
        """扫描未识别的文件

        Args:
            directories: 要扫描的目录列表（None = 使用配置的 media_dirs）
            scan_mode: all=全部 / no_number=仅无法提取番号 / no_match=仅番号无匹配

        Returns:
            {
                "total_files": N,
                "no_number": [{path, filename, size, mtime}],
                "no_match": [{path, filename, size, mtime, extracted_number}],
                "scanned_dirs": [...],
            }
        """
        if directories is None:
            directories = get_config().scraper.media_dirs or []

        if not directories:
            return {"total_files": 0, "no_number": [], "no_match": [], "scanned_dirs": []}

        db = get_database()
        # 预取所有已识别的番号集合
        async with db.session() as session:
            result = await session.execute(select(Movie.code).where(Movie.code.is_not(None)))
            existing_codes = {row[0] for row in result.fetchall()}

            # 也查询所有已关联的文件路径
            result = await session.execute(select(Movie.file_path).where(Movie.file_path.is_not(None)))
            existing_paths = {row[0] for row in result.fetchall()}

        # 把同步的 rglob 扫描放到线程池中，避免阻塞 FastAPI 事件循环
        return await asyncio.to_thread(
            self._scan_sync,
            directories,
            existing_codes,
            existing_paths,
            scan_mode,
        )

    def _scan_sync(
        self,
        directories: list[str],
        existing_codes: set,
        existing_paths: set,
        scan_mode: str,
    ) -> dict:
        """同步扫描文件系统（在线程池中执行）"""

        no_number_files = []
        no_match_files = []
        total_files = 0

        for directory in directories:
            scan_dir = Path(directory)
            if not scan_dir.exists():
                continue

            for f in scan_dir.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                if self._should_ignore(f.name):
                    continue

                # 跳过已关联的文件
                file_path_str = str(f)
                if file_path_str in existing_paths:
                    continue

                total_files += 1

                try:
                    stat = f.stat()
                    size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                except OSError:
                    size = 0
                    mtime = None

                # 提取番号
                try:
                    number_result = extract_number(f.name)
                    extracted = number_result.number if number_result else None
                except Exception:
                    extracted = None

                file_info = {
                    "path": file_path_str,
                    "filename": f.name,
                    "size": size,
                    "mtime": mtime,
                    "size_mb": round(size / (1024 * 1024), 2) if size else 0,
                }

                if not extracted:
                    if scan_mode in ("all", "no_number"):
                        no_number_files.append(file_info)
                else:
                    normalized = normalize_number(extracted)
                    if normalized not in existing_codes:
                        if scan_mode in ("all", "no_match"):
                            file_info["extracted_number"] = normalized
                            no_match_files.append(file_info)

        logger.info(
            f"扫描完成: 共 {total_files} 个视频文件，"
            f"{len(no_number_files)} 个无法提取番号，{len(no_match_files)} 个番号无匹配"
        )

        return {
            "total_files": total_files,
            "no_number": no_number_files,
            "no_match": no_match_files,
            "scanned_dirs": directories,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    async def manual_link(
        self,
        file_path: str,
        movie_id: int,
    ) -> dict:
        """手动将文件关联到现有 Movie 记录

        Args:
            file_path: 文件路径
            movie_id: 目标 Movie ID

        Returns:
            {"ok": bool, "msg": str}
        """
        db = get_database()
        async with db.session() as session:
            movie = await session.get(Movie, movie_id)
            if not movie:
                return {"ok": False, "msg": f"Movie ID {movie_id} 不存在"}

            if not os.path.isfile(file_path):
                return {"ok": False, "msg": f"文件不存在: {file_path}"}

            movie.file_path = file_path
            try:
                movie.file_size = os.path.getsize(file_path)
            except OSError:
                pass

            await session.commit()
            logger.info(f"手动关联: {file_path} → Movie {movie_id} ({movie.code})")
            return {"ok": True, "msg": f"已关联到 {movie.code}"}

    async def manual_set_number(
        self,
        file_path: str,
        number: str,
        create_if_missing: bool = True,
    ) -> dict:
        """手动指定文件番号（用于修正识别错误）

        Args:
            file_path: 文件路径
            number: 指定的番号
            create_if_missing: 如果 Movie 不存在是否创建空记录

        Returns:
            {"ok": bool, "msg": str, "movie_id": int}
        """
        db = get_database()
        normalized = normalize_number(number)

        async with db.session() as session:
            # 查找现有 Movie
            result = await session.execute(
                select(Movie).where(Movie.code == normalized)
            )
            movie = result.scalar_one_or_none()

            if not movie and create_if_missing:
                # 创建空记录
                movie = Movie(
                    code=normalized,
                    title=Path(file_path).stem,
                    file_path=file_path,
                    file_size=os.path.getsize(file_path) if os.path.isfile(file_path) else 0,
                    status="pending",
                    source="manual",
                )
                session.add(movie)
                await session.commit()
                await session.refresh(movie)
                logger.info(f"创建新影片记录: {normalized} (手动指定)")
            elif not movie:
                return {"ok": False, "msg": f"番号 {normalized} 在数据库中不存在，且未开启自动创建"}
            else:
                # 已存在，关联文件
                movie.file_path = file_path
                try:
                    movie.file_size = os.path.getsize(file_path)
                except OSError:
                    pass

            await session.commit()
            return {
                "ok": True,
                "msg": f"已将文件关联到番号 {normalized}",
                "movie_id": movie.id,
                "code": movie.code,
            }

    async def rename_file(
        self,
        old_path: str,
        new_filename: str,
    ) -> dict:
        """重命名文件（修正文件名后可重新识别）

        Args:
            old_path: 原文件路径
            new_filename: 新文件名（不含目录）

        Returns:
            {"ok": bool, "msg": str, "new_path": str}
        """
        if not os.path.isfile(old_path):
            return {"ok": False, "msg": f"文件不存在: {old_path}"}

        # 安全检查：新文件名不能包含路径分隔符
        if "/" in new_filename or "\\" in new_filename or ".." in new_filename:
            return {"ok": False, "msg": "新文件名不能包含路径分隔符"}

        old_path_obj = Path(old_path)
        new_path = old_path_obj.parent / new_filename

        if new_path.exists():
            return {"ok": False, "msg": f"目标文件已存在: {new_path}"}

        try:
            old_path_obj.rename(new_path)
            logger.info(f"重命名: {old_path_obj.name} → {new_filename}")

            # 如果关联的 Movie 存在，更新 file_path
            db = get_database()
            async with db.session() as session:
                result = await session.execute(
                    select(Movie).where(Movie.file_path == old_path)
                )
                movie = result.scalar_one_or_none()
                if movie:
                    movie.file_path = str(new_path)
                    await session.commit()

            return {"ok": True, "msg": f"已重命名为 {new_filename}", "new_path": str(new_path)}
        except Exception as e:
            return {"ok": False, "msg": f"重命名失败: {e}"}

    async def delete_file(self, file_path: str) -> dict:
        """删除孤立文件

        Args:
            file_path: 文件路径

        Returns:
            {"ok": bool, "msg": str}
        """
        if not os.path.isfile(file_path):
            return {"ok": False, "msg": f"文件不存在: {file_path}"}

        try:
            os.remove(file_path)
            logger.info(f"删除孤立文件: {file_path}")
            return {"ok": True, "msg": "文件已删除"}
        except Exception as e:
            return {"ok": False, "msg": f"删除失败: {e}"}


# 全局单例
unrecognized_service = UnrecognizedFileService()


__all__ = ["unrecognized_service", "UnrecognizedFileService"]
