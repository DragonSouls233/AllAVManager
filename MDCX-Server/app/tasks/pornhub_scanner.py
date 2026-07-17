"""
PORNHub 扫描器
番号格式：ph1234567890abcdef（viewkey）
"""

import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_pornhub_code(filename: str) -> str | None:
    """从文件名提取 PORNHub viewkey

    支持格式:
      - phabcdef123456  (带 ph 前缀)
      - abcdef123456    (纯 viewkey，13 位 hex)
    """
    stem = Path(filename).stem
    # 优先匹配带 ph 前缀的
    pattern = r'(ph[a-f0-9]{10,20})'
    match = re.search(pattern, stem, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    # 回退匹配纯 13 位 hex (viewkey)
    pattern2 = r'\b([a-f0-9]{13})\b'
    match2 = re.search(pattern2, stem, re.IGNORECASE)
    if match2:
        return match2.group(1).lower()
    return None


class PornhubScanner(BaseScanner):
    """PORNHub 模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("pornhub", media_dirs)

    async def scan(self) -> dict:
        """扫描 PORNHub 媒体目录并落库"""
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
        db = ModuleDatabase.get_instance("pornhub")
        session = await db.get_session()
        try:
            from app.db.pornhub_models import PornhubMovie
            from sqlalchemy import select

            for root, dirs, files in os.walk(media_dir):
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    code = extract_pornhub_code(file_name)
                    if not code:
                        continue
                    result["matched"] += 1

                    # 检查是否已存在
                    existing = await session.execute(select(PornhubMovie).where(PornhubMovie.code == code))
                    if existing.scalar_one_or_none():
                        continue

                    # 写入新影片记录
                    new_movie = PornhubMovie(
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
