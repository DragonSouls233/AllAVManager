"""PORNHub 搜索缓存 — 避免重复请求同一视频。

缓存视图: viewkey → ScrapeResult
过期时间: 24h
存储: 内存缓存（服务重启丢失）+ 可选磁盘持久化
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 24 * 3600  # 24 小时
_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "pornhub_cache.json",
)


@dataclass
class PornhubCacheEntry:
    viewkey: str
    result_json: str
    timestamp: float = 0.0


class PornhubSearchCache:
    """线程安全的 PORNHub 搜索缓存。"""

    def __init__(self, ttl: int = _CACHE_TTL, persist: bool = True):
        self._ttl = ttl
        self._persist = persist
        self._lock = Lock()
        self._cache: dict[str, PornhubCacheEntry] = {}
        self._load()

    def get(self, viewkey: str) -> Optional[dict]:
        """获取缓存的搜索结果。"""
        with self._lock:
            entry = self._cache.get(viewkey)
            if not entry:
                return None
            if time.time() - entry.timestamp > self._ttl:
                del self._cache[viewkey]
                return None
            try:
                return json.loads(entry.result_json)
            except json.JSONDecodeError:
                return None

    def set(self, viewkey: str, data: dict):
        """缓存搜索结果。"""
        with self._lock:
            self._cache[viewkey] = PornhubCacheEntry(
                viewkey=viewkey,
                result_json=json.dumps(data, ensure_ascii=False),
                timestamp=time.time(),
            )
        if self._persist:
            self._save()

    def has(self, viewkey: str) -> bool:
        with self._lock:
            entry = self._cache.get(viewkey)
            if not entry:
                return False
            if time.time() - entry.timestamp > self._ttl:
                del self._cache[viewkey]
                return False
            return True

    def clear(self):
        with self._lock:
            self._cache.clear()
        if self._persist:
            self._save()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def _load(self):
        if not self._persist:
            return
        try:
            path = Path(_CACHE_FILE)
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                for viewkey, entry in data.items():
                    self._cache[viewkey] = PornhubCacheEntry(
                        viewkey=viewkey,
                        result_json=entry.get("result_json", ""),
                        timestamp=entry.get("timestamp", 0),
                    )
                if self._cache:
                    logger.info("Pornhub cache loaded: %d entries", len(self._cache))
        except Exception as e:
            logger.debug("Pornhub cache load failed: %s", e)

    def _save(self):
        if not self._persist:
            return
        try:
            path = Path(_CACHE_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                viewkey: {"result_json": e.result_json, "timestamp": e.timestamp}
                for viewkey, e in self._cache.items()
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("Pornhub cache save failed: %s", e)


# 全局单例
_search_cache = None


def get_search_cache() -> PornhubSearchCache:
    global _search_cache
    if _search_cache is None:
        _search_cache = PornhubSearchCache()
    return _search_cache
