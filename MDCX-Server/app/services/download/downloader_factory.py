"""
下载器多引擎工厂

根据 URL/类型 自动选择最优下载引擎。
支持 3 种内置引擎 + 外部引擎扩展。

引擎选择策略:
  1. 以 .m3u8 结尾 -> M3U8Engine
  2. 包含指定视频站点域名 (pornhub, xvideos 等) -> YtDlpEngine
  3. 其他直链 -> HttpEngine

用法:
  factory = DownloaderFactory()
  result = await factory.download("https://example.com/video.mp4")
"""

from typing import Optional

from app.services.download.download_models import DownloadResult
from app.services.download.ytdlp_engine import YtDlpEngine, YtDlpConfig
from app.services.download.m3u8_engine import M3U8Engine, M3U8EngineConfig
from app.services.download.http_engine import HttpEngine, HttpEngineConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)

# yt-dlp 支持的常见视频站点（非完整列表）
YDLP_SUPPORTED_DOMAINS = [
    "pornhub.com", "xvideos.com", "xhamster.com", "redtube.com",
    "youporn.com", "tube8.com", "spankbang.com", "eporner.com",
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com",
    "twitter.com", "x.com", "instagram.com", "tiktok.com",
    "onlyfans.com", "fansly.com",
]


class DownloaderFactory:
    """下载器多引擎工厂

    自动选择引擎，支持按类型 / URL 格式 / 域名 三种匹配模式。
    """

    def __init__(
        self,
        ytdlp_config: Optional[YtDlpConfig] = None,
        m3u8_config: Optional[M3U8EngineConfig] = None,
        http_config: Optional[HttpEngineConfig] = None,
    ):
        self._ytdlp_engine = None
        self._m3u8_engine = None
        self._http_engine = None
        self._ytdlp_config = ytdlp_config
        self._m3u8_config = m3u8_config
        self._http_config = http_config

    @property
    def ytdlp(self) -> YtDlpEngine:
        if self._ytdlp_engine is None:
            self._ytdlp_engine = YtDlpEngine(self._ytdlp_config)
        return self._ytdlp_engine

    @property
    def m3u8(self) -> M3U8Engine:
        if self._m3u8_engine is None:
            self._m3u8_engine = M3U8Engine(self._m3u8_config)
        return self._m3u8_engine

    @property
    def http(self) -> HttpEngine:
        if self._http_engine is None:
            self._http_engine = HttpEngine(self._http_config)
        return self._http_engine

    def select_engine(self, url: str) -> str:
        """根据 URL 选择引擎类型

        Returns:
            "ytdlp" | "m3u8" | "http"
        """
        url_lower = url.lower()

        # m3u8
        if url_lower.endswith(".m3u8") or "m3u8" in url_lower:
            return "m3u8"

        # yt-dlp 站点
        for domain in YDLP_SUPPORTED_DOMAINS:
            if domain in url_lower:
                return "ytdlp"

        # 默认 HTTP
        return "http"

    async def download(self, url: str, output_path: Optional[str] = None) -> DownloadResult:
        """自动选择引擎下载

        Args:
            url: 下载 URL
            output_path: 输出路径

        Returns:
            DownloadResult
        """
        engine_type = self.select_engine(url)
        logger.info(f"选择引擎 [{engine_type}] 下载: {url}")

        if engine_type == "ytdlp":
            return await self.ytdlp.download(url, output_dir=str(output_path))
        elif engine_type == "m3u8":
            return await self.m3u8.download_playlist(url, output_path)
        else:
            return await self.http.download(url, output_path)

    async def get_info(self, url: str) -> Optional[dict]:
        """获取资源信息（不下载）"""
        engine_type = self.select_engine(url)
        if engine_type == "ytdlp":
            return await self.ytdlp.get_info(url)
        elif engine_type == "m3u8":
            return await self.m3u8.get_info(url)
        else:
            return await self.http.get_info(url)


# 全局单例
_factory: Optional[DownloaderFactory] = None


def get_downloader_factory() -> DownloaderFactory:
    global _factory
    if _factory is None:
        _factory = DownloaderFactory()
    return _factory
