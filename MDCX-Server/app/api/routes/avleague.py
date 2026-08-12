"""
AVリーグ（AV联盟）数据接口

提供：
- GET /api/v1/avleague/leaderboard - 实时榜单（新人 / 全女优，多周期）
- GET /api/v1/avleague/actor-works - 演员作品列表 + 本地库比对（新作发现）
"""
from fastapi import APIRouter, Query

from app.services.avleague_service import fetch_leaderboard, get_actor_new_works

router = APIRouter()


@router.get("/leaderboard", summary="AV联盟实时榜单")
async def avleague_leaderboard(
    kind: str = Query("all", description="榜单类型：all=全女优，new=新人"),
    period: str = Query("3d", description="统计周期：24h / 3d / 30d / year / newest / all"),
    page: int = Query(1, ge=1, description="页码"),
    tag: int | None = Query(None, description="标签 ID（如 27=巨乳、19=美少女、50=20代）"),
):
    """实时抓取 AV联盟 演员人气榜单（每次请求实时抓取，不缓存）"""
    return await fetch_leaderboard(kind=kind, period=period, page=page, tag=tag)


@router.get("/actor-works", summary="演员作品列表 + 新作发现")
async def avleague_actor_works(
    name: str = Query(..., description="演员名"),
    limit: int = Query(15, ge=1, le=30, description="最多比对的近期作品数"),
    module: str = Query("jav", description="本地比对用的模块库"),
):
    """搜索 AV联盟 演员，拉取近期作品并提取番号，与本地库比对标记是否已收录"""
    return await get_actor_new_works(name=name, limit=limit, module=module)
