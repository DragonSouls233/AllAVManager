"""站点 Cookie 管理 API 路由

提供"走内置代理 → 打开浏览器 → 用户手动登录 → 自动保存 Cookie"的完整流程。

POST  /api/v1/cookies/login/{site}    → 启动浏览器登录
GET   /api/v1/cookies/login/{site}    → 查询登录进度
GET   /api/v1/cookies/status          → 所有站点 Cookie 状态概览
GET   /api/v1/cookies/supported       → 列出支持的站点
POST  /api/v1/cookies/validate/{site} → 验证 Cookie 有效性
PUT   /api/v1/cookies/{site}          → 手动写入 Cookie（粘贴文本）
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.utils.cookie_manager import (
    COOKIE_SITES,
    get_all_status,
    get_cookie,
    set_cookie,
    validate_cookie,
    login_with_browser,
)
from app.utils.cookie_login import get_login_status
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class CookieWriteRequest(BaseModel):
    """手动写入 Cookie 请求"""
    cookie: str
    note: Optional[str] = None


@router.get("/supported")
async def list_supported_sites():
    """列出所有支持 Cookie 登录的站点"""
    return {
        "sites": [
            {
                "id": site_id,
                "name": cfg["name"],
                "domain": cfg["domain"],
                "login_url": cfg["login_url"],
                "has_cookie": bool(get_cookie(site_id)),
            }
            for site_id, cfg in COOKIE_SITES.items()
        ]
    }


@router.get("/status")
async def cookie_status():
    """获取所有站点的 Cookie 状态（含预览）"""
    return get_all_status()


@router.post("/login/{site}")
async def start_cookie_login(site: str):
    """启动浏览器登录流程

    浏览器将使用项目内置代理打开，保证 Cookie 绑定的 IP 与爬虫一致。

    支持的 site: javdb, javbus, fc2ppvdb, pan115
    """
    site = site.lower().strip()
    if site not in COOKIE_SITES:
        return {
            "success": False,
            "error": f"不支持的站点: {site}",
            "supported": list(COOKIE_SITES.keys()),
        }
    result = login_with_browser(site)
    return result


@router.get("/login/{site}")
async def check_login_status(site: str):
    """查询浏览器登录的实时进度"""
    site = site.lower().strip()
    if site not in COOKIE_SITES:
        return {"status": "error", "message": f"不支持的站点: {site}"}
    return get_login_status(site)


@router.post("/validate/{site}")
async def validate_site_cookie(site: str):
    """验证指定站点的 Cookie 是否有效"""
    site = site.lower().strip()
    if site not in COOKIE_SITES:
        return {"valid": False, "message": f"不支持的站点: {site}", "site": site}
    result = await validate_cookie(site)
    return {"site": site, **result}


@router.put("/{site}")
async def write_cookie_manually(site: str, req: CookieWriteRequest):
    """手动粘贴 Cookie 文本（不通过浏览器登录）

    适用于已有现成 Cookie 或从其他浏览器导出的场景。
    """
    site = site.lower().strip()
    if site not in COOKIE_SITES:
        return {
            "success": False,
            "error": f"不支持的站点: {site}",
            "supported": list(COOKIE_SITES.keys()),
        }

    cookie_str = req.cookie.strip()
    if not cookie_str:
        return {"success": False, "error": "Cookie 内容为空"}

    ok = set_cookie(site, cookie_str)
    if ok:
        logger.info(f"手动写入 {site} Cookie 成功，长度 {len(cookie_str)}")
        return {
            "success": True,
            "message": f"{COOKIE_SITES[site]['name']} Cookie 已手动保存",
            "length": len(cookie_str),
        }
    else:
        return {"success": False, "error": "Cookie 保存失败"}


@router.delete("/{site}")
async def delete_cookie(site: str):
    """清空指定站点的 Cookie"""
    site = site.lower().strip()
    if site not in COOKIE_SITES:
        return {"success": False, "error": f"不支持的站点: {site}"}

    set_cookie(site, "")
    return {"success": True, "message": f"{COOKIE_SITES[site]['name']} Cookie 已清空"}
