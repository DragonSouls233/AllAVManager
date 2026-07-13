"""
PORNHub 扫描器
番号格式：ph1234567890abcdef（viewkey）
"""

import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_pornhub_code(filename: str) -> str | None:
    """从文件名提取 PORNHub viewkey"""
    stem = Path(filename).stem
    pattern = r'(ph[a-f0-9]{10,20})'
    match = re.search(pattern, stem, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


class PornhubScanner(BaseScanner):
    """PORNHub 模块扫描器"""

    def __init__(self, media_dirs: list[str]):
        super().__init__("pornhub", media_dirs)

    async def scan(self) -> dict:
        results = {"total": 0, "scanned": 0, "matched": 0, "errors": []}
        for media_dir in self.media_dirs:
            try:
                videos = self.find_video_files(media_dir)
                results["total"] += len(videos)
                for v in videos:
                    results["scanned"] += 1
                    code = extract_pornhub_code(v.name)
                    if code:
                        results["matched"] += 1
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
        return results
