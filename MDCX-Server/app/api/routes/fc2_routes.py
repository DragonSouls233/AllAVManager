"""
FC2 模块 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException

from app.db.module_db import ModuleDatabase

router = APIRouter(prefix="/api/v1/fc2", tags=["FC2模块"])


def get_fc2_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("fc2")


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20):
    """列出 FC2 模块影片列表"""
    db = get_fc2_db()
    session = await db.get_session()
    try:
        from app.db.fc2_models import Fc2Movie
        from sqlalchemy import select, func
        total_stmt = select(func.count(Fc2Movie.id))
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()
        stmt = select(Fc2Movie).order_by(Fc2Movie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "seller_id": m.seller_id, "is_mosaic": m.is_mosaic,
             "cover_url": m.cover_url, "actor": m.actor,
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
