"""Cover-image refill for already-scraped folders that are missing
poster/fanart/thumb images.

直接从 mp-relay 复制，适配 MDCX 配置模块。
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# 导入 MDCX 配置
from app.config.manager import get_config

log = logging.getLogger(__name__)


_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_HTML_HEADERS: dict[str, str] = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
}

_JAVBUS_COOKIES: dict[str, str] = {"existmag": "all"}
_JAVDB_CDN_BASE: str = "https://c0.jdbstatic.com/covers"
_JAVDB_REFERER: str = "https://javdb.com/"

# JAVBus/AVSOX 站点基础 URL（硬编码，极少变化）
_JAVBUS_BASE: str = "https://www.javbus.com"
_AVSOX_BASE: str = "https://www.avsox.click"
_JAVDB_BASE: str = "https://javdb.com"

_IMG_EXTS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif",
})

_POSTER_CROP_LEFT: float = 0.5375
_CROP_MIN_RATIO: float = 1.20
_CROP_MAX_RATIO: float = 1.58

_MIN_IMAGE_BYTES: int = 2000

_IMG_MAGIC: tuple[bytes, ...] = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n",
    b"GIF8",
    b"BM",
)

_REFILL_CONCURRENCY: int = 4
_fetch_semaphore: asyncio.Semaphore = asyncio.Semaphore(_REFILL_CONCURRENCY)

_RE_JAVDBID = re.compile(r"<javdbid>(.*?)</javdbid>", re.S)
_RE_NUM = re.compile(r"<num>(.*?)</num>", re.S)


@dataclass
class RefillResult:
    folder: str
    code: str = ""
    javdbid: str = ""
    source: str = ""
    status: str = "pending"
    reason: str = ""
    files_written: list[str] = field(default_factory=list)


def _get_proxy() -> Optional[str]:
    """从 MDCX 配置中获取代理 URL。"""
    try:
        config = get_config()
        if config.proxy.enabled:
            addr = config.proxy.address or ""
            port = config.proxy.port or 0
            if addr and port:
                return f"http://{addr}:{port}"
    except Exception:
        pass
    return None


def _get_javdb_cookie() -> str:
    """从 MDCX 配置中获取 JavDB Cookie。"""
    try:
        config = get_config()
        return config.crawler.javdb_cookie or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# NFO parsing
# ---------------------------------------------------------------------------

def _read_nfo(folder: Path) -> Optional[str]:
    for f in folder.iterdir():
        if f.suffix.lower() == ".nfo" and f.is_file():
            try:
                return f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning("can't read %s: %s", f, e)
                return None
    return None


def _extract_ids(nfo: str) -> tuple[str, str]:
    jid = ""
    num = ""
    m = _RE_JAVDBID.search(nfo)
    if m:
        jid = m.group(1).strip()
    m = _RE_NUM.search(nfo)
    if m:
        num = m.group(1).strip()
    return jid, num


def _is_valid_image(p: Path) -> bool:
    try:
        if p.stat().st_size < _MIN_IMAGE_BYTES:
            return False
    except OSError:
        return False
    if not _PIL_OK:
        return True
    try:
        with Image.open(p) as im:
            return im.width > 0 and im.height > 0
    except Exception:
        return False


def _has_image(folder: Path) -> bool:
    try:
        return any(
            _is_valid_image(p)
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _IMG_EXTS
        )
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Shared HTTP / HTML helpers
# ---------------------------------------------------------------------------

def _abs_url(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    return urljoin(base.rstrip("/") + "/", href.lstrip("/"))


def _looks_like_image(content: bytes) -> bool:
    if not content or len(content) < 2000:
        return False
    if content[8:12] == b"WEBP":
        return True
    return any(content.startswith(m) for m in _IMG_MAGIC)


async def _guarded_get(client: httpx.AsyncClient, url: str, *,
                       referer: str = "") -> Optional[httpx.Response]:
    headers = {"Referer": referer} if referer else None
    async with _fetch_semaphore:
        try:
            return await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("cover-refill GET %s failed: %s", url, e)
            return None


def _cover_url_from_detail(html: str, base: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    big = soup.select_one("a.bigImage")
    if big:
        href = big.get("href") or ""
        if not href:
            img = big.select_one("img")
            href = img.get("src", "") if img else ""
        if href:
            return _abs_url(base, href)
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get("content"):
        return _abs_url(base, og["content"])
    return ""


def _first_movie_box(html: str, base: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("a.movie-box")
    if box and box.get("href"):
        return _abs_url(base, box["href"])
    return ""


# ---------------------------------------------------------------------------
# Cover sources
# ---------------------------------------------------------------------------

async def _fetch_cover_javbus(client: httpx.AsyncClient, code: str) -> Optional[bytes]:
    base = _JAVBUS_BASE.rstrip("/")
    cover_url = ""

    r = await _guarded_get(client, f"{base}/{code}")
    if r is not None and r.status_code == 200:
        cover_url = _cover_url_from_detail(r.text, base)

    if not cover_url:
        rs = await _guarded_get(client, f"{base}/search/{quote(code)}")
        if rs is not None and rs.status_code == 200:
            detail = _first_movie_box(rs.text, base)
            if detail:
                rd = await _guarded_get(client, detail)
                if rd is not None and rd.status_code == 200:
                    cover_url = _cover_url_from_detail(rd.text, base)

    if not cover_url:
        return None
    ri = await _guarded_get(client, cover_url, referer=f"{base}/")
    if ri is not None and ri.status_code == 200 and _looks_like_image(ri.content):
        return ri.content
    return None


async def _fetch_cover_avsox(client: httpx.AsyncClient, code: str) -> Optional[bytes]:
    base = _AVSOX_BASE.rstrip("/")
    rs = await _guarded_get(client, f"{base}/cn/search/{quote(code)}")
    if rs is None or rs.status_code != 200:
        return None
    detail = _first_movie_box(rs.text, base)
    if not detail:
        return None
    rd = await _guarded_get(client, detail)
    if rd is None or rd.status_code != 200:
        return None
    cover_url = _cover_url_from_detail(rd.text, base)
    if not cover_url:
        return None
    ri = await _guarded_get(client, cover_url, referer=f"{base}/")
    if ri is not None and ri.status_code == 200 and _looks_like_image(ri.content):
        return ri.content
    return None


# ---------------------------------------------------------------------------
# JavDB fetchers (last-resort source; Cloudflare-gated)
# ---------------------------------------------------------------------------

def _javdb_cover_url(javdbid: str) -> str:
    prefix = javdbid[:2].lower()
    return f"{_JAVDB_CDN_BASE}/{prefix}/{javdbid}.jpg"


async def _fetch_cover_bytes(client: httpx.AsyncClient, javdbid: str) -> Optional[bytes]:
    url = _javdb_cover_url(javdbid)
    r = await _guarded_get(client, url, referer=_JAVDB_REFERER)
    if r is None or r.status_code != 200:
        if r is not None:
            log.info("javdb cover %s → HTTP %s", url, r.status_code)
        return None
    if not _looks_like_image(r.content):
        return None
    return r.content


async def _search_javdb_for_id(client: httpx.AsyncClient, code: str) -> Optional[str]:
    cookie = _get_javdb_cookie()
    base = _JAVDB_BASE.rstrip("/")
    search_url = f"{base}/search?q={quote(code)}&f=all"

    headers = {"Referer": _JAVDB_REFERER}
    if cookie:
        headers["Cookie"] = cookie

    async with _fetch_semaphore:
        try:
            r = await client.get(search_url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("javdb search failed for %s: %s", code, e)
            return None
    if r.status_code != 200:
        log.info("javdb search %s → HTTP %s", code, r.status_code)
        return None

    m = re.search(r'/v/([A-Za-z0-9]+)', r.text)
    if not m:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# Per-folder refill
# ---------------------------------------------------------------------------

def _safe_code(folder_name: str, num: str) -> str:
    if num:
        return re.sub(r"[^\w\-]", "_", num)
    first = folder_name.split()[0] if folder_name else "unknown"
    return re.sub(r"[^\w\-]", "_", first) or "cover"


def _make_poster(body: bytes, raw_code: str = "") -> bytes:
    if not _PIL_OK or "VR" in (raw_code or "").upper():
        return body
    try:
        with Image.open(io.BytesIO(body)) as im:
            w, h = im.size
            if not h:
                return body
            ratio = w / h
            if ratio < _CROP_MIN_RATIO or ratio >= _CROP_MAX_RATIO:
                return body
            left = int(w * _POSTER_CROP_LEFT)
            cropped = im.crop((left, 0, w, h)).convert("RGB")
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception as e:
        log.warning("poster crop failed (%s); using full cover", e)
        return body


def _write_covers(folder: Path, code: str, body: bytes, *, dry_run: bool,
                  raw_code: str = "") -> list[str]:
    poster = body if dry_run else _make_poster(body, raw_code)
    name_bytes: list[tuple[str, bytes]] = [
        (f"{code}-poster.jpg", poster),
        (f"{code}-fanart.jpg", body),
        (f"{code}-thumb.jpg", body),
        ("folder.jpg", poster),
    ]
    written: list[str] = []
    for name, data in name_bytes:
        target = folder / name
        if target.exists():
            continue
        if dry_run:
            written.append(name)
            continue
        try:
            target.write_bytes(data)
            written.append(name)
        except OSError as e:
            log.warning("can't write %s: %s", target, e)
    return written


async def refill_one(client: httpx.AsyncClient, folder: Path, *, dry_run: bool) -> RefillResult:
    res = RefillResult(folder=str(folder))

    if _has_image(folder):
        res.status = "skip_has_img"
        return res

    nfo = _read_nfo(folder)
    if not nfo:
        res.status = "error"
        res.reason = "no NFO in folder"
        return res

    javdbid, num = _extract_ids(nfo)
    res.javdbid = javdbid
    res.code = _safe_code(folder.name, num)
    raw_code = (num or "").strip()

    if not raw_code:
        first = folder.name.split()[0] if folder.name else ""
        if first and any(ch.isdigit() for ch in first):
            raw_code = first

    if not raw_code and not javdbid:
        res.status = "skip_no_id"
        res.reason = "no <num>/<javdbid> in NFO and folder name has no code"
        return res

    body: Optional[bytes] = None

    if raw_code:
        body = await _fetch_cover_javbus(client, raw_code)
        if body:
            res.source = "javbus"
        if not body:
            body = await _fetch_cover_avsox(client, raw_code)
            if body:
                res.source = "avsox"

    if not body:
        if not javdbid and raw_code:
            javdbid = await _search_javdb_for_id(client, raw_code) or ""
            if javdbid:
                res.javdbid = javdbid
        if javdbid:
            body = await _fetch_cover_bytes(client, javdbid)
            if body:
                res.source = "javdb"

    if not body:
        res.status = "skip_no_id"
        res.reason = f"no cover on javbus/avsox/javdb for {raw_code or javdbid!r}"
        return res

    res.files_written = _write_covers(folder, res.code, body, dry_run=dry_run, raw_code=raw_code)
    res.status = "dry_run" if dry_run else "refilled"
    return res


# ---------------------------------------------------------------------------
# Library walk
# ---------------------------------------------------------------------------

def _enumerate_movie_folders(root: Path) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for studio in root.iterdir():
        if not studio.is_dir():
            continue
        try:
            children = list(studio.iterdir())
        except OSError:
            continue
        for d in children:
            if not d.is_dir():
                continue
            try:
                files = list(d.iterdir())
            except OSError:
                continue
            if any(f.suffix.lower() == ".nfo" for f in files):
                out.append(d)
    return out


async def refill_root(root: str, *, dry_run: bool = True,
                       limit: Optional[int] = None,
                       proxy: Optional[str] = None) -> dict:
    """Walk ``root`` and refill every cover-missing folder. Returns summary."""
    root_path = Path(root)
    folders = _enumerate_movie_folders(root_path)
    log.info("cover-refill scanning %s: %d movie folders", root, len(folders))

    candidates = [f for f in folders if not _has_image(f)]
    log.info("cover-refill candidates (no images): %d", len(candidates))
    if limit is not None:
        candidates = candidates[:limit]

    effective_proxy = proxy if proxy is not None else _get_proxy()
    client_kw: dict = dict(
        timeout=25.0,
        follow_redirects=True,
        headers=_HTML_HEADERS,
        cookies=_JAVBUS_COOKIES,
    )
    if effective_proxy:
        client_kw["proxy"] = effective_proxy

    async with httpx.AsyncClient(**client_kw) as client:
        results = await asyncio.gather(
            *(refill_one(client, f, dry_run=dry_run) for f in candidates),
            return_exceptions=True,
        )

    summary: dict[str, int] = {}
    by_source: dict[str, int] = {}
    out_results: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            summary["error"] = summary.get("error", 0) + 1
            out_results.append({"folder": "", "status": "error", "reason": str(r)[:200]})
            continue
        summary[r.status] = summary.get(r.status, 0) + 1
        if r.source:
            by_source[r.source] = by_source.get(r.source, 0) + 1
        out_results.append({
            "folder": r.folder,
            "code": r.code,
            "javdbid": r.javdbid,
            "source": r.source,
            "status": r.status,
            "reason": r.reason,
            "files_written": r.files_written,
        })

    return {
        "root": root,
        "dry_run": dry_run,
        "proxy_used": bool(effective_proxy),
        "scanned_folders": len(folders),
        "missing_image_candidates": len(candidates),
        "summary": summary,
        "by_source": by_source,
        "results": out_results,
    }
