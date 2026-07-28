"""多站点聚合搜索 API。

一个接口搜索多个 Torrent/磁力站点，按 hash 去重排序。
支持注册任意搜索源，并发执行，统一结果格式。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import httpx
from bs4 import BeautifulSoup

from app.config.manager import get_config

log = logging.getLogger(__name__)


@dataclass
class TorrentResult:
    name: str
    magnet: str = ""
    size: int = 0
    seeders: int = 0
    leechers: int = 0
    source: str = ""
    code: str = ""
    is_chinese_sub: bool = False
    detail_url: str = ""


@dataclass
class AggregateResult:
    query: str
    results: list[TorrentResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_time_ms: float = 0.0


SearchFn = Callable[[str, httpx.AsyncClient], Awaitable[list[TorrentResult]]]


class AggregateSearcher:
    """多站点聚合搜索器。"""

    def __init__(self, proxy: Optional[str] = None, timeout: float = 15.0):
        self.proxy = proxy
        self.timeout = timeout
        self._searchers: dict[str, SearchFn] = {}

    def register(self, name: str, fn: SearchFn):
        self._searchers[name] = fn

    async def search(self, query: str, concurrency: int = 5) -> AggregateResult:
        start = time.time()
        result = AggregateResult(query=query)
        if not self._searchers:
            return result

        sem = asyncio.Semaphore(concurrency)

        async def _search_one(name: str, fn: SearchFn):
            async with sem:
                try:
                    async with httpx.AsyncClient(
                        timeout=self.timeout,
                        proxy=self.proxy,
                        follow_redirects=True,
                    ) as client:
                        items = await fn(query, client)
                        result.results.extend(items)
                except Exception as e:
                    result.errors.append(f"{name}: {e}")

        await asyncio.gather(*(
            _search_one(name, fn) for name, fn in self._searchers.items()
        ))

        seen_hashes: set[str] = set()
        deduped: list[TorrentResult] = []
        for r in sorted(result.results, key=lambda x: x.seeders, reverse=True):
            key = r.magnet[:50] if r.magnet else r.name[:60]
            if key not in seen_hashes:
                seen_hashes.add(key)
                deduped.append(r)

        result.results = deduped
        result.total_time_ms = (time.time() - start) * 1000
        return result


# ---------------------------------------------------------------------------
# 内置搜索源
# ---------------------------------------------------------------------------


async def search_sukebei(query: str, client: httpx.AsyncClient) -> list[TorrentResult]:
    results: list[TorrentResult] = []
    url = f"https://sukebei.nyaa.si/?q={query}&s=seeders&o=desc"
    try:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return results
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("table.torrent-list > tbody > tr"):
            cols = row.select("td")
            if len(cols) < 6:
                continue
            name_el = cols[1].select_one("a:last-child")
            magnet_el = cols[2].select_one('a[href^="magnet:"]')
            size_text = cols[3].get_text(strip=True)
            seeders_text = cols[5].get_text(strip=True)

            name = name_el.get_text(strip=True) if name_el else ""
            magnet = magnet_el["href"] if magnet_el else ""
            seeders = int(seeders_text) if seeders_text.isdigit() else 0
            size = _parse_size(size_text)

            if name:
                results.append(TorrentResult(
                    name=name, magnet=magnet, size=size,
                    seeders=seeders, source="sukebei",
                    is_chinese_sub="字幕" in name or "中字" in name or "CH" in name.upper(),
                ))
    except Exception as e:
        log.warning("sukebei search failed: %s", e)
    return results


def _parse_size(text: str) -> int:
    text = text.strip().upper()
    m = re.match(r"([\d.]+)\s*(KI?B|MI?B|GI?B|TI?B|B)", text)
    if not m:
        return 0
    num = float(m.group(1))
    unit = m.group(2)
    multipliers = {"B": 1, "KIB": 1024, "KB": 1024, "MIB": 1024 ** 2, "MB": 1024 ** 2,
                   "GIB": 1024 ** 3, "GB": 1024 ** 3, "TIB": 1024 ** 4, "TB": 1024 ** 4}
    return int(num * multipliers.get(unit, 1))


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_default_searcher() -> AggregateSearcher:
    """创建带默认搜索源的聚合搜索器。"""
    config = get_config()
    proxy = None
    if config.proxy.enabled and config.proxy.address:
        proxy = f"http://{config.proxy.address}:{config.proxy.port}"

    searcher = AggregateSearcher(proxy=proxy)
    searcher.register("sukebei", search_sukebei)
    return searcher
