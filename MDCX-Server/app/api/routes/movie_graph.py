"""影片图谱路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_session
from app.services.movie_graph import movie_graph_service

router = APIRouter()


class RelationRequest(BaseModel):
    movie_id: int
    related_movie_id: int
    relation_type: str
    weight: float = 1.0


@router.get("/{movie_id}/graph")
async def get_graph(
    movie_id: int,
    depth: int = 1,
    session: AsyncSession = Depends(get_session)
):
    """获取影片关联图谱"""
    return await movie_graph_service.get_graph(movie_id, depth, session)


@router.get("/{movie_id}/recommendations")
async def get_recommendations(
    movie_id: int,
    limit: int = 10,
    session: AsyncSession = Depends(get_session)
):
    """获取关联推荐"""
    return {"items": await movie_graph_service.get_recommendations(movie_id, limit, session)}


@router.post("/relation")
async def save_relation(
    req: RelationRequest,
    session: AsyncSession = Depends(get_session)
):
    """保存关联关系"""
    success = await movie_graph_service.save_relation(
        req.movie_id, req.related_movie_id, req.relation_type, req.weight, session
    )
    return {"status": "ok" if success else "exists"}
