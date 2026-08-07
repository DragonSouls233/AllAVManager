"""
JAV 无码扫描器
番号格式：HEYZO-1234 / 111111-111 / RED0123 / Caribbeancom / HEYDOUGA-xxx ...
统一使用中央 number.py 引擎识别番号（兼容下划线/横线、各种无码前缀），
并在扫描阶段把视频目录的 NFO + 封面 + 预览图归集到 data/movies/uncensored/{code}/，
同时识别番号与演员（目录名 + NFO）。
"""

import asyncio
import os
import re
from pathlib import Path

from app.scraper.folder_actor import extract_actor_from_folder
from app.scraper.number import (
    extract_number_from_path,
    is_uncensored,
    normalize_number,
)
from app.tasks.base_scanner import (
    BaseScanner,
    copy_video_assets_to_data_dir,
    find_local_cover,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 无码目录中常见的非演员文件夹名黑名单
ACTOR_BLACKLIST = {
    "JAV", "无码", "uncensored", "HD", "高清", "合集", "精选",
    "新建文件夹", "unknown", "Other", "others",
}


def _is_acceptable_code(code: str, stem: str) -> bool:
    """仅接受真实番号：无码类型，或文件名中字母与数字间确有分隔符的标准番号。

    避免把 gachig116 这类「字母+数字但无分隔符」的文件名误判为 GACHIG-116。
    """
    if not code:
        return False
    if is_uncensored(code):
        return True
    parts = code.split("-")
    if len(parts) >= 2:
        prefix, dig = parts[0], parts[1]
        if re.search(re.escape(prefix) + r"[-_.]" + re.escape(dig), stem, re.I):
            return True
    return False


def _extract_uncensored_code(file_path: Path) -> str | None:
    """从视频文件（含父目录回退）提取无码番号，使用中央 number.py 引擎。"""
    result = extract_number_from_path(str(file_path))
    if not result or not result.number:
        return None
    code = normalize_number(result.number)
    stem = Path(file_path.name).stem
    if not _is_acceptable_code(code, stem):
        return None
    return code


def _clean_text(s: str) -> str:
    """清洗 NFO 文本：去 CDATA 包裹与残留标签，折叠空白。"""
    if not s:
        return s
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_nfo_metadata(nfo_path: Path) -> dict:
    """从 movie.nfo 提取 title / actors / studio（正则容错，避免畸形 XML 崩溃）。"""
    meta: dict = {"title": None, "actors": [], "studio": None}
    try:
        text = nfo_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return meta
    # title
    m = re.search(r"<title>\s*(.*?)\s*</title>", text, re.DOTALL | re.IGNORECASE)
    if m:
        meta["title"] = _clean_text(m.group(1))
    # studio / maker
    for tag in ("studio", "maker"):
        m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL | re.IGNORECASE)
        if m and m.group(1).strip():
            meta["studio"] = _clean_text(m.group(1))
            break
    # actors
    seen: set[str] = set()
    for block in re.finditer(r"<actor\b[^>]*>(.*?)</actor>", text, re.DOTALL | re.IGNORECASE):
        nm = re.search(r"<name>\s*(.*?)\s*</name>", block.group(1), re.DOTALL | re.IGNORECASE)
        if nm:
            name = _clean_text(nm.group(1))
            if name and name not in seen:
                seen.add(name)
                meta["actors"].append(name)
    return meta


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
            # 性能修复：一次性载入已存在番号，避免每文件一次 SELECT 的 N+1 查询
            existing_codes: set[str] = set(
                (await session.execute(select(UncensoredMovie.code))).scalars().all()
            )

            walk_entries = await asyncio.to_thread(lambda: list(os.walk(media_dir)))
            for root, dirs, files in walk_entries:
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    code = _extract_uncensored_code(file_path)
                    if not code:
                        continue
                    result["matched"] += 1

                    # 检查是否已存在（内存判重，避免 N+1 查询）
                    if code in existing_codes:
                        continue
                    existing_codes.add(code)

                    # 提取演员：目录名 + NFO（合并去重）
                    folder_actors = self._get_folder_actors(file_path, media_dir)
                    actor_names = list(folder_actors)

                    # 解析同目录 NFO（兼容 movie.nfo 与 {番号}.nfo 两种命名）
                    video_dir = file_path.parent
                    nfo_meta: dict = {"title": None, "actors": [], "studio": None}
                    for nfo_candidate in (video_dir / "movie.nfo", video_dir / f"{file_path.stem}.nfo"):
                        if nfo_candidate.exists():
                            nfo_meta = _parse_nfo_metadata(nfo_candidate)
                            break
                    for a in nfo_meta.get("actors", []):
                        if a not in actor_names:
                            actor_names.append(a)

                    actor_str = ",".join(actor_names) if actor_names else None
                    if actor_names:
                        result["actors"].update(actor_names)

                    # 标题优先用 NFO 中的真实标题，否则回退文件名
                    title = nfo_meta.get("title") or Path(file_name).stem
                    studio = nfo_meta.get("studio")

                    # 本地封面（通用名或 {番号}-poster.jpg 等），回填 cover_url
                    cover_url = find_local_cover(file_path, code)

                    # 写入新影片记录
                    new_movie = UncensoredMovie(
                        code=code,
                        title=title,
                        source_platform="uncensored",
                        actor=actor_str,
                        studio=studio,
                        cover_url=cover_url,
                        file_path=str(file_path),
                        file_size=file_path.stat().st_size if file_path.exists() else 0,
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1

                    # 将视频目录的 NFO + 封面 + 预览图复制到数据中心目录
                    if code:
                        asyncio.ensure_future(
                            copy_video_assets_to_data_dir(str(file_path), code, "uncensored")
                        )

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
