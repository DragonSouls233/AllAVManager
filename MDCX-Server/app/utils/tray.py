"""
系统托盘模块 - 桌面系统托盘 + 控制台窗口管理
"""

import os
import sys
import threading
import webbrowser
from typing import Optional, Callable

import pystray
from PIL import Image, ImageDraw, ImageFont

from app.utils.logger import get_logger

logger = get_logger(__name__)

_tray_instance: Optional[pystray.Icon] = None
_on_quit: Optional[Callable] = None
_on_restart: Optional[Callable] = None
_on_toggle_console: Optional[Callable] = None


def _create_icon() -> Image.Image:
    """创建托盘图标（MDCX 风格）"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 深色背景圆形
    draw.ellipse([2, 2, size - 2, size - 2], fill=(30, 41, 59, 255))
    # 字母 "M" 图形
    draw.polygon([
        (12, 22), (20, 22), (32, 38), (44, 22), (52, 22),
        (52, 42), (46, 42), (46, 30), (32, 48), (18, 30),
        (18, 42), (12, 42)
    ], fill=(96, 165, 250, 255))
    return img


def _toggle_console():
    """显示/隐藏控制台窗口"""
    global _on_toggle_console
    if _on_toggle_console:
        _on_toggle_console()


def _open_browser(url: str):
    """在浏览器中打开"""
    try:
        webbrowser.open(url)
        logger.info(f"已打开浏览器: {url}")
    except Exception as e:
        logger.error(f"打开浏览器失败: {e}")


def _do_restart():
    """执行重启"""
    global _on_restart
    if _on_restart:
        _on_restart()


def _do_quit():
    """退出"""
    global _on_quit, _tray_instance
    if _on_quit:
        _on_quit()
    if _tray_instance:
        _tray_instance.stop()
    os._exit(0)


def run_tray(
    port: int = 8420,
    host: str = "0.0.0.0",
    on_quit: Callable = None,
    on_restart: Callable = None,
    on_toggle_console: Callable = None,
):
    """
    启动系统托盘

    Args:
        port: 服务端口
        host: 监听地址
        on_quit: 退出回调
        on_restart: 重启回调
        on_toggle_console: 切换控制台可见性回调
    """
    global _tray_instance, _on_quit, _on_restart, _on_toggle_console
    _on_quit = on_quit
    _on_restart = on_restart
    _on_toggle_console = on_toggle_console

    local_url = f"http://127.0.0.1:{port}"
    api_url = f"http://127.0.0.1:{port}/api/v1"

    icon = _create_icon()

    menu = pystray.Menu(
        pystray.MenuItem("📂 打开管理界面", lambda _: _open_browser(local_url)),
        pystray.MenuItem("📋 API 文档", lambda _: _open_browser(f"{api_url}/docs")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🪟 显示/隐藏控制台", lambda _: _toggle_console()),
        pystray.MenuItem("🔄 重启服务", lambda _: _do_restart()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ 退出", lambda _: _do_quit()),
    )

    _tray_instance = pystray.Icon(
        "mdcx-server",
        icon,
        "MDCX 服务端\n龙魂视频管理系统",
        menu,
    )

    logger.info("系统托盘已启动（右下角图标）")
    _tray_instance.run()


def start_tray(
    port: int = 8420,
    host: str = "0.0.0.0",
    on_quit: Callable = None,
    on_restart: Callable = None,
    on_toggle_console: Callable = None,
) -> threading.Thread:
    """
    在后台线程启动系统托盘

    Returns: 托盘线程
    """
    thread = threading.Thread(
        target=run_tray,
        args=(port, host, on_quit, on_restart, on_toggle_console),
        daemon=True,
    )
    thread.start()
    return thread
