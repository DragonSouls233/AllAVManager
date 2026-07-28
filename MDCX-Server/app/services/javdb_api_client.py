"""JavDB App JSON API 客户端。

使用 jdsignature HMAC-SHA256 认证，绕过 Cloudflare 保护。
支持 jdsignature 自动签名、会话管理、token 自动续期。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from app.config.manager import get_config

log = logging.getLogger(__name__)

_JAVDB_API_BASE = "https://api.javdb.com"
_JAVDB_CDN_BASE = "https://c0.jdbstatic.com/covers"
_JAVDB_REFERER = "https://javdb.com/"


@dataclass
class JavDBMovie:
    id: str
    code: str
    title: str
    title_cn: str = ""
    date: str = ""
    duration: int = 0
    director: str = ""
    maker: str = ""
    publisher: str = ""
    series: str = ""
    score: float = 0.0
    genres: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    cover_url: str = ""
    fanart_url: str = ""
    screenshots: list[str] = field(default_factory=list)
    magnet_links: list[dict] = field(default_factory=list)


class JavDBClient:
    """JavDB App JSON API 客户端。"""

    def __init__(self, username: str = "", password: str = "",
                 session_token: str = "", proxy: Optional[str] = None,
                 timeout: float = 30.0):
        self._username = username
        self._password = password
        self._session_token: Optional[str] = session_token or None
        self._timeout = timeout
        self._proxy = proxy
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                proxy=self._proxy,
                headers={
                    "User-Agent": "JavDB/4.3.4 (Android; 14; SDK 34)",
                    "Accept": "application/json",
                    "Accept-Language": "zh-CN",
                },
            )
        return self._http

    def _make_signature(self, method: str, path: str, body: str = "") -> str:
        token = self._session_token
        if not token:
            return ""
        data = method.upper() + path + body
        sig = hmac.new(
            token.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        middle = token[:16]
        suffix = token[-16:]
        signature = base64.b64encode(sig).decode("utf-8")
        return f"JV1.{middle}.{signature}.{suffix}"

    async def request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        client = await self._get_client()
        url = urljoin(_JAVDB_API_BASE, path)
        body = kwargs.get("content", "") or json.dumps(kwargs.get("json", {})) or ""
        body_encoded = body if isinstance(body, str) else body.decode("utf-8", errors="replace")

        headers = dict(kwargs.pop("headers", {}))
        sig = self._make_signature(method, path, body_encoded)
        if sig:
            headers["X-Javdb-Signature"] = sig
        if self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"

        try:
            r = await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            log.warning("JavDB API request failed: %s %s: %s", method, path, e)
            return None

        if r.status_code == 401:
            log.warning("JavDB API auth expired, attempting re-login")
            if await self._login():
                return await self.request(method, path, headers=headers, **kwargs)
            return None

        if r.status_code != 200:
            log.warning("JavDB API error: %s %s -> %s", method, path, r.status_code)
            return None

        try:
            return r.json()
        except json.JSONDecodeError:
            log.warning("JavDB API response not JSON: %s", r.text[:200])
            return None

    async def _login(self) -> bool:
        if not self._username or not self._password:
            log.warning("JavDB login skipped: no username/password configured")
            return False
        data = {"user": {"username": self._username, "password": self._password}}
        result = await self.request("POST", "/api/v1/login/sessions", json=data)
        if result and "session_token" in result:
            self._session_token = result["session_token"]
            log.info("JavDB login successful")
            return True
        log.warning("JavDB login failed")
        return False

    async def search_movie(self, code: str) -> Optional[JavDBMovie]:
        path = f"/api/v1/search/movies?q={code}&page=1"
        result = await self.request("GET", path)
        if not result:
            return None
        movies = (result.get("data") or {}).get("movies") or []
        if not movies:
            return None
        best = None
        code_upper = code.upper().replace("-", "")
        for m in movies:
            movie_code = (m.get("code") or "").upper().replace("-", "")
            if movie_code == code_upper:
                best = m
                break
        if not best and movies:
            best = movies[0]
        if not best:
            return None
        return await self.get_movie(best["id"])

    async def get_movie(self, movie_id: str) -> Optional[JavDBMovie]:
        path = f"/api/v1/movies/{movie_id}"
        result = await self.request("GET", path)
        if not result:
            return None
        data = result.get("data") or {}
        movie = data.get("movie") or {}
        return JavDBMovie(
            id=movie_id,
            code=movie.get("code") or "",
            title=movie.get("title") or "",
            title_cn=movie.get("title_cn") or "",
            date=movie.get("date") or "",
            duration=movie.get("duration") or 0,
            director=movie.get("director") or "",
            maker=movie.get("maker") or "",
            publisher=movie.get("publisher") or "",
            series=movie.get("series") or "",
            score=movie.get("score") or 0.0,
            genres=[g.get("name", "") for g in (movie.get("genres") or [])],
            actors=[a.get("name", "") for a in (movie.get("actors") or [])],
            cover_url=movie.get("cover_url") or "",
            fanart_url=movie.get("fanart_url") or "",
            screenshots=[s.get("url", "") for s in (movie.get("screenshots") or [])],
            magnet_links=(movie.get("magnet_links") or []),
        )

    async def get_actor(self, actor_id: str) -> Optional[dict]:
        path = f"/api/v1/actors/{actor_id}"
        return await self.request("GET", path)

    def get_cover_url(self, javdb_id: str) -> str:
        prefix = javdb_id[:2].lower()
        return f"{_JAVDB_CDN_BASE}/{prefix}/{javdb_id}.jpg"

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None


async def create_client_from_config() -> JavDBClient:
    """从 MDCX 配置创建 JavDB 客户端。"""
    config = get_config()
    cookie = (config.crawler.javdb_cookie or "").strip()
    proxy = None
    if config.proxy.enabled and config.proxy.address:
        proxy = f"http://{config.proxy.address}:{config.proxy.port}"
    return JavDBClient(session_token=cookie, proxy=proxy)
