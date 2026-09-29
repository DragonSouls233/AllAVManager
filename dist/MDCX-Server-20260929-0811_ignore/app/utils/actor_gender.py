"""演员性别过滤工具

需求：演员库只保留女演员，男演员一律不入库、不写入 NFO。

判定优先级：
1. 源站明确标记（javdb ``strong.male``）→ 结果对象的 ``male_actors``
2. 持久化男演员名单（模块库 actors 表 gender='male'，或本地 JSON 名单）
3. 女演员名单命中（若某演员已被确认是女性，则强制保留）

设计原则：高精度不追召回 —— 判定不了的一律放行（当女演员），避免误杀。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

# 男演员名单持久化文件（服务器可写目录）
_MALE_LIST_PATH = os.environ.get(
    "MDCX_MALE_ACTORS_PATH",
    str(Path(__file__).resolve().parents[2] / "data" / "male_actors.json"),
)

_cache: Optional[set[str]] = None
_cache_mtime: float = 0.0


def _load() -> set[str]:
    """载入男演员名单（带 mtime 缓存，文件不存在返回空集）"""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(_MALE_LIST_PATH)
    except OSError:
        return _cache or set()
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    try:
        with open(_MALE_LIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        names = data.get("male_actors", []) if isinstance(data, dict) else list(data)
        _cache = {str(n).strip() for n in names if str(n).strip()}
    except Exception:
        _cache = set()
    _cache_mtime = mtime
    return _cache


def add_male_actors(names: Iterable[str]) -> int:
    """把确认的男演员名追加进持久化名单，返回新增数量"""
    existing = _load()
    to_add = {str(n).strip() for n in names if str(n).strip()} - existing
    if not to_add:
        return 0
    try:
        os.makedirs(os.path.dirname(_MALE_LIST_PATH), exist_ok=True)
        merged = sorted(existing | to_add)
        with open(_MALE_LIST_PATH, "w", encoding="utf-8") as f:
            json.dump({"male_actors": merged}, f, ensure_ascii=False, indent=2)
        global _cache, _cache_mtime
        _cache = set(merged)
        _cache_mtime = os.path.getmtime(_MALE_LIST_PATH)
    except Exception:
        return 0
    return len(to_add)


def known_male_actors() -> set[str]:
    """返回已知男演员名单"""
    return set(_load())


def split_by_gender(
    names: Iterable[str],
    male_actors: Optional[Iterable[str]] = None,
) -> tuple[list[str], list[str]]:
    """把演员名列表按性别拆分为 (女演员, 男演员)

    Args:
        names: 待判定演员名
        male_actors: 源站本次明确标记的男演员（最高优先级）
    """
    source_male = {str(n).strip() for n in (male_actors or []) if str(n).strip()}
    known_male = _load()

    female: list[str] = []
    male: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if name in source_male or name in known_male:
            male.append(name)
        else:
            female.append(name)
    return female, male


def filter_female_only(
    names: Iterable[str],
    male_actors: Optional[Iterable[str]] = None,
) -> list[str]:
    """只保留女演员（源站标记 + 已知名单双重剔除）"""
    female, _ = split_by_gender(names, male_actors)
    return female
