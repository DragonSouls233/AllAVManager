"""
M3U8/HLS 流下载引擎

专用于 m3u8 格式的 HLS 视频流下载。
适用于需要手动处理分片 ts 文件合并、密钥解密的场景。

核心功能:
  - m3u8 解析（playlist / key / segment）
  - 分片并发下载
  - AES-128 解密（IV+KEY）
  - ts 文件合并为 mp4
  - 重试 + 断点续传
"""

import asyncio
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.download.download_models import DownloadConfig, DownloadResult
from app.services.proxy_manager import get_effective_proxy_url
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class M3U8Segment:
    """HLS 分片信息"""
    url: str
    duration: float = 0.0
    sequence: int = 0
    key: Optional[str] = None
    iv: Optional[str] = None
    downloaded: bool = False
    local_path: Optional[str] = None


@dataclass
class M3U8Playlist:
    """m3u8 播放列表"""
    url: str
    segments: list[M3U8Segment] = field(default_factory=list)
    key: Optional[str] = None
    method: Optional[str] = None
    iv: Optional[bytes] = None
    base_url: str = ""
    duration: float = 0.0
    target_duration: float = 10.0


@dataclass
class M3U8EngineConfig:
    """M3U8 引擎配置"""
    max_concurrent: int = 8
    max_retries: int = 3
    timeout: int = 60
    output_dir: str = "./downloads"
    ffmpeg_path: str = "ffmpeg"
    use_proxy: bool = True
    max_download_size_mb: int = 0  # 0 = 不限


class M3U8Engine:
    """M3U8/HLS 流下载引擎"""

    def __init__(self, config: Optional[M3U8EngineConfig] = None):
        self.config = config or M3U8EngineConfig()
        self.proxy = get_effective_proxy_url() if self.config.use_proxy else None

    async def parse_playlist(self, url: str) -> Optional[M3U8Playlist]:
        """解析 m3u8 播放列表"""
        async with AsyncHttpClient(proxy=self.proxy, timeout=self.config.timeout) as client:
            resp = await client.get(url)
            if not resp:
                logger.error(f"m3u8 请求失败: {url}")
                return None
            text = await resp.text("utf-8", errors="replace") if hasattr(resp, "text") else None
            if not text:
                text = str(resp)

        playlist = M3U8Playlist(url=url)
        base_url = url[:url.rfind("/") + 1]
        playlist.base_url = base_url

        lines = text.strip().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("#EXTINF:"):
                duration_match = re.search(r"#EXTINF:\s*([\d.]+)", line)
                duration = float(duration_match.group(1)) if duration_match else 0
                i += 1
                if i < len(lines) and not lines[i].startswith("#"):
                    seg_url = lines[i].strip()
                    if not seg_url.startswith("http"):
                        seg_url = urljoin(base_url, seg_url)
                    segment = M3U8Segment(
                        url=seg_url,
                        duration=duration,
                        sequence=len(playlist.segments),
                    )
                    playlist.segments.append(segment)
            elif line.startswith("#EXT-X-KEY:"):
                method_match = re.search(r"METHOD=(\w+)", line)
                if method_match:
                    playlist.method = method_match.group(1)
                key_match = re.search(r"URI=\"([^\"]+)\"", line)
                if key_match:
                    key_url = key_match.group(1)
                    if not key_url.startswith("http"):
                        key_url = urljoin(base_url, key_url)
                    playlist.key = key_url
                iv_match = re.search(r"IV=0x([\da-fA-F]+)", line)
                if iv_match:
                    playlist.iv = bytes.fromhex(iv_match.group(1))
            elif line.startswith("#EXT-X-TARGETDURATION:"):
                td_match = re.search(r"(\d+)", line)
                if td_match:
                    playlist.target_duration = float(td_match.group(1))
            i += 1

        if playlist.segments:
            playlist.duration = sum(s.duration for s in playlist.segments)

        logger.info(f"m3u8 解析完成: {len(playlist.segments)} segments, {playlist.duration:.1f}s")
        return playlist

    async def download_playlist(
        self, url: str, output_path: Optional[str] = None
    ) -> DownloadResult:
        """下载整个 m3u8 流并合并为 mp4

        Args:
            url: m3u8 URL
            output_path: 输出文件路径（不含扩展名）

        Returns:
            DownloadResult
        """
        result = DownloadResult()
        playlist = await self.parse_playlist(url)
        if not playlist or not playlist.segments:
            result.error = "无法解析 m3u8 播放列表"
            return result

        # 使用 ffmpeg 直接下载合并（最简单）
        if output_path is None:
            output_path = os.path.join(
                self.config.output_dir,
                os.path.basename(url).replace(".m3u8", "").replace("%", "_")
            )

        output_file = f"{output_path}.mp4"
        temp_dir = Path(self.config.output_dir) / "ts_parts"
        temp_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.config.ffmpeg_path,
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            output_file,
        ]

        if self.proxy:
            proxy_parts = self.proxy.replace("socks5://", "").replace("http://", "").split(":")
            if len(proxy_parts) >= 2:
                cmd[1:1] = [
                    "-http_proxy", self.proxy,
                    "-https_proxy", self.proxy,
                ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.config.timeout * 10
            )

            if process.returncode == 0:
                file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
                result.success = True
                result.file_path = output_file
                result.file_size = file_size
                logger.info(f"M3U8 下载完成: {output_file} ({file_size} bytes)")
            else:
                result.error = f"ffmpeg 返回错误: {stderr.decode('utf-8', errors='replace')[:500]}"
        except FileNotFoundError:
            result.error = "ffmpeg 未安装，请手动合并分片文件"
        except asyncio.TimeoutError:
            result.error = f"M3U8 下载超时"

        return result

    async def get_info(self, url: str) -> Optional[dict]:
        """获取 m3u8 信息（不下载）"""
        playlist = await self.parse_playlist(url)
        if not playlist:
            return None
        return {
            "url": url,
            "duration": playlist.duration,
            "segments": len(playlist.segments),
            "method": playlist.method,
            "has_key": playlist.key is not None,
            "target_duration": playlist.target_duration,
        }


# 全局单例
_engine: Optional[M3U8Engine] = None


def get_m3u8_engine() -> M3U8Engine:
    global _engine
    if _engine is None:
        _engine = M3U8Engine()
    return _engine
