"""刮削质量人工复核审计

把「刮削质量」从靠猜变成可运营：扫描各模块影片，挑出**可疑条目**，
交给人分页核查、忽略、导出 CSV。

判定规则（每个可独立开关）见 :data:`RULES`。
扫描结果在内存缓存，TTL 见 :data:`CACHE_TTL`。忽略名单落 JSON 文件，
避免给 movies 表再加列。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.utils.module_helper import MODULE_MODELS, get_module_model, get_module_session

# 扫描批次：keyset 分页，避免大表 offset 越翻越慢
BATCH = 2000
CACHE_TTL = 600  # 秒

_MODULE_LABELS = {
    "jav": "JAV有码",
    "uncensored": "JAV无码",
    "fc2": "FC2",
    "pornhub": "PORNHUB",
    "anime": "里番",
    "western": "欧美",
    "chinese": "国产",
}

# ------------------------------------------------------------------
# 乱码特征：UTF-8 被当 GBK/cp1252 解码后的典型残留
# ------------------------------------------------------------------
_MOJIBAKE_RE = re.compile(
    r"[\ufffd]"                      # U+FFFD 替换字符
    r"|\u00c3[\u0080-\u00bf]"        # Ã—
    r"|\u00c2[\u00a0-\u00bf]"        # Â + 控制符
    r"|\u00e2\u0080[\u0090-\u00bf]"  # â€‘
    r"|\u00ef\u00bf\u00bd"           # ï¿½
    r"|\u00e6[\u0097-\u009f]"        # æ—¥
    r"|\u00e5[\xa4-\xbf]"            # å¤§
)

# 占位标题：刮到了但等于没刮
_PLACEHOLDER_TITLES = {
    "unknown", "n/a", "na", "none", "null", "-", "--", "unknown title",
    "no title", "untitled", "标题不明", "不明",
}

# 番号规则：只在规则明确的模块上做 bad_code 判定，避免误报淹没列表
_CODE_RULES: dict[str, re.Pattern] = {
    "jav": re.compile(r"^[A-Za-z]{2,8}[-_ ]?\d{2,6}$"),
    "uncensored": re.compile(r"^[A-Za-z]{2,8}[-_ ]?\d{2,6}$"),
    "anime": re.compile(r"^[A-Za-z0-9]{2,12}[-_ ]?\d{1,6}$"),
    "fc2": re.compile(r"^FC2[-_ ]?\d{4,8}$", re.IGNORECASE),
    "pornhub": re.compile(r"^[a-z0-9]{6,20}$", re.IGNORECASE),
}

# 规则注册表：(code, 中文名, 严重度 high/medium/low, 说明)
RULES: list[tuple[str, str, str, str]] = [
    ("missing_cover", "缺封面", "medium", "封面与缩略图均为空"),
    ("missing_title", "缺标题", "high", "标题为空"),
    ("mojibake", "标题乱码", "high", "疑似编码解码错误产生的乱码"),
    ("bad_code", "番号异常", "high", "番号不符合该模块的命名规范"),
    ("no_metadata", "无元数据", "medium", "简介、演员、厂商三项全空"),
    ("placeholder_title", "占位标题", "low", "标题是未知/占位值或与番号相同"),
    ("pending_stuck", "长期未刮削", "low", "有文件但一直处于 pending 状态"),
]

RULE_CODES = [r[0] for r in RULES]
RULE_LABELS = {r[0]: r[1] for r in RULES}
RULE_SEVERITY = {r[0]: r[2] for r in RULES}

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# ------------------------------------------------------------------
# 缓存 / 忽略名单
# ------------------------------------------------------------------
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_LOCK = asyncio.Lock()


def _data_root() -> Path:
    """数据根目录（与模块库同级），忽略名单落在这里"""
    try:
        from app.config.manager import get_config

        db_url = get_config().database.url
        if "///" in db_url:
            return Path(db_url.split("///")[-1]).parent
    except Exception:
        pass
    return Path("data/database")


def _ignore_file() -> Path:
    return _data_root() / "review_ignored.json"


def _module_label(m: str) -> str:
    return _MODULE_LABELS.get(m, m)


def available_modules() -> list[str]:
    base = _data_root()
    out = []
    for m in MODULE_MODELS:
        p = base / f"{m}.db"
        try:
            if p.exists() and p.stat().st_size > 0:
                out.append(m)
        except OSError:
            continue
    return out


# ------------------------------------------------------------------
# 判定
# ------------------------------------------------------------------

def _rule_missing_cover(row: dict) -> bool:
    return not (row.get("cover_url") or row.get("thumb_url"))


def _rule_missing_title(row: dict) -> bool:
    t = (row.get("title") or "").strip()
    return not t


def _rule_mojibake(row: dict) -> bool:
    t = row.get("title") or ""
    if not t:
        return False
    return bool(_MOJIBAKE_RE.search(t))


def _rule_bad_code(row: dict, module: str) -> bool:
    pat = _CODE_RULES.get(module)
    if not pat:
        return False
    code = (row.get("code") or "").strip()
    if not code:
        return True
    return not pat.match(code)


def _rule_no_metadata(row: dict) -> bool:
    return not any(
        (row.get(k) or "").strip() if isinstance(row.get(k), str) else row.get(k)
        for k in ("plot", "actor", "studio")
    )


def _rule_placeholder_title(row: dict) -> bool:
    t = (row.get("title") or "").strip()
    code = (row.get("code") or "").strip()
    if not t:
        return False
    if t.lower() in _PLACEHOLDER_TITLES:
        return True
    return bool(code) and t.lower() == code.lower()


def _rule_pending_stuck(row: dict) -> bool:
    return row.get("status") == "pending" and bool(row.get("file_path"))


async def scan_module(module: str, on_progress=None) -> list[dict]:
    """扫描单个模块，返回问题条目列表"""
    Movie = get_module_model(module, "movie")
    session = await get_module_session(module)

    cols = (
        Movie.id, Movie.code, Movie.title, Movie.cover_url, Movie.thumb_url,
        Movie.actor, Movie.studio, Movie.plot, Movie.status,
        Movie.file_path, Movie.updated_at,
    )
    _FIELDS = ("id", "code", "title", "cover_url", "thumb_url",
               "actor", "studio", "plot", "status", "file_path", "updated_at")

    issues: list[dict] = []
    last_id = 0
    scanned = 0

    while True:
        stmt = (
            select(*cols)
            .where(Movie.id > last_id)
            .order_by(Movie.id)
            .limit(BATCH)
        )
        rows = (await session.execute(stmt)).all()
        if not rows:
            break

        for r in rows:
            row = dict(zip(_FIELDS, r))
            last_id = row["id"]
            scanned += 1

            hits: list[str] = []
            if _rule_missing_cover(row):
                hits.append("missing_cover")
            if _rule_missing_title(row):
                hits.append("missing_title")
            if _rule_mojibake(row):
                hits.append("mojibake")
            if _rule_bad_code(row, module):
                hits.append("bad_code")
            if _rule_no_metadata(row):
                hits.append("no_metadata")
            if _rule_placeholder_title(row):
                hits.append("placeholder_title")
            if _rule_pending_stuck(row):
                hits.append("pending_stuck")

            if hits:
                sev = min((_SEVERITY_ORDER[RULE_SEVERITY[h]] for h in hits))
                issues.append({
                    "module": module,
                    "module_label": _module_label(module),
                    "id": row["id"],
                    "code": row["code"],
                    "title": row["title"],
                    "cover_url": row["cover_url"],
                    "actor": row["actor"],
                    "studio": row["studio"],
                    "status": row["status"],
                    "file_path": row["file_path"],
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                    "types": hits,
                    "type_labels": [RULE_LABELS[h] for h in hits],
                    "severity": ("high", "medium", "low")[sev],
                })

        if on_progress:
            await on_progress(module, scanned, len(issues))

        if len(rows) < BATCH:
            break

    return {"module": module, "label": _module_label(module),
            "scanned": scanned, "issues": issues}


async def scan(modules: list[str] | None = None, force: bool = False) -> dict:
    """扫描并缓存。force=False 时命中未过期缓存直接返回"""
    modules = modules or available_modules()
    now = time.time()
    results = []
    for m in modules:
        cached = _CACHE.get(m)
        if not force and cached and now - cached[0] < CACHE_TTL:
            results.append(cached[1])
            continue
        stat = await scan_module(m)
        async with _CACHE_LOCK:
            _CACHE[m] = (time.time(), stat)
        results.append(stat)
    return {"modules": results}


def get_cached(module: str) -> dict | None:
    cached = _CACHE.get(module)
    if not cached:
        return None
    age = int(time.time() - cached[0])
    stat = cached[1]
    return {**stat, "cached_age": age, "expired": age >= CACHE_TTL}


# ------------------------------------------------------------------
# 忽略名单
# ------------------------------------------------------------------

def load_ignored() -> dict[str, dict]:
    p = _ignore_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ignored(data: dict[str, dict]) -> None:
    p = _ignore_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(module: str, movie_id: int) -> str:
    return f"{module}:{movie_id}"


def add_ignored(module: str, movie_id: int, reason: str = "") -> None:
    data = load_ignored()
    data[_key(module, movie_id)] = {"reason": reason, "at": time.time()}
    save_ignored(data)


def remove_ignored(module: str, movie_id: int) -> None:
    data = load_ignored()
    data.pop(_key(module, movie_id), None)
    save_ignored(data)


def clear_ignored() -> None:
    save_ignored({})


def iv(value: Any) -> str:
    """CSV 注入防护：Excel 会把 = + - @ 开头的单元格当公式执行"""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s
