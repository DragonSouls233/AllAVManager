"""WebDAV 服务端实现

将本地媒体库以 WebDAV 文件系统形式暴露给外部客户端（Windows 资源管理器、
macOS Finder、Linux davfs2、Infuse、VLC 等）。

参考 mdc-ng / MediaStationGo / nexus-media 的 WebDAV 服务端方案。

支持的核心 WebDAV 方法：
- OPTIONS: 返回 DAV 能力
- PROPFIND: 列出目录内容 / 返回文件属性（XML multistatus）
- GET: 流式下载/播放（支持 Range）
- HEAD: 文件元数据
- PUT: 上传文件（可选）

虚拟目录布局（由配置 webdav_server.virtual_layout 决定）：
- flat:      /webdav/{code}.ext
- by_code:   /webdav/{letter}/{code}.ext  (letter = 番号首字母，0-9 合并为 "0-9")
- by_actor:  /webdav/{actor}/{code}.ext
- by_studio: /webdav/{studio}/{code}.ext
"""

import os
import re
import asyncio
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, quote

from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse, Response as FastResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_session
from app.db.models import Movie, MovieActor, Actor, Studio
from app.utils.logger import get_logger

logger = get_logger(__name__)

# WebDAV XML 命名空间
NS_DAV = "DAV:"

# 文件扩展名映射（用于构造虚拟文件名）
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".ts", ".flv", ".iso")


# ============== 工具函数 ==============

def _get_movie_ext(file_path: Optional[str]) -> str:
    """从影片文件路径提取扩展名（兜底 .mp4）"""
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext:
            return ext
    return ".mp4"


def _get_first_letter(code: str) -> str:
    """番号首字母分组（数字开头归为 0-9）"""
    if not code:
        return "0-9"
    first = code[0].upper()
    if first.isdigit():
        return "0-9"
    if first.isalpha():
        return first
    return "0-9"


