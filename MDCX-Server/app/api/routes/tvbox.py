"""TVBox 开放接口路由（§7.10）

实现 TVBox 客户端可识别的开放接口规范，让 TVBox 客户端能直接接入 MDCX 媒体库。

参考：
- TVBoxOSC: https://github.com/CatVodTVOfficial/TVBoxOSC
- TVBox 配置文件规范（config.json）：sites / lives / rules / wallpaper
- TVBox XRoute 解析规则（type=1 走 JSON X selection，由本服务返回 JSON）

挂在 /tvbox 路径下，不走 /api/v1 前缀，不走 AuthMiddleware 认证。
通过 query 参数 token 进行简单鉴权（在 TvboxConfig.token 中配置）。

端点：
- GET /tvbox/config.json         返回 TVBox 配置（spider / sites / lives / rules）
- GET /tvbox/home.html           首页分类（class 列表）
- GET /tvbox/category.html       分类影片列表（分页）
- GET /tvbox/detail.html         影片详情（含播放源）
- GET /tvbox/search.html         搜索
- GET /tvbox/play.html           播放地址（直接返回 m3u8/MP4 URL）
- GET /tvbox/stream/{movie_id}   直接流式播放视频文件（公开端点）
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse, Response
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, PROJECT_ROOT
from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor, Studio, Series, FavoriteItem
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ============== 鉴权依赖 ==============

def _verify_token(token: Optional[str] = None) -> None:
    """简单 token 校验（query 参数 ?token=xxx）

    - 配置中 token 为空：放行（开放访问）
    - 配置中 token 非空：必须传入匹配的 token
    """
    cfg = get_config().tvbox
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="TVBox 接口未启用")
    if cfg.token and token != cfg.token:
        raise HTTPException(status_code=401, detail="Token 无效")


def _build_base_url(request: Request) -> str:
    """根据请求构造服务基础 URL"""
    cfg = get_config()
    server_host = getattr(cfg.server, "host", "127.0.0.1")
    server_port = getattr(cfg.server, "port", 8420)
    # 优先使用请求头中的 host，回退到配置
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        proto = request.headers.get("x-forwarded-proto", "http")
        return f"{proto}://{forwarded.split(',')[0].strip()}"
    if server_host in ("0.0.0.0", "127.0.0.1", "localhost"):
        return f"http://localhost:{server_port}"
    return f"http://{server_host}:{server_port}"


def _build_stream_url(movie_id: int, base_url: str) -> str:
    """构造流媒体播放 URL（指向 /tvbox/stream/{id}）"""
    cfg = get_config().tvbox
    sep = "&" if "?" in base_url else "?"
    # base_url 本身不带 token 参数，这里追加
    token_part = f"{sep}token={cfg.token}" if cfg.token else ""
    return f"{base_url}/tvbox/stream/{movie_id}{token_part}"


def _movie_to_list_item(movie: Movie, base_url: str) -> dict:
    """Movie -> TVBox 列表项（精简字段）"""
    # NSFW 隐藏模式下仅返回番号作为标题
    cfg = get_config().tvbox
    if cfg.nsfw_hidden:
        title = movie.code
    else:
        title = f"[{movie.code}] {movie.title}" if movie.title else movie.code
    return {
        "vod_id": str(movie.id),
        "vod_name": title,
        "vod_pic": movie.cover_url or movie.poster_url or "",
        "vod_remarks": movie.release_date or "",
    }


def _movie_to_detail_item(movie: Movie, base_url: str, session: AsyncSession) -> dict:
    """Movie -> TVBox 详情项（含播放源）

    注意：演员列表需在调用处异步查询后填充。
    """
    cfg = get_config().tvbox
    if cfg.nsfw_hidden:
        title = movie.code
        content = ""
    else:
        title = f"[{movie.code}] {movie.title}" if movie.title else movie.code
        content = movie.plot or movie.plot_short or ""

    play_url = _build_stream_url(movie.id, base_url)
    # TVBox 播放格式：播放源标识$播放URL（多个用 # 分隔）
    play_from = cfg.play_from
    vod_play_url = f"{play_from}${play_url}"

    return {
        "vod_id": str(movie.id),
        "vod_name": title,
        "vod_pic": movie.cover_url or movie.poster_url or "",
        "vod_content": content,
        "vod_remarks": movie.release_date or "",
        "vod_year": (movie.release_date[:4] if movie.release_date and len(movie.release_date) >= 4 else ""),
        "vod_area": "日本",
        "vod_type": "电影",
        "vod_play_from": play_from,
        "vod_play_url": vod_play_url,
    }


# ============== 通用查询构建 ==============

def _apply_category_filter(query, category: str):
    """根据 TVBox 分类 ID 应用筛选"""
    if category == "all" or not category:
        return query
    if category == "censored":
        # 有码
        return query.where(Movie.is_uncensored == False)  # noqa: E712
    if category == "uncensored":
        # 无码
        return query.where(Movie.is_uncensored == True)  # noqa: E712
    if category == "chinese":
        # 中文字幕
        return query.where(Movie.is_chinese == True)  # noqa: E712
    if category == "latest":
        # 最新（按发布日期降序）
        return query  # 排序在外部处理
    if category == "hot":
        # 热门（按播放次数降序）
        return query  # 排序在外部处理
    return query


def _apply_nsfw_filter(query, nsfw_hidden: bool):
    """NSFW 模式：仅展示已收藏的影片"""
    if not nsfw_hidden:
        return query
    fav_subq = select(FavoriteItem.entity_id).where(FavoriteItem.entity_type == "movie")
    return query.where(Movie.id.in_(fav_subq))


# ============== TVBox 端点 ==============

@router.get("/config.json")
async def tvbox_config(request: Request, token: Optional[str] = None):
    """TVBox 配置文件（客户端入口）

    返回 sites / lives / rules / wallpaper，TVBox 客户端首次加载时请求。
    """
    _verify_token(token)
    cfg = get_config().tvbox
    base_url = _build_base_url(request)
    token_part = f"?token={cfg.token}" if cfg.token else ""

    site_api = f"{base_url}/maccms/api.php/provide/vod{token_part}"
    # 从 VERSION.json 读取版本号
    _version = "2.4.0"
    try:
        vpath = PROJECT_ROOT / "VERSION.json"
        if vpath.exists():
            _version = json.loads(vpath.read_text(encoding="utf-8")).get("version", "2.4.0")
    except Exception:
        pass
    return {
        "sites": [
            {
                "key": "mdcx",
                "name": cfg.site_name,
                # type=1: JSON X selection（MacCMS 风格 API）
                "type": 1,
                "api": site_api,
                "searchable": 1,
                "quickSearch": 1,
                "filterable": 1,
                "ext": "",
            }
        ],
        "lives": [],
        "rules": [],
        "wallpaper": "",
        # 额外信息（TVBox 客户端会忽略未识别字段）
        "version": _version,
        "site_name": cfg.site_name,
        "home_url": f"{base_url}/tvbox/home.html{token_part}",
    }


@router.get("/home.html")
async def tvbox_home(request: Request, token: Optional[str] = None):
    """TVBox 首页分类列表

    返回 class 列表（type_id / type_name）。
    """
    _verify_token(token)
    return {
        "class": [
            {"type_id": "all", "type_name": "全部"},
            {"type_id": "censored", "type_name": "有码"},
            {"type_id": "uncensored", "type_name": "无码"},
            {"type_id": "chinese", "type_name": "中字"},
            {"type_id": "latest", "type_name": "最新"},
            {"type_id": "hot", "type_name": "热门"},
        ]
    }


@router.get("/category.html")
async def tvbox_category(
    request: Request,
    token: Optional[str] = None,
    t: str = Query("all", description="分类ID"),
    pg: int = Query(1, ge=1, description="页码"),
    session: AsyncSession = Depends(get_session),
):
    """TVBox 分类影片列表（分页）

    - t: 分类 ID（all/censored/uncensored/chinese/latest/hot）
    - pg: 页码
    """
    _verify_token(token)
    cfg = get_config().tvbox
    page_size = cfg.page_size
    base_url = _build_base_url(request)

    query = select(Movie).where(Movie.file_path.isnot(None))
    query = _apply_category_filter(query, t)
    query = _apply_nsfw_filter(query, cfg.nsfw_hidden)

    # 排序
    if t == "latest":
        query = query.order_by(Movie.release_date.desc().nulls_last(), Movie.id.desc())
    elif t == "hot":
        query = query.order_by(Movie.play_count.desc().nulls_last(), Movie.id.desc())
    else:
        query = query.order_by(Movie.id.desc())

    # 总数
    count_query = select(func.count(Movie.id)).where(Movie.file_path.isnot(None))
    count_query = _apply_category_filter(count_query, t)
    count_query = _apply_nsfw_filter(count_query, cfg.nsfw_hidden)
    total = await session.scalar(count_query) or 0

    # 分页
    query = query.offset((pg - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    movies = result.scalars().all()

    return {
        "list": [_movie_to_list_item(m, base_url) for m in movies],
        "page": pg,
        "pagecount": (total + page_size - 1) // page_size if page_size > 0 else 0,
        "limit": page_size,
        "total": total,
    }


@router.get("/detail.html")
async def tvbox_detail(
    request: Request,
    token: Optional[str] = None,
    code: str = Query(..., description="影片番号或 ID"),
    session: AsyncSession = Depends(get_session),
):
    """TVBox 影片详情

    - code: 可以是 movie.id 或 movie.code（番号）
    """
    _verify_token(token)
    base_url = _build_base_url(request)

    # 先按 ID 查，再按番号查
    movie = None
    if code.isdigit():
        movie = await session.get(Movie, int(code))
    if not movie:
        result = await session.execute(select(Movie).where(Movie.code == code).limit(1))
        movie = result.scalar_one_or_none()
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    item = _movie_to_detail_item(movie, base_url, session)

    # 演员列表（非 NSFW 隐藏模式才返回）
    cfg = get_config().tvbox
    if not cfg.nsfw_hidden:
        actor_result = await session.execute(
            select(Actor.name)
            .join(MovieActor, MovieActor.actor_id == Actor.id)
            .where(MovieActor.movie_id == movie.id)
            .limit(20)
        )
        actors = [r[0] for r in actor_result.fetchall()]
        item["vod_actor"] = ",".join(actors)

    return {"list": [item]}


@router.get("/search.html")
async def tvbox_search(
    request: Request,
    token: Optional[str] = None,
    wd: str = Query(..., description="搜索关键字"),
    pg: int = Query(1, ge=1, description="页码"),
    session: AsyncSession = Depends(get_session),
):
    """TVBox 搜索接口

    - wd: 搜索关键字（番号 / 标题）
    """
    _verify_token(token)
    cfg = get_config().tvbox
    page_size = cfg.page_size
    base_url = _build_base_url(request)

    kw = f"%{wd}%"
    query = (
        select(Movie)
        .where(
            Movie.file_path.isnot(None),
            or_(
                Movie.code.like(kw),
                Movie.title.like(kw),
                Movie.original_title.like(kw),
            ),
        )
    )
    query = _apply_nsfw_filter(query, cfg.nsfw_hidden)
    query = query.order_by(Movie.id.desc())

    count_query = (
        select(func.count(Movie.id))
        .where(
            Movie.file_path.isnot(None),
            or_(
                Movie.code.like(kw),
                Movie.title.like(kw),
                Movie.original_title.like(kw),
            ),
        )
    )
    count_query = _apply_nsfw_filter(count_query, cfg.nsfw_hidden)
    total = await session.scalar(count_query) or 0

    query = query.offset((pg - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    movies = result.scalars().all()

    return {
        "list": [_movie_to_list_item(m, base_url) for m in movies],
        "page": pg,
        "pagecount": (total + page_size - 1) // page_size if page_size > 0 else 0,
        "limit": page_size,
        "total": total,
    }


@router.get("/play.html")
async def tvbox_play(
    request: Request,
    token: Optional[str] = None,
    id: str = Query(..., description="影片 ID"),
    session: AsyncSession = Depends(get_session),
):
    """TVBox 播放地址

    返回 play 信息，TVBox 客户端可直接播放或交给解析器。
    """
    _verify_token(token)
    base_url = _build_base_url(request)

    if not id.isdigit():
        raise HTTPException(status_code=400, detail="id 必须是数字 ID")
    movie = await session.get(Movie, int(id))
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    play_url = _build_stream_url(movie.id, base_url)
    return {
        "parse": 0,  # 0 = 直接播放，1 = 需要解析
        "url": play_url,
        "header": {
            "User-Agent": "MDCX-TVBox/1.0",
        },
    }


# ============== 流媒体端点（公开，供 TVBox 客户端直接播放） ==============

VIDEO_EXT_MAP = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".ts": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".webm": "video/webm",
}


@router.get("/stream/{movie_id}")
async def tvbox_stream(
    movie_id: int,
    request: Request,
    token: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """直接流式播放视频文件

    支持 Range 请求（拖动进度条）。此端点为公开端点，
    供 TVBox 客户端在拿到 play URL 后直接请求。
    """
    _verify_token(token)

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")
    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = file_path.suffix.lower()
    media_type = VIDEO_EXT_MAP.get(ext, "application/octet-stream")
    file_size = file_path.stat().st_size

    # 处理 Range 请求
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        try:
            range_spec = range_header[6:].split("-")
            start = int(range_spec[0]) if range_spec[0] else 0
            end = int(range_spec[1]) if len(range_spec) > 1 and range_spec[1] else file_size - 1
            end = min(end, file_size - 1)
            content_length = end - start + 1

            def iter_range():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        chunk = f.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        yield chunk
                        remaining -= len(chunk)

            return StreamingResponse(
                iter_range(),
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                    "Cache-Control": "public, max-age=3600",
                },
                status_code=206,
            )
        except (ValueError, IndexError):
            pass

    # 完整文件流
    def iter_file():
        with open(file_path, "rb") as f:
            while True:
                data = f.read(1024 * 1024)
                if not data:
                    break
                yield data

    return StreamingResponse(
        iter_file(),
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Cache-Control": "public, max-age=3600",
        },
    )


__all__ = ["router"]
