"""想要清单的磁力资源查询（学 peach wants_magnets 的只读资源层）

对 wants 清单的番号搜磁力资源。磁力解析不重写——复用
`aggregate_searcher`（sukebei 源，2026-10-25 实测直连 200、SSIS-001
搜出 25 条含中字版），本模块只做编排：

- 缓存：内存 OrderedDict 128 部 + TTL，重复打开对话框不重复打源
- 串行限速：Semaphore(1) —— 一台服务同时只查一部（peach 同款设计，
  防把 sukebei 打爆触发验证码/封禁）
- 失败冷却：同番号失败 60s 内不重试（peach 同款）
- 排序：中字优先 → 有做种优先 → 做种数降序 → 有大小优先
  （upgrade_candidate 场景下用户要的就是中字版，排最前）

下载：`send_to_downloader` 把选中磁力交给 downloader_manager 的激活
下载器（aria2/qb/tr 都实现 add_torrent），只负责转交，不管下载进度
（下载页已有）。

代理说明：sukebei.nyaa.si 已加入 xray_config.SCRAPE_PROXY_DOMAINS
（domain 模式下清单外域名一律直连，国内出口会静默超时）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Callable, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 缓存容量（部）与 TTL（秒）
_CACHE_CAPACITY = 128
_CACHE_TTL = 30 * 60
# 失败冷却（秒）：同番号失败后这段时间内直接返回失败，不打源
_FAILURE_COOLDOWN = 60
# 单次搜索返回的最大条目数
_MAX_ITEMS = 128

# 内存缓存：normalized_code -> (monotonic_ts, result_dict)
_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
# 失败冷却：normalized_code -> monotonic_ts
_failures: dict[str, float] = {}
# 串行锁：同时只允许一个搜索在飞（peach 同款限速）
_search_sem = asyncio.Semaphore(1)


def _rank_key(item: dict):
    """排序键：中字 > 有做种 > 做种数 > 有大小 > 大小。"""
    return (
        0 if item.get("is_chinese") else 1,
        0 if (item.get("seeders") or 0) > 0 else 1,
        -(item.get("seeders") or 0),
        0 if (item.get("size") or 0) > 0 else 1,
        -(item.get("size") or 0),
    )


def _format_size(n: int) -> str:
    if not n or n <= 0:
        return ""
    units = [("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)]
    for label, factor in units:
        if n >= factor:
            return f"{n / factor:.2f} {label}"
    return f"{n} B"


def _get_searcher():
    """拿聚合搜索器（懒建，失败返回 None）。"""
    try:
        from app.services.aggregate_searcher import (
            AggregateSearcher, search_sukebei,
        )
        from app.services.proxy_manager import get_effective_proxy_url

        searcher = AggregateSearcher(proxy=get_effective_proxy_url())
        searcher.register("sukebei", search_sukebei)
        return searcher
    except Exception as e:
        logger.warning(f"[wants_resources] 搜索器不可用: {e}")
        return None


async def search_resources(
    code: str,
    force: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """搜一个番号的磁力资源（只读，不碰任何文件/下载器）。

    Args:
        code: 番号（SSIS-001 / ssis-001 均可，内部 normalize）
        force: 跳过缓存强制重搜（用户手动点「刷新」）
        log: 可选日志回调

    Returns:
        {
          "state": "ready" | "empty" | "error" | "cooldown",
          "code": 归一化番号,
          "items": [{id,name,magnet,size,size_text,seeders,is_chinese,source}],
          "cached": bool,          # 是否来自缓存
          "message": str,          # error/cooldown/empty 时的人类可读说明
        }
    """
    _log = log or (lambda _m: None)
    from app.services.wants import normalize_code

    nc = normalize_code(code)
    if not nc:
        return {"state": "error", "code": "", "items": [],
                "message": "番号不能为空", "cached": False}

    # 缓存命中（force 时跳过）
    if not force:
        hit = _cache.get(nc)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL:
            _cache.move_to_end(nc)
            return {**hit[1], "cached": True}
        if hit:
            del _cache[nc]

    # 失败冷却
    fail_ts = _failures.get(nc)
    if fail_ts and time.monotonic() - fail_ts < _FAILURE_COOLDOWN:
        return {"state": "cooldown", "code": nc, "items": [],
                "message": "刚才搜索失败，请稍后再试（60 秒冷却）", "cached": False}

    searcher = _get_searcher()
    if searcher is None:
        return {"state": "error", "code": nc, "items": [],
                "message": "搜索服务不可用", "cached": False}

    _log(f"正在搜索 {nc} 的磁力资源…")
    async with _search_sem:  # 串行：一部一部来，不打爆源
        try:
            agg = await searcher.search(nc, concurrency=3)
        except Exception as e:
            logger.warning(f"[wants_resources] 搜索 {nc} 失败: {type(e).__name__}: {e}")
            _failures[nc] = time.monotonic()
            return {"state": "error", "code": nc, "items": [],
                    "message": f"搜索失败：{type(e).__name__}", "cached": False}

    items = []
    for r in agg.results:
        if not r.magnet:
            continue
        items.append({
            "id": f"magnet:{(r.magnet[:64])}",
            "name": r.name,
            "magnet": r.magnet,
            "size": r.size,
            "size_text": _format_size(r.size),
            "seeders": r.seeders,
            "is_chinese": bool(r.is_chinese_sub),
            "source": r.source or "sukebei",
        })
    items.sort(key=_rank_key)
    items = items[:_MAX_ITEMS]

    if not items:
        result = {"state": "empty", "code": nc, "items": [],
                  "message": "没有搜到资源（可能还没放出，或源被限流）",
                  "cached": False}
        if agg.errors:
            result["message"] += f"；源错误：{agg.errors[0][:80]}"
        _failures.pop(nc, None)
        _cache[nc] = (time.monotonic(), result)
        if len(_cache) > _CACHE_CAPACITY:
            _cache.popitem(last=False)
        return {**result, "cached": False}

    result = {
        "state": "ready", "code": nc, "items": items, "message": "",
        "cached": False,
        "total_time_ms": round(agg.total_time_ms, 1),
        "chinese_count": sum(1 for i in items if i["is_chinese"]),
    }
    _failures.pop(nc, None)
    _cache[nc] = (time.monotonic(), result)
    if len(_cache) > _CACHE_CAPACITY:
        _cache.popitem(last=False)
    _log(f"{nc}：搜到 {len(items)} 条资源（中字 {result['chinese_count']} 条）")
    return {**result, "cached": False}


def clear_cache() -> int:
    """清空资源缓存（设置页/测试用）。返回清掉的条数。"""
    n = len(_cache)
    _cache.clear()
    _failures.clear()
    return n


async def send_to_downloader(
    magnet: str,
    download_dir: Optional[str] = None,
    name: Optional[str] = None,
) -> dict:
    """把磁力交给当前激活的下载器（aria2/qb/tr）。

    只转交，不管下载进度（下载页已有任务列表）。
    """
    if not magnet or not magnet.strip().lower().startswith("magnet:"):
        return {"status": "error", "message": "不是有效的磁力链接"}

    from app.services.downloader_manager import DownloaderManager
    from app.config.manager import get_config

    manager = DownloaderManager()
    try:
        downloader = manager.get_active()
    except Exception as e:
        logger.warning(f"[wants_resources] 取激活下载器失败: {e}")
        return {"status": "error", "message": f"下载器不可用：{type(e).__name__}"}
    if downloader is None:
        return {"status": "error",
                "message": "没有激活的下载器（请先在下载设置里启用并测试通过）"}

    active_name = get_config().downloader.active or (manager.list_available() or [""])[0]
    try:
        task_id = await downloader.add_torrent(magnet.strip(), download_dir=download_dir, name=name)
        logger.info(f"[wants_resources] 已发送到 {active_name or 'downloader'}: {task_id}")
        return {"status": "ok", "task_id": str(task_id), "downloader": active_name}
    except Exception as e:
        logger.error(f"[wants_resources] 发送下载失败: {e}")
        return {"status": "error", "message": f"发送下载失败：{e}"}


__all__ = ["search_resources", "send_to_downloader", "clear_cache"]
