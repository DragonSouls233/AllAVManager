"""刮削专用「多出口」代理池。

## 为什么需要（2026-10-14）

内置 xray 的配置是 **1 个 socks inbound → balancer(leastPing) → N 个节点**。
leastPing 的含义是：**所有流量都走当前延迟最低的那一个节点**。于是：

   节点池里躺着 3 条（实际去重后只有 2 个不同出口），
   但 100% 的刮削流量都从同一个出口 IP 出去

后果有两个：
  1. 并行度再高，出口带宽/连接数也只有一份；
  2. PH 的限流是**按出口 IP** 计的，等于拿一个 IP 硬扛全部请求。

本模块的做法：**每个不同出口各开一个 socks inbound，并用 routing 规则把
该 inbound 的流量固定绑到对应节点 outbound**。这样 N 个 worker 各绑一个
inbound，就是 N 条互不干扰的独立出口。

## 与生产实例的隔离

刻意**复用** bin/xray/xray.exe，但用独立配置文件与独立端口段（默认 18950+），
与生产 18920/18921 完全不冲突；进程也单独管理，随时可 stop 而不影响正常服务。

## 已知限制

- 同一订阅里重复的条目（同 address:port）会被去重，不会重复开入口。
- 池只在**批量刮削**场景启用；单发刮削仍走全局代理（行为不变）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from app.services.xray_config import resolve_proxy_rules

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
XRAY_DIR = PROJECT_ROOT / "bin" / "xray"
XRAY_BIN = XRAY_DIR / ("xray.exe" if sys.platform == "win32" else "xray")

#: 池专用端口段起点。刻意远离 18920/18921（生产 socks/http）与 18940/18945（诊断脚本）。
POOL_PORT_BASE = 18950


def _data_dir() -> Path:
    import os

    env = os.getenv("MDCX_DATA_DIR") or os.getenv("SCRAPER_DATA_DIR")
    if env:
        p = Path(env)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return PROJECT_ROOT / "data"


def _free_port(start: int, tries: int = 60, exclude: Optional[set[int]] = None) -> int:
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
    raise RuntimeError(f"no free port near {start}")


class ScrapeProxyPool:
    """管理一组「一出口一口」的本地 socks5 入口。"""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._log_fh = None
        self._ports: list[int] = []
        self._addrs: list[str] = []
        self._lock = asyncio.Lock()
        self._started_at: float = 0.0

    # ------------------------------------------------------------------
    # 节点读取（按真实出口去重）
    # ------------------------------------------------------------------
    def _load_distinct_nodes(self) -> list[dict[str, Any]]:
        from app.services.proxy_parser import parse_node_url

        nf = _data_dir() / "proxy" / "nodes.json"
        if not nf.exists():
            logger.info("代理池: nodes.json 不存在")
            return []
        try:
            data = json.loads(nf.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"代理池: 读 nodes.json 失败 {e}")
            return []

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for item in data.get("nodes", []):
            raw = item.get("raw_url", "")
            if not raw:
                continue
            try:
                n = parse_node_url(raw)
            except Exception as e:
                logger.debug(f"代理池: 跳过无法解析的节点 {item.get('name')}: {e}")
                continue
            key = f"{n.address}:{n.port}"
            if key in seen:
                logger.debug(f"代理池: 去重重复出口 {item.get('name')} -> {key}")
                continue
            seen.add(key)
            out.append({
                "name": item.get("name") or n.name,
                "addr": key,
                "outbound": n.outbound,
            })
        return out

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(self, max_size: int = 8, wait: float = 2.5) -> list[str]:
        async with self._lock:
            if self._proc and self._proc.poll() is None:
                await asyncio.sleep(0.5)
                self._wait_ports_up(timeout=5.0)
                return self.urls()

            if not XRAY_BIN.exists():
                logger.warning(f"代理池: xray 不存在 {XRAY_BIN}")
                return []

            nodes = self._load_distinct_nodes()
            if not nodes:
                logger.info("代理池: 无可用节点")
                return []

            nodes = nodes[:max_size]
            used: set[int] = set()
            ports: list[int] = []
            for i in range(len(nodes)):
                p = _free_port(POOL_PORT_BASE + i * 3, exclude=used)
                used.add(p)
                ports.append(p)

            cfg = self._build_config(nodes, ports)
            cfg_path = _data_dir() / "proxy" / "xray_pool.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                               encoding="utf-8")

            log_path = _data_dir() / "proxy" / "xray_pool.log"
            fh = open(log_path, "wb")
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            try:
                self._proc = subprocess.Popen(
                    [str(XRAY_BIN), "-c", str(cfg_path)],
                    cwd=str(XRAY_DIR),
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                self._log_fh = fh  # 保持句柄存活，避免 GC 关掉子进程 stdout
            except Exception as e:
                logger.error(f"代理池: 启动 xray 失败 {e}")
                try:
                    fh.close()
                except Exception:
                    pass
                return []

            await asyncio.sleep(wait)
            if self._proc.poll() is not None:
                try:
                    err = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
                except Exception:
                    err = "<log unreadable>"
                logger.error(f"代理池: xray 启动即退出: {err}")
                self._proc = None
                return []

            self._ports = ports
            self._addrs = [n["addr"] for n in nodes]
            self._started_at = time.time()
            self._wait_ports_up(timeout=8.0)
            logger.info(
                f"代理池就绪: {len(ports)} 个出口 "
                f"{list(zip(self._addrs, ports))}"
            )
            return self.urls()

    def _wait_ports_up(self, timeout: float = 8.0) -> None:
        deadline = time.time() + timeout
        for p in self._ports:
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", p), timeout=0.6):
                        break
                except OSError:
                    time.sleep(0.2)

    def urls(self) -> list[str]:
        return [f"socks5://127.0.0.1:{p}" for p in self._ports]

    def info(self) -> dict[str, Any]:
        return {
            "running": bool(self._proc and self._proc.poll() is None),
            "pid": self._proc.pid if self._proc else None,
            "exits": len(self._ports),
            "urls": self.urls(),
            "addrs": list(self._addrs),
            "uptime_sec": int(time.time() - self._started_at) if self._started_at else 0,
        }

    async def stop(self) -> None:
        async with self._lock:
            proc, self._proc = self._proc, None
            self._ports, self._addrs = [], []
            self._started_at = 0.0
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=4)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
            if self._log_fh is not None:
                try:
                    self._log_fh.close()
                except Exception:
                    pass
                self._log_fh = None

    # ------------------------------------------------------------------
    # 配置生成
    # ------------------------------------------------------------------
    @staticmethod
    def _build_config(nodes: list[dict[str, Any]], ports: list[int]) -> dict[str, Any]:
        """生成「每节点一个 inbound，inboundTag 固定绑 outboundTag」的配置。

        🔴 顺序即语义：Xray 的 ``routing.rules`` **按顺序匹配、命中即出**。
           pinned 规则必须排在末尾的兜底规则**之前**，否则流量会被兜底
           规则先吃掉，多出口就退化成单出口（且不会报错，极难排查）。
        """
        outbounds: list[dict[str, Any]] = []
        pinned_rules: list[dict[str, Any]] = []

        for i, (n, port) in enumerate(zip(nodes, ports)):
            tag = f"pool-{i}"
            ob = json.loads(json.dumps(n["outbound"]))  # 深拷贝，别改到原对象
            ob["tag"] = tag
            outbounds.append(ob)
            pinned_rules.append({
                "type": "field",
                "inboundTag": [f"socks-pool-{i}"],
                "outboundTag": tag,
            })

        inbounds = [{
            "tag": f"socks-pool-{i}",
            "port": port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        } for i, port in enumerate(ports)]

        outbounds += [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]

        return {
            "log": {"loglevel": "warning"},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": {
                "domainStrategy": "IPIfNonMatch",
                "rules": [
                    {"type": "field", "outboundTag": "direct", "ip": ["geoip:private"]},
                ]
                + pinned_rules
                + [
                    # pinned inbound 的其余流量（非私有地址）也走对应节点
                    {"type": "field", "outboundTag": "direct", "network": "tcp,udp"},
                ],
            },
        }


_pool: Optional[ScrapeProxyPool] = None
_pool_init = False


def get_scrape_proxy_pool() -> ScrapeProxyPool:
    """取代理池单例（不自动启动，启动由批量任务显式触发）。"""
    global _pool, _pool_init
    if not _pool_init:
        _pool = ScrapeProxyPool()
        _pool_init = True
    return _pool


async def ensure_pool_urls(max_size: int = 8) -> list[str]:
    """确保池已启动并返回可用出口 URL 列表。

    任一步失败都返回空列表 —— 调用方据此回退到「并发 + 全局单出口」，
    绝不能因为池起不来就让批量刮削整体不可用。
    """
    try:
        return await get_scrape_proxy_pool().start(max_size=max_size)
    except Exception as e:
        logger.warning(f"代理池启动失败，回退单出口: {e}")
        return []
