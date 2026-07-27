"""
JAV 无码扫描器
番号格式：HEYZO-1234 / 111111-111 / RED0123 / Caribbeancom
支持从目录名提取演员
"""

import asyncio
import os
import re
from pathlib import Path

from app.scraper.folder_actor import extract_actor_from_folder
from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)

UNCENSORED_PREFIXES = [
    "HEYZO", "1PONDO", "CARIB", "CARIBBEAN", "10MU", "MUM",
    "TOKYO-HOT", "TOKYO HOT", "RED", "PACOPACOMAMA",
    "KIND", "GACHINCO", "LADY", "XXX", "S2M", "BT",
    "LAF", "SMD", "BURST", "MKD", "MUKD",
]


def extract_uncensored_code(filename: str) -> dict | None:
    """从文件名提取无码番号"""
    stem = Path(filename).stem.upper()
    for prefix in UNCENSORED_PREFIXES:
        pattern = rf'({prefix}[-_]?(\d{{2,6}}))'
        match = re.search(pattern, stem)
        if match:
            code = match.group(1).replace("_", "-")
            platform = prefix
            return {"code": code, "platform": platform}
    pattern = r'((\d{6})-(\d{3}))'
    match = re.search(pattern, stem)
    if match:
        return {"code": match.group(1), "platform": "unkn"}

    return None


# 无码目录中常见的非演员文件夹名黑名单
ACTOR_BLACKLIST = {
    "JAV", "无码", "uncensored", "HD", "高清", "合集", "精选",
    "新建文件夹", "unknown", "Other", "others",
}


class UncensoredScanner(BaseScanner):
    """无码模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("uncensored", media_dirs)
        self.folder_depth = 2  # 检查最近2层目录

    async def scan(self) -> dict:
        """扫描无码媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors": set(), "errors": []}

        for media_dir in self.media_dirs:
            try:
                dir_result = await self._scan_directory(media_dir)
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["matched"] += dir_result["matched"]
                results["movies_added"] += dir_result.get("movies_added", 0)
                if dir_result.get("actors"):
                    results["actors"].update(dir_result["actors"])
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

        # 同步演员表
        if results["actors"]:
            await self._sync_actors(list(results["actors"]))
            await self._update_actor_counts()

        results["actors"] = list(results["actors"])
        return results

    async def _scan_directory(self, media_dir: Path) -> dict:
        """扫描单个媒体目录并写入数据库"""
        result = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "actors": set()}
        media_dir = Path(media_dir)

        from app.db.module_db import ModuleDatabase
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select

        db = ModuleDatabase.get_instance("uncensored")
        session = await db.get_session()
        try:
            walk_entries = await asyncio.to_thread(lambda: list(os.walk(media_dir)))
            for root, dirs, files in walk_entries:
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    info = extract_uncensored_code(file_name)
                    if not info:
                        continue
                    result["matched"] += 1

                    code = info["code"]
                    platform = info.get("platform")

                    # 检查是否已存在
                    existing = await session.execute(select(UncensoredMovie).where(UncensoredMovie.code == code))
                    if existing.scalar_one_or_none():
                        continue

                    # 提取演员
                    folder_actors = self._get_folder_actors(file_path, media_dir)
                    actor_str = ",".join(folder_actors) if folder_actors else None
                    if folder_actors:
                        result["actors"].update(folder_actors)

                    # 写入新影片记录
                    new_movie = UncensoredMovie(
                        code=code,
                        title=Path(file_name).stem,
                        source_platform=platform,
                        actor=actor_str,
                        file_path=str(file_path),
                        file_size=file_path.stat().st_size if file_path.exists() else 0,
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

            await session.commit()
        finally:
            await session.close()

        return result

    def _get_folder_actors(self, file_path: Path, media_dir: Path) -> list[str]:
        """从目录路径提取演员"""
        try:
            rel_path = file_path.relative_to(media_dir)
        except ValueError:
            return []

        parts = list(rel_path.parents)[::-1]
        all_actors = []
        seen = set()

        # 检查最近2层目录
        check_folders = []
        for i in range(min(self.folder_depth, len(parts))):
            f = parts[-(i + 1)]
            if f is not None:
                check_folders.append(f)

        for folder in check_folders:
            name = folder.name if hasattr(folder, "name") else str(folder)
            # 跳过日期前缀目录
            if re.match(r'^\[\d{4}-\d{2}-\d{2}\]', name):
                continue
            if name in ACTOR_BLACKLIST:
                continue

            actors = extract_actor_from_folder(name, blacklist=ACTOR_BLACKLIST)
            for actor in actors:
                if actor not in seen:
                    all_actors.append(actor)
                    seen.add(actor)

        return all_actors

    async def _sync_actors(self, actor_names: list[str]):
        """同步演员表"""
        from app.db.module_db import ModuleDatabase
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select

        db = ModuleDatabase.get_instance("uncensored")
        session = await db.get_session()
        try:
            for name in actor_names:
                existing = await session.execute(select(UncensoredActor).where(UncensoredActor.name == name))
                if not existing.scalar_one_or_none():
                    session.add(UncensoredActor(name=name, source="folder"))
            await session.commit()
        finally:
            await session.close()

    async def _update_actor_counts(self):
        """更新演员表的 movie_count"""
        from app.db.module_db import ModuleDatabase
        from app.db.uncensored_models import UncensoredActor, UncensoredMovie
        from sqlalchemy import select, func

        db = ModuleDatabase.get_instance("uncensored")
        session = await db.get_session()
        try:
            actors = await session.execute(select(UncensoredActor))
            for actor_row in actors.scalars().all():
                count = await session.scalar(
                    select(func.count()).select_from(UncensoredMovie).where(
                        UncensoredMovie.actor.like(f"%{actor_row.name}%")
                    )
                ) or 0
                actor_row.movie_count = count
            await session.commit()
        finally:
            await session.close()
