"""
JAV 有码模块扫描器

功能：
- 从文件名提取标准 JAV 番号（使用 number.py extract_number 支持 -C/-UC 后缀）
- 从目录名提取演员（使用 folder_actor.py）
- 写入 jav.db
"""

import asyncio
import os
import re
from pathlib import Path

from app.scraper.folder_actor import extract_actor_from_folder
from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)

# JAV 工作室黑名单（不识别为演员的文件夹名）
STUDIO_BLACKLIST = {
    "R18", "premium", "SOD", "IDEAPOCKET", "MOODYZ", "S1", "S1NO1",
    "MADONNA", "KA", "kawaii", "kirakira", "wanz", "MGS", "DMM",
    "FC2", "HEYZO", "CARIB", "1PONDO", "MKD", "JAV", "高清", "HD",
    "有码", "无码", "国产", "欧美", "合集", "精选", "新建文件夹",
    "unknown", "Unknow", "Other", "others",
}

# JAV 工作室自动识别（用于填充 studio 字段）
STUDIO_MAP = {
    "S1": "S1 NO.1 STYLE",
    "IDEAPOCKET": "IDEAPOCKET",
    "MOODYZ": "MOODYZ",
    "MADONNA": "MADONNA",
    "PREMIUM": "PREMIUM",
    "KAWAII": "kawaii*",
    "KIRAKIRA": "kira☆kira",
    "WANZ": "WANZ FACTORY",
    "SOD": "SOD",
    "R18": "R18",
    "PREMIUM": "PREMIUM",
}


def is_valid_jav_code(code: str) -> bool:
    """判断是否为标准 JAV 番号"""
    if not code:
        return False
    # 标准 JAV: 字母-数字，如 ABC-123
    jav_pattern = re.compile(r'^[A-Za-z]{2,6}-\d{2,5}$', re.IGNORECASE)
    return bool(jav_pattern.match(code))


