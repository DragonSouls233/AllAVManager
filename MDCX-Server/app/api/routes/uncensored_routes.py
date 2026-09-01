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


@router.get("/studios")
async def list_studios(search: Optional[str] = Query(None, description="按名字/日文名/别名搜索")):
    """列出无码厂商列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import Studio
        from sqlalchemy import select, or_
        stmt = select(Studio)
        if search:
            cond = or_(
                Studio.name.contains(search),
                Studio.name_jp.contains(search),
            )
            alias_col = getattr(Studio, "alias", None)
            if alias_col is not None:
                cond = or_(cond, alias_col.contains(search))
            stmt = stmt.where(cond)
        stmt = stmt.order_by(Studio.movie_count.desc())
        result = await session.execute(stmt)
        studios = result.scalars().all()
        return [{"id": s.id, "name": s.name, "name_jp": s.name_jp, "movie_count": s.movie_count, "module_type": "uncensored"} for s in studios]
    finally:
        await session.close()


@router.get("/studios/{studio_id}")
async def get_studio(studio_id: int):
    """获取无码厂商详情"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import Studio
        from sqlalchemy import select
        stmt = select(Studio).where(Studio.id == studio_id)
        result = await session.execute(stmt)
        studio = result.scalars().first()
        if not studio:
            raise HTTPException(status_code=404, detail="厂商不存在")
        return {"id": studio.id, "name": studio.name, "name_jp": studio.name_jp,
                "movie_count": studio.movie_count, "module_type": "uncensored"}
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
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie, UncensoredActor, MovieActor as UMovieActor
        from sqlalchemy import select
        movie = await session.get(UncensoredMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        # 优先从 movie_actors 关联表获取
        rows = (await session.execute(
            select(UncensoredActor, UMovieActor.role)
            .join(UMovieActor, UMovieActor.actor_id == UncensoredActor.id)
            .where(UMovieActor.movie_id == movie_id)
        )).all()
        if rows:
            items = [
                {"id": a.id, "name": a.name, "avatar_url": a.avatar_url, "role": role}
                for a, role in rows
            ]
            return {"items": items}
        # fallback: 从 movie.actor 文本字段解析
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
            fanart_url=scrape_result.poster_url or scrape_result.cover_url,
            thumb_url=scrape_result.sample_images[0] if scrape_result.sample_images else scrape_result.thumb_url,
            referer=scrape_result.cover_url,
        )
        if local_media.get("cover"):
            movie.cover_url = local_media["cover"]
        if local_media.get("fanart"):
            movie.poster_url = local_media["fanart"]
        if local_media.get("thumb"):
            movie.thumb_url = local_media["thumb"]
        # 样图/剧照保存到数据库(以 JSON 列表格式)
        if scrape_result.sample_images:
            movie.sample_images = ",".join(scrape_result.sample_images)
        if not movie.cover_url and scrape_result.cover_url:
            movie.cover_url = scrape_result.cover_url

        # 演员处理
        new_actor_names: set[str] = set()
        if scrape_result.actors:
            new_actor_names = {a.name for a in scrape_result.actors}
            movie.actor = ",".join(sorted(new_actor_names))

            # 清除旧的 movie_actors 关联
            from app.db.uncensored_models import MovieActor as UMovieActor
            old_ma_q = select(UMovieActor).where(UMovieActor.movie_id == movie.id)
            for ma_row in (await session.execute(old_ma_q)).scalars().all():
                await session.delete(ma_row)

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
                # 写入 movie_actors 关联表
                await session.flush()
                ex2 = await session.execute(select(UncensoredActor).where(UncensoredActor.name == actor_info.name))
                db_actor2 = ex2.scalar_one_or_none()
                if db_actor2:
                    session.add(UMovieActor(movie_id=movie.id, actor_id=db_actor2.id))
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

        # ── NFO 生成（回写到影片所在目录，失败不阻断）──
        try:
            from app.output.nfo import NFOGenerator
            out_dir = str(movie.output_dir) if hasattr(movie, "output_dir") and movie.output_dir else (
                str(_Path(movie.file_path).parent) if movie.file_path else ""
            )
            if out_dir:
                gen = NFOGenerator(output_dir=out_dir)
                actor_names = [a.strip() for a in (movie.actor or "").split(",") if a.strip()]
                nfo_path = gen.generate_from_movie(
                    movie=movie, movie_dir=None, kodi_compatible=True, actor_names=actor_names
                )
                if nfo_path:
                    logger.info(f"无码 NFO 生成成功: {nfo_path}")
        except Exception as nfo_err:
            logger.warning(f"无码 NFO 生成失败 [{movie_id}]: {nfo_err}")

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
        from app.output.nfo import NFOGenerator
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
                                fanart_url=sr.poster_url or sr.cover_url,
                                thumb_url=sr.sample_images[0] if sr.sample_images else sr.thumb_url,
                                referer=sr.cover_url,
                            )
                            if local_media.get("cover"):
                                mv.cover_url = local_media["cover"]
                            elif sr.cover_url:
                                mv.cover_url = sr.cover_url
                            if local_media.get("fanart"):
                                mv.poster_url = local_media["fanart"]
                            if local_media.get("thumb"):
                                mv.thumb_url = local_media["thumb"]
                            if sr.sample_images:
                                mv.sample_images = ",".join(sr.sample_images)

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
                                # 批量刷新+写入 movie_actors 关联表
                                await s.flush()
                                try:
                                    from app.db.uncensored_models import MovieActor as UMovieActor
                                    old_ma_q = select(UMovieActor).where(UMovieActor.movie_id == mv.id)
                                    for ma_row in (await s.execute(old_ma_q)).scalars().all():
                                        await s.delete(ma_row)
                                    for ai in sr.actors:
                                        ex2 = await s.execute(select(UncensoredActor).where(UncensoredActor.name == ai.name))
                                        db_actor = ex2.scalar_one_or_none()
                                        if db_actor:
                                            s.add(UMovieActor(movie_id=mv.id, actor_id=db_actor.id))
                                except Exception as ae:
                                    logger.debug(f"无码批量刮削写入演员关联失败 [{mv.code}]: {ae}")
                            mv.source = sr.source or "scraper"
                            mv.status = "scraped"
                            await s.commit()
                            mv_dir = None
                            if hasattr(mv, "output_dir") and mv.output_dir:
                                mv_dir = str(mv.output_dir)
                            elif hasattr(mv, "file_path") and mv.file_path:
                                mv_dir = _os.path.dirname(str(mv.file_path))
                            try:
                                if mv_dir and _os.path.isdir(mv_dir):
                                    actor_names = [a.strip() for a in (mv.actor or "").split(",") if a.strip()]
                                    NFOGenerator(output_dir=mv_dir).generate_from_movie(
                                        mv, movie_dir=None, kodi_compatible=True, actor_names=actor_names
                                    )
                            except Exception as nfo_err:
                                logger.debug(f"无码批量NFO生成失败 [{mv.code}]: {nfo_err}")
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


