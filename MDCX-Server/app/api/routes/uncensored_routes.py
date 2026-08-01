"""
JAV 无码模块 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request as _Request

from app.db.module_db import ModuleDatabase

import os as _os
from pathlib import Path as _Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uncensored", tags=["无码模块"])


def get_uncensored_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("uncensored")


@router.get("/actors")
async def list_actors():
    """列出无码演员列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select
        stmt = select(UncensoredActor).order_by(UncensoredActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count, "source": a.source, "avatar_url": a.avatar_url, "module_type": "uncensored"} for a in actors]
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取无码演员详情"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select
        stmt = select(UncensoredActor).where(UncensoredActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"id": actor.id, "name": actor.name, "alias": actor.alias,
                "avatar_url": actor.avatar_url, "source": actor.source,
                "module_type": "uncensored",
                "movie_count": actor.movie_count,
                "created_at": str(actor.created_at)}
    finally:
        await session.close()


@router.get("/movies")
async def list_movies(
    skip: int = 0,
    limit: int = 20,
    keyword: Optional[str] = Query(None, description="搜索标题/番号"),
    actor: Optional[str] = Query(None, description="按演员名过滤"),
):
    """列出无码模块影片列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select, func, or_

        filters = []
        if keyword:
            kw = f"%{keyword}%"
            filters.append(or_(UncensoredMovie.title.like(kw), UncensoredMovie.code.like(kw)))
        if actor:
            filters.append(UncensoredMovie.actor.like(f"%{actor}%"))

        total_stmt = select(func.count(UncensoredMovie.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()

        stmt = select(UncensoredMovie)
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.order_by(UncensoredMovie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()

        pending_stmt = select(func.count(UncensoredMovie.id)).where(UncensoredMovie.status == "pending")
        pending_result = await session.execute(pending_stmt)
        pending_count = pending_result.scalar()

        return {"total": total, "pending_count": pending_count or 0, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "source_platform": m.source_platform,
             "series": m.series,
             "cover_url": m.cover_url, "actor": m.actor,
             "module_type": "uncensored",
             "file_path": m.file_path, "status": m.status}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取无码影片详情"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "original_title": movie.original_title,
            "source_platform": movie.source_platform, "series": movie.series,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "actor": movie.actor, "studio": movie.studio,
            "module_type": "uncensored",
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "genre": movie.genre, "tag": movie.tag,
            "source": movie.source, "source_url": movie.source_url,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
        }
    finally:
        await session.close()


# ========== 刮削 ==========


@router.post("/movies/{movie_id}/scrape")
async def scrape_uncensored_movie(movie_id: int):
    """刮削指定无码影片的元数据"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie, UncensoredActor
        from sqlalchemy import select

        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        from app.scraper.engine import get_scraper_engine
        engine = get_scraper_engine()
        scrape_result = await engine.scrape_number(movie.code)

        if not scrape_result or not scrape_result.title:
            return {"status": "error", "message": f"刮削失败: 未找到 {movie.code} 的数据"}

        movie.title = scrape_result.title
        if scrape_result.original_title:
            movie.original_title = scrape_result.original_title
        if scrape_result.cover_url:
            movie.cover_url = scrape_result.cover_url
        if scrape_result.release_date:
            movie.release_date = str(scrape_result.release_date)
        if scrape_result.duration:
            movie.duration = scrape_result.duration
        if scrape_result.rating:
            movie.rating = scrape_result.rating
        if scrape_result.plot:
            movie.plot = scrape_result.plot
        if scrape_result.studio:
            movie.studio = scrape_result.studio
        if scrape_result.genres:
            movie.genre = ",".join(scrape_result.genres)
        if scrape_result.tags:
            movie.tag = ",".join(scrape_result.tags)

        if scrape_result.actors:
            movie.actor = ",".join(a.name for a in scrape_result.actors)
            for actor_info in scrape_result.actors:
                existing = await session.execute(select(UncensoredActor).where(UncensoredActor.name == actor_info.name))
                db_actor = existing.scalar_one_or_none()
                if db_actor:
                    db_actor.movie_count += 1
                else:
                    session.add(UncensoredActor(name=actor_info.name, source="scraper", movie_count=1))

        movie.source = scrape_result.source or "scraper"
        movie.status = "scraped"
        await session.commit()

        return {"status": "ok", "message": f"刮削成功: {scrape_result.title}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"无码刮削失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/scrape-all-pending")
async def scrape_all_pending_uncensored(background_tasks: BackgroundTasks):
    """后台批量刮削所有 status=pending 的无码影片"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.status == "pending").order_by(UncensoredMovie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待刮削的影片", "total": 0}

    async def _run():
        from app.db.uncensored_models import UncensoredMovie, UncensoredActor
        from app.scraper.engine import get_scraper_engine
        from sqlalchemy import select
        engine = get_scraper_engine()
        success = failed = 0
        for m in pending:
            try:
                sr = await engine.scrape_number(m.code)
                if sr and sr.title:
                    s = await db.get_session()
                    try:
                        st = select(UncensoredMovie).where(UncensoredMovie.id == m.id)
                        r = await s.execute(st)
                        mv = r.scalar_one_or_none()
                        if mv:
                            mv.title = sr.title
                            if sr.original_title: mv.original_title = sr.original_title
                            if sr.cover_url: mv.cover_url = sr.cover_url
                            if sr.release_date: mv.release_date = str(sr.release_date)
                            if sr.duration: mv.duration = sr.duration
                            if sr.rating: mv.rating = sr.rating
                            if sr.plot: mv.plot = sr.plot
                            if sr.studio: mv.studio = sr.studio
                            if sr.genres: mv.genre = ",".join(sr.genres)
                            if sr.tags: mv.tag = ",".join(sr.tags)
                            if sr.actors:
                                mv.actor = ",".join(a.name for a in sr.actors)
                                for ai in sr.actors:
                                    ex = await s.execute(select(UncensoredActor).where(UncensoredActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if not a:
                                        s.add(UncensoredActor(name=ai.name, source="scraper", movie_count=1))
                            mv.source = sr.source or "scraper"
                            mv.status = "scraped"
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except:
                failed += 1
        logger.info(f"无码批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)
    return {"status": "started", "total": len(pending), "message": f"无码批量刮削已启动，共 {len(pending)} 部"}


# ========== 播放/播放工具 API ==========


@router.get("/movies/{movie_id}/play")
async def play_uncensored_movie(movie_id: int):
    """获取无码影片播放信息"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "file_exists": _Path(movie.file_path).exists() if movie.file_path else False,
            "cover_url": movie.cover_url, "duration": movie.duration,
            "status": movie.status,
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/play/file")
async def play_uncensored_video_file(movie_id: int, request: _Request):
    """无码影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select

        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
    finally:
        await session.close()

    if not movie or not movie.file_path:
        raise HTTPException(status_code=404, detail="视频不存在")

    file_path = _Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = file_path.suffix.lower()
    media_type = "video/mp4"
    if ext == ".mkv":
        media_type = "video/x-matroska"
    elif ext == ".webm":
        media_type = "video/webm"
    elif ext == ".mov":
        media_type = "video/quicktime"
    elif ext == ".ts":
        media_type = "video/mp2t"
    elif ext == ".avi":
        media_type = "video/x-msvideo"

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
                        to_read = min(8192, remaining)
                        data = f.read(to_read)
                        if not data:
                            break
                        yield data
                        remaining -= len(data)

            return StreamingResponse(
                _iter_chunk(),
                status_code=206,
                media_type=media_type,
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

    return StreamingResponse(
        _iter_full(),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{_os.path.basename(file_path)}"',
        },
    )


@router.get("/movies/{movie_id}/play/external")
async def get_uncensored_external_play_url(movie_id: int, protocol: str = "http"):
    """获取无码影片外部播放地址"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select

        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie or not movie.file_path:
            raise HTTPException(status_code=404, detail="影片没有关联文件")
        if not _Path(movie.file_path).exists():
            raise HTTPException(status_code=404, detail="视频文件不存在")

        from app.config.manager import get_config
        config = get_config()
        host = getattr(config.server, "host", "0.0.0.0")
        port = getattr(config.server, "port", 8420)

        if host in ("0.0.0.0", "127.0.0.1", "localhost"):
            base = f"http://localhost:{port}"
        else:
            base = f"http://{host}:{port}"

        if protocol == "http":
            play_url = f"{base}/api/v1/uncensored/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
