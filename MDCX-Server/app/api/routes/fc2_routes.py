"""
FC2 模块 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request as _Request

from app.db.module_db import ModuleDatabase

import json
import os as _os
from pathlib import Path as _Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fc2", tags=["FC2模块"])


def get_fc2_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("fc2")


@router.get("/actors")
async def list_actors(search: Optional[str] = Query(None, description="按名字/日文名/别名搜索")):
    """列出 FC2 演员列表"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Actor
        from sqlalchemy import select, or_
        stmt = select(Fc2Actor)
        if search:
            alias_col = getattr(Fc2Actor, "alias", None)
            cond = or_(
                Fc2Actor.name.contains(search),
                Fc2Actor.name_jp.contains(search),
                Fc2Actor.name_en.contains(search),
            )
            if alias_col is not None:
                cond = or_(cond, alias_col.contains(search))
            stmt = stmt.where(cond)
        stmt = stmt.order_by(Fc2Actor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count, "source": a.source, "avatar_url": a.avatar_url, "module_type": "fc2"} for a in actors]
    finally:
        await session.close()


@router.get("/studios")
async def list_studios(search: Optional[str] = Query(None, description="按名字/日文名/别名搜索")):
    """列出 FC2 厂商列表"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Studio
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
        return [{"id": s.id, "name": s.name, "name_jp": s.name_jp, "movie_count": s.movie_count, "module_type": "fc2"} for s in studios]
    finally:
        await session.close()


@router.get("/studios/{studio_id}")
async def get_studio(studio_id: int):
    """获取 FC2 厂商详情"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Studio
        from sqlalchemy import select
        stmt = select(Studio).where(Studio.id == studio_id)
        result = await session.execute(stmt)
        studio = result.scalars().first()
        if not studio:
            raise HTTPException(status_code=404, detail="厂商不存在")
        return {"id": studio.id, "name": studio.name, "name_jp": studio.name_jp,
                "movie_count": studio.movie_count, "module_type": "fc2"}
    finally:
        await session.close()


# ========== 封面端点（纯本地查找，不连外网） ==========


