"""
维基百科（中文）数据接口

提供：
- GET /api/v1/wikipedia/actress-category - 日本AV女优 分类成员列表（演员发现）
"""
from fastapi import APIRouter, Query

from app.services.wikipedia_category_service import fetch_actress_category

router = APIRouter()


@router.get("/actress-category", summary="维基百科 日本AV女优 分类成员")
async def wikipedia_actress_category(
    limit: int = Query(200, ge=1, le=500, description="单次拉取条数"),
    continue_token: str | None = Query(None, description="分页游标（gcmcontinue），从第一页开始可省略"),
):
    """实时抓取中文维基百科「Category:日本AV女優」分类下的女优条目"""
    return await fetch_actress_category(limit=limit, continue_token=continue_token)
