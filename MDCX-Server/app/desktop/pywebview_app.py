"""PyWebView 轻量桌面备选方案（无需 Electron）。

通过 PyWebView 将 MDCX 后端 Web 界面包装为原生桌面应用。
相比 Electron：
  - 打包体积 ~10MB vs 100MB+
  - 无需 Node.js 环境
  - 可直接访问 Python 函数（JS <-> Python 双向调用）

启动方式：
  python -m app.desktop.pywebview_app

参考：OpenAver (PyWebView + FastAPI 桌面方案)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class MDCXAPI:
    """PyWebView JS <-> Python 双向 API 桥。

    在桌面 JS 中通过 pywebview.api.search_movie(code) 直接调用。
    """

    @staticmethod
    def search_movie(code: str) -> str:
        """搜索影片（返回 JSON 字符串）。"""
        try:
            import asyncio
            async def _do():
                from app.services.javdb_api_client import create_client_from_config
                client = await create_client_from_config()
                try:
                    movie = await client.search_movie(code)
                    if movie:
                        return json.dumps({
                            "code": movie.code, "title": movie.title,
                            "title_cn": movie.title_cn, "date": movie.date,
                            "duration": movie.duration, "actors": movie.actors,
                            "genres": movie.genres, "cover_url": movie.cover_url,
                        }, ensure_ascii=False)
                    return json.dumps({"error": f"未找到 {code}"})
                finally:
                    await client.close()
            return asyncio.run(_do())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @staticmethod
    def get_library_stats() -> str:
        """获取媒体库统计。"""
        try:
            import asyncio
            async def _do():
                from app.services.mcp_service import MCPService
                svc = MCPService()
                stats = await svc._resource_library_stats()
                return json.dumps(stats)
            return asyncio.run(_do())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @staticmethod
    def open_file(path: str) -> bool:
        """用系统默认程序打开文件。"""
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
            return True
        except Exception as e:
            logger.warning("open_file failed: %s", e)
            return False

    @staticmethod
    def select_folder() -> str:
        """调用系统文件夹选择器。"""
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title="选择媒体库目录")
        root.destroy()
        return folder or ""

    @staticmethod
    def get_platform() -> str:
        return sys.platform


def _run_server():
    """在新线程中启动 FastAPI 服务器。"""
    import uvicorn
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="warning")


def run_desktop():
    """启动 PyWebView 桌面应用。

    启动一个线程运行 FastAPI，主线程运行 PyWebView 窗口。
    """
    try:
        import webview
    except ImportError:
        print("请安装 PyWebView: pip install pywebview")
        print("或者继续使用 Electron: npm run dev")
        sys.exit(1)

    # 启动后端线程
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # 等待服务器就绪
    import time
    time.sleep(2)

    api = MDCXAPI()
    window = webview.create_window(
        title="MDCX 龙魂视频管理",
        url="http://127.0.0.1:8420",
        js_api=api,
        width=1280,
        height=800,
        resizable=True,
        fullscreen=False,
        min_size=(960, 600),
        confirm_close=True,
        text_select=True,
    )
    webview.start(
        debug=os.getenv("MDCX_DEBUG", "").lower() in ("1", "true", "yes"),
        http_server=False,
    )


if __name__ == "__main__":
    run_desktop()
