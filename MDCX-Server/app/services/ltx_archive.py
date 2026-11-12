# -*- coding: utf-8 -*-
"""LTX 线上资源库本地镜像（SQLite + 封面/头像文件 + 按演员归档）。

目录：<安装根>/ltx_archive（与 data/ 平级的独立新文件夹）
  - ltx.db                     : 作品(ltx_items) + 演员头像(ltx_avatars)
  - covers/<演员>/<CODE>.jpg   : 封面（按演员分文件夹）
  - avatars/<演员>.jpg          : 演员头像
  - by_actor/<演员>.json/.txt   : 每个演员的 番号+标题+下载链接

要点：
  * 按 code UPSERT（增量，不整包重写）；
  * primary_actor = actors[0]，用于"一个作品归一个演员"（对齐线上库的演员分类）；
  * 服务端计算 本地已拥有/缺失，前端只拉需要的；
  * 封面/头像后台限并发下载，可断点续（跳过已存在）。
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import sqlite3
import threading
from pathlib import Path

# 2026-11-06：只读查询统一走语句级超时（timeout=10 只是锁等待，管不住慢 SQL）。
from app.utils.sqlite_ro import connect_ro, fetch_all

logger = logging.getLogger(__name__)

_dl_lock = threading.Lock()
_downloading = False

_CODE_RE = re.compile(r"[^A-Z0-9\-_.]")
_NAME_RE = re.compile(r'[\\/:*?"<>|]')


def _safe_code(v: str) -> str:
    return _CODE_RE.sub("_", str(v or "").upper())


def _safe_name(v: str) -> str:
    s = _NAME_RE.sub("_", str(v or "").strip())
    return s or "_"


def archive_dir() -> Path:
    from app.config.manager import DATA_DIR

    d = Path(DATA_DIR).parent / "ltx_archive"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ============================================================
# LTX 站点验证凭证（ltx_pass）管理 —— 单一真源
# ------------------------------------------------------------
# 2026-11-12：源站对 /api/* 加了 Cloudflare Turnstile gate，验证通过后
# POST /api/verify 下发 HttpOnly 的 ltx_pass（值内嵌 13 位毫秒时间戳=到期时间，
# 实测约 7 天）。**实测站点在后续请求里不会 Set-Cookie 续签**，所以到期只能
# 重新从浏览器导出一次。能自动化的部分是：
#   * 每次同步自动读取注入，保存后立即生效（热读文件）、无需重启；
#   * 页头显示到期日/剩余天数，剩余 ≤3 天预警，过期时同步失败原因直说；
#   * 用户在 LTX 补全页自助粘贴更新，不必回控制台找运维。
# ============================================================
_LTX_COOKIE_FILE = "_ltx_cookie.txt"
_CF_CLEARANCE_FILE = "_cf_clearance.txt"  # 旧版兼容：通用 CF challenge 凭证
_LTX_PASS_TS_RE = re.compile(r"\.(\d{13})\.")


def credential_path() -> Path:
    return archive_dir() / _LTX_COOKIE_FILE


def _clean_cookie(raw: str) -> str:
    """清洗从 DevTools 直接复制的 Cookie（可能带 ``Cookie:`` 前缀、引号、换行）。"""
    s = re.sub(r"^\s*cookie\s*:\s*", "", str(raw or "").strip(), flags=re.I)
    return " ".join(s.splitlines()).strip().strip('"').strip()


def _wrap_cookie(v: str, legacy: bool = False) -> str:
    """完整串原样返回；单值按来源包装成 ltx_pass= / cf_clearance=。"""
    return v if "=" in v else (("cf_clearance=" if legacy else "ltx_pass=") + v)


def credential_value() -> tuple[str | None, str]:
    """返回 ``(可直接放进 Cookie 头的串, 生效来源)``。

    顺序与旧版 ``jav_routes._ltx_sync_cookie`` 一致：环境变量优先、其次文件。
    环境变量是容器化部署留的口子；页面自助保存写的是 ``_ltx_cookie.txt``。
    """
    import os

    env = os.environ.get("MDCX_LTX_COOKIE")
    if env and env.strip():
        return _wrap_cookie(_clean_cookie(env), False), "env:MDCX_LTX_COOKIE"
    legacy_env = os.environ.get("MDCX_LTX_CF_CLEARANCE")
    if legacy_env and legacy_env.strip():
        return _wrap_cookie(_clean_cookie(legacy_env), True), "env:MDCX_LTX_CF_CLEARANCE"
    for fname, legacy in ((_LTX_COOKIE_FILE, False), (_CF_CLEARANCE_FILE, True)):
        p = archive_dir() / fname
        try:
            if p.exists():
                v = _clean_cookie(p.read_text(encoding="utf-8"))
                if v:
                    return _wrap_cookie(v, legacy), "file:" + fname
        except Exception:
            logger.debug("[ltx] 读凭证文件失败 %s", p, exc_info=True)
    return None, "none"


def credential_info() -> dict:
    """凭证状态（**绝不返回凭证值**，供前端展示与预警）。"""
    value, source = credential_value()
    info = {
        "configured": bool(value),
        "source": source,
        "cookie_names": [],
        "expires_at": "",
        "expires_in_days": None,
        "expired": False,
        "needs_renew": False,   # 过期或剩余 ≤3 天
        "updated_at": "",
        "env_override": source.startswith("env:"),
    }
    if not value:
        info["needs_renew"] = True
        return info
    info["cookie_names"] = [
        p.split("=", 1)[0].strip() for p in value.split(";") if p.strip()
    ]
    m = re.search(r"(?:^|;)\s*ltx_pass=([^;]+)", value)
    if m:
        ts = _LTX_PASS_TS_RE.search(m.group(1).strip())
        if ts:
            try:
                exp = datetime.datetime.fromtimestamp(int(ts.group(1)) / 1000)
                days = (exp - datetime.datetime.now()).total_seconds() / 86400.0
                info["expires_at"] = exp.strftime("%Y-%m-%d %H:%M:%S")
                info["expires_in_days"] = round(days, 1)
                info["expired"] = days <= 0
                # 每日 08:10 有定时同步，留 3 天缓冲，避免周末/出差期间失效
                info["needs_renew"] = days <= 3
            except (ValueError, OverflowError, OSError):
                pass
    try:
        p = credential_path()
        if p.exists():
            info["updated_at"] = datetime.datetime.fromtimestamp(
                p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    if "ltx_pass" not in info["cookie_names"]:
        # 只有 cf_clearance / ltx_c 的旧凭证对该站的 gate 无效
        info["needs_renew"] = True
    return info


def save_credential(raw: str) -> dict:
    """保存凭证（原子写，避免每日定时任务读到半截文件），返回 ``credential_info()``。"""
    v = _clean_cookie(raw)
    if not v:
        raise ValueError("Cookie 内容为空")
    names = [p.split("=", 1)[0].strip() for p in v.split(";") if p.strip()]
    if "ltx_pass" not in names:
        if "=" not in v:
            v = "ltx_pass=" + v  # 只贴了 ltx_pass 的值
        else:
            raise ValueError(
                "Cookie 里没有 ltx_pass；请在浏览器 Network 面板复制 "
                "/api/items 请求的完整 Cookie 头"
            )
    p = credential_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(v, encoding="utf-8")
    tmp.replace(p)
    logger.info("[ltx] 验证凭证已更新（页面自助保存，立即生效，无需重启）")
    return credential_info()


def db_path() -> Path:
    return archive_dir() / "ltx.db"


def covers_root() -> Path:
    d = archive_dir() / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def avatars_dir() -> Path:
    d = archive_dir() / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def by_actor_dir() -> Path:
    d = archive_dir() / "by_actor"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path()), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    c = _conn()
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ltx_items(
                code TEXT PRIMARY KEY,
                code_norm TEXT,
                title TEXT,
                actors_json TEXT,
                primary_actor TEXT,
                cover_url TEXT,
                cover_file TEXT,
                cover_source TEXT,
                links_json TEXT,
                release_date TEXT,
                maker TEXT,
                score REAL,
                remote_updated_at TEXT,
                fetched_at TEXT,
                subtitle_url TEXT
            )
            """
        )
        cols = [r[1] for r in c.execute("PRAGMA table_info(ltx_items)").fetchall()]
        if "primary_actor" not in cols:
            c.execute("ALTER TABLE ltx_items ADD COLUMN primary_actor TEXT")
        if "cover_source" not in cols:
            c.execute("ALTER TABLE ltx_items ADD COLUMN cover_source TEXT")
        # 2026-11-12：线上 LTX 站新增「中文SRT字幕下载」，/api/items 每条带 subtitle 直链。
        if "subtitle_url" not in cols:
            c.execute("ALTER TABLE ltx_items ADD COLUMN subtitle_url TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ltx_code_norm ON ltx_items(code_norm)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ltx_primary ON ltx_items(primary_actor)")
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ltx_avatars(
                name TEXT PRIMARY KEY,
                avatar_url TEXT,
                avatar_file TEXT
            )
            """
        )
        c.commit()
    finally:
        c.close()


def upsert_items(items: list[dict], remote_updated_at=None) -> int:
    init_db()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    c = _conn()
    n = 0
    try:
        for it in items:
            code = str(it.get("code") or "").strip()
            if not code:
                continue
            norm = code.upper()
            actors = it.get("actors") or []
            primary = actors[0] if actors else "(未知演员)"
            c.execute(
                """INSERT INTO ltx_items(code, code_norm, title, actors_json, primary_actor, cover_url,
                        links_json, release_date, maker, score, remote_updated_at, fetched_at,
                        subtitle_url)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET
                        code_norm=excluded.code_norm, title=excluded.title,
                        actors_json=excluded.actors_json, primary_actor=excluded.primary_actor,
                        cover_url=excluded.cover_url, links_json=excluded.links_json,
                        release_date=excluded.release_date, maker=excluded.maker, score=excluded.score,
                        remote_updated_at=excluded.remote_updated_at, fetched_at=excluded.fetched_at,
                        subtitle_url=excluded.subtitle_url""",
                (
                    code, norm, it.get("title_zh") or it.get("title") or "",
                    json.dumps(actors, ensure_ascii=False), primary,
                    it.get("cover") or "", json.dumps(it.get("links") or [], ensure_ascii=False),
                    it.get("date"), it.get("maker"), it.get("score"), remote_updated_at, now,
                    str(it.get("subtitle") or "").strip(),
                ),
            )
            n += 1
        c.commit()
    finally:
        c.close()
    return n


def save_avatars(avatars: dict) -> int:
    """保存 演员名→头像URL 映射（已下载的 avatar_file 保留）。"""
    init_db()
    n = 0
    if not isinstance(avatars, dict):
        return 0
    c = _conn()
    try:
        for name, url in avatars.items():
            if not name:
                continue
            if isinstance(url, dict):
                url = url.get("url") or url.get("src") or ""
            c.execute(
                """INSERT INTO ltx_avatars(name, avatar_url) VALUES(?,?)
                   ON CONFLICT(name) DO UPDATE SET avatar_url=excluded.avatar_url""",
                (str(name), str(url or "")),
            )
            n += 1
        c.commit()
    finally:
        c.close()
    return n


def local_jav_ltx_codes() -> set[str]:
    from app.config.manager import DATA_DIR

    p = Path(DATA_DIR) / "database" / "jav.db"
    if not p.exists():
        return set()
    try:
        c = connect_ro(p)
        try:
            rows = fetch_all(
                c,
                "SELECT code FROM movies WHERE COALESCE(is_hd_uncensored,0)=1",
                label="ltx:local_jav_ltx_codes",
            )
            return {str(r[0]).upper() for r in rows if r[0]}
        finally:
            c.close()
    except Exception:
        logger.warning("[ltx] 读取本地 jav LTX 番号失败", exc_info=True)
        return set()


def _jav_db_path() -> Path | None:
    from app.config.manager import DATA_DIR

    p = Path(DATA_DIR) / "database" / "jav.db"
    return p if p.exists() else None


def local_jav_cover_map(codes: set[str]) -> dict[str, Path]:
    """番号 → 本地 JAV 封面文件（复用，省下载）。只查传入的 codes。"""
    p = _jav_db_path()
    if not p or not codes:
        return {}
    from app.config.manager import DATA_DIR

    out: dict[str, Path] = {}
    try:
        c = connect_ro(p)
        try:
            rows = fetch_all(
                c,
                "SELECT code, cover_url FROM movies WHERE cover_url IS NOT NULL AND cover_url<>''",
                label="ltx:local_jav_cover_map",
            )
        finally:
            c.close()
    except Exception:
        return {}
    movies_root = Path(DATA_DIR) / "movies" / "jav"
    for code, cover in rows:
        if not code:
            continue
        norm = str(code).upper()
        if norm not in codes or norm in out:
            continue
        cp = None
        try:
            cp = Path(str(cover))
        except Exception:
            cp = None
        if cp and cp.is_file() and cp.stat().st_size > 0:
            out[norm] = cp
            continue
        d = movies_root / str(code)
        for fn in ("poster.jpg", "poster.png", "cover.jpg", "thumb.jpg"):
            f = d / fn
            if f.is_file() and f.stat().st_size > 0:
                out[norm] = f
                break
    return out


def local_jav_id_map(codes: set[str]) -> dict[str, int]:
    """番号 → 本地 JAV 影片 id（仅 is_hd_uncensored=1），供页面回链本地详情。"""
    p = _jav_db_path()
    if not p or not codes:
        return {}
    out: dict[str, int] = {}
    try:
        c = connect_ro(p)
        try:
            rows = fetch_all(
                c,
                "SELECT id, code FROM movies WHERE COALESCE(is_hd_uncensored,0)=1",
                label="ltx:local_jav_id_map",
            )
        finally:
            c.close()
    except Exception:
        return {}
    for mid, code in rows:
        if code and str(code).upper() in codes:
            out[str(code).upper()] = mid
    return out


_STATUS_FILE = "_sync_status.json"


def _status_path() -> Path:
    return archive_dir() / _STATUS_FILE


def read_sync_status() -> dict:
    """读「最近一次同步尝试」的状态文件（不存在/损坏 → {}）。"""
    p = _status_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def record_sync_result(
    ok: bool,
    http: int | None = None,
    count: int | None = None,
    items: int | None = None,
    attempts: int = 1,
    error: str = "",
) -> dict:
    """把「最近一次同步尝试」写盘，成功和失败都写。

    为什么要单独一个文件：同步失败时 ``ltx_items`` 一行都不会变，
    ``snapshot_meta()`` 的 ``saved_at``（= MAX(fetched_at)）就停在旧日期，
    前端看起来像「从来没自动同步过」——2026-11-09/10 的 429 限流就是这样
    （11-08 之后两天没更新，但每天 04:00 的任务其实都跑了）。
    有了这个文件才能区分「没跑」和「跑了但失败（429）」。
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")
    prev = read_sync_status()
    st = {
        "at": now,
        "ok": bool(ok),
        "http": http,
        "count": count,
        "items": items,
        "attempts": attempts,
        "error": (error or "")[:300],
        # 上次「成功」的时间要保留，否则失败时无从判断到底多久没成功过
        "last_ok_at": now if ok else (prev.get("last_ok_at") or ""),
    }
    try:
        _status_path().write_text(
            json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        logger.debug("[ltx] 写同步状态失败", exc_info=True)
    return st


def _stale_hours(since: str) -> float | None:
    """距上次成功多少小时（解析失败返回 None）。"""
    if not since:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(since))
    except Exception:
        return None
    return round((datetime.datetime.now() - t).total_seconds() / 3600.0, 1)


