"""聚合多站 M3U8 在线播放源搜索。

输入番号 → 并发搜索多站 → 聚合播放链接。

来源站点（移植自 javapi Go 版的内部爬虫）：
- missav.com — JAV 在线播放主流站
- jable.tv — 高画质在线站
- javgg.net — 磁力 + 在线双源
- av01.tv — 日活最大的在线站
- javtrailers.com — 预告片站
- sevenmmtv — 旧片站
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config.manager import get_config

logger = logging.getLogger(__name__)


@dataclass
class StreamSource:
    url: str
    site: str
    quality: str = ""
    priority: int = 0  # 越小越优先
    is_hls: bool = True
    note: str = ""


@dataclass
class StreamSearchResult:
    code: str
    title: str = ""
    sources: list[StreamSource] = field(default_factory=list)
    cover_url: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# 各站点爬虫
# ---------------------------------------------------------------------------


async def _search_missav(code: str, client: httpx.AsyncClient) -> list[StreamSource]:
    """MissAV — JAV 在线播放主流站。

    URL 模式: https://missav.com/{code}
    获取 iframe 中的 M3U8 播放地址。
    """
    sources: list[StreamSource] = []
    url = f"https://missav.com/{code.lower()}"
    try:
        r = await client.get(url, headers={"Referer": "https://missav.com/"})
        if r.status_code != 200:
            return sources
        # 尝试提取 M3U8 URL
        m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', r.text)
        seen = set()
        for m in m3u8_matches:
            clean = m.split("&")[0]
            if clean not in seen:
                seen.add(clean)
                quality = "720p"
                if "1080" in clean:
                    quality = "1080p"
                elif "480" in clean:
                    quality = "480p"
                sources.append(StreamSource(
                    url=clean, site="missav",
                    quality=quality, priority=1,
                ))
    except Exception as e:
        logger.debug("missav search failed for %s: %s", code, e)
    return sources


async def _search_jable(code: str, client: httpx.AsyncClient) -> list[StreamSource]:
    """Jable — 高画质在线站。

    URL 模式: https://jable.tv/videos/{code}/
    通过 API 获取 M3U8 地址。
    """
    sources: list[StreamSource] = []
    url = f"https://jable.tv/videos/{code.lower()}/"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return sources
        # 提取 M3U8
        m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', r.text)
        seen = set()
        for m in m3u8_matches:
            clean = m.split("&")[0]
            if clean not in seen:
                seen.add(clean)
                quality = "720p"
                if "1080" in clean:
                    quality = "1080p"
                sources.append(StreamSource(
                    url=clean, site="jable",
                    quality=quality, priority=2,
                ))
    except Exception as e:
        logger.debug("jable search failed for %s: %s", code, e)
    return sources


async def _search_av01(code: str, client: httpx.AsyncClient) -> list[StreamSource]:
    """AV01 — 日活最大的在线站。

    URL 模式: https://av01.tv/{code}/
    """
    sources: list[StreamSource] = []
    url = f"https://av01.tv/{code.lower()}/"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return sources
        # 尝试提取 M3U8
        m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', r.text)
        seen = set()
        for m in m3u8_matches:
            clean = m.split("&")[0]
            if clean not in seen:
                seen.add(clean)
                sources.append(StreamSource(
                    url=clean, site="av01",
                    quality="720p", priority=4,
                ))
        # 如果没有 M3U8，找 iframe
        if not sources:
            iframe_matches = re.findall(r'<iframe[^>]+src="([^"]+)"', r.text)
            for iframe_url in iframe_matches:
                sources.append(StreamSource(
                    url=iframe_url, site="av01",
                    is_hls=False, priority=5,
                    note="iframe embed",
                ))
    except Exception as e:
        logger.debug("av01 search failed for %s: %s", code, e)
    return sources


async def _search_javgg(code: str, client: httpx.AsyncClient) -> list[StreamSource]:
    """JavGG — 磁力 + 在线双源。
    通过 API 搜索番号，返回包含播放链接的结果。
    """
    sources: list[StreamSource] = []
    search_url = f"https://javgg.net/search/{quote(code)}"
    try:
        r = await client.get(search_url)
        if r.status_code != 200:
            return sources
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.select("a[href*='/video/']"):
            href = link.get("href", "")
            if href:
                detail_url = f"https://javgg.net{href}" if href.startswith("/") else href
                try:
                    dr = await client.get(detail_url)
                    if dr.status_code == 200:
                        m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', dr.text)
                        for m in m3u8_matches:
                            sources.append(StreamSource(
                                url=m.split("&")[0], site="javgg",
                                quality="720p", priority=3,
                            ))
                except Exception:
                    pass
    except Exception as e:
        logger.debug("javgg search failed for %s: %s", code, e)
    return sources


async def _search_javtrailers(code: str, client: httpx.AsyncClient) -> list[StreamSource]:
    """JavTrailers — 预告片站。
    Thumbnail 特供，ID 使用空格+连字符格式。
    """
    sources: list[StreamSource] = []
    url = f"https://www.javtrailers.com/{code.lower().replace('-', '-')}/"
    try:
        r = await client.get(url)
        if r.status_code == 200:
            video_matches = re.findall(r'(https?://[^"\']+\.mp4[^"\']*)', r.text)
            for v in video_matches:
                clean = v.split("&")[0]
                sources.append(StreamSource(
                    url=clean, site="javtrailers",
                    is_hls=False, priority=6,
                    quality="720p",
                ))
    except Exception as e:
        logger.debug("javtrailers search failed for %s: %s", code, e)
    return sources


async def _search_sevenmmtv(code: str, client: httpx.AsyncClient) -> list[StreamSource]:
    """SevenMMTV — 旧番补充站。"""
    sources: list[StreamSource] = []
    search_url = f"https://7mmtv.sx/search/{quote(code)}"
    try:
        r = await client.get(search_url)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a[href*='/watch/']")
            for link in links[:3]:
                href = link.get("href", "")
                if href:
                    detail_url = f"https://7mmtv.sx{href}" if href.startswith("/") else href
                    try:
                        dr = await client.get(detail_url)
                        if dr.status_code == 200:
                            m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', dr.text)
                            for m in m3u8_matches:
                                sources.append(StreamSource(
                                    url=m.split("&")[0], site="7mmtv",
                                    quality="720p", priority=7,
                                ))
                    except Exception:
                        pass
    except Exception as e:
        logger.debug("7mmtv search failed for %s: %s", code, e)
    return sources


# ---------------------------------------------------------------------------
# 入口函数
# ---------------------------------------------------------------------------

# 注册所有搜索器
_SEARCHERS: list[tuple[str, callable]] = [
    ("missav", _search_missav),
    ("jable", _search_jable),
    ("av01", _search_av01),
    ("javgg", _search_javgg),
    ("javtrailers", _search_javtrailers),
    ("7mmtv", _search_sevenmmtv),
]


async def search_online_source(code: str) -> StreamSearchResult:
    """聚合搜索番号的在线播放源。

    Args:
        code: 番号，如 "SSIS-001"

    Returns:
        StreamSearchResult 包含所有站点的播放链接
    """
    result = StreamSearchResult(code=code.upper())

    from app.services.proxy_manager import get_effective_proxy_url

    # 统一走项目代理唯一入口（内置 xray 优先，回退 config.proxy）
    proxy = get_effective_proxy_url()

    async with httpx.AsyncClient(
        timeout=15.0,
        proxy=proxy,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
            "Accept-Language": "zh-CN",
        },
    ) as client:
        sem = asyncio.Semaphore(3)

        async def _search_one(name: str, fn) -> list[StreamSource]:
            async with sem:
                try:
                    return await fn(code, client) or []
                except Exception as e:
                    logger.debug("stream search %s failed: %s", name, e)
                    return []

        all_sources = await asyncio.gather(*(
            _search_one(name, fn) for name, fn in _SEARCHERS
        ))

        seen_urls: set[str] = set()
        for sources in all_sources:
            for s in sources:
                if s.url not in seen_urls:
                    seen_urls.add(s.url)
                    result.sources.append(s)

        # 按优先级排序
        result.sources.sort(key=lambda s: s.priority)

    if not result.sources:
        result.error = "未找到任何在线播放源"

    return result


async def search_online_source_aggregated(code: str) -> dict:
    """聚合搜索结果的字典版本，方便 API 返回 JSON。"""
    r = await search_online_source(code)
    return {
        "code": r.code,
        "title": r.title,
        "cover_url": r.cover_url,
        "sources": [
            {"url": s.url, "site": s.site, "quality": s.quality,
             "is_hls": s.is_hls, "note": s.note}
            for s in r.sources
        ],
        "source_count": len(r.sources),
        "error": r.error,
    }
