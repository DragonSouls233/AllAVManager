"""FC2 泄漏检测器 — 移植自 FC2-Leak-Detector。

功能：
1. 查询 fc2ppvdb.com API 获取作者/女优的全部 FC2 视频
2. 检查哪些视频已流出（leaked）
3. 获取磁力链接（按体积最大排序）
4. 下载缩略图
5. 生成 NFO 和报告
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_FC2PPVDB_API = "https://fc2ppvdb.com"
_MAGNET_BASE = "https://sukebei.nyaa.si"


@dataclass
class FC2Video:
    video_id: str
    title: str = ""
    image_url: str = ""
    status: str = "unknown"   # "leaked" | "unleaked" | "unknown"
    magnets: list[str] = field(default_factory=list)
    image_path: str = ""


@dataclass
class FC2AnalysisResult:
    writer_id: str
    writer_name: str = ""
    is_actress: bool = False
    total: int = 0
    leaked: int = 0
    unleaked: int = 0
    with_magnet: int = 0
    videos: list[FC2Video] = field(default_factory=list)


class FC2LeakDetector:
    """FC2 泄漏检测器。"""

    def __init__(self, proxy: Optional[str] = None, timeout: float = 30.0):
        self.proxy = proxy
        self.timeout = timeout

    async def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            proxy=self.proxy,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html",
                "Accept-Language": "zh-CN,ja;q=0.9",
            },
            follow_redirects=True,
        )

    async def fetch_writer_name(self, writer_id: str, is_actress: bool = False) -> str:
        """获取作者/女优的名称。"""
        entity_type = "actresses" if is_actress else "writers"
        url = f"{_FC2PPVDB_API}/{entity_type}/{writer_id}"
        async with await self._get_client() as client:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    h3 = soup.select_one(f".{entity_type[:-1]}-info h3, .user-info h3")
                    if h3:
                        return h3.text.strip()
                    title = soup.select_one("title")
                    if title and " - " in title.text:
                        return title.text.split(" - ")[0].strip()
            except Exception as e:
                logger.warning("fetch_writer_name failed: %s", e)
        return f"{'Actress' if is_actress else 'Writer'}_{writer_id}"

    async def fetch_videos(self, writer_id: str, is_actress: bool = False) -> list[FC2Video]:
        """获取作者/女优的全部 FC2 视频。"""
        entity_type = "actresses" if is_actress else "writers"
        entity_param = "actressid" if is_actress else "writerid"
        api_path = f"/api/v1/{entity_type}/actress-articles" if is_actress else f"/api/v1/writers/writer-articles"

        all_videos: list[FC2Video] = []
        page = 1

        async with await self._get_client() as client:
            while True:
                url = f"{_FC2PPVDB_API}{api_path}?{entity_param}={writer_id}&page={page}&per_page=100"
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    items = data.get("data") or []
                    if not items:
                        break

                    for item in items:
                        if is_actress:
                            vid = str(item.get("video_id", ""))
                            title = item.get("title", f"FC2-PPV-{vid}")
                            image = item.get("image_url", "")
                        else:
                            vid = str(item.get("video_id") or item.get("id", ""))
                            title = item.get("title", f"FC2-PPV-{vid}")
                            if vid and vid.isdigit():
                                first = vid[0]
                                prefix = f"00{first}" if len(vid) >= 1 else "000"
                                middle = vid[1:3] if len(vid) >= 3 else "00"
                                image = f"{_FC2PPVDB_API}/storage/thumbs/article/{prefix}/{middle}/fc2ppv-{vid}.jpg"
                            else:
                                image = ""

                        if vid:
                            all_videos.append(FC2Video(video_id=vid, title=title, image_url=image))

                    if not data.get("next_page_url"):
                        break
                    page += 1
                except Exception as e:
                    logger.warning("fetch page %d failed: %s", page, e)
                    break

        return all_videos

    async def check_status(self, video_id: str) -> tuple[bool, str]:
        """检查单个 FC2 视频的流出状态。

        Returns:
            (is_leaked, site_name)
        """
        check_sites = [
            {"url": "https://sukebei.nyaa.si/?q=FC2-PPV-{vid}&s=seeders&o=desc", "name": "Sukebei"},
            {"url": "https://ja.hentai-cat.site/search?q=FC2-PPV-{vid}", "name": "HentaiCat"},
        ]

        async with await self._get_client() as client:
            for site in check_sites:
                url = site["url"].format(vid=video_id)
                try:
                    r = await client.get(url)
                    if r.status_code == 200 and ("FC2-PPV-" + video_id) in r.text:
                        return True, site["name"]
                except Exception:
                    continue
        return False, ""

    async def fetch_magnet(self, video_id: str) -> list[str]:
        """从 Sukebei 获取 FC2 视频的磁力链接，按大小降序返回。"""
        url = f"{_MAGNET_BASE}/?q=FC2-PPV-{video_id}&s=seeders&o=desc"
        magnets: list[tuple[int, str]] = []

        async with await self._get_client() as client:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    return []
                soup = BeautifulSoup(r.text, "html.parser")
                for row in soup.select("table.torrent-list > tbody > tr"):
                    magnet_link = row.select_one('a[href^="magnet:"]')
                    size_cell = row.select_one("td.text-center")
                    if not magnet_link:
                        continue
                    size = 0
                    if size_cell:
                        size_text = size_cell.text.strip().lower()
                        m = re.match(r"([\d.]+)\s*(k|m|g)b?", size_text)
                        if m:
                            mul = {"k": 1024, "m": 1024**2, "g": 1024**3}
                            size = float(m.group(1)) * mul.get(m.group(2), 1)
                    magnets.append((size, magnet_link["href"]))
            except Exception as e:
                logger.warning("fetch_magnet failed for %s: %s", video_id, e)

        magnets.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in magnets[:1]]

    async def analyze(self, writer_id: str, is_actress: bool = False,
                      with_magnet: bool = True) -> FC2AnalysisResult:
        """完整分析一个作者/女优的 FC2 视频泄漏情况。"""
        logger.info("Analyzing FC2 %s: %s", "actress" if is_actress else "writer", writer_id)

        name = await self.fetch_writer_name(writer_id, is_actress)
        videos = await self.fetch_videos(writer_id, is_actress)

        result = FC2AnalysisResult(
            writer_id=writer_id,
            writer_name=name,
            is_actress=is_actress,
            total=len(videos),
        )

        sem = asyncio.Semaphore(5)

        async def _process(v: FC2Video):
            async with sem:
                is_leaked, site = await self.check_status(v.video_id)
                if is_leaked:
                    v.status = "leaked"
                    result.leaked += 1
                    if with_magnet:
                        v.magnets = await self.fetch_magnet(v.video_id)
                        if v.magnets:
                            result.with_magnet += 1
                else:
                    v.status = "unleaked"
                    result.unleaked += 1

        await asyncio.gather(*(
            _process(v) for v in videos
        ))

        result.videos = videos
        logger.info("FC2 analysis complete: %d total, %d leaked, %d with magnet",
                     result.total, result.leaked, result.with_magnet)
        return result
