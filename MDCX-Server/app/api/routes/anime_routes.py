"""
日本里番模块 API 路由 (prefix=/anime)

端点：
- GET  /anime/movies              影片列表（按 制作商/系列/集数 筛选）
- GET  /anime/movies/{id}         影片详情
- GET  /anime/movies/{id}/cover/file   封面（本地优先，绝不连外网）
- GET  /anime/movies/{id}/play/file    视频流（支持 Range）
- GET  /anime/series             系列列表（按作品数排序）
- GET  /anime/series/{id}/movies 某系列全部集数（按集数排序）
- GET  /anime/makers             制作商列表（按作品数排序）
"""
import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, select, text

from app.db.module_db import ModuleDatabase
from app.db.anime_models import AnimeMovie, AnimeSeries, AnimeStudio
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/anime", tags=["日本里番模块"])

MODULE = "anime"


def get_anime_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance(MODULE)


def _image_media_type(p: str) -> str:
    ext = Path(p).suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")


def _cover_url(movie_id: int) -> str:
    return f"/api/v1/anime/movies/{movie_id}/cover/file"


def _movie_summary(m: AnimeMovie) -> dict:
    return {
        "id": m.id,
        "code": m.code,
        "title": m.title,
        "maker": m.maker,
        "studio": m.studio,
        "series": m.series,
        "series_id": m.series_id,
        "episode": m.episode,
        "release_date": m.release_date,
        "duration": m.duration,
        "cover": _cover_url(m.id),
        "play_url": f"/api/v1/anime/movies/{m.id}/play/file",
        "has_file": bool(m.file_path and os.path.exists(m.file_path)),
        "status": m.status,
        "source": m.source,
    }


# ============================================================
# 影片列表
# ============================================================
@router.get("/movies")
async def list_anime_movies(
    q: Optional[str] = None,
    maker: Optional[str] = None,
    series: Optional[str] = None,
    series_id: Optional[int] = None,
    sort: str = "recent",
    skip: int = 0,
    limit: int = 48,
):
    db = get_anime_db()
    session = await db.get_session()
    try:
        stmt = select(AnimeMovie)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                (AnimeMovie.title.like(like)) | (AnimeMovie.maker.like(like)) | (AnimeMovie.series.like(like))
            )
        if maker:
            stmt = stmt.where(AnimeMovie.maker == maker)
        if series:
            stmt = stmt.where(AnimeMovie.series == series)
        if series_id is not None:
            stmt = stmt.where(AnimeMovie.series_id == series_id)

        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0

        if sort == "episode":
            stmt = stmt.order_by(AnimeMovie.series, AnimeMovie.episode.is_(None), AnimeMovie.episode, AnimeMovie.release_date)
        else:  # recent
            stmt = stmt.order_by(AnimeMovie.release_date.is_(None), AnimeMovie.release_date.desc(), AnimeMovie.id.desc())

        stmt = stmt.offset(skip).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return {"items": [_movie_summary(m) for m in rows], "total": total}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_anime_movie(movie_id: int):
    db = get_anime_db()
    session = await db.get_session()
    try:
        m = (await session.execute(select(AnimeMovie).where(AnimeMovie.id == movie_id))).scalar_one_or_none()
        if not m:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            **_movie_summary(m),
            "plot": m.plot,
            "director": m.director,
            "file_path": m.file_path,
            "play_url": f"/api/v1/anime/movies/{m.id}/play/file",
        }
    finally:
        await session.close()


