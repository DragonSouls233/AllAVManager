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

import asyncio
import hashlib
import os
import re
from pathlib import Path

from app.tasks.base_scanner import BaseScanner, copy_video_assets_to_data_dir, iter_media_entries, _file_size
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 欧美品牌前缀映射（参考 CommunityScrapers AyloAPI domains.py + vixenNetwork）
# 注意：前缀按匹配优先级排序，长前缀/精确前缀在前，避免短前缀误匹配
WESTERN_SITE_PREFIXES = {
    # ===== Vixen 网络（优先匹配，避免被其他品牌误匹配）=====
    "blackedraw": "Blacked Raw",
    "blacked": "Blacked",
    "tushyraw": "TushyRaw",
    "tushy": "Tushy",
    "vixen": "Vixen",
    "deeper": "Deeper",
    "milfy": "Milfy",
    "wifey": "Wifey",
    "slayed": "Slayed",
    # ===== Aylo 品牌 =====
    "brazzers": "Brazzers",
    "brzzrs": "Brazzers",
    "bangbros": "BangBros",
    "bbros": "BangBros",
    "bb.": "BangBros",  # bb.date.scene 格式
    "realitykings": "Reality Kings",
    "rk": "Reality Kings",
    "mofos": "Mofos",
    "digitalplayground": "Digital Playground",
    "twistys": "Twistys",
    "babes": "Babes",
    # ===== Naughty America（放在 PublicAgent 后面，避免 na 误匹配 publicagent）=====
    "naughtyamerica": "Naughty America",
    "tonightsgirlfriend": "Naughty America",
    "myfriendshotmom": "Naughty America",
    "mysistershotfriend": "Naughty America",
    "thundercock": "Naughty America",
    "mylf": "MYLF",
    # ===== 其他独立品牌 =====
    "publicagent": "PublicAgent",
    "pba.": "PublicAgent",  # PublicAgent 的简写/旧格式
    "hegre": "Hegre",
    "hegreart": "Hegre",
    # ===== Algolia 品牌 =====
    "evilangel": "Evil Angel",
    "adulttime": "Adult Time",
    "puretaboo": "Pure Taboo",
    # ===== TeamSkeet =====
    "teamskeet": "TeamSkeet",
    "brattysis": "BrattySis",
    # ===== 其他 =====
    "playboy": "Playboy",
    "penthouse": "Penthouse",
    "wicked": "Wicked",
    "sexart": "SexArt",
    "stripshow": "StripShow",
    "eroticax": "EroticaX",
    "girlsway": "Girlsway",
    "girlfriendsfilms": "GirlfriendsFilms",
    "realityjunkies": "RealityJunkies",
    "wankz": "Wankz",
    "pornfidelity": "PornFidelity",
    "teenmegaworld": "TeenMegaWorld",
}

# 品牌网络映射
SITE_NETWORK_MAP = {
    # Vixen 网络
    "Vixen": "Vixen Network",
    "Blacked": "Vixen Network",
    "Blacked Raw": "Vixen Network",
    "Tushy": "Vixen Network",
    "TushyRaw": "Vixen Network",
    "Deeper": "Vixen Network",
    "Milfy": "Vixen Network",
    "Wifey": "Vixen Network",
    "Slayed": "Vixen Network",
    # Aylo 网络
    "Brazzers": "Aylo",
    "BangBros": "Aylo",
    "Reality Kings": "Aylo",
    "Mofos": "Aylo",
    "Digital Playground": "Aylo",
    "Twistys": "Aylo",
    "Babes": "Aylo",
    # NA 网络
    "Naughty America": "Naughty America",
    "MYLF": "Naughty America",
    # Algolia 网络
    "Evil Angel": "Algolia",
    "Adult Time": "Algolia",
    "Pure Taboo": "Algolia",
    # 独立品牌（无网络归属）
    "Hegre": "Independent",
    "PublicAgent": "Independent",
    "TeamSkeet": "TeamSkeet",
    "BrattySis": "TeamSkeet",
    "Playboy": "Playboy",
    "Penthouse": "Penthouse",
}


def extract_site_from_filename(filename: str) -> tuple[str | None, str | None]:
    """从文件名或文件夹名提取站点和品牌网络

    支持格式:
    - brazzers_12345.mp4
    - BangBros - Scene 1.mp4
    - vixen-2023-01-15.mp4
    - [PublicAgent] video.mp4   （文件夹名）
    - Hegre.xxx.mp4
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

            # 性能修复：一次性载入已存在番号，避免每文件一次 SELECT 的 N+1 查询
            existing_codes: set[str] = set(
                (await session.execute(select(WesternMovie.code))).scalars().all()
            )

            walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
            for root, dirs, files in walk_entries:
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

                    # 检查是否已存在（内存判重，避免 N+1 查询）
                    if code in existing_codes:
                        continue
                    existing_codes.add(code)

                    # 写入新影片记录
                    new_movie = WesternMovie(
                        code=code,
                        title=Path(file_name).stem,
                        site=site,
                        network=network,
                        file_path=str(file_path),
                        file_size=_file_size(file_path),
                        status="pending",
                    )
                    session.add(new_movie)
                    result["movies_added"] += 1
                    result["scanned"] += 1
                    if code:
                        # 并发受限（防整盘扫描时无限制 ensure_future 风暴拖死事件循环）
                        asyncio.ensure_future(
                            self._copy_limited(
                                copy_video_assets_to_data_dir(str(file_path), code, "western")
                            )
                        )

            await session.commit()
        finally:
            await session.close()

        return result