# ========== 按番号刮削(前端 scrape/movie 端点) ==========


@router.post("/scrape/movie")
async def scrape_uncensored_by_code(body: dict):
    """按番号刮削，如果影片存在则重刮，不存在则创建后刮削"""
    code = str(body.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="番号不能为空")

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select

        stmt = select(UncensoredMovie).where(UncensoredMovie.code == code)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()

        if movie:
            movie_id = movie.id
        else:
            session.add(UncensoredMovie(code=code, title=code, status="pending"))
            await session.commit()
            stmt2 = select(UncensoredMovie).where(UncensoredMovie.code == code)
            r2 = await session.execute(stmt2)
            movie = r2.scalar_one_or_none()
            if not movie:
                raise HTTPException(status_code=500, detail="创建影片失败")
            movie_id = movie.id
    finally:
        await session.close()

    return await scrape_uncensored_movie(movie_id)


@router.post("/scrape/batch")
async def scrape_uncensored_batch(body: dict, background_tasks: BackgroundTasks):
    """批量刮削"""
    movie_ids = body.get("movie_ids", [])
    if not movie_ids:
        return {"status": "error", "message": "未提供影片ID列表"}

    from app.db.uncensored_models import UncensoredMovie
    from app.scraper.engine import get_scraper_engine
    from app.utils.media_helpers import ensure_movie_media_local, ensure_actor_avatar_local
    from sqlalchemy import select

    db = get_uncensored_db()
    engine = get_scraper_engine()
    session = await db.get_session()
    try:
        stmt = select(UncensoredMovie).where(UncensoredMovie.id.in_(movie_ids))
        result = await session.execute(stmt)
        movies = result.scalars().all()
    finally:
        await session.close()

    if not movies:
        return {"status": "error", "message": "未找到任何影片"}

    async def _batch_scrape():
        success = 0
        failed = 0
        for m in movies:
            try:
                sr = await engine.scrape_number(m.code, module="uncensored")
                if sr and sr.title:
                    s = await db.get_session()
                    try:
                        stmt = select(UncensoredMovie).where(UncensoredMovie.id == m.id)
                        res = await s.execute(stmt)
                        mv = res.scalar_one_or_none()
                        if mv:
                            mv.title = sr.title
                            if sr.cover_url:
                                mv.cover_url = sr.cover_url
                            if sr.actors:
                                mv.actor = ",".join(a.name for a in sr.actors)
                            if sr.genres:
                                mv.genre = ",".join(sr.genres)
                            if sr.release_date:
                                mv.release_date = str(sr.release_date)
                            if sr.duration:
                                mv.duration = sr.duration
                            mv.status = "scraped"
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except Exception:
                failed += 1
        logger.info(f"无码批量刮削完成: 成功{success}, 失败{failed}")

    background_tasks.add_task(_batch_scrape)
    return {"status": "started", "total": len(movies)}


