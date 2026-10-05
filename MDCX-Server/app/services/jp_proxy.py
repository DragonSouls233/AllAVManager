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


def _socks_alive(host: str, port: int, timeout: float = 1.5) -> bool:
    """端口是否真的在监听（不能只信配置：本地 Xray 可能没开）。"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_front_socks() -> str:
    """挑一个**真的活着**的前置 socks。

    🔴 2026-10-05 实测踩坑：日本节点服务器在境外，本机直连必然超时，
    所以链式的「前置」是刚需。但前置本身是外部进程（用户本地 Xray 10808
    或项目内置 xray 18920），**它挂了整条日本链路就全废**，而原来这里
    只是盲信 `get_effective_proxy_url()`，10808 不可达时照样生成配置，
    最终表现为「服务 running 但请求全 ConnectError」。

    优先级：项目当前代理 → 内置 xray(18920) → 本地 Xray(10808)。
    """
    candidates: list[str] = []
    try:
        from app.services.proxy_manager import get_effective_proxy_url
        cur = (get_effective_proxy_url() or "").replace("socks5://", "").strip()
        if cur:
            candidates.append(cur)
    except Exception as e:  # noqa: BLE001
        logger.debug("读取当前代理失败: %s", e)
    candidates.append("127.0.0.1:18920")   # 项目内置 xray socks
    candidates.append("127.0.0.1:10808")   # 常见本地 Xray

    for cand in candidates:
        host, _, p = cand.rpartition(":")
        if not p.isdigit():
            continue
        if _socks_alive(host or "127.0.0.1", int(p)):
            logger.info("日本链路前置代理: %s", cand)
            return cand
    # 都不可达也要返回最优猜测，让 xray 报真实错误而不是静默失败
    fallback = candidates[0] if candidates else "127.0.0.1:10808"
    logger.warning("未找到可用的前置 socks，回退 %s（链路可能不通）", fallback)
    return fallback


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
        self._log_file = None
        #: True 表示端口由「上一个进程的 detached xray」在服务，本进程未持有 proc
        self._adopted = False
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
        """日本出口是否**真的可用**。

        🔴 判定必须**以端口为权威**，不能只看 `self._proc`：
        xray 是 detached 独立进程，服务重启后端口仍由上一个 xray 监听，
        此时 `self._proc is None` 但链路完全正常。若此时判 False 并再起一个
        实例，就会撞 `bind: Only one usage of each socket address`，
        新实例起不来 → `get_jp_proxy_url()` 返回 None → 分流静默退回美国出口
        （2026-10-05 实测踩到：DMM 明明有日本节点却拿到「海外限制」页）。

        所以：`端口活着 = 可用`（哪怕不是本进程起的）。
        """
        if self._port_alive(JP_SOCKS_PORT):
            if self._proc is None or self._proc.poll() is not None:
                self._adopted = True
            return True
        return False

    @staticmethod
    def _port_alive(port: int, timeout: float = 1.0) -> bool:
        import socket
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except OSError:
            return False

    def proxy_for(self) -> str:
        """轮转取一个日本节点对应的 socks URL（实现简易故障转移）。"""
        n = self._live_node_count()
        with self._rr_lock:
            self._rr = (self._rr + 1) % n
            idx = self._rr
        return "socks5://127.0.0.1:%d" % (JP_SOCKS_PORT + idx)

    def _live_node_count(self) -> int:
        """实际在监听的节点端口数。

        接管已运行实例时 `self._node_count` 不可信（=0），直接用会退化成
        永远只用第 0 个端口。这里实探一遍端口，只统计活着的前 N 个。
        """
        best = 0
        for i in range(MAX_JP_NODES):
            if not self._port_alive(JP_SOCKS_PORT + i, timeout=0.4):
                break
            best = i + 1
        return best or max(1, self._node_count)

    def socks_url(self) -> str:
        return self.proxy_for()

    def status(self) -> dict:
        live = self._live_node_count()
        return {
            "running": self.is_running(),
            "socks_port": JP_SOCKS_PORT,
            "http_port": JP_HTTP_PORT,
            "front": self._front,
            "uptime": round(time.time() - self._started_at, 1) if self._started_at else 0,
            "last_error": self._last_err,
            "nodes": len(load_jp_nodes()),
            "active_nodes": live,
            "adopted": self._adopted,
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
            front_socks = resolve_front_socks()
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
            # 🔴 必须让 xray **脱离本进程组**（Windows CREATE_NEW_PROCESS_GROUP +
            # DETACHED_PROCESS + CREATE_NO_WINDOW）：否则调用方脚本/服务一退出，
            # xray 就被连带杀掉，表现为「服务自报 running 但端口 ConnectError」
            # （2026-10-05 实测踩到）。
            # 日志必须落**文件**而不是 stderr=PIPE：脱离后没人读管道，
            # xray 写日志会把管道写满而卡死。
            flags = 0
            for name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS",
                         "CREATE_NO_WINDOW"):
                flags |= getattr(subprocess, name, 0)
            log_path = _data_dir() / "proxy" / "jp_proxy_xray.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(str(log_path), "ab", buffering=0)
            self._proc = subprocess.Popen(
                [str(XRAY_BIN), "run", "-c", str(tmp)],
                stdout=self._log_file, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
        except Exception as e:  # noqa: BLE001
            self._last_err = "xray 启动失败: %s" % e
            logger.warning(self._last_err)
            return False

        time.sleep(2.5)
        if not self.is_running():
            tail = ""
            try:
                lp = _data_dir() / "proxy" / "jp_proxy_xray.log"
                if lp.exists():
                    tail = lp.read_text(encoding="utf-8", errors="replace")[-300:]
            except Exception:
                pass
            self._last_err = "xray 未就绪: %s" % (
                tail.strip() or ("rc=%s" % self._proc.returncode))
            logger.warning(self._last_err)
            self.stop()
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
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self._started_at = 0.0
        self._node_count = 0


def get_jp_proxy_service() -> JPProxyService:
    return JPProxyService.instance()


# --------------------------------------------------------------------------
# 节点探测（供 scripts/_refresh_jp_nodes.py 调用）
# --------------------------------------------------------------------------
#: 判定节点是否合格时用的 FANZA 目标（取首页即可，不必打详情页——详情页是
#: JS 动态渲染，静态请求恒定返回空壳，用它判会误杀所有节点）
FANZA_PROBE_URLS: tuple[str, ...] = ("https://www.dmm.co.jp/",)


def build_chained_config(node, socks_port: int, front_socks: str) -> dict:
    """构造「前置代理 → 日本节点」的链式 xray 配置（**单节点单端口**）。

    🔴 为什么必须链式（2026-10-05 实测）：这批免费节点服务器在**境外**
    （8x/3x/5x AWS 段），本机直连它们的 TCP 443 全部 TimeoutError
    ⇒ xray 直连模式下 100% 不通，极易被误判成「节点全挂了」。让节点
    outbound 经 `proxySettings` 走前置 socks 出去才有机会连上。
    实测同一批节点：直连 0 存活 → 链式 21/24 存活。
    """
    ob = dict(node.outbound)
    ob["tag"] = "jp"
    ob["proxySettings"] = {"tag": "front"}
    host, _, p = front_socks.rpartition(":")
    port = int(p) if p.isdigit() else 10808
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "socks-in", "port": socks_port, "listen": "127.0.0.1",
            "protocol": "socks", "settings": {"auth": "noauth", "udp": True},
        }],
        "outbounds": [
            ob,
            {"tag": "front", "protocol": "socks",
             "settings": {"servers": [{"address": host or "127.0.0.1",
                                       "port": port}]}},
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {"rules": [
            {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "jp"},
        ]},
    }


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def probe_node(node_url: str, xray_bin: Optional[str] = None,
                     timeout: float = 12.0,
                     front_socks: str = "") -> dict:
    """起一个**临时独立 xray** 探测单个节点。

    返回 {url,name,ok,ip,country,fanza,err}。`ok=True` 表示出口为日本且
    FANZA 未被地区封锁 —— 只有这种节点才值得进正式池。

    为什么用临时实例而不是复用常驻服务：常驻服务已占用固定端口 18930+，
    探测要并发筛几十个节点，只能各自起临时实例。
    """
    import asyncio
    import shutil
    import socket
    import tempfile

    from app.services.proxy_parser import parse_node_url
    from app.services.proxy_manager import XRAY_BIN
    from app.services.xray_config import build_xray_config

    xray_bin = str(xray_bin or XRAY_BIN)
    res = {"url": node_url[:80], "ok": False, "ip": "", "country": "",
           "fanza": "", "err": ""}
    try:
        node = parse_node_url(node_url)
    except Exception as e:  # noqa: BLE001
        res["err"] = "parse: %s" % e
        return res
    res["name"] = str(getattr(node, "name", ""))[:40]

    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="jpvpn_"))
    proc = None
    try:
        if front_socks:
            cfg = build_chained_config(node, port, front_socks)
        else:
            cfg = build_xray_config(nodes=[node], socks_port=port,
                                    http_port=_free_port())
        cfg_path = tmp / "config.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.Popen(
            [xray_bin, "run", "-c", str(cfg_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        socks = "socks5://127.0.0.1:%d" % port
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                if proc.poll() is not None:
                    res["err"] = "xray 启动失败 rc=%s" % proc.returncode
                    return res
                time.sleep(0.3)

        import httpx
        async with httpx.AsyncClient(proxy=socks, timeout=timeout,
                                     follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0"}) as c:
            alive = False
            for probe in ("https://1.1.1.1/cdn-cgi/trace",
                          "https://api.ip.sb/geoip"):
                try:
                    rr = await c.get(probe, timeout=6.0)
                    if rr.status_code < 500:
                        alive = True
                        if "ip.sb" in probe:
                            try:
                                j = rr.json()
                                res["ip"] = j.get("ip") or j.get("query") or ""
                                res["country"] = (j.get("country_code")
                                                  or j.get("country") or "").upper()[:2]
                            except Exception:  # noqa: BLE001
                                pass
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not alive:
                res["err"] = "节点不通（超时/拒绝）"
                return res
            if not res["ip"]:
                for url in ("https://ipinfo.io/json", "https://ipapi.co/json/"):
                    try:
                        rr = await c.get(url, timeout=8.0)
                        j = rr.json()
                        res["ip"] = j.get("ip") or j.get("query") or ""
                        res["country"] = (j.get("country_code")
                                          or j.get("country") or "").upper()[:2]
                        break
                    except Exception:  # noqa: BLE001
                        continue
            if not res["ip"]:
                res["err"] = "出口 IP 探测失败"
                return res
            for u in FANZA_PROBE_URLS:
                try:
                    rr = await c.get(u, timeout=20.0)
                    body = rr.text[:4000]
                    blocked = any(k in body for k in ("海外からは", "ブロックされ",
                                                      "not available in your"))
                    res["fanza"] = "%s %d" % ("BLOCKED" if blocked else "OK",
                                              rr.status_code)
                    if not blocked:
                        res["ok"] = True
                    break
                except Exception as e:  # noqa: BLE001
                    res["fanza"] = "ERR %s" % type(e).__name__
    except Exception as e:  # noqa: BLE001
        res["err"] = res["err"] or "%s: %s" % (type(e).__name__, str(e)[:60])
    finally:
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    return res


def get_jp_proxy_url(auto_start: bool = True) -> Optional[str]:
    """取日本出口代理 URL；不可用时返回 None（调用方回退原代理）。"""
    svc = get_jp_proxy_service()
    if not svc.is_running():
        if not auto_start:
            return None
        if not svc.start():
            return None
    return svc.socks_url()
