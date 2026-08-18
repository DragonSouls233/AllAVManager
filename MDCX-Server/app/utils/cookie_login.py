"""
Cookie 登录助手

使用 Playwright 打开浏览器窗口（走项目内置代理），让用户登录后自动保存 Cookie。

关键设计：浏览器走 get_effective_proxy_url() 返回的代理，保证 Cookie 绑定的 IP
与爬虫后续请求的 IP 一致，避免「Cookie 在本机有效但在服务器失效」的问题。

线程模型（fix）：FastAPI 端点是 async 的，旧实现用 threading.Thread 跑
sync_playwright()，在 Windows 上子线程的 asyncio loop 创建子进程会直接抛
NotImplementedError（浏览器永远起不来）。这里改为在事件循环内创建 asyncio
任务 + async_playwright()，彻底规避子进程限制。
"""
import asyncio
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from app.utils.cookie_manager import COOKIE_SITES, set_cookie

_login_status: dict[str, dict] = {}

# 兼容旧端点（/cookie-login/{site}），导出站点白名单
SUPPORTED_SITES = set(COOKIE_SITES.keys())

# 保持 asyncio 任务引用，避免被 GC 回收
_login_tasks: dict[str, asyncio.Task] = {}


def get_login_status(site: str) -> dict:
    """Get current login status"""
    return _login_status.get(site, {"status": "unknown"})


def start_login(site: str, callback: Optional[Callable] = None) -> dict:
    """Start a login browser in the running event loop (or a fallback thread)."""
    if site not in COOKIE_SITES:
        return {"success": False, "error": f"不支持的站点: {site}"}

    site_config = COOKIE_SITES[site]
    _login_status[site] = {"status": "starting", "message": "正在启动浏览器..."}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 非事件循环上下文（罕见，如外部脚本）：起线程 + asyncio.run
        thread = threading.Thread(
            target=_run_in_thread,
            args=(site, site_config, callback),
            daemon=True,
        )
        thread.start()
    else:
        # 事件循环上下文（FastAPI 端点）：直接创建 asyncio 任务
        task = loop.create_task(_do_login(site, site_config, callback))
        _login_tasks[site] = task
        # 任务结束后清理引用
        task.add_done_callback(lambda _t, _s=site: _login_tasks.pop(_s, None))

    return {"success": True, "message": "浏览器启动中..."}


def _run_in_thread(site: str, site_config: dict, callback: Optional[Callable] = None):
    """Fallback: run the async login flow in a fresh thread."""
    try:
        asyncio.run(_do_login(site, site_config, callback))
    except Exception as e:  # noqa: BLE001
        logger.error(f"Cookie 登录助手线程失败 {site}: {e}")


async def _do_login(site: str, site_config: dict, callback: Optional[Callable] = None):
    """Run the login flow as an asyncio task (async Playwright)."""
    try:
        from playwright.async_api import async_playwright

        _login_status[site] = {"status": "opening", "message": "正在打开浏览器..."}

        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()

        async with async_playwright() as p:
            launch_args = {
                "headless": False,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if proxy_url:
                launch_args["proxy"] = {"server": proxy_url}
                _login_status[site] = {
                    "status": "opening",
                    "message": f"浏览器代理: {proxy_url}",
                }
                logger.info(f"Cookie 登录浏览器使用代理: {proxy_url}")
            else:
                logger.warning("Cookie 登录浏览器未使用代理（可能 IP 不匹配）")

            browser = await p.chromium.launch(**launch_args)
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                )
                page = await context.new_page()

                _login_status[site] = {
                    "status": "waiting",
                    "message": f"请在浏览器中登录 {site_config['name']}",
                }

                await page.goto(site_config["login_url"], timeout=60000)

                # CF 挑战等待（最多等 30 秒让 5 秒盾过完）
                for i in range(30):
                    try:
                        content = await page.content()
                        low = content.lower()
                        if "just a moment" in low or "attention required" in low:
                            _login_status[site] = {
                                "status": "waiting",
                                "message": f"等待 Cloudflare 挑战通过... ({i+1}s)",
                            }
                            await page.wait_for_timeout(1000)
                        else:
                            break
                    except Exception:
                        break

                _login_status[site] = {
                    "status": "waiting",
                    "message": f"请在浏览器中登录 {site_config['name']}",
                }

                # 等待用户登录（10 分钟超时）
                max_wait = 600
                logged_in = False
                for _ in range(max_wait):
                    try:
                        await page.wait_for_timeout(1000)

                        if site == "pan115":
                            try:
                                cookies = await context.cookies()
                                logged_in = any(
                                    c.get("name", "").upper() == "UID" for c in cookies
                                )
                            except Exception:
                                logged_in = False
                        else:
                            content = await page.content()
                            low = content.lower()
                            indicator = site_config.get("success_indicator")
                            # javdb/fc2 等站点英文界面显示 "Logout"，中文界面显示 "登出"；
                            # 同时检测 URL 已离开登录页，避免 indicator 漏判。
                            if indicator and indicator.lower() in low:
                                logged_in = True
                            elif "/login" in page.url.lower():
                                logged_in = False
                            elif "登出" in low or "log out" in low or "logout" in low:
                                logged_in = True
                            else:
                                logged_in = False

                        if logged_in:
                            _login_status[site] = {
                                "status": "saving",
                                "message": "检测到登录成功，正在保存 Cookie...",
                            }
                            break
                    except Exception:
                        break

                # 提取 Cookie
                try:
                    cookies = await context.cookies()
                    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                    if cookie_str and logged_in:
                        # 统一用 cookie_manager 写入
                        set_cookie(site, cookie_str)

                        # pan115 特殊处理：重置登录态
                        if site == "pan115":
                            try:
                                from app.services.pan_115 import pan_115_client
                                pan_115_client._logged_in = False
                                pan_115_client._client = None
                                pan_115_client._need_relogin = False
                            except Exception:
                                pass

                        _login_status[site] = {
                            "status": "completed",
                            "message": f"Cookie 已保存 ({len(cookies)} 个)",
                            "cookies_count": len(cookies),
                        }
                        logger.info(f"{site_config['name']} Cookie 保存成功: {len(cookies)} 个")
                    elif cookie_str and not logged_in:
                        # 超时但浏览器没关，尝试保存（用户可能手动关了）
                        set_cookie(site, cookie_str)
                        _login_status[site] = {
                            "status": "completed",
                            "message": f"超时但已保存当前 Cookie ({len(cookies)} 个)，请验证是否有效",
                            "cookies_count": len(cookies),
                        }
                        logger.info(f"{site_config['name']} 超时保存 Cookie: {len(cookies)} 个")
                    else:
                        _login_status[site] = {
                            "status": "failed",
                            "message": "未获取到 Cookie，请确保已成功登录",
                        }
                except Exception as e:
                    _login_status[site] = {
                        "status": "failed",
                        "message": f"Cookie 提取失败: {e}",
                    }

            finally:
                await browser.close()

    except ImportError:
        _login_status[site] = {
            "status": "failed",
            "message": "Playwright 未安装，请运行: pip install playwright && playwright install chromium",
        }
    except Exception as e:
        _login_status[site] = {
            "status": "failed",
            "message": f"登录失败: {type(e).__name__}: {e}",
        }
        logger.error(f"Cookie 登录助手失败: {e}", exc_info=True)

    if callback:
        try:
            callback(site, _login_status.get(site, {}))
        except Exception:  # noqa: BLE001
            pass
