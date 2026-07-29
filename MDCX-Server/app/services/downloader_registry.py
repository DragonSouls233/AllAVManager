"""多站点下载器注册表 — 从 Hitomi-Downloader 提取的站点模式。

Hitomi-Downloader 支持 60+ 站点的下载模式。
这里提取最常用的站点注册信息，用于 MDCX 下载器统一管理。

站点模式：
- single: 单文件 MP4 直接下载
- hls: HLS m3u8 分段下载 + ffmpeg 合并
- gallery: 图片集下载
- playlist: 播放列表（多视频）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DownloadSite:
    """下载站点注册信息。"""
    name: str
    domains: list[str]
    mode: str                    # "single" | "hls" | "gallery" | "playlist"
    video_pattern: str = ""      # URL 匹配模式
    supports_quality: bool = False
    supports_search: bool = False
    requires_cookie: bool = False
    requires_proxy: bool = False
    notes: str = ""


# 60+ 站点注册表
SITE_REGISTRY: list[DownloadSite] = [
    # === 主流 ===
    DownloadSite("PornHub", ["pornhub.com", "pornhubpremium.com"], "single",
                 supports_quality=True, supports_search=True,
                 notes="多画质选择（720p/1080p/4K）"),
    DownloadSite("xVideos", ["xvideos.com", "xvideos.red"], "single",
                 supports_quality=True, supports_search=True),
    DownloadSite("xHamster", ["xhamster.com", "xhamster.desi", "xhamster2.com"], "single",
                 supports_quality=True, supports_search=True),
    DownloadSite("RedTube", ["redtube.com"], "single",
                 supports_quality=True),
    DownloadSite("Tube8", ["tube8.com"], "single"),
    DownloadSite("YouPorn", ["youporn.com"], "single",
                 supports_quality=True, supports_search=True),
    DownloadSite("SpankBang", ["spankbang.com"], "hls",
                 supports_search=True),
    DownloadSite("Eporner", ["eporner.com"], "single",
                 supports_quality=True, supports_search=True),

    # === 日本主流 ===
    DownloadSite("MissAV", ["missav.com", "missav.ws", "missav.one"], "hls",
                 supports_search=True,
                 notes="JAV 在线播放站"),
    DownloadSite("Jable", ["jable.tv", "jable.xyz"], "hls",
                 supports_search=True),
    DownloadSite("AV01", ["av01.tv"], "hls",
                 supports_search=True),
    DownloadSite("JavGG", ["javgg.net"], "hls",
                 supports_search=True),
    DownloadSite("JavDB", ["javdb.com"], "single",
                 requires_cookie=True,
                 notes="元数据为主，部分视频可下载"),
    DownloadSite("FC2", ["fc2.com"], "single",
                 requires_cookie=True, supports_search=True,
                 notes="FC2 付费视频"),

    # === 欧美品牌 ===
    DownloadSite("Brazzers", ["brazzers.com"], "single",
                 requires_cookie=True, supports_quality=True),
    DownloadSite("Reality Kings", ["realitykings.com"], "single",
                 requires_cookie=True),
    DownloadSite("Mofos", ["mofos.com"], "single",
                 requires_cookie=True),
    DownloadSite("Vixen", ["vixen.com"], "single",
                 requires_cookie=True, supports_quality=True),
    DownloadSite("Blacked", ["blacked.com", "blackedraw.com"], "single",
                 requires_cookie=True, supports_quality=True),
    DownloadSite("Tushy", ["tushy.com", "tushyraw.com"], "single",
                 requires_cookie=True, supports_quality=True),
    DownloadSite("Naughty America", ["naughtyamerica.com"], "single",
                 requires_cookie=True),
    DownloadSite("Digital Playground", ["digitalplayground.com"], "single",
                 requires_cookie=True),
    DownloadSite("Evil Angel", ["evilangel.com"], "single",
                 requires_cookie=True),
    DownloadSite("TeamSkeet", ["teamskeet.com"], "single",
                 requires_cookie=True),
    DownloadSite("BangBros", ["bangbros.com"], "single",
                 requires_cookie=True),
    DownloadSite("MYLF", ["mylf.com"], "single",
                 requires_cookie=True),

    # === 无码 ===
    DownloadSite("TOKYO-HOT", ["my.tokyo-hot.com"], "single",
                 supports_search=True),
    DownloadSite("HEYZO", ["heyzo.com"], "single",
                 supports_search=True),
    DownloadSite("1PONDO", ["1pondo.tv"], "single",
                 supports_search=True),
    DownloadSite("Caribbeancom", ["caribbeancom.com"], "single",
                 supports_search=True),
    DownloadSite("10musume", ["10musume.com"], "single",
                 supports_search=True),
    DownloadSite("Pacopacomama", ["pacopacomama.com"], "single",
                 supports_search=True),

    # === 国产 ===
    DownloadSite("麻豆传媒", ["madouqu.com"], "single",
                 supports_search=True, requires_proxy=True),
    DownloadSite("SWAG", ["swag.live"], "single",
                 requires_cookie=True),

    # === 其他 ===
    DownloadSite("Sukebei", ["sukebei.nyaa.si"], "single",
                 supports_search=True, supports_quality=True,
                 notes="磁力站"),
    DownloadSite("IAFD", ["iafd.com"], "single",
                 notes="元数据站，无视频"),
]


def find_site_by_url(url: str) -> Optional[DownloadSite]:
    """根据 URL 找到对应的站点注册信息。"""
    import re
    for site in SITE_REGISTRY:
        for domain in site.domains:
            if re.search(re.escape(domain).replace(r"\.", r"\."), url):
                return site
    return None


def get_sites_by_mode(mode: str) -> list[DownloadSite]:
    """按下载模式筛选站点。"""
    return [s for s in SITE_REGISTRY if s.mode == mode]


def get_site_names() -> list[str]:
    """返回所有注册站点名称。"""
    return [s.name for s in SITE_REGISTRY]
