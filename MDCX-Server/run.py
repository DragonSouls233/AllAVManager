"""
MDCX 服务端启动入口 - 桌面托盘模式

启动后自动进入系统托盘（右下角），日志显示在控制台窗口。
控制台窗口可随时隐藏/显示，服务在后台持续运行。
"""
# =============================================================================
# 控制台配色（ANSI）
# =============================================================================
import argparse
import os
import platform
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GREY = "\033[90m"


def _init_ansi():
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            for attr in dir(Style):
                if not attr.startswith("_"):
                    setattr(Style, attr, "")


_init_ansi()


_console_visible = True
_server_process: subprocess.Popen = None
_tray_thread: threading.Thread = None


# =============================================================================
# 控制台窗口管理（Windows）
# =============================================================================
def _get_console_hwnd():
    """获取控制台窗口句柄"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.kernel32.GetConsoleWindow()
    except Exception:
        pass
    return None


def toggle_console():
    """切换控制台窗口显示/隐藏"""
    global _console_visible
    hwnd = _get_console_hwnd()
    if not hwnd:
        return
    try:
        import ctypes
        if _console_visible:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            _console_visible = False
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            _console_visible = True
    except Exception:
        pass


# =============================================================================
# 启动前端口清理（Windows）
# =============================================================================
_CLEAN_PORTS = [8420, 18920, 18921]


def _kill_process_on_port(port: int) -> bool:
    """杀掉占用指定端口的进程"""
    if platform.system() != "Windows":
        return False
    try:
        result = subprocess.run(
            f'netstat -ano | findstr ":{port} "',
            shell=True, capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 5 and "LISTENING" in line:
                pid = parts[-1]
                try:
                    proc = subprocess.run(
                        f"taskkill /F /PID {pid}",
                        shell=True, capture_output=True, text=True, timeout=5
                    )
                    if proc.returncode == 0:
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def _cleanup_before_start(server_port: int):
    """启动前清理：杀掉残留进程"""
    ports_to_check = list(set([server_port] + _CLEAN_PORTS))

    # 杀掉占用关键端口的进程
    killed_any = False
    for port in ports_to_check:
        if _kill_process_on_port(port):
            _warn(f"已清理端口 {port} 上的残留进程")
            killed_any = True

    # 杀掉残留的 xray 子进程
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                'tasklist /NH /FI "IMAGENAME eq xray.exe" 2>nul',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if "xray.exe" in result.stdout:
                subprocess.run("taskkill /F /IM xray.exe", shell=True,
                               capture_output=True, timeout=5)
                _warn("已清理残留 xray 代理进程")
                killed_any = True
        except Exception:
            pass

    # 清理 PID 和锁文件
    for lock_file in ["data/proxy/xray_config.json", "data/proxy/nodes.json"]:
        lock_path = Path(lock_file)
        if lock_path.exists():
            try:
                lock_path.unlink()
            except Exception:
                pass

    if killed_any:
        time.sleep(1)  # 等端口彻底释放
        _ok("端口和进程清理完成")


# =============================================================================
# 横幅与日志
# =============================================================================
BANNER = f"""{Style.CYAN}{Style.BOLD}
   __  __  ____   ______  __  __
  |  \\/  |/ __ \\ / ____/ |  \\/  |
  | \\  / | |  | | |     | \\  / |
  | |\\/| | |  | | |     | |\\/| |
  | |  | | |__| | |____ | |  | |
  |_|  |_|\\____/ \\_____||_|  |_|
  {Style.GREEN}龙魂视频管理系统 - Server{Style.RESET}
"""


def _p(label, msg, color=Style.WHITE):
    print(f"  {Style.BOLD}{color}▸{Style.RESET} {Style.DIM}{label}:{Style.RESET} {color}{msg}{Style.RESET}")


def _info(msg):
    print(f"  {Style.BOLD}{Style.BLUE}ℹ{Style.RESET} {msg}{Style.RESET}")


def _ok(msg):
    print(f"  {Style.BOLD}{Style.GREEN}✔{Style.RESET} {Style.GREEN}{msg}{Style.RESET}")


def _warn(msg):
    print(f"  {Style.BOLD}{Style.YELLOW}⚠{Style.RESET} {Style.YELLOW}{msg}{Style.RESET}")


def _err(msg):
    print(f"  {Style.BOLD}{Style.RED}✘{Style.RESET} {Style.RED}{msg}{Style.RESET}")


# =============================================================================
# 参数解析
# =============================================================================
def _parse_args():
    p = argparse.ArgumentParser(
        description="MDCX 服务端启动器（桌面托盘模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python run.py                    # 默认启动（带系统托盘）
  python run.py --port 8420        # 指定端口
  python run.py --no-browser       # 不打开浏览器
  python run.py --no-tray          # 纯控制台模式（不启动托盘）
  python run.py --debug            # 调试模式（热重载）
        """
    )
    p.add_argument("--host", default=None, help="监听地址")
    p.add_argument("--port", type=int, default=None, help="监听端口")
    p.add_argument("--workers", type=int, default=None, help="Worker 进程数")
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p.add_argument("--no-tray", action="store_true", help="纯控制台模式（无系统托盘）")
    p.add_argument("--no-cleanup", action="store_true", help="跳过启动前端口清理")
    p.add_argument("--debug", action="store_true", help="Debug 模式（自动重载）")
    return p.parse_args()


