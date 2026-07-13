"""
配置管理路由
"""

import time
from typing import Any

from curl_cffi.requests import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.config.manager import get_config_manager
from app.config.models import Config
from app.api.routes.auth import require_admin
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("")
async def get_config():
    """获取配置"""
    manager = get_config_manager()
    return manager.config.model_dump()


def _strip_media_dirs(updates: dict[str, Any]) -> bool:
    """递归剔除 media_dirs 键——媒体目录仅允许服务端本机绑定，不接受网络请求修改

    Returns:
        是否剔除了任何 media_dirs 键
    """
    stripped = False
    if "media_dirs" in updates:
        del updates["media_dirs"]
        stripped = True
    scraper = updates.get("scraper")
    if isinstance(scraper, dict) and "media_dirs" in scraper:
        del scraper["media_dirs"]
        stripped = True
    return stripped


@router.patch("")
async def update_config(
    updates: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """更新配置（仅管理员）

    注意：media_dirs（媒体目录）为服务端本机绑定项，此处强制剔除，
    任何网络请求（含管理员 token）都无法通过此接口修改，必须走服务器本机的
    config.yaml 或 tools/bind_media.py 工具。
    """
    if _strip_media_dirs(updates):
        logger.warning("PATCH /config 尝试修改 media_dirs 已被忽略（媒体目录仅服务端本机可绑定）")

    manager = get_config_manager()
    errors = manager.update(**updates)

    if errors:
        raise HTTPException(status_code=400, detail=errors)

    manager.save()
    return {"status": "ok", "config": manager.config.model_dump()}


@router.post("/reset")
async def reset_config(_admin: dict = Depends(require_admin)):
    """重置配置为默认值（仅管理员）"""
    manager = get_config_manager()
    manager.reset()
    return {"status": "ok", "config": manager.config.model_dump()}


# ===== 代理测试 =====

# 代理测试目标（通用网络连通性）
PROXY_TEST_TARGETS = [
    {"name": "Google", "url": "https://www.google.com"},
    {"name": "YouTube", "url": "https://www.youtube.com"},
    {"name": "GitHub", "url": "https://github.com"},
    {"name": "百度", "url": "https://www.baidu.com"},
]


@router.post("/test-proxy")
async def test_proxy():
    """
    测试代理连通性

    使用 curl_cffi（和爬虫相同的 HTTP 客户端）测试各站点的直连和通过代理的连接情况，
    避免 httpx 的 SOCKS5 兼容问题。
    """
    manager = get_config_manager()
    config = manager.config
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()
    proxy_enabled = bool(proxy_url)

    results = []

    for target in PROXY_TEST_TARGETS:
        direct_result = await _test_url_curl(target["url"])
        
        # 通过代理测试
        proxy_result = None
        if proxy_enabled:
            proxy_result = await _test_url_curl(target["url"], proxy=proxy_url)
        
        results.append({
            "name": target["name"],
            "url": target["url"],
            "direct": direct_result,
            "proxy": proxy_result,
        })

    return {
        "proxy_configured": proxy_enabled,
        "proxy_url": proxy_url,
        "results": results,
        "proxy_working": any(r.get("proxy", {}).get("success") for r in results) if proxy_enabled else None,
    }


async def _test_url_curl(url: str, proxy: str | None = None, timeout: float = 10.0) -> dict:
    """使用 curl_cffi 测试 URL 可达性（和爬虫使用相同的 HTTP 引擎）"""
    start = time.time()
    session = None
    try:
        kwargs = {
            "timeout": timeout,
            "verify": False,
        }
        if proxy:
            kwargs["proxy"] = proxy

        session = AsyncSession(**kwargs)
        resp = await session.get(url, impersonate="chrome124")
        elapsed = (time.time() - start) * 1000
        return {
            "success": resp.status_code < 500,
            "status_code": resp.status_code,
            "time_ms": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        error_msg = str(e)
        if len(error_msg) > 80:
            error_msg = error_msg[:80] + "..."
        return {
            "success": False,
            "status_code": None,
            "time_ms": round(elapsed, 1),
            "error": error_msg,
        }
    finally:
        if session:
            try:
                await session.close()
            except Exception:
                pass


# ===== Cookie 检查 =====

@router.post("/check-javdb-cookie")
async def check_javdb_cookie(data: dict[str, Any]):
    """测试 JavDB Cookie 是否有效"""
    cookie = data.get("cookie", "")
    if not cookie:
        return {"valid": False, "message": "未提供 Cookie"}

    try:
        from app.utils.http_client import AsyncHttpClient
        from app.config.manager import get_config
        config = get_config()
        from app.services.proxy_manager import get_effective_proxy_url
        proxy = get_effective_proxy_url()

        async with AsyncHttpClient(proxy=proxy, timeout=15) as client:
            resp = await client.get(
                "https://javdb.com/users/home",
                headers={"cookie": cookie, "User-Agent": "Mozilla/5.0"},
                impersonate="chrome124",
            )
            low = resp.text.lower()
            # fix23c: 之前只检查 "JavDB" in text，但登录页也含 "JavDB" 字样 -> 误判有效
            # 改为检查是否被重定向到登录页
            if "<title>登入" in low or "<title>login" in low or "return_to_url" in low:
                return {"valid": False, "message": "Cookie 已失效（被重定向到登录页），请重新登录获取"}
            if "cloudflare" in low and len(resp.text) < 5000:
                return {"valid": False, "message": "已被 Cloudflare 拦截"}
            if resp.status_code == 200 and "JavDB" in resp.text:
                return {"valid": True, "message": "JavDB Cookie 有效"}
            else:
                return {"valid": False, "message": f"Cookie 无效 (HTTP {resp.status_code})"}
    except Exception as e:
        return {"valid": False, "message": f"请求失败: {str(e)[:80]}"}


# ===== 统一 Cookie 管理端点 (fix24) =====

from app.utils.cookie_manager import (
    get_supported_sites, get_cookie, set_cookie, get_cookie_headers,
    get_all_status, validate_cookie, login_with_browser,
)
from app.utils.cookie_login import start_login, get_login_status


@router.get("/cookie/status")
async def cookie_status():
    """获取所有站点 Cookie 状态"""
    try:
        return get_all_status()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.post("/cookie/{site}/login")
async def cookie_unified_login(site: str):
    """启动浏览器登录 - 走项目内置代理，保证 Cookie IP 一致"""
    try:
        result = login_with_browser(site)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@router.get("/cookie/{site}/status")
async def cookie_login_status_unified(site: str):
    """查询浏览器登录状态"""
    try:
        return get_login_status(site)
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


@router.post("/cookie/{site}/validate")
async def cookie_validate(site: str):
    """验证指定站点 Cookie 是否有效"""
    try:
        return await validate_cookie(site)
    except Exception as e:
        return {"valid": False, "message": str(e)[:200]}


@router.put("/cookie/{site}")
async def cookie_set(site: str, payload: dict):
    """手动设置 Cookie"""
    try:
        cookie_value = payload.get("cookie", "")
        if not cookie_value:
            return {"success": False, "message": "Cookie 值为空"}
        ok = set_cookie(site, cookie_value)
        return {"success": ok, "message": "Cookie 已保存" if ok else "保存失败"}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}


@router.post("/cookie-login/{site}")
async def cookie_login(site: str):
    """Open browser for user to login and save cookies"""
    from app.utils.cookie_login import start_login, SUPPORTED_SITES

    if site not in SUPPORTED_SITES:
        raise HTTPException(status_code=400, detail=f"不支持的站点: {site}")

    result = start_login(site)
    return result


@router.get("/cookie-login/{site}/status")
async def cookie_login_status(site: str):
    """Get login status"""
    from app.utils.cookie_login import get_login_status

    status = get_login_status(site)
    return status


@router.post("/stealth-fetch")
async def test_stealth_fetch(request: dict):
    """Test StealthyFetcher for a URL"""
    from app.utils.stealth_fetcher import stealth_fetch, is_available

    if not is_available():
        return {"success": False, "message": "Scrapling 未安装，请运行: pip install scrapling[all]"}

    url = request.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    result = await stealth_fetch(url)
    if result:
        return {"success": True, "status": result["status"], "html_length": len(result["html"])}
    return {"success": False, "message": "请求失败"}


@router.get("/debug/crawler-cookie")
async def debug_crawler_cookie():
    """调试：返回当前各爬虫实际读到的 cookie 状态（脱敏显示）

    用于排查「前端 PATCH 写入但爬虫读不到」类问题。
    已迁移到统一的 cookie_manager.get_all_status()，保持兼容。
    """
    try:
        return get_all_status()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.post("/check-javbus-cookie")
async def check_javbus_cookie(data: dict[str, Any]):
    """测试 JavBus Cookie 是否有效"""
    cookie = data.get("cookie", "")
    if not cookie:
        return {"valid": False, "message": "未提供 Cookie"}

    try:
        from app.utils.http_client import AsyncHttpClient
        from app.config.manager import get_config
        config = get_config()
        from app.services.proxy_manager import get_effective_proxy_url
        proxy = get_effective_proxy_url()

        async with AsyncHttpClient(proxy=proxy, timeout=15) as client:
            resp = await client.get(
                "https://www.javbus.com",
                headers={"cookie": cookie, "User-Agent": "Mozilla/5.0"},
                impersonate="chrome124",
            )
            if resp.status_code == 200 and "JavBus" in resp.text:
                return {"valid": True, "message": "JavBus Cookie 有效"}
            elif "cloudflare" in resp.text.lower() or "driver-verify" in resp.text.lower():
                return {"valid": False, "message": "Cookie 无效或已被 Cloudflare 拦截"}
            else:
                return {"valid": False, "message": f"Cookie 无效 (HTTP {resp.status_code})"}
    except Exception as e:
        return {"valid": False, "message": f"请求失败: {str(e)[:80]}"}