def snapshot_meta() -> dict:
    init_db()
    c = _conn()
    try:
        row = c.execute("SELECT COUNT(*), MAX(fetched_at) FROM ltx_items").fetchone()
    finally:
        c.close()
    meta = {"count": row[0] or 0, "saved_at": row[1] or ""}
    st = read_sync_status()
    if st:
        meta.update(
            {
                "last_try_at": st.get("at") or "",
                "last_ok_at": st.get("last_ok_at") or "",
                "last_try_ok": bool(st.get("ok")),
                "last_http": st.get("http"),
                "last_error": st.get("error") or "",
                "stale_hours": _stale_hours(st.get("last_ok_at") or ""),
            }
        )
    # 2026-11-12：凭证状态随快照一起下发，页头可直接显示「X 天后过期」并预警，
    # 免得每日定时任务失败时用户还得回控制台查原因。
    meta["credential"] = credential_info()
    return meta


def _cover_view(norm: str, cover_file: str | None, remote: str) -> str:
    if cover_file:
        return "/api/v1/jav/ltx-cover/%s" % _safe_code(norm)
    return remote or ""


def get_cover_path(code: str) -> Path | None:
    c = _conn()
    try:
        row = c.execute(
            "SELECT cover_file FROM ltx_items WHERE code_norm=?", (str(code).upper(),)
        ).fetchone()
    finally:
        c.close()
    if not row or not row[0]:
        return None
    p = archive_dir() / row[0]
    return p if p.exists() and p.stat().st_size > 0 else None