def _format_http_date(dt: datetime) -> str:
    """格式化为 HTTP 日期（RFC 7231）"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _format_iso_date(dt: Optional[datetime]) -> str:
    """格式化为 ISO8601 日期（WebDAV lastmodified）"""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_basic_auth(authorization: Optional[str], expected_user: str, expected_pass: str) -> bool:
    """验证 HTTP Basic Auth"""
    if not expected_user:
        # 未配置用户名则放行（依赖外层 JWT 中间件）
        return True
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        user, _, pwd = decoded.partition(":")
        return user == expected_user and pwd == expected_pass
    except Exception:
        return False


# ============== 虚拟路径解析 ==============

async def _resolve_movie_by_path(
    path: str,
    layout: str,
    session: AsyncSession,
) -> Optional[Movie]:
    """将虚拟路径解析为 Movie 对象

    Args:
        path: 虚拟相对路径（如 "A/ABC-123.mp4"）
        layout: 虚拟目录布局
        session: 数据库会话

    Returns:
        Movie 对象或 None
    """
    # 提取文件名（去掉扩展名后即番号）
    filename = path.rstrip("/").split("/")[-1]
    if not filename:
        return None
    # 去掉扩展名
    code = os.path.splitext(filename)[0]
    if not code:
        return None

    # 直接按 code 精确匹配（虚拟目录结构只影响展示，文件名仍是 {code}.ext）
    result = await session.execute(
        select(Movie).where(Movie.code == code).limit(1)
    )
    return result.scalars().first()


async def _list_virtual_dir(
    rel_path: str,
    layout: str,
    session: AsyncSession,
) -> list[dict]:
    """列出虚拟目录下的内容

    Args:
        rel_path: 相对路径（如 "" = 根, "A" = A 目录, "演员名" 等）
        layout: 虚拟目录布局
        session: 数据库会话

    Returns:
        条目列表 [{"name", "is_dir", "size", "movie_id", "code", "title", "modified"}]
    """
    rel_path = rel_path.strip("/")
    # 只查询有文件路径的影片
    base_query = select(Movie).where(Movie.file_path.is_not(None))

    if layout == "flat":
        # 扁平布局：根目录直接列出所有影片文件
        if rel_path:
            return []  # 扁平布局没有子目录
        result = await session.execute(base_query.order_by(Movie.code))
        movies = result.scalars().all()
        return [
            {
                "name": f"{m.code}{_get_movie_ext(m.file_path)}",
                "is_dir": False,
                "size": m.file_size or 0,
                "movie_id": m.id,
                "code": m.code,
                "title": m.title or "",
                "modified": m.updated_at if hasattr(m, "updated_at") else None,
                "file_path": m.file_path,
            }
            for m in movies
        ]

    elif layout == "by_code":
        # 按番号首字母分组
        if not rel_path:
            # 根目录：列出所有字母分组（仅返回有影片的字母）
            result = await session.execute(
                base_query.with_only_columns(Movie.code).order_by(Movie.code)
            )
            letters = set()
            for (code,) in result.fetchall():
                letters.add(_get_first_letter(code))
            return [
                {"name": letter, "is_dir": True, "count": 0}
                for letter in sorted(letters)
            ]
        else:
            # 子目录：列出该字母下的所有影片
            # rel_path 应该是字母（如 "A" 或 "0-9"）
            letter = rel_path.split("/")[0]
            result = await session.execute(
                base_query.order_by(Movie.code)
            )
            movies = result.scalars().all()
            filtered = [m for m in movies if _get_first_letter(m.code) == letter]
            return [
                {
                    "name": f"{m.code}{_get_movie_ext(m.file_path)}",
                    "is_dir": False,
                    "size": m.file_size or 0,
                    "movie_id": m.id,
                    "code": m.code,
                    "title": m.title or "",
                    "modified": m.updated_at if hasattr(m, "updated_at") else None,
                    "file_path": m.file_path,
                }
                for m in filtered
            ]

    elif layout == "by_actor":
        # 按演员分组
        if not rel_path:
            # 根目录：列出所有演员名（仅返回有影片的演员）
            result = await session.execute(
                select(Actor.name)
                .join(MovieActor, Actor.id == MovieActor.actor_id)
                .join(Movie, Movie.id == MovieActor.movie_id)
                .where(Movie.file_path.is_not(None))
                .distinct()
                .order_by(Actor.name)
            )
            return [
                {"name": name, "is_dir": True, "count": 0}
                for (name,) in result.fetchall() if name
            ]
        else:
            # 子目录：列出该演员的所有影片
            actor_name = rel_path.split("/")[0]
            result = await session.execute(
                select(Movie)
                .join(MovieActor, Movie.id == MovieActor.movie_id)
                .join(Actor, Actor.id == MovieActor.actor_id)
                .where(Movie.file_path.is_not(None))
                .where(Actor.name == actor_name)
                .order_by(Movie.code)
            )
            movies = result.scalars().all()
            return [
                {
                    "name": f"{m.code}{_get_movie_ext(m.file_path)}",
                    "is_dir": False,
                    "size": m.file_size or 0,
                    "movie_id": m.id,
                    "code": m.code,
                    "title": m.title or "",
                    "modified": m.updated_at if hasattr(m, "updated_at") else None,
                    "file_path": m.file_path,
                }
                for m in movies
            ]

    elif layout == "by_studio":
        # 按厂商分组
        if not rel_path:
            # 根目录：列出所有厂商名
            result = await session.execute(
                select(Movie.maker)
                .where(Movie.file_path.is_not(None))
                .where(Movie.maker.is_not(None))
                .distinct()
                .order_by(Movie.maker)
            )
            return [
                {"name": name, "is_dir": True, "count": 0}
                for (name,) in result.fetchall() if name
            ]
        else:
            studio_name = rel_path.split("/")[0]
            result = await session.execute(
                base_query.where(Movie.maker == studio_name).order_by(Movie.code)
            )
            movies = result.scalars().all()
            return [
                {
                    "name": f"{m.code}{_get_movie_ext(m.file_path)}",
                    "is_dir": False,
                    "size": m.file_size or 0,
                    "movie_id": m.id,
                    "code": m.code,
                    "title": m.title or "",
                    "modified": m.updated_at if hasattr(m, "updated_at") else None,
                    "file_path": m.file_path,
                }
                for m in movies
            ]

    return []


# ============== WebDAV 协议响应构建 ==============

def _build_propfind_response(
    href: str,
    items: list[dict],
    include_content: bool = True,
) -> str:
    """构建 PROPFIND multistatus XML 响应

    Args:
        href: 请求的根 href（如 "/webdav/A/"）
        items: 目录条目列表
        include_content: 是否包含文件内容属性（size/content-type）

    Returns:
        XML 字符串
    """
    # 使用 ElementTree 构建 XML（避免命名空间前缀问题，手动构建）
    parts = ['<?xml version="1.0" encoding="utf-8"?>']
    parts.append('<D:multistatus xmlns:D="DAV:">')

    # 当前目录自身（self entry）
    parts.append('<D:response>')
    parts.append(f'<D:href>{_xml_escape(href)}</D:href>')
    parts.append('<D:propstat>')
    parts.append('<D:prop>')
    parts.append('<D:resourcetype><D:collection/></D:resourcetype>')
    parts.append(f'<D:displayname>{_xml_escape(href.rstrip("/").split("/")[-1] or "root")}</D:displayname>')
    parts.append('</D:prop>')
    parts.append('<D:status>HTTP/1.1 200 OK</D:status>')
    parts.append('</D:propstat>')
    parts.append('</D:response>')

    # 子条目
    base = href.rstrip("/") + "/"
    for item in items:
        item_href = base + quote(item["name"])
        parts.append('<D:response>')
        parts.append(f'<D:href>{_xml_escape(item_href)}</D:href>')
        parts.append('<D:propstat>')
        parts.append('<D:prop>')
        if item.get("is_dir"):
            parts.append('<D:resourcetype><D:collection/></D:resourcetype>')
        else:
            parts.append('<D:resourcetype/>')
            if include_content:
                parts.append(f'<D:getcontentlength>{item.get("size", 0)}</D:getcontentlength>')
                ext = os.path.splitext(item["name"])[1].lower().lstrip(".")
                mime = _get_mime_type(ext)
                parts.append(f'<D:getcontenttype>{mime}</D:getcontenttype>')
        parts.append(f'<D:displayname>{_xml_escape(item["name"])}</D:displayname>')
        modified = item.get("modified")
        if modified:
            parts.append(f'<D:getlastmodified>{_format_http_date(modified)}</D:getlastmodified>')
        parts.append('</D:prop>')
        parts.append('<D:status>HTTP/1.1 200 OK</D:status>')
        parts.append('</D:propstat>')
        parts.append('</D:response>')

    parts.append('</D:multistatus>')
    return "".join(parts)


def _build_single_file_propfind_response(
    href: str,
    movie: Movie,
    file_path: str,
    file_size: int,
) -> str:
    """构建单个文件的 PROPFIND 响应"""
    try:
        stat = os.stat(file_path)
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        size = file_size or stat.st_size
    except OSError:
        modified = None
        size = file_size or 0

    parts = ['<?xml version="1.0" encoding="utf-8"?>']
    parts.append('<D:multistatus xmlns:D="DAV:">')
    parts.append('<D:response>')
    parts.append(f'<D:href>{_xml_escape(href)}</D:href>')
    parts.append('<D:propstat>')
    parts.append('<D:prop>')
    parts.append('<D:resourcetype/>')
    parts.append(f'<D:getcontentlength>{size}</D:getcontentlength>')
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    parts.append(f'<D:getcontenttype>{_get_mime_type(ext)}</D:getcontenttype>')
    if modified:
        parts.append(f'<D:getlastmodified>{_format_http_date(modified)}</D:getlastmodified>')
    parts.append(f'<D:displayname>{_xml_escape(os.path.basename(file_path))}</D:displayname>')
    parts.append('</D:prop>')
    parts.append('<D:status>HTTP/1.1 200 OK</D:status>')
    parts.append('</D:propstat>')
    parts.append('</D:response>')
    parts.append('</D:multistatus>')
    return "".join(parts)


def _xml_escape(text: str) -> str:
    """XML 字符转义"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _get_mime_type(ext: str) -> str:
    """根据扩展名返回 MIME 类型"""
    mime_map = {
        "mp4": "video/mp4",
        "mkv": "video/x-matroska",
        "avi": "video/x-msvideo",
        "wmv": "video/x-ms-wmv",
        "mov": "video/quicktime",
        "m4v": "video/x-m4v",
        "ts": "video/mp2t",
        "flv": "video/x-flv",
        "iso": "application/octet-stream",
    }
    return mime_map.get(ext.lower(), "application/octet-stream")