@router.post("/scrape")
async def start_scraping_uncensored(body: dict, background_tasks: BackgroundTasks):
    """启动刮削任务"""
    mode = body.get("mode", "all")
    if mode == "all":
        return await scrape_all_pending_uncensored(background_tasks)
    return {"status": "ok", "message": f"刮削模式: {mode}"}


@router.get("/scraping/status")
async def get_uncensored_scraping_status():
    """获取刮削状态"""
    return {"status": "idle", "progress": 0, "total": 0, "completed": 0, "failed": 0}


@router.get("/scraping/pending")
async def get_uncensored_pending_scrape():
    """获取待刮削影片数量"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select, func
        stmt = select(func.count(UncensoredMovie.id)).where(UncensoredMovie.status == "pending")
        total = await session.scalar(stmt) or 0
        return {"total": total}
    finally:
        await session.close()


@router.get("/search/movie")
async def search_uncensored_movie(code: str = Query(...)):
    """搜索无码影片"""
    from app.scraper.engine import get_scraper_engine
    engine = get_scraper_engine()
    try:
        result = await engine.scrape_number(code, module="uncensored")
        if result:
            return {
                "status": "found",
                "code": result.code,
                "title": result.title,
                "cover_url": result.cover_url,
                "actors": [a.name for a in result.actors],
                "genres": result.genres,
                "source": result.source,
                "release_date": str(result.release_date) if result.release_date else None,
                "duration": result.duration,
                "studio": result.studio,
                "sample_images": result.sample_images,
            }
        return {"status": "not_found", "code": code}
    except Exception as e:
        return {"status": "error", "code": code, "message": str(e)}


@router.get("/scrape/special")
async def get_uncensored_special_scrape():
    """获取特殊刮削配置"""
    return {
        "sites": ["javbus", "javdb", "avsox"],
        "description": "无码特殊刮削：支持指定站点强制重刮",
    }


@router.post("/scrape/special")
async def execute_uncensored_special_scrape(body: dict):
    """执行特殊刮削"""
    code = str(body.get("code") or "").strip().upper()
    site = str(body.get("site") or "").strip().lower()
    url = str(body.get("url") or "").strip()
    movie_id = body.get("movie_id")

    if not code:
        raise HTTPException(status_code=400, detail="番号不能为空")

    from app.scraper.engine import get_scraper_engine
    engine = get_scraper_engine()

    sources = [site] if site in ("javbus", "javdb", "avsox") else None
    try:
        scrape_result = await engine.scrape_number(code, sources=sources, module="uncensored")
    except Exception as e:
        scrape_result = await engine.scrape_number(code, module="uncensored")

    if not scrape_result or not scrape_result.title:
        return {"status": "error", "message": f"未找到 {code} 的数据"}

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        target_id = movie_id
        if not target_id:
            stmt = select(UncensoredMovie).where(UncensoredMovie.code == code)
            r = await session.execute(stmt)
            m = r.scalar_one_or_none()
            if not m:
                return {"status": "error", "message": "影片不存在，请先创建"}
            target_id = m.id

        stmt = select(UncensoredMovie).where(UncensoredMovie.id == target_id)
        r = await session.execute(stmt)
        movie = r.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        movie.title = scrape_result.title
        if scrape_result.cover_url:
            movie.cover_url = scrape_result.cover_url
        if scrape_result.actors:
            movie.actor = ",".join(a.name for a in scrape_result.actors)
        if scrape_result.genres:
            movie.genre = ",".join(scrape_result.genres)
        if scrape_result.release_date:
            movie.release_date = str(scrape_result.release_date)
        if scrape_result.duration:
            movie.duration = scrape_result.duration
        if scrape_result.sample_images:
            movie.sample_images = ",".join(scrape_result.sample_images)
        movie.status = "scraped"
        movie.source = scrape_result.source
        await session.commit()

        return {"status": "ok", "message": f"特殊刮削成功: {scrape_result.title}", "movie_id": target_id}
    finally:
        await session.close()


@router.post("/test/code")
async def test_uncensored_code(body: dict):
    """测试番号能否被刮削到"""
    code = str(body.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="番号不能为空")

    from app.scraper.engine import get_scraper_engine
    engine = get_scraper_engine()
    try:
        result = await engine.scrape_number(code, module="uncensored")
        if result:
            return {
                "status": "ok",
                "found": True,
                "code": result.code,
                "title": result.title,
                "cover_url": result.cover_url,
                "actors": [a.name for a in result.actors],
                "genres": result.genres,
                "source": result.source,
                "release_date": str(result.release_date) if result.release_date else None,
                "duration": result.duration,
                "sample_images_count": len(result.sample_images) if result.sample_images else 0,
            }
        return {"status": "ok", "found": False, "code": code, "message": "未找到该番号的元数据"}
    except Exception as e:
        return {"status": "error", "found": False, "code": code, "message": str(e)}


@router.post("/folders/check")
async def check_uncensored_folder(body: dict):
    """检查文件夹中的无码影片"""
    from app.scraper.number import extract_number
    import os

    folder_path = str(body.get("folder_path") or "").strip()
    if not folder_path or not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail="文件夹不存在")

    videos = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"):
                code_result = extract_number(f)
                videos.append({
                    "file": f,
                    "path": os.path.join(root, f),
                    "code": code_result.number if code_result else None,
                    "is_uncensored": bool(getattr(code_result, "is_uncensored", None)),
                })
    return {"total": len(videos), "videos": videos}


@router.post("/movies/import-nfo")
async def import_uncensored_nfo(body: dict):
    """从NFO目录导入影片信息"""
    from app.scraper.number import extract_number
    import os
    from xml.etree import ElementTree as ET

    folder_path = str(body.get("folder_path") or "").strip()
    if not folder_path or not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail="文件夹不存在")

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        added = 0
        updated = 0

        for root, _, files in os.walk(folder_path):
            for f in files:
                if not f.lower().endswith(".nfo"):
                    continue
                nfo_path = os.path.join(root, f)
                code = None
                try:
                    with open(nfo_path, "r", encoding="utf-8") as fh:
                        tree = ET.parse(fh)
                    root_el = tree.getroot()
                    code_el = root_el.find("uniqueid")
                    if code_el is not None and code_el.get("type") == "JAVDB":
                        code = code_el.text
                    else:
                        code_el2 = root_el.find("code")
                        if code_el2 is not None:
                            code = code_el2.text
                except Exception:
                    code_result = extract_number(f.replace(".nfo", ""))
                    code = code_result.number if code_result else None

                if not code:
                    continue
                code = code.upper()
                stmt = select(UncensoredMovie).where(UncensoredMovie.code == code)
                r = await session.execute(stmt)
                movie = r.scalar_one_or_none()
                if movie:
                    updated += 1
                else:
                    session.add(UncensoredMovie(code=code, title=code, status="pending"))
                    added += 1

        await session.commit()
        return {"status": "ok", "message": f"从NFO导入完成", "added": added, "updated": updated}
    finally:
        await session.close()


@router.post("/movies/scan")
async def scan_uncensored_directory(body: dict):
    """扫描目录添加影片"""
    return await check_uncensored_folder(body)


@router.post("/movies/{movie_id}/reload-nfo")
async def reload_uncensored_movie_nfo(movie_id: int):
    """重新生成影片NFO"""
    from app.output.nfo import NFOGenerator

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        r = await session.execute(stmt)
        movie = r.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        out_dir = str(_Path(movie.file_path).parent) if movie.file_path else ""
        if not out_dir:
            return {"status": "error", "message": "无文件路径，无法生成NFO"}

        gen = NFOGenerator(output_dir=out_dir)
        actor_names = [a.strip() for a in (movie.actor or "").split(",") if a.strip()]
        nfo_path = gen.generate_from_movie(movie=movie, movie_dir=None, kodi_compatible=True, actor_names=actor_names)
        return {"status": "ok", "nfo_path": nfo_path}
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/{movie_id}/refresh-images")
async def refresh_uncensored_movie_images(movie_id: int):
    """刷新影片预览图"""
    from app.scraper.engine import get_scraper_engine

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        r = await session.execute(stmt)
        movie = r.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        engine = get_scraper_engine()
        scrape_result = await engine.scrape_number(movie.code, module="uncensored")
        if scrape_result and scrape_result.sample_images:
            movie.sample_images = ",".join(scrape_result.sample_images)
            if scrape_result.cover_url:
                movie.cover_url = scrape_result.cover_url
            await session.commit()
            return {"status": "ok", "sample_count": len(scrape_result.sample_images)}
        return {"status": "error", "message": "刮削未返回预览图"}
    finally:
        await session.close()


# 已移除: /movies/{id}/poster (AI海报开发中)
# 已移除: /movies/{id}/media/refill (媒体补全开发中)
# 已移除: /covers/refresh (封面刷新开发中)
@router.post("/movies/{movie_id}/media")
async def get_uncensored_media_info(movie_id: int):
    """获取影片媒体信息（播放信息）"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        r = await session.execute(stmt)
        movie = r.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "movie_id": movie.id,
            "code": movie.code,
            "title": movie.title,
            "file_path": movie.file_path,
            "file_size": movie.file_size,
            "cover_url": movie.cover_url,
            "duration": movie.duration,
            "status": movie.status,
        }
    finally:
        await session.close()


