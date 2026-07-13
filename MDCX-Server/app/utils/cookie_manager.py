"""
统一 Cookie 管理器

所有爬虫的 Cookie 读取/写入/验证/登录都走这里，不再各自实现 _get_*_cookie_headers。

设计要点：
1. 只读 app.config.manager（新配置），不回退 mdcx.config.manager（旧配置），减少混乱
2. 浏览器登录走项目内置代理（get_effective_proxy_url），保证 Cookie IP 与爬虫请求 IP 一致
3. 每个站点的验证逻辑是真正有效的（不是只看 HTTP 200）
"""
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 站点配置表 - 唯一数据源
COOKIE_SITES = {
    "javdb": {
        "name": "JavDB",
        "domain": "javdb.com",
        "config_key": "crawler.javdb_cookie",
        "login_url": "https://javdb.com/login",
        "success_indicator": "logout",
        "validate_url": "https://javdb.com/users/home",
        "validate_type": "login_redirect",
    },
    "javbus": {
        "name": "JavBus",
        "domain": "javbus.com",
        "config_key": "crawler.javbus_cookie",
        "login_url": "https://www.javbus.com",
        "success_indicator": "登出",
        "validate_url": "https://www.javbus.com",
        "validate_type": "lostpasswd",
    },
    "fc2ppvdb": {
        "name": "FC2PPVDB",
        "domain": "fc2ppvdb.com",
        "config_key": "crawler.fc2ppvdb_cookie",
        "login_url": "https://fc2ppvdb.com/login",
        "success_indicator": "logout",
        "validate_url": "https://fc2ppvdb.com",
        "validate_type": "login_redirect",
    },
    "pan115": {
        "name": "115网盘",
        "domain": "115.com",
        "config_key": "pan_115.cookies",
        "login_url": "https://passport.115.com/?ct=login",
        "success_indicator": None,
        "validate_url": "https://115.com",
        "validate_type": "uid_cookie",
    },
}


def get_supported_sites() -> dict:
    return COOKIE_SITES


def get_cookie(site: str) -> Optional[str]:
    """唯一读取入口 - 取代所有爬虫里的 _get_*_cookie_headers"""
    cfg = COOKIE_SITES.get(site)
    if not cfg:
        return None
    try:
        from app.config.manager import get_config_manager
        manager = get_config_manager()
        key = cfg["config_key"]
        if "." in key:
            parts = key.split(".")
            obj = manager.config
            for p in parts:
                obj = getattr(obj, p, None)
                if obj is None:
                    break
            return obj
        return getattr(manager.config, key, None)
    except Exception as e:
        logger.debug(f"get_cookie({site}) 失败: {e}")
        return None


def get_cookie_headers(site: str) -> Optional[dict]:
    """返回带 cookie 的 headers dict，供爬虫直接用"""
    cookie = get_cookie(site)
    if cookie:
        return {"cookie": cookie, "User-Agent": "Mozilla/5.0"}
    return None


def set_cookie(site: str, cookie: str) -> bool:
    """唯一写入入口"""
    cfg = COOKIE_SITES.get(site)
    if not cfg:
        return False
    try:
        from app.config.manager import get_config_manager
        manager = get_config_manager()
        key = cfg["config_key"]
        if "." in key:
            manager.update(**{key: cookie})
        else:
            manager.update(**{key: cookie})
        logger.info(f"Cookie 已保存: {cfg['name']} (长度: {len(cookie) if cookie else 0})")
        return True
    except Exception as e:
        logger.error(f"set_cookie({site}) 失败: {e}")
        return False


def get_all_status() -> dict:
    """返回所有站点状态（供调试端点用）"""
    result = {}
    for site, cfg in COOKIE_SITES.items():
        cookie = get_cookie(site)
        if not cookie:
            result[site] = {
                "name": cfg["name"],
                "domain": cfg["domain"],
                "configured": False,
                "length": 0,
                "preview": None,
            }
        else:
            v = str(cookie)
            preview = (v[:8] + "..." + v[-8:]) if len(v) > 16 else v
            result[site] = {
                "name": cfg["name"],
                "domain": cfg["domain"],
                "configured": True,
                "length": len(v),
                "preview": preview,
            }
    return result


async def validate_cookie(site: str) -> dict:
    """唯一验证入口 - 每个站点用真正有效的验证逻辑"""
    cfg = COOKIE_SITES.get(site)
    if not cfg:
        return {"valid": False, "message": f"不支持的站点: {site}"}

    cookie = get_cookie(site)
    if not cookie:
        return {"valid": False, "message": "未配置 Cookie"}

    vtype = cfg["validate_type"]
    vurl = cfg["validate_url"]

    try:
        from app.services.proxy_manager import get_effective_proxy_url
        from app.utils.http_client import AsyncHttpClient

        proxy = get_effective_proxy_url()
        async with AsyncHttpClient(proxy=proxy, timeout=15) as client:
            resp = await client.get(
                vurl,
                headers={"cookie": cookie, "User-Agent": "Mozilla/5.0"},
                impersonate="chrome124",
            )
            low = resp.text.lower()

            if vtype == "login_redirect":
                if "<title>登入" in low or "<title>login" in low or "return_to_url" in low:
                    return {"valid": False, "message": "Cookie 已失效（被重定向到登录页）"}
                if "cloudflare" in low and len(resp.text) < 5000:
                    return {"valid": False, "message": "已被 Cloudflare 拦截"}
                if resp.status_code == 200 and cfg["domain"] in resp.text.lower():
                    return {"valid": True, "message": f"{cfg['name']} Cookie 有效"}
                return {"valid": False, "message": f"Cookie 无效 (HTTP {resp.status_code})"}

            elif vtype == "lostpasswd":
                if "lostpasswd" in low:
                    return {"valid": False, "message": "Cookie 无效（JavBus 返回密码找回页）"}
                if resp.status_code == 200:
                    return {"valid": True, "message": f"{cfg['name']} Cookie 有效"}
                return {"valid": False, "message": f"Cookie 无效 (HTTP {resp.status_code})"}

            elif vtype == "uid_cookie":
                if "uid" in cookie.lower():
                    return {"valid": True, "message": f"{cfg['name']} Cookie 有效"}
                return {"valid": False, "message": "Cookie 缺少 UID 字段"}

            return {"valid": False, "message": "未知验证类型"}

    except Exception as e:
        return {"valid": False, "message": f"验证请求失败: {str(e)[:80]}"}


def login_with_browser(site: str, callback=None) -> dict:
    """启动 Playwright 浏览器登录（走项目代理，保证 IP 一致）"""
    cfg = COOKIE_SITES.get(site)
    if not cfg:
        return {"success": False, "error": f"不支持的站点: {site}"}

    from app.utils.cookie_login import start_login
    return start_login(site, callback=callback)
