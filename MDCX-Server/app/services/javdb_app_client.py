"""JavDB 匿名 App JSON API 客户端（绕 Cloudflare 抓磁力）。

来源：逆向 javdb-cli（Go）的 jdsignature 匿名签名方案。
- 不需要登录 Cookie / Token，直接返回 JSON，天然绕过 Cloudflare 5秒盾 / Turnstile。
- Host: https://jdforrepam.com （App 镜像域名）
- 签名：jdsignature = f"{ts}.{SUFFIX}.{md5(str(ts) + PREFIX)}"
- 每个请求必须带全套 public query 参数（app_channel/app_version/platform/device_uuid...），否则服务端返回 ParameterInvalid。

⚠️ 签名常量与 JavDB App 版本（api_version=1.9.28）强绑定。JavDB 改版后常量可能失效，
   届时需重新逆向并同步更新下方两个常量；上层调用方应保留 HTML 爬虫作为降级通道。

本客户端与 `javdb_api_client.py`（HMAC + 登录 Token 方案，api.javdb.com）**互补不替换**：
- javdb_api_client：需登录，能取收藏/观看记录等私有数据。
- javdb_app_client：免登录，专用于取公开元数据 + 磁力，是 JavDB 爬虫被 CF 拦截时的兜底磁力源。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

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


def _parse_magnet(raw: dict) -> JavDBAppMagnet:
    h = (raw.get("hash") or "").strip()
    return JavDBAppMagnet(
        name=raw.get("name") or "",
        hash=h,
        size=int(raw.get("size") or 0),
        cnsub=bool(raw.get("cnsub" if "cnsub" in raw else "cnsub") or raw.get("cnsub") or False),
        hd=bool(raw.get("hd") or False),
        files_count=int(raw.get("files_count") or 0),
        created_at=raw.get("created_at") or "",
        pikpak_url=raw.get("pikpak_url") or "",
        magnet_uri=f"magnet:?xt=urn:btih:{h}" if h else "",
    )


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
    ):
        self._base = base_url.rstrip("/")
        self._proxy = proxy
        self._timeout = timeout
        self._retries = retries
        self._lang = lang
        self._device_uuid = str(uuid.uuid4())
        self._http: Optional[httpx.AsyncClient] = None

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
        client = await self._get_client()
        last_err: Optional[Exception] = None
        for _ in range(self._retries + 1):
            ts = int(time.time())
            q = self._public_params()
            if params:
                q.update({k: str(v) for k, v in params.items() if v is not None})
            url = f"{self._base}{path}?" + "&".join(f"{k}={v}" for k, v in q.items())
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
        """按番号搜索，返回精确匹配（number==code）的电影；无精确匹配则返回首个相关项。"""
        params: dict[str, Any] = {"q": code, "page": 1}
        if zone and zone in ZONES:
            params["movie_type"] = ZONES[zone]
        data = await self._request("GET", "/api/v2/search", params)
        if not data:
            return None
        movies = (data.get("movies") or []) if isinstance(data, dict) else []
        if not movies:
            return None
        cu = code.upper().replace("-", "")
        best = None
        for m in movies:
            num = (m.get("number") or "").upper().replace("-", "")
            if num == cu:
                best = m
                break
        if best is None:
            best = movies[0]
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

    async def get_magnets(self, movie_id: str) -> list[JavDBAppMagnet]:
        """按 App movie id 取磁力列表。"""
        if not movie_id:
            return []
        data = await self._request("GET", f"/api/v1/movies/{movie_id}/magnets")
        if not data:
            return []
        raw_list = data.get("magnets") or []
        return [_parse_magnet(r) for r in raw_list if isinstance(r, dict)]

    async def get_movie_detail(self, movie_id: str) -> Optional[dict]:
        """取电影详情（/api/v4/movies/{id}）。"""
        if not movie_id:
            return None
        return await self._request("GET", f"/api/v4/movies/{movie_id}")

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None


async def create_app_client_from_config() -> JavDBAppClient:
    """从 MDCX 配置创建匿名客户端（仅取代理，无需登录）。"""
    proxy = None
    try:
        from app.config.manager import get_config
        config = get_config()
        if config.proxy.enabled and config.proxy.address:
            proxy = f"http://{config.proxy.address}:{config.proxy.port}"
    except Exception:  # noqa: BLE001
        log.debug("create_app_client_from_config: 读取代理配置失败，使用直连")
    return JavDBAppClient(proxy=proxy)


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