@router.get("/covers/problems")
async def detect_uncensored_cover_problems(page: int = 1, page_size: int = 20):
    """检测封面问题"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(
            (UncensoredMovie.cover_url.is_(None)) | (UncensoredMovie.cover_url == "")
        ).offset((page - 1) * page_size).limit(page_size)
        r = await session.execute(stmt)
        items = []
        for m in r.scalars().all():
            items.append({"id": m.id, "code": m.code, "title": m.title, "cover_url": m.cover_url})
        return {"items": items, "total": len(items)}
    finally:
        await session.close()


@router.post("/covers/refresh")
async def refresh_uncensored_covers(body: dict):
    """批量刷新封面：对全部影片重新触发刮削并下载封面"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select, update as sq_update
        # 将已刮削影片的 cover_url/thumb_url/poster_url 置空，重新刮削时会重新下载
        stmt = sq_update(UncensoredMovie).where(
            UncensoredMovie.status == "scraped"
        ).values(cover_url=None, thumb_url=None, poster_url=None, status="pending")
        result = await session.execute(stmt)
        await session.commit()
        return {"status": "ok", "updated": result.rowcount}
    finally:
        await session.close()


@router.get("/stats")
async def get_uncensored_stats():
    """获取统计信息"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie, UncensoredActor
        from sqlalchemy import select, func
        movie_count = await session.scalar(select(func.count(UncensoredMovie.id))) or 0
        actor_count = await session.scalar(select(func.count(UncensoredActor.id))) or 0
        scraped = await session.scalar(
            select(func.count(UncensoredMovie.id)).where(UncensoredMovie.status == "scraped")
        ) or 0
        pending = await session.scalar(
            select(func.count(UncensoredMovie.id)).where(UncensoredMovie.status == "pending")
        ) or 0
        return {"movies": movie_count, "actors": actor_count, "scraped": scraped, "pending": pending}
    finally:
        await session.close()


@router.get("/tags")
async def list_uncensored_tags(page: int = 1, page_size: int = 50):
    """获取无码标签列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select, func
        stmt = select(UncensoredMovie.genre).where(
            (UncensoredMovie.genre != None) & (UncensoredMovie.genre != "")
        )
        r = await session.execute(stmt)
        genres = [row[0] for row in r.fetchall() if row[0]]
        all_tags = set()
        for g in genres:
            for t in g.split(","):
                t = t.strip()
                if t:
                    all_tags.add(t)
        tag_list = sorted(all_tags)[(page - 1) * page_size : page * page_size]
        return {"items": [{"id": i + 1, "name": t} for i, t in enumerate(tag_list)], "total": len(all_tags)}
    finally:
        await session.close()


