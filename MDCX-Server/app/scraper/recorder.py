"""刮削尝试记录器 —— 把内存里的失败统计变成可查询的源健康度

## 为什么需要（2026-10-04 实测）

`app/scraper/failure_reason.py` 已把失败分成 19 类，但数据只存在
`ScraperEngine.failures` 这个**进程内存 dict** 里，导致：

1. `failure_summary()` / `reset_failures()` **全仓零调用方** ——
   分级做完了却没有出口，没人看得到；
2. 重启即丢，看不出「哪个源最近一直在降」；
3. **成功次数压根没记** ⇒ 无法算成功率。而判断「哪个源在拖后腿」
   必须用 `成功/(成功+失败)`：只看失败数会把「量大但命中率高」的源
   和「几乎全败」的源混成同一个数字。

本模块负责把**成功与失败两侧**落到 `scrape_attempts` 表（`app/db/models.py`），
并对外提供源健康度聚合查询。

## 三条硬约束（都是实测踩出来的）

1. **绝不能拖慢刮削**：批量缓冲 + 后台 flush，缓冲满时**丢弃最旧的**
   并计数，绝不阻塞主流程。观测数据的价值远低于刮削本身。
2. **绝不能让主流程回滚**：写库一律try/except 吞掉，只记日志。
   一次「记录失败」绝不能变成「刮削失败」。
3. **不能无限增长**：`prune()` 按时间窗清理；调用方（API/任务结束）
   负责触发。默认保留 30 天。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: 内存缓冲上限。超出后丢弃最旧记录——宁可丢观测数据也不能让内存无限涨。
DEFAULT_BUFFER_SIZE = 500

#: 单次 flush 的最大条数（避免一条超长 SQL 锁住 sqlite 写锁）
DEFAULT_FLUSH_CHUNK = 100

#: 默认保留天数
DEFAULT_RETENTION_DAYS = 30


@dataclass
class AttemptRecord:
    """一条待落库的尝试记录（纯数据，不碰 DB）"""

    source: str
    success: bool
    reason: str = "none"
    matched_rule: Optional[str] = None
    duration_ms: Optional[int] = None
    number: Optional[str] = None
    module: Optional[str] = None
    error_type: Optional[str] = None
    message: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


class ScrapeRecorder:
    """刮削尝试记录器（进程内单例使用）

    典型用法::

        recorder = get_recorder()
        recorder.record_success("javdb", number, duration_ms=820, module="jav")
        recorder.record_failure(info, duration_ms=5000, module="jav")
        await recorder.flush()
    """

    def __init__(
        self,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._buf: list[AttemptRecord] = []
        self._buffer_size = max(1, buffer_size)
        self._retention_days = retention_days
        self._dropped = 0        # 因缓冲满被丢弃的条数
        self._write_errors = 0   # 写库失败次数（用于健康自检）
        self._written = 0
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def _push(self, rec: AttemptRecord) -> None:
        """入缓冲。**同步且不阻塞** —— 不能await，调用点在热路径上。"""
        if len(self._buf) >= self._buffer_size:
            # 丢最旧的 1/4，一次腾出空间，避免每条都丢一条
            drop = max(1, self._buffer_size // 4)
            del self._buf[:drop]
            self._dropped += drop
            if self._dropped and self._dropped % 100 < drop:
                logger.warning(
                    "刮削记录缓冲已满，累计丢弃 %s 条观测数据"
                    "（可调大 ScrapeRecorder.buffer_size）", self._dropped,
                )
        self._buf.append(rec)

    def record_success(
        self,
        source: str,
        number: Optional[str] = None,
        *,
        duration_ms: Optional[int] = None,
        module: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> None:
        """记录一次**成功**尝试。

        🔴 成功也必须记——这是能算出成功率的前提。只记失败的话，
        「尝试了 10 次成功 1 次」和「尝试了 1000 次成功 900 次」
        在统计上无法区分。
        """
        self._push(AttemptRecord(
            source=source, success=True, reason="none",
            number=number, module=module, task_id=task_id,
            duration_ms=duration_ms,
        ))

    def record_failure(
        self,
        info: Any,
        *,
        source: Optional[str] = None,
        number: Optional[str] = None,
        duration_ms: Optional[int] = None,
        module: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> None:
        """记录一次**失败**尝试。

        ``info`` 可以是 :class:`~app.scraper.failure_reason.FailureInfo`、
        异常、字符串或 None（"无异常但无结果"），内部统一走
        ``classify_scrape_error`` 归一化。
        """
        from app.scraper.failure_reason import classify_scrape_error

        try:
            fi = classify_scrape_error(info, source=source, number=number)
        except Exception as e:  # 分类器自身出错也不能影响主流程
            logger.debug("失败分类异常，降级为 unknown: %s", e)
            self._push(AttemptRecord(
                source=source or "?", success=False, reason="unknown",
                number=number, module=module, task_id=task_id,
                duration_ms=duration_ms, error_type="classify_error",
            ))
            return

        self._push(AttemptRecord(
            source=fi.source or source or "?",
            success=False,
            reason=fi.reason.value,
            matched_rule=fi.matched_rule,
            number=fi.number or number,
            module=module,
            task_id=task_id,
            duration_ms=duration_ms,
            error_type=fi.exception_type,
            message=(fi.message or "")[:500] or None,
        ))

    # ------------------------------------------------------------------
    # 落库
    # ------------------------------------------------------------------

    @property
    def pending(self) -> int:
        return len(self._buf)

    @property
    def stats(self) -> dict:
        return {
            "buffered": len(self._buf),
            "written": self._written,
            "dropped": self._dropped,
            "write_errors": self._write_errors,
        }

    async def flush(self) -> int:
        """把缓冲写入数据库，返回写入条数。

        永不抛异常：写库失败只计数。调用方可以放心 `await recorder.flush()`。
        """
        async with self._lock:
            if not self._buf:
                return 0
            batch, self._buf = self._buf, []

        try:
            await self._write_batch(batch)
            self._written += len(batch)
            return len(batch)
        except Exception as e:
            # 已从缓冲摘除的批次丢了就丢了——不能重新塞回去无限重试
            self._write_errors += 1
            logger.warning("刮削记录落库失败，丢弃 %s 条: %s", len(batch), e)
            return 0

    async def _write_batch(self, batch: list[AttemptRecord]) -> None:
        from sqlalchemy import insert

        from app.db.database import Database
        from app.db.models import ScrapeAttempt

        rows = [
            {
                "source": r.source[:50],
                "number": (r.number or None) and r.number[:100],
                "module": (r.module or None) and r.module[:20],
                "success": r.success,
                "reason": r.reason[:30],
                "matched_rule": r.matched_rule and r.matched_rule[:50],
                "duration_ms": r.duration_ms,
                "error_type": r.error_type and r.error_type[:80],
                "message": r.message,
                "task_id": r.task_id and r.task_id[:50],
                "created_at": r.created_at,
            }
            for r in batch
        ]

        db = Database()
        try:
            # 直接用底层 engine 批量插，避开 ORM 会话开销。
            # 观测数据用 ORM 反而慢：每条都要建 identity map。
            async with db.engine.begin() as conn:
                for i in range(0, len(rows), DEFAULT_FLUSH_CHUNK):
                    await conn.execute(insert(ScrapeAttempt), rows[i:i + DEFAULT_FLUSH_CHUNK])
        finally:
            await db.engine.dispose()

    def schedule_flush(self, delay: float = 5.0) -> None:
        """安排后台延迟 flush（不阻塞调用方）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # 无事件循环（如同步脚本里），跳过
        if self._flush_task and not self._flush_task.done():
            return
        self._flush_task = loop.create_task(self._delayed_flush(delay))

    async def _delayed_flush(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self.flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("后台 flush 失败: %s", e)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def prune(self, days: Optional[int] = None) -> int:
        """删除过期记录，返回删除条数。"""
        from sqlalchemy import delete, text

        from app.db.database import Database
        from app.db.models import ScrapeAttempt

        d = self._retention_days if days is None else days
        cutoff = datetime.now() - timedelta(days=d)
        db = Database()
        try:
            async with db.engine.begin() as conn:
                res = await conn.execute(
                    delete(ScrapeAttempt).where(ScrapeAttempt.created_at < cutoff)
                )
                #兜底：SQLite 里 DateTime 存字符串，比较可能不生效
                if not res.rowcount:
                    res = await conn.execute(
                        text(
                            "DELETE FROM scrape_attempts "
                            "WHERE created_at < :cutoff"
                        ),
                        {"cutoff": cutoff.strftime("%Y-%m-%d %H:%M:%S")},
                    )
                return int(res.rowcount or 0)
        except Exception as e:
            self._write_errors += 1
            logger.warning("清理 scrape_attempts 失败: %s", e)
            return 0
        finally:
            await db.engine.dispose()


# ----------------------------------------------------------------------
# 进程内单例
# ----------------------------------------------------------------------

_recorder: Optional[ScrapeRecorder] = None


def get_recorder() -> ScrapeRecorder:
    """获取进程内单例记录器。"""
    global _recorder
    if _recorder is None:
        _recorder = ScrapeRecorder()
    return _recorder


def reset_recorder() -> None:
    """重置单例（测试用）。"""
    global _recorder
    _recorder = None


# ----------------------------------------------------------------------
# 健康度聚合查询
# ----------------------------------------------------------------------

async def source_health(
    hours: int = 24,
    module: Optional[str] = None,
) -> list[dict]:
    """按源聚合近 N 小时的健康度，返回按成功率升序（最差的排最前）。

    这是「哪个源在拖后腿」的直接答案。判定口径：

    - ``success_rate`` = 成功 / (成功 + 失败)，**只看失败数会误判**，
      因为量大的源天然失败数高。
    - ``permanent_failures`` 单独列出：站点确认没有该资源 ≠ 源坏了。
    - ``avg_duration_ms`` 偏高常伴随被拦截或限流。

    返回行示例::

        {"source": "javbus", "attempts": 320, "successes": 12,
         "failures": 308, "success_rate": 0.0375,
         "permanent_failures": 300, "avg_duration_ms": 820,
         "top_reason": "not_found", "demote": true}
    """
    from sqlalchemy import text

    from app.db.database import Database

    since = datetime.now() - timedelta(hours=hours)
    db = Database()
    try:
        params: dict[str, Any] = {"since": since.strftime("%Y-%m-%d %H:%M:%S")}
        mod_where = "AND module = :module" if module else ""
        if module:
            params["module"] = module

        # 🔴 统计与 top_reason 必须写在**同一条 SQL** 里。
        # 拆成两条查询在 SQLite/WAL 下会拿到不同读快照：后写入的批次
        # 对先前开启的连接不可见，表现为「主查询统计到了 20 次失败，
        # 但 top_reason 恒为 None」（实测踩过，最难查的一类）。
        sql = f"""
            WITH agg AS (
                SELECT source,
                       COUNT(*)                                   AS attempts,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END)  AS successes,
                       SUM(CASE WHEN success THEN 0 ELSE 1 END)  AS failures,
                       AVG(COALESCE(duration_ms, 0))             AS avg_ms,
                       -- 永久性失败：站点确认无此资源，不代表源坏了
                       SUM(CASE WHEN reason IN
                           ('not_found','no_resource','gone','unsupported')
                           THEN 1 ELSE 0 END)AS permanent
                FROM scrape_attempts
                WHERE created_at >= :since {mod_where}
                GROUP BY source
            ),
            top AS (
                SELECT source, reason FROM (
                    SELECT source, reason,
                           ROW_NUMBER() OVER (
                               PARTITION BY source ORDER BY COUNT(*) DESC
                           ) AS rn
                    FROM scrape_attempts
                    WHERE success = 0 AND created_at >= :since {mod_where}
                    GROUP BY source, reason
                ) WHERE rn = 1
            )
            SELECT agg.source, agg.attempts, agg.successes, agg.failures,
                   agg.avg_ms, agg.permanent, top.reason AS top_reason
            FROM agg LEFT JOIN top ON agg.source = top.source
        """

        async with db.engine.connect() as conn:
            rows = (await conn.execute(text(sql), params)).mappings().all()

        out: list[dict] = []
        for r in rows:
            attempts = int(r["attempts"] or 0)
            successes = int(r["successes"] or 0)
            failures = int(r["failures"] or 0)
            permanent = int(r["permanent"] or 0)
            # 降权判定：量大 + 成功率极低 + 且存在**非永久性**失败
            #（全是不存在 ≠ 源坏了，那种情况降权会误伤）
            out.append({
                "source": r["source"],
                "attempts": attempts,
                "successes": successes,
                "failures": failures,
                "permanent_failures": permanent,
                "success_rate": round(successes / attempts, 4) if attempts else 0.0,
                "avg_duration_ms": int(r["avg_ms"] or 0),
                "top_reason": r["top_reason"],
                "demote": bool(
                    attempts >= 5
                    and successes / attempts < 0.05
                    and (failures - permanent) > 0
                ),
            })
        # 最差的排最前（调用方最需要先看到的就是这些）
        out.sort(key=lambda x: (x["success_rate"], -x["attempts"]))
        return out
    finally:
        await db.engine.dispose()


async def failure_breakdown(hours: int = 24) -> dict:
    """按失败原因汇总（跨源），用于回答「最近主要卡在哪类问题上」。"""
    from sqlalchemy import text

    from app.db.database import Database

    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    db = Database()
    try:
        async with db.engine.connect() as conn:
            rows = (await conn.execute(
                text(
                    "SELECT reason, COUNT(*) n FROM scrape_attempts "
                    "WHERE success = 0 AND created_at >= :since "
                    "GROUP BY reason ORDER BY n DESC"
                ),
                {"since": since},
            )).all()
        return {r[0]: int(r[1]) for r in rows}
    except Exception as e:
        logger.warning("查询失败分布出错: %s", e)
        return {}
    finally:
        await db.engine.dispose()
