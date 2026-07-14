"""
下载引擎模块

提供多引擎下载能力:
- YtDlpEngine: 1000+ 站点通用下载（yt-dlp 封装）
- M3U8Engine: HLS 流下载（ffmpeg）
- HttpEngine: HTTP 多线程分片下载
- DownloaderFactory: 自动选择最优引擎
- DownloadCacheDB: 下载缓存去重
- TempDownloadManager: 临时下载管理器（API 入口）
"""

from app.services.download.ytdlp_engine import YtDlpEngine, YtDlpConfig, get_ytdlp_engine
from app.services.download.m3u8_engine import M3U8Engine, M3U8EngineConfig, get_m3u8_engine
from app.services.download.http_engine import HttpEngine, HttpEngineConfig, get_http_engine
from app.services.download.downloader_factory import DownloaderFactory, get_downloader_factory
from app.services.download.download_cache import DownloadCacheDB, get_download_cache
from app.services.download.temp_download_manager import TempDownloadManager, TempDownloadConfig, get_download_manager

__all__ = [
    "YtDlpEngine", "YtDlpConfig", "get_ytdlp_engine",
    "M3U8Engine", "M3U8EngineConfig", "get_m3u8_engine",
    "HttpEngine", "HttpEngineConfig", "get_http_engine",
    "DownloaderFactory", "get_downloader_factory",
    "DownloadCacheDB", "get_download_cache",
    "TempDownloadManager", "TempDownloadConfig", "get_download_manager",
]
