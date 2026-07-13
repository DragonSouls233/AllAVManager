"""
JAV 无码模块 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException

from app.db.module_db import ModuleDatabase

router = APIRouter(prefix="/api/v1/uncensored", tags=["无码模块"])


def get_uncensored_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("uncensored")


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20):
    """列出无码模块影片列表"""
    db = get_uncensored_db()
    session = await db.get_session()
    try:
        from app.db.uncensored_models import UncensoredMovie
        from sqlalchemy import select, func
        total_stmt = select(func.count(UncensoredMovie.id))
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()
        stmt = select(UncensoredMovie).order_by(UncensoredMovie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "source_platform": m.source_platform,
             "series": m.series,
             "cover_url": m.cover_url, "actor": m.actor,
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