# ============================================================
# 系列（核心：看同作品相同集数）
# ============================================================
@router.get("/series")
async def list_anime_series(limit: int = 200):
    db = get_anime_db()
    session = await db.get_session()
    try:
        stmt = (
            select(
                AnimeSeries.id,
                AnimeSeries.name,
                AnimeSeries.studio_id,
                func.count(AnimeMovie.id).label("cnt"),
            )
            .outerjoin(AnimeMovie, AnimeMovie.series_id == AnimeSeries.id)
            .group_by(AnimeSeries.id)
            .order_by(text("cnt DESC"))
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        series_list = []
        for r in rows:
            maker = None
            if r.studio_id:
                st = (await session.execute(select(AnimeStudio).where(AnimeStudio.id == r.studio_id))).scalar_one_or_none()
                maker = st.name if st else None
            series_list.append({"id": r.id, "name": r.name, "maker": maker, "movie_count": r.cnt})
        return {"items": series_list, "total": len(series_list)}
    finally:
        await session.close()


@router.get("/series/{series_id}/movies")
async def list_anime_series_movies(series_id: int):
    """某系列全部集数，按集数排序（null 集数排最后）"""
    db = get_anime_db()
    session = await db.get_session()
    try:
        stmt = (
            select(AnimeMovie)
            .where(AnimeMovie.series_id == series_id)
            .order_by(AnimeMovie.episode.is_(None), AnimeMovie.episode, AnimeMovie.release_date)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {"series_id": series_id, "items": [_movie_summary(m) for m in rows], "total": len(rows)}
    finally:
        await session.close()


# ============================================================
# 制作商
# ============================================================
@router.get("/makers")
async def list_anime_makers(limit: int = 200):
    db = get_anime_db()
    session = await db.get_session()
    try:
        stmt = (
            select(AnimeStudio.name, func.count(AnimeMovie.id).label("cnt"))
            .outerjoin(AnimeMovie, AnimeMovie.studio_id == AnimeStudio.id)
            .group_by(AnimeStudio.id)
            .order_by(text("cnt DESC"))
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        return {"items": [{"name": r.name, "movie_count": r.cnt} for r in rows], "total": len(rows)}
    finally:
        await session.close()


# ============================================================
# 封面（本地优先，绝不连外网）
# ============================================================
@router.get("/movies/{movie_id}/cover/file")
async def get_anime_cover_file(movie_id: int):
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )

    db = get_anime_db()
    session = await db.get_session()
    try:
        m = (await session.execute(select(AnimeMovie).where(AnimeMovie.id == movie_id))).scalar_one_or_none()
        if not m:
            raise HTTPException(status_code=404, detail="影片不存在")

        if m.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path(MODULE, m.code)
                if fast_file_exists(str(p)):
                    return FileResponse(str(p), media_type=_image_media_type(str(p)),
                                        headers={"Cache-Control": "public, max-age=86400"})

        if m.file_path:
            video_dir = Path(m.file_path).parent
            for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg", "thumb.jpg"]:
                img_path = video_dir / img_name
                if img_path.exists() and img_path.is_file():
                    return FileResponse(str(img_path), media_type=_image_media_type(img_name),
                                        headers={"Cache-Control": "public, max-age=86400"})
    finally:
        await session.close()

    # 占位 SVG
    from fastapi.responses import HTMLResponse
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="340" '
        'viewBox="0 0 240 340"><rect fill="#2a2a35" width="240" height="340"/>'
        '<text x="120" y="170" text-anchor="middle" fill="#888" font-size="14">无封面</text></svg>'
    )
    return HTMLResponse(content=svg, media_type="image/svg+xml")


# ============================================================
# 视频流（支持 Range）
# ============================================================
@router.get("/movies/{movie_id}/play/file")
async def play_anime_video_file(movie_id: int, request: Request):
    db = get_anime_db()
    session = await db.get_session()
    try:
        m = (await session.execute(select(AnimeMovie).where(AnimeMovie.id == movie_id))).scalar_one_or_none()
    finally:
        await session.close()

    if not m or not m.file_path:
        raise HTTPException(status_code=404, detail="视频不存在")
    file_path = Path(m.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = file_path.suffix.lower()
    media_type = {
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".ts": "video/mp2t",
    }.get(ext, "video/mp4")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        try:
            range_str = range_header.replace("bytes=", "")
            parts = range_str.split("-")
            start = int(parts[0])
            end = int(parts[1]) if parts[1] else file_size - 1
            if start >= file_size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
            chunk_size = end - start + 1

            async def _iter_chunk():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        data = f.read(min(8192, remaining))
                        if not data:
                            break
                        yield data
                        remaining -= len(data)

            return StreamingResponse(
                _iter_chunk(), status_code=206, media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(chunk_size),
                    "Accept-Ranges": "bytes",
                },
            )
        except (ValueError, IndexError):
            pass

    async def _iter_full():
        with open(file_path, "rb") as f:
            while True:
                data = f.read(8192)
                if not data:
                    break
                yield data

    # Content-Disposition 必须能被 latin-1 编码（HTTP 头限制）。
    # 原始文件名常含日文/中文，直接放 header 会触发 UnicodeEncodeError → 500。
    # 用 ASCII 的 code 作为 filename 兜底，再用 RFC 5987 的 filename* 传递真实 UTF-8 文件名。
    from urllib.parse import quote
    raw_name = os.path.basename(file_path)
    ascii_name = f"{m.code or 'video'}{ext}"
    content_disposition = (
        f'inline; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(raw_name)}"
    )
    return StreamingResponse(
        _iter_full(), media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": content_disposition,
        },
    )


# ============================================================
# 手动刮削（getchu 源）
# ============================================================
@router.post("/movies/{movie_id}/scrape")
async def scrape_anime_movie_manual(movie_id: int):
    """手动刮削指定里番：getchu 补全元数据 + 封面 + 预览图 + NFO。

    幂等：仅填空字段；封面/NFO/预览图已存在则跳过。
    """
    from app.scraper.anime_getchu import scrape_anime_and_apply

    db = get_anime_db()
    session = await db.get_session()
    try:
        m = (await session.execute(select(AnimeMovie).where(AnimeMovie.id == movie_id))).scalar_one_or_none()
    finally:
        await session.close()
    if not m:
        raise HTTPException(status_code=404, detail="影片不存在")

    result = await scrape_anime_and_apply(m.code, m.title or "", m.maker, movie_id=m.id)
    if not result["ok"]:
        return {"status": "error", "message": f"刮削失败：getchu 未找到 {m.code} 的数据", **result}
    return {"status": "success", "message": f"刮削完成：{result.get('title') or m.code}", **result}


@router.post("/movies/scrape-pending")
async def scrape_anime_pending(limit: int = 20):
    """批量手动刮削 status=pending 的里番（尚未有本地 NFO 的新增文件）。

    getchu 逐部刮削，受模块级 Semaphore(2) 限流；返回成功/失败统计。
    """
    from app.scraper.anime_getchu import scrape_anime_and_apply

    db = get_anime_db()
    session = await db.get_session()
    try:
        rows = (
            (await session.execute(
                select(AnimeMovie)
                .where(AnimeMovie.status == "pending")
                .order_by(AnimeMovie.id.desc())
                .limit(limit)
            )).scalars().all()
        )
    finally:
        await session.close()

    ok, failed = 0, 0
    results = []
    for m in rows:
        r = await scrape_anime_and_apply(m.code, m.title or "", m.maker, movie_id=m.id)
        if r["ok"]:
            ok += 1
        else:
            failed += 1
        results.append({"id": m.id, "code": m.code, **r})
    return {"status": "done", "total": len(rows), "ok": ok, "failed": failed, "items": results}
