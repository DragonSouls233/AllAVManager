"""NFO <runtime> 时长换算 —— 全仓唯一真相源。

🔴 为什么单独成文件：``app/importer/__init__.py`` 会连带 import ``sync.py``
（拉 sqlalchemy、asyncpg 等重依赖），而 ``app/utils/__init__.py`` 只导出 logger。
把纯函数放 utils，扫描器（anime/uncensored/...）与 importer 都能直接引用，
不会因为 import 一个时间解析函数而把整条 DB 依赖链拖进来。

🔴 契约：对外返回值一律是**分钟**（与 ``ScrapeResult.duration``、
Kodi/Jellyfin ``<runtime>`` 语义一致）。写秒会造成 60 倍偏差。

真实 NFO 样本实测形态（G:\\TEST 43 个样本）：
    "3121" / "13" / "223"   → 纯分钟
    "42分鍾" / "42分钟"      → 中文
    "27:17"                 → mm:ss
    "01:52:37"               → hh:mm:ss（FC2 常见）

⚠️ 历史缺陷：旧实现是 ``re.search(r'(\\d+)', s)`` 只取第一个数字段，
于是 "01:52:37" → 1 分钟、"1:30" → 1 分钟。**静默产出错误时长比缺失更糟**
（Kodi 会显示 1 分钟，且下游无法察觉），因此这里必须显式处理各形态。
"""

import re
from typing import Optional

# hh:mm:ss —— 小时数放宽到 3 位（超长片源），分钟/秒各 2 位
_RUNTIME_HMS_RE = re.compile(r"^\s*(\d{1,3})\s*:\s*(\d{1,2})\s*:\s*(\d{1,2})\s*$")
# mm:ss —— 分钟数放宽到 4 位（个别站点直接写总分钟数:秒）
_RUNTIME_MS_RE = re.compile(r"^\s*(\d{1,4})\s*:\s*(\d{1,2})\s*$")
# 中文 "42分鍾" / "42分钟"（鍾 是「钟」的异体字，样本里真实出现过）
_RUNTIME_CN_RE = re.compile(r"(\d{1,5})\s*分\s*[钟鍾]?")
# 纯分钟
_RUNTIME_PLAIN_RE = re.compile(r"^\s*(\d{1,5})\s*$")

# 合理区间：>0 且 <= 100000 分钟（约 69 天）。0 与明显异常值视为无效，
# 避免脏 NFO 把 duration 污染成 0（Kodi 里 0 等价于"未知"）。
_MIN_MINUTES = 1
_MAX_MINUTES = 100000


def parse_runtime_minutes(raw: object) -> Optional[int]:
    """把 NFO ``<runtime>`` 的各种写法统一换算成**分钟**；无法解析返回 ``None``。

    Args:
        raw: 原始文本（``"01:52:37"`` / ``"27:17"`` / ``"3121"`` / ``"42分鍾"``）
            或已是数字类型（Kodev JSON 里可能是 int/float）。

    Returns:
        整数分钟；空值/无法解析/超出合理区间时返回 ``None``（**不是 0**）。
    """
    if raw is None:
        return None

    # 已是数值型（Kodev JSON）：直接当分钟用
    if isinstance(raw, bool):          # bool 是 int 的子类，单独挡掉
        return None
    if isinstance(raw, (int, float)):
        minutes = int(raw)
        return minutes if _MIN_MINUTES <= minutes <= _MAX_MINUTES else None

    s = str(raw).strip()
    if not s:
        return None

    # 源站常把标签名和值挤在一起，xpath 取文本时会带上前导分隔符。
    # 真实样本：FC2 的 ``//span[contains(text(),"動画時間")]/../text()`` 取到 ``": 01:52:37"``，
    # uncensored 的 ``"再生時間"`` 表格取到 ``"：113分"``（全角冒号）。
    # 不剥掉的话正则全部匹配不上 ⇒ 静默返回 None（比返回错值更隐蔽，因为看不出异常）。
    s = s.lstrip(":：﹕∣|").strip()
    if not s:
        return None

    minutes: Optional[int] = None
    m = _RUNTIME_HMS_RE.match(s)
    if m:
        # hh:mm:ss → 小时*60 + 分；秒数 >=30 进位到分（就近取整）
        h, mi, sec = (int(x) for x in m.groups())
        minutes = h * 60 + mi + (1 if sec >= 30 else 0)
    else:
        m = _RUNTIME_MS_RE.match(s)
        if m:
            mi, sec = (int(x) for x in m.groups())
            minutes = mi + (1 if sec >= 30 else 0)
        else:
            m = _RUNTIME_CN_RE.search(s)
            if m:
                minutes = int(m.group(1))
            else:
                m = _RUNTIME_PLAIN_RE.match(s)
                if m:
                    minutes = int(m.group(1))

    if minutes is None or not (_MIN_MINUTES <= minutes <= _MAX_MINUTES):
        return None
    return minutes
