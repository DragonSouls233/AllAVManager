"""JavDB 匿名 App JSON API 客户端（绕 Cloudflare 抓磁力）。

来源：逆向 javdb-cli（Go）的 jdsignature 匿名签名方案。
- 不需要登录 Cookie / Token，直接返回 JSON，天然绕过 Cloudflare 5秒盾 / Turnstile。
- Host: https://jdforrepam.com （App 镜像域名）
- 签名：jdsignature = f"{ts}.{SUFFIX}.{md5(str(ts) + PREFIX)}"
- 每个请求必须带全套 public query 参数（app_channel/app_version/platform/device_uuid...），否则服务端返回 ParameterInvalid。
- 自动选线（auto_host=True，默认）：通过 /api/v1/startup 探测 + 解密 backup_domains_data
  自动选择最快 API 域名，避免单域名失效导致全挂（见 javdb_autohost.py）。

================================================================================
⚠️ JavDB App API 来源与版本追踪（更新前必读）======================================
权威参考:   https://github.com/FlanChanXwO/javdb-cli   (Go, NOT github.com/javinfo/cli)
本地副本:   G:\\MDCX\\.references\\MDCX-Project-Reference\\ref15-javdb-cli   (submodule, v0.7.2)
            ├── internal/javdb/appapi/endpoint/route/decrypt.go  ← backup_domains 解密
            ├── internal/javdb/appapi/endpoint/route/selector.go ← 自动选线
            ├── sdk/reversesearch.go                             ← 以图搜番
            └── internal/javdb/appapi/endpoint/magnets/magnets.go← 磁力排序
App 镜像:   https://jdforrepam.com
逆向版本:   JavDB.apk 1.9.28  (app_version=1.9.28, app_version_number=10928)
版本差异:   bdvajstudio 官方 App 已到 v1.9.35 (2026-03-11)，
            但 jdforrepam.com 服务端仍接受 v1.9.28 签名（2026-08 实测通过）。
            何时更新？当 check_command_hint 失败、API 持续返回 ParameterInvalid。
失效信号:   所有 API 调用持续返回 ParameterInvalid / success:false
替代方案:   走 javdb_api_client.py (api.javdb.com, 需登录) 或 HTML 爬虫降级
================================================================================
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

# 维护元数据：给后续更新/排障用的集中入口（单点修改）
JAVDB_APP_API_META = {
    # 在线参考源：github.com/FlanChanXwO/javdb-cli（注意：不是 github.com/javinfo/cli，那是商业 API CLI）
    "source_repo": "https://github.com/FlanChanXwO/javdb-cli",
    "source_version": "v0.7.2",
    # 本地参考副本（git submodule，位于参考项目集中目录，可批量更新）：
    #   G:\MDCX\.references\MDCX-Project-Reference\ref15-javdb-cli
    #   ├─ internal/javdb/appapi/endpoint/route/decrypt.go   # backup_domains_data 解密
    #   ├─ internal/javdb/appapi/endpoint/route/selector.go  # 自动选线
    #   ├─ internal/javdb/appapi/endpoint/magnets/magnets.go # 磁力排序
    #   └─ sdk/reversesearch.go                              # 以图搜番
    "local_reference": r"G:\MDCX\.references\MDCX-Project-Reference\ref15-javdb-cli",
    "synced_features": [
        "自动选线 (v0.6.0)  → javdb_autohost.py + auto_host",
        "以图搜番 (v0.7.0)  → javdb_reverse_search.py (AVScan)",
        "磁力排序筛选 (v0.7.2)→ rank_magnets/filter_magnets",
        "统一投影 (v0.6.0)  → project_movie/project_magnet",
        "演员别名补全 (mdcx-diy) → fetch_actor_aliases + app/utils/actor_name_utils.py",
    ],
    "mirror_host": "https://jdforrepam.com",
    "app_version": "1.9.28",
    "app_version_number": "10928",
    "reverse_target": "JavDB.apk 1.9.28",
    "deprecated_after": None,           # 一旦确认上游常量失效，在此填失效日期
    "check_command_hint":
        "python -c \"import asyncio; from app.services.javdb_app_client import JavDBAppClient;"
        "asyncio.run((lambda c: (print('OK'), c.close()))(JavDBAppClient()))\"",
    "update_steps": [
        "1. 拉取最新参考: git clone https://github.com/FlanChanXwO/javdb-cli (或同步到 .references/GitHub/)",
        "2. 看 internal/javdb/protocol/signature/sign.go 的 Prefix / Suffix 是否变了",
        "3. 同步到下方 _JAVDB_APP_SIGN_PREFIX / _JAVDB_APP_SIGN_SUFFIX",
        "4. 看 internal/javdb/appapi/device.go 是否改了 app_version / device_id 生成规则",
        "5. 同步到 _APP_VERSION / _APP_VERSION_NUMBER / _build_device_uuid()",
        "6. 跑 check_command_hint 确认",
    ],
}

log = logging.getLogger(__name__)

# --- 签名常量（逆向自 JavDB.apk 1.9.28，与 App 版本强绑定） -------------------
_JAVDB_APP_SIGN_PREFIX = (
    "71cf27bb3c0bcdf207b64abecddc970098c7421ee7203b9cdae54478478a199e7d5a6e1a"
    "57691123c1a931c057842fb73ba3b3c83bcd69c17ccf174081e3d8aa"
)
_JAVDB_APP_SIGN_SUFFIX = "lpw6vgqzsp"

_BASE_URL = "https://jdforrepam.com"
_USER_AGENT = "Dart/3.4 (dart:io)"
_APP_VERSION = "1.9.28"
_APP_VERSION_NUMBER = "10928"
_LANG = "en"

# search movie_type 分区掩码
ZONES = {
    "censored": 0,    # 有码
    "uncensored": 1,  # 无码
    "western": 2,     # 西方
    "fc2": 3,         # FC2
}


def make_signature(ts: int) -> str:
    """生成 jdsignature。

    >>> make_signature(1784134914)
    '1784134914.lpw6vgqzsp.85b53cc0034eff62f361723615a3b8e3'
    """
    return f"{ts}.{_JAVDB_APP_SIGN_SUFFIX}." + hashlib.md5(
        f"{ts}{_JAVDB_APP_SIGN_PREFIX}".encode("utf-8")
    ).hexdigest()


@dataclass
class JavDBAppMagnet:
    name: str = ""
    hash: str = ""
    size: int = 0            # JavDB 以 MB 为单位
    cnsub: bool = False      # 是否有中文字幕
    hd: bool = False         # 是否高清
    files_count: int = 0
    created_at: str = ""     # 形如 "09/05/2021"
    pikpak_url: str = ""
    magnet_uri: str = ""     # 由 hash 构造的标准 magnet 链接


@dataclass
class JavDBAppMovie:
    id: str = ""
    number: str = ""         # 番号（如 ABP-123）
    title: str = ""
    origin_title: str = ""
    thumb_url: str = ""
    cover_url: str = ""
    duration: int = 0
    magnets_count: int = 0
    release_date: str = ""
    has_cnsub: bool = False
    has_preview_video: bool = False
    raw: dict = field(default_factory=dict)


def _safe_int(v: Any) -> int:
    """宽松整数解析：兼容 int/float/带前缀数字字符串（如 '1.2GB'、'123MB'）。

    移植自 javdb-cli magnets.go anyInt 语义（只取前导数字）。
    """
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    m = re.match(r"\d+", s)
    return int(m.group()) if m else 0


def _parse_magnet(raw: dict) -> JavDBAppMagnet:
    h = (raw.get("hash") or "").strip()
    return JavDBAppMagnet(
        name=raw.get("name") or "",
        hash=h,
        size=_safe_int(raw.get("size")),
        cnsub=bool(raw.get("cnsub") or False),
        hd=bool(raw.get("hd") or False),
        files_count=_safe_int(raw.get("files_count")),
        created_at=raw.get("created_at") or "",
        pikpak_url=raw.get("pikpak_url") or "",
        magnet_uri=f"magnet:?xt=urn:btih:{h}" if h else "",
    )


# --- 统一投影（移植 javdb-cli v0.6.0 统一 movie/magnet 投影语义）----------------

def project_movie(raw: dict) -> dict:
    """宽松影片行投影：任意原始 dict → 统一字段（JavDBAppMovie 结构）。"""
    return {
        "id": raw.get("id") or "",
        "number": raw.get("number") or "",
        "title": raw.get("title") or "",
        "origin_title": raw.get("origin_title") or "",
        "thumb_url": raw.get("thumb_url") or "",
        "cover_url": raw.get("cover_url") or "",
        "duration": _safe_int(raw.get("duration")),
        "magnets_count": _safe_int(raw.get("magnets_count")),
        "release_date": raw.get("release_date") or "",
        "has_cnsub": bool(raw.get("has_cnsub") or False),
        "has_preview_video": bool(raw.get("has_preview_video") or False),
    }


def project_magnet(raw: dict) -> dict:
    """宽松磁力行投影：任意原始 dict → 统一字段（JavDBAppMagnet 结构）。"""
    h = (raw.get("hash") or "").strip()
    return {
        "name": raw.get("name") or "",
        "hash": h,
        "size": _safe_int(raw.get("size")),
        "cnsub": bool(raw.get("cnsub") or False),
        "hd": bool(raw.get("hd") or False),
        "files_count": _safe_int(raw.get("files_count")),
        "created_at": raw.get("created_at") or "",
        "pikpak_url": raw.get("pikpak_url") or "",
        "magnet_uri": f"magnet:?xt=urn:btih:{h}" if h else "",
    }


# --- 磁力排序/筛选（移植 javdb-cli v0.7.2 magnets.go）----------------------------

def magnet_better(a: "JavDBAppMagnet", b: "JavDBAppMagnet") -> bool:
    """a 是否优于 b：cnsub > hd > size > files_count（MagnetBetter）。"""
    return (bool(a.cnsub), bool(a.hd), a.size, a.files_count) > (
        bool(b.cnsub), bool(b.hd), b.size, b.files_count)


def rank_magnets(magnets: list["JavDBAppMagnet"], count: int = 0) -> list["JavDBAppMagnet"]:
    """稳定排序磁力列表并按 count 截取；count<=0 返回全部排序结果。不修改输入。"""
    if not magnets:
        return magnets
    ranked = sorted(magnets, key=lambda m: (bool(m.cnsub), bool(m.hd), m.size, m.files_count), reverse=True)
    if count > 0 and count < len(ranked):
        ranked = ranked[:count]
    return ranked


def filter_magnets(
    magnets: list["JavDBAppMagnet"],
    cnsub: bool = False,
    hd: bool = False,
    min_size: int = 0,
) -> list["JavDBAppMagnet"]:
    """按 cnsub/hd/最小体积筛选（FilterMagnets）。"""
    out: list[JavDBAppMagnet] = []
    for m in magnets:
        if cnsub and not m.cnsub:
            continue
        if hd and not m.hd:
            continue
        if min_size > 0 and m.size < min_size:
            continue
        out.append(m)
    return out


# 自动选线进程内缓存：选线结果 + 上次线路（下次优先验证复用，对应 selector 的
# PreferredHost 语义）。跨进程持久化由上层（如 config 或独立存储）自行处理。
class _AutoHostStore:
    def __init__(self) -> None:
        self._value: Optional[str] = None

    def get(self) -> Optional[str]:
        return self._value

    def set(self, host: str) -> None:
        self._value = host


_AUTO_HOST_CACHE = _AutoHostStore()
_AUTO_HOST_PREFERRED = _AutoHostStore()


class JavDBAppClient:
    """JavDB 匿名 App API 客户端。

    用法：
        client = JavDBAppClient()
        movie = await client.search_movie("ABP-123")      # 精确匹配番号
        magnets = await client.get_magnets(movie.id)      # 取磁力
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        proxy: Optional[str] = None,
        timeout: float = 30.0,
        retries: int = 2,
        lang: str = _LANG,
        auto_host: bool = False,
    ):
        self._auto_host = auto_host or (base_url == "auto")
        self._base: Optional[str] = None if self._auto_host else base_url.rstrip("/")
        self._proxy = proxy
        self._timeout = timeout
        self._retries = retries
        self._lang = lang
        self._device_uuid = str(uuid.uuid4())
        self._http: Optional[httpx.AsyncClient] = None

    async def ensure_base(self) -> str:
        """确保已选定 API host（自动选线模式惰性完成一次，结果进程内缓存）。

        返回最终 base url。自动选线失败回退官方镜像 _BASE_URL。
        """
        if self._base is not None:
            return self._base
        from app.services.javdb_autohost import select_auto_host

        cached = _AUTO_HOST_CACHE.get()
        if cached is not None:
            self._base = cached
            return self._base
        try:
            result = await select_auto_host(
                preferred=_AUTO_HOST_PREFERRED.get(),
                proxy=self._proxy,
                timeout=min(self._timeout, 8.0),
                lang=self._lang,
            )
            host = result.host
            _AUTO_HOST_CACHE.set(host)
            _AUTO_HOST_PREFERRED.set(host)
            log.info("JavDB App API 自动选线: %s (%.0fms)", host, result.latency * 1000)
        except Exception as e:  # noqa: BLE001
            log.warning("JavDB App API 自动选线失败，回退 %s: %s", _BASE_URL, e)
            host = _BASE_URL
        self._base = host
        return self._base

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                proxy=self._proxy,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
            )
        return self._http

    def _public_params(self) -> dict[str, str]:
        return {
            "app_channel": "official",
            "app_version": _APP_VERSION,
            "app_version_number": _APP_VERSION_NUMBER,
            "platform": "android",
            "system_version": "13",
            "device_model": "Pixel 6",
            "device_name": "Pixel",
            "device_uuid": self._device_uuid,
        }

    async def _request(
        self, method: str, path: str, params: Optional[dict] = None
    ) -> Optional[dict]:
        """发送带签名 + public 参数的请求，返回 data 字段；失败返回 None。"""
        base = await self.ensure_base()
        client = await self._get_client()
        last_err: Optional[Exception] = None
        for _ in range(self._retries + 1):
            ts = int(time.time())
            q = self._public_params()
            if params:
                q.update({k: str(v) for k, v in params.items() if v is not None})
            url = f"{base}{path}?" + "&".join(f"{k}={v}" for k, v in q.items())
            headers = {
                "Accept": "application/json",
                "accept-language": self._lang,
                "jdsignature": make_signature(ts),
            }
            try:
                r = await client.request(method, url, headers=headers)
            except httpx.HTTPError as e:
                last_err = e
                continue
            if r.status_code >= 400:
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                continue
            try:
                env = r.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
            if not env.get("success"):
                # 服务端业务错误（success:0）：ParameterInvalid / ResourceNotFound 等
                log.debug("JavDB app api biz error: %s", env.get("action"))
                return None
            return env.get("data")
        if last_err:
            log.warning("JavDB app api request failed after retries: %s", last_err)
        return None

    async def search_movie(
        self, code: str, zone: Optional[str] = None
    ) -> Optional[JavDBAppMovie]:
        """按番号搜索，返回精确匹配（number==code）的电影；无精确匹配则返回首个相关项。

        若传了 zone（分区过滤）但未命中精确匹配，自动去掉分区限制全量重搜一次，
        避免 JavDB 分区索引不全导致漏判——调用方无需感知。
        """
        cu = code.upper().replace("-", "")
        movies = await self._search_raw(code, zone)
        best = self._find_exact(movies, cu)
        if best is None and zone and zone in ZONES:
            movies = await self._search_raw(code, None)
            best = self._find_exact(movies, cu)
        if best is None and movies:
            best = movies[0]
        if best is None:
            return None
        return JavDBAppMovie(
            id=best.get("id") or "",
            number=best.get("number") or "",
            title=best.get("title") or "",
            origin_title=best.get("origin_title") or "",
            thumb_url=best.get("thumb_url") or "",
            cover_url=best.get("cover_url") or "",
            duration=int(best.get("duration") or 0),
            magnets_count=int(best.get("magnets_count") or 0),
            release_date=best.get("release_date") or "",
            has_cnsub=bool(best.get("has_cnsub") or False),
            has_preview_video=bool(best.get("has_preview_video") or False),
            raw=best,
        )

    async def _search_raw(self, code: str, zone: Optional[str]) -> list[dict]:
        """按番号 + 可选分区执行一次搜索，返回原始 movie 列表。"""
        params: dict[str, Any] = {"q": code, "page": 1}
        if zone and zone in ZONES:
            params["movie_type"] = ZONES[zone]
        data = await self._request("GET", "/api/v2/search", params)
        if not data:
            return []
        return (data.get("movies") or []) if isinstance(data, dict) else []

    @staticmethod
    def _find_exact(movies: list[dict], code_upper_clean: str) -> Optional[dict]:
        """在搜索结果中找番号精确匹配的条目。"""
        for m in movies:
            num = (m.get("number") or "").upper().replace("-", "")
            if num == code_upper_clean:
                return m
        return None

    async def fetch_actor_index(
        self,
        zone: str = "censored",
        max_pages: int = 100,
        limit: int = 50,
    ) -> dict[str, list[str]]:
        """翻页抓取演员目录，返回 {actor_id: [全部名字]}（匿名 App API，免登录不绑 IP）。

        端点 /api/v1/actors?type={zone}&page=N&limit=M：
        - type 分区：censored=0 / uncensored=1 / western=2 / fc2=3
        - 每条含 name（主名）、name_zht（繁体名）、other_name（曾用名，逗号分隔）
        翻页直到 actors 为空或达到 max_pages。
        """
        if zone not in ZONES:
            raise ValueError(f"未知分区: {zone}")
        index: dict[str, list[str]] = {}
        for page in range(1, max_pages + 1):
            data = await self._request(
                "GET",
                "/api/v1/actors",
                {"page": page, "type": ZONES[zone], "limit": limit},
            )
            if not data:
                break
            actors = data.get("actors") or []
            if not actors:
                break
            for a in actors:
                aid = (a.get("id") or "").strip()
                if not aid:
                    continue
                names: list[str] = []
                for raw in (
                    a.get("name") or "",
                    a.get("name_zht") or "",
                    (a.get("other_name") or "").replace("，", ","),
                ):
                    for n in raw.split(","):
                        n = n.strip()
                        if n and n not in names:
                            names.append(n)
                if names:
                    index[aid] = names
            if page % 20 == 0:
                log.info(f"JavDB App API 演员目录已抓取 {page} 页，累计 {len(index)} 人")
        return index

    async def get_magnets(
        self,
        movie_id: str,
        limit: Optional[int] = None,
        sort: bool = True,
    ) -> list[JavDBAppMagnet]:
        """按 App movie id 取磁力列表。

        默认按优先规则（cnsub > hd > size > files_count）稳定排序（v0.7.2 磁力排序）；
        limit>0 时截取前 N 条（对应 search --magnets N 语义）。
        """
        if not movie_id:
            return []
        data = await self._request("GET", f"/api/v1/movies/{movie_id}/magnets")
        if not data:
            return []
        raw_list = data.get("magnets") or []
        magnets = [_parse_magnet(r) for r in raw_list if isinstance(r, dict)]
        if sort:
            magnets = rank_magnets(magnets)
        if limit and limit > 0:
            magnets = magnets[:limit]
        return magnets

    async def search_movie_exact(self, code: str) -> Optional[str]:
        """严格番号精确解析：zone=all 搜索，大小写不敏感完整相等（去连字符）。

        零匹配与多重精确匹配都返回 None（不沿用首项回退）。移植自
        javdb-cli v0.7.2 ResolveMovieIDExact。返回 movie id 供以图搜番联动。
        """
        cu = code.upper().replace("-", "")
        movies = await self._search_raw(code, None)
        exact = [
            m for m in movies
            if (m.get("number") or "").upper().replace("-", "") == cu
        ]
        if len(exact) != 1:
            return None
        return exact[0].get("id") or None

    async def get_movie_detail(self, movie_id: str) -> Optional[dict]:
        """取电影详情（/api/v4/movies/{id}）。"""
        if not movie_id:
            return None
        return await self._request("GET", f"/api/v4/movies/{movie_id}")

    async def fetch_actor_aliases(
        self,
        actor_name: str,
        max_movies: int = 5,
    ) -> list[str]:
        """按演员名查询别名（JavDB App API 演员详情 other_name 字段）。

        移植自 mdcx-diy（cdlongbow/mdcx-diy）`mdcx/crawlers/javdb_app.py`
        fetch_javdb_aliases（ref22-mdcx-diy）：
        流程: /api/v2/search 搜索演员名 → 前 max_movies 部影片详情 → 匹配演员
        → /api/v1/actors/{id} 详情 other_name 字段拆分别名；并并入 name_zht。
        搜索无结果、未匹配到演员、无别名均返回空列表，由调用方决定如何降级。
        """
        from app.utils.actor_name_utils import actor_name_matches, split_aliases

        target = (actor_name or "").strip()
        if not target:
            return []
        data = await self._request("GET", "/api/v2/search", {"q": target, "page": 1})
        if not data:
            return []
        movies = data.get("movies") or []
        for movie in movies[:max_movies]:
            mid = (movie.get("id") or "").strip()
            if not mid:
                continue
            detail = await self.get_movie_detail(mid)
            if not detail:
                continue
            actors = (detail.get("movie") or {}).get("actors") or []
            for actor in actors:
                if not isinstance(actor, dict):
                    continue
                cand_name = (actor.get("name") or "").strip()
                if not cand_name or not actor_name_matches(target, cand_name):
                    continue
                aid = (actor.get("id") or "").strip()
                if not aid:
                    continue
                actor_data = await self._request("GET", f"/api/v1/actors/{aid}")
                if not actor_data:
                    continue
                a = (actor_data.get("actor") or {}) if isinstance(actor_data, dict) else {}
                return split_aliases(
                    a.get("other_name") or "",
                    a.get("name_zht") or "",
                    target,
                    a.get("name") or cand_name,
                )
        return []

    async def build_scrape_fields(
        self,
        mv: JavDBAppMovie,
        magnets: list[JavDBAppMagnet],
    ) -> dict:
        """聚合搜索 + v4 详情字段，返回可直接构造 ScrapeResult 的 dict（不含 source）。

        2026-08-18 新增：搜索接口字段极少（无 studio/series/actors/tags/plot），
        v4 详情接口补齐，解决 NFO 系列/演员/标签/简介缺失。
        """
        import re as _re

        detail = await self.get_movie_detail(mv.id) or {}
        dm = (detail.get("movie") or {}) if isinstance(detail, dict) else {}

        # 演员
        from app.crawlers.base import ActorInfo  # 局部导入避免循环依赖

        actors: list[ActorInfo] = []
        for a in (dm.get("actors") or []) if isinstance(dm.get("actors"), list) else []:
            if isinstance(a, dict) and a.get("name"):
                actors.append(ActorInfo(
                    name=str(a.get("name")),
                    avatar_url=str(a.get("avatar_url") or "") or None,
                ))

        # 标签/类型（JavDB tag name 常为 "中文名、日文名" 顿号分隔，拆分）
        genres: list[str] = []
        tags: list[str] = []
        for t in (dm.get("tags") or []) if isinstance(dm.get("tags"), list) else []:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            parts = [p.strip() for p in _re.split(r"[、,，/]", str(t.get("name"))) if p.strip()]
            genres.extend(parts)
            tags.extend(parts)
        genres = list(dict.fromkeys(genres))
        tags = list(dict.fromkeys(tags))

        # 样图（v4 详情 preview_images 为 large_url；搜索接口为 thumb）
        sample_images: list[str] = []
        previews = dm.get("preview_images")
        if isinstance(previews, list):
            for p in previews:
                if isinstance(p, dict) and p.get("large_url"):
                    sample_images.append(str(p["large_url"]))
                elif isinstance(p, dict) and p.get("thumb_url"):
                    sample_images.append(str(p["thumb_url"]))
        if not sample_images:
            raw_previews = mv.raw.get("preview_images")
            if isinstance(raw_previews, list):
                for p in raw_previews:
                    if isinstance(p, dict) and p.get("thumb_url"):
                        sample_images.append(str(p["thumb_url"]))

        rating = None
        try:
            if dm.get("score"):
                rating = float(dm["score"])
        except (TypeError, ValueError):
            rating = None

        return {
            "code": mv.number or "",
            "title": mv.title or mv.origin_title or "",
            "original_title": mv.origin_title or "",
            "release_date": dm.get("release_date") or mv.release_date or "",
            "duration": mv.duration or None,
            "plot": str(dm.get("summary") or "") or None,
            "genres": genres,
            "tags": tags,
            "actors": actors,
            "all_actors": [a.name for a in actors],
            "directors": [str(dm["director_name"])] if dm.get("director_name") else [],
            "studio": str(dm.get("maker_name") or "") or None,
            "maker": str(dm.get("maker_name") or "") or None,
            "label": str(dm.get("publisher_name") or "") or None,
            "series": str(dm.get("series_name") or "") or None,
            "rating": rating,
            "cover_url": mv.cover_url or mv.thumb_url or "",
            "poster_url": mv.cover_url or "",
            "thumb_url": mv.thumb_url or "",
            "sample_images": sample_images,
            "raw_data": {
                "javdb_id": mv.id,
                "source": "javdb_app_api",
                "magnets": [
                    {
                        "name": m.name,
                        "hash": m.hash,
                        "size": m.size,
                        "cnsub": m.cnsub,
                        "hd": m.hd,
                        "magnet_uri": m.magnet_uri,
                    }
                    for m in magnets
                ],
            },
        }

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None


