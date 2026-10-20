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

# 🔴 2026-10-20：TOP250 不再只是「JAV 有码」的事，改为跨 4 个模块的收录体检。
# JavDB 榜单本身就有这 4 个分区（见 ZONES），所以数据源无需新增抓取，
# 要改的是**本地库对照**：原来只查 jav.db，现在每个分区查各自模块库。
#
# 分区 → 本地模块名（模块库 code 字段存番号）
ZONE_MODULE = {
    "censored": "jav",
    "uncensored": "uncensored",
    "western": "western",
    "fc2": "fc2",
}

# 分区 → 展示名 / 菜单归属（前端用）
ZONE_LABEL = {
    "censored": "JAV 有码",
    "uncensored": "JAV 无码",
    "western": "欧美",
    "fc2": "FC2",
}


def normalize_code(code: str) -> str:
    """番号归一化：用于跨库匹配，抹平大小写/分隔符/常见前缀差异。

    实测需要归一化的场景：
      - 大小写：``FC2-PPV-1234567`` vs ``fc2-ppv-1234567``
      - 空格/分隔符：``ABP-123`` vs ``ABP 123``
      - 尾部连字符差异
    ⚠️ 只做「大小写 + 去掉所有分隔符」的保守归一化，**不删除有语义的字符**，
    避免把不同番号误判成同一部。
    """
    if not code:
        return ""
    import re
    return re.sub(r"[^a-z0-9]+", "", str(code).strip().lower())

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


async def crossref_library(codes: list[str], zone: str = "censored") -> tuple[set, dict]:
    """返回 (codes 中本地库已收录的集合, 该模块库规模信息)。

    🔴 2026-10-20 改为**按分区查对应模块库**（原实现硬编码只查 jav.db）：
        censored→jav / uncensored→uncensored / western→western / fc2→fc2

    匹配用归一化 key（见 normalize_code）而不是直接 lower() 比对，
    避免 FC2 的 ``FC2-PPV-1234567`` 因分隔符/大小写差异被判成"未收录"。
    """
    from sqlalchemy import func, select

    from app.db.module_db import ModuleDatabase

    module = ZONE_MODULE.get(zone, "jav")
    # 各模块的 base/影片模型类名不统一，统一从表里取
    base_cls, movie_cls = _get_module_movie_model(module)

    info = {
        "module": module,
        "label": ZONE_LABEL.get(zone, zone),
        "library_total": 0,
        "available": False,
    }

    norm = {normalize_code(c): c for c in codes if c}
    if not norm:
        return set(), info

    db = ModuleDatabase.get_instance(module, base_class=base_cls)
    async with db.session_scope() as session:
        # 模块库规模
        try:
            info["library_total"] = (await session.execute(
                select(func.count()).select_from(movie_cls))).scalar_one()
            info["available"] = True
        except Exception as e:  # 库为空/表不存在时也返回统计，不让对照整体失败
            log.warning("[top250] 读取 %s 库规模失败: %s", module, e)

        present: set = set()
        # 归一化后 IN 查（把库里 code 也归一化在 Python 侧做，SQL 侧只做粗筛）
        # 库可能很大，先用原始 code 粗筛（直接等值/IN），再对候选做归一化确认。
        try:
            raw_rows = (await session.execute(
                select(movie_cls.code).where(movie_cls.code.in_(list(norm.values())))
            )).all()
            for (c,) in raw_rows:
                present.add(c.lower())
        except Exception as e:
            log.warning("[top250] 粗筛 %s 失败: %s", module, e)

        if len(present) < len(norm):
            # 粗筛没覆盖全 → 拉全库 code 归一化比对（模块库量级 1 万级，可接受）
            try:
                all_codes = (await session.execute(
                    select(movie_cls.code))).all()
                have = {normalize_code(c) for (c,) in all_codes if c}
                for nk, orig in norm.items():
                    if nk in have:
                        present.add(orig.lower())
            except Exception as e:
                log.warning("[top250] 全库归一化比对 %s 失败: %s", module, e)

    # 只保留真正在 codes 里的
    result = {c.lower() for c in present if c.lower() in {x.lower() for x in codes}}
    return result, info


