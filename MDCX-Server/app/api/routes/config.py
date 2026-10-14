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
        # 若命中 curl_cffi 原生层致命错误，顺带置位**进程级**降级标志，
        # 让后续刮削请求提前走 httpx（此处不 re-raise，仍返回错误 dict）。
        try:
            from app.utils.http_client import is_fatal_curl_error, mark_curl_unavailable
            if is_fatal_curl_error(e):
                mark_curl_unavailable(f"连通性测试命中 curl_cffi 致命错误: {e!r}")
        except Exception:
            pass
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


# ===== 按站点代理覆盖（amane #365）=====

@router.get("/site-proxy")
async def get_site_proxy(_admin: dict = Depends(require_admin)):
    """读取「按站点覆盖代理」配置。

    用途：某些站点封代理出口 IP（走代理必失败），或某些地域站需要另一条出口
    （如 DMM/FANZA 走日本节点）。在全局代理之外给它单独指定代理或强制直连。
    """
    from app.services import site_proxy

    return site_proxy.describe()


@router.put("/site-proxy")
async def put_site_proxy(
    payload: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """写入「按站点覆盖代理」配置。

    请求体：
        {"enabled": true, "sites": {"javdb": "socks5://127.0.0.1:10808",
                                    "javbus.com": "direct"}}

    - key 可以是**爬虫名**（javdb / dmm_web ...）或**域名**（javbus.com）。
      域名支持后缀匹配，且取最长匹配，避免 javdb 误覆盖 javdb_new。
    - value 为 direct / none / off / 空 → 该站强制直连。
    """
    from app.services import site_proxy

    try:
        saved = site_proxy.save_config(payload or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("保存站点代理配置失败: %s", e)
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)[:120]}")

    logger.info("按站点代理配置已更新：%d 条", len(saved.get("sites") or {}))
    return site_proxy.describe()


@router.post("/site-proxy/test")
async def test_site_proxy(
    payload: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """解析一次：给定站点名/URL，报告实际会走哪条代理（不发起请求）。

    用于在保存前确认匹配是否符合预期（尤其是域名后缀匹配有没有误伤）。
    """
    from app.services import site_proxy
    from app.services.proxy_manager import get_effective_proxy_url

    site = str(payload.get("site") or "").strip()
    url = str(payload.get("url") or "").strip()
    hit = site_proxy.resolve(site=site, url=url)
    effective = get_effective_proxy_url(site=site, url=url)
    return {
        "site": site,
        "url": url,
        "override": None if hit is None else ("direct" if hit[1] is None else hit[1]),
        "matched": hit is not None,
        "effective_proxy": effective,
        "mode": "direct" if effective is None else "proxy",
    }


# ===== 跨机路径对照表（openaver 0.17.7）=====

@router.get("/path-map")
async def get_path_map(_admin: dict = Depends(require_admin)):
    """读取「跨机路径对照表」配置。"""
    from app.services import path_map

    return path_map.describe()


@router.put("/path-map")
async def put_path_map(
    payload: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """写入「跨机路径对照表」配置。

    请求体：
        {"enabled": true,
         "rules": [{"remote": "/volume1/av", "local": "\\\\NAS\\av", "enabled": true}]}

    - remote / local 互为镜像：map_to_local 用 remote→local，map_to_remote 反之。
    - 仅当两者都非空才保留该条规则。
    """
    from app.services import path_map

    try:
        saved = path_map.save_config(payload or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("路径对照表已更新：%d 条规则", len(saved.get("rules") or []))
    return path_map.describe()


@router.post("/path-map/test")
async def test_path_map(
    payload: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """解析一次：给定路径，报告经对照表后的结果（不改动配置）。

    请求体：{"path": "/volume1/av/ABC-123/ABC-123.mp4", "direction": "to_local"}
    direction 缺省 to_local；可传 to_remote。
    """
    from app.services import path_map

    p = str(payload.get("path") or "").strip()
    direction = str(payload.get("direction") or "to_local").strip().lower()
    if direction == "to_remote":
        result = path_map.map_to_remote(p)
        applied = result != p
        return {"input": p, "direction": "to_remote", "output": result, "changed": applied}
    result = path_map.map_to_local(p)
    applied = result != p
    return {"input": p, "direction": "to_local", "output": result, "changed": applied}


# ===== 自定义来源 YAML 规则档（openaver 0.17.7）=====

@router.get("/custom-sources")
async def list_custom_sources(_admin: dict = Depends(require_admin)):
    """列出 data/custom_sources 下全部规则档及其校验状态。"""
    from app.services.custom_source import registry

    items = []
    for spec, errors in registry.load_all():
        raw_yaml = ""
        try:
            p = registry.sources_dir() / f"{spec.name}.yaml"
            if p.exists():
                raw_yaml = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            raw_yaml = ""
        items.append({
            "name": spec.name,
            "display_name": spec.display_name,
            "enabled": spec.enabled,
            "base_url": spec.base_url,
            "has_search": spec.has_search,
            "has_detail": spec.has_detail,
            "test_case_count": len(spec.test_cases),
            "valid": not errors,
            "errors": errors,
            "yaml": raw_yaml,
        })
    return {"items": items}


@router.post("/custom-sources/validate")
async def validate_custom_source(
    payload: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """校验一段 YAML（不落盘），并离线跑通其 test_cases。

    验收硬条件：test_cases 必须至少一例 expect: not_found，且能真正判定为 not_found。
    请求体：{"yaml": "<YAML 文本>"}
    """
    from app.services.custom_source import registry, schema

    text = str(payload.get("yaml") or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="yaml 不能为空")
    try:
        spec_dict = schema.load_spec_from_yaml(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errors = schema.validate_spec(spec_dict)
    test_results = []
    if not errors:
        try:
            test_results = registry.run_test_cases(spec_dict)
        except Exception as e:  # noqa: BLE001
            errors.append(f"test_cases 运行异常: {e}")
    return {
        "valid": not errors,
        "errors": errors,
        "test_results": test_results,
    }


@router.put("/custom-sources/{name}")
async def put_custom_source(
    name: str,
    payload: dict[str, Any],
    _admin: dict = Depends(require_admin),
):
    """保存（新增/覆盖）一个规则档。校验失败返回 400 且不落盘。"""
    from app.services.custom_source import registry

    text = str(payload.get("yaml") or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="yaml 不能为空")
    spec, errors = registry.save_spec(name, text)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))
    return {"name": spec.name, "display_name": spec.display_name, "saved": True}


@router.delete("/custom-sources/{name}")
async def delete_custom_source(
    name: str,
    _admin: dict = Depends(require_admin),
):
    """删除一个规则档。"""
    from app.services.custom_source import registry

    ok = registry.delete_spec(name)
    return {"name": name, "deleted": ok}
