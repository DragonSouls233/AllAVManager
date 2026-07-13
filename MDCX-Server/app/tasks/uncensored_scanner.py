"""
JAV 无码扫描器
番号格式：HEYZO-1234 / 111111-111 / RED0123 / Caribbeancom
"""

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
        results = {"total": 0, "scanned": 0, "matched": 0, "errors": []}
        for media_dir in self.media_dirs:
            try:
                videos = self.find_video_files(media_dir)
                results["total"] += len(videos)
                for v in videos:
                    results["scanned"] += 1
                    info = extract_uncensored_code(v.name)
                    if info:
                        results["matched"] += 1
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
        return results
