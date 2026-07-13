"""
FC2 扫描器
番号格式：FC2-123456 / FC2PPV-123456 / 纯数字
"""

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
        results = {"total": 0, "scanned": 0, "matched": 0, "errors": []}
        for media_dir in self.media_dirs:
            try:
                videos = self.find_video_files(media_dir)
                results["total"] += len(videos)
                for v in videos:
                    results["scanned"] += 1
                    code = extract_fc2_code(v.name)
                    if code:
                        results["matched"] += 1
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
        return results
