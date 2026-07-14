"""
站点注册表管理 API 路由

提供内置站点配置的查询接口：
- GET /sites             获取所有站点配置
- GET /sites/{category}  按分类获取站点
- GET /sites/scrapable   获取可刮削的站点
- GET /sites/downloadable 获取可下载的站点
- GET /sites/lookup      根据 URL 查找站点
"""

from fastapi import APIRouter, Query

from app.config.site_registry import (
    ALL_SITES,
    SiteCategory,
    get_site_by_url,
    get_scrapable_sites,
    get_downloadable_sites,
    get_sites_by_category,
)

router = APIRouter(prefix="/sites", tags=["站点注册表"])


@router.get("")
async def list_all_sites():
    """获取所有站点配置"""
    result = {}
    for category, sites in ALL_SITES.items():
        result[category.value] = [
            {"id": k, **v}
            for k, v in sites.items()
        ]
    return result


@router.get("/{category}")
async def get_sites_by_category_endpoint(category: SiteCategory):
    """按分类获取站点（chinese / western / jav / magnet）"""
    sites = get_sites_by_category(category)
    return [
        {"id": k, **v}
        for k, v in sites.items()
    ]


@router.get("/scrapable/list")
async def get_scrapable_sites_endpoint(category: SiteCategory = Query(...)):
    """获取可刮削的站点列表"""
    return get_scrapable_sites(category)


@router.get("/downloadable/list")
async def get_downloadable_sites_endpoint(category: SiteCategory = Query(...)):
    """获取可下载的站点列表"""
    return get_downloadable_sites(category)


@router.get("/lookup/url")
async def lookup_site(url: str = Query(..., description="要查询的 URL")):
    """根据 URL 查找站点配置"""
    site = get_site_by_url(url)
    if not site:
        return {"found": False, "url": url}
    return {"found": True, "url": url, "site": site}


@router.get("/category/list")
async def list_categories():
    """获取所有分类"""
    return {
        "categories": [
            {"id": "chinese", "name": "国产站点", "count": len(get_sites_by_category(SiteCategory.CHINESE))},
            {"id": "western", "name": "欧美站点", "count": len(get_sites_by_category(SiteCategory.WESTERN))},
            {"id": "jav", "name": "JAV站点", "count": len(get_sites_by_category(SiteCategory.JAV))},
        ]
    }
