"""演员名归一化：把「同一人多种写法」收敛到同一个键。

## 为什么需要（实测 2026-10-09）

演员库里同一个人会被拆成多条记录，根因是**各源写法不同**：

    森沢かな            (JavDB 原名，78 部)
    森沢かな（飯岡かなこ） (JavDB 带括号别名，70 部)
    森泽佳奈            (简体 + 把假名转成汉字，52 部)

三条关联影片重叠 0~5 部，但厂牌完全一致（ADN/DASS/MIAB/GVH）⇒ 同一人。
同类还有 美園和花/美园和花、本庄鈴/本庄铃 等 8 组 17 条。

真正的祸首是 `app/db/movie_actor_sync.py::sync_movie_actors`：
它找演员时只做「`name` 精确匹配 + `lower()` 大小写兜底」，
**没有任何简繁 / 括号别名 / 异体字归一化** ⇒ 每刮一次就多造一条记录。
`merge_actor_name_variants()` 也只按 `lower(name)` 分组，管不了简繁差异。

## 三层归一

1. **剥离括号别名**：`森沢かな（飯岡かなこ）` → `森沢かな`（括号内容作为别名另存）
2. **简繁 + 日文新字体 + 全角 + 去标点**：复用 `actor_name_utils.normalize_actor_name`
   （NFKC + zhconv 繁体 + JP_VARIANT_MAP，已覆盖 沢→澤 这类日文新字体）
3. **假名↔汉字**：`かな` ⇄ `佳奈`。这不是标准转换（不是翻译），
   无法用规则推导，因此用**数据驱动**的对照表 `data/actor_kana_map.json`，
   由 `scripts/_scan_actor_split.py` 从库内实证的同名组里挖掘，
   **只收「汉字部分完全一致 + 长度相同」的配对**，宁可漏合不可错合。

## 用法

    from app.utils.actor_name_canon import canon_key, load_kana_map
    key = canon_key("森沢かな（飯岡かなこ）")   # -> 森澤佳奈（命中假名表时）

落盘链路用法见 `app/db/movie_actor_sync.py::sync_movie_actors`。
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

# 括号别名：`森沢かな（飯岡かなこ）` / `Anna Cherry(Soda)`
_PAREN_RE = re.compile(r"[（(]([^）)]*)[）)]")


def strip_paren_alias(name: str) -> tuple[str, list[str]]:
    """剥离括号别名 -> (主名, [别名...])。没有括号时原样返回。"""
    s = (name or "").strip()
    aliases = [m.strip() for m in _PAREN_RE.findall(s) if m.strip()]
    base = _PAREN_RE.sub("", s).strip()
    return (base or s), aliases


# ---------------------------------------------------------------- 假名对照表

_KANA_MAP: Optional[dict[str, str]] = None


def load_kana_map() -> dict[str, str]:
    """载入实证假名对照表（缺省为空表，不影响归一化主流程）。

    由 `scripts/_scan_actor_split.py` 生成。**只应包含有实证支撑的配对。**
    """
    global _KANA_MAP
    if _KANA_MAP is not None:
        return _KANA_MAP
    path = os.environ.get(
        "MDCX_KANA_MAP_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                     "data", "actor_kana_map.json"),
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("kana_to_hanzi") if isinstance(data, dict) else data
        _KANA_MAP = {str(k): str(v) for k, v in (raw or {}).items() if k and v}
    except Exception:
        _KANA_MAP = {}
    return _KANA_MAP


def reload_kana_map() -> None:
    """强制重载（生成新表后可用）。"""
    global _KANA_MAP
    _KANA_MAP = None


# ---------------------------------------------------------------- 主入口


def canon_key(name: str) -> str:
    """演员名归一键。空名返回空串。

    流程：剥离括号别名 -> 简繁/异体字/全角归一 -> 假名转汉字（查实证表）。
    """
    if not name:
        return ""
    base, _ = strip_paren_alias(str(name))

    try:
        from app.utils.actor_name_utils import normalize_actor_name

        key = normalize_actor_name(base)
    except Exception:
        # 兜底：极端情况下别让归一化抛错导致落盘失败
        key = re.sub(r"[^\w一-鿿぀-ヿ]", "", base).lower()

    if not key:
        return ""

    km = load_kana_map()
    if km:
        for k, v in km.items():
            if k in key:
                key = key.replace(k, v)
    return key


def same_actor(a: str, b: str) -> bool:
    """两个名字是否指向同一人（归一键相等）。"""
    ka, kb = canon_key(a), canon_key(b)
    return bool(ka) and ka == kb


if __name__ == "__main__":  # 手工自测
    for n in ("森沢かな", "森沢かな（飯岡かなこ）", "森泽佳奈",
              "美園和花", "美园和花", "本庄鈴", "本庄铃"):
        print("%-24s -> %s" % (n, canon_key(n)))