def get_avatar_path(name: str) -> Path | None:
    c = _conn()
    try:
        row = c.execute(
            "SELECT avatar_file FROM ltx_avatars WHERE name=?", (name,)
        ).fetchone()
    finally:
        c.close()
    if not row or not row[0]:
        return None
    p = archive_dir() / row[0]
    return p if p.exists() and p.stat().st_size > 0 else None


def list_actors() -> dict:
    """演员列表（头像 + 线上数 + 本地有 + 缺失），按线上数降序。"""
    init_db()
    local = local_jav_ltx_codes()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT primary_actor, code_norm FROM ltx_items"
        ).fetchall()
        avatars = {
            r[0]: (r[1], r[2])
            for r in c.execute(
                "SELECT name, avatar_file, avatar_url FROM ltx_avatars"
            ).fetchall()
        }
    finally:
        c.close()

    agg: dict[str, dict] = {}
    for actor, norm in rows:
        actor = actor or "(未知演员)"
        a = agg.setdefault(actor, {"count": 0, "have": 0, "missing": 0})
        a["count"] += 1
        if norm in local:
            a["have"] += 1
        else:
            a["missing"] += 1

    actors = []
    new_cnt = 0
    for name, a in agg.items():
        if a["have"] == 0:
            new_cnt += 1
        file, url = avatars.get(name, (None, None))
        if file:
            avatar = "/api/v1/jav/ltx-avatar?name=%s" % _q(name)
        else:
            avatar = url or ""
        actors.append(
            {
                "name": name,
                "count": a["count"],
                "have": a["have"],
                "missing": a["missing"],
                "is_new": a["have"] == 0,
                "avatar": avatar,
            }
        )
    actors.sort(key=lambda x: (-x["count"], x["name"]))
    meta = snapshot_meta()
    return {
        "snapshot": meta,
        "online_total": len(rows),
        "local_total": len(local),
        "actor_total": len(agg),
        "new_actor_total": new_cnt,
        "actors": actors,
    }


