"""
JAV 有码模块 API 路由

包含：
- 只读端点（列表/详情）
- 刮削端点（单部/批量/自动）
- NFO 导入端点
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jav", tags=["JAV有码"])


def get_jav_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("jav")


# 空头像占位图（与 modules.py 保持一致，避免前端 @error 裂图差异）
_SVG_EMPTY_AVATAR = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" '
    'viewBox="0 0 120 120"><rect width="120" height="120" rx="60" fill="#374151"/>'
    '<text x="60" y="74" text-anchor="middle" font-size="48" font-family="Arial" '
    'fill="#9ca3af">?</text></svg>'
)


def _avatar_placeholder():
    from fastapi.responses import Response
    return Response(content=_SVG_EMPTY_AVATAR, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-cache"})


# ========== 演员合并 ==========


@router.post("/actors/merge")
async def api_merge_actors(data: dict):
    """合并演员（将 source_ids 合并到 canonical_id）"""
    from app.services.actor_merge_service import merge_actors
    db = get_jav_db()
    session = await db.get_session()
    try:
        result = await merge_actors(
            session,
            canonical_id=data.get("canonical_id", 0),
            source_ids=data.get("source_ids", []),
        )
        return result
    finally:
        await session.close()


@router.get("/actors/similar")
async def api_search_similar_actors(name: str = Query(..., description="搜索相似演员")):
    """搜索名字相似的演员（推荐合并候选）"""
    from app.services.actor_merge_service import search_similar_actors
    db = get_jav_db()
    session = await db.get_session()
    try:
        result = await search_similar_actors(session, name)
        return {"items": result, "total": len(result)}
    finally:
        await session.close()


@router.get("/actors/{actor_id}/merge-candidates")
async def api_merge_candidates(actor_id: int):
    """获取指定演员的合并候选列表"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavActor
        from sqlalchemy import select
        from app.services.actor_merge_service import search_similar_actors

        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        candidates = await search_similar_actors(session, actor.name)
        return {"actor": {"id": actor.id, "name": actor.name, "alias": actor.alias, "movie_count": actor.movie_count},
                "candidates": candidates, "total": len(candidates)}
    finally:
        await session.close()


# ========== 番号提取测试 ==========


@router.post("/code-extract-test")
async def api_code_extract_test(data: dict):
    """测试从文件名提取番号

    参考 JavBoss v1.8.0 番号提取测试工具
    """
    filename = data.get("filename", "")
    if not filename:
        return {"error": "filename is required"}

    from app.scraper.number import extract_number, extract_number_from_path
    # 提取番号（先尝试直接文件名）
    result = extract_number(filename)
    codes = []
    if result and result.number:
        codes.append({
            "code": result.number,
            "type": "direct",
            "is_chinese": result.is_chinese,
            "is_uncensored": result.is_uncensored,
        })
    return {
        "filename": filename,
        "extracted_codes": codes,
        "count": len(codes),
    }


# ========== 只读端点 ==========


