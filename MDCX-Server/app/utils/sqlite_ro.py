"""只读 SQLite 查询的**语句级**超时保护。

背景
----
项目里有 4 处 ``sqlite3.connect("file:...?mode=ro", timeout=10)``
（ltx_archive.py ×3、pornhub_external_db.py ×1）。这里的 ``timeout`` 只是
**锁等待**超时，管不住一条慢 SQL：一旦查询扫全表 / 递归 CTE 失控，
连接会一直占着；这些查询又跑在同步代码里被 async 路由调用，协程被取消
也停不住底层线程，表现就是接口挂死、线程池被慢慢吃满。

做法（借鉴 amane 的 ``set_progress_handler`` 思路，独立实现，未复制源码）：
按 VM 指令数回调，超过时限返回 1 让 SQLite 抛 ``SQLITE_INTERRUPT``。
计时从 ``execute`` 前开始、``finally`` 里撤销 handler —— **建连时间不计入**，
每个查询独立计时，长期持有的连接也不会累积误差。

用法::

    c = connect_ro(path)
    try:
        rows = fetch_all(c, "SELECT code FROM movies WHERE ...", label="ltx")
    finally:
        c.close()

``StatementTimeout`` 继承 RuntimeError；调用方现有的 ``except Exception``
会兜住并降级为空结果（这些查询本来就允许失败时返回空集）。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)

#: 默认语句时限（毫秒）。这些查询都是只读快查，10s 已经很宽松。
DEFAULT_STATEMENT_TIMEOUT_MS = 10_000

#: 每多少条 VM 指令回调一次。1000 是精度/开销的常见折中。
_PROGRESS_VM_STEPS = 1_000


class StatementTimeout(RuntimeError):
    """只读查询超过语句级时限（区别于锁等待超时）。"""


def connect_ro(path: str | Path, *, timeout: float = 10, **kwargs: Any) -> sqlite3.Connection:
    """打开只读连接。``timeout`` 仍是锁等待超时，与语句超时互补。"""
    p = Path(path)
    return sqlite3.connect(
        "file:%s?mode=ro" % p.as_posix(),
        uri=True,
        timeout=timeout,
        **kwargs,
    )


def fetch_all(
    conn: sqlite3.Connection,
    sql: str,
    params: Sequence[Any] | dict[str, Any] | None = None,
    *,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    label: str = "",
) -> list[Any]:
    """执行只读查询并取回全部行，超时抛 ``StatementTimeout``。

    ``statement_timeout_ms <= 0`` 表示不启用保护（保留给确需长跑的场景）。
    """
    if statement_timeout_ms <= 0:
        return conn.execute(sql, params or ()).fetchall()

    limit_s = statement_timeout_ms / 1000.0
    started = time.monotonic()
    tag = label or sql.strip().split("\n", 1)[0][:60]

    def _progress() -> int:
        return 1 if (time.monotonic() - started) >= limit_s else 0

    conn.set_progress_handler(_progress, _PROGRESS_VM_STEPS)
    try:
        return conn.execute(sql, params or ()).fetchall()
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            elapsed = (time.monotonic() - started) * 1000
            logger.warning(
                "[sqlite-ro] 只读查询超时: label=%s limit=%dms elapsed=%.0fms",
                tag, statement_timeout_ms, elapsed,
            )
            raise StatementTimeout(
                "只读查询超过 %dms 已中断: %s" % (statement_timeout_ms, tag)
            ) from e
        raise
    finally:
        # 必须撤销：连接可能被复用（pornhub_external_db 长期持有），
        # 否则下一次快查会沿用上一次已过期的起始时间而被立即打断。
        conn.set_progress_handler(None, 0)
