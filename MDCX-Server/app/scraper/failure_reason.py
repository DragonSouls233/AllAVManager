"""刮削失败原因分级

## 为什么需要（2026-10-04）

`ScraperEngine._scrape_with_crawler` 此前把**所有**异常统一 `return None`，
只留一行 `爬虫 X 刮削 Y 出错: <ExcName>: <msg>`。上层拿到的只有"没结果"，
无法区分这 4 类本质不同的失败：

| 类别 | 含义 | 正确处置 |
|---|---|---|
| `network` / `timeout` | 网络抖动、代理不稳 | **换源继续**，本源后续可重试 |
| `blocked` | 被 WAF / CF 拦截、IP 被 ban | 换源继续，并降低本源权重 |
| `not_found` / `no_resource` | 站点确认无此资源 | 换源；**不应重试同一 URL** |
| `age_gate` | 需年龄验证 / 登录 | 需专门处理，不算源失效 |

不区分的实际代价：
- 网络抖动被当成"该片不存在" → 写进永久跳过名单，再也不重试
- 源被 WAF 拦截时无法降权，反复撞同一堵墙
- 统计里只看到"失败 N 次"，定位不到是上游问题还是本地代码问题

设计参考 amane `net/errors.py:35-61`（16 个 FailureReason）+ `:135-149`
的拦截检测字符串启发式。本模块只做**纯函数分类**，不依赖网络。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FailureReason(str, Enum):
    """刮削失败原因（字符串枚举，可直接落库/落日志）"""

    NONE = "none"                # 未失败
    UNKNOWN = "unknown"          # 无法归类

    # --- 永久性：再试一次也是同样结果 ---
    NOT_FOUND = "not_found"      # HTTP 404 / 页面不存在
    NO_RESOURCE = "no_resource"  # 站点明确回复"无此资源"
    GONE = "gone"                # HTTP 410
    UNSUPPORTED = "unsupported"  # 源不支持该番号类型

    # --- 拦截类：换源有效，本源需降权 ---
    BLOCKED = "blocked"          # 403 / WAF / CF 挑战 / IP ban
    AGE_GATE = "age_gate"        # 年龄验证 / 需登录
    CAPTCHA = "captcha"          # 验证码
    RATE_LIMITED = "rate_limited"  # 429 / 限流

    # --- 瞬时类：应重试 ---
    TIMEOUT = "timeout"          # 超时
    NETWORK = "network"          # 连接/DNS/TLS 层错误
    SERVER_ERROR = "server_error"  # 5xx

    # --- 本地问题 ---
    PARSE_ERROR = "parse_error"  # 页面结构变化导致解析失败
    CLIENT_ERROR = "client_error"  # 其他 4xx


#: 永久性失败 —— 不应再对同一资源重试，应换源 / 记入跳过名单
PERMANENT_REASONS: frozenset[str] = frozenset(
    {
        FailureReason.NOT_FOUND.value,
        FailureReason.NO_RESOURCE.value,
        FailureReason.GONE.value,
        FailureReason.UNSUPPORTED.value,
    }
)

#: 拦截类 —— 换源有效，但本源应降权
BLOCKING_REASONS: frozenset[str] = frozenset(
    {
        FailureReason.BLOCKED.value,
        FailureReason.AGE_GATE.value,
        FailureReason.CAPTCHA.value,
        FailureReason.RATE_LIMITED.value,
    }
)

#: 瞬时类 —— 同一本源重试通常会成功
TRANSIENT_REASONS: frozenset[str] = frozenset(
    {
        FailureReason.TIMEOUT.value,
        FailureReason.NETWORK.value,
        FailureReason.SERVER_ERROR.value,
    }
)

#: 本地代码问题 —— 源可能没坏，是我们的解析器过期了
LOCAL_REASONS: frozenset[str] = frozenset(
    {FailureReason.PARSE_ERROR.value, FailureReason.CLIENT_ERROR.value}
)


@dataclass
class FailureInfo:
    """一次失败的完整描述"""

    reason: FailureReason = FailureReason.UNKNOWN
    source: Optional[str] = None
    number: Optional[str] = None
    message: str = ""
    exception_type: Optional[str] = None
    #: 命中的规则说明（调试用：为什么判成这个原因）
    matched_rule: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def is_permanent(self) -> bool:
        return self.reason.value in PERMANENT_REASONS

    @property
    def is_transient(self) -> bool:
        return self.reason.value in TRANSIENT_REASONS

    @property
    def is_blocking(self) -> bool:
        return self.reason.value in BLOCKING_REASONS

    @property
    def is_local(self) -> bool:
        """是否为本地解析器问题（源可能仍可用，不该降权）"""
        return self.reason.value in LOCAL_REASONS

    @property
    def should_retry_same_source(self) -> bool:
        """是否值得对同一源重试。永久失败与拦截中的 captcha 不值得。"""
        return self.reason.value in TRANSIENT_REASONS

    @property
    def should_demote_source(self) -> bool:
        """是否应降低该源权重。拦截类与永久 404 说明源对该资源无效。"""
        return self.is_blocking or self.is_permanent

    def to_dict(self) -> dict:
        return {
            "reason": self.reason.value,
            "source": self.source,
            "number": self.number,
            "message": self.message[:500],
            "exception_type": self.exception_type,
            "matched_rule": self.matched_rule,
            "is_permanent": self.is_permanent,
            "is_transient": self.is_transient,
            "is_blocking": self.is_blocking,
            "is_local": self.is_local,
            "should_retry_same_source": self.should_retry_same_source,
            "should_demote_source": self.should_demote_source,
            **({"extra": self.extra} if self.extra else {}),
        }


# --------------------------------------------------------------------------
# 规则表：(编译后的正则, FailureReason, 规则名)
# 顺序敏感：先匹配到的胜出 ⇒ 具体的规则必须排在通用的 HTTP 状态码规则之前。
# --------------------------------------------------------------------------
_RULES: list[tuple[re.Pattern, FailureReason, str]] = [
    # --- 站点明确说"没有这个资源"（含假成功：某些源返回"非常抱歉"却 HTTP 200）---
    (re.compile(r"非常抱歉|找不到您要的|没有找到|无此(作品|资源|影片)"), FailureReason.NO_RESOURCE, "site_no_resource"),
    (re.compile(r"\bno\s+results?\b|no\s+match(?:es)?\s+found", re.I), FailureReason.NO_RESOURCE, "site_no_resource_en"),

    # --- 年龄验证 / 登录墙 ---
    (re.compile(r"age\s*(?:verif|gate|check)|are\s+you\s+(?:over|18)|18\+\s*(?:only|verification)|confirm your age", re.I), FailureReason.AGE_GATE, "age_gate"),
    (re.compile(r"(?:adult|成人)内容?验证|需要登录|请先登录|login required|sign in to", re.I), FailureReason.AGE_GATE, "login_wall"),

    # --- 验证码 ---
    (re.compile(r"captcha|验证码|are you a robot|recaptcha|hcaptcha", re.I), FailureReason.CAPTCHA, "captcha"),

    # --- 限流 ---
    (re.compile(r"\b429\b|too many requests|rate\s*limit|请求过于频繁|访问过于频繁", re.I), FailureReason.RATE_LIMITED, "rate_limited"),

    # --- WAF / CF 拦截 ---
    (re.compile(r"cloudflare|cloudflare ray id|cf-ray|just a moment|attention required", re.I), FailureReason.BLOCKED, "cloudflare"),
    (re.compile(r"\b403\b|forbidden|access denied|blocked by|ip has been banned|your ip", re.I), FailureReason.BLOCKED, "forbidden_403"),
    (re.compile(r"\b451\b|unavailable for legal reasons", re.I), FailureReason.BLOCKED, "legal_451"),
    (re.compile(r"\b503\b|service unavailable|maintenance mode|正在维护", re.I), FailureReason.SERVER_ERROR, "unavailable_503"),

    # --- 永久性：不存在 ---
    (re.compile(r"\b404\b|not found|page not found|页面不存在|找不到页面", re.I), FailureReason.NOT_FOUND, "not_found_404"),
    (re.compile(r"\b410\b|\bgone\b|已下架|已删除", re.I), FailureReason.GONE, "gone_410"),

    # --- 瞬时：网络 ---
    (re.compile(r"timed?\s*out|timeout|超时", re.I), FailureReason.TIMEOUT, "timeout"),
    (re.compile(r"connection\s+(?:reset|refused|aborted|error)|could not resolve|getaddrinfo|name or service not known|dns|ssl|tls|certificate|proxy error", re.I), FailureReason.NETWORK, "network"),
    (re.compile(r"\b5\d\d\b|internal server error|bad gateway|gateway time-?out", re.I), FailureReason.SERVER_ERROR, "server_5xx"),

    # --- 本地：解析器过期 ---
    (re.compile(r"expecting\s+(?:value|element)|unterminated|no such element|list index out of range|keyerror|attributeerror|typeerror|\.get\(.+\)\s*failed", re.I), FailureReason.PARSE_ERROR, "parse_error"),

    # --- 兜底 4xx ---
    (re.compile(r"\b4\d\d\b|bad request", re.I), FailureReason.CLIENT_ERROR, "client_4xx"),
]

_COMPILED: list[tuple[re.Pattern, FailureReason, str]] = [
    (pat, reason, name) for pat, reason, name in _RULES
]


def classify_text(text: Optional[str]) -> tuple[FailureReason, Optional[str]]:
    """按错误文本分类，返回 (原因, 命中规则名)。

    先用「状态码独立出现」的宽松匹配，再逐条规则。
    """
    if not text:
        return FailureReason.UNKNOWN, None
    for pat, reason, name in _COMPILED:
        if pat.search(text):
            return reason, name
    return FailureReason.UNKNOWN, None


#: 异常类型名 → 原因（优先于文本规则，因为异常类型更明确）
_EXC_RULES: list[tuple[str, FailureReason]] = [
    ("asyncio.TimeoutError", FailureReason.TIMEOUT),
    ("TimeoutError", FailureReason.TIMEOUT),
    ("ReadTimeout", FailureReason.TIMEOUT),
    ("ConnectTimeout", FailureReason.TIMEOUT),
    ("ConnectionResetError", FailureReason.NETWORK),
    ("ConnectionRefusedError", FailureReason.NETWORK),
    ("ConnectionAbortedError", FailureReason.NETWORK),
    ("socket.gaierror", FailureReason.NETWORK),
    ("ClientConnectorError", FailureReason.NETWORK),
    ("ClientSSLError", FailureReason.NETWORK),
    ("ServerTimeoutError", FailureReason.SERVER_ERROR),
    ("JSONDecodeError", FailureReason.PARSE_ERROR),
    ("KeyError", FailureReason.PARSE_ERROR),
    ("IndexError", FailureReason.PARSE_ERROR),
    ("AttributeError", FailureReason.PARSE_ERROR),
    ("TypeError", FailureReason.PARSE_ERROR),
    ("ValueError", FailureReason.PARSE_ERROR),
]


def classify_exception(exc: BaseException) -> tuple[FailureReason, Optional[str]]:
    """按异常对象分类：先看异常类型链，再看文本。"""
    cur: Optional[BaseException] = exc
    seen = 0
    while cur is not None and seen < 5:
        seen += 1
        full = f"{type(cur).__module__}.{type(cur).__name__}"
        for token, reason in _EXC_RULES:
            if token in full:
                return reason, f"exc:{token}"
        # requests / curl_cffi 的状态码异常
        code = getattr(cur, "response", None)
        status = getattr(code, "status_code", None) if code is not None else None
        if status is None:
            status = getattr(cur, "status", None)
        if isinstance(status, int):
            return _reason_from_status(status), f"status:{status}"
        cur = cur.__cause__ or cur.__context__
    reason, rule = classify_text(str(exc))
    return reason, rule


def _reason_from_status(status: int) -> FailureReason:
    if status in (404,):
        return FailureReason.NOT_FOUND
    if status in (410,):
        return FailureReason.GONE
    if status in (403, 451):
        return FailureReason.BLOCKED
    if status in (429,):
        return FailureReason.RATE_LIMITED
    if status in (401, 407):
        return FailureReason.AGE_GATE
    if 500 <= status < 600:
        return FailureReason.SERVER_ERROR
    if 400 <= status < 500:
        return FailureReason.CLIENT_ERROR
    return FailureReason.UNKNOWN


def classify_scrape_error(
    error: Any = None,
    *,
    source: Optional[str] = None,
    number: Optional[str] = None,
) -> FailureInfo:
    """把任意失败输入（异常 / 字符串 / None）归一化成 :class:`FailureInfo`。

    ``error`` 为 ``None`` 表示"没有异常但也没结果"——无法判断原因，
    归为 ``UNKNOWN`` 且**不判永久失败**（宁可重试也不误伤）。
    """
    if error is None:
        return FailureInfo(
            reason=FailureReason.UNKNOWN,
            source=source,
            number=number,
            message="无异常但无结果",
            matched_rule="none",
        )

    if isinstance(error, FailureInfo):
        return error

    if isinstance(error, BaseException):
        reason, rule = classify_exception(error)
        return FailureInfo(
            reason=reason,
            source=source,
            number=number,
            message=str(error),
            exception_type=type(error).__name__,
            matched_rule=rule,
        )

    text = str(error)
    reason, rule = classify_text(text)
    return FailureInfo(
        reason=reason,
        source=source,
        number=number,
        message=text,
        matched_rule=rule,
    )


def is_permanent_failure(error_or_info: Any) -> bool:
    """:attr:`FailureInfo.is_permanent` 的函数式入口。"""
    return classify_scrape_error(error_or_info).is_permanent


def should_retry_same_source(error_or_info: Any) -> bool:
    return classify_scrape_error(error_or_info).should_retry_same_source


def should_demote_source(error_or_info: Any) -> bool:
    return classify_scrape_error(error_or_info).should_demote_source


class FailureAggregator:
    """按 (源, 原因) 聚合失败计数，用于任务结束后的健康度报告。

    之前只有"失败 N 次"一个数字，定位不到是哪个源、在什么原因上失败。
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._samples: dict[tuple[str, str], str] = {}
        self.total = 0

    def record(self, info: FailureInfo) -> None:
        key = (info.source or "?", info.reason.value)
        self._counts[key] = self._counts.get(key, 0) + 1
        self.total += 1
        self._samples.setdefault(key, info.message[:200])

    def record_any(self, error: Any, *, source: Optional[str] = None,
                   number: Optional[str] = None) -> FailureInfo:
        info = classify_scrape_error(error, source=source, number=number)
        self.record(info)
        return info

    def as_dict(self) -> dict:
        by_source: dict[str, dict] = {}
        for (src, reason), n in self._counts.items():
            by_source.setdefault(src, {})[reason] = n
        return {
            "total": self.total,
            "by_source": by_source,
            "samples": {
                f"{s}|{r}": m for (s, r), m in self._samples.items()
            },
        }

    def summary(self) -> str:
        """一行摘要，供日志直接打印。"""
        if not self._counts:
            return "无失败"
        parts = [
            f"{s}:{r}={n}" for (s, r), n in
            sorted(self._counts.items(), key=lambda kv: -kv[1])
        ]
        return f"总计 {self.total} 次 | " + ", ".join(parts)

    def reset(self) -> None:
        self._counts.clear()
        self._samples.clear()
        self.total = 0
