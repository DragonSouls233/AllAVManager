"""
厂商/工作室管理路由

API 端点：
- GET  /api/v1/studios        - 厂商列表（支持分页、搜索）
- GET  /api/v1/studios/{id}   - 厂商详情（含作品列表）
- POST /api/v1/studios        - 创建厂商
- PATCH /api/v1/studios/{id}  - 更新厂商
- DELETE /api/v1/studios/{id} - 删除厂商
- POST /api/v1/studios/sync-from-movies - 从现有电影的 maker/studio 字段同步厂商
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import Database, get_session
from app.db.models import Studio, Movie

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Response Models =====

class StudioResponse(BaseModel):
    """厂商响应模型"""
    id: int
    name: str
    name_jp: Optional[str] = None
    movie_count: int = 0

    class Config:
        from_attributes = True


class StudioListResponse(BaseModel):
    """厂商列表响应"""
    total: int
    items: list[StudioResponse]


class StudioMovieResponse(BaseModel):
    """厂商作品响应"""
    id: int
    code: str
    title: Optional[str] = None
    release_date: Optional[str] = None
    cover_url: Optional[str] = None

    class Config:
        from_attributes = True


class StudioDetailResponse(BaseModel):
    """厂商详情响应"""
    studio: StudioResponse
    movie_count: int
    recent_movies: list[StudioMovieResponse]


class StudioCreateRequest(BaseModel):
    """创建厂商请求"""
    name: str
    name_jp: Optional[str] = None


class StudioUpdateRequest(BaseModel):
    """更新厂商请求"""
    name: Optional[str] = None
    name_jp: Optional[str] = None


# ===== API Endpoints =====

@router.get("", response_model=StudioListResponse)
async def list_studios(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    获取厂商列表

    - 支持搜索（按名字）
    - 支持分页
    """
    query = select(Studio)

    if search:
        query = query.where(
            Studio.name.contains(search) | Studio.name_jp.contains(search)
        )

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    # 排序和分页
    query = query.order_by(Studio.movie_count.desc(), Studio.name.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    studios = result.scalars().all()

    items = [
        StudioResponse(
            id=s.id, name=s.name, name_jp=s.name_jp,
            movie_count=s.movie_count,
        )
        for s in studios
    ]

    return StudioListResponse(
        total=total or 0,
        items=items,
    )


@router.get("/{studio_id}", response_model=StudioDetailResponse)
async def get_studio(
    studio_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取厂商详情

    包含基本信息和最近10部作品
    """
    studio = await session.get(Studio, studio_id)
    if not studio:
        raise HTTPException(status_code=404, detail="厂商不存在")

    # 统计作品数
    movie_count = await session.scalar(
        select(func.count(Movie.id)).where(
            (Movie.studio_id == studio.id) | (Movie.maker == studio.name)
        )
    ) or 0

    # 获取最近10部作品
    movies_query = (
        select(Movie)
        .where(
            (Movie.studio_id == studio.id) | (Movie.maker == studio.name)
        )
        .order_by(Movie.release_date.desc())
        .limit(10)
    )
    result = await session.execute(movies_query)
    recent_movies = result.scalars().all()

    studio_resp = StudioResponse(
        id=studio.id, name=studio.name, name_jp=studio.name_jp,
        movie_count=movie_count,
    )
    movie_resps = [
        StudioMovieResponse(
            id=m.id, code=m.code, title=m.title,
            release_date=m.release_date, cover_url=m.cover_url,
        )
        for m in recent_movies
    ]

    return StudioDetailResponse(
        studio=studio_resp,
        movie_count=movie_count,
        recent_movies=movie_resps,
    )


@router.post("", response_model=StudioResponse)
async def create_studio(
    body: StudioCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    创建厂商

    - 厂商名唯一
    """
    existing = await session.scalar(
        select(Studio).where(Studio.name == body.name)
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"厂商 '{body.name}' 已存在")

    studio = Studio(
        name=body.name,
        name_jp=body.name_jp,
        movie_count=0,
    )
    session.add(studio)
    await session.commit()
    await session.refresh(studio)

    return StudioResponse(
        id=studio.id, name=studio.name, name_jp=studio.name_jp,
        movie_count=studio.movie_count,
    )


@router.post("/sync-from-movies")
async def sync_studios_from_movies(
    session: AsyncSession = Depends(get_session),
):
    """
    从现有电影的 maker/studio 字段同步厂商

    - 读取所有 Movie 的 maker 和 studio 字段
    - 为每个唯一值创建 Studio（如果不存在）
    - 更新 movie_count 冗余字段
    """
    # 获取所有电影的 maker 和 studio
    result = await session.execute(
        select(Movie.maker, Movie.studio_id).where(
            (Movie.maker.isnot(None)) | (Movie.studio_id.isnot(None))
        )
    )
    movies = result.fetchall()

    # 收集唯一厂商名
    studio_names: set[str] = set()
    for maker, studio_id in movies:
        if maker and maker.strip():
            studio_names.add(maker.strip())
        if studio_id:
            studio_obj = await session.get(Studio, studio_id)
            if studio_obj and studio_obj.name.strip():
                studio_names.add(studio_obj.name.strip())

    studios_created = 0
    studios_skipped = 0

    for name in studio_names:
        existing = await session.scalar(
            select(Studio).where(Studio.name == name)
        )
        if existing:
            studios_skipped += 1
            continue

        studio = Studio(name=name, movie_count=0)
        session.add(studio)
        studios_created += 1

    await session.commit()

    # 更新所有厂商的 movie_count
    all_studios = (await session.execute(select(Studio))).scalars().all()
    for studio in all_studios:
        count = await session.scalar(
            select(func.count(Movie.id)).where(
                (Movie.studio_id == studio.id) | (Movie.maker == studio.name)
            )
        ) or 0
        studio.movie_count = count

    await session.commit()

    logger.info(f"厂商同步完成: 创建 {studios_created} 个厂商, 跳过 {studios_skipped} 个已存在厂商")

    return {
        "status": "ok",
        "studios_created": studios_created,
        "studios_skipped": studios_skipped,
    }


@router.patch("/{studio_id}")
async def update_studio(
    studio_id: int,
    body: StudioUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    更新厂商信息

    - 支持更新: name, name_jp
    """
    studio = await session.get(Studio, studio_id)
    if not studio:
        raise HTTPException(status_code=404, detail="厂商不存在")

    if body.name is not None:
        existing = await session.scalar(
            select(Studio).where(Studio.name == body.name, Studio.id != studio_id)
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"厂商名 '{body.name}' 已被占用")
        studio.name = body.name
    if body.name_jp is not None:
        studio.name_jp = body.name_jp

    await session.commit()
    await session.refresh(studio)

    return {
        "status": "ok",
        "studio": StudioResponse(
            id=studio.id, name=studio.name, name_jp=studio.name_jp,
            movie_count=studio.movie_count,
        ),
    }


@router.delete("/{studio_id}")
async def delete_studio(
    studio_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    删除厂商
    """
    studio = await session.get(Studio, studio_id)
    if not studio:
        raise HTTPException(status_code=404, detail="厂商不存在")

    await session.delete(studio)
    await session.commit()

    return {"status": "ok", "message": f"厂商 '{studio.name}' 已删除"}
