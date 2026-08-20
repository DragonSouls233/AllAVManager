"""JavDB 以图搜番模块 — 移植自 javdb-cli v0.7.2（reversesearch）。

来源：github.com/FlanChanXwO/javdb-cli v0.7.2
  sdk/reversesearch.go
  internal/reversesearch/provider/provider.go   ← AVScan 上传协议
  internal/reversesearch/image/                  ← 图片 magic 校验

功能：
  1. 上传原始图片字节到内置 AVScan provider（https://avscan.cc/search），
     返回规范化候选（video_code + best_similarity + frames）。
  2. 可选联动：对每个候选做严格番号精确解析（zone=all、大小写不敏感、
     去连字符），再取 JavDB 完整详情（复用 JavDBAppClient）。

协议要点（与 v0.7.2 核对一致）：
  - multipart 字段名固定为 file，builtin filename=f.jpg；
  - 上传原始字节不转码；part 内联 Content-Type 按真实 magic 声明；
  - 仅支持 JPEG/PNG/WEBP，最大 8 MiB；
  - 响应统一协议：{"results":[{"video_code","best_similarity","frames":[
    {"image_name","similarity","timestamp","thumbnail_url"}]}]}
  - timestamp / thumbnail_url 缺失时按 image_name 派生。

用法：
    from app.services.javdb_reverse_search import search_by_image
    result = await search_by_image(image_bytes)
    for match in result.matches:
        print(match.candidate.video_code, match.movie_id, match.movie)
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

BUILTIN_NAME = "builtin"
BUILTIN_URL = "https://avscan.cc/search"
BUILTIN_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MiB

# 图片 magic 检测
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_MAGIC = b"RIFF"


def detect_image_format(raw: bytes) -> Optional[str]:
    """返回 'jpeg' / 'png' / 'webp'；无法识别返回 None。"""
    if raw.startswith(_JPEG_MAGIC):
        return "jpeg"
    if raw.startswith(_PNG_MAGIC):
        return "png"
    if len(raw) >= 12 and raw.startswith(_WEBP_MAGIC) and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _part_content_type(fmt: str) -> str:
    return {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        fmt, "application/octet-stream"
    )


@dataclass
class ReverseSearchFrame:
    image_name: str = ""
    similarity: float = 0.0
    timestamp: str = ""
    thumbnail_url: str = ""


@dataclass
class ReverseSearchCandidate:
    video_code: str = ""
    similarity: float = 0.0
    frames: list[ReverseSearchFrame] = field(default_factory=list)


@dataclass
class ReverseSearchResponse:
    source: str = "builtin"
    candidates: list[ReverseSearchCandidate] = field(default_factory=list)


@dataclass
class ImageSearchMatch:
    candidate: ReverseSearchCandidate
    movie_id: str = ""
    movie: Optional[dict] = None
    error: Optional[str] = None


@dataclass
class ImageSearchResult:
    reverse_search: ReverseSearchResponse
    matches: list[ImageSearchMatch] = field(default_factory=list)


# --- AVScan 上传 ---------------------------------------------------------------

async def reverse_search(
    image_bytes: bytes,
    proxy: Optional[str] = None,
    timeout: float = 60.0,
    retries: int = 3,
    retry_wait: float = 30.0,
    filename: str = "f.jpg",
    endpoint: str = BUILTIN_URL,
) -> ReverseSearchResponse:
    """上传原始图片到 AVScan，返回规范化候选。

    校验：非空、≤8 MiB、JPEG/PNG/WEBP。失败抛异常。
    """
    if not image_bytes:
        raise ValueError("reverse search image bytes are empty")
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise ValueError("reverse search image exceeds the 8 MiB limit")
    fmt = detect_image_format(image_bytes)
    if fmt is None:
        raise ValueError("reverse search image is not JPEG, PNG or WEBP")

    body, content_type = _build_multipart(image_bytes, filename, fmt)
    last: Optional[Exception] = None
    async with httpx.AsyncClient(
        timeout=timeout,
        proxy=proxy,
        follow_redirects=True,
        headers={"User-Agent": BUILTIN_USER_AGENT},
    ) as client:
        for attempt in range(1, retries + 1):
            try:
                r = await client.post(endpoint, content=body, headers={"Content-Type": content_type})
            except httpx.HTTPError as e:
                last = e
                if attempt < retries:
                    await asyncio.sleep(retry_wait * attempt)
                continue
            if r.status_code == 429:
                last = RuntimeError("AVScan returned HTTP 429 (rate limited)")
                if attempt < retries:
                    await asyncio.sleep(retry_wait * attempt)
                continue
            if r.status_code < 200 or r.status_code > 299:
                raise RuntimeError(f"AVScan returned HTTP {r.status_code}")
            return _decode_response(r.json(), source="builtin")
    raise RuntimeError(f"AVScan search failed: {last}")


def _build_multipart(raw: bytes, filename: str, fmt: str) -> tuple[bytes, str]:
    """构建固定字段 file 的 multipart body（内联 Content-Type 按 magic 声明）。"""
    boundary = "----MDCX-AVScan"
    disposition = (
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'
    )
    body = (
        f"--{boundary}\r\n{disposition}\r\n"
        f"Content-Type: {_part_content_type(fmt)}\r\n\r\n"
    ).encode("utf-8") + raw + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def _decode_response(payload: dict, source: str) -> ReverseSearchResponse:
    response = ReverseSearchResponse(source=source)
    results = payload.get("results") or []
    if not isinstance(results, list):
        return response
    for item in results:
        if not isinstance(item, dict):
            continue
        code = str(item.get("video_code") or "").strip()
        if not code:
            raise ValueError("AVScan response contains an empty video_code")
        candidate = ReverseSearchCandidate(
            video_code=code,
            similarity=float(item.get("best_similarity") or 0.0),
        )
        for f in item.get("frames") or []:
            if not isinstance(f, dict):
                continue
            frame = ReverseSearchFrame(
                image_name=str(f.get("image_name") or ""),
                similarity=float(f.get("similarity") or 0.0),
                timestamp=str(f.get("timestamp") or ""),
                thumbnail_url=str(f.get("thumbnail_url") or ""),
            )
            _derive_frame_fields(frame, code)
            candidate.frames.append(frame)
        response.candidates.append(candidate)
    return response


_TIMESTAMP_PATTERN = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")


def _derive_frame_fields(frame: ReverseSearchFrame, video_code: str) -> None:
    """按 AVScan 命名规则从 image_name 派生 timestamp / thumbnail_url（缺失时）。"""
    base = frame.image_name
    if "/" in base:
        base = base.rsplit("/", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    if not frame.timestamp and "_" in base:
        suffix = base.rsplit("_", 1)[-1].replace("-", ":")
        if _TIMESTAMP_PATTERN.match(suffix):
            frame.timestamp = suffix
    if not frame.thumbnail_url and base:
        frame.thumbnail_url = (
            f"https://avscan.cc/thumb/{video_code}/{base}.webp"
        )


# --- 联动：候选 → JavDB 详情 ----------------------------------------------------

async def search_by_image(
    image_bytes: bytes,
    *,
    proxy: Optional[str] = None,
    skip_movie_detail: bool = False,
    max_candidates: int = 8,
    reverse_timeout: float = 60.0,
    app_client: Optional[Any] = None,
) -> ImageSearchResult:
    """反搜并对全部候选并发执行严格番号解析 +（可选）完整详情。

    通过 app_client（JavDBAppClient）联动 JavDB；未传入时延迟创建
    （构造参数与 create_app_client_from_config 一致，带项目代理）。
    结果按 provider 原始顺序恢复；候选级失败写入 match.error 并继续。
    """
    response = await reverse_search(image_bytes, proxy=proxy, timeout=reverse_timeout)
    result = ImageSearchResult(reverse_search=response)
    candidates = response.candidates[:max_candidates]
    if not candidates:
        return result

    if app_client is None:
        from app.services.javdb_app_client import create_app_client_from_config

        app_client = await create_app_client_from_config()

    matches: list[ImageSearchMatch] = [None] * len(candidates)  # type: ignore[list-item]

    async def _link(index: int, candidate: ReverseSearchCandidate) -> None:
        match = ImageSearchMatch(candidate=candidate)
        try:
            movie_id = await app_client.search_movie_exact(candidate.video_code)
            if not movie_id:
                match.error = f"exact number resolve failed: {candidate.video_code}"
            else:
                match.movie_id = movie_id
                if not skip_movie_detail:
                    match.movie = await app_client.get_movie_detail(movie_id)
        except Exception as e:  # noqa: BLE001
            match.error = str(e)
        matches[index] = match

    await asyncio.gather(
        *[_link(i, c) for i, c in enumerate(candidates)]
    )
    result.matches = [m for m in matches if m is not None]
    return result


__all__ = [
    "ImageSearchMatch",
    "ImageSearchResult",
    "ReverseSearchCandidate",
    "ReverseSearchFrame",
    "ReverseSearchResponse",
    "detect_image_format",
    "reverse_search",
    "search_by_image",
]