@router.get("/movies/{movie_id}/cover/file")
async def get_fc2_cover_file(movie_id: int):
    """获取 FC2 影片封面图片文件"""
    from fastapi.responses import FileResponse, Response
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )
    from app.db.fc2_models import Fc2Movie

    db = get_fc2_db()
    session = await db.get_session()
    try:
        movie = await session.get(Fc2Movie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 1) 规范目录：{data_base}/movies/fc2/{code}/poster.jpg
        if movie.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path("fc2", movie.code)
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

        # 3) 视频目录下
        if movie.file_path:
            try:
                video_dir = _Path(movie.file_path).parent
                import asyncio
                for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg", "thumb.jpg"]:
                    img_path = video_dir / img_name
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

        # 4) SVG 占位图
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


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取 FC2 演员详情"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Actor
        from sqlalchemy import select
        stmt = select(Fc2Actor).where(Fc2Actor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"id": actor.id, "name": actor.name, "alias": actor.alias,
                "avatar_url": actor.avatar_url, "source": actor.source,
                "module_type": "fc2",
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
    """列出 FC2 模块影片列表"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select, func, or_

        filters = []
        if keyword:
            kw = f"%{keyword}%"
            filters.append(or_(Fc2Movie.title.like(kw), Fc2Movie.code.like(kw)))
        if actor:
            filters.append(Fc2Movie.actor.like(f"%{actor}%"))
        if series:
            filters.append(Fc2Movie.series == series)
        if maker:
            filters.append(or_(Fc2Movie.maker == maker, Fc2Movie.studio == maker))
        if genre:
            filters.append(Fc2Movie.genre.contains(genre))
        if code_prefix:
            filters.append(Fc2Movie.code.startswith(code_prefix))

        total_stmt = select(func.count(Fc2Movie.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()

        stmt = select(Fc2Movie)
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.order_by(Fc2Movie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()

        pending_stmt = select(func.count(Fc2Movie.id)).where(Fc2Movie.status == "pending")
        pending_result = await session.execute(pending_stmt)
        pending_count = pending_result.scalar()

        return {"total": total, "pending_count": pending_count or 0, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "seller_id": m.seller_id, "is_mosaic": m.is_mosaic,
             "is_chinese": m.is_chinese, "is_uncensored": m.is_uncensored,
             "is_leak": m.is_leak, "is_4k": m.is_4k,
             "cover_url": m.cover_url, "actor": m.actor,
             "module_type": "fc2",
             "file_path": m.file_path, "status": m.status}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取 FC2 影片详情"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select
        stmt = select(Fc2Movie).where(Fc2Movie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "original_title": movie.original_title,
            "is_mosaic": movie.is_mosaic, "seller_id": movie.seller_id,
            "is_chinese": movie.is_chinese, "is_uncensored": movie.is_uncensored,
            "is_leak": movie.is_leak, "is_4k": movie.is_4k,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "actor": movie.actor, "studio": movie.studio,
            "module_type": "fc2",
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


# ========== 相关推荐与演员端点（通用详情页使用） ==========


@router.get("/movies/{movie_id}/related")
async def get_fc2_related_movies(movie_id: int):
    """获取FC2影片的相关推荐（同演员/同类别）"""
    from sqlalchemy import select, or_, and_
    from app.db.fc2_models import Fc2Movie

    db = get_fc2_db()
    session = await db.get_session()
    try:
        movie = await session.get(Fc2Movie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        related_ids = {movie_id}
        actor_movies = []
        genre_movies = []
        limit = 12

        if movie.actor:
            actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
            if actor_names:
                filters = [Fc2Movie.actor.contains(name) for name in actor_names]
                stmt = select(Fc2Movie).where(
                    and_(or_(*filters), Fc2Movie.id != movie_id)
                ).order_by(Fc2Movie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        actor_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "fc2", "cover_url": m.cover_url,
                        })

        if movie.genre:
            genre_parts = [g.strip() for g in movie.genre.split(",") if g.strip()]
            if genre_parts:
                genre_filters = [Fc2Movie.genre.contains(gp) for gp in genre_parts[:5]]
                stmt = select(Fc2Movie).where(
                    and_(or_(*genre_filters), Fc2Movie.id != movie_id)
                ).order_by(Fc2Movie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        genre_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "fc2", "cover_url": m.cover_url,
                        })

        return {
            "actor_movies": actor_movies[:limit],
            "series_movies": [],
            "genre_movies": genre_movies[:limit],
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/actors")
async def get_fc2_movie_actors(movie_id: int):
    """获取FC2影片关联的演员列表"""
    from app.db.fc2_models import Fc2Movie, Fc2Actor

    db = get_fc2_db()
    session = await db.get_session()
    try:
        movie = await session.get(Fc2Movie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        if not movie.actor:
            return {"items": []}
        actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
        items = []
        for name in actor_names:
            stmt = select(Fc2Actor).where(Fc2Actor.name == name)
            result = await session.execute(stmt)
            actor = result.scalar_one_or_none()
            if actor:
                items.append({"id": actor.id, "name": actor.name, "avatar_url": actor.avatar_url})
            else:
                items.append({"id": name, "name": name, "avatar_url": None})
        return {"items": items}
    finally:
        await session.close()


# ========== 刮削 ==========


@router.post("/movies/{movie_id}/scrape")
async def scrape_fc2_movie(movie_id: int):
    """刮削指定 FC2 影片的元数据"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie, Fc2Actor
        from sqlalchemy import select

        stmt = select(Fc2Movie).where(Fc2Movie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        from app.scraper.engine import get_scraper_engine
        engine = get_scraper_engine()
        scrape_result = await engine.scrape_number(movie.code, module="fc2")

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
        if scrape_result.maker:
            movie.maker = scrape_result.maker
        if scrape_result.director:
            movie.director = scrape_result.director
        if scrape_result.series:
            movie.series = scrape_result.series
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
            module_name="fc2", code=movie.code,
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
        # 样图/剧照保存到数据库(以 JSON 列表格式，与 NFO 解析器兼容)
        if scrape_result.sample_images:
            movie.sample_images = json.dumps(scrape_result.sample_images, ensure_ascii=False)
        if not movie.cover_url and scrape_result.cover_url:
            movie.cover_url = scrape_result.cover_url

        if scrape_result.actors:
            movie.actor = ",".join(a.name for a in scrape_result.actors)
            for actor_info in scrape_result.actors:
                existing = await session.execute(select(Fc2Actor).where(Fc2Actor.name == actor_info.name))
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
                    session.add(Fc2Actor(
                        name=actor_info.name,
                        avatar_url=local_avatar or actor_info.avatar_url,
                        source="scraper",
                        source_site=scrape_result.source,
                        movie_count=0,
                    ))

        movie.source = scrape_result.source or "scraper"
        if scrape_result.source_url:
            movie.source_url = scrape_result.source_url
        movie.status = "scraped"
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
                    logger.info(f"FC2 NFO 生成成功: {nfo_path}")
        except Exception as nfo_err:
            logger.warning(f"FC2 NFO 生成失败 [{movie_id}]: {nfo_err}")

        return {"status": "ok", "message": f"刮削成功: {scrape_result.title}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FC2 刮削失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/scrape-all-pending")
async def scrape_all_pending_fc2(background_tasks: BackgroundTasks):
    """后台批量刮削所有 status=pending 的 FC2 影片"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select
        stmt = select(Fc2Movie).where(Fc2Movie.status == "pending").order_by(Fc2Movie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待刮削的影片", "total": 0}

    async def _run():
        from app.db.fc2_models import Fc2Movie, Fc2Actor
        from app.scraper.engine import get_scraper_engine
        from app.utils.media_helpers import ensure_movie_media_local, ensure_actor_avatar_local
        from app.output.nfo import NFOGenerator
        engine = get_scraper_engine()
        success = failed = 0
        for m in pending:
            try:
                sr = await engine.scrape_number(m.code)
                if sr and sr.title:
                    s = await db.get_session()
                    try:
                        st = select(Fc2Movie).where(Fc2Movie.id == m.id)
                        r = await s.execute(st)
                        mv = r.scalar_one_or_none()
                        if mv:
                            old_actors = mv.actor.split(",") if mv.actor else []
                            mv.title = sr.title
                            if sr.original_title:
                                mv.original_title = sr.original_title
                            if sr.release_date:
                                mv.release_date = str(sr.release_date)
                            if sr.duration:
                                mv.duration = sr.duration
                            if sr.plot:
                                mv.plot = sr.plot[:2000]
                            if sr.studio:
                                mv.studio = sr.studio
                            if sr.maker:
                                mv.maker = sr.maker
                            if sr.director:
                                mv.director = sr.director
                            if sr.series:
                                mv.series = sr.series
                            if sr.genres:
                                mv.genre = ",".join(sr.genres)
                            if sr.tags:
                                mv.tag = ",".join(sr.tags)

                            local_media = await ensure_movie_media_local(
                                module_name="fc2", code=mv.code,
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
                            # 样图/剧照(以 JSON 列表格式，与 NFO 解析器兼容)
                            if sr.sample_images:
                                mv.sample_images = json.dumps(sr.sample_images, ensure_ascii=False)
                            if sr.actors:
                                new_actor_names = set()
                                mv.actor = ",".join(a.name for a in sr.actors)
                                for ai in sr.actors:
                                    new_actor_names.add(ai.name)
                                    ex = await s.execute(select(Fc2Actor).where(Fc2Actor.name == ai.name))
                                    existing = ex.scalar_one_or_none()
                                    if not existing:
                                        local_avatar = await ensure_actor_avatar_local(ai.name, ai.avatar_url)
                                        new_actor = Fc2Actor(name=ai.name, source="scraper", movie_count=1)
                                        new_actor.avatar_url = local_avatar or ai.avatar_url
                                        s.add(new_actor)
                                    else:
                                        if existing.movie_count < 100:
                                            existing.movie_count += 1
                                        if not existing.avatar_url and ai.avatar_url:
                                            local_avatar = await ensure_actor_avatar_local(ai.name, ai.avatar_url)
                                            existing.avatar_url = local_avatar or ai.avatar_url
                                remove_count = 0
                                for name in old_actors:
                                    n = name.strip()
                                    if n and n not in new_actor_names:
                                        actor_stmt = select(Fc2Actor).where(Fc2Actor.name == n)
                                        actor_result = await s.execute(actor_stmt)
                                        actor_obj = actor_result.scalar_one_or_none()
                                        if actor_obj and actor_obj.movie_count > 0:
                                            actor_obj.movie_count -= 1
                                            if remove_count < 30:
                                                remove_count += 1
                            if sr.rating:
                                try:
                                    mv.rating = float(sr.rating)
                                except:
                                    pass
                            if sr.year:
                                mv.year = sr.year
                            if sr.description:
                                mv.description = sr.description[:2000]
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
                                logger.debug(f"FC2 批量NFO生成失败 [{mv.code}]: {nfo_err}")
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except:
                failed += 1
        logger.info(f"FC2 批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)
    return {"status": "started", "total": len(pending), "message": f"FC2 批量刮削已启动，共 {len(pending)} 部"}


# ========== 播放 ==========


@router.get("/movies/{movie_id}/play")
async def play_fc2_movie(movie_id: int):
    """获取 FC2 影片播放信息"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select
        stmt = select(Fc2Movie).where(Fc2Movie.id == movie_id)
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
async def play_fc2_video_file(movie_id: int, request: _Request):
    """FC2 影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select

        stmt = select(Fc2Movie).where(Fc2Movie.id == movie_id)
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
async def get_fc2_external_play_url(movie_id: int, request: _Request, protocol: str = "http"):
    """获取 FC2 影片外部播放地址"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select

        stmt = select(Fc2Movie).where(Fc2Movie.id == movie_id)
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
            play_url = f"{base}/api/v1/fc2/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
