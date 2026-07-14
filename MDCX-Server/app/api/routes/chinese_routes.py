"""
国产模块 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException

from app.db.module_db import ModuleDatabase
from app.scraper.folder_actor import extract_actor_from_folder, DEFAULT_BLACKLIST

router = APIRouter(prefix="/chinese", tags=["国产模块"])


def get_chinese_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("chinese")


@router.get("/actors")
async def list_actors():
    """列出国产模块演员列表"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseActor
        from sqlalchemy import select
        stmt = select(ChineseActor).order_by(ChineseActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count, "source": a.source} for a in actors]
    finally:
        await session.close()


@router.post("/actors/scan-folders")
async def sync_folder_actors():
    """从媒体目录的文件夹名同步演员"""
    from app.config.manager import get_config
    config = get_config()
    from app.tasks.chinese_scanner import ChineseScanner
    scanner = ChineseScanner(config.chinese.media_dirs)
    result = await scanner.scan()
    return result


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20):
    """列出国产模块影片列表"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select, func
        total_stmt = select(func.count(ChineseMovie.id))
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()
        stmt = select(ChineseMovie).order_by(ChineseMovie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "folder_name": m.folder_name,
             "folder_based_actors": m.folder_based_actors,
             "studio": m.studio, "cover_url": m.cover_url,
             "file_path": m.file_path, "status": m.status}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取国产影片详情"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select
        stmt = select(ChineseMovie).where(ChineseMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "folder_name": movie.folder_name,
            "folder_based_actors": movie.folder_based_actors,
            "studio": movie.studio, "cover_url": movie.cover_url,
            "poster_url": movie.poster_url, "release_date": movie.release_date,
            "duration": movie.duration, "rating": movie.rating,
            "plot": movie.plot, "genre": movie.genre, "tag": movie.tag,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
        }
    finally:
        await session.close()
