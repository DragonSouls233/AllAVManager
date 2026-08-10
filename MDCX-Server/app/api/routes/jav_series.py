"""
JAV 有码 · 系列聚合路由

重要背景：
- jav 模块的 `series` 表为空（series_id 全为 NULL），现有通用 /series 端点的 FK join
  对 jav 查不到任何作品。
- jav 影片的系列信息实际存放在 `movies.series` 文本字段（已刮削填充，共 2329 部有值）。
- 因此本模块直接按 `movies.series` 文本字段聚合，不依赖 series 表 / series_id。

API 端点：
- GET /api/v1/jav/series              - 系列列表（按影片数聚合，可过滤 > min_count、可搜索）
- GET /api/v1/jav/series/{name}/movies - 某系列全部作品（按上映日期倒序，分页）
"""

from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from app.utils.module_helper import get_module_session, get_module_model

router = APIRouter()


# ===== Response Models =====

class JavSeriesItem(BaseModel):
    """单个系列聚合项"""
    name: str
    movie_count: int


class JavSeriesListResponse(BaseModel):
    total: int
    total_movies: int = 0  # 全部系列涵盖的影片总数（受 search/min_count 影响）
    items: list[JavSeriesItem]


class JavSeriesMovieItem(BaseModel):
    """系列内作品（带模块类型，前端据此拼封面端点）"""
    id: int
    code: str
    title: Optional[str] = None
    release_date: Optional[str] = None
    cover_url: Optional[str] = None
    module_type: str = "jav"


class JavSeriesMoviesResponse(BaseModel):
    series: str
    total: int
    items: list[JavSeriesMovieItem]


# ===== API Endpoints =====

@router.get("", response_model=JavSeriesListResponse)
async def list_jav_series(
    search: Optional[str] = Query(None, description="系列名模糊搜索"),
    min_count: int = Query(2, ge=1, description="系列包含影片数下限（含），默认 2 即聚合 2 部及以上的系列"),
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=200),
):
    """
    按 movies.series 文本聚合 JAV 系列。

    - 仅展示影片数 >= min_count 的系列（默认 2 部及以上）
    - 按影片数倒序、系列名升序排列
    - 支持系列名模糊搜索与分页
    """
    session = await get_module_session("jav")
    Movie = get_module_model("jav", "movie")

    # 聚合查询：series 文本 -> 计数
    query = (
        select(Movie.series, func.count(Movie.id).label("c"))
        .where(Movie.series.isnot(None), Movie.series != "")
    )
    if search:
        query = query.where(Movie.series.contains(search))
    query = (
        query.group_by(Movie.series)
        .having(func.count(Movie.id) >= min_count)
        .order_by(func.count(Movie.id).desc(), Movie.series.asc())
    )

    result = await session.execute(query)
    rows = result.all()  # [(series_name, count), ...]

    total = len(rows)
    total_movies = sum(cnt for _, cnt in rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    items = [JavSeriesItem(name=name, movie_count=cnt) for name, cnt in page_rows]

    return JavSeriesListResponse(total=total, total_movies=total_movies, items=items)


@router.get("/{series_name}/movies", response_model=JavSeriesMoviesResponse)
async def get_jav_series_movies(
    series_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    """
    获取某系列的全部作品（按上映日期倒序）。

    series_name 为 URL 编码后的系列名（FastAPI 自动解码）。
    """
    session = await get_module_session("jav")
    Movie = get_module_model("jav", "movie")

    # 总数
    total = await session.scalar(
        select(func.count(Movie.id)).where(Movie.series == series_name)
    ) or 0

    if total == 0:
        # 可能是编码不匹配，尝试解码一次（双保险）
        from urllib.parse import unquote
        decoded = unquote(series_name)
        if decoded != series_name:
            total = await session.scalar(
                select(func.count(Movie.id)).where(Movie.series == decoded)
            ) or 0
            series_name = decoded

    if total == 0:
        raise HTTPException(status_code=404, detail="该系列暂无作品")

    movies_q = (
        select(Movie)
        .where(Movie.series == series_name)
        .order_by(Movie.release_date.isnot(None).desc(), Movie.release_date.desc(), Movie.code.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(movies_q)
    movies = result.scalars().all()

    items = [
        JavSeriesMovieItem(
            id=m.id,
            code=m.code,
            title=m.title,
            release_date=m.release_date,
            cover_url=m.cover_url,
            module_type="jav",
        )
        for m in movies
    ]

    return JavSeriesMoviesResponse(series=series_name, total=total, items=items)
