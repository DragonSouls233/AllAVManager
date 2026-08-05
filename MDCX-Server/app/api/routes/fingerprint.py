"""
视频指纹去重路由

API 端点：
- POST /api/v1/fingerprint/compute/{movie_id}  - 计算单个影片指纹（支持 module 参数）
- POST /api/v1/fingerprint/scan                - 批量扫描所有有文件路径但无指纹的影片（支持 module 参数）
- GET  /api/v1/fingerprint/duplicates          - 查找重复影片（支持 module 参数）
- GET  /api/v1/fingerprint/status              - 指纹覆盖率统计（支持 module 参数）
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from sqlalchemy import select, func, and_

from app.services.fingerprint import compute_video_fingerprint, hamming_distance
from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/compute/{movie_id}")
async def compute_fingerprint(
    movie_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/pornhub/western"),
):
    """计算单个影片的视频指纹"""
    if module not in MODULE_MODELS:
        raise HTTPException(status_code=400, detail=f"未知模块: {module}")

    sess = await get_module_session(module)
    async with sess:
        model = get_module_model(module, "movie")
        movie = await sess.get(model, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        if not movie.file_path:
            raise HTTPException(status_code=400, detail="影片没有关联文件")
        fp = compute_video_fingerprint(movie.file_path)
        if not fp:
            raise HTTPException(status_code=500, detail="指纹计算失败")
        movie.fingerprint = fp
        await sess.commit()
        return {"status": "ok", "movie_id": movie_id, "fingerprint": fp}


@router.post("/scan")
async def scan_fingerprints(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/pornhub/western"),
):
    """批量扫描所有有文件路径但无指纹的影片"""
    if module not in MODULE_MODELS:
        raise HTTPException(status_code=400, detail=f"未知模块: {module}")

    sess = await get_module_session(module)
    async with sess:
        model = get_module_model(module, "movie")
        result = await sess.execute(
            select(model)
            .where(and_(model.file_path.isnot(None), model.fingerprint.is_(None)))
            .limit(limit)
        )
        movies = result.scalars().all()
        if not movies:
            return {"status": "ok", "message": "没有需要计算指纹的影片", "processed": 0}

        async def _compute_batch(mid_list: list[int]):
            s2 = await get_module_session(module)
            async with s2:
                m2 = get_module_model(module, "movie")
                for mid in mid_list:
                    m = await s2.get(m2, mid)
                    if m and m.file_path:
                        fp = compute_video_fingerprint(m.file_path)
                        if fp:
                            m.fingerprint = fp
                            await s2.commit()
                            logger.info(f"[{module}] 影片 {m.code} 指纹: {fp[:16]}...")

        movie_ids = [m.id for m in movies]
        background_tasks.add_task(_compute_batch, movie_ids)
        return {
            "status": "ok",
            "message": f"已排队 {len(movies)} 个 [{module}] 影片进行指纹计算",
            "queued": len(movies),
            "movie_ids": movie_ids,
        }


@router.get("/duplicates")
async def find_duplicates(
    threshold: int = Query(5, ge=0, le=20, description="汉明距离阈值"),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/pornhub/western"),
):
    """查找重复影片（指纹相似度高于阈值）"""
    if module not in MODULE_MODELS:
        raise HTTPException(status_code=400, detail=f"未知模块: {module}")

    sess = await get_module_session(module)
    async with sess:
        model = get_module_model(module, "movie")
        result = await sess.execute(
            select(model.id, model.code, model.title, model.file_path, model.fingerprint)
            .where(model.fingerprint.isnot(None))
            .order_by(model.id)
        )
        rows = result.fetchall()
        if len(rows) < 2:
            return {"status": "ok", "duplicates": [], "total_with_fingerprint": len(rows)}

        duplicates = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                r1, r2 = rows[i], rows[j]
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
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/pornhub/western"),
):
    """指纹覆盖率统计"""
    if module not in MODULE_MODELS:
        raise HTTPException(status_code=400, detail=f"未知模块: {module}")

    sess = await get_module_session(module)
    async with sess:
        model = get_module_model(module, "movie")
        total = await sess.scalar(
            select(func.count()).select_from(model).where(model.file_path.isnot(None))
        )
        with_fp = await sess.scalar(
            select(func.count()).select_from(model).where(
                and_(model.file_path.isnot(None), model.fingerprint.isnot(None))
            )
        )
        return {
            "module": module,
            "total_movies": total or 0,
            "with_fingerprint": with_fp or 0,
            "without_fingerprint": (total or 0) - (with_fp or 0),
            "coverage": f"{(with_fp / total * 100):.1f}%" if total else "0%",
        }
