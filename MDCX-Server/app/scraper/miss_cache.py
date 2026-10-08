"""按源记忆「明确答复没有」的番号 —— 缺口补全的「负缓存」。

## 为什么需要（来自 ref96-peach / library_processing.py::_MissCache）

缺口补全每轮会对同一批「源站确实没收录」的番号反复发起请求，每条卡在
站点间隔上，答案永远一样。真实账本上这样的行有几百到上千条，一轮就是
几十分钟纯浪费。按源把「说过没有」记下来，期内不再问，能直接把这部分
时间砍掉。

## 三条硬约束（实测踩出来的）

1. **只记 NotFound**：网络故障 / 超时 / 被拦截，下次可能就好了，**绝不**
   记进负缓存。否则会把一个暂时被墙的源永久跳过。在缺口补全里，
   ``_try_source`` 的 ``fatal`` 分支（超时/异常/被封）永远不会走到 record，
   只有「源正常返回、但没这片」才记。
2. **按源分开记**：一档里几站各说各的「没有」，接上新的一站只多出一个
   没有记忆的站，别的站说过的照旧作数。所以键是 ``(source, code)``。
3. **新源接入即失效**：记录时带着当时的「源阵容」(lineup)。若之后给某番号
   试的阵容里出现了**记录时还不存在的源**，这条记忆作废 —— 因为那个新源
   可能刚好有这部片。这是 ref96 的 ``joined`` 机制。

## 与 ref96 的差异

- 落盘格式简化为单文件 JSON（每模块一个），不再有按档/按站的 legacy 兼容。
- 阵容失效判定用 ``joined[source] > stamp``（严格大于）—— 记录时该源已在
  阵容中，其 joined 时刻 == 记录时刻，不会被自己误伤；只有「记录之后才出现」
  的源才会使旧记忆失效。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

# 来源明确答复「没有」之后多久不再问。「没有」不是永久的：来源会补录，
# 片子可能后来上架。与 ref96 的 MISS_TTL_SECONDS 保持一致（7 天）。
MISS_TTL_SECONDS = 7 * 24 * 3600

# 单模块负缓存条目硬上限（防御性：超出后丢最旧的）。正常 TTL 7 天会先清掉大部分。
_MAX_ENTRIES = 200_000


def _default_now() -> float:
    return time.time()


class MissCache:
    """来源明确答复「没有」的番号，按源分开记，期内不再问。

    典型用法::

        cache = MissCache(path)
        # 试源前：该源已知无此片 → 跳过
        if cache.fresh(src, code, lineup=order):
            return None
        r = await scrape_number(...)
        if r is None and not fatal:        # 源正常返回但没这片
            cache.record(src, code, lineup=order)
    """

    def __init__(
        self,
        path: str | Path,
        *,
        ttl: int = MISS_TTL_SECONDS,
        now: Optional[type(time.time)] = None,
    ) -> None:
        self._path = Path(path)
        self._ttl = ttl
        self._now = now or _default_now
        self._entries: dict[str, dict[str, float]] = {}   # source -> {code: stamp}
        self._joined: dict[str, float] = {}               # source -> 首次出现时刻
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        for source, codes in (data.get("misses") or {}).items():
            if isinstance(codes, dict):
                self._entries[source] = {
                    c: float(t) for c, t in codes.items()
                    if isinstance(t, (int, float))
                }
        joined = data.get("joined") or {}
        if isinstance(joined, dict):
            self._joined = {
                s: float(t) for s, t in joined.items()
                if isinstance(t, (int, float))
            }

    def _save(self) -> None:
        now = self._now()
        # TTL 内保留；顺手丢过期项
        misses = {
            s: {c: t for c, t in codes.items() if now - t < self._ttl}
            for s, codes in self._entries.items()
            if codes
        }
        # 硬上限：按 (source, code) 收集后丢最旧的
        flat: list[tuple[float, str, str]] = []
        for s, codes in misses.items():
            for c, t in codes.items():
                flat.append((t, s, c))
        if len(flat) > _MAX_ENTRIES:
            flat.sort()  # 最早的在前
            drop = len(flat) - _MAX_ENTRIES
            for _, s, c in flat[:drop]:
                misses.get(s, {}).pop(c, None)
        data = {
            "misses": {s: c for s, c in misses.items() if c},
            "joined": {s: t for s, t in self._joined.items() if now - t < self._ttl},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    # ------------------------------------------------------------------
    # 阵容（lineup）簿记：记录/查询时遇到没见过的源 → 记下其接入时刻
    # ------------------------------------------------------------------
    def _observe_lineup(self, lineup: Iterable[str]) -> bool:
        """把阵容里未登记的源记为「此刻接入」。返回是否有新源被登记（用于决定落盘）。"""
        now = self._now()
        grew = False
        for s in lineup:
            if s not in self._joined:
                self._joined[s] = now
                grew = True
        return grew

    # ------------------------------------------------------------------
    # 查询 / 记录
    # ------------------------------------------------------------------
    def fresh(self, source: str, code: str, lineup: Iterable[str] = ()) -> bool:
        """``source`` 对 ``code`` 说过「没有」且还在期内，且记录时的阵容未变。

        ``lineup`` 是本次应当问的源集合（如 ``source_order_for(code)``）。
        其中若有源是记录之后才接入的，这条记忆作废（新源可能刚好有这部片）。
        """
        with self._lock:
            lineup = tuple(lineup)
            grew = self._observe_lineup(lineup)
            stamp = self._entries.get(source, {}).get(code)
            if stamp is None or (self._now() - stamp) >= self._ttl:
                if grew:
                    self._save()
                return False
            # 阵容失效：存在晚于本条记忆接入的源
            for s in lineup:
                if self._joined.get(s, 0.0) > stamp:
                    if grew:
                        self._save()
                    return False
            return True

    def record(self, source: str, code: str, lineup: Iterable[str] = ()) -> None:
        """记下 ``source`` 对 ``code`` 说过「没有」。每次都落盘，任务被打断也不丢。"""
        with self._lock:
            lineup = tuple(lineup)
            self._observe_lineup(lineup)
            now = self._now()
            self._entries.setdefault(source, {})[code] = now
            self._save()

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------
    def count(self) -> int:
        with self._lock:
            return sum(len(c) for c in self._entries.values())

    def prune(self) -> int:
        """丢弃过期条目，返回删除条数。"""
        with self._lock:
            now = self._now()
            removed = 0
            for codes in self._entries.values():
                stale = [c for c, t in codes.items() if now - t >= self._ttl]
                for c in stale:
                    codes.pop(c, None)
                    removed += 1
            self._entries = {s: c for s, c in self._entries.items() if c}
            self._save()
            return removed


# ----------------------------------------------------------------------
# 模块级单例：每模块一个负缓存文件，放在 data/cache/miss/<module>.json
# ----------------------------------------------------------------------
_CACHES: dict[str, MissCache] = {}
_CACHES_LOCK = threading.Lock()


def get_miss_cache(module: str) -> MissCache:
    """取某模块的负缓存单例（进程内共享，落盘在 data/cache/miss/<module>.json）。"""
    with _CACHES_LOCK:
        cached = _CACHES.get(module)
        if cached is not None:
            return cached
        from app.config.manager import DATA_DIR

        path = Path(DATA_DIR) / "cache" / "miss" / f"{module}.json"
        cache = MissCache(path)
        _CACHES[module] = cache
        return cache


def reset_miss_cache() -> None:
    """清空单例（测试用）。"""
    with _CACHES_LOCK:
        _CACHES.clear()
