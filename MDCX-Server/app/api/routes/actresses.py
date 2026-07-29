"""女优收藏 + 相似探索 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.actress_manager import (
    ActressCollect,
    get_actress_db,
    SimilarityEngine,
    SimilarMovie,
)

router = APIRouter()
engine = SimilarityEngine()


@router.get("")
async def api_list_actresses(
    keyword: str = Query("", description="搜索关键词"),
    tier: int = Query(0, description="分级过滤 (0=全部)"),
    favorite_only: bool = Query(False, description="仅收藏"),
    sort_by: str = Query("movie_count", description="排序: movie_count/name/tier"),
):
    """获取女优收藏列表。"""
    db = get_actress_db()

    if keyword:
        results = db.search(keyword)
    elif favorite_only:
        results = db.get_favorites()
    elif tier > 0:
        results = db.get_by_tier(tier)
    else:
        results = db.all()

    if sort_by == "name":
        results.sort(key=lambda a: a.name)
    elif sort_by == "tier":
        results.sort(key=lambda a: a.tier)

    return {
        "total": len(results),
        "items": [a.__dict__ for a in results],
    }


@router.get("/stats")
async def api_actress_stats():
    """女优数据库统计。"""
    return get_actress_db().stats()


@router.post("/{name}/favorite")
async def api_actress_favorite(name: str, favorite: bool = True):
    """设置/取消收藏。"""
    db = get_actress_db()
    a = db.get(name)
    if not a:
        raise HTTPException(status_code=404, detail=f"未找到: {name}")
    db.set_favorite(name, favorite)
    return {"name": name, "favorite": favorite}


@router.post("/{name}/tier")
async def api_actress_tier(name: str, tier: int = Query(3, ge=1, le=5)):
    """设置女优分级。"""
    db = get_actress_db()
    a = db.get(name)
    if not a:
        raise HTTPException(status_code=404, detail=f"未找到: {name}")
    db.set_tier(name, tier)
    return {"name": name, "tier": tier}


@router.post("/sync")
async def api_actress_sync():
    """从各模块数据库同步女优信息。"""
    db = get_actress_db()
    db.sync_from_db()
    stats = db.stats()
    return {"status": "synced", "stats": stats}
