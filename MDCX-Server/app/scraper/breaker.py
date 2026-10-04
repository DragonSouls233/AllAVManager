"""源熔断器 —— 在**发起请求之前**短路已知失效的源。

## 为什么必须有这个（2026-10-04 实测）

`BaseCrawler.mark_error()` 里已有一条禁用逻辑，但它是**请求之后**才计数，
而且只统计**进程内存**：

```python
if self._error_count >= 10 and self._success_count == 0:
    self._status = CrawlerStatus.ERROR
```

三个问题，叠加起来就是批量刮削时的"卡住不动"：

1. **前 10 次必等满超时**。一个 DNS 解析失败的源，每次 `scrape()` 都要
   等满 `engine.timeout`（默认 60s）才返回 None。批量补刮 5000 个番号
   × 3 个死源 = 白等 250 小时。这正是"刮削走一半不动"的真凶之一。
2. **重启即忘**。`_error_count` 在 `__init__` 里归零，服务重启后
   死源重新排队再等 10 次。服务器上服务重启很频繁（崩溃恢复、配置变更），
   于是同一个死源会被反复重新"发现"。
3. **不区分失败性质**。`not_found`（站点确实没这个番号）被当成源的过错，
   而 `local`（本地信号量耗尽）根本不是源的锅 —— 按现在的逻辑，
   本地并发打满会把好源也累到 10 次然后禁用掉。

## 本模块的做法

- **持久化**：判定依据查 `scrape_attempts` 表（上一轮已建），
  重启后立即生效，不需要重新试错。
- **分级冷却**：按 `FailureReason` 的 `permanent/blocked/transient/local`
  四类给完全不同的冷却时长，避免"限流一下就永久下线"和
  "永久失效只冷却 1 分钟"这两种反向错误。
- **前置短路**：检查点在 `engine._scrape_with_crawler` 的信号量 acquire
  **之前**，命中熔断直接返回 None，**不占并发名额、不发网络请求**。
- **半开探测**：冷却期满后放 1 个请求过去（half-open），
  成功则清零重建，失败则冷却时长翻倍（上限封顶）。

## 为什么不做成"永久拉黑"

站点会恢复：`www.madouqu.com` 实测同一天内先是 200/71KB，几小时后全
`ConnectTimeout`；`getchu.com` 首页通、搜索从可用变成恒返回"全0件中"。
永久拉黑等于一次误判就永久损失一个源。所以采用**带上限的指数退避**：
反复失败时冷却期会稳定在一个较长的值（默认封顶 6 小时），但始终保留
半开机会。

## 口径细节

- **只看最近窗口**：默认 30 分钟。避免"三天前失败过一次"就永久熔断好源。
- **最小样本量**：默认 5 次。1~2 次失败可能只是偶发网络抖动。
- **成功率 0 才熔断**：只要窗口内有过成功，就不熔断（哪怕失败 9 次成功 1 次）。
- **完全无记录 = 不熔断**：新源第一次调用必须放行，否则永远无法建立样本。
- **`local` 类失败一票否决**：`failures` 类为 `local` 说明是本地资源问题
  （信号量耗尽、写库失败），这类失败**不计入**熔断判定。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.scraper.failure_reason import (
    BLOCKING_REASONS,
    LOCAL_REASONS,
    PERMANENT_REASONS,
    TRANSIENT_REASONS,
    FailureReason,
)


# ----------------------------------------------------------------------
# 冷却时长配置
# ----------------------------------------------------------------------

#: 永久性失败（DNS 解析不了 / 404 / 站点确认无此资源）→ 长冷却
DEFAULT_PERMANENT_COOLDOWN = 30 * 60.0          # 30 分钟

#: 被拦截（403 / 反爬 / 需要登录）→ 中长冷却，站点可能几小时后放开
DEFAULT_BLOCKED_COOLDOWN = 10 * 60.0           # 10 分钟

#: 瞬时故障（超时 / 5xx / 连接重置）→ 短冷却，这类恢复很快
DEFAULT_TRANSIENT_COOLDOWN = 90.0              # 90 秒

#: 冷却时长上限（指数退避封顶）
MAX_COOLDOWN = 6 * 3600.0                      # 6 小时

#: 判定窗口：只看最近这么多时间内的尝试
DEFAULT_WINDOW_MINUTES = 30

#: 窗口内至少要有这么多次尝试才判定，避免 1 次偶发失败就熔断
DEFAULT_MIN_SAMPLES = 5

#: 每熔断一次冷却翻倍的倍数（用于半开失败后的退避）
BACKOFF_FACTOR = 2.0

#: 视为「有成功过」的最小成功率。严格大于 0 即不熔断。
_SUCCESS_RATE_EXEMPT = 0.0


# ----------------------------------------------------------------------
# 失败分级 → 基础冷却
# ----------------------------------------------------------------------

def _cooldown_for_reason(reason: str) -> Optional[float]:
    """按失败原因返回基础冷却秒数。

    返回 ``None`` 表示**不参与熔断判定**（本地问题）。

    🔴 这里判定用 ``failure_reason`` 导出的**字符串集合**
    （``PERMANENT_REASONS`` / ``BLOCKING_REASONS`` / ``TRANSIENT_REASONS`` /
    ``LOCAL_REASONS``），而不是枚举上的属性 —— ``is_permanent`` 等属性
    只存在于 ``FailureInfo`` 上，``FailureReason`` 枚举本身没有。
    写成 ``fr.permanent`` 会直接 AttributeError。

    判定顺序刻意是 local → permanent → blocking → transient：
    一个原因可能同时落进多个集合（如 ``db_error`` 既属 local 也可能属
    transient），**local 优先**才能保证"本地问题不熔断好源"这条铁律。
    """
    try:
        fr = FailureReason(reason)
    except ValueError:
        # 未知原因：给短冷却但不打满标记，避免误伤好源。
        # 不能返回 None —— 那等于完全不熔断，未知失败会变成无限重试。
        return 45.0

    val = fr.value
    if val in LOCAL_REASONS:
        return None
    if val in PERMANENT_REASONS:
        return DEFAULT_PERMANENT_COOLDOWN
    if val in BLOCKING_REASONS:
        return DEFAULT_BLOCKED_COOLDOWN
    if val in TRANSIENT_REASONS:
        return DEFAULT_TRANSIENT_COOLDOWN
    return 45.0


# ----------------------------------------------------------------------
# 熔断状态
# ----------------------------------------------------------------------

@dataclass
class BreakerState:
    """单个源的熔断状态（进程内缓存，权威数据在 scrape_attempts 表）。"""

    name: str
    #: 熔断到期时间戳（time.monotonic 基准）
    open_until: float = 0.0
    #: 连续熔断次数，用于指数退避
    strike: int = 0
    #: 是否处于「半开」状态（冷却已过，放行 1 个探测请求）
    half_open: bool = False
    #: 统计信息，仅用于日志与 /crawlers/health 展示
    last_reason: str = ""
    last_opened_at: float = 0.0

    def is_open(self, now: float) -> bool:
        """当前是否应短路。"""
        if self.open_until <= 0:
            return False
        if now >= self.open_until:
            # 冷却期满 → 半开，放一个请求过去试探
            return False
        return True


@dataclass
class BreakerDecision:
    """熔断判定结果，便于调用方记录与测试断言。"""

    should_skip: bool
    reason: str = ""
    cooldown: float = 0.0
    stats: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# 熔断器
# ----------------------------------------------------------------------

class SourceBreaker:
    """按源名维护熔断状态。**线程/协程安全**不做强保证 ——
    判定最坏只是"多放一个请求过去"，不会造成正确性问题。
    """

    def __init__(
        self,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        enabled: bool = True,
    ) -> None:
        self.window_minutes = window_minutes
        self.min_samples = min_samples
        self.enabled = enabled
        self._states: dict[str, BreakerState] = {}

    # -- 状态访问 ------------------------------------------------------

    def get_state(self, name: str) -> BreakerState:
        st = self._states.get(name)
        if st is None:
            st = BreakerState(name=name)
            self._states[name] = st
        return st

    def snapshot(self) -> dict[str, dict]:
        """当前所有熔断中的源（供健康度接口展示）。"""
        now = time.monotonic()
        out: dict[str, dict] = {}
        for name, st in self._states.items():
            if st.open_until > now:
                out[name] = {
                    "open_until": st.open_until,
                    "remaining": round(st.open_until - now, 1),
                    "strike": st.strike,
                    "last_reason": st.last_reason,
                }
        return out

    def reset(self, name: Optional[str] = None) -> None:
        """清除熔断状态（手动恢复 / 测试用）。"""
        if name is None:
            self._states.clear()
        else:
            self._states.pop(name, None)

    # -- 判定 ----------------------------------------------------------

    def check(self, name: str, now: Optional[float] = None) -> BreakerDecision:
        """本地快速判定：是否处于熔断中（不查库）。"""
        if not self.enabled:
            return BreakerDecision(False)
        now = now if now is not None else time.monotonic()
        st = self.get_state(name)
        if st.is_open(now):
            return BreakerDecision(
                should_skip=True,
                reason=f"circuit_open:{st.last_reason or 'unknown'}",
                cooldown=st.open_until - now,
            )
        return BreakerDecision(False)

    async def check_persisted(
        self,
        name: str,
        now: Optional[float] = None,
    ) -> BreakerDecision:
        """完整判定：先查本地状态，再查 ``scrape_attempts`` 持久数据。

        查库是为了让熔断**跨进程重启生效** —— 服务器上服务重启频繁，
        只靠内存计数等于每次重启都要重新试错一轮死源。
        """
        local = self.check(name, now=now)
        if local.should_skip or not self.enabled:
            return local

        stats = await self._load_window_stats(name)
        verdict = self._evaluate(stats)
        if not verdict.should_skip:
            return verdict

        # 持久数据判定要熔断 → 写入本地状态，让后续调用零开销短路
        st = self.get_state(name)
        cooldown = verdict.cooldown
        # 已处于退避中则用指数退避，但受 MAX_COOLDOWN 封顶
        if st.strike > 0:
            cooldown = min(cooldown * (BACKOFF_FACTOR ** st.strike), MAX_COOLDOWN)
        st.open_until = (now if now is not None else time.monotonic()) + cooldown
        st.last_reason = verdict.stats.get("top_reason", "")
        st.strike += 1
        st.last_opened_at = now if now is not None else time.monotonic()
        return verdict

    def _evaluate(self, stats: dict) -> BreakerDecision:
        """纯函数判定，单独抽出便于单测。"""
        if not stats or not stats.get("attempts"):
            # 无样本 ⇒ 新源，放行。这是熔断器最容易被写错的地方：
            # 若把"无数据"当作"全败"，新源会被永久锁死。
            return BreakerDecision(False)

        attempts = int(stats.get("attempts") or 0)
        successes = int(stats.get("successes") or 0)
        counted = int(stats.get("counted") or 0)  # 排除 local 类后的样本数

        if attempts < self.min_samples or counted < self.min_samples:
            return BreakerDecision(False, stats=stats)

        if successes > _SUCCESS_RATE_EXEMPT:
            # 窗口内成功过 ⇒ 源是活的，哪怕失败很多（多为 not_found）
            return BreakerDecision(False, stats=stats)

        top_reason = stats.get("top_reason") or "unknown"
        cooldown = _cooldown_for_reason(top_reason)
        if cooldown is None:
            return BreakerDecision(False, stats=stats)

        return BreakerDecision(
            should_skip=True,
            reason=f"circuit_open:{top_reason}",
            cooldown=cooldown,
            stats=stats,
        )

    async def _load_window_stats(self, name: str) -> dict:
        """从 ``scrape_attempts`` 读该源在窗口内的聚合计数。

        🔴 与 ``recorder.source_health`` 同理：统计与 top_reason 必须在
        **同一条 SQL** 里。拆两条在 SQLite/WAL 下会拿到不同读快照。
        """
        from sqlalchemy import text

        from app.db.database import Database
        from app.scraper.failure_reason import LOCAL_REASONS

        local_list = ",".join(f"'{r}'" for r in LOCAL_REASONS) or "''"

        sql = f"""
            WITH agg AS (
                SELECT source,
                       COUNT(*)                                  AS attempts,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successes,
                       SUM(CASE WHEN reason IN ({local_list})
                                THEN 0 ELSE 1 END)              AS counted
                FROM scrape_attempts
                WHERE source = :source
                  AND created_at >= :since
                GROUP BY source
            ),
            top AS (
                SELECT reason FROM (
                    SELECT reason, ROW_NUMBER() OVER (
                        ORDER BY COUNT(*) DESC
                    ) AS rn
                    FROM scrape_attempts
                    WHERE source = :source
                      AND created_at >= :since
                      AND success = 0
                      AND reason NOT IN ({local_list})
                    GROUP BY reason
                ) WHERE rn = 1
            )
            SELECT a.attempts, a.successes, a.counted, t.reason AS top_reason
            FROM agg a LEFT JOIN top t ON 1=1
        """
        since = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() - self.window_minutes * 60),
        )
        db = Database()
        try:
            async with db.engine.connect() as conn:
                row = (
                    await conn.execute(text(sql), {"source": name, "since": since})
                ).mappings().first()
            if not row:
                return {}
            return dict(row)
        except Exception:
            # 🔴 熔断器绝不能因为查库失败而阻断刮削主流程 ——
            # 观测设施降级为"不熔断"，而不是把刮削一起拖垮。
            return {}

    # -- 反馈 ----------------------------------------------------------

    def record_success(self, name: str) -> None:
        """源成功一次 → 清零退避（含半开闭合）。"""
        st = self.get_state(name)
        st.open_until = 0.0
        st.strike = 0
        st.half_open = False

    def record_failure(self, name: str, reason: str) -> None:
        """源失败一次 → 立即按该原因开一次熔断。

        与"查库批量判定"不同，这里是**即时**的：一个源刚刚明确 DNS 失败，
        队列里剩下的番号不该再一个个去试。冷却取该原因的基准值，
        半开失败时由 strike 计数在下次 ``check_persisted`` 时指数放大。
        """
        if not self.enabled:
            return
        cooldown = _cooldown_for_reason(reason)
        if cooldown is None:
            # local 类失败不是源的锅，不开熔断
            return
        now = time.monotonic()
        st = self.get_state(name)
        base = cooldown * (BACKOFF_FACTOR ** st.strike)
        st.open_until = now + min(base, MAX_COOLDOWN)
        st.last_reason = reason
        st.strike += 1
        st.last_opened_at = now


# ----------------------------------------------------------------------
# 模块级单例
# ----------------------------------------------------------------------

_breaker: Optional[SourceBreaker] = None


def get_breaker() -> SourceBreaker:
    global _breaker
    if _breaker is None:
        _breaker = SourceBreaker()
    return _breaker


def reset_breaker() -> None:
    """重置单例（测试用）。"""
    global _breaker
    _breaker = None