# 已移除: favorites/subscriptions (无用户系统) / crawlers/logs (无日志系统)
# 已移除: /movies/{id}/poster (AI海报) /media/refill /covers/refresh (开发中桩)


@router.get("/genres")
async def list_uncensored_genres():
    """获取无码分类列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie.genre).where(
            (UncensoredMovie.genre != None) & (UncensoredMovie.genre != "")
        )
        r = await session.execute(stmt)
        genres = [row[0] for row in r.fetchall() if row[0]]
        all_tags = set()
        for g in genres:
            for t in g.split(","):
                t = t.strip()
                if t:
                    all_tags.add(t)
        return {"items": [{"id": i + 1, "name": t} for i, t in enumerate(sorted(all_tags))], "total": len(all_tags)}
    finally:
        await session.close()


@router.post("/actors/search")
async def search_uncensored_actors(body: dict = None):
    """搜索无码演员"""
    from fastapi import Request
    if body:
        keyword = str(body.get("keyword") or body.get("search") or "").strip()
    else:
        keyword = ""
    if not keyword:
        return {"items": [], "total": 0}
    return await search_similar_actors_uncensored(keyword)


async def search_similar_actors_uncensored(keyword: str):
    """搜索无码演员"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select
        stmt = select(UncensoredActor).where(
            UncensoredActor.name.ilike(f"%{keyword}%")
        ).limit(20)
        r = await session.execute(stmt)
        items = []
        for a in r.scalars().all():
            items.append({"id": a.id, "name": a.name, "avatar_url": a.avatar_url, "movie_count": a.movie_count})
        return {"items": items, "total": len(items)}
    finally:
        await session.close()


