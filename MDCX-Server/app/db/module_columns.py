r"""模块专属列落库（唯一真相源，供 workflow / 各落盘路径复用）

## 为什么需要这个文件

`_save_to_db`（`app/scraper/workflow.py`）只写**通用列**（title/release_date/
duration/rating/…）。各模块表还有自己的专属列，例如 pornhub.movies 的
``source_id / source_views / source_score / uploader / categories``。

这些值**只能从 `ScrapeResult.raw_data` 里取**（`ScrapeResult` 本身没有对应字段），
此前有三处各自手写了一遍提取逻辑：

- `app/patcher/strategy.py::_scrape_missing`（补刮路径，走 SQL UPDATE）
- `app/api/routes/pornhub_routes.py`（单曲/批量刮削，走 ORM）  ← 已删除
- 缺：主流水线 `workflow._save_to_db` ⇒ **走扫库批刮的影片专属列永远是 NULL**

本模块把「raw_data → 模块专属列」的映射收口到一处，供 ORM 落盘路径调用。
补刮路径（strategy.py）是拼 SQL，保留它自己的 `_MODULE_COLUMN_MAP`；
⚠️ **两边改键名要同步**，否则会出现「批刮有值、补刮没有」。

## 量纲约定（改前先看）

- `source_views` = **播放量**（`ph_views`），不是评分人数。
- `source_score` = **站点原始评分**（PH 为 0-5 制），顶层 `rating` 才是折算后的 0-10。
- `votes` = 评分人数，PH 表**没有**该列，不要往 `source_downloads` 里塞。
"""

from __future__ import annotations

from typing import Any

from app.crawlers.base import ScrapeResult  # noqa: F401  (仅用于类型说明)

#: {模块名: {DB 列名: (raw_data 键, 转换器)}}
#: 转换器为 None 表示原样写入（会在写入前统一做标量校验）。
_MODULE_COLUMN_SPEC: dict[str, dict[str, tuple[tuple[str, ...], Any]]] = {
    "pornhub": {
        "source_id": (("ph_video_id", "viewkey"), None),
        "source_views": (("ph_views",), None),
        "source_score": (("ph_rating",), None),
        "uploader": (("ph_uploader",), None),
        "categories": (("ph_categories",), "_join_categories"),
    },
}


def _join_categories(value: Any) -> str | None:
    """把 PH 的 categories 结构拍平成逗号分隔字符串。

    真实形态（2026-10-05 实测，``webmasters/video_by_id``）::

        [{"category": "Anal"}, {"category": "Big Dick"}, ...]

    也有源给纯字符串列表，两种都兼容。返回 None 表示无值（不覆盖库中旧值）。
    """
    if not value:
        return None
    names: list[str] = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, dict):
                n = item.get("category") or item.get("name") or item.get("tag_name")
            else:
                n = item
            if n:
                s = str(n).strip()
                if s and s not in names:
                    names.append(s)
    elif isinstance(value, str):
        return value.strip() or None
    return ",".join(names) or None


def _coerce_scalar(value: Any) -> Any:
    """只放行标量；list/dict 一律丢弃（列是 Integer/Float/String）。"""
    if value is None or isinstance(value, (list, tuple, set, dict)):
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return value


def _coerce_number(value: Any) -> Any:
    """source_views / source_score 是数值列，字符串数字也转，转不了就丢弃。"""
    v = _coerce_scalar(value)
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


def collect_module_columns(result: Any, module: str | None) -> dict[str, Any]:
    """从 ScrapeResult 里提取该模块的专属列值。返回 {列名: 值}（已过滤 None）。"""
    if not module:
        return {}
    spec = _MODULE_COLUMN_SPEC.get(module)
    if not spec:
        return {}

    raw = getattr(result, "raw_data", None) or {}
    out: dict[str, Any] = {}
    for col, (keys, conv) in spec.items():
        val: Any = None
        for k in keys:
            if raw.get(k) not in (None, "", [], {}):
                val = raw.get(k)
                break
        if val is None:
            continue
        if conv == "_join_categories":
            val = _join_categories(val)
        else:
            val = _coerce_number(val) if col in ("source_views", "source_score") else _coerce_scalar(val)
        if val is None:
            continue
        out[col] = val
    return out


def apply_module_columns(movie: Any, result: Any, module: str | None) -> list[str]:
    """把模块专属列写进 ORM 影片对象。

    只写**有值的**（None = 源站没说，不该把库里已有的旧值清成 NULL）；
    只写**目标类真实存在的列**（其他模块没有这些列，盲目 setattr 会在 flush
    时抛 ``no such column`` 并回滚整条事务）。

    Returns:
        实际写入的列名列表（便于日志/测试断言）。
    """
    values = collect_module_columns(result, module)
    if not values:
        return []
    written: list[str] = []
    for col, val in values.items():
        if not hasattr(movie, col):
            continue
        setattr(movie, col, val)
        written.append(col)
    return written
