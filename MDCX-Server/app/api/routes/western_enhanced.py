"""欧美模块新增路由 — 批量搜索 + 品牌映射 + IAFD 加速。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.crawlers.western_aggregate import WesternAggregateCrawler, WesternBulkSearcher
from app.services.western_utils import AYLO_BRANDS, VIXEN_SITES, normalize_scene_url, extract_brand_from_url

router = APIRouter()


@router.get("/brands")
async def api_western_brands():
    """返回所有已知欧美品牌列表。"""
    return {
        "aylo_brands": [
            {"name": b.name, "domain": b.domain, "tags": b.tags}
            for b in AYLO_BRANDS
        ],
        "vixen_sites": [
            {"domain": d, "name": n} for d, n in VIXEN_SITES.items()
        ],
        "total": len(AYLO_BRANDS) + len(VIXEN_SITES),
    }


@router.post("/aggregate-search")
async def api_western_aggregate_search(data: dict):
    """聚合搜索欧美场景。

    Body:
    {
        "query": "Busty Mom Seduces Son",
        "mode": "fast" | "deep",     # fast=只查TPDB, deep=IAFD+TPDB
        "brand": "brazzers"          # 可选品牌过滤
    }
    """
    query = data.get("query", "")
    mode = data.get("mode", "fast")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    if mode == "deep":
        crawler = WesternBulkSearcher()
    else:
        crawler = WesternAggregateCrawler()

    r = await crawler.scrape(query)
    return {
        "query": query,
        "mode": mode,
        "brand_guess": extract_brand_from_url(query),
        "result": r.__dict__ if r else None,
    }
