"""
JAV 无码模块 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request as _Request
from sqlalchemy import func, select

from app.db.module_db import ModuleDatabase

import os as _os
from pathlib import Path as _Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uncensored", tags=["无码模块"])


def get_uncensored_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("uncensored")


@router.get("/actors")
async def list_actors(search: Optional[str] = Query(None, description="按名字/日文名/别名搜索")):
    """列出无码演员列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select, or_
        stmt = select(UncensoredActor)
        if search:
            alias_col = getattr(UncensoredActor, "alias", None)
            cond = or_(
                UncensoredActor.name.contains(search),
                UncensoredActor.name_jp.contains(search),
                UncensoredActor.name_en.contains(search),
            )
            if alias_col is not None:
                cond = or_(cond, alias_col.contains(search))
            stmt = stmt.where(cond)
        stmt = stmt.order_by(UncensoredActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count, "source": a.source, "avatar_url": a.avatar_url, "module_type": "uncensored"} for a in actors]
    finally:
        await session.close()


# ========== 封面端点（纯本地查找，不连外网） ==========


@router.get("/movies/{movie_id}/cover/file")
async def get_uncensored_cover_file(movie_id: int):
    """获取无码影片封面图片文件"""
    from fastapi.responses import FileResponse, Response
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        movie = await session.get(UncensoredMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 1) 规范目录：{data_base}/movies/uncensored/{code}/poster.jpg
        if movie.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path("uncensored", movie.code)
                if fast_file_exists(str(p)):
                    ext = _Path(str(p)).suffix.lower()
                    mt = "image/jpeg"
                    if ext == ".png": mt = "image/png"
                    elif ext == ".webp": mt = "image/webp"
                    return FileResponse(str(p), media_type=mt,
                                        headers={"Cache-Control": "public, max-age=86400"})

        # 2) DB 中 cover_url/poster_url/thumb_url 的本地路径
        for attr in ("cover_url", "poster_url", "thumb_url"):
            url = getattr(movie, attr, None)
            if not url: continue
            if not url.startswith(("http://", "https://", "/")):
                if fast_file_exists(url):
                    ext = _Path(url).suffix.lower()
                    mt = "image/jpeg"
                    if ext == ".png": mt = "image/png"
                    elif ext == ".webp": mt = "image/webp"
                    return FileResponse(url, media_type=mt,
                                        headers={"Cache-Control": "public, max-age=86400"})

        # 3) 视频所在目录下的 poster.jpg/cover.jpg 等
        if movie.file_path:
            try:
                video_dir = _Path(movie.file_path).parent
                for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg", "thumb.jpg"]:
                    img_path = video_dir / img_name
                    import asyncio
                    if await asyncio.wait_for(
                        asyncio.to_thread(lambda p=img_path: p.exists() and p.is_file()),
                        timeout=3.0,
                    ):
                        ext = _Path(str(img_path)).suffix.lower()
                        mt = "image/jpeg"
                        if ext == ".png": mt = "image/png"
                        elif ext == ".webp": mt = "image/webp"
                        return FileResponse(str(img_path), media_type=mt,
                                            headers={"Cache-Control": "public, max-age=86400"})
            except asyncio.TimeoutError:
                pass

        # 4) 全部找不到：返回内置 SVG 占位图
        from fastapi.responses import HTMLResponse
        placeholder = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360" '
            'viewBox="0 0 240 360"><rect fill="#f0f0f0" width="240" height="360"/>'
            '<text x="120" y="180" text-anchor="middle" fill="#bbb" '
            'font-size="14">暂无封面</text></svg>'
        )
        return HTMLResponse(content=placeholder, media_type="image/svg+xml",
                            headers={"Cache-Control": "no-cache"})
    finally:
        await session.close()


# ========== 相关推荐与演员端点（通用详情页使用） ==========


