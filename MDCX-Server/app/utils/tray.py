"""
系统托盘模块 - 支持 Windows 系统托盘运行
"""

import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 全局托盘实例
_tray_instance: Optional[pystray.Icon] = None
_server_process = None


def create_default_icon() -> Image.Image:
    """创建默认托盘图标"""
    width = 64
    height = 64
    image = Image.new("RGB", (width, height), color=(66, 133, 244))
    draw = ImageDraw.Draw(image)

    # 绘制一个简单的播放按钮图标
    center_x, center_y = width // 2, height // 2
    triangle_points = [
        (center_x - 15, center_y - 20),
        (center_x - 15, center_y + 20),
        (center_x + 20, center_y),
    ]
    draw.polygon(triangle_points, fill=(255, 255, 255))

    return image


def create_menu(backend_url: str, frontend_url: str) -> pystray.Menu:
    """创建托盘菜单"""
    return pystray.Menu(
        pystray.MenuItem(
            "打开前台",
            lambda _: open_url(frontend_url),
        ),
        pystray.MenuItem(
            "打开后台 API",
            lambda _: open_url(backend_url),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "启动/重启服务",
            lambda _: restart_services(),
        ),
        pystray.MenuItem(
            "停止服务",
            lambda _: stop_services(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "退出",
            lambda _: quit_app(),
        ),
    )


def open_url(url: str):
    """打开浏览器"""
    try:
        webbrowser.open(url)
        logger.info(f"已打开: {url}")
    except Exception as e:
        logger.error(f"打开浏览器失败: {e}")


def restart_services():
    """重启服务"""
    global _server_process
    stop_services()
    # 重新启动服务需要在外部处理
    logger.info("服务重启请求已发送")


def stop_services():
    """停止服务"""
    global _server_process
    if _server_process:
        try:
            _server_process.terminate()
            _server_process = None
            logger.info("服务已停止")
        except Exception as e:
            logger.error(f"停止服务失败: {e}")


def quit_app():
    """退出应用"""
    global _tray_instance
    stop_services()
    if _tray_instance:
        _tray_instance.stop()
    sys.exit(0)


def run_in_tray(backend_url: str = "http://localhost:8420", frontend_url: str = "http://localhost:8420"):
    """
    在系统托盘中运行应用

    Args:
        backend_url: 后端 API 地址
        frontend_url: 前端地址（Docker模式下与后端相同）
    """
    global _tray_instance

    # 如果是 Docker 模式，前端和后端使用相同地址
    icon = create_default_icon()
    menu = create_menu(backend_url, frontend_url)

    _tray_instance = pystray.Icon(
        "MDCX",
        icon,
        "MDCX 媒体库管理系统",
        menu,
    )

    logger.info("系统托盘已启动")
    _tray_instance.run()


def start_tray_background(backend_port: int = 8420, is_docker: bool = False):
    """
    在后台启动托盘

    Args:
        backend_port: 后端端口
        is_docker: 是否在 Docker 环境中运行
    """
    if is_docker:
        # Docker 模式下，前端通过后端静态文件服务
        frontend_url = f"http://localhost:{backend_port}"
    else:
        # 非 Docker 模式，前端运行在 3000 端口
        frontend_url = "http://localhost:3000"

    backend_url = f"http://localhost:{backend_port}"

    # 在新线程中运行托盘
    tray_thread = threading.Thread(
        target=run_in_tray,
        args=(backend_url, frontend_url),
        daemon=True,
    )
    tray_thread.start()

    return tray_thread


class TrayRunner:
    """托盘运行器 - 用于管理托盘生命周期"""

    def __init__(self, backend_port: int = 8420, is_docker: bool = False):
        self.backend_port = backend_port
        self.is_docker = is_docker
        self.tray_thread: Optional[threading.Thread] = None

    def start(self):
        """启动托盘"""
        if self.is_docker:
            frontend_url = f"http://localhost:{self.backend_port}"
        else:
            frontend_url = "http://localhost:3000"

        backend_url = f"http://localhost:{self.backend_port}"

        self.tray_thread = threading.Thread(
            target=run_in_tray,
            args=(backend_url, frontend_url),
            daemon=True,
        )
        self.tray_thread.start()
        logger.info("系统托盘已启动")

    def stop(self):
        """停止托盘"""
        global _tray_instance
        if _tray_instance:
            _tray_instance.stop()
            logger.info("系统托盘已停止")