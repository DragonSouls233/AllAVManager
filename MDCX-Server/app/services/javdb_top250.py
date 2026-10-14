"""JavDB App TOP250 抓取 + 本地 jav 库对照（需登录 JWT）。

数据来源：JavDB App 匿名 API 通道 jdforrepam.com 的 ``/api/v1/movies/top`` 端点。
- 网站 ``/rankings/top`` 与匿名 App API 均无 TOP250，只有**登录态 App** 才有
  （实测：网站路径重定向 /login，匿名 App API 返回 JWTVerificationError）。
- 流程：
    1. ``POST /api/v1/sessions``（带 jdsignature 签名 + form username/password）→ 取 JWT
    2. ``GET /api/v1/movies/top?type=video_type&type_value={zone}&page=N&limit=50``
       （带 ``Authorization: Bearer <token>`` + jdsignature）→ 翻页取到 250
    3. 解析 ranking/number/title/cover_url/score/release_date
    4. 对照本地 ``jav.db`` 的 ``movies.code`` → 标记 in_library
- 签名方案与 javdb_app_client 完全一致（复用 ``make_signature``）。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional
from urllib.parse import quote

import httpx

from app.services.javdb_app_client import make_signature
from app.services.proxy_manager import get_effective_proxy_url

log = logging.getLogger(__name__)

# 与 javdb_app_client 同源的 App 通道与版本常量（jdforrepam.com 镜像）
_BASE_URL = "https://jdforrepam.com"
_APP_VERSION = "1.9.28"
_APP_VERSION_NUMBER = "10928"
_USER_AGENT = "Dart/3.4 (dart:io)"

# 分区掩码（与 javdb-cli model.Zones 一致）
ZONES = {"censored": 0, "uncensored": 1, "western": 2, "fc2": 3}

# 封面代理端点（/jav/top250/cover）的**域名白名单**。
# 🔴 该端点会按调用方传入的 URL 发起服务端请求 ⇒ 必须白名单，否则等于给
#    登录用户提供一个任意 URL 抓取器（SSRF，可打内网 / 云元数据 169.254.169.254）。
#    2026-10-14 实测 TOP250 全部 250 条封面都来自 tp.spfcas.com，故只放行它；
#    将来若 JavDB 换图床，把新域名加进来即可（不要用通配符）。
PROXY_ALLOWED_COVER_HOSTS = frozenset({"tp.spfcas.com"})

# 进程内 token 缓存（登录成功后写入；GET 端点 token 解析顺序：query > config > cache）
_token_cache: dict = {"token": None, "ts": 0.0}

# 榜单结果缓存（避免每次刷新都打 javdb；TOP250 变化慢）
_CACHE: dict = {"items": None, "zone": None, "ts": 0.0}
_CACHE_TTL = 12 * 3600


def _public_params() -> dict:
    return {
        "app_channel": "official",
        "app_version": _APP_VERSION,
        "app_version_number": _APP_VERSION_NUMBER,
        "platform": "android",
        "system_version": "13",
        "device_model": "Pixel 6",
        "device_name": "Pixel",
        "device_uuid": str(uuid.uuid4()),
    }


def _headers(ts: int, token: Optional[str] = None) -> dict:
    h = {
        "Accept": "application/json",
        "accept-language": "en",
        "User-Agent": _USER_AGENT,
        "jdsignature": make_signature(ts),
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _read_config_creds() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """从配置读取 JavDB App 凭据：返回 (token, username, password)。"""
    try:
        from app.config.manager import get_config

        cfg = get_config()
        crawler = getattr(cfg, "crawler", None)
        if crawler is None:
            return None, None, None
        tok = getattr(crawler, "javdb_app_token", None) or None
        usr = getattr(crawler, "javdb_app_username", None) or None
        pwd = getattr(crawler, "javdb_app_password", None) or None
        return tok, usr, pwd
    except Exception as e:  # noqa: BLE001
        log.debug("读取 javdb App 凭据失败: %s", e)
        return None, None, None


async def login(username: str, password: str, proxy: Optional[str] = None) -> str:
    """登录 JavDB App，返回 JWT（同时写入进程内缓存）。

    端点 POST /api/v1/sessions，form 含公共参数 + username/password，header 带 jdsignature。
    """
    if not username or not password:
        raise RuntimeError("需要 JavDB App 的用户名和密码")
    proxy = proxy or get_effective_proxy_url()
    ts = int(time.time())
    form = _public_params()
    form["username"] = username
    form["password"] = password
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=30, follow_redirects=True) as c:
            r = await c.post(
                f"{_BASE_URL}/api/v1/sessions",
                data=form,
                headers=_headers(ts),
            )
            if r.status_code >= 400:
                raise RuntimeError(f"登录 HTTP {r.status_code}: {r.text[:200]}")
            env = r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"登录请求失败: {e}")
    if not env.get("success"):
        raise RuntimeError(f"登录失败: {env.get('action')} {env.get('message')}")
    data = env.get("data") or {}
    token = data.get("token") or data.get("access_token")
    if not token:
        raise RuntimeError("登录响应缺少 token")
    _token_cache["token"] = token
    _token_cache["ts"] = time.time()
    return token


def _parse_movie(m: dict) -> Optional[dict]:
    """宽松解析单部影片条目 → 统一字段。

    实测（2026-10-14 登录态抓取 250 条）：TOP250 接口**不返回 score/评分**字段，
    但会返回 duration(秒)、magnets_count、has_cnsub(中字幕)、has_preview_video 等。
    评分改由前端在缺失时不显示（v-if="score != null"），此处只做透传不臆造。
    """
    if not isinstance(m, dict):
        return None
    code = (m.get("number") or "").strip()
    title = (m.get("title") or m.get("origin_title") or "").strip()
    cover = m.get("cover_url") or m.get("thumb_url") or ""
    try:
        ranking = int(m.get("ranking") or 0)
    except (TypeError, ValueError):
        ranking = 0
    try:
        score = float(m.get("score")) if m.get("score") not in (None, "") else None
    except (TypeError, ValueError):
        score = None
    try:
        duration = int(m.get("duration") or 0) or None
    except (TypeError, ValueError):
        duration = None
    return {
        "ranking": ranking,
        "code": code,
        "title": title,
        "cover_url": cover,
        "score": score,
        "release_date": (m.get("release_date") or "").strip(),
        "duration": duration,
        "magnets_count": m.get("magnets_count"),
        "has_cnsub": bool(m.get("has_cnsub")),
        "has_preview_video": bool(m.get("has_preview_video")),
        "in_library": False,  # 后续 crossref 填充
    }


async def fetch_top250(
    token: str,
    zone: str = "censored",
    proxy: Optional[str] = None,
    max_items: int = 250,
) -> list[dict]:
    """翻页抓取 TOP250（默认有码）。返回解析后的影片列表。"""
    if zone not in ZONES:
        raise ValueError(f"未知分区: {zone}")
    proxy = proxy or get_effective_proxy_url()
    zone_val = ZONES[zone]
    items: list[dict] = []
    page = 1
    limit = 50
    async with httpx.AsyncClient(proxy=proxy, timeout=30, follow_redirects=True) as c:
        while len(items) < max_items:
            ts = int(time.time())
            q = _public_params()
            q.update(
                {
                    "type": "video_type",
                    "type_value": str(zone_val),
                    "start_rank": "1",
                    "page": str(page),
                    "limit": str(limit),
                    "ignore_watched": "false",
                }
            )
            url = f"{_BASE_URL}/api/v1/movies/top?" + "&".join(
                f"{k}={v}" for k, v in q.items()
            )
            try:
                r = await c.get(url, headers=_headers(ts, token))
            except httpx.HTTPError as e:
                raise RuntimeError(f"TOP250 请求失败: {e}")
            if r.status_code >= 400:
                raise RuntimeError(f"TOP250 HTTP {r.status_code}: {r.text[:200]}")
            try:
                env = r.json()
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"TOP250 响应解析失败: {e} body={r.text[:120]}")
            if not env.get("success"):
                raise RuntimeError(
                    f"TOP250 失败: {env.get('action')} {env.get('message')}"
                )
            data = env.get("data") or {}
            movies = data.get("movies") or []
            if not movies:
                break
            for m in movies:
                item = _parse_movie(m)
                if item:
                    items.append(item)
            if len(movies) < limit:
                break
            page += 1
    return items[:max_items]


async def crossref_library(codes: list[str]) -> set:
    """返回 codes 中本地 jav.db 已收录（code 命中）的集合（大小写不敏感）。"""
    from app.db.jav_models import JAV_BASE, JavMovie
    from app.db.module_db import ModuleDatabase
    from sqlalchemy import func, select

    norm = {c.lower() for c in codes if c}
    if not norm:
        return set()
    db = ModuleDatabase.get_instance("jav", base_class=JAV_BASE)
    present: set = set()
    async with db.session_scope() as session:
        stmt = select(func.lower(JavMovie.code)).where(
            func.lower(JavMovie.code).in_(norm)
        )
        res = await session.execute(stmt)
        for (c,) in res.all():
            present.add(c)
    return present


async def get_top250(
    zone: str = "censored",
    token: Optional[str] = None,
    only_missing: bool = False,
    refresh: bool = False,
) -> list[dict]:
    """编排：解析 token → （缓存）抓榜 → 对照本地库 → 返回带 in_library 的列表。

    token 解析顺序：显式参数 > 进程缓存 > 配置 token > 配置账号自动登录。
    🔴 关键：预置的 token 可能**过期或无效**（实测踩过：配置里留了编造的占位 token，
    会让 TOP250 直接 401 且永不回退）。故抓到鉴权类错误时强制用账号重新登录重试一次，
    只有重试仍失败才向上抛错。
    """
    proxy = get_effective_proxy_url()
    tok = token or _token_cache.get("token")
    cfg_tok, usr, pwd = _read_config_creds()
    if not tok:
        tok = cfg_tok
        if not tok and usr and pwd:
            log.info("JavDB App Token 缺失，使用配置账号自动登录")
            tok = await login(usr, pwd, proxy=proxy)
    if not tok:
        raise RuntimeError("NO_TOKEN")

    now = time.time()
    cached_ok = (
        not refresh
        and _CACHE["items"]
        and _CACHE["zone"] == zone
        and now - _CACHE["ts"] < _CACHE_TTL
    )
    if cached_ok:
        items = [dict(i) for i in _CACHE["items"]]
    else:
        try:
            items = await fetch_top250(tok, zone, proxy=proxy)
        except RuntimeError as e:
            # token 失效/无权限：若配置里有账号，自动重新登录重试一次
            msg = str(e)
            auth_bad = any(
                k in msg
                for k in ("JWT", "401", "403", "unauthorized", "Unauthorized",
                          "token", "Token", "登录")
            )
            if auth_bad and usr and pwd:
                log.warning("JavDB TOP250 token 失效（%s），用配置账号重新登录重试", msg[:120])
                tok = await login(usr, pwd, proxy=proxy)
                items = await fetch_top250(tok, zone, proxy=proxy)
            else:
                raise
        _CACHE.update(items=items, zone=zone, ts=now)

    codes = [i["code"] for i in items]
    present = await crossref_library(codes)
    for i in items:
        i["in_library"] = i["code"].lower() in present
        # 🔴 2026-10-14：把 spfcas 原始 URL 改写成本服务的封面代理路径。
        #    原因：该 CDN 对 JPEG 做了 XOR 混淆，浏览器直连拿到的是乱码二进制，
        #    <img> 解码失败 ⇒ 页面显示「无封面」；且 spfcas 在墙内未必直连得到。
        #    代理端点会服务端下载 → XOR 解密 → 回传合法 JPEG。
        #    前端 el-image 直接用这个字段，无需改任何 Vue 代码。
        if i.get("cover_url"):
            i["cover_url"] = f"/api/v1/jav/top250/cover?url={quote(i['cover_url'], safe='')}"

    if only_missing:
        items = [i for i in items if not i["in_library"]]
    return items
