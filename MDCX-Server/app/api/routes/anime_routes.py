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
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, or_, select, text

from app.db.module_db import ModuleDatabase
from app.db.anime_models import AnimeMovie, AnimeSeries, AnimeSeriesFavorite, AnimeStudio
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


def _parse_genre_list(raw) -> list[str]:
    """把 DB 的 genre JSON 数组字符串解析成列表（详情页 category chips 用）"""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if s.startswith("["):
        try:
            import json

            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
    return [x.strip() for x in re.split(r"[,，、|;；\n]", s) if x.strip()]


def _actor_names(m: AnimeMovie) -> list[str]:
    """把 actor 文本（逗号分隔）解析成演员名单（与通用详情端点 actor_names 同口径）"""
    raw = getattr(m, "actor", "") or ""
    names: list[str] = []
    for chunk in re.split(r"[,，、/|;；\n]", str(raw)):
        name = chunk.strip()
        if name and name not in names:
            names.append(name)
    return names


# ============================================================
# 影片列表
# ============================================================
@router.get("/categories")
async def list_anime_categories(
    q: str = Query("", description="类别名模糊筛选"),
    limit: int = Query(500, ge=1, le=2000),
):
    """里番类别聚合：解析 AnimeMovie.genre（JSON 数组字符串），按 count 降序返回。

    与 /modules/{module}/categories 的返回形状一致，供桌面端「类别」页复用。
    """
    import json
    from collections import Counter

    db = get_anime_db()
    session = await db.get_session()
    try:
        rows = (
            await session.execute(
                select(AnimeMovie.genre).where(
                    AnimeMovie.genre.isnot(None), AnimeMovie.genre != ""
                )
            )
        ).scalars().all()
        total_movies = (
            await session.execute(select(func.count(AnimeMovie.id)))
        ).scalar() or 0
    finally:
        await session.close()

    counter: Counter = Counter()
    for raw in rows:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("[") else raw
        except Exception:
            parsed = raw
        if isinstance(parsed, list):
            for g in parsed:
                if g:
                    counter[str(g).strip()] += 1
        elif isinstance(parsed, str):
            for g in (x.strip() for x in parsed.replace("|", ",").split(",") if x.strip()):
                counter[g] += 1

    items = [{"name": name, "count": cnt} for name, cnt in counter.most_common()]
    if q:
        kw = q.strip().lower()
        items = [it for it in items if kw in it["name"].lower()]
    if limit > 0:
        items = items[:limit]
    return {"module": "anime", "total_movies": total_movies, "total_categories": len(items), "items": items}


@router.get("/movies")
async def list_anime_movies(
    q: Optional[str] = None,
    maker: Optional[str] = None,
    series: Optional[str] = None,
    series_id: Optional[int] = None,
    genre: Optional[str] = None,
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
        if genre:
            # genre 列为 JSON 数组字符串，按带引号的完整标签匹配，避免子串误配
            stmt = stmt.where(AnimeMovie.genre.contains('"%s"' % genre))

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
            "plot_short": m.plot_short,
            "genre": _parse_genre_list(m.genre),
            "actor_names": _actor_names(m),
            "original_title": m.original_title,
            "director": m.director,
            "rating": m.rating,
            "file_size": m.file_size,
            "play_count": m.play_count,
            "view_status": m.view_status,
            "file_path": m.file_path,
            "play_url": f"/api/v1/anime/movies/{m.id}/play/file",
        }
    finally:
        await session.close()


# ============================================================
# 系列（核心：看同作品相同集数）
# ============================================================
def _series_agg_columns():
    """系列列表的聚合列：作品数 / 首部影片 id（取封面）/ 最新一集日期。

    用相关子查询而非 GROUP BY + JOIN：可直接按聚合列排序并 offset/limit 分页，
    数据库只需处理当前页的系列（全库 1400+ 系列时差异明显）。
    """
    cnt = (
        select(func.count(AnimeMovie.id))
        .where(AnimeMovie.series_id == AnimeSeries.id)
        .correlate(AnimeSeries)
        .scalar_subquery()
    )
    first_movie = (
        select(AnimeMovie.id)
        .where(AnimeMovie.series_id == AnimeSeries.id)
        .order_by(AnimeMovie.episode.is_(None), AnimeMovie.episode, AnimeMovie.release_date, AnimeMovie.id)
        .limit(1)
        .correlate(AnimeSeries)
        .scalar_subquery()
    )
    latest = (
        select(func.max(AnimeMovie.release_date))
        .where(AnimeMovie.series_id == AnimeSeries.id)
        .correlate(AnimeSeries)
        .scalar_subquery()
    )
    return cnt, first_movie, latest