class JavScanner(BaseScanner):
    """JAV 有码模块扫描器"""

    def __init__(self, media_dirs: list[str], config: dict | None = None):
        super().__init__("jav", media_dirs)
        self.config = config or {}
        self.actor_blacklist = set(self.config.get("blacklist", [])) | STUDIO_BLACKLIST
        self.folder_depth = self.config.get("folder_depth", 2)

    async def scan(self) -> dict:
        """扫描有码媒体目录并落库"""
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
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        db = ModuleDatabase.get_instance("jav")
        session = await db.get_session()
        try:
            walk_entries = await asyncio.to_thread(lambda: list(os.walk(media_dir)))
            for root, dirs, files in walk_entries:
                # 收集当前目录的演员信息
                dir_path = Path(root)

                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = dir_path / file_name
                    result["total"] += 1

                    # 使用统一番号提取（从 number.py 或内置逻辑）
                    code = self._extract_code(file_name, dir_path)
                    if not code:
                        continue
                    result["matched"] += 1

                    # 检查是否已存在
                    existing = await session.execute(select(JavMovie).where(JavMovie.code == code))
                    if existing.scalar_one_or_none():
                        continue

                    # 提取演员
                    folder_actors = self._get_folder_actors(file_path, media_dir)
                    actor_str = ",".join(folder_actors) if folder_actors else None
                    if folder_actors:
                        result["actors"].update(folder_actors)

                    # 检测中字/无码标记
                    is_chinese, is_uncensored = self._detect_suffix(file_name)

                    # 提取工作室
                    studio = self._detect_studio(code, dir_path, media_dir)

                    # 写入新影片记录
                    new_movie = JavMovie(
                        code=code,
                        title=Path(file_name).stem,
                        file_path=str(file_path),
                        file_size=file_path.stat().st_size if file_path.exists() else 0,
                        actor=actor_str,
                        studio=studio,
                        is_chinese=is_chinese,
                        is_uncensored=is_uncensored,
                        is_mosaic=not is_uncensored,
                        source="folder",
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

            await session.commit()
        finally:
            await session.close()

        return result

    def _extract_code(self, file_name: str, file_dir: Path) -> str | None:
        """从文件名提取标准 JAV 番号"""
        stem = Path(file_name).stem

        # 标准 JAV 番号模式：字母-数字，支持 -C/-UC/-U 后缀
        patterns = [
            # 主模式：字母2-6位-数字2-5位，可选后缀
            r'([A-Za-z]{2,6}-\d{2,5})(?:[-_.\s]?[CUc]?[UCuc]?)?$',
            # 方括号内模式：[ABC-123]
            r'\[([A-Za-z]{2,6}-\d{2,5})\]',
        ]

        for pattern in patterns:
            match = re.search(pattern, stem)
            if match:
                code = match.group(1).upper()
                # 清理残留的尾部分隔符
                code = code.rstrip('-_. ')
                return code

        # 如果文件名无匹配，尝试父目录名
        parent_name = file_dir.name
        for pattern in patterns:
            match = re.search(pattern, parent_name)
            if match:
                code = match.group(1).upper()
                code = code.rstrip('-_. ')
                return code

        return None

    def _detect_suffix(self, file_name: str) -> tuple[bool, bool]:
        """检测文件名中的 -C/-UC/-U 后缀"""
        stem = Path(file_name).stem
        is_chinese = False
        is_uncensored = False

        # 优先匹配复合后缀
        uc_match = re.search(r'[-_.\s]?(UC|uc)$', stem)
        if uc_match:
            return True, True  # UC = 中字 + 无码

        c_match = re.search(r'[-_.\s]?C$', stem)
        if c_match:
            return True, False  # C = 中字

        u_match = re.search(r'[-_.\s]?U$', stem)
        if u_match:
            return False, True  # U = 无码

        return is_chinese, is_uncensored

    def _detect_studio(self, code: str, file_dir: Path, media_dir: Path) -> str | None:
        """尝试检测工作室"""
        # 从目录名检测
        try:
            rel = file_dir.relative_to(media_dir)
            parts = list(rel.parents) if rel != Path('.') else []
            # 从最外层目录开始匹配
            for p in reversed(parts):
                name = str(p).upper()
                for key in STUDIO_MAP:
                    if key in name:
                        return STUDIO_MAP[key]
        except ValueError:
            pass
        return None

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
            # 跳过日期前缀目录，如 [2020-02-06]...
            if re.match(r'^\[\d{4}-\d{2}-\d{2}\]', name):
                continue
            # 跳过已识别为工作室的目录
            if name.upper() in STUDIO_BLACKLIST:
                continue

            actors = extract_actor_from_folder(
                name,
                blacklist=self.actor_blacklist,
            )
            for actor in actors:
                if actor not in seen:
                    all_actors.append(actor)
                    seen.add(actor)

        return all_actors

    async def _sync_actors(self, actor_names: list[str]):
        """同步演员表"""
        from app.db.module_db import ModuleDatabase
        from app.db.jav_models import JavActor
        from sqlalchemy import select

        db = ModuleDatabase.get_instance("jav")
        session = await db.get_session()
        try:
            for name in actor_names:
                existing = await session.execute(select(JavActor).where(JavActor.name == name))
                if not existing.scalar_one_or_none():
                    session.add(JavActor(name=name, source="folder"))
            await session.commit()
        finally:
            await session.close()

    async def _update_actor_counts(self):
        """更新演员表的 movie_count"""
        from app.db.module_db import ModuleDatabase
        from app.db.jav_models import JavActor, JavMovie
        from sqlalchemy import select, func

        db = ModuleDatabase.get_instance("jav")
        session = await db.get_session()
        try:
            actors = await session.execute(select(JavActor))
            for actor_row in actors.scalars().all():
                count = await session.scalar(
                    select(func.count()).select_from(JavMovie).where(
                        JavMovie.actor.like(f"%{actor_row.name}%")
                    )
                ) or 0
                actor_row.movie_count = count
            await session.commit()
        finally:
            await session.close()