def _load_config():
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from app.config.models import get_config
        return get_config()
    except Exception as e:
        _warn(f"配置加载失败: {e}")
        return None


def _get_local_ips():
    import socket
    ips = ["127.0.0.1"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except Exception:
        pass
    return list(dict.fromkeys(ips))


# =============================================================================
# 服务进程管理
# =============================================================================
def _start_server(host, port, workers, debug):
    """启动服务器（使用 uvicorn.run 内嵌启动，中文日志）"""
    import uvicorn
    from app.utils.log_config import LOGGING_CONFIG, UvicornLogFilter

    # 设置第三方库日志级别（降低噪音）
    import logging
    for noisy in ("apscheduler", "httpx", "httpcore", "urllib3", "PIL", "pystray"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # 为 uvicorn 添加中文翻译过滤器
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).addFilter(UvicornLogFilter())

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        workers=workers,
        reload=debug,
        log_config=LOGGING_CONFIG,
    )


def _start_server_subprocess(host, port, workers, debug):
    """启动服务器子进程（可独立管理生命周期）"""
    global _server_process
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", str(host),
        "--port", str(port),
        "--workers", str(workers),
        "--log-level", "info",
    ]
    if debug:
        cmd.append("--reload")
    _server_process = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent),
        stdout=None,
        stderr=None,
    )
    return _server_process


def _restart_server():
    """重启服务器进程"""
    global _server_process
    _warn("正在重启服务...")
    if _server_process:
        try:
            _server_process.terminate()
            _server_process.wait(timeout=10)
        except Exception:
            pass
    time.sleep(1)
    cfg = _load_config()
    args = _parse_args()
    host = args.host or "0.0.0.0"
    port = args.port or 8420
    workers = args.workers or 1
    _start_server_subprocess(host, port, workers, args.debug)
    _ok("服务已重启")


# =============================================================================
# 主入口
# =============================================================================
def main():
    global _tray_thread, _server_process

    args = _parse_args()

    # 加载配置（提前加载，用于清理）
    cfg = _load_config()
    host = args.host or (cfg.server.host if cfg else "0.0.0.0")
    port = args.port or (cfg.server.port if cfg else 8420)
    workers = args.workers or (cfg.server.workers if cfg else 1)

    # ===== 启动前端口清理 =====
    if not args.no_cleanup:
        # 先显示标题用于清理日志
        os.system("cls" if platform.system() == "Windows" else "clear")
        print(BANNER)
        print(f"  {Style.DIM}{Style.BOLD}启动前端口清理...{Style.RESET}")
        _cleanup_before_start(port)
        print()
    else:
        os.system("cls" if platform.system() == "Windows" else "clear")
        print(BANNER)

    print(f"  {Style.DIM}{'─' * 54}{Style.RESET}")

    # ===== 显示信息 =====
    _p("服务地址", f"http://127.0.0.1:{port}", Style.CYAN)
    for ip in _get_local_ips():
        if ip != "127.0.0.1":
            _p("局域网地址", f"http://{ip}:{port}", Style.CYAN)
    _p("工作进程", f"{workers} 个", Style.WHITE)
    _p("Debug 模式", "开" if args.debug else "关", Style.WHITE)
    _p("系统托盘", "开" if not args.no_tray else "关", Style.WHITE)
    _p("自动打开浏览器", "否" if args.no_browser else "是", Style.WHITE)

    # ===== 启动系统托盘 =====
    if not args.no_tray:
        try:
            from app.utils.tray import start_tray
            _tray_thread = start_tray(
                port=port,
                host=host,
                on_quit=lambda: os._exit(0),
                on_restart=_restart_server,
                on_toggle_console=toggle_console,
            )
            _ok("系统托盘已启动（右下角图标）")
        except Exception as e:
            _warn(f"系统托盘启动失败（不影响服务运行）: {e}")
    else:
        _info("纯控制台模式，未启动系统托盘")

    # ===== 自动打开浏览器 =====
    if not args.no_browser:
        def _open_browser_later():
            time.sleep(2.5)
            try:
                webbrowser.open(f"http://127.0.0.1:{port}")
                _ok(f"已打开浏览器 http://127.0.0.1:{port}")
            except Exception as e:
                _warn(f"自动打开浏览器失败: {e}")
        threading.Thread(target=_open_browser_later, daemon=True).start()

    print(f"  {Style.DIM}{'─' * 54}{Style.RESET}")
    print(f"  {Style.GREEN}{Style.BOLD}服务启动中... 日志如下：{Style.RESET}")
    print(f"  {Style.DIM}按 Ctrl+C 停止服务 | 系统托盘图标管理窗口可见性{Style.RESET}\n")

    # ===== 启动服务（直接内嵌） =====
    try:
        _start_server(host, port, workers, args.debug)
    except KeyboardInterrupt:
        print(f"\n  {Style.YELLOW}服务已通过键盘中断关闭{Style.RESET}")
    except Exception as e:
        _err(f"服务异常退出: {e}")
    finally:
        _info("服务进程已结束")


if __name__ == "__main__":
    main()