def _build_series_query(q: Optional[str], maker: Optional[str], favorite: bool, sort: str):
    cnt, first_movie, latest = _series_agg_columns()
    stmt = select(
        AnimeSeries.id,
        AnimeSeries.name,
        AnimeSeries.studio_id,
        cnt.label("movie_count"),
        first_movie.label("first_movie_id"),
        latest.label("latest_date"),
    )

    joined_studio = False
    if q:
        like = f"%{q}%"
        stmt = stmt.outerjoin(AnimeStudio, AnimeStudio.id == AnimeSeries.studio_id)
        joined_studio = True
        stmt = stmt.where(or_(AnimeSeries.name.like(like), AnimeStudio.name.like(like)))
    if maker:
        if not joined_studio:
            stmt = stmt.outerjoin(AnimeStudio, AnimeStudio.id == AnimeSeries.studio_id)
            joined_studio = True
        stmt = stmt.where(AnimeStudio.name == maker)
    if favorite:
        stmt = stmt.join(AnimeSeriesFavorite, AnimeSeriesFavorite.series_id == AnimeSeries.id)

    if favorite and sort == "fav_time":
        # 喜好页默认：最近收藏的排最前
        stmt = stmt.order_by(AnimeSeriesFavorite.created_at.desc(), AnimeSeries.name)
    elif sort == "name":
        stmt = stmt.order_by(AnimeSeries.name)
    elif sort == "recent":
        stmt = stmt.order_by(latest.is_(None), latest.desc(), AnimeSeries.name)
    else:
        # 默认按作品数（大系列靠前）
        stmt = stmt.order_by(cnt.desc(), AnimeSeries.name)
    return stmt


async def _series_payload(session, rows) -> list[dict]:
    """把行对象组装成前端需要的结构（含制作商名、封面、是否已收藏）。"""
    studio_ids = {r.studio_id for r in rows if r.studio_id}
    makers: dict[int, str] = {}
    if studio_ids:
        sts = (await session.execute(
            select(AnimeStudio.id, AnimeStudio.name).where(AnimeStudio.id.in_(studio_ids))
        )).all()
        makers = {sid: name for sid, name in sts}

    series_ids = [r.id for r in rows]
    fav_ids: set[int] = set()
    if series_ids:
        fav_ids = {
            r[0] for r in (await session.execute(
                select(AnimeSeriesFavorite.series_id).where(AnimeSeriesFavorite.series_id.in_(series_ids))
            )).all()
        }

    return [
        {
            "id": r.id,
            "name": r.name,
            "maker": makers.get(r.studio_id),
            "movie_count": r.movie_count or 0,
            "cover": _cover_url(r.first_movie_id) if r.first_movie_id else None,
            "latest_date": r.latest_date,
            "favorited": r.id in fav_ids,
        }
        for r in rows
    ]


