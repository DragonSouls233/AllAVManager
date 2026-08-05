"""
三态视频标记 API 路由（v3.0）

提供影片观看状态（browsed/watched/wanted）的 CRUD 接口。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update

from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS

router = APIRouter()


# 三态枚举
VIEW_STATUS_BROWSED = "browsed"
VIEW_STATUS_WATCHED = "watched"
VIEW_STATUS_WANTED = "wanted"

VALID_STATUSES = {VIEW_STATUS_BROWSED, VIEW_STATUS_WATCHED, VIEW_STATUS_WANTED}


def _resolve_module(module: str) -> str:
    """解析模块名，无效时回退到 jav"""
    return module if module in MODULE_MODELS else "jav"


# ============================================
# 请求/响应模型
# ============================================

class ViewStatusRequest(BaseModel):
    """设置观看状态请求"""
    status: str | None = Field(..., description="browsed/watched/wanted，None 清除")


class BatchViewStatusRequest(BaseModel):
    """批量设置观看状态请求"""
    movie_ids: list[int] = Field(..., min_length=1, max_length=500)
    status: str = Field(..., description="browsed/watched/wanted")


class ViewStatusResponse(BaseModel):
    movie_id: int
    code: str | None = None
    view_status: str | None = None


class ViewStatusStatsResponse(BaseModel):
    browsed: int
    watched: int
    wanted: int
    unmarked: int


# ============================================
# 路由
# ============================================

@router.get("/stats", response_model=ViewStatusStatsResponse, summary="统计各状态影片数量")
async def get_view_status_stats(
    module: str = Query("jav", description="模块名: jav/fc2/uncensored/chinese/western/pornhub"),
):
    """统计 browsed/watched/wanted/unmarked 各状态影片数量"""
    module = _resolve_module(module)
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    result = {}
    for status in VALID_STATUSES:
        stmt = select(func.count(MovieModel.id)).where(MovieModel.view_status == status)
        r = await session.execute(stmt)
        result[status] = r.scalar() or 0

    stmt = select(func.count(MovieModel.id)).where(MovieModel.view_status.is_(None))
    r = await session.execute(stmt)
    result["unmarked"] = r.scalar() or 0

    return ViewStatusStatsResponse(**result)


@router.get("/{movie_id}", response_model=ViewStatusResponse, summary="获取单部影片观看状态")
async def get_movie_view_status(
    movie_id: int,
    module: str = Query("jav", description="模块名: jav/fc2/uncensored/chinese/western/pornhub"),
):
    module = _resolve_module(module)
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    movie = await session.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(404, f"影片 {movie_id} 不存在")
    return ViewStatusResponse(
        movie_id=movie.id, code=movie.code, view_status=movie.view_status
    )


@router.put("/{movie_id}", response_model=ViewStatusResponse, summary="设置单部影片观看状态")
async def set_movie_view_status(
    movie_id: int,
    body: ViewStatusRequest,
    module: str = Query("jav", description="模块名: jav/fc2/uncensored/chinese/western/pornhub"),
):
    """设置单部影片观看状态

    status 取值：
    - `browsed`：浏览过
    - `watched`：已观看
    - `wanted`：想看
    - `null`：清除标记
    """
    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(400, f"无效的 view_status: {body.status}，有效值: {VALID_STATUSES}")

    module = _resolve_module(module)
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    movie = await session.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(404, f"影片 {movie_id} 不存在")

    movie.view_status = body.status
    await session.commit()
    await session.refresh(movie)

    return ViewStatusResponse(
        movie_id=movie.id, code=movie.code, view_status=movie.view_status
    )


@router.post("/batch", summary="批量设置观看状态")
async def batch_set_view_status(
    body: BatchViewStatusRequest,
    module: str = Query("jav", description="模块名: jav/fc2/uncensored/chinese/western/pornhub"),
):
    """批量设置影片观看状态"""
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"无效的 view_status: {body.status}")

    if not body.movie_ids:
        return {"updated": 0, "status": body.status, "total_requested": 0}

    module = _resolve_module(module)
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    stmt = (
        update(MovieModel)
        .where(MovieModel.id.in_(body.movie_ids))
        .values(view_status=body.status)
    )
    result = await session.execute(stmt)
    await session.commit()
    updated = result.rowcount or 0

    return {"updated": updated, "status": body.status, "total_requested": len(body.movie_ids)}


@router.get("/", summary="按状态列出影片")
async def list_movies_by_status(
    status: str = Query(..., description="browsed/watched/wanted"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    module: str = Query("jav", description="模块名: jav/fc2/uncensored/chinese/western/pornhub"),
):
    """按观看状态列出影片"""
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"无效的 view_status: {status}")

    module = _resolve_module(module)
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    stmt = (
        select(MovieModel)
        .where(MovieModel.view_status == status)
        .order_by(MovieModel.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    movies = result.scalars().all()

    return {
        "status": status,
        "total": len(movies),
        "items": [
            {
                "id": m.id,
                "code": m.code,
                "title": m.title,
                "cover_url": m.cover_url,
                "view_status": m.view_status,
                "last_played_at": m.last_played_at.isoformat() if m.last_played_at else None,
            }
            for m in movies
        ],
    }