def _q(s: str) -> str:
    from urllib.parse import quote

    return quote(str(s), safe="")


def actor_items(actor: str) -> dict:
    """某演员名下所有作品（含本地是否已拥有）。"""
    init_db()
    local = local_jav_ltx_codes()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT code, code_norm, title, cover_url, cover_file, links_json, release_date, maker, score "
            "FROM ltx_items WHERE primary_actor=? ORDER BY release_date DESC",
            (actor,),
        ).fetchall()
    finally:
        c.close()
    items = []
    norms = set()
    for code, norm, title, cover_url, cover_file, lj, rdate, maker, score in rows:
        norm = norm or str(code).upper()
        norms.add(norm)
        try:
            links = json.loads(lj or "[]")
        except Exception:
            links = []
        items.append(
            {
                "code": code,
                "title": title or "",
                "cover": _cover_view(norm, cover_file, cover_url),
                "links": links,
                "owned": norm in local,
                "date": rdate or "",
                "maker": maker or "",
                "score": score,
                "_norm": norm,
            }
        )
    idmap = local_jav_id_map(norms)
    for it in items:
        it["jav_id"] = idmap.get(it.pop("_norm"))
    return {"actor": actor, "items": items}


def query_gap() -> dict:
    """仅缺失（按 primary_actor 分组），供"补全"使用。"""
    init_db()
    local = local_jav_ltx_codes()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT code, code_norm, title, primary_actor, cover_url, cover_file, links_json "
            "FROM ltx_items"
        ).fetchall()
    finally:
        c.close()
    by_actor: dict[str, dict] = {}
    total = 0
    missing_with_links = 0
    for code, norm, title, actor, cover_url, cover_file, lj in rows:
        total += 1
        norm = norm or str(code).upper()
        actor = actor or "(未知演员)"
        try:
            links = json.loads(lj or "[]")
        except Exception:
            links = []
        g = by_actor.setdefault(actor, {"online": 0, "have": 0, "missing": []})
        g["online"] += 1
        if norm in local:
            g["have"] += 1
        elif links:
            missing_with_links += 1
            g["missing"].append(
                {
                    "code": code,
                    "title": title or "",
                    "cover": _cover_view(norm, cover_file, cover_url),
                    "links": links,
                }
            )
    groups = []
    new_cnt = 0
    for actor, g in by_actor.items():
        is_new = g["have"] == 0
        if is_new:
            new_cnt += 1
        groups.append(
            {
                "actor": actor,
                "online": g["online"],
                "have": g["have"],
                "missing_total": g["online"] - g["have"],
                "items": g["missing"],
                "is_new": is_new,
            }
        )
    groups.sort(key=lambda x: (0 if x["is_new"] else 1, -len(x["items"]), -x["missing_total"]))
    return {
        "snapshot": snapshot_meta(),
        "online_total": total,
        "local_total": len(local),
        "actor_total": len(by_actor),
        "new_actor_total": new_cnt,
        "missing_with_links": missing_with_links,
        "groups": groups,
    }


