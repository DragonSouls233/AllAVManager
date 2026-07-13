"""
视频指纹去重路由

API 端点：
- POST /api/v1/fingerprint/compute/{movie_id}  - 计算单个影片指纹
- POST /api/v1/fingerprint/scan                - 批量扫描所有有文件路径但无指纹的影片
- GET  /api/v1/fingerprint/duplicates          - 查找重复影片
- GET  /api/v1/fingerprint/status              - 指纹覆盖率统计
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Movie
from app.services.fingerprint import compute_video_fingerprint, hamming_distance

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/compute/{movie_id}")
async def compute_fingerprint(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """计算单个影片的视频指纹"""
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片没有关联文件")

    fp = compute_video_fingerprint(movie.file_path)
    if not fp:
        raise HTTPException(status_code=500, detail="指纹计算失败（ffmpeg 未安装或文件无法读取）")

    movie.fingerprint = fp
    await session.commit()

    return {"status": "ok", "movie_id": movie_id, "fingerprint": fp}


@router.post("/scan")
async def scan_fingerprints(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """批量扫描所有有文件路径但无指纹的影片"""
    # 查找需要计算指纹的影片
    result = await session.execute(
        select(Movie)
        .where(and_(Movie.file_path.isnot(None), Movie.fingerprint.is_(None)))
        .limit(limit)
    )
    movies = result.scalars().all()

    if not movies:
        return {"status": "ok", "message": "没有需要计算指纹的影片", "processed": 0}

    # 后台任务计算指纹
    async def _compute_batch(movie_ids: list[int]):
        db = get_database()
        async with db.session() as s:
            for mid in movie_ids:
                m = await s.get(Movie, mid)
                if m and m.file_path:
                    fp = compute_video_fingerprint(m.file_path)
                    if fp:
                        m.fingerprint = fp
                        await s.commit()
                        logger.info(f"影片 {m.code} 指纹: {fp[:16]}...")

    from app.db.database import get_database
    movie_ids = [m.id for m in movies]
    background_tasks.add_task(_compute_batch, movie_ids)

    return {
        "status": "ok",
        "message": f"已排队 {len(movies)} 个影片进行指纹计算",
        "queued": len(movies),
        "movie_ids": movie_ids,
    }


@router.get("/duplicates")
async def find_duplicates(
    threshold: int = Query(5, ge=0, le=20, description="汉明距离阈值"),
    session: AsyncSession = Depends(get_session),
):
    """查找重复影片（指纹相似度高于阈值）"""
    # 获取所有有指纹的影片
    result = await session.execute(
        select(Movie.id, Movie.code, Movie.title, Movie.file_path, Movie.fingerprint)
        .where(Movie.fingerprint.isnot(None))
        .order_by(Movie.id)
    )
    rows = result.fetchall()

    if len(rows) < 2:
        return {"status": "ok", "duplicates": [], "total_with_fingerprint": len(rows)}

    # 两两比较找重复
    duplicates = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            r1 = rows[i]
            r2 = rows[j]
            dist = hamming_distance(r1[4], r2[4])
            if 0 <= dist <= threshold:
                duplicates.append({
                    "movie_1": {"id": r1[0], "code": r1[1], "title": r1[2], "file_path": r1[3]},
                    "movie_2": {"id": r2[0], "code": r2[1], "title": r2[2], "file_path": r2[3]},
                    "hamming_distance": dist,
                })

    return {
        "status": "ok",
        "duplicates": duplicates,
        "duplicate_count": len(duplicates),
        "total_with_fingerprint": len(rows),
    }


@router.get("/status")
async def fingerprint_status(
    session: AsyncSession = Depends(get_session),
):
    """指纹覆盖率统计"""
    total = await session.scalar(select(func.count()).select_from(Movie).where(Movie.file_path.isnot(None)))
    with_fp = await session.scalar(select(func.count()).select_from(Movie).where(
        and_(Movie.file_path.isnot(None), Movie.fingerprint.isnot(None))
    ))

    return {
        "total_movies": total or 0,
        "with_fingerprint": with_fp or 0,
        "without_fingerprint": (total or 0) - (with_fp or 0),
        "coverage": f"{(with_fp / total * 100):.1f}%" if total else "0%",
    }
