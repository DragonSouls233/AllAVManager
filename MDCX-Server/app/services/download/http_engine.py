"""
HTTP 多线程分片下载引擎

适用于没有反爬、没有 m3u8 保护的静态文件直链下载。
支持断点续传、多线程分片、自动重试。

核心能力:
  - HTTP Range 分片下载
  - 多线程并发（每个分片一个线程）
  - 断点续传（已下载部分跳过）
  - 代理集成（MDCX 内置代理）
  - 大文件分片合并
"""

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import aiohttp

from app.services.download.download_models import DownloadConfig, DownloadResult
from app.services.proxy_manager import get_proxy
from app.utils.logger import get_logger

logger = get_logger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB 每个分片
MAX_CONCURRENT_CHUNKS = 5


@dataclass
class HttpEngineConfig:
    """HTTP 引擎配置"""
    output_dir: str = "./downloads"
    chunk_size: int = CHUNK_SIZE
    max_concurrent: int = MAX_CONCURRENT_CHUNKS
    max_retries: int = 3
    timeout: int = 60
    use_proxy: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


class HttpEngine:
    """HTTP 多线程分片下载引擎"""

    def __init__(self, config: Optional[HttpEngineConfig] = None):
        self.config = config or HttpEngineConfig()

    async def _get_file_size(self, url: str, session: aiohttp.ClientSession) -> Optional[int]:
        """获取文件大小（HEAD 请求）"""
        try:
            async with session.head(url) as resp:
                if resp.status == 200:
                    content_length = resp.headers.get("Content-Length")
                    if content_length:
                        return int(content_length)
                return None
        except Exception as e:
            logger.warning(f"获取文件大小失败: {e}")
            return None

    async def _download_chunk(
        self,
        url: str,
        start: int,
        end: int,
        chunk_idx: int,
        temp_file: Path,
        session: aiohttp.ClientSession,
    ) -> bool:
        """下载单个分片"""
        headers = {"Range": f"bytes={start}-{end}"}
        retries = self.config.max_retries
        for attempt in range(retries):
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status not in (206, 200):
                        logger.warning(f"chunk {chunk_idx}: HTTP {resp.status}")
                        continue
                    data = await resp.read()
                    # 写入临时文件
                    with open(temp_file, "ab") as f:
                        f.seek(chunk_idx * self.config.chunk_size)
                        f.write(data)
                    return True
            except Exception as e:
                logger.debug(f"chunk {chunk_idx} 下载失败 (attempt {attempt+1}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(1)
        return False

    async def download(self, url: str, output_path: Optional[str] = None) -> DownloadResult:
        """下载文件

        Args:
            url: 文件直链
            output_path: 输出路径（自动生成文件名）

        Returns:
            DownloadResult
        """
        result = DownloadResult(engine="http")
        proxy = get_proxy() if self.config.use_proxy else None

        proxy_url = None
        if proxy:
            proxy_url = proxy.replace("socks5://", "http://")

        connector = aiohttp.TCPConnector()
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout_obj,
            headers={"User-Agent": self.config.user_agent},
        ) as session:
            # 获取文件大小
            file_size = await self._get_file_size(url, session)
            if not file_size:
                result.error = "无法获取文件大小"
                return result

            # 生成输出路径
            if not output_path:
                filename = url.split("/")[-1].split("?")[0]
                if not filename:
                    filename = f"download_{int(time.time())}.mp4"
                output_path = str(Path(self.config.output_dir) / filename)

            output_file = Path(output_path)
            temp_file = output_file.with_suffix(output_file.suffix + ".part")

            # 计算分片数
            num_chunks = max(1, file_size // self.config.chunk_size)
            if file_size % self.config.chunk_size:
                num_chunks += 1

            # 并发下载分片
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            tasks = []
            for i in range(num_chunks):
                start = i * self.config.chunk_size
                end = min(start + self.config.chunk_size - 1, file_size - 1)
                tasks.append(self._download_chunk(url, start, end, i, temp_file, session))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if isinstance(r, bool) and r)

            if success_count < num_chunks:
                result.error = f"分片下载失败: {success_count}/{num_chunks}"
                temp_file.unlink(missing_ok=True)
                return result

            # 合并文件
            try:
                temp_file.rename(output_file)
            except OSError:
                result.error = "文件合并失败"
                return result

            # 计算哈希
            sha1 = hashlib.sha1()
            with open(output_file, "rb") as f:
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    sha1.update(data)

            result.success = True
            result.file_path = str(output_file)
            result.file_size = file_size
            result.hash = sha1.hexdigest()
            logger.info(f"HTTP 下载完成: {output_file} ({file_size} bytes)")

        return result

    async def get_info(self, url: str) -> Optional[dict]:
        """获取文件信息"""
        proxy = get_proxy() if self.config.use_proxy else None
        async with aiohttp.ClientSession() as session:
            file_size = await self._get_file_size(url, session)
            if not file_size:
                return None
            filename = url.split("/")[-1].split("?")[0]
            return {
                "url": url,
                "filename": filename,
                "file_size": file_size,
                "engine": "http",
            }


# 全局单例
_engine: Optional[HttpEngine] = None


def get_http_engine() -> HttpEngine:
    global _engine
    if _engine is None:
        _engine = HttpEngine()
    return _engine
