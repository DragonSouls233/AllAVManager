"""
FC2 扫描器
番号格式：FC2-123456 / FC2PPV-123456 / 纯数字
"""

import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner
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

            for root, dirs, files in os.walk(media_dir):
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

                    # 检查是否已存在
                    existing = await session.execute(select(Fc2Movie).where(Fc2Movie.code == code))
                    if existing.scalar_one_or_none():
                        continue

                    # 写入新影片记录
                    new_movie = Fc2Movie(
                        code=code,
                        title=Path(file_name).stem,
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