@router.get("/series")
async def list_anime_series(
    q: Optional[str] = None,
    maker: Optional[str] = None,
    sort: str = "count",
    favorite: bool = False,
    skip: int = 0,
    limit: int = 48,
):
    """系列列表（服务端分页 + 服务端过滤）。

    - q：系列名 / 制作商 模糊匹配（下沉到 SQL，前端不必全量拉取 1400+ 系列）
    - maker：制作商精确过滤
    - favorite：True 时只返回已标记「喜好」的系列
    - sort：count(作品数) / name(名称) / recent(最新一集) / fav_time(收藏时间)
    - skip/limit：分页；返回 total 为过滤后的真实总数（非当前页条数）
    """
    limit = max(1, min(int(limit), 2000))
    skip = max(0, int(skip))
    db = get_anime_db()
    session = await db.get_session()
    try:
        stmt = _build_series_query(q, maker, favorite, sort)
        total = (
            await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar() or 0
        rows = (await session.execute(stmt.offset(skip).limit(limit))).all()
        return {"items": await _series_payload(session, rows), "total": total}
    finally:
        await session.close()


# ============================================================
# 喜好（收藏的系列）
# ============================================================
@router.get("/favorites/series")
async def list_anime_favorite_series(
    q: Optional[str] = None,
    sort: str = "fav_time",
    skip: int = 0,
    limit: int = 48,
):
    """喜好的系列列表（分页，默认按收藏时间倒序）。"""
    limit = max(1, min(int(limit), 2000))
    skip = max(0, int(skip))
    db = get_anime_db()
    session = await db.get_session()
    try:
        stmt = _build_series_query(q, None, True, sort)
        total = (
            await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar() or 0
        rows = (await session.execute(stmt.offset(skip).limit(limit))).all()
        items = await _series_payload(session, rows)

        # 补上收藏时间（喜好页展示"何时加入"）
        if items:
            ids = [i["id"] for i in items]
            favs = (await session.execute(
                select(AnimeSeriesFavorite.series_id, AnimeSeriesFavorite.created_at)
                .where(AnimeSeriesFavorite.series_id.in_(ids))
            )).all()
            fav_map = {sid: created for sid, created in favs}
            for i in items:
                i["favorited_at"] = fav_map.get(i["id"])
        return {"items": items, "total": total}
    finally:
        await session.close()


@router.post("/favorites/series")
async def add_anime_favorite_series(series_id: int = Query(...)):
    """标记系列为喜好（幂等：重复调用不报错）。"""
    db = get_anime_db()
    session = await db.get_session()
    try:
        s = (await session.execute(select(AnimeSeries).where(AnimeSeries.id == series_id))).scalar_one_or_none()
        if not s:
            raise HTTPException(status_code=404, detail="系列不存在")
        existing = (await session.execute(
            select(AnimeSeriesFavorite).where(AnimeSeriesFavorite.series_id == series_id)
        )).scalar_one_or_none()
        if not existing:
            session.add(AnimeSeriesFavorite(series_id=series_id, series_name=s.name))
            await session.commit()
        elif existing.series_name != s.name:
            existing.series_name = s.name
            await session.commit()
        return {"status": "success", "series_id": series_id, "favorited": True}
    finally:
        await session.close()


@router.delete("/favorites/series/{series_id}")
async def remove_anime_favorite_series(series_id: int):
    """取消系列喜好（幂等）。"""
    db = get_anime_db()
    session = await db.get_session()
    try:
        fav = (await session.execute(
            select(AnimeSeriesFavorite).where(AnimeSeriesFavorite.series_id == series_id)
        )).scalar_one_or_none()
        if fav:
            await session.delete(fav)
            await session.commit()
        return {"status": "success", "series_id": series_id, "favorited": False}
    finally:
        await session.close()


@router.post("/favorites/series/{series_id}/toggle")
async def toggle_anime_favorite_series(series_id: int):
    """切换喜好状态：已收藏则取消，未收藏则收藏。返回最终状态。"""
    db = get_anime_db()
    session = await db.get_session()
    try:
        fav = (await session.execute(
            select(AnimeSeriesFavorite).where(AnimeSeriesFavorite.series_id == series_id)
        )).scalar_one_or_none()
        if fav:
            await session.delete(fav)
            await session.commit()
            return {"status": "success", "series_id": series_id, "favorited": False}

        s = (await session.execute(select(AnimeSeries.id, AnimeSeries.name).where(AnimeSeries.id == series_id))).first()
        if not s:
            raise HTTPException(status_code=404, detail="系列不存在")
        session.add(AnimeSeriesFavorite(series_id=series_id, series_name=s.name))
        await session.commit()
        return {"status": "success", "series_id": series_id, "favorited": True}
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


# ============================================================
# 指定目录刮削（仅对指定目录下的影片发起 getchu 网络刮削）
# ============================================================
@router.post("/scrape-dir")
async def scrape_anime_dir(directory: str, only_missing: bool = True):
    """对指定目录下的里番发起 getchu 刮削（后台任务）。

    目录必须是 anime 模块 media_dirs 之一或其子目录（防任意路径遍历）。
    仅刮削已扫描入库的影片；only_missing=True 时跳过已完整刮削的影片。
    天然不波及 1999~2025 全部内容——传入 J:\\动漫\\2026 即只刮 2026。
    返回 job_id，进度用 GET /anime/scrape-dir/{job_id}/status 查询。
    """
    from app.config.manager import get_config

    cfg = get_config()
    media_dirs = list(getattr(cfg.modules.anime, "media_dirs", []) or [])
    if not media_dirs:
        raise HTTPException(status_code=400, detail="anime 模块未配置 media_dirs")

    norm = os.path.normpath(directory)
    if not any(
        norm == os.path.normpath(d)
        or norm.startswith(os.path.normpath(d) + os.sep)
        for d in media_dirs
    ):
        raise HTTPException(
            status_code=400,
            detail="目录必须是 anime 媒体目录或其子目录（防止越权访问）",
        )
    if not os.path.isdir(norm):
        raise HTTPException(status_code=400, detail="目录不存在或不可访问")

    from app.services.anime_scrape_service import run_anime_dir_scrape

    job_id = f"anime_dir_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    asyncio.create_task(run_anime_dir_scrape(job_id, norm, only_missing))
    return {
        "status": "started",
        "job_id": job_id,
        "directory": norm,
        "only_missing": only_missing,
        "message": "指定目录刮削已启动（后台执行）",
    }


@router.get("/scrape-dir/{job_id}/status")
async def scrape_anime_dir_status(job_id: str):
    """查询指定目录刮削任务进度。"""
    from app.services.anime_scrape_service import get_anime_dir_scrape_status

    st = get_anime_dir_scrape_status(job_id)
    if not st:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return st