# 播放器端点: /play/{movieId}/info 和 /play/{movieId}/url
@router.get("/play/{movie_id}/info")
async def get_uncensored_play_info(movie_id: int):
    """获取播放信息"""
    return await get_uncensored_movie_play(movie_id)


@router.get("/play/{movie_id}/url")
async def get_uncensored_play_url(movie_id: int):
    """获取播放URL"""
    return await get_uncensored_movie_play(movie_id)


# 已移除重复的 GET /movies/{movie_id}/play 路由定义
# 保留第一个 play_uncensored_movie 函数（含完整字段：file_size, file_exists, status）


# 演员影片列表
@router.get("/actors/{actor_id}/movies")
async def get_uncensored_actor_movies(actor_id: int, page: int = 1, page_size: int = 24):
    """获取演员的影片列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor, UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredActor).where(UncensoredActor.id == actor_id)
        r = await session.execute(stmt)
        actor = r.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        stmt = select(UncensoredMovie).where(UncensoredMovie.actor.contains(actor.name))
        r = await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        items = []
        for m in r.scalars().all():
            items.append({
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url, "release_date": m.release_date,
                "duration": m.duration, "status": m.status,
            })
        return {"actor": {"id": actor.id, "name": actor.name}, "items": items, "total": len(items)}
    finally:
        await session.close()


# 创建影片
@router.post("/movies")
async def create_uncensored_movie(body: dict):
    """创建无码影片"""
    code = str(body.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="番号不能为空")

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.code == code)
        r = await session.execute(stmt)
        existing = r.scalar_one_or_none()
        if existing:
            return {"status": "exists", "id": existing.id}

        movie = UncensoredMovie(
            code=code,
            title=code,
            status="pending",
        )
        session.add(movie)
        await session.commit()
        return {"status": "created", "id": movie.id, "code": code}
    finally:
        await session.close()


# 更新/删除影片
@router.put("/movies/{movie_id}")
async def update_uncensored_movie(movie_id: int, body: dict):
    """更新无码影片"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        r = await session.execute(stmt)
        movie = r.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        for field in ("title", "original_title", "actor", "studio", "genre", "tag",
                      "release_date", "duration", "plot", "cover_url", "poster_url",
                      "thumb_url", "sample_images", "status", "rating"):
            if field in body:
                setattr(movie, field, body[field])
        await session.commit()
        return {"status": "ok", "id": movie.id}
    finally:
        await session.close()