# ============== FastAPI 路由 ==============

router = APIRouter()


@router.api_route("/{path:path}", methods=["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "DELETE", "MKCOL", "MOVE", "COPY"])
async def webdav_handler(
    request: Request,
    path: str,
    session: AsyncSession = Depends(get_session),
):
    """WebDAV 主处理器

    所有 WebDAV 方法集中处理，根据方法分发到对应的处理函数。
    路径参数 path 已经过 URL 解码（FastAPI 自动处理）。
    """
    cfg = get_config().webdav_server
    if not cfg.enabled:
        raise HTTPException(status_code=404, detail="WebDAV 服务端未启用")

    # Basic Auth 验证（如配置了用户名密码）
    auth_header = request.headers.get("Authorization")
    if not _check_basic_auth(auth_header, cfg.username or "", cfg.password or ""):
        return FastResponse(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="MDCX WebDAV"'},
            content="Unauthorized",
        )

    method = request.method
    rel_path = unquote(path).strip("/")

    # 构造完整的 href（用于 PROPFIND 响应）
    mount_path = cfg.mount_path.rstrip("/")
    full_href = f"{mount_path}/{rel_path}" if rel_path else f"{mount_path}/"
    if not full_href.endswith("/"):
        # 目录请求通常带尾斜杠
        pass

    if method == "OPTIONS":
        return _handle_options()

    if method == "PROPFIND":
        return await _handle_propfind(request, rel_path, full_href, cfg.virtual_layout, session)

    if method in ("GET", "HEAD"):
        return await _handle_get_head(request, method, rel_path, cfg.virtual_layout, session)

    if method == "PUT":
        return await _handle_put(request, rel_path, session)

    # MKCOL / DELETE / MOVE / COPY 暂不支持（媒体库为只读虚拟视图）
    if method in ("MKCOL", "DELETE", "MOVE", "COPY"):
        return FastResponse(status_code=403, content="媒体库为只读视图，不支持修改操作")

    raise HTTPException(status_code=405, detail=f"Method {method} not allowed")


# ============== 方法处理器 ==============

def _handle_options() -> FastResponse:
    """OPTIONS: 返回 DAV 能力"""
    return FastResponse(
        headers={
            "DAV": "1, 2",
            "Allow": "OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE, MKCOL, MOVE, COPY",
            "MS-Author-Via": "DAV",
            "Content-Length": "0",
        },
        status_code=200,
    )


async def _handle_propfind(
    request: Request,
    rel_path: str,
    full_href: str,
    layout: str,
    session: AsyncSession,
) -> FastResponse:
    """PROPFIND: 列出目录或返回文件属性"""
    # 判断是文件还是目录：尝试解析为影片
    movie = await _resolve_movie_by_path(rel_path, layout, session)
    if movie and movie.file_path:
        # 单个文件
        # 确保 href 不以 / 结尾
        href = full_href.rstrip("/")
        xml = _build_single_file_propfind_response(
            href, movie, movie.file_path, movie.file_size or 0
        )
        return FastResponse(
            content=xml,
            media_type="application/xml; charset=utf-8",
            status_code=207,
        )

    # 目录：列出内容
    items = await _list_virtual_dir(rel_path, layout, session)
    # 确保 href 以 / 结尾（目录）
    href = full_href if full_href.endswith("/") else full_href + "/"
    xml = _build_propfind_response(href, items)
    return FastResponse(
        content=xml,
        media_type="application/xml; charset=utf-8",
        status_code=207,
    )


async def _handle_get_head(
    request: Request,
    method: str,
    rel_path: str,
    layout: str,
    session: AsyncSession,
) -> FastResponse:
    """GET/HEAD: 流式返回文件内容（支持 Range）"""
    movie = await _resolve_movie_by_path(rel_path, layout, session)
    if not movie or not movie.file_path:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = movie.file_path
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"文件不存在于磁盘: {file_path}")

    try:
        file_size = os.path.getsize(file_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"无法读取文件: {e}")

    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    mime = _get_mime_type(ext)

    # 处理 Range 请求（视频播放器常用）
    range_header = request.headers.get("Range")
    if range_header and range_header.startswith("bytes="):
        try:
            range_spec = range_header[6:].split(",")[0].strip()
            start_str, _, end_str = range_spec.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                return FastResponse(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"},
                )
            content_length = end - start + 1

            if method == "HEAD":
                return FastResponse(
                    headers={
                        "Content-Length": str(content_length),
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Content-Type": mime,
                        "Accept-Ranges": "bytes",
                    },
                    status_code=206,
                )

            async def file_stream():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length
                    chunk_size = 1024 * 1024  # 1MB
                    while remaining > 0:
                        to_read = min(chunk_size, remaining)
                        data = f.read(to_read)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                file_stream(),
                status_code=206,
                headers={
                    "Content-Length": str(content_length),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Type": mime,
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-cache",
                },
            )
        except ValueError:
            pass  # Range 解析失败，回退到完整下载

    # 完整文件下载
    if method == "HEAD":
        return FastResponse(
            headers={
                "Content-Length": str(file_size),
                "Content-Type": mime,
                "Accept-Ranges": "bytes",
            },
            status_code=200,
        )

    return FileResponse(
        file_path,
        media_type=mime,
        filename=os.path.basename(file_path),
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        },
    )