@router.get("/actors")
async def list_actors():
    """列出有码演员列表"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavActor
        from sqlalchemy import select
        stmt = select(JavActor).order_by(JavActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count,
                 "module_type": "jav",
                 "source": a.source, "avatar_url": a.avatar_url} for a in actors]
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取有码演员详情"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavActor
        from sqlalchemy import select
        stmt = select(JavActor).where(JavActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"id": actor.id, "name": actor.name, "alias": actor.alias,
                    "module_type": "jav",
                    "avatar_url": actor.avatar_url, "source": actor.source,
                    "source_site": actor.source_site, "movie_count": actor.movie_count,
                    "created_at": str(actor.created_at)}
    finally:
        await session.close()


@router.get("/actors/{actor_id}/movies")
async def get_actor_movies(
    actor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    """获取演员作品列表"""
    from app.db.jav_models import JavActor, JavMovie
    from sqlalchemy import select, func, or_

    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        offset = (page - 1) * page_size
        # 搜索含有演员名的影片
        name_part = f"%{actor.name}%"
        total_q = select(func.count(JavMovie.id)).where(JavMovie.actor.like(name_part))
        total = (await session.execute(total_q)).scalar() or 0

        stmt = select(JavMovie).where(JavMovie.actor.like(name_part)) \
            .order_by(JavMovie.release_date.desc().nulls_last(), JavMovie.id.desc()) \
            .offset(offset).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()

        items = []
        for m in rows:
            items.append({
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url, "poster_url": m.poster_url,
                "release_date": str(m.release_date) if m.release_date else None,
                "duration": m.duration, "rating": m.rating,
                "studio": m.studio, "maker": getattr(m, "maker", None),
                "genre": m.genre,
                "module_type": "jav",
                "file_path": m.file_path,
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        await session.close()


@router.get("/actors/{actor_id}/timeline")
async def get_actor_timeline(actor_id: int):
    """获取演员作品时间线

    返回结构必须与前端 ActorDetail.vue 时间线视图严格对齐：
    total / years / details / unknown / year_range / debut_year 缺一不可，
    否则前端 v-if="timeline.total > 0" 直接判空，时间线永远显示"暂无作品"。
    MovieActor 关联表恒为空，只能靠 movie.actor 字段模糊匹配（与 actors.py 一致）。
    """
    from app.db.jav_models import JavActor, JavMovie
    from sqlalchemy import select
    from collections import defaultdict

    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        name_part = f"%{actor.name}%"
        # 查该演员全部作品（含无日期），用于 total 与完整年份分组
        movies = (await session.execute(
            select(JavMovie).where(JavMovie.actor.like(name_part))
        )).scalars().all()

        total = len(movies)

        year_map = defaultdict(list)
        unknown_movies = []
        for m in movies:
            if m.release_date:
                try:
                    y = int(str(m.release_date)[:4])
                except (ValueError, TypeError):
                    y = None
                if y:
                    year_map[y].append(m)
                else:
                    unknown_movies.append(m)
            else:
                unknown_movies.append(m)

        # 年份降序（与前端柱状图一致）
        sorted_years = sorted(year_map.keys(), reverse=True)
        years_data = [{"year": y, "count": len(year_map[y])} for y in sorted_years]

        # 每年来源详情：按日期降序，避免详情与柱状图数量不一致
        details = []
        for y in sorted_years:
            ms = sorted(
                year_map[y],
                key=lambda x: str(x.release_date) if x.release_date else "",
                reverse=True,
            )
            details.append({
                "year": y,
                "count": len(ms),
                "movies": [{
                    "id": m.id, "code": m.code, "title": m.title,
                    "cover_url": m.cover_url,
                    "release_date": m.release_date,
                    "module_type": "jav",
                } for m in ms],
            })

        first_year = sorted_years[-1] if sorted_years else None
        last_year = sorted_years[0] if sorted_years else None
        debut_year = actor.debut_year or first_year

        unknown_data = {
            "year": None,
            "count": len(unknown_movies),
            "movies": [{
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url,
                "release_date": m.release_date,
                "module_type": "jav",
            } for m in unknown_movies],
        } if unknown_movies else None

        return {
            "actor_id": actor_id,
            "actor_name": actor.name,
            "total": total,
            "years": years_data,
            "details": details,
            "unknown": unknown_data,
            "year_range": [first_year, last_year],
            "debut_year": debut_year,
            "module_type": "jav",
        }
    finally:
        await session.close()


@router.get("/actors/{actor_id}/tags")
async def get_actor_tags(actor_id: int):
    """获取演员标签"""
    from app.db.jav_models import JavActor
    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"tags": [], "module_type": "jav"}
    finally:
        await session.close()


@router.get("/actors/{actor_id}/avatar/file")
async def get_actor_avatar_file(actor_id: int):
    """获取演员头像文件"""
    from app.db.jav_models import JavActor
    from fastapi.responses import FileResponse
    from pathlib import Path as _Path

    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        # 优先返回规范目录头像（真实文件路径）
        # 注意: 模块演员模型(JavActor 等)没有 avatar_path 列，getattr 默认 "" → _Path("") 等价
        # Path(".")，其 exists() 为 True；若直接 FileResponse(".") 会抛
        # RuntimeError: File at path . is not a file → HTTP 500。必须校验绝对路径 + is_file()。
        avatar_path = getattr(actor, "avatar_path", "") or ""
        if avatar_path and _Path(avatar_path).is_absolute() and _Path(avatar_path).is_file():
            return FileResponse(str(avatar_path), media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})

        # 优先读取约定文件 DATA/avatars/jav/actor_{id}.jpg（按模块隔离）
        try:
            from app.config.manager import get_config_manager
            avatar_file = _Path(get_config_manager().computed.data_dir) / "avatars" / "jav" / f"actor_{actor_id}.jpg"
            if avatar_file.exists():
                return FileResponse(str(avatar_file), media_type="image/jpeg",
                                    headers={"Cache-Control": "public, max-age=86400"})
        except Exception:
            pass

        # 回退: avatar_url 为真实本地绝对路径时直接返回（gfriends 导入写入的正是此路径）
        avatar_url_field = getattr(actor, "avatar_url", None)
        if avatar_url_field:
            av = str(avatar_url_field).strip()
            if av.startswith(("http://", "https://")):
                # 远程 URL 需前端代理，本端点仅服务本地文件，回退占位图
                pass
            elif _Path(av).is_absolute() and _Path(av).exists():
                return FileResponse(av, media_type="image/jpeg",
                                    headers={"Cache-Control": "public, max-age=86400"})

        return _avatar_placeholder()
    finally:
        await session.close()


@router.get("/movies")
async def list_movies(
    skip: int = 0,
    limit: int = 20,
    keyword: Optional[str] = Query(None, description="搜索标题/番号"),
    actor: Optional[str] = Query(None, description="按演员名过滤"),
    status_filter: Optional[str] = Query(None, alias="status", description="过滤状态 pending/scraped"),
):
    """列出有码模块影片列表"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select, func, or_

        # 构建查询条件
        filters = []
        if keyword:
            kw = f"%{keyword}%"
            filters.append(or_(JavMovie.title.like(kw), JavMovie.code.like(kw)))
        if actor:
            filters.append(JavMovie.actor.like(f"%{actor}%"))
        if status_filter:
            filters.append(JavMovie.status == status_filter)

        total_stmt = select(func.count(JavMovie.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()

        stmt = select(JavMovie)
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.order_by(JavMovie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()

        # 统计待刮削数量
        pending_stmt = select(func.count(JavMovie.id)).where(JavMovie.status == "pending")
        pending_result = await session.execute(pending_stmt)
        pending_count = pending_result.scalar()

        return {
            "total": total,
            "pending_count": pending_count or 0,
            "items": [
                {"id": m.id, "code": m.code, "title": m.title,
                 "module_type": "jav",
                 "source_platform": m.source,
                 "series": m.series,
                 "cover_url": m.cover_url, "actor": m.actor,
                 "file_path": m.file_path, "status": m.status}
                for m in movies
            ],
        }
    finally:
        await session.close()


def _parse_sample_images(raw: Optional[str]) -> list:
    """解析 sample_images JSON 字符串为列表"""
    if not raw:
        return []
    try:
        import json
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取有码影片详情"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select
        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "module_type": "jav",
            "original_title": movie.original_title,
            "is_chinese": movie.is_chinese, "is_uncensored": movie.is_uncensored,
            "is_mosaic": movie.is_mosaic,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "thumb_url": movie.thumb_url, "sample_images": _parse_sample_images(movie.sample_images),
            "actor": movie.actor, "studio": movie.studio,
            "series": movie.series, "label": movie.label,
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "genre": movie.genre, "tag": movie.tag,
            "source": movie.source, "source_url": movie.source_url,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "fingerprint": movie.fingerprint,
            "play_count": movie.play_count, "last_played_at": str(movie.last_played_at) if movie.last_played_at else None,
            "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
            "updated_at": str(movie.updated_at),
        }
    finally:
        await session.close()


# ========== 相关推荐与演员端点（通用详情页使用） ==========


@router.get("/movies/{movie_id}/related")
async def get_jav_related_movies(movie_id: int):
    """获取JAV影片的相关推荐（同演员/同系列/同类别）"""
    from sqlalchemy import select, or_, and_
    from app.db.jav_models import JavMovie

    db = get_jav_db()
    session = await db.get_session()
    try:
        movie = await session.get(JavMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        related_ids = {movie_id}
        actor_movies = []
        series_movies = []
        genre_movies = []
        limit = 12

        # 同演员
        if movie.actor:
            actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
            if actor_names:
                filters = [JavMovie.actor.contains(name) for name in actor_names]
                stmt = select(JavMovie).where(
                    and_(or_(*filters), JavMovie.id != movie_id)
                ).order_by(JavMovie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        actor_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "jav", "cover_url": m.cover_url,
                        })

        # 同系列
        if movie.series:
            stmt = select(JavMovie).where(
                and_(JavMovie.series == movie.series, JavMovie.id != movie_id)
            ).order_by(JavMovie.id.desc()).limit(limit)
            result = await session.execute(stmt)
            for m in result.scalars().all():
                if m.id not in related_ids:
                    related_ids.add(m.id)
                    series_movies.append({
                        "id": m.id, "code": m.code, "title": m.title,
                        "module_type": "jav", "cover_url": m.cover_url,
                    })

        # 同类别
        if movie.genre:
            genre_parts = [g.strip() for g in movie.genre.split(",") if g.strip()]
            if genre_parts:
                genre_filters = [JavMovie.genre.contains(gp) for gp in genre_parts[:5]]
                stmt = select(JavMovie).where(
                    and_(or_(*genre_filters), JavMovie.id != movie_id)
                ).order_by(JavMovie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        genre_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "jav", "cover_url": m.cover_url,
                        })

        return {
            "actor_movies": actor_movies[:limit],
            "series_movies": series_movies[:limit],
            "genre_movies": genre_movies[:limit],
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/actors")
async def get_jav_movie_actors(movie_id: int):
    """获取JAV影片关联的演员列表"""
    from app.db.jav_models import JavMovie, JavActor

    db = get_jav_db()
    session = await db.get_session()
    try:
        movie = await session.get(JavMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        if not movie.actor:
            return {"items": []}
        actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
        items = []
        for name in actor_names:
            stmt = select(JavActor).where(JavActor.name == name)
            result = await session.execute(stmt)
            actor = result.scalar_one_or_none()
            if actor:
                items.append({"id": actor.id, "name": actor.name, "avatar_url": actor.avatar_url})
            else:
                items.append({"id": name, "name": name, "avatar_url": None})
        return {"items": items}
    finally:
        await session.close()


# ========== 刮削端点 ==========


@router.post("/movies/{movie_id}/scrape")
async def scrape_jav_movie(movie_id: int):
    """刮削指定有码影片的元数据

    使用 JavDB/JavBus 等爬虫从网络获取元数据，
    然后写入 JAV 模块 DB（JavMovie + JavActor）。
    """
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie, JavActor
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 使用 ScraperEngine 刮削
        from app.scraper.engine import get_scraper_engine
        engine = get_scraper_engine()
        scrape_result = await engine.scrape_number(movie.code)

        if not scrape_result or not scrape_result.title:
            return {"status": "error", "message": f"刮削失败: 未找到 {movie.code} 的数据"}

        # 映射 ScrapeResult → JavMovie 字段
        movie.title = scrape_result.title
        if scrape_result.original_title:
            movie.original_title = scrape_result.original_title

        # ── 资源下载：将远程封面/预览图/头像下载到本地 ──
        from app.utils.media_helpers import (
            ensure_movie_media_local,
            ensure_actor_avatar_local,
        )

        # 下载封面/背景图/缩略图到 L:/data/movies/jav/{code}/
        local_media = await ensure_movie_media_local(
            module_name="jav", code=movie.code,
            cover_url=scrape_result.cover_url,
            fanart_url=scrape_result.poster_url,
            thumb_url=scrape_result.thumb_url,
        )
        # 存本地路径到数据库
        if local_media.get("cover"):
            movie.cover_url = local_media["cover"]
        if local_media.get("fanart"):
            movie.poster_url = local_media["fanart"]
        if local_media.get("thumb"):
            movie.thumb_url = local_media["thumb"]
        if scrape_result.poster_url:
            movie.poster_url = scrape_result.poster_url
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
        if scrape_result.series:
            movie.series = scrape_result.series
        if scrape_result.label:
            movie.label = scrape_result.label
        if scrape_result.is_mosaic is not None:
            movie.is_mosaic = scrape_result.is_mosaic
        if scrape_result.is_uncensored is not None:
            movie.is_uncensored = scrape_result.is_uncensored
        if scrape_result.is_chinese is not None:
            movie.is_chinese = scrape_result.is_chinese
        if scrape_result.genres:
            movie.genre = ",".join(scrape_result.genres)
        if scrape_result.tags:
            movie.tag = ",".join(scrape_result.tags)
        if scrape_result.sample_images:
            import json
            movie.sample_images = json.dumps(scrape_result.sample_images, ensure_ascii=False)

        # 演员
        if scrape_result.actors:
            actor_names = [a.name for a in scrape_result.actors]
            movie.actor = ",".join(actor_names)

            for actor_info in scrape_result.actors:
                existing = await session.execute(
                    select(JavActor).where(JavActor.name == actor_info.name)
                )
                db_actor = existing.scalar_one_or_none()
                if db_actor:
                    db_actor.movie_count += 1
                    if not db_actor.avatar_url and actor_info.avatar_url:
                        # 下载头像到 L:/data/avatars/{name}.jpg
                        local_avatar = await ensure_actor_avatar_local(
                            actor_info.name, actor_info.avatar_url
                        )
                        db_actor.avatar_url = local_avatar or actor_info.avatar_url
                    if not db_actor.source_site:
                        db_actor.source_site = scrape_result.source
                else:
                    # 下载头像到 L:/data/avatars/{name}.jpg
                    local_avatar = await ensure_actor_avatar_local(
                        actor_info.name, actor_info.avatar_url
                    )
                    session.add(JavActor(
                        name=actor_info.name,
                        avatar_url=local_avatar or actor_info.avatar_url,
                        source="scraper",
                        source_site=scrape_result.source,
                        movie_count=1,
                    ))

        # 来源信息
        movie.source = scrape_result.source
        if scrape_result.source_url:
            movie.source_url = scrape_result.source_url
        movie.status = "scraped"
        await session.commit()

        return {
            "status": "ok",
            "message": f"刮削成功: {scrape_result.title}",
            "source": scrape_result.source,
            "actors": [a.name for a in scrape_result.actors] if scrape_result.actors else [],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JAV 刮削失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/scrape-all-pending")
async def scrape_all_pending_jav(background_tasks: BackgroundTasks):
    """后台批量刮削所有 status=pending 的 JAV 影片"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.status == "pending").order_by(JavMovie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待刮削的影片", "total": 0}

    async def _run():
        from app.db.jav_models import JavMovie, JavActor
        from app.scraper.engine import get_scraper_engine
        from sqlalchemy import select

        engine = get_scraper_engine()
        success = 0
        failed = 0
        for m in pending:
            try:
                scrape_result = await engine.scrape_number(m.code)
                if scrape_result and scrape_result.title:
                    s = await db.get_session()
                    try:
                        st = select(JavMovie).where(JavMovie.id == m.id)
                        r = await s.execute(st)
                        mv = r.scalar_one_or_none()
                        if mv:
                            mv.title = scrape_result.title
                            if scrape_result.original_title:
                                mv.original_title = scrape_result.original_title
                            if scrape_result.cover_url:
                                mv.cover_url = scrape_result.cover_url
                            if scrape_result.poster_url:
                                mv.poster_url = scrape_result.poster_url
                            if scrape_result.release_date:
                                mv.release_date = str(scrape_result.release_date)
                            if scrape_result.duration:
                                mv.duration = scrape_result.duration
                            if scrape_result.rating:
                                mv.rating = scrape_result.rating
                            if scrape_result.plot:
                                mv.plot = scrape_result.plot
                            if scrape_result.studio:
                                mv.studio = scrape_result.studio
                            if scrape_result.series:
                                mv.series = scrape_result.series
                            if scrape_result.label:
                                mv.label = scrape_result.label
                            if scrape_result.genres:
                                mv.genre = ",".join(scrape_result.genres)
                            if scrape_result.tags:
                                mv.tag = ",".join(scrape_result.tags)
                            if scrape_result.actors:
                                mv.actor = ",".join(a.name for a in scrape_result.actors)
                                for ai in scrape_result.actors:
                                    ex = await s.execute(select(JavActor).where(JavActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if not a:
                                        s.add(JavActor(
                                            name=ai.name,
                                            avatar_url=ai.avatar_url,
                                            source="scraper",
                                            source_site=scrape_result.source,
                                            movie_count=1,
                                        ))
                            mv.source = scrape_result.source
                            mv.status = "scraped"
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"JAV 刮削失败 {m.code}: {e}")
                failed += 1
        logger.info(f"JAV 批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "total": len(pending),
        "message": f"JAV 批量刮削已启动，共 {len(pending)} 部待刮削影片",
    }


# ========== NFO 导入端点 ==========


@router.post("/movies/import-nfo")
async def import_jav_nfo(
    background_tasks: BackgroundTasks,
    media_dir: Optional[str] = Query(None, description="指定扫描目录，不传则使用配置中的所有 JAV 媒体目录"),
    recursive: bool = Query(True, description="是否递归扫描子目录"),
):
    """从 JAV 媒体目录扫描 NFO 文件并导入到 JavMovie 表

    扫描视频文件同目录下的 *.nfo 文件，解析元数据（标题、封面、演员、简介等），
    写入 JAV 模块数据库（JavMovie + JavActor）。
    已有 scraped 状态的影片不会覆盖。
    """
    from app.config.manager import get_config

    config = get_config()

    # 确定扫描目录
    if media_dir:
        dirs = [media_dir]
    else:
        dirs = config.modules.jav.media_dirs

    if not dirs:
        return {"status": "error", "message": "未配置 JAV 媒体目录，请先在配置中设置"}

    # 收集所有 NFO 文件
    import os
    from pathlib import Path

    nfo_files: list[str] = []
    for d in dirs:
        d_path = Path(d)
        if not d_path.exists():
            logger.warning(f"媒体目录不存在: {d}")
            continue

        if recursive:
            walk_gen = os.walk(d_path)
        else:
            walk_gen = [(str(d_path), [], [f.name for f in d_path.iterdir() if f.is_file()])]

        for root, _, files in walk_gen:
            for f in files:
                if f.lower().endswith(".nfo"):
                    nfo_path = os.path.join(root, f)
                    nfo_files.append(nfo_path)

    if not nfo_files:
        return {"status": "ok", "message": f"在 {len(dirs)} 个目录中未找到任何 NFO 文件", "total": 0}

    async def _run_import():
        """后台执行 NFO 导入"""
        from app.db.jav_models import JavMovie, JavActor
        from app.importer.nfo_parser import NFOParser
        from sqlalchemy import select

        parser = NFOParser()
        imported = 0
        skipped = 0
        errors = 0

        for nfo_path in nfo_files:
            try:
                # 解析 NFO
                imported_movie = parser.parse(nfo_path)
                if not imported_movie or not imported_movie.code:
                    skipped += 1
                    continue

                code = imported_movie.code.upper()
                s = await db.get_session()
                try:
                    # 检查是否已存在
                    st = select(JavMovie).where(JavMovie.code == code)
                    r = await s.execute(st)
                    mv = r.scalar_one_or_none()

                    if mv:
                        # 已存在的影片只补全缺失字段
                        updates = []
                        if mv.title is None and imported_movie.title:
                            mv.title = imported_movie.title
                            updates.append("title")
                        if mv.original_title is None and imported_movie.original_title:
                            mv.original_title = imported_movie.original_title
                            updates.append("original_title")
                        if mv.plot is None and imported_movie.plot:
                            mv.plot = imported_movie.plot
                            updates.append("plot")
                        if mv.release_date is None and imported_movie.release_date:
                            mv.release_date = imported_movie.release_date.strftime("%Y-%m-%d")
                            updates.append("release_date")
                        if mv.duration is None and imported_movie.duration:
                            mv.duration = imported_movie.duration
                            updates.append("duration")
                        if mv.studio is None and imported_movie.studio:
                            mv.studio = imported_movie.studio
                            updates.append("studio")
                        if mv.series is None and imported_movie.series:
                            mv.series = imported_movie.series
                            updates.append("series")
                        if imported_movie.genres and mv.genre is None:
                            mv.genre = ",".join(imported_movie.genres)
                            updates.append("genre")
                        if imported_movie.actors and mv.actor is None:
                            mv.actor = ",".join(imported_movie.actors)
                            updates.append("actor")
                        if imported_movie.is_chinese is not None and mv.is_chinese is None:
                            mv.is_chinese = imported_movie.is_chinese
                        if imported_movie.is_uncensored is not None and mv.is_uncensored is None:
                            mv.is_uncensored = imported_movie.is_uncensored
                        if mv.source is None or mv.source == "folder":
                            mv.source = "nfo"

                        # 封面图片：检查 NFO 同目录下的同名图片
                        nfo_dir = Path(nfo_path).parent
                        for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg"]:
                            img_path = nfo_dir / img_name
                            if img_path.exists() and mv.cover_url is None:
                                mv.cover_url = str(img_path)
                                updates.append("cover_url")
                                break

                        if updates:
                            await s.commit()
                            imported += 1
                        else:
                            skipped += 1
                    else:
                        # 新建影片
                        cover_url = None
                        nfo_dir = Path(nfo_path).parent
                        for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg"]:
                            img_path = nfo_dir / img_name
                            if img_path.exists():
                                cover_url = str(img_path)
                                break

                        new_movie = JavMovie(
                            code=code,
                            title=imported_movie.title or code,
                            original_title=imported_movie.original_title,
                            plot=imported_movie.plot,
                            release_date=imported_movie.release_date.strftime("%Y-%m-%d") if imported_movie.release_date else None,
                            duration=imported_movie.duration,
                            studio=imported_movie.studio,
                            series=imported_movie.series,
                            genre=",".join(imported_movie.genres) if imported_movie.genres else None,
                            actor=",".join(imported_movie.actors) if imported_movie.actors else None,
                            cover_url=cover_url,
                            is_chinese=imported_movie.is_chinese if imported_movie.is_chinese else False,
                            is_uncensored=imported_movie.is_uncensored if imported_movie.is_uncensored else False,
                            source="nfo",
                            status="pending",
                        )
                        s.add(new_movie)

                        # 演员同步
                        if imported_movie.actors:
                            for actor_name in imported_movie.actors:
                                ex = await s.execute(select(JavActor).where(JavActor.name == actor_name))
                                if not ex.scalar_one_or_none():
                                    s.add(JavActor(name=actor_name, source="nfo"))

                        await s.commit()
                        imported += 1

                finally:
                    await s.close()

            except Exception as e:
                logger.debug(f"NFO 导入失败 [{nfo_path}]: {e}")
                errors += 1

        logger.info(f"JAV NFO 导入完成: 导入/更新 {imported}, 跳过 {skipped}, 错误 {errors}")

    background_tasks.add_task(_run_import)

    return {
        "status": "started",
        "total": len(nfo_files),
        "message": f"NFO 导入已启动，共发现 {len(nfo_files)} 个 NFO 文件",
    }


# ========== 封面/预览图文件代理 ==========

import os as _os
from pathlib import Path as _Path
from fastapi import Request as _Request


@router.get("/movies/{movie_id}/cover/file")
async def get_jav_cover_file(movie_id: int):
    """获取 JAV 模块影片封面图片文件

    纯本地查找，绝不连接外网。
    返回优先级：
    1. {data_base}/movies/jav/{code}/poster.jpg（规范目录下本地文件，刮削时已下载）
    2. DB 中 cover_url/poster_url/thumb_url 的本地路径
    3. 视频所在目录下的 poster.jpg/cover.jpg 等
    4. 内置 SVG 占位图
    """
    from fastapi.responses import FileResponse, Response
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )

    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 1) 规范目录：{data_base}/movies/jav/{code}/poster.jpg（最快命中）
        if movie.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path("jav", movie.code)
                if fast_file_exists(str(p)):
                    return FileResponse(
                        str(p),
                        media_type=_image_media_type(str(p)),
                        headers={"Cache-Control": "public, max-age=86400"},
                    )

        # 2) DB 中 cover_url/poster_url/thumb_url 的本地路径
        for attr in ("cover_url", "poster_url", "thumb_url"):
            url = getattr(movie, attr, None)
            if not url:
                continue
            if not url.startswith(("http://", "https://", "/")):
                if fast_file_exists(url):
                    return FileResponse(
                        url,
                        media_type=_image_media_type(url),
                        headers={"Cache-Control": "public, max-age=86400"},
                    )

        # 2.5) DB 中 cover_url/poster_url/thumb_url 是远程 URL 时，尝试下载到规范目录
        if movie.code:
            # 从 cover_url 提取域名作为 referer（防盗链绕过）
            cover_url_str = movie.cover_url or movie.poster_url or movie.thumb_url or ""
            ref_domain = ""
            if cover_url_str.startswith(("http://", "https://")):
                try:
                    from urllib.parse import urlparse
                    ref_domain = f"{urlparse(cover_url_str).scheme}://{urlparse(cover_url_str).netloc}/"
                except Exception:
                    pass
            for attr in ("cover_url", "poster_url", "thumb_url"):
                url = getattr(movie, attr, None)
                if url and url.startswith(("http://", "https://")):
                    # 确定目标文件名
                    target = get_movie_cover_path("jav", movie.code)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                            resp = await asyncio.wait_for(
                                client.get(url, headers={"Referer": ref_domain} if ref_domain else None),
                                timeout=15.0,
                            )
                            if resp.status_code == 200 and len(resp.content) > 500:
                                with open(target, "wb") as f:
                                    f.write(resp.content)
                                # 同时尝试下载 fanart 和 thumb
                                if attr == "cover_url" and movie.poster_url and movie.poster_url.startswith(("http://", "https://")):
                                    try:
                                        fanart_target = get_movie_fanart_path("jav", movie.code)
                                        fresp = await asyncio.wait_for(
                                            client.get(movie.poster_url, headers={"Referer": ref_domain} if ref_domain else None),
                                            timeout=10.0,
                                        )
                                        if fresp.status_code == 200 and len(fresp.content) > 500:
                                            fanart_target.parent.mkdir(parents=True, exist_ok=True)
                                            with open(fanart_target, "wb") as f:
                                                f.write(fresp.content)
                                    except Exception:
                                        pass
                                if fast_file_exists(str(target)):
                                    return FileResponse(
                                        str(target),
                                        media_type=_image_media_type(str(target)),
                                        headers={"Cache-Control": "public, max-age=86400"},
                                    )
                    except Exception:
                        pass
                    break  # 只尝试第一个有效的远程 URL

        # 3) 视频所在目录下的 poster.jpg/cover.jpg/fanart.jpg/thumb.jpg
        if movie.file_path:
            try:
                video_dir = _Path(movie.file_path).parent
                for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg", "thumb.jpg"]:
                    img_path = video_dir / img_name
                    if await asyncio.wait_for(
                        asyncio.to_thread(lambda p=img_path: p.exists() and p.is_file()),
                        timeout=3.0,
                    ):
                        return FileResponse(
                            str(img_path),
                            media_type=_image_media_type(img_name),
                            headers={"Cache-Control": "public, max-age=86400"},
                        )
            except asyncio.TimeoutError:
                logger.debug(f"JAV封面: 扫描视频目录超时 [movie_id={movie_id}]")

        # 4) 全部找不到：返回内置 SVG 占位图（不连外网）
        from fastapi.responses import HTMLResponse
        _placeholder = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360" '
            'viewBox="0 0 240 360"><rect fill="#f0f0f0" width="240" height="360"/>'
            '<text x="120" y="180" text-anchor="middle" fill="#bbb" '
            'font-size="14">暂无封面</text></svg>'
        )
        return HTMLResponse(content=_placeholder, media_type="image/svg+xml",
                            headers={"Cache-Control": "no-cache"})
    finally:
        await session.close()


def _image_media_type(path: str) -> str:
    ext = _Path(path).suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


# ========== 播放端点 ==========

import os as _os
from pathlib import Path as _Path
from fastapi import Request as _Request

_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m2ts", ".m4v", ".3gp", ".ogv"}


@router.get("/movies/{movie_id}/play")
async def play_jav_movie(movie_id: int):
    """获取 JAV 影片播放信息（含 file_path）"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        file_exists = False
        if movie.file_path:
            file_exists = _Path(movie.file_path).exists()

        return {
            "id": movie.id,
            "code": movie.code,
            "title": movie.title,
            "file_path": movie.file_path,
            "file_size": movie.file_size,
            "file_exists": file_exists,
            "cover_url": movie.cover_url,
            "duration": movie.duration,
            "status": movie.status,
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/play/file")
async def play_jav_video_file(movie_id: int, request: _Request):
    """JAV 影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
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
async def get_jav_external_play_url(movie_id: int, protocol: str = "http"):
    """获取 JAV 影片外部播放地址"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
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
            play_url = f"{base}/api/v1/jav/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