@router.delete("/movies/{movie_id}")
async def delete_uncensored_movie(movie_id: int):
    """删除无码影片"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select, delete
        stmt = delete(UncensoredMovie).where(UncensoredMovie.id == movie_id)
        await session.execute(stmt)
        await session.commit()
        return {"status": "ok"}
    finally:
        await session.close()


# 创建/更新/删除演员
@router.post("/actors")
async def create_uncensored_actor(body: dict):
    """创建无码演员"""
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="演员名不能为空")

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select
        stmt = select(UncensoredActor).where(UncensoredActor.name == name)
        r = await session.execute(stmt)
        existing = r.scalar_one_or_none()
        if existing:
            return {"status": "exists", "id": existing.id}

        actor = UncensoredActor(
            name=name,
            avatar_url=body.get("avatar_url"),
            alias=body.get("alias"),
            birthday=body.get("birthday"),
            source="manual",
            movie_count=0,
        )
        session.add(actor)
        await session.commit()
        return {"status": "created", "id": actor.id}
    finally:
        await session.close()


@router.put("/actors/{actor_id}")
async def update_uncensored_actor(actor_id: int, body: dict):
    """更新无码演员"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select
        stmt = select(UncensoredActor).where(UncensoredActor.id == actor_id)
        r = await session.execute(stmt)
        actor = r.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        for field in ("name", "avatar_url", "alias", "birthday", "bio", "source"):
            if field in body:
                setattr(actor, field, body[field])
        await session.commit()
        return {"status": "ok", "id": actor.id}
    finally:
        await session.close()


@router.delete("/actors/{actor_id}")
async def delete_uncensored_actor(actor_id: int):
    """删除无码演员"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import delete
        stmt = delete(UncensoredActor).where(UncensoredActor.id == actor_id)
        await session.execute(stmt)
        await session.commit()
        return {"status": "ok"}
    finally:
        await session.close()


@router.post("/actors/{actor_id}/avatar")
async def download_uncensored_actor_avatar(actor_id: int, body: dict):
    """从 URL 下载无码演员头像到本地"""
    from app.utils.media_helpers import ensure_actor_avatar_local
    url = body.get("avatar_url", "")
    if not url:
        raise HTTPException(status_code=400, detail="需要提供 avatar_url")
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredActor
        from sqlalchemy import select
        actor = (await session.execute(select(UncensoredActor).where(UncensoredActor.id == actor_id))).scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        local_avatar = await ensure_actor_avatar_local(actor.name, url)
        if local_avatar:
            actor.avatar_url = local_avatar
            await session.commit()
            return {"status": "ok", "avatar_url": local_avatar}
        return {"status": "error", "message": "下载失败"}
    finally:
        await session.close()


# 创建/更新/删除片商
@router.post("/studios")
async def create_uncensored_studio(body: dict):
    """创建无码片商"""
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="片商名不能为空")

    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredStudio
        from sqlalchemy import select
        stmt = select(UncensoredStudio).where(UncensoredStudio.name == name)
        r = await session.execute(stmt)
        existing = r.scalar_one_or_none()
        if existing:
            return {"status": "exists", "id": existing.id}

        studio = UncensoredStudio(name=name, website=body.get("website"), logo_url=body.get("logo_url"))
        session.add(studio)
        await session.commit()
        return {"status": "created", "id": studio.id}
    finally:
        await session.close()


@router.put("/studios/{studio_id}")
async def update_uncensored_studio(studio_id: int, body: dict):
    """更新无码片商"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredStudio
        from sqlalchemy import select
        stmt = select(UncensoredStudio).where(UncensoredStudio.id == studio_id)
        r = await session.execute(stmt)
        studio = r.scalar_one_or_none()
        if not studio:
            raise HTTPException(status_code=404, detail="片商不存在")

        for field in ("name", "website", "logo_url"):
            if field in body:
                setattr(studio, field, body[field])
        await session.commit()
        return {"status": "ok", "id": studio.id}
    finally:
        await session.close()


