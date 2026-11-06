"""本地图片响应的条件缓存中间件（解决「换封面/换头像后不刷新」）。

背景（2026-11-06 实测确认）
---------------------------
我方所有封面/头像端点都用固定 URL（如 ``/api/v1/jav/movies/7/cover/file``），
且统一写了 ``Cache-Control: public, max-age=86400``：

* ``FileResponse`` 在完整 ASGI 调用时**会**自动带 ``ETag`` / ``Last-Modified``
  （Starlette ``set_stat_headers`` 基于 ``st_mtime`` + ``st_size``），
  所以文件换了 ETag 确实会变；
* 但 ``max-age=86400`` 让浏览器在 24 小时内**根本不会发出校验请求**，
  换图后用户最长要等一天才能看到新图；
* 而 Starlette 的 ``FileResponse.__call__`` **不处理** ``If-None-Match``：
  即便把响应改成 ``no-cache``，每次请求也都会返回 200 + 全量图片，
  封面墙一次几百张图会明显变慢。

本中间件（纯 ASGI，一处注册全局生效）：

1. 对 ``200 + Content-Type: image/* + 带 ETag`` 的本地图片响应，
   把 ``max-age=86400`` 改写为 ``no-cache``（强制每次校验，但仍允许缓存）；
2. 补上 Starlette 缺失的条件请求处理：请求带 ``If-None-Match`` 且匹配 ETag
   （或带 ``If-Modified-Since`` 且未过期）时改判 ``304 Not Modified``，
   移除 body 相关头并丢弃响应体，省掉重复传输；
3. 文件被替换后 ETag 变化 ⇒ 条件不匹配 ⇒ 返回 200 + 新图，换图立即生效。

设计约束
--------
* **零业务代码改动**：不碰 39 处 ``FileResponse`` 调用点，也不需要前端给
  URL 拼 ``?t=``/``?v=`` 参数（``src/utils/media.js`` 已记录该做法会因
  反斜杠 + 中文路径被反向代理错误转发导致 404，属于历史坑，勿重踩）。
* **最小影响面**：只处理带 ETag 的图片响应。JSON / 视频流 / 无 ETag 的
  内存图片（如 ``Response(content=...)`` 的代理封面、SVG 占位图）全部原样透传；
  非 200（含各内层中间件自己产生的 304）同样透传。
* 支持 ``If-None-Match: *``、弱校验 ``W/"..."``、逗号分隔多值；
  按 RFC 9110，存在 ``If-None-Match`` 时优先于 ``If-Modified-Since``。
* 兼容 Starlette 1.6 的 ``http.response.pathsend`` 零拷贝消息。
"""

from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

#: 需要改写的长缓存标记。只改这一类，避免动到 no-store / 自定义策略的响应。
_LONG_CACHE_MARK = "max-age"

#: 304 响应不应携带的 body 相关头（RFC 9110 §15.4.5）。
_BODY_HEADERS = ("content-type", "content-length", "content-encoding", "content-range")


def _strip_weak(value: str) -> str:
    """去掉 ETag 的弱校验前缀 ``W/``，用于弱比较。"""
    v = value.strip()
    return v[2:].strip() if v[:2].upper() == "W/" else v


def _etag_matches(if_none_match: str | None, etag: str | None) -> bool:
    """判断 If-None-Match 是否命中当前 ETag（弱比较，支持 ``*`` 与多值）。"""
    if not if_none_match or not etag:
        return False
    target = _strip_weak(etag)
    for token in if_none_match.split(","):
        candidate = token.strip()
        if candidate == "*":
            return True
        if _strip_weak(candidate) == target:
            return True
    return False


def _not_modified_since(if_modified_since: str | None, last_modified: str | None) -> bool:
    """If-Modified-Since 弱校验：资源最后修改时间不晚于客户端持有的时间即 304。"""
    if not if_modified_since or not last_modified:
        return False
    try:
        since = parsedate_to_datetime(if_modified_since)
        modified = parsedate_to_datetime(last_modified)
        if since.tzinfo is None or modified.tzinfo is None:
            return False
        return modified <= since
    except (TypeError, ValueError, OverflowError):
        return False


class ImageRevalidationMiddleware:
    """纯 ASGI 中间件：让本地图片走「no-cache + ETag/304」条件缓存。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return

        inm: str | None = None
        ims: str | None = None
        for key, value in scope.get("headers", []):
            lower = key.lower()
            if lower == b"if-none-match" and inm is None:
                inm = value.decode("latin-1")
            elif lower == b"if-modified-since" and ims is None:
                ims = value.decode("latin-1")

        # 无校验头时无需拦截 304 分支，但仍要改写 Cache-Control。
        state = {"not_modified": False, "terminated": False}

        async def send_wrapper(message: Message) -> None:
            mtype = message["type"]

            if mtype == "http.response.start":
                headers = MutableHeaders(scope=message)
                content_type = (headers.get("content-type") or "").lower()
                etag = headers.get("etag")

                if message.get("status") == 200 and content_type.startswith("image/") and etag:
                    cache_control = headers.get("cache-control") or ""
                    if _LONG_CACHE_MARK in cache_control.lower():
                        # 24h 强缓存 ⇒ 每次校验（浏览器仍复用 304 缓存，不增带宽）
                        headers["cache-control"] = "no-cache"

                    matched = (
                        _etag_matches(inm, etag)
                        if inm
                        else _not_modified_since(ims, headers.get("last-modified"))
                    )
                    if matched:
                        message["status"] = 304
                        for name in _BODY_HEADERS:
                            if name in headers:
                                del headers[name]
                        state["not_modified"] = True

                await send(message)
                return

            if state["not_modified"] and mtype in ("http.response.body", "http.response.pathsend"):
                # 304 不带 body；把内层已发出的文件流丢弃，只补一个终止消息。
                if not state["terminated"]:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    state["terminated"] = True
                return

            await send(message)

        await self.app(scope, receive, send_wrapper)

        # HEAD / send_header_only 等不发 body 的响应，也要补终止消息避免挂起。
        if state["not_modified"] and not state["terminated"]:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
