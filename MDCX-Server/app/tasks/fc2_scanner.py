"""
FC2 扫描器
番号格式：FC2-123456 / FC2PPV-123456 / 纯数字
"""

import asyncio
import json
import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir, iter_media_entries, _file_size, detect_version_flags
from app.utils.logger import get_logger
from app.utils.nfo_fields import empty_nfo_fields, parse_nfo_fields

logger = get_logger(__name__)


def find_nfo_sibling(video_path: Path) -> Path | None:
    """找视频同目录的 NFO：先 {stem}.nfo，再退回通用 movie.nfo。

    只做两次 ``in`` 目录列表判断，不逐个 exists 探测（网络盘上每次 stat 都很贵）。
    """
    parent = video_path.parent
    try:
        entries = set(os.listdir(parent))
    except OSError:
        return None
    for cand in (f"{video_path.stem}.nfo", "movie.nfo"):
        if cand in entries:
            return parent / cand
    return None


def extract_fc2_code(filename: str) -> str | None:
    """从文件名提取 FC2 番号"""
    stem = Path(filename).stem
    patterns = [
        r'(FC2[-_]?PPV[-_]?(\d{5,7}))',
        r'(FC2[-_]?(\d{5,7}))',
        r'^(\d{6,7})$',
        r'[\[\(](\d{5,7})[\]\)]',
    ]
    for pattern in patterns:
        match = re.search(pattern, stem, re.IGNORECASE)
        if match:
            code = match.group(1).upper().replace("_", "-")
            if not code.startswith("FC2-"):
                code = f"FC2-{code}"
            return code
    return None


class Fc2Scanner(BaseScanner):
    """FC2 模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("fc2", media_dirs)

    async def scan(self) -> dict:
        """扫描 FC2 媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0, "errors": []}

        logger.info(f"[fc2] 扫描启动: media_dirs={[str(d) for d in self.media_dirs]}")
        for media_dir in self.media_dirs:
            try:
                logger.info(f"[fc2] 开始扫描目录: {media_dir}")
                dir_result = await self._scan_directory(media_dir)
                logger.info(
                    f"[fc2] 目录扫描完成: {media_dir} 共发现 {dir_result['total']} 个文件，"
                    f"新增 {dir_result.get('movies_added', 0)}"
                )
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["matched"] += dir_result["matched"]
                results["movies_added"] += dir_result.get("movies_added", 0)
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

        logger.info(
            f"[fc2] 扫描完成: 共发现 {results['total']} 个文件，新增 {results['movies_added']}，"
            f"错误 {len(results['errors'])} 个"
        )
        return results

    async def _scan_directory(self, media_dir: Path) -> dict:
        """扫描单个媒体目录并写入数据库"""
        result = {"total": 0, "scanned": 0, "matched": 0, "movies_added": 0}
        media_dir = Path(media_dir)

        from app.db.module_db import ModuleDatabase
        db = ModuleDatabase.get_instance("fc2")
        session = await db.get_session()
        try:
            from app.db.fc2_models import Fc2Movie
            from sqlalchemy import select

            # 性能修复：一次性载入已存在番号，避免每文件一次 SELECT 的 N+1 查询
            existing_codes: set[str] = set(
                (await session.execute(select(Fc2Movie.code))).scalars().all()
            )

            walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
            for root, dirs, files in walk_entries:
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    code = extract_fc2_code(file_name)
                    if not code:
                        continue
                    result["matched"] += 1

                    # 检查是否已存在（内存判重，避免 N+1 查询）
                    if code in existing_codes:
                        continue
                    existing_codes.add(code)

                    # 检测版本标记（-C 中文 / -U 无码 / -UC 无码中文 / -Leak 破解 / -4K）
                    flags = detect_version_flags(file_name)

                    # 🔴 旧实现完全不读 NFO，title 直接用文件名（FC2-4802082 这种
                    # 就是纯番号），把本地已存在的 premiered/plot/genre/runtime 全丢掉。
                    # 实测 G:\TEST 43 个 NFO：premiered 81%、genre 81%、runtime 79%、
                    # plot 39% —— 数据一直在磁盘上。解析实现见 app/utils/nfo_fields.py。
                    nfo_meta: dict = empty_nfo_fields()
                    nfo_path = find_nfo_sibling(file_path)
                    if nfo_path is not None:
                        nfo_meta = parse_nfo_fields(nfo_path)

                    genre_list = nfo_meta.get("genre") or []
                    tag_list = nfo_meta.get("tag") or []

                    # 写入新影片记录
                    new_movie = Fc2Movie(
                        code=code,
                        title=nfo_meta.get("title") or Path(file_name).stem,
                        original_title=nfo_meta.get("original_title"),
                        studio=nfo_meta.get("studio"),
                        maker=nfo_meta.get("maker"),
                        series=nfo_meta.get("series"),
                        plot=nfo_meta.get("plot"),
                        plot_short=nfo_meta.get("plot_short"),
                        release_date=nfo_meta.get("release_date"),
                        duration=nfo_meta.get("duration"),
                        rating=nfo_meta.get("rating"),
                        genre=json.dumps(genre_list, ensure_ascii=False) if genre_list else None,
                        tag=json.dumps(tag_list, ensure_ascii=False) if tag_list else None,
                        actor=",".join(nfo_meta["actors"]) if nfo_meta.get("actors") else None,
                        source="nfo" if nfo_path is not None else None,
                        file_path=str(file_path),
                        file_size=_file_size(file_path),
                        is_chinese=flags["is_chinese"],
                        is_uncensored=flags["is_uncensored"],
                        is_leak=flags["is_leak"],
                        is_4k=flags["is_4k"],
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1
                    if code:
                        # 并发受限（防整盘扫描时无限制 ensure_future 风暴拖死事件循环）
                        asyncio.ensure_future(
                            self._copy_limited(
                                copy_video_assets_to_data_dir(str(file_path), code, "fc2")
                            )
                        )

            await session.commit()
        finally:
            await session.close()

        # 演员关联表回填：2026-10-04 新增。
        # 本扫描器此前**完全没有**这个步骤（jav/uncensored/pornhub/chinese 都有），
        # 而 FC2 的 NFO 是带演员的（实测 5/5：KING POWER D / えぽす。/ オナキング），
        # 于是 fc2 库 movie_actors 恒为 0 行，"按演员查影片" 只能靠文本 LIKE 兜底。
        # 失败不中断扫描（基类内部已 try/except）。
        await self._sync_actor_links()

        return result