@router.delete("/studios/{studio_id}")
async def delete_uncensored_studio(studio_id: int):
    """删除无码片商"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredStudio
        from sqlalchemy import delete
        stmt = delete(UncensoredStudio).where(UncensoredStudio.id == studio_id)
        await session.execute(stmt)
        await session.commit()
        return {"status": "ok"}
    finally:
        await session.close()


# 片商影片列表
@router.get("/studios/{studio_id}/movies")
async def get_uncensored_studio_movies(studio_id: int, page: int = 1, page_size: int = 24):
    """获取片商的影片列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredStudio, UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredStudio).where(UncensoredStudio.id == studio_id)
        r = await session.execute(stmt)
        studio = r.scalar_one_or_none()
        if not studio:
            raise HTTPException(status_code=404, detail="片商不存在")

        stmt = select(UncensoredMovie).where(UncensoredMovie.studio == studio.name)
        r = await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        items = []
        for m in r.scalars().all():
            items.append({
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url, "release_date": m.release_date,
            })
        return {"studio": {"id": studio.id, "name": studio.name}, "items": items, "total": len(items)}
    finally:
        await session.close()


# 分类影片列表
@router.get("/genres/{genre_id}/movies")
async def get_uncensored_genre_movies(genre_id: int, page: int = 1, page_size: int = 24):
    """获取分类的影片列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select
        stmt = select(UncensoredMovie).where(UncensoredMovie.genre.contains(str(genre_id)))
        r = await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        items = []
        for m in r.scalars().all():
            items.append({
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url, "release_date": m.release_date,
            })
        return {"items": items, "total": len(items)}
    finally:
        await session.close()


# 爬虫设置端点
@router.get("/crawlers/stats")
async def get_uncensored_crawlers_stats():
    """获取爬虫统计"""
    from app.crawlers.provider import get_crawlers_for_module
    crawlers = get_crawlers_for_module("uncensored")
    return {
        "total": len(crawlers),
        "crawlers": [{"name": c.name, "display_name": c.display_name, "priority": c.priority} for c in crawlers],
    }


@router.put("/crawlers/{crawler_id}/enabled")
async def set_uncensored_crawler_enabled(crawler_id: str, body: dict):
    """启用/禁用爬虫"""
    enabled = bool(body.get("enabled", True))
    from app.crawlers.provider import get_crawler
    crawler = get_crawler(crawler_id)
    if not crawler:
        raise HTTPException(status_code=404, detail="爬虫不存在")
    if enabled:
        crawler.enable()
    else:
        crawler.disable()
    return {"status": "ok", "name": crawler_id, "enabled": enabled}


@router.put("/crawlers/{crawler_id}/priority")
async def set_uncensored_crawler_priority(crawler_id: str, body: dict):
    """设置爬虫优先级"""
    priority = int(body.get("priority", 0))
    from app.crawlers.provider import get_crawler
    crawler = get_crawler(crawler_id)
    if not crawler:
        raise HTTPException(status_code=404, detail="爬虫不存在")
    crawler.priority = priority
    return {"status": "ok", "name": crawler_id, "priority": crawler.priority}


@router.get("/crawlers/logs")
async def get_uncensored_crawler_logs(limit: int = 100):
    """获取爬虫日志（暂未实现持久化日志）"""
    return {"items": [], "total": 0, "note": "日志系统暂未实现持久化"}


@router.get("/crawlers/settings")
async def get_uncensored_crawler_settings():
    """获取爬虫设置"""
    from app.crawlers.provider import get_crawlers_for_module
    crawlers = get_crawlers_for_module("uncensored")
    settings = {}
    for c in crawlers:
        settings[c.name] = {
            "display_name": c.display_name,
            "priority": c.priority,
            "requires_proxy": c.requires_proxy,
            "description": c.description,
        }
    return settings


@router.put("/crawlers/settings")
async def update_uncensored_crawler_settings(body: dict):
    """更新爬虫设置"""
    return {"status": "ok"}



