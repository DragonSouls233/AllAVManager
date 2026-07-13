"""
Xray 子进程代理管理器

职责:
- 启动/停止/重启 xray.exe 子进程
- 维护节点池 (内存 + data/proxy/nodes.json)
- 生成 xray 配置文件
- 健康检查 (进程存活/socks 端口可连)
- 对外提供当前 socks5 URL 给 http_client 使用

线程模型:
- 单例 _manager; FastAPI lifespan startup 调 start(); shutdown 调 stop()
- 后台 asyncio task 做健康检查 (5s 间隔)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.services.proxy_parser import NodeConfig, parse_node_url, parse_subscription_content
from app.services.xray_config import build_xray_config

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
XRAY_DIR = PROJECT_ROOT / "bin" / "xray"
XRAY_BIN = XRAY_DIR / ("xray.exe" if sys.platform == "win32" else "xray")

# 专用端口：刻意避开 10808/10809 等常见代理冲突区（v2rayN/clash 等常用），
# 大幅降低与其他客户端撞车导致 xray 双 inbound 同端口退出的概率。
XRAY_SOCKS_PORT = 18920
XRAY_HTTP_PORT = 18921


def _data_dir() -> Path:
    env = os.getenv("MDCX_DATA_DIR") or os.getenv("SCRAPER_DATA_DIR")
    if env:
        p = Path(env)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return PROJECT_ROOT / "data"


PROXY_DATA_DIR = _data_dir() / "proxy"
NODES_FILE = PROXY_DATA_DIR / "nodes.json"
CONFIG_FILE = PROXY_DATA_DIR / "xray_config.json"


@dataclass
class ProxyState:
    running: bool = False
    pid: int | None = None
    socks_port: int = XRAY_SOCKS_PORT
    http_port: int = XRAY_HTTP_PORT
    current_node_id: str | None = None
    mode: str = "domain"
    subscription_url: str | None = None
    last_error: str | None = None
    nodes_count: int = 0


def _pick_free_port(start: int, exclude: set[int] | None = None, tries: int = 40) -> int:
    exclude = exclude or set()
    for p in range(start, start + tries):
        if p in exclude:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"no free port near {start} (exclude={exclude})")


class ProxyManager:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._nodes: dict[str, NodeConfig] = {}
        self._state = ProxyState()
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task | None = None
        self._log_thread: threading.Thread | None = None

    # ============ 持久化 ============
    def _ensure_dirs(self) -> None:
        PROXY_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def load_nodes(self) -> None:
        self._ensure_dirs()
        if not NODES_FILE.exists():
            return
        try:
            data = json.loads(NODES_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("load nodes.json failed: %s", e)
            return

        self._state.subscription_url = data.get("subscription_url")
        self._state.mode = data.get("mode", "domain")
        self._state.current_node_id = data.get("current_node_id")
        for item in data.get("nodes", []):
            # 从 raw_url 重建 outbound
            raw = item.get("raw_url", "")
            try:
                node = parse_node_url(raw)
                node.id = item.get("id", node.id)
                node.name = item.get("name", node.name)
                node.latency_ms = item.get("latency_ms")
                node.country = item.get("country")
            except Exception as e:
                logger.warning("rebuild node from raw_url failed: %s", e)
                continue
            self._nodes[node.id] = node
        self._state.nodes_count = len(self._nodes)
        logger.info("proxy manager loaded %d nodes", len(self._nodes))

    def save_nodes(self) -> None:
        self._ensure_dirs()
        data = {
            "subscription_url": self._state.subscription_url,
            "mode": self._state.mode,
            "current_node_id": self._state.current_node_id,
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "protocol": n.protocol,
                    "address": n.address,
                    "port": n.port,
                    "raw_url": n.raw_url,
                    "latency_ms": n.latency_ms,
                    "country": n.country,
                }
                for n in self._nodes.values()
            ],
        }
        NODES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ============ 节点管理 ============
    def list_nodes(self) -> list[NodeConfig]:
        return list(self._nodes.values())

    def add_node(self, url: str) -> NodeConfig:
        node = parse_node_url(url)
        self._nodes[node.id] = node
        self._state.nodes_count = len(self._nodes)
        self.save_nodes()
        return node

    def remove_node(self, node_id: str) -> bool:
        if node_id in self._nodes:
            del self._nodes[node_id]
            if self._state.current_node_id == node_id:
                self._state.current_node_id = None
            self._state.nodes_count = len(self._nodes)
            self.save_nodes()
            return True
        return False

    def replace_all_nodes(self, nodes: list[NodeConfig]) -> None:
        self._nodes = {n.id: n for n in nodes}
        self._state.nodes_count = len(self._nodes)
        # 若原选中节点已消失，清空
        if self._state.current_node_id not in self._nodes:
            self._state.current_node_id = None
        self.save_nodes()

    def set_subscription(self, url: str | None) -> None:
        self._state.subscription_url = url
        self.save_nodes()

    def set_mode(self, mode: str) -> None:
        if mode not in {"domain", "global", "direct"}:
            raise ValueError(f"invalid mode: {mode}")
        self._state.mode = mode
        self.save_nodes()

    def select_node(self, node_id: str | None) -> bool:
        """
        手动选择当前走代理的节点。
        - node_id=None 或 "auto"：取消选择，走全部节点 leastPing 负载均衡。
        - 否则锁定到指定节点（该节点必须存在于节点池）。
        返回是否成功。
        """
        if node_id in (None, "auto", ""):
            self._state.current_node_id = None
        else:
            if node_id not in self._nodes:
                return False
            self._state.current_node_id = node_id
        self.save_nodes()
        return True

    # ============ Xray 进程 ============
    def _xray_available(self) -> bool:
        return XRAY_BIN.exists()

    def _build_config(self) -> dict[str, Any]:
        # 端口未占用则用专用默认，否则递增；socks/http 必须互不相同。
        # 专用端口基数刻意相距较远（18920/18921），即便其中一个被占用，
        # exclude + 兜底也能保证两个 inbound 不会落到同一端口。
        socks_port = _pick_free_port(self._state.socks_port or XRAY_SOCKS_PORT)
        http_port = _pick_free_port(
            self._state.http_port or XRAY_HTTP_PORT, exclude={socks_port}
        )
        # 兜底：极端情况下 http 仍与 socks 撞车，强制错开一个空闲端口
        if http_port == socks_port:
            http_port = _pick_free_port(socks_port + 1, exclude={socks_port})
        self._state.socks_port = socks_port
        self._state.http_port = http_port
        return build_xray_config(
            list(self._nodes.values()),
            socks_port=socks_port,
            http_port=http_port,
            mode=self._state.mode,
            preferred_node_id=self._state.current_node_id,
        )

    async def start(self) -> None:
        async with self._lock:
            if self._proc and self._proc.poll() is None:
                logger.info("xray already running, pid=%s", self._proc.pid)
                return
            if not self._xray_available():
                self._state.last_error = f"xray binary not found at {XRAY_BIN}"
                logger.warning(self._state.last_error)
                return
            if not self._nodes:
                self._state.last_error = "no proxy nodes configured, skip starting xray"
                logger.info(self._state.last_error)
                return

            self._ensure_dirs()
            config = self._build_config()
            CONFIG_FILE.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

            # 用日志文件作为 xray 的 stdout 目标。
            # 坑：PIPE + 后台 drain 线程在 Windows asyncio (ProactorEventLoop) 下
            # 偶发 PIPE 句柄注册到 IOCP 后在线程间传递时状态异常，导致 xray 子进程
            # 写入时 pipe broken → 立即退出 (exit_code=1) → "xray exited early"。
            # 改用直接文件句柄可靠得多 —— 子进程直接写文件，无 PIPE+线程竞态。
            XRAY_LOG = PROXY_DATA_DIR / "xray.log"
            try:
                # 清空旧日志
                XRAY_LOG.write_bytes(b"")
                log_fh = open(XRAY_LOG, "ab", buffering=0)
                self._proc = subprocess.Popen(
                    [str(XRAY_BIN), "-c", str(CONFIG_FILE)],
                    cwd=str(XRAY_DIR),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                # 不要让 Python GC 关闭传给子进程的文件句柄 —— 用单独引用保持存活
                self._log_fh = log_fh
            except Exception as e:
                self._state.last_error = f"start xray failed: {e}"
                logger.exception(self._state.last_error)
                return

            # 给 xray 一点启动时间
            await asyncio.sleep(2.0)
            if self._proc and self._proc.poll() is not None:
                err = ""
                try:
                    if XRAY_LOG.exists():
                        raw = XRAY_LOG.read_text(encoding="utf-8", errors="replace")
                        err = "\n".join(raw.strip().splitlines()[-15:])[-800:]
                except Exception:
                    err = "<log read failed>"
                self._state.last_error = f"xray exited early: {err}" if err else "xray exited early (no log output)"
                logger.error(self._state.last_error)
                self._proc = None
                return

            self._state.running = True
            self._state.pid = self._proc.pid
            self._state.last_error = None
            logger.info(
                "xray started pid=%s socks=127.0.0.1:%s http=127.0.0.1:%s",
                self._proc.pid, self._state.socks_port, self._state.http_port,
            )

            # 启动健康检查
            if not self._health_task or self._health_task.done():
                self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        async with self._lock:
            if self._health_task and not self._health_task.done():
                self._health_task.cancel()
            self._health_task = None
            if self._proc and self._proc.poll() is None:
                logger.info("stopping xray pid=%s", self._proc.pid)
                try:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                        self._proc.wait(timeout=2)
                except Exception as e:
                    logger.error("stop xray error: %s", e)
            self._proc = None
            # 关闭日志文件句柄
            try:
                if hasattr(self, '_log_fh') and self._log_fh and not self._log_fh.closed:
                    self._log_fh.close()
            except Exception:
                pass
            self._state.running = False
            self._state.pid = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _health_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                if self._proc is None:
                    self._state.running = False
                    return
                if self._proc.poll() is not None:
                    self._state.running = False
                    self._state.last_error = f"xray died unexpectedly, exit_code={self._proc.returncode}"
                    logger.warning(self._state.last_error)
                    self._proc = None
                    return
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.exception("health loop error: %s", e)

    # ============ 对外查询 ============
    def get_current_socks5_url(self) -> str | None:
        """给 http_client 用：优先使用内嵌代理。"""
        if self._state.running:
            return f"socks5://127.0.0.1:{self._state.socks_port}"
        return None

    def get_state(self) -> dict[str, Any]:
        return asdict(self._state)


# ============ 单例 ============
_manager: ProxyManager | None = None


def get_proxy_manager() -> ProxyManager:
    global _manager
    if _manager is None:
        _manager = ProxyManager()
        _manager.load_nodes()
    return _manager


def get_effective_proxy_url() -> str | None:
    """返回当前生效的代理 URL —— 全项目统一的代理端口唯一来源。

    优先级：
      1. 内置 xray 正在运行 → 返回其真实 socks5 地址
         （端口由 ProxyManager 动态探测，约 18920，不再是写死的 10808）
      2. 否则回退到旧版 config.proxy（用户在 config.yaml 手填的 http/socks5/address:port）
      3. 都没有 → None（直连）

    历史坑：cookiecloud / javdb / face_crop / 各路由此前只用 config.proxy.proxy_url，
    一旦用户改用内置 xray（端口 18920/18921）而旧版 10808 代理停掉，就会硬失败。
    统一走本函数即可自动跟上“当前代理端口”。
    """
    # 1) 内置 xray 实际端口优先
    try:
        url = get_proxy_manager().get_current_socks5_url()
        if url:
            return url
    except Exception:
        logger.debug("get_current_socks5_url failed, fallback to config.proxy", exc_info=True)

    # 2) 回退旧版 config.proxy
    try:
        from app.config.manager import get_config
        cfg = get_config().proxy
        if cfg.enabled and cfg.proxy_url:
            return cfg.proxy_url
    except Exception:
        logger.debug("read config.proxy failed", exc_info=True)

    return None

