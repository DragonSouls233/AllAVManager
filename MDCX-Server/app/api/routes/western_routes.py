"""
欧美模块 API 路由

参考来源：
- 现有: chinese_routes.py (路由模式)
- P0: CommunityScrapers/scrapers/IAFD/IAFD.py (演员数据来源)

整合说明：
- 路由框架: 沿用 MDCX 模块路由模式
- 演员数据: 支持 IAFD/ThePornDB 来源
"""

from fastapi import APIRouter, HTTPException

from app.db.module_db import ModuleDatabase

router = APIRouter(prefix="/western", tags=["欧美模块"])


def get_western_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("western")


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20):
    """列出欧美影片"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select, func
        total = (await session.execute(select(func.count(WesternMovie.id)))).scalar() or 0
        stmt = select(WesternMovie).order_by(WesternMovie.created_at.desc()).offset(skip).limit(limit)
        movies = (await session.execute(stmt)).scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "site": m.site, "network": m.network, "studio": m.studio,
             "cover_url": m.cover_url, "file_path": m.file_path,
             "status": m.status, "release_date": m.release_date}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取欧美影片详情"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select
        movie = (await session.execute(select(WesternMovie).where(WesternMovie.id == movie_id))).scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "original_title": movie.original_title,
            "site": movie.site, "network": movie.network, "studio": movie.studio,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "genre": movie.genre, "tag": movie.tag, "actors": movie.actors,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "source": movie.source,
            "source_url": movie.source_url,
            "created_at": str(movie.created_at),
        }
    finally:
        await session.close()


@router.get("/actors")
async def list_actors():
    """列出欧美演员"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternActor
        from sqlalchemy import select
        stmt = select(WesternActor).order_by(WesternActor.movie_count.desc())
        actors = (await session.execute(stmt)).scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count,
                 "source": a.source, "avatar_url": a.avatar_url,
                 "gender": a.gender, "country": a.country}
                for a in actors]
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取欧美演员详情"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternActor
        from sqlalchemy import select
        actor = (await session.execute(select(WesternActor).where(WesternActor.id == actor_id))).scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {
            "id": actor.id, "name": actor.name, "alias": actor.alias,
            "avatar_url": actor.avatar_url, "source": actor.source,
            "gender": actor.gender, "birthdate": actor.birthdate,
            "country": actor.country, "ethnicity": actor.ethnicity,
            "measurements": actor.measurements, "height": actor.height,
            "weight": actor.weight, "twitter": actor.twitter,
            "instagram": actor.instagram, "movie_count": actor.movie_count,
        }
    finally:
        await session.close()


@router.post("/scan")
async def scan_media():
    """扫描欧美媒体目录"""
    from app.config.manager import get_config
    config = get_config()
    media_dirs = getattr(config.modules.western, "media_dirs", []) if hasattr(config, "modules") else []
    if not media_dirs:
        raise HTTPException(status_code=400, detail="未配置媒体目录")
    from app.tasks.western_scanner import WesternScanner
    scanner = WesternScanner(media_dirs)
    result = await scanner.scan()
    return result
