"""详情页 HTML 结构健康度（可观测 + 降级判定）。

背景
----
2026-11-06 实测参考项目 ref206-JAVscraper 的 javDB 改版修复：
详情页信息块从 ``section > div > div:nth-of-type(5)`` 挪到了 ``(4)``。
我方 ``app/crawlers/javdb.py`` 用**语义 XPath**（按 "日期:" / "片商:" 等
标签文字定位），这次改版没有影响 —— 但这恰恰是最危险的地方：

    一旦站点把标签文字或 DOM 层级也改掉，所有 XPath 会**同时返回空**，
    爬虫只得到一个「只有番号、没有任何字段」的结果，甚至直接 None。
    上层看到 None 只会当成「这个源没数据」，既没有日志、也没有指标，
    运维要等到用户发现字段全空才察觉，且很难和「该片确实没收录」区分。

本模块提供进程内的轻量计数（不加 DB 表、不引入依赖），供：

- 爬虫在结构异常时打 warning 日志（带番号/缺失锚点/缺失字段）；
- ``GET /api/v1/crawlers/health`` 暴露 ``detail_structure``，前端一眼可见；
- 后续接入告警/自动切换端点时有现成的信号源。

思路借鉴 amane 的「解析结构变更可观测」，独立实现，未复制任何源码。
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any

_lock = threading.Lock()

#: 每源的累计计数；值为 Counter，允许任意键，方便以后扩展。
_stats: dict[str, Counter] = {}

#: 每源最近一次异常的结构签名（只保留 last，不落盘、不记番号全集）。
_last: dict[str, dict[str, Any]] = {}


def _counter(source: str) -> Counter:
    c = _stats.get(source)
    if c is None:
        c = Counter()
        _stats[source] = c
    return c


def record_detail_check(
    source: str,
    *,
    code: str = "",
    kind: str = "ok",
    missing_anchors: list[str] | None = None,
    missing_fields: list[str] | None = None,
) -> None:
    """记录一次详情页结构检查。

    kind 取值：
      ``ok``                 结构正常；
      ``structure_degraded`` 详情页面在、但信息块锚点消失 / 字段几乎全空；
      ``not_detail_page``    压根不是详情页（CF 挑战页、404、列表页），
                             属于网络/反爬问题，**不要**算成结构改版。
    """
    with _lock:
        _counter(source)[kind] += 1
        if kind != "ok":
            _last[source] = {
                "kind": kind,
                "code": code,
                "at": time.time(),
                "missing_anchors": list(missing_anchors or []),
                "missing_fields": list(missing_fields or []),
            }


def record_fallback_result(source: str, ok: bool) -> None:
    """记录一次「HTML 结构失效 → 改用官方 App API」的结果。"""
    with _lock:
        c = _counter(source)
        c["fallback_attempts"] += 1
        c["fallback_ok" if ok else "fallback_failed"] += 1


def get_detail_structure_stats() -> dict[str, dict]:
    """返回快照（供健康端点 / 前端展示）。``at`` 为 Unix 秒。"""
    with _lock:
        out: dict[str, dict] = {}
        for source, c in _stats.items():
            row = dict(c)
            last = dict(_last.get(source, {}))
            out[source] = {**row, "last": last}
        return out


def reset_detail_structure_stats() -> None:
    """清空统计（测试用）。"""
    with _lock:
        _stats.clear()
        _last.clear()
