"""
系列管理路由

API 端点：
- GET  /api/v1/series         - 系列列表（支持分页、搜索）
- GET  /api/v1/series/{id}    - 系列详情（含作品列表）
- POST /api/v1/series         - 创建系列
- PATCH /api/v1/series/{id}   - 更新系列
- DELETE /api/v1/series/{id}  - 删除系列
- POST /api/v1/series/sync-from-movies - 从现有电影的 series 字段同步系列
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import Database, get_session
from app.db.models import Series, Studio, Movie

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Response Models =====

class SeriesResponse(BaseModel):
    """系列响应模型"""
    id: int
    name: str
    name_jp: Optional[str] = None
    studio_id: Optional[int] = None
    studio_name: Optional[str] = None
    movie_count: int = 0

    class Config:
        from_attributes = True


class SeriesListResponse(BaseModel):
    """系列列表响应"""
    total: int
    items: list[SeriesResponse]


class SeriesMovieResponse(BaseModel):
    """系列作品响应"""
    id: int
    code: str
    title: Optional[str] = None
    release_date: Optional[str] = None
    cover_url: Optional[str] = None

    class Config:
        from_attributes = True


class SeriesDetailResponse(BaseModel):
    """系列详情响应"""
    series: SeriesResponse
    movie_count: int
    recent_movies: list[SeriesMovieResponse]


class SeriesCreateRequest(BaseModel):
    """创建系列请求"""
    name: str
    name_jp: Optional[str] = None
    studio_id: Optional[int] = None


class SeriesUpdateRequest(BaseModel):
    """更新系列请求"""
    name: Optional[str] = None
    name_jp: Optional[str] = None
    studio_id: Optional[int] = None


# ===== API Endpoints =====

@router.get("", response_model=SeriesListResponse)
async def list_series(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    获取系列列表

    - 支持搜索（按名字）
    - 支持分页
    """
    query = select(Series)

    if search:
        query = query.where(
            Series.name.contains(search) | Series.name_jp.contains(search)
        )

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    # 排序和分页
    query = query.order_by(Series.movie_count.desc(), Series.name.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    series_list = result.scalars().all()

    # 构建 studio_name
    items = []
    for s in series_list:
        studio_name = None
        if s.studio_id:
            studio = await session.get(Studio, s.studio_id)
            if studio:
                studio_name = studio.name
        items.append(SeriesResponse(
            id=s.id, name=s.name, name_jp=s.name_jp,
            studio_id=s.studio_id, studio_name=studio_name,
            movie_count=s.movie_count,
        ))

    return SeriesListResponse(
        total=total or 0,
        items=items,
    )


@router.get("/{series_id}", response_model=SeriesDetailResponse)
async def get_series(
    series_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取系列详情

    包含基本信息和最近10部作品
    """
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="系列不存在")

    # 获取 studio_name
    studio_name = None
    if series.studio_id:
        studio = await session.get(Studio, series.studio_id)
        if studio:
            studio_name = studio.name

    # 统计作品数
    movie_count = await session.scalar(
        select(func.count(Movie.id)).where(Movie.series_id == series.id)
    ) or 0

    # 获取最近10部作品
    movies_query = (
        select(Movie)
        .where(Movie.series_id == series.id)
        .order_by(Movie.release_date.desc())
        .limit(10)
    )
    result = await session.execute(movies_query)
    recent_movies = result.scalars().all()

    series_resp = SeriesResponse(
        id=series.id, name=series.name, name_jp=series.name_jp,
        studio_id=series.studio_id, studio_name=studio_name,
        movie_count=movie_count,
    )
    movie_resps = [
        SeriesMovieResponse(
            id=m.id, code=m.code, title=m.title,
            release_date=m.release_date, cover_url=m.cover_url,
        )
        for m in recent_movies
    ]

    return SeriesDetailResponse(
        series=series_resp,
        movie_count=movie_count,
        recent_movies=movie_resps,
    )


@router.post("", response_model=SeriesResponse)
async def create_series(
    body: SeriesCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    创建系列

    - 系列名唯一
    - 可关联 studio_id
    """
    existing = await session.scalar(
        select(Series).where(Series.name == body.name)
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"系列 '{body.name}' 已存在")

    # 验证 studio_id
    studio_name = None
    if body.studio_id:
        studio = await session.get(Studio, body.studio_id)
        if not studio:
            raise HTTPException(status_code=404, detail="关联的厂商不存在")
        studio_name = studio.name

    series = Series(
        name=body.name,
        name_jp=body.name_jp,
        studio_id=body.studio_id,
        movie_count=0,
    )
    session.add(series)
    await session.commit()
    await session.refresh(series)

    return SeriesResponse(
        id=series.id, name=series.name, name_jp=series.name_jp,
        studio_id=series.studio_id, studio_name=studio_name,
        movie_count=series.movie_count,
    )


@router.post("/sync-from-movies")
async def sync_series_from_movies(
    session: AsyncSession = Depends(get_session),
):
    """
    从现有电影的 series 字段同步系列

    - 读取所有 Movie 的 series 字段
    - 为每个唯一值创建 Series（如果不存在）
    - 尝试根据 maker/studio 字段关联 studio_id
    - 更新 movie_count 冗余字段
    """
    # 获取所有电影的 series 字段
    result = await session.execute(
        select(Movie.series_id, Movie.maker, Movie.studio_id).where(
            Movie.series_id.isnot(None)
        )
    )
    movies = result.fetchall()

    # 收集唯一系列名，并记录对应的厂商
    series_names: set[str] = set()
    series_studio_map: dict[str, str] = {}  # series_name -> studio/maker name

    # 预加载所有厂商和系列
    all_studios = (await session.execute(select(Studio))).scalars().all()
    studio_name_to_id = {s.name: s.id for s in all_studios}
    all_series_list = (await session.execute(select(Series))).scalars().all()
    series_id_to_name = {s.id: s.name for s in all_series_list}

    for series_id, maker, studio_id in movies:
        if not series_id:
            continue
        name = series_id_to_name.get(series_id)
        if not name:
            continue
        series_names.add(name)
        # 记录关联的厂商（优先 maker）
        if maker and maker.strip():
            series_studio_map.setdefault(name, maker.strip())
        elif studio_id:
            studio_obj = await session.get(Studio, studio_id)
            if studio_obj and studio_obj.name.strip():
                series_studio_map.setdefault(name, studio_obj.name.strip())

    series_created = 0
    series_skipped = 0

    for name in series_names:
        existing = await session.scalar(
            select(Series).where(Series.name == name)
        )
        if existing:
            series_skipped += 1
            continue

        # 尝试关联 studio_id
        studio_id = None
        studio_name = series_studio_map.get(name)
        if studio_name and studio_name in studio_name_to_id:
            studio_id = studio_name_to_id[studio_name]

        series = Series(name=name, studio_id=studio_id, movie_count=0)
        session.add(series)
        series_created += 1

    await session.commit()

    # 更新所有系列的 movie_count
    all_series = (await session.execute(select(Series))).scalars().all()
    for series in all_series:
        count = await session.scalar(
            select(func.count(Movie.id)).where(Movie.series_id == series.id)
        ) or 0
        series.movie_count = count

    await session.commit()

    logger.info(f"系列同步完成: 创建 {series_created} 个系列, 跳过 {series_skipped} 个已存在系列")

    return {
        "status": "ok",
        "series_created": series_created,
        "series_skipped": series_skipped,
    }


@router.patch("/{series_id}")
async def update_series(
    series_id: int,
    body: SeriesUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    更新系列信息

    - 支持更新: name, name_jp, studio_id
    """
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="系列不存在")

    if body.name is not None:
        existing = await session.scalar(
            select(Series).where(Series.name == body.name, Series.id != series_id)
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"系列名 '{body.name}' 已被占用")
        series.name = body.name
    if body.name_jp is not None:
        series.name_jp = body.name_jp
    if body.studio_id is not None:
        if body.studio_id:
            studio = await session.get(Studio, body.studio_id)
            if not studio:
                raise HTTPException(status_code=404, detail="关联的厂商不存在")
        series.studio_id = body.studio_id

    await session.commit()
    await session.refresh(series)

    # 获取 studio_name
    studio_name = None
    if series.studio_id:
        studio = await session.get(Studio, series.studio_id)
        if studio:
            studio_name = studio.name

    return {
        "status": "ok",
        "series": SeriesResponse(
            id=series.id, name=series.name, name_jp=series.name_jp,
            studio_id=series.studio_id, studio_name=studio_name,
            movie_count=series.movie_count,
        ),
    }


@router.delete("/{series_id}")
async def delete_series(
    series_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    删除系列
    """
    series = await session.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="系列不存在")

    await session.delete(series)
    await session.commit()

    return {"status": "ok", "message": f"系列 '{series.name}' 已删除"}
