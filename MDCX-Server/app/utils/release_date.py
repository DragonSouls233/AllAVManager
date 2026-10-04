"""发行日期解析 —— `ScrapeResult.release_date` 的唯一真相源。

契约：`release_date` 是 **`datetime.date`**，不是 str、不是空串。
爬虫把 str 塞进去会一路穿过 crawler → strategy → NFO → DB 不报错，
直到 Kodi/Jellyfin 按 date 解析时才失败（或静默显示错误日期）。
"""

import re
from datetime import date, datetime, timezone
from typing import Optional

# 支持的日期形态（按优先级）：
#   2024-01-31 / 2024/01/31 / 2024.01.31
#   2024年1月31日
#   31.01.2024（欧洲写法，先排除 4 位开头的 YYYY-MM-DD）
#   20240131（紧凑 8 位）
_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"),
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"),
    re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})"),
    re.compile(r"\b(\d{4})(\d{2})(\d{2})\b"),
    # 英文月份（PH 的 <span class="videoUploaded">Jan 31, 2024</span>）
    re.compile(
        r"(?i)\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"
    ),
)

# 英文月份 → 月份序号
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# 合理年份区间：站点不会给 1970 年前或 2100 年后的发行日期
_MIN_YEAR = 1940
_MAX_YEAR = 2100


def parse_release_date(raw) -> Optional[date]:
    """把任意来源的日期文本解析为 `datetime.date`，失败返 None。

    🔴 不要返回 str 或 "" —— `ScrapeResult.release_date` 契约是 `Optional[date]`。
    旧代码 `result.release_date = date_els[0].strip() if date_els else ""`
    会把 `"2024-01-31"`（str）与 `""`（空串）都塞进去，
    下游 `if result.release_date:` 判空虽然过得了，但 `.year` 属性访问会炸。

    解析失败一律返 None（不是空串）—— 空串在 `if not x` 语境下等价，
    但 `isinstance` 判定和日志展示上会误导排查。
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, date):
        return raw          # 已经是 date（datetime 是 date 子类，一并通过）
    text = str(raw).strip()
    if not text:
        return None

    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        groups = m.groups()
        # 英文月份：('Jan', '31', '2024')
        if isinstance(groups[0], str) and groups[0][:3].lower() in _MONTHS:
            month = _MONTHS[groups[0][:3].lower()]
            day, year = int(groups[1]), int(groups[2])
            if not (_MIN_YEAR <= year <= _MAX_YEAR):
                continue
            try:
                return date(year, month, day)
            except ValueError:
                continue
        a, b, c = (int(g) for g in groups)
        # `2024-01-31` 类：a=年
        if a >= 1000:
            year, month, day = a, b, c
        else:
            # `31.01.2024` 类：c=年；也兼容 `2024/1` 这类 b 是月份、a 是日的
            year, month, day = c, b, a
        if not (_MIN_YEAR <= year <= _MAX_YEAR):
            continue
        try:
            return date(year, month, day)
        except ValueError:
            # 形如 2024-02-31（不存在的日期）继续试下一个 pattern
            continue
    return None


def parse_ph_publish_date(raw) -> Optional[date]:
    """解析 Pornhub 的 `publish_date` 字段。

    ⚠️ PH 这个字段的格式**在两种形态间摇摆过**，且当前无网络无法实测确认：
      ① unix 时间戳字符串：`"1700000000"`（GraphQL `video` 类型常见）
      ② 紧凑日期：`"20240131"` / 带分隔的 `"2024-01-31"`
    ⇒ 这里两种都收，解析不出来一律返 None（不猜、不填今天）。

    真实样本一旦拿到，请回填到本函数的 docstring 并补一条断言。
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, date):
        return raw

    text = str(raw).strip()
    if not text:
        return None

    # 🔴 顺序要紧：先试「紧凑日期」，再判 unix。
    #    13 位纯数字有两个候选含义：`2024013100000`（YYYYMMDDHHMMSS 风格）
    #    和 `1700000000000`（毫秒时间戳）。若先按时间戳判，会把
    #    2024013100000 解成 2034-02-20（**差 10 年的静默错误**），实测踩过。
    #    判据：前 4 位落在 [1940, 2100] 且第 5-6 位是合法月份 ⇒ 按日期解。
    if text.isdigit() and len(text) in (8, 10, 12, 13, 14):
        head_year = int(text[:4]) if len(text) >= 4 else 0
        head_month = int(text[4:6]) if len(text) >= 6 else 0
        looks_like_compact_date = (
            _MIN_YEAR <= head_year <= _MAX_YEAR and 1 <= head_month <= 12
        )
        if looks_like_compact_date:
            return parse_release_date(text[:8] if len(text) >= 8 else text)

    # unix 时间戳：10 位（秒）/ 13 位（毫秒）
    if text.isdigit() and len(text) in (10, 13):
        try:
            seconds = int(text) // 1000 if len(text) == 13 else int(text)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            return None

    # 带分隔日期
    return parse_release_date(text)
