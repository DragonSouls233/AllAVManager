# -*- coding: utf-8 -*-
"""日本出口代理服务（FANZA 等日区限定站点用）。

为什么需要
----------
FANZA / DMM 对**海外 IP 地区封锁**，实测本机现有代理（10808）出口是
`23.94.112.121 / US` ⇒ 拿到的是海外版页面，拿不到 FANZA 完整数据。
必须有一条**日本出口**的链路才能刮削。

链式是必需的（2026-10-05 实测）
-------------------------------
这批免费日本节点服务器在境外（AWS 8x/3x/5x 段），本机**直连它们的 TCP 443
全部 TimeoutError** ⇒ xray 直连模式下 100% 不通，极易误判成「节点全挂了」。
必须让节点 outbound 经 `proxySettings` 走前置 socks（项目现有 10808 / 内置 xray）
出去才连得上。实测 24 个节点：直连 0 存活，链式 21 存活（16 个去重日本 IP，
FANZA 全部 200）。

配置格式
--------
`data/proxy/jp_nodes.json`::

    {"nodes": ["trojan://...", "vless://..."], "updated_at": "..."}

由 `scripts/_import_jp_nodes.py` 从免费订阅导入（已实测可用的会被筛进来）。

用法
----
::

    from app.services.jp_proxy import get_jp_proxy_url
    proxy = get_jp_proxy_url()      # None 表示不可用，调用方回退原代理
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: 需要日本出口的域名后缀（按需扩充）
JP_DOMAINS = (
    "dmm.co.jp",
    "fanza.co.jp",
    "fanza.com",
    "doujin.com",
    "mgstage.com",
    "fc2-content.com",
    "seesaawiki.jp",   # 素人女优 wiki（部分内容按地区限制）
)

#: 日本节点监听端口段（与内置 xray 的 18920/18921 刻意错开）。
#: 18930 起每个节点一个 socks 端口（最多 MAX_JP_NODES 个），
#: http 端口放在**段尾之后**，绝不能是 18931 —— 那是第 2 个节点的 socks 端口，
#: 撞端口会让 xray 直接退出（实测 rc=-1，且 -test 也可能侥幸通过）。
JP_SOCKS_PORT = int(os.environ.get("MDCX_JP_SOCKS_PORT", "18930"))
MAX_JP_NODES = 4
JP_HTTP_PORT = JP_SOCKS_PORT + MAX_JP_NODES + 1


def _data_dir() -> Path:
    root = os.environ.get("MDCX_DATA_DIR")
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[2] / "data"


def _nodes_file() -> Path:
    return _data_dir() / "proxy" / "jp_nodes.json"


def load_jp_nodes() -> list:
    """读取已验证可用的日本节点列表。"""
    p = _nodes_file()
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("读取日本节点配置失败 %s: %s", p, e)
        return []
    return [str(x) for x in (d.get("nodes") or []) if str(x).strip()]


def save_jp_nodes(nodes: list) -> Path:
    p = _nodes_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "nodes": nodes,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def needs_jp_proxy(url: str) -> bool:
    """该 URL 是否需要日本出口。"""
    u = (url or "").lower()
    return any(d in u for d in JP_DOMAINS)


class JPProxyService:
    """常驻链式 xray，对外提供日本出口 socks5/http。

    单例用法：`get_jp_proxy_service()`。
    """

    _inst: Optional["JPProxyService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._front: Optional[str] = None
        self._started_at: float = 0.0
        self._last_err: str = ""
        self._node_count: int = 0
        self._rr: int = 0
        self._rr_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "JPProxyService":
        if cls._inst is None:
            with cls._lock:
                if cls._inst is None:
                    cls._inst = cls()
        return cls._inst

    # ---------- 状态 ----------
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def proxy_for(self) -> str:
        """轮转取一个日本节点对应的 socks URL（实现简易故障转移）。"""
        n = max(1, self._node_count)
        with self._rr_lock:
            self._rr = (self._rr + 1) % n
            idx = self._rr
        return "socks5://127.0.0.1:%d" % (JP_SOCKS_PORT + idx)

    def socks_url(self) -> str:
        return self.proxy_for()

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "socks_port": JP_SOCKS_PORT,
            "http_port": JP_HTTP_PORT,
            "front": self._front,
            "uptime": round(time.time() - self._started_at, 1) if self._started_at else 0,
            "last_error": self._last_err,
            "nodes": len(load_jp_nodes()),
            "active_nodes": self._node_count,
        }

    # ---------- 生命周期 ----------
    def build_config(self, node_urls: list, front_socks: str,
                     max_nodes: int = 4) -> dict:
        """生成链式配置：**每个日本节点一个独立 inbound 端口**。

        🔴 不用 xray 的 `balancers`（实测多节点 + balancerTag 组合下请求直接
        ConnectError，单节点 inbound 一切正常）⇒ 改为「一个节点一个端口」，
        由 :meth:`proxy_for` 按轮转挑端口。同一时刻只有被选中的那个节点在用，
        但所有节点都已实测可用，轮转天然实现故障转移。
        """
        from app.services.proxy_parser import parse_node_url

        outs = []
        for i, u in enumerate(node_urls[:max_nodes]):
            try:
                node = parse_node_url(u)
            except Exception as e:  # noqa: BLE001
                logger.debug("跳过无法解析的日本节点: %s", e)
                continue
            ob = dict(node.outbound)
            ob["tag"] = "jp-%d" % len(outs)
            ob["proxySettings"] = {"tag": "front"}
            outs.append(ob)
        if not outs:
            raise ValueError("没有可用的日本节点")

        host, _, p = front_socks.rpartition(":")
        front_port = int(p) if p.isdigit() else 10808
        inbounds = [{
            "tag": "jp-in-%d" % i, "port": JP_SOCKS_PORT + i, "listen": "127.0.0.1",
            "protocol": "socks", "settings": {"auth": "noauth", "udp": True},
        } for i in range(len(outs))]
        inbounds.append({
            "tag": "jp-http", "port": JP_HTTP_PORT, "listen": "127.0.0.1",
            "protocol": "http", "settings": {},
        })
        return {
            "log": {"loglevel": "warning"},
            "inbounds": inbounds,
            "outbounds": [
                *outs,
                {"tag": "front", "protocol": "socks",
                 "settings": {"servers": [{"address": host or "127.0.0.1",
                                           "port": front_port}]}},
                {"tag": "direct", "protocol": "freedom"},
                {"tag": "block", "protocol": "blackhole"},
            ],
            "routing": {"rules": [
                {"type": "field", "inboundTag": [ib["tag"]],
                 "outboundTag": outs[i]["tag"]}
                for i, ib in enumerate(inbounds[:len(outs)])
            ]},
        }

    def start(self, front_socks: Optional[str] = None) -> bool:
        if self.is_running():
            return True
        nodes = load_jp_nodes()
        if not nodes:
            self._last_err = "未配置日本节点（data/proxy/jp_nodes.json 为空）"
            logger.warning(self._last_err)
            return False
        if not front_socks:
            from app.services.proxy_manager import get_effective_proxy_url
            front_socks = get_effective_proxy_url() or "127.0.0.1:10808"
        try:
            cfg = self.build_config(nodes, front_socks)
        except Exception as e:  # noqa: BLE001
            self._last_err = "配置生成失败: %s" % e
            logger.warning(self._last_err)
            return False

        from app.services.proxy_manager import XRAY_BIN
        import tempfile

        tmp = Path(tempfile.gettempdir()) / "mdcx_jp_proxy.json"
        tmp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        try:
            self._proc = subprocess.Popen(
                [str(XRAY_BIN), "run", "-c", str(tmp)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        except Exception as e:  # noqa: BLE001
            self._last_err = "xray 启动失败: %s" % e
            logger.warning(self._last_err)
            return False

        time.sleep(2.0)
        if not self.is_running():
            err = ""
            try:
                err = (self._proc.stderr.read() or b"").decode("utf-8", "replace")[:300]
            except Exception:
                pass
            self._last_err = "xray 退出: %s" % (err.strip() or "rc=%s" % self._proc.returncode)
            logger.warning(self._last_err)
            return False
        self._front = front_socks
        self._node_count = sum(
            1 for ob in cfg.get("outbounds", [])
            if str(ob.get("tag", "")).startswith("jp-"))
        self._started_at = time.time()
        self._last_err = ""
        logger.info("日本出口代理已启动 端口 %d-%d (前置 %s, 节点池 %d, 启用 %d)",
                    JP_SOCKS_PORT, JP_SOCKS_PORT + max(0, self._node_count - 1),
                    front_socks, len(nodes), self._node_count)
        return True

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        self._started_at = 0.0
        self._node_count = 0


def get_jp_proxy_service() -> JPProxyService:
    return JPProxyService.instance()


def get_jp_proxy_url(auto_start: bool = True) -> Optional[str]:
    """取日本出口代理 URL；不可用时返回 None（调用方回退原代理）。"""
    svc = get_jp_proxy_service()
    if not svc.is_running():
        if not auto_start:
            return None
        if not svc.start():
            return None
    return svc.socks_url()