def _get_module_movie_model(module: str):
    """取某模块的 (DeclarativeBase, 影片模型) —— 各模块模型类名不统一。"""
    import importlib
    table = {
        "jav": ("app.db.jav_models", "JAV_BASE", "JavMovie"),
        "uncensored": ("app.db.uncensored_models", "UNCENSORED_BASE", "UncensoredMovie"),
        "western": ("app.db.western_models", "WESTERN_BASE", "WesternMovie"),
        "fc2": ("app.db.fc2_models", "FC2_BASE", "Fc2Movie"),
        "chinese": ("app.db.chinese_models", "CHINESE_BASE", "ChineseMovie"),
        "pornhub": ("app.db.pornhub_models", "PORNHUB_BASE", "PornhubMovie"),
        "anime": ("app.db.anime_models", "ANIME_BASE", "AnimeMovie"),
    }
    if module not in table:
        raise ValueError(f"未知模块: {module}")
    mod_name, base_name, cls_name = table[module]
    mod = importlib.import_module(mod_name)
    return getattr(mod, base_name), getattr(mod, cls_name)


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
        # 🔴 存副本而非引用：后续任何「原地改 items」的操作都不会污染缓存
        # （2026-10-17 的 cover_url 嵌套 bug 就是引用被原地改写造成的）
        _CACHE.update(items=[dict(i) for i in items], zone=zone, ts=now)

    codes = [i["code"] for i in items]
    # 🔴 2026-10-20：按当前分区对照**对应模块库**（原实现固定查 jav.db）
    present, lib_info = await crossref_library(codes, zone=zone)
    # 🔴🔴 2026-10-17 修复：必须在【响应出口】构造副本后再改写 cover_url，
    # 绝不能原地修改 items 里的 dict —— _CACHE["items"] 存的就是这批 dict 对象
    # （第 300 行直接 update 了引用），原地改写会把缓存污染成代理 URL，
    # 下次缓存命中再 quote 包装一层 ⇒ cover_url 无限嵌套
    # （/top250/cover?url=%2Fapi%2Fv1%2Fjav%2Ftop250%2Fcover%3Furl%3D...）⇒
    # 白名单校验必挂、502 ⇒ 前端全部「无封面」。副本构造保证缓存永远干净。
    # startswith 判断是幂等双保险（万一将来又有路径原地改）。
    out = []
    for i in items:
        item = dict(i)
        # present 存的是库里的原始 code；用归一化双向比对，避免大小写/分隔符差异
        item["in_library"] = normalize_code(item["code"]) in {
            normalize_code(p) for p in present}
        # 🔴 2026-10-14：把 spfcas 原始 URL 改写成本服务的封面代理路径。
        #    原因：该 CDN 对 JPEG 做了 XOR 混淆，浏览器直连拿到的是乱码二进制，
        #    <img> 解码失败 ⇒ 页面显示「无封面」；且 spfcas 在墙内未必直连得到。
        #    代理端点会服务端下载 → XOR 解密 → 回传合法 JPEG。
        #    前端 el-image 直接用这个字段，无需改任何 Vue 代码。
        cu = item.get("cover_url")
        if cu and not cu.startswith("/api/v1/jav/top250/cover"):
            item["cover_url"] = f"/api/v1/jav/top250/cover?url={quote(cu, safe='')}"
        out.append(item)

    if only_missing:
        out = [i for i in out if not i["in_library"]]

    # 🔴 2026-10-20：附带本地库规模，供前端显示"库里共 N 部"和"收录率 0%"的区分
    lib_info["collected"] = sum(1 for i in out if i["in_library"]) if not only_missing else 0
    lib_info["total_in_rank"] = len(out) if not only_missing else len(out)
    _LAST_LIBRARY_INFO.update(lib_info)
    return out


# 最近一次对照的本地库信息（供路由层汇总返回，避免改 get_top250 的返回类型）
_LAST_LIBRARY_INFO: dict = {}


async def get_zones_overview(token: Optional[str] = None,
                             refresh: bool = False) -> list[dict]:
    """一次性取 4 个分区的 TOP250 收录体检总览。

    🔴 2026-10-20 新增：用户要求"TOP250 变成 4 个模块的收录统计"。
    单个分区抓取失败**不拖垮整体**（例如某分区无权限），该分区返回 error 字段，
    其余分区照常返回 —— 否则 0 库存的欧美/FC2 会让整页不可用。
    """
    result = []
    for zone, label in ZONE_LABEL.items():
        entry = {"zone": zone, "label": label,
                 "module": ZONE_MODULE.get(zone), "items": []}
        try:
            items = await get_top250(zone=zone, token=token, refresh=refresh)
            entry["items"] = items
            entry["total"] = len(items)
            entry["collected"] = sum(1 for i in items if i.get("in_library"))
            entry["library_total"] = _LAST_LIBRARY_INFO.get("library_total", 0)
            entry["module_available"] = _LAST_LIBRARY_INFO.get("available", True)
            entry["rate"] = (entry["collected"] / entry["total"] * 100
                             if entry["total"] else 0.0)
            entry["status"] = "ok"
        except Exception as e:
            log.warning("[top250] 分区 %s 抓取失败: %s", zone, e)
            entry.update(total=0, collected=0, library_total=0, rate=0.0,
                         status="error", error=str(e)[:200])
        result.append(entry)
    return result
