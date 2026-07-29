"""Stash 兼容 API 路由 — 让外部 Stash 插件通过 MDCX 刮削元数据。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.stash_compat import (
    stash_scene_by_url,
    stash_scene_by_name,
    stash_performer_by_name,
)

router = APIRouter()


@router.get("/scene/url")
async def api_stash_scene_by_url(url: str = Query(..., description="场景 URL")):
    """Stash 标准：通过 URL 刮削场景。"""
    scene = await stash_scene_by_url(url)
    if not scene:
        raise HTTPException(status_code=404, detail="scene not found")
    return scene


@router.get("/scene/search")
async def api_stash_scene_search(
    name: str = Query(..., description="场景名称"),
    brand: str = Query("", description="可选品牌过滤"),
):
    """Stash 标准：通过名称搜索场景。"""
    scene = await stash_scene_by_name(name, brand)
    if not scene:
        return {"title": name, "note": "not found"}
    return scene


@router.get("/performer/search")
async def api_stash_performer_search(name: str = Query(..., description="演员名称")):
    """Stash 标准：搜索演员。"""
    performer = await stash_performer_by_name(name)
    if not performer:
        return {"name": name, "note": "not found"}
    return performer