# ---------------- 后台下载：封面(按演员) + 头像 + 每演员数据文件 ----------------
def start_download(max_workers: int = 8) -> bool:
    global _downloading
    with _dl_lock:
        if _downloading:
            return False
        _downloading = True
    t = threading.Thread(target=_download_worker, args=(max_workers,), daemon=True)
    t.start()
    return True


# 兼容旧名
def start_cover_download(max_workers: int = 8) -> bool:
    return start_download(max_workers)


def _download_worker(max_workers: int) -> None:
    global _downloading
    try:
        from concurrent.futures import ThreadPoolExecutor

        import requests

        from app.services.proxy_manager import get_effective_proxy_url

        init_db()
        proxy = get_effective_proxy_url(url="https://c0.jdbstatic.com/")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        tl = threading.local()

        def sess():
            s = getattr(tl, "s", None)
            if s is None:
                s = requests.Session()
                s.trust_env = False
                tl.s = s
            return s

        def fetch_bytes(url):
            r = sess().get(
                url, timeout=25, verify=False, proxies=proxies,
                headers={"Referer": "https://javdb.com/", "User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
                return r.content
            return None

        # --- 封面（按演员文件夹，索引 0 优先）---
        c = _conn()
        try:
            crow = c.execute(
                "SELECT code_norm, primary_actor, cover_url, cover_file FROM ltx_items WHERE cover_url<>''"
            ).fetchall()
        finally:
            c.close()

        import shutil

        # 复用本地 JAV 封面（有番号+封面就不下载）
        local_map = local_jav_cover_map({str(r[0]).upper() for r in crow})

        def dl_cover(row):
            norm, actor, url, cover_file = row
            rel = "covers/%s/%s.jpg" % (_safe_name(actor), _safe_code(norm))
            target = archive_dir() / rel
            if target.exists() and target.stat().st_size > 0:
                return (norm, rel, "jav" if norm in local_map else None)
            target.parent.mkdir(parents=True, exist_ok=True)
            # 1) 优先复制本地 JAV 封面（不下载）
            src = local_map.get(norm)
            if src is not None:
                try:
                    shutil.copyfile(src, target)
                    return (norm, rel, "jav")
                except Exception:
                    pass
            # 2) 旧扁平文件迁移
            old = archive_dir() / "covers" / ("%s.jpg" % _safe_code(norm))
            if old.exists() and old.stat().st_size > 0:
                try:
                    old.replace(target)
                    return (norm, rel, "remote")
                except Exception:
                    pass
            # 3) 网络下载
            try:
                b = fetch_bytes(url)
                if b:
                    target.write_bytes(b)
                    return (norm, rel, "remote")
            except Exception:
                pass
            return (norm, None, None)

        done = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for i, (norm, rel, src) in enumerate(ex.map(dl_cover, crow)):
                if rel:
                    done.append((rel, src, norm))
                if (i + 1) % 200 == 0:
                    logger.info("[ltx] 封面 %d/%d", i + 1, len(crow))
                    _commit_cover(done)
                    done = []
        _commit_cover(done)

        # --- 头像 ---
        c = _conn()
        try:
            arow = c.execute(
                "SELECT name, avatar_url FROM ltx_avatars WHERE avatar_url<>'' AND (avatar_file IS NULL OR avatar_file='')"
            ).fetchall()
        finally:
            c.close()

        def dl_avatar(row):
            name, url = row
            rel = "avatars/%s.jpg" % _safe_name(name)
            target = archive_dir() / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size > 0:
                return (name, rel)
            try:
                b = fetch_bytes(url)
                if b:
                    target.write_bytes(b)
                    return (name, rel)
            except Exception:
                pass
            return (name, None)

        adone = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for name, rel in ex.map(dl_avatar, arow):
                if rel:
                    adone.append((rel, name))
        if adone:
            c = _conn()
            try:
                c.executemany("UPDATE ltx_avatars SET avatar_file=? WHERE name=?", adone)
                c.commit()
            finally:
                c.close()
        logger.info("[ltx] 头像下载完成 %d/%d", len(adone), len(arow))

        _write_by_actor()
        logger.info("[ltx] 镜像下载任务完成")
    except Exception:
        logger.warning("[ltx] 镜像下载失败", exc_info=True)
    finally:
        with _dl_lock:
            _downloading = False


def _commit_cover(pairs):
    if not pairs:
        return
    c = _conn()
    try:
        c.executemany(
            "UPDATE ltx_items SET cover_file=?, cover_source=COALESCE(?, cover_source) "
            "WHERE code_norm=?",
            pairs,
        )
        c.commit()
    finally:
        c.close()


def _write_by_actor():
    """每个演员一份 by_actor/<演员>.json 与 .txt（番号 + 标题 + 下载链接）。"""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT primary_actor, code, title, links_json FROM ltx_items"
        ).fetchall()
    finally:
        c.close()
    groups: dict[str, list] = {}
    for actor, code, title, lj in rows:
        actor = actor or "(未知演员)"
        try:
            links = json.loads(lj or "[]")
        except Exception:
            links = []
        groups.setdefault(actor, []).append({"code": code, "title": title or "", "links": links})
    d = by_actor_dir()
    for actor, items in groups.items():
        safe = _safe_name(actor)
        obj = {"actor": actor, "count": len(items), "items": items}
        try:
            (d / ("%s.json" % safe)).write_text(
                json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            lines = ["# %s (%d)" % (actor, len(items)), ""]
            for it in items:
                lines.append("%s\t%s" % (it["code"], (it["links"] or [""])[0]))
            (d / ("%s.txt" % safe)).write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            logger.debug("[ltx] 写 by_actor 失败 %s", actor, exc_info=True)
    logger.info("[ltx] by_actor 数据文件已生成: %d 个演员", len(groups))