async def create_app_client_from_config() -> JavDBAppClient:
    """从 MDCX 配置创建匿名客户端（仅取代理，无需登录）。

    默认启用自动选线（auto_host=True）：启动时通过 /api/v1/startup 探测选择
    最快 API 域名并进程内缓存；失败自动回退官方镜像。
    """
    proxy = None
    try:
        from app.services.proxy_manager import get_effective_proxy_url
        # 统一走项目代理唯一入口：优先内置 xray 实际端口，回退 config.proxy
        proxy = get_effective_proxy_url()
    except Exception:  # noqa: BLE001
        log.debug("create_app_client_from_config: 读取代理配置失败，使用直连")
    client = JavDBAppClient(proxy=proxy, auto_host=True)
    # 启动时做一次轻量健康检查（不阻塞调用方；失败仅打 WARNING）
    try:
        asyncio.create_task(_async_health_check(client))
    except RuntimeError:
        # 无事件循环（CLI/测试环境）则跳过
        pass
    return client


async def _async_health_check(client: "JavDBAppClient") -> None:
    """单次轻量探测：搜索 1 部常见番号 + 校验成功 → 确认签名常量未失效

    - 成功：DEBUG 日志
    - 失败：WARNING 日志（说明需重新逆向 javdb-cli 更新 PREFIX/SUFFIX）
    """
    try:
        mv = await client.search_movie("ABP-123", zone="censored")
        if mv and mv.id:
            log.debug("JavDBAppClient 健康检查通过 (PREFIX/SUFFIX 仍有效)")
        else:
            log.warning(
                "JavDBAppClient 健康检查未通过：可能需重新逆向 javdb-cli 更新 "
                "_JAVDB_APP_SIGN_PREFIX / _JAVDB_APP_SIGN_SUFFIX (当前版本: %s)",
                JAVDB_APP_API_META.get("app_version"),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("JavDBAppClient 健康检查异常: %s", e)


if __name__ == "__main__":
    # 自测：python -m app.services.javdb_app_client ABP-123
    import sys

    async def _self_test(code: str):
        c = JavDBAppClient()
        try:
            mv = await c.search_movie(code)
            print("movie:", mv.number, mv.title, "magnets_count=", mv.magnets_count)
            if mv:
                mags = await c.get_magnets(mv.id)
                print(f"got {len(mags)} magnets, first:", mags[0].magnet_uri if mags else None)
        finally:
            await c.close()

    asyncio.run(_self_test(sys.argv[1] if len(sys.argv) > 1 else "ABP-123"))
