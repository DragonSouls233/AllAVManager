"""
FC2 扫描器
番号格式：FC2-123456 / FC2PPV-123456 / 纯数字
"""

import asyncio
import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir, iter_media_entries, _file_size, detect_version_flags
from app.utils.logger import get_logger

logger = get_logger(__name__)


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

        for media_dir in self.media_dirs:
            try:
                dir_result = await self._scan_directory(media_dir)
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["matched"] += dir_result["matched"]
                results["movies_added"] += dir_result.get("movies_added", 0)
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

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

                    # 写入新影片记录
                    new_movie = Fc2Movie(
                        code=code,
                        title=Path(file_name).stem,
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

        return result
