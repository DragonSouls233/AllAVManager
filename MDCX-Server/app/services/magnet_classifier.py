"""磁力链接四分类（subtitle / hacked_subtitle / hacked_no_subtitle / no_subtitle）。

来源：移植 JAVDB_AutoSpider 的 `parsing/magnet_categorize.py`（纯 Python 实现，
无 Rust 依赖，可安全照抄）。

分类规则（与 AutoSpider 完全一致）：
- subtitle          : 有中文字幕（cnsub）且名字不含 '.无码破解'
- hacked_subtitle   : 名字含 -UC / -CU / -C.无码破解 / -U-C / -C-U（破解 + 字幕）
- hacked_no_subtitle: 名字含 -U 或 .无码破解（破解、无字幕；排除已归入 hacked_subtitle 的）
- no_subtitle       : 无字幕且非破解；其中 4K 优先

每类选最佳（按 时间戳 + 大小 降序），并附 size / 文件数 / 分辨率。

输入磁力对象需含属性：name, hash（或 link）, size（字节或 MB）, cnsub, hd,
created_at（可选，用于时间戳排序）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["MagnetBucket", "classify_magnets", "infer_resolution", "parse_size"]

# 破解内容命名模式（与 AutoSpider 完全一致）
_HACKED_SUBTITLE_PATTERNS = ("-UC", "-CU", "-C.无码破解", "-U-C", "-C-U")
_HACKED_PATTERNS_ALL = ("-UC", "-CU", "-C.无码破解", "-U-C", "-C-U", "-U", ".无码破解")


def parse_size(size) -> int:
    """把大小解析为字节数（兼容 '1.5GB'/'800MB'/'6210'MB 等）。"""
    if size is None:
        return 0
    if isinstance(size, (int, float)):
        # JavDB App API 的 size 以 MB 为单位
        return int(size * 1024 * 1024)
    s = str(size).strip().upper().replace(",", "")
    try:
        for suffix, mult in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
            if suffix in s:
                return int(float(s.replace(suffix, "").strip()) * mult)
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def infer_resolution(name: str, tags=None) -> Optional[int]:
    """从磁力名/标签推断分辨率：720/1080/2560/3840/7680。"""
    tag_text = " ".join(tags or [])
    if "8K" in tag_text:
        return 7680
    if "4K" in tag_text:
        return 3840
    if "2K" in tag_text:
        return 2560
    if name:
        low = name.lower()
        if "8k" in low:
            return 7680
        if "4k" in low:
            return 3840
        if "2k" in low:
            return 2560
        if "1080p" in low or "1080" in low:
            return 1080
        if "720p" in low or "720" in low:
            return 720
    return None


def _sort_key(m: dict) -> tuple:
    return (m.get("_ts", ""), m.get("_size", 0))


def _to_bucket_dict(m: Any) -> dict:
    """把磁力对象转成分类用的 dict（name/cnsub/hd/tags/size/created_at）。"""
    name = getattr(m, "name", "") or ""
    if hasattr(m, "cnsub"):  # JavDBAppMagnet
        tags = []
        if m.cnsub:
            tags.append("字幕")
        if m.hd:
            tags.append("高清")
        size = m.size  # 字节（JavDBAppMagnet.size 以 MB 计）
        created_at = m.created_at or ""
    else:  # MagnetInfo（link/name/hash）
        tags = []
        if name and ("字幕" in name or "subtitle" in name.lower()):
            tags.append("字幕")
        size = getattr(m, "file_size", "") or 0
        created_at = ""
    return {
        "name": name,
        "tags": tags,
        "size": size,
        "_ts": created_at,
        "_size": parse_size(size),
        "obj": m,
    }


@dataclass
class MagnetBucket:
    """四分类结果。每项为最佳磁力（None 表示该分类无候选）。"""
    subtitle: Optional[Any] = None
    hacked_subtitle: Optional[Any] = None
    hacked_no_subtitle: Optional[Any] = None
    no_subtitle: Optional[Any] = None
    # 元信息
    size_subtitle: Optional[int] = None
    size_hacked_subtitle: Optional[int] = None
    size_hacked_no_subtitle: Optional[int] = None
    size_no_subtitle: Optional[int] = None
    resolution_subtitle: Optional[int] = None
    resolution_hacked_subtitle: Optional[int] = None
    resolution_hacked_no_subtitle: Optional[int] = None
    resolution_no_subtitle: Optional[int] = None

    def best(self) -> Optional[Any]:
        """返回最优先分类的磁力（hacked_subtitle > hacked_no_subtitle > subtitle > no_subtitle）。"""
        for cat in ("hacked_subtitle", "hacked_no_subtitle", "subtitle", "no_subtitle"):
            v = getattr(self, cat)
            if v is not None:
                return v
        return None

    def all_picks(self) -> dict:
        return {
            "subtitle": self.subtitle,
            "hacked_subtitle": self.hacked_subtitle,
            "hacked_no_subtitle": self.hacked_no_subtitle,
            "no_subtitle": self.no_subtitle,
        }


def _bucket_magnets(buckets: list[dict]) -> dict[str, list[dict]]:
    subtitle = [
        m for m in buckets
        if any(t in m["tags"] for t in ("字幕", "Subtitle"))
        and ".无码破解" not in m["name"]
    ]
    subtitle.sort(key=_sort_key, reverse=True)

    hacked_subtitle, hacked_no_subtitle = [], []
    for m in buckets:
        name = m["name"]
        if any(p in name for p in _HACKED_SUBTITLE_PATTERNS):
            hacked_subtitle.append(m)
        elif "-U" in name or ".无码破解" in name:
            hacked_no_subtitle.append(m)
    hacked_subtitle.sort(key=_sort_key, reverse=True)
    hacked_no_subtitle.sort(key=_sort_key, reverse=True)

    k4, normal = [], []
    for m in buckets:
        name = m["name"]
        is_subtitle = any(t in m["tags"] for t in ("字幕", "Subtitle")) and ".无码破解" not in name
        is_hacked = any(p in name for p in _HACKED_PATTERNS_ALL)
        if not is_subtitle and not is_hacked:
            (k4 if "4k" in name.lower() else normal).append(m)
    k4.sort(key=_sort_key, reverse=True)
    normal.sort(key=_sort_key, reverse=True)

    return {
        "subtitle": subtitle,
        "hacked_subtitle": hacked_subtitle,
        "hacked_no_subtitle": hacked_no_subtitle,
        "no_subtitle": k4 + normal,
    }


def classify_magnets(magnets: list) -> MagnetBucket:
    """对磁力列表做四分类，返回每类最佳。"""
    buckets = [_to_bucket_dict(m) for m in magnets]
    grouped = _bucket_magnets(buckets)

    result = MagnetBucket()
    for cat in ("subtitle", "hacked_subtitle", "hacked_no_subtitle", "no_subtitle"):
        lst = grouped[cat]
        if lst:
            best = lst[0]
            setattr(result, cat, best["obj"])
            setattr(result, f"size_{cat}", best["_size"])
            setattr(result, f"resolution_{cat}", infer_resolution(best["name"], best["tags"]))
    return result


if __name__ == "__main__":
    from app.services.javdb_app_client import JavDBAppMagnet, _parse_magnet

    # 用真实 JavDB 磁力字段构造样例
    samples = [
        {"name": "SDDE-611-C.无码破解.mp4", "hash": "a" * 40, "size": 1500, "cnsub": False, "hd": True, "created_at": "2021/01/01"},
        {"name": "SDDE-611-UC.mp4", "hash": "b" * 40, "size": 2500, "cnsub": True, "hd": True, "created_at": "2021/02/01"},
        {"name": "SDDE-611 4K.mp4", "hash": "c" * 40, "size": 4000, "cnsub": False, "hd": True, "created_at": "2021/03/01"},
        {"name": "SDDE-611 字幕版.mp4", "hash": "d" * 40, "size": 1800, "cnsub": True, "hd": False, "created_at": "2021/04/01"},
    ]
    magnets = [_parse_magnet(s) for s in samples]
    r = classify_magnets(magnets)
    print("subtitle          ->", r.subtitle.name if r.subtitle else None)
    print("hacked_subtitle   ->", r.hacked_subtitle.name if r.hacked_subtitle else None)
    print("hacked_no_subtitle->", r.hacked_no_subtitle.name if r.hacked_no_subtitle else None)
    print("no_subtitle       ->", r.no_subtitle.name if r.no_subtitle else None)
    print("best              ->", r.best().name if r.best() else None)
    assert r.hacked_subtitle.name == "SDDE-611-UC.mp4"
    assert r.no_subtitle.name == "SDDE-611 4K.mp4"  # 4K 优先
    print("classify OK")
