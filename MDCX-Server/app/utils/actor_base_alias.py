"""演员马甲统一：把「同一人在不同源的别名」收敛到规范名。

## 为什么需要（用户 2026-10-09 提出）

同一个人在库里会被拆成多条记录，光靠简繁归一不够 —— 各源给的**本名/别名**本身就不同：

    森沢かな / 森沢かな（飯岡かなこ） / 森泽佳奈

`actor_name_canon.canon_key` 只能吃掉「简繁 / 异体字 / 括号别名」这类**写法差异**，
吃不掉「本名 vs 化名」这种**身份差异**。后者要靠外部马甲库。

## 马甲来源与实测覆盖（2026-10-09 勘察 `data/database/actor_base.db`）

| 来源 | 条数 | 说明 |
|---|---|---|
| gfriends | 33826 | 绝大多数是「本名 -> 本名」，等于没有映射价值 |
| avleague | 1286 | 女优榜同一人只出现一次，主要是罗马字/别名 |
| **wiki** | **145** | 真正提供「别名 -> 规范名」的源，但量最小 |
| javdb | 101 | JavDB 演员页的其它写法 |
| dmm | 21 | DMM 的罗马字 |

合计 35379 行、可解析到 canonical 的 **35318** 条。
但实测 jav 库 2062 个演员里，只有 **145 个**能被它映射到别的规范名（7%）——
因为库里的名字大多本来就是 gfriends 的写法。

⇒ **结论：马甲库有用但覆盖面有限**，不能当唯一手段；
真正的马甲增量要靠**继续采集 wiki / JavDB 演员页**。
本模块的价值是：把已经采集到的 35318 条用起来，别浪费。

## 用法

    from app.utils.actor_base_alias import resolve_alias
    resolve_alias("飯岡かなこ")   # -> 可能返回该人的规范名；查不到返回 None

**降级策略**：actor_base.db 不存在 / 打不开时一律返回 None，
调用方继续走 `actor_name_canon` 的归一键路径，绝不让归一化成为落盘的阻塞点。
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from typing import Optional

#: alias_key(已归一) -> canonical_name
_ALIAS: dict[str, str] = {}

#: alias_key(已归一) -> canonical_id，用于同人多别名互认
_ALIAS_ID: dict[str, int] = {}

_LOADED = False
_LOCK = threading.Lock()
_TTL = 900.0
_LOADED_AT = 0.0


def _base_db_path() -> str:
    data = os.environ.get("MDCX_DATA_DIR") or os.environ.get("MDCX_DATA_ROOT")
    if not data:
        data = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
        )
    return os.path.join(data, "database", "actor_base.db")


def _canon_key(name: str) -> str:
    try:
        from app.utils.actor_name_canon import canon_key

        return canon_key(name)
    except Exception:
        return (name or "").strip().lower()


def _load() -> bool:
    """加载马甲表。失败返回 False（调用方走降级）。"""
    global _LOADED, _LOADED_AT
    path = _base_db_path()
    if not os.path.exists(path):
        _LOADED = False
        return False
    alias: dict[str, str] = {}
    alias_id: dict[str, int] = {}
    try:
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        # canonical 名字先落内存，避免每条 alias 都回查
        canon = {
            int(r["id"]): r["canonical_name"]
            for r in con.execute("SELECT id, canonical_name FROM av_jav")
        }
        for r in con.execute("SELECT alias_key, canonical_id FROM aliases"):
            cid = r["canonical_id"]
            name = canon.get(cid)
            if not name:
                continue
            k = _canon_key(r["alias_key"])
            if not k:
                continue
            alias.setdefault(k, name)
            alias_id.setdefault(k, int(cid))
        con.close()
    except Exception:
        return False
    _ALIAS.clear()
    _ALIAS.update(alias)
    _ALIAS_ID.clear()
    _ALIAS_ID.update(alias_id)
    _LOADED = True
    _LOADED_AT = time.time()
    return True


def _ensure() -> None:
    if _LOADED and (time.time() - _LOADED_AT) < _TTL:
        return
    with _LOCK:
        if _LOADED and (time.time() - _LOADED_AT) < _TTL:
            return
        _load()


def reload() -> None:
    """强制重载（重新采集马甲后调用）。"""
    with _LOCK:
        _load()


def available() -> bool:
    _ensure()
    return _LOADED


def stats() -> dict:
    _ensure()
    return {
        "loaded": _LOADED,
        "alias_count": len(_ALIAS),
        "db": _base_db_path(),
    }


def resolve_alias(name: str) -> Optional[str]:
    """查马甲表 -> 规范名；查不到/不该替换时返回 None（调用方降级到归一键路径）。

    🔴 **质量闸**（2026-10-09 实测踩坑，必须保留）：
    基础表里有一批演员的 `canonical_name` 本身就是**小写罗马字**
    （`aika` / `julia` / `minamo`），而 `canon_key()` 会把名字小写化
    ⇒ 直接采用会把库里的 `AIKA` 改写成 `aika`、`JULIA` → `julia`，
    **这是把规范名改成劣化形态**。还会把 `Rio（柚木ティナ）` 截成 `rio`，丢信息。
    所以只有「**纯简繁/异体字级别的改写**」才允许替换：

        1. 映射结果与原名只有大小写差 → 不替换（canon_key 已能归一）
        2. 原名是 CJK/假名、映射结果退化成纯 ASCII → 不替换（形态被改坏）
        3. 映射结果明显比原名短（丢掉了括号别名等）→ 不替换
    """
    if not name:
        return None
    _ensure()
    if not _LOADED:
        return None
    orig = str(name).strip()
    hit = (_ALIAS.get(_canon_key(orig)) or "").strip()
    if not hit or hit == orig:
        return None
    # ① 主体（剥掉括号别名后）只与原名差大小写 ⇒ 大小写本来就由 canon_key 归一，
    #    不需要动。也拦掉「RION -> rion（二宮沙羅）」这种只多括号、主体仅大小写差异的。
    hit_body = re.sub(r"[（(][^）)]*[）)]", "", hit).strip()
    if not hit_body or hit_body.lower() == orig.lower():
        return None
    # ② 规范名退化成纯拉丁字母（罗马字），而原名是 CJK/假名 ⇒ 不采用
    if _has_cjk(orig) and _is_ascii_only(hit):
        return None
    # ②' **方向闸**：只允许「简体/新字体 -> 繁体」方向的统一。
    #    基础表里 canonical_name 质量参差，实测出现过
    #    `北條麻妃 -> 北条麻妃`（繁体→简体）、`三上悠亞 -> 三上悠亜`（繁体→日文新字体）
    #    这类**反向劣化**改写，会把库里已经规范的繁体名改回简体。
    #    原名若本身是繁体，一律不替换（那种差异 canon_key 已能归一）。
    if _has_traditional(orig):
        return None
    # ②'' **空格闸**：实测基础表有 canonical_name 凭空多空格的情况
    #    （`角奈保` -> `角 奈保`），会给库里引入新的写法差异 ⇒ 拒绝。
    if (" " in hit) != (" " in orig):
        return None
    # ③ 明显变短（多半丢了括号别名）⇒ 不采用
    if len(hit) < len(orig) * 0.6 and not _is_ascii_only(orig):
        return None
    return hit


def _has_traditional(s: str) -> bool:
    """字符串是否含繁体字（用 zhconv 转成简体后有变化即为含繁体）。"""
    try:
        from app.utils.actor_name_utils import _zhconv_convert

        return _zhconv_convert(s, "zh-hans") != s
    except Exception:
        return False


def _has_cjk(s: str) -> bool:
    return any("぀" <= c <= "ヿ" or "一" <= c <= "鿿"
               or "豈" <= c <= "﫿" for c in (s or ""))


def _is_ascii_only(s: str) -> bool:
    return all(ord(c) < 128 or c.isspace() for c in (s or ""))


def alias_of(name: str) -> Optional[int]:
    """查马甲表 -> canonical_id（用于判断两个写法是否同一人）。"""
    if not name:
        return None
    _ensure()
    if not _LOADED:
        return None
    return _ALIAS_ID.get(_canon_key(name))
