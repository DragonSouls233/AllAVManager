"""
国产模块扫描器
含文件夹演员识别核心功能
"""

import hashlib
import os
from pathlib import Path

from app.scraper.folder_actor import extract_actor_from_folder
from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)


def generate_chinese_code(file_path: Path, folder_actors: list[str]) -> str:
    """为国产视频生成唯一编码"""
    folder_part = "_".join(folder_actors) if folder_actors else "unknown"
    hash_part = hashlib.sha256(str(file_path).encode()).hexdigest()[:8]
    return f"CN-{folder_part}-{hash_part}"


def extract_code_from_filename(filename: str) -> str | None:
    """从国产视频文件名尝试提取番号"""
    import re
    patterns = [
        r'(MD-?\d+)', r'(TM-?\d+)', r'(91CM-?\d+)', r'(MKY-?\w+)',
        r'(SWAG[-_]\w+)', r'(REAL[-_]\w+)', r'(EDM-?\d+)',
        r'(HKD-?\d+)', r'(JVID-?\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return match.group(1).upper().replace("_", "-")
    return None


def extract_actor_from_filename(filename: str) -> str | None:
    """从国产视频文件名提取演员名"""
    import re
    stem = Path(filename).stem
    patterns = [
        r'[A-Z]+-?\d+[._\s]+([\u4e00-\u9fff]{2,4})',
        r'([\u4e00-\u9fff]{2,4})[._\s][A-Z]+',
    ]
    for pattern in patterns:
        match = re.search(pattern, stem)
        if match:
            return match.group(1)
    return None


class ChineseScanner(BaseScanner):
    """国产模块扫描器"""

    def __init__(self, media_dirs: list[str], config: dict | None = None):
        super().__init__("chinese", media_dirs)
        self.config = config or {}
        self.actor_blacklist = set(
            self.config.get("blacklist", [])
        ) | {"新建文件夹", "合集", "精选", "unknown", "未分类"}
        self.folder_depth = self.config.get("folder_depth", 1)
        self.studio_names_as_folder = self.config.get("studio_names_as_folder", False)

    async def scan(self) -> dict:
        """扫描国产媒体目录"""
        results = {"total": 0, "scanned": 0, "actors": set(), "errors": []}

        for media_dir in self.media_dirs:
            try:
                dir_result = await self._scan_directory(media_dir)
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["actors"].update(dir_result["actors"])
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

        results["actors"] = list(results["actors"])
        return results

    async def _scan_directory(self, media_dir: Path) -> dict:
        """扫描单个媒体目录"""
        result = {"total": 0, "scanned": 0, "actors": set()}

        for root, dirs, files in os.walk(media_dir):
            for file_name in files:
                ext = Path(file_name).suffix.lower()
                if ext not in self.video_extensions:
                    continue

                file_path = Path(root) / file_name
                result["total"] += 1

                folder_actors = self._get_folder_actors(file_path, media_dir)
                if folder_actors:
                    result["actors"].update(folder_actors)

                result["scanned"] += 1

        return result

    def _get_folder_actors(self, file_path: Path, media_dir: Path) -> list[str]:
        """获取视频文件对应的文件夹演员名"""
        rel_path = file_path.relative_to(media_dir)
        parts = list(rel_path.parents)[::-1]

        folders_to_check = []
        if self.folder_depth == 1:
            folders_to_check = [rel_path.parent]
        elif self.folder_depth == 2:
            folders_to_check = [rel_path.parent, parts[-2] if len(parts) >= 2 else None]
        else:
            for i in range(min(self.folder_depth, len(parts))):
                folders_to_check.append(parts[-(i + 1)])

        all_actors = []
        seen = set()
        for folder in folders_to_check:
            if folder is None:
                continue
            name = folder.name if hasattr(folder, "name") else str(folder)
            actors = extract_actor_from_folder(
                name,
                blacklist=self.actor_blacklist,
                studio_names_as_folder=self.studio_names_as_folder,
            )
            for actor in actors:
                if actor not in seen:
                    all_actors.append(actor)
                    seen.add(actor)

        return all_actors