async def _handle_put(
    request: Request,
    rel_path: str,
    session: AsyncSession,
) -> FastResponse:
    """PUT: 上传文件到媒体目录（简化实现）

    将上传的文件保存到配置的第一个媒体目录中。
    注意：此操作不会自动创建 Movie 记录，需要后续通过扫描器识别。
    """
    cfg = get_config()
    media_dirs = cfg.scraper.media_dirs or []
    if not media_dirs:
        return FastResponse(status_code=403, content="未配置媒体目录，无法上传")

    # 提取文件名
    filename = rel_path.split("/")[-1] if rel_path else ""
    if not filename:
        return FastResponse(status_code=400, content="未指定文件名")

    # 安全检查：防止路径穿越
    if "/" in filename or "\\" in filename or ".." in filename:
        return FastResponse(status_code=400, content="非法文件名")

    target_dir = Path(media_dirs[0])
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    # 写入文件
    try:
        body = await request.body()
        with open(target_path, "wb") as f:
            f.write(body)
        logger.info(f"WebDAV PUT 上传文件: {target_path} ({len(body)} bytes)")
        return FastResponse(status_code=201, content="Created")
    except Exception as e:
        logger.error(f"WebDAV PUT 失败: {e}")
        return FastResponse(status_code=500, content=str(e))


__all__ = ["router"]