@router.get("/movies/{movie_id}/related")
async def get_uncensored_related_movies(movie_id: int):
    """获取无码影片的相关推荐（同演员/同系列/同类别）"""
    from sqlalchemy import select, or_, and_
    from app.db.uncensored_models import UncensoredMovie

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        movie = await session.get(UncensoredMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        related_ids = {movie_id}
        actor_movies = []
        series_movies = []
        genre_movies = []
        limit = 12

        if movie.actor:
            actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
            if actor_names:
                filters = [UncensoredMovie.actor.contains(name) for name in actor_names]
                stmt = select(UncensoredMovie).where(
                    and_(or_(*filters), UncensoredMovie.id != movie_id)
                ).order_by(UncensoredMovie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        actor_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "uncensored", "cover_url": m.cover_url,
                        })

        if movie.series:
            stmt = select(UncensoredMovie).where(
                and_(UncensoredMovie.series == movie.series, UncensoredMovie.id != movie_id)
            ).order_by(UncensoredMovie.id.desc()).limit(limit)
            result = await session.execute(stmt)
            for m in result.scalars().all():
                if m.id not in related_ids:
                    related_ids.add(m.id)
                    series_movies.append({
                        "id": m.id, "code": m.code, "title": m.title,
                        "module_type": "uncensored", "cover_url": m.cover_url,
                    })

        if movie.genre:
            genre_parts = [g.strip() for g in movie.genre.split(",") if g.strip()]
            if genre_parts:
                genre_filters = [UncensoredMovie.genre.contains(gp) for gp in genre_parts[:5]]
                stmt = select(UncensoredMovie).where(
                    and_(or_(*genre_filters), UncensoredMovie.id != movie_id)
                ).order_by(UncensoredMovie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        genre_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "uncensored", "cover_url": m.cover_url,
                        })

        return {
            "actor_movies": actor_movies[:limit],
            "series_movies": series_movies[:limit],
            "genre_movies": genre_movies[:limit],
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/actors")
async def get_uncensored_movie_actors(movie_id: int):
    """获取无码影片关联的演员列表"""
    from app.db.uncensored_models import UncensoredMovie, UncensoredActor

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        movie = await session.get(UncensoredMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        if not movie.actor:
            return {"items": []}
        actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
        items = []
        for name in actor_names:
            stmt = select(UncensoredActor).where(UncensoredActor.name == name)
            result = await session.execute(stmt)
            actor = result.scalar_one_or_none()
            if actor:
                items.append({"id": actor.id, "name": actor.name, "avatar_url": actor.avatar_url})
            else:
                items.append({"id": name, "name": name, "avatar_url": None})
        return {"items": items}
    finally:
        await session.close()


# ========== 后续端点 ==========


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
    # 2026-08-08 新增: 详情页跳转筛选参数
    series: Optional[str] = Query(None, description="按系列精确过滤"),
    maker: Optional[str] = Query(None, description="按片商/制作商过滤（匹配 maker 或 studio）"),
    genre: Optional[str] = Query(None, description="按类别过滤（genre 字段包含）"),
    code_prefix: Optional[str] = Query(None, description="番号前缀精确过滤"),
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
        if series:
            filters.append(UncensoredMovie.series == series)
        if maker:
            filters.append(or_(UncensoredMovie.maker == maker, UncensoredMovie.studio == maker))
        if genre:
            filters.append(UncensoredMovie.genre.contains(genre))
        if code_prefix:
            filters.append(UncensoredMovie.code.startswith(code_prefix))

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
             "is_chinese": m.is_chinese, "is_uncensored": m.is_uncensored,
             "is_leak": m.is_leak, "is_4k": m.is_4k,
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
            "is_chinese": movie.is_chinese, "is_uncensored": movie.is_uncensored,
            "is_leak": movie.is_leak, "is_4k": movie.is_4k,
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
    """刮削指定无码影片的元数据（含资源下载与演员合并）"""
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

        # 记录刮削前的旧演员列表（用于后续重算 movie_count）
        old_actor_names: set[str] = set()
        if movie.actor:
            old_actor_names = {a.strip() for a in movie.actor.split(",") if a.strip()}

        from app.scraper.engine import get_scraper_engine
        engine = get_scraper_engine()
        scrape_result = await engine.scrape_number(movie.code, module="uncensored")

        if not scrape_result or not scrape_result.title:
            return {"status": "error", "message": f"刮削失败: 未找到 {movie.code} 的数据"}

        movie.title = scrape_result.title
        if scrape_result.original_title:
            movie.original_title = scrape_result.original_title
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

        # ── 资源下载：将远程封面/预览图下载到本地 ──
        from app.utils.media_helpers import (
            ensure_movie_media_local,
            ensure_actor_avatar_local,
        )

        local_media = await ensure_movie_media_local(
            module_name="uncensored", code=movie.code,
            cover_url=scrape_result.cover_url,
            fanart_url=scrape_result.poster_url,
            thumb_url=scrape_result.thumb_url,
        )
        if local_media.get("cover"):
            movie.cover_url = local_media["cover"]
        if local_media.get("fanart"):
            movie.poster_url = local_media["fanart"]
        if local_media.get("thumb"):
            movie.thumb_url = local_media["thumb"]
        if not movie.cover_url and scrape_result.cover_url:
            movie.cover_url = scrape_result.cover_url

        # 演员处理
        new_actor_names: set[str] = set()
        if scrape_result.actors:
            new_actor_names = {a.name for a in scrape_result.actors}
            movie.actor = ",".join(sorted(new_actor_names))

            for actor_info in scrape_result.actors:
                existing = await session.execute(
                    select(UncensoredActor).where(UncensoredActor.name == actor_info.name)
                )
                db_actor = existing.scalar_one_or_none()
                if db_actor:
                    if not db_actor.avatar_url and actor_info.avatar_url:
                        local_avatar = await ensure_actor_avatar_local(
                            actor_info.name, actor_info.avatar_url
                        )
                        db_actor.avatar_url = local_avatar or actor_info.avatar_url
                else:
                    local_avatar = await ensure_actor_avatar_local(
                        actor_info.name, actor_info.avatar_url
                    )
                    session.add(UncensoredActor(
                        name=actor_info.name,
                        avatar_url=local_avatar or actor_info.avatar_url,
                        source="scraper",
                        source_site=scrape_result.source,
                        movie_count=0,
                    ))
        else:
            movie.actor = None

        movie.source = scrape_result.source or "scraper"
        movie.status = "scraped"
        await session.commit()

        # 重算受影响演员作品数（重刮可能改变演员列表，不能简单累加）
        affected = new_actor_names | old_actor_names
        if affected:
            actors = (await session.execute(
                select(UncensoredActor).where(UncensoredActor.name.in_(list(affected)))
            )).scalars().all()
            for actor in actors:
                actor.movie_count = await session.scalar(
                    select(func.count(UncensoredMovie.id)).where(
                        UncensoredMovie.actor.contains(actor.name),
                        UncensoredMovie.status != "pending",
                    )
                ) or 0
            await session.commit()

        return {
            "status": "ok",
            "message": f"刮削成功: {scrape_result.title}",
            "source": scrape_result.source,
            "actors": sorted(new_actor_names),
        }

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
        from app.utils.media_helpers import ensure_movie_media_local, ensure_actor_avatar_local
        from sqlalchemy import select
        engine = get_scraper_engine()
        success = failed = 0
        affected_actors: set[str] = set()
        for m in pending:
            try:
                sr = await engine.scrape_number(m.code, module="uncensored")
                if sr and sr.title:
                    s = await db.get_session()
                    try:
                        st = select(UncensoredMovie).where(UncensoredMovie.id == m.id)
                        r = await s.execute(st)
                        mv = r.scalar_one_or_none()
                        if mv:
                            mv.title = sr.title
                            if sr.original_title: mv.original_title = sr.original_title
                            if sr.release_date: mv.release_date = str(sr.release_date)
                            if sr.duration: mv.duration = sr.duration
                            if sr.rating: mv.rating = sr.rating
                            if sr.plot: mv.plot = sr.plot
                            if sr.studio: mv.studio = sr.studio
                            if sr.genres: mv.genre = ",".join(sr.genres)
                            if sr.tags: mv.tag = ",".join(sr.tags)

                            # 下载封面到本地
                            local_media = await ensure_movie_media_local(
                                module_name="uncensored", code=mv.code,
                                cover_url=sr.cover_url,
                                fanart_url=sr.poster_url,
                            )
                            if local_media.get("cover"):
                                mv.cover_url = local_media["cover"]
                            if local_media.get("fanart"):
                                mv.poster_url = local_media["fanart"]
                            if not mv.cover_url and sr.cover_url:
                                mv.cover_url = sr.cover_url

                            if sr.actors:
                                mv.actor = ",".join(a.name for a in sr.actors)
                                for ai in sr.actors:
                                    affected_actors.add(ai.name)
                                    ex = await s.execute(select(UncensoredActor).where(UncensoredActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if not a:
                                        local_avatar = await ensure_actor_avatar_local(
                                            ai.name, ai.avatar_url
                                        )
                                        s.add(UncensoredActor(
                                            name=ai.name,
                                            avatar_url=local_avatar or ai.avatar_url,
                                            source="scraper",
                                            source_site=sr.source,
                                            movie_count=0,
                                        ))
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

        # 批量重算受影响演员的作品数
        if affected_actors:
            try:
                s = await db.get_session()
                try:
                    actors = (await s.execute(
                        select(UncensoredActor).where(UncensoredActor.name.in_(list(affected_actors)))
                    )).scalars().all()
                    for actor in actors:
                        actor.movie_count = await s.scalar(
                            select(func.count(UncensoredMovie.id)).where(
                                UncensoredMovie.actor.contains(actor.name),
                                UncensoredMovie.status != "pending",
                            )
                        ) or 0
                    await s.commit()
                finally:
                    await s.close()
            except Exception as e:
                logger.warning(f"无码批量刮削-重算作品数失败: {e}")

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

    from app.utils.http_headers import safe_content_disposition
    return StreamingResponse(
        _iter_full(),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": safe_content_disposition(file_path),
        },
    )


@router.get("/movies/{movie_id}/play/external")
async def get_uncensored_external_play_url(movie_id: int, request: _Request, protocol: str = "http"):
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
        from app.utils.play_url import build_play_base_url
        config = get_config()
        host = getattr(config.server, "host", "0.0.0.0")
        port = getattr(config.server, "port", 8420)

        base = build_play_base_url(request, host, port)

        if protocol == "http":
            play_url = f"{base}/api/v1/uncensored/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()


# ========== 演员合并 ==========


@router.post("/actors/merge")
async def merge_uncensored_actors(canonical_id: int = Query(...), source_ids: list[int] = Query(...)):
    """合并无码演员：source 并入 canonical"""
    from app.services.actor_merge_service import merge_actors
    result = await merge_actors(canonical_id, source_ids, "uncensored")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/actors/merge/search")
async def search_similar_uncensored_actors(
    name: str = Query(..., description="演员名称"),
    threshold: float = Query(0.6, ge=0, le=1),
):
    """搜索名称相似的无码演员（推荐合并候选）"""
    from app.services.actor_merge_service import search_similar_actors
    items = await search_similar_actors(name, threshold=threshold, module="uncensored")
    return {"items": items, "total": len(items)}


@router.get("/actors/merge/candidates/{actor_id}")
async def get_uncensored_merge_candidates(actor_id: int):
    """获取无码演员的合并候选列表"""
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
        from app.services.actor_merge_service import search_similar_actors
        items = await search_similar_actors(actor.name, threshold=0.6, module="uncensored")
        return {"actor": {"id": actor.id, "name": actor.name, "alias": actor.alias, "movie_count": actor.movie_count},
                "candidates": items, "total": len(items)}
    finally:
        await session.close()
