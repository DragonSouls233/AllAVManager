"""
欧美模块扫描器

参考来源：
- 现有: chinese_scanner.py (扫描器框架)
- P0: mdcx-master/mdcx/crawlers/theporndb.py (站点/品牌识别)
- P0: CommunityScrapers/scrapers/AyloAPI/domains.py (品牌域名映射)

整合说明：
- 扫描框架: 沿用 MDCX BaseScanner
- 文件名识别: 支持品牌前缀匹配（brazzers/bangbros/vixen 等）
- 代理集成: 通过 MDCX 内置代理 (强制)
"""

import hashlib
import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 欧美品牌前缀映射（参考 CommunityScrapers AyloAPI domains.py + vixenNetwork）
WESTERN_SITE_PREFIXES = {
    # Aylo 品牌（Brazzers/BangBros/RealityKings/Mofos 等）
    "brazzers": "Brazzers",
    "brzzrs": "Brazzers",
    "bangbros": "BangBros",
    "bbros": "BangBros",
    "realitykings": "Reality Kings",
    "rk": "Reality Kings",
    "mofos": "Mofos",
    "digitalplayground": "Digital Playground",
    "twistys": "Twistys",
    "babes": "Babes",
    # Algolia 品牌
    "evilangel": "Evil Angel",
    "adulttime": "Adult Time",
    "puretaboo": "Pure Taboo",
    # Vixen 网络
    "vixen": "Vixen",
    "blacked": "Blacked",
    "tushy": "Tushy",
    "tushyraw": "TushyRaw",
    "deeper": "Deeper",
    # Naughty America
    "naughtyamerica": "Naughty America",
    "na": "Naughty America",
    "mylf": "MYLF",
    # TeamSkeet
    "teamskeet": "TeamSkeet",
    # 其他
    "playboy": "Playboy",
    "penthouse": "Penthouse",
    "wicked": "Wicked",
}

# 品牌网络映射
SITE_NETWORK_MAP = {
    "Brazzers": "Aylo",
    "BangBros": "Aylo",
    "Reality Kings": "Aylo",
    "Mofos": "Aylo",
    "Digital Playground": "Aylo",
    "Twistys": "Aylo",
    "Babes": "Aylo",
    "Evil Angel": "Algolia",
    "Adult Time": "Algolia",
    "Pure Taboo": "Algolia",
    "Vixen": "Vixen Network",
    "Blacked": "Vixen Network",
    "Tushy": "Vixen Network",
    "TushyRaw": "Vixen Network",
    "Deeper": "Vixen Network",
    "Naughty America": "Naughty America",
    "MYLF": "Naughty America",
    "TeamSkeet": "TeamSkeet",
}


def extract_site_from_filename(filename: str) -> tuple[str | None, str | None]:
    """从文件名提取站点和品牌网络

    支持格式:
    - brazzers_12345.mp4
    - BangBros - Scene 1.mp4
    - vixen-2023-01-15.mp4
    """
    name_lower = filename.lower()

    for prefix, site_name in WESTERN_SITE_PREFIXES.items():
        if prefix in name_lower:
            network = SITE_NETWORK_MAP.get(site_name)
            return site_name, network

    return None, None


def generate_western_code(file_path: Path, site: str | None) -> str:
    """为欧美视频生成唯一编码"""
    site_part = site or "unknown"
    hash_part = hashlib.sha256(str(file_path).encode()).hexdigest()[:8]
    return f"WE-{site_part}-{hash_part}"


class WesternScanner(BaseScanner):
    """欧美模块扫描器"""

    def __init__(self, media_dirs: list[str], config: dict | None = None):
        super().__init__("western", media_dirs)
        self.config = config or {}

    async def scan(self) -> dict:
        """扫描欧美媒体目录并落库"""
        results = {"total": 0, "scanned": 0, "movies_added": 0, "sites": set(), "errors": []}

        for media_dir in self.media_dirs:
            try:
                dir_result = await self._scan_directory(media_dir)
                results["total"] += dir_result["total"]
                results["scanned"] += dir_result["scanned"]
                results["movies_added"] += dir_result.get("movies_added", 0)
                results["sites"].update(dir_result.get("sites", set()))
            except Exception as e:
                results["errors"].append(f"{media_dir}: {e}")
                logger.error(f"扫描目录失败 {media_dir}: {e}")

        results["sites"] = list(results["sites"])
        return results

    async def _scan_directory(self, media_dir) -> dict:
        """扫描单个媒体目录并写入数据库"""
        result = {"total": 0, "scanned": 0, "movies_added": 0, "sites": set()}
        media_dir = Path(media_dir)

        from app.db.module_db import ModuleDatabase
        db = ModuleDatabase.get_instance("western")
        session = await db.get_session()
        try:
            from app.db.western_models import WesternMovie
            from sqlalchemy import select

            for root, dirs, files in os.walk(media_dir):
                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext not in self.video_extensions:
                        continue

                    file_path = Path(root) / file_name
                    result["total"] += 1

                    # 提取站点信息
                    site, network = extract_site_from_filename(file_name)
                    if site:
                        result["sites"].add(site)

                    # 生成编码
                    code = generate_western_code(file_path, site)

                    # 检查是否已存在
                    existing = await session.execute(select(WesternMovie).where(WesternMovie.code == code))
                    if existing.scalar_one_or_none():
                        continue

                    # 写入新影片记录
                    new_movie = WesternMovie(
                        code=code,
                        title=Path(file_name).stem,
                        site=site,
                        network=network,
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
