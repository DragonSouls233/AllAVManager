"""
JAV 无码扫描器
番号格式：HEYZO-1234 / 111111-111 / RED0123 / Caribbeancom
"""

import os
import re
from pathlib import Path

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


class UncensoredScanner(BaseScanner):
    """无码模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("uncensored", media_dirs)

    async def scan(self) -> dict:
        """扫描无码媒体目录并落库"""
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
        db = ModuleDatabase.get_instance("uncensored")
        session = await db.get_session()
        try:
            from app.db.uncensored_models import UncensoredMovie
            from sqlalchemy import select

            for root, dirs, files in os.walk(media_dir):
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

                    # 写入新影片记录
                    new_movie = UncensoredMovie(
                        code=code,
                        title=Path(file_name).stem,
                        source_platform=platform,
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
