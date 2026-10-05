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

import asyncio
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


def _config_file() -> Path:
    return _data_dir() / "proxy" / "jp_config.json"


#: 默认订阅源。GitHub 仓库路径会变（作者改名/仓库删除/分支调整），
#: 所以做成可配置项，失效时在 Web 界面直接换新地址即可，无需改代码。
DEFAULT_SUB_URLS: tuple[str, ...] = (
    "https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/"
    "output/by-country/v2ray-base64-JP.txt",
)

#: 默认刷新周期（小时）。免费节点寿命以**小时**计（2026-10-05 实测：
#: 同一批 11:30 实测 21/24 可用，11:40 全部 TLS 握手失败），所以必须定期重拉。
#: 用户明确要求「至少 8 小时」—— 间隔太密只是白耗执行开销，节点并不会更长寿。
DEFAULT_REFRESH_HOURS = 8

#: 刷新周期允许范围。低于 1h 意义不大（免费节点活不过几小时），
#: 高于 24h 则可能整段时间都无可用节点。
MIN_REFRESH_HOURS = 1
MAX_REFRESH_HOURS = 168


def load_jp_config() -> dict:
    """读取日本节点的**可配置项**（订阅源、刷新周期）。

    🔴 为什么要独立于 jp_nodes.json：节点池是机器写的（刷新脚本），
    而订阅源/周期是人改的（用户在界面上换失效的 GitHub 地址）。
    分开存避免两边互相覆盖。
    """
    cfg = {
        "sub_urls": list(DEFAULT_SUB_URLS),
        "refresh_hours": DEFAULT_REFRESH_HOURS,
        "sample": 40,
        "auto_start": True,
    }
    p = _config_file()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            subs = [str(u).strip() for u in (d.get("sub_urls") or []) if str(u).strip()]
            # 允许配空数组（用户想手工维护节点池），但列表为空时回退默认源
            if subs:
                cfg["sub_urls"] = subs
            try:
                h = int(d.get("refresh_hours", DEFAULT_REFRESH_HOURS))
                cfg["refresh_hours"] = max(MIN_REFRESH_HOURS,
                                           min(MAX_REFRESH_HOURS, h))
            except (TypeError, ValueError):
                pass
            try:
                cfg["sample"] = max(5, min(200, int(d.get("sample", 40))))
            except (TypeError, ValueError):
                pass
            cfg["auto_start"] = bool(d.get("auto_start", True))
        except Exception as e:  # noqa: BLE001
            logger.warning("读取日本节点配置失败 %s: %s", p, e)
    return cfg


def save_jp_config(sub_urls: Optional[list] = None,
                    refresh_hours: Optional[int] = None,
                    sample: Optional[int] = None,
                    auto_start: Optional[bool] = None) -> dict:
    """保存可配置项（只覆盖传入的字段），返回保存后的完整配置。"""
    cfg = load_jp_config()
    if sub_urls is not None:
        clean = [str(u).strip() for u in sub_urls if str(u).strip()]
        if not clean:
            raise ValueError("订阅源不能为空")
        for u in clean:
            if not u.startswith(("http://", "https://")):
                raise ValueError("订阅源必须是 http(s) 地址: %s" % u)
        cfg["sub_urls"] = clean
    if refresh_hours is not None:
        try:
            h = int(refresh_hours)
        except (TypeError, ValueError):
            raise ValueError("刷新周期必须是整数小时")
        cfg["refresh_hours"] = max(MIN_REFRESH_HOURS, min(MAX_REFRESH_HOURS, h))
    if sample is not None:
        try:
            cfg["sample"] = max(5, min(200, int(sample)))
        except (TypeError, ValueError):
            raise ValueError("取样数必须是整数")
    if auto_start is not None:
        cfg["auto_start"] = bool(auto_start)

    p = _config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def get_nodes_meta() -> dict:
    """节点池的元信息（供界面展示）。"""
    p = _nodes_file()
    updated = ""
    if p.exists():
        try:
            updated = str(json.loads(p.read_text(encoding="utf-8")).get("updated_at") or "")
        except Exception:  # noqa: BLE001
            updated = ""
    return {"count": len(load_jp_nodes()), "updated_at": updated, "file": str(p)}


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


# --------------------------------------------------------------------------
# 节点池刷新（订阅 → 实测筛选 → 写盘 → 重启）
# --------------------------------------------------------------------------
# 🔴 为什么从 scripts/_refresh_jp_nodes.py 提升到正式模块：
#   Web 界面要能「立即刷新」，API 必须能在**服务器上**直接调用；而
#   scripts/ 下的东西未必随正式代码部署（2026-10-05 就踩过：刷新脚本
#   依赖另一个测试脚本，服务器上 FileNotFoundError）。脚本改为调用本模块，
#   两边共用一份实现。

def node_host(node_url: str) -> str:
    """取节点 URL 的 host（用于按 host 分散取样）。

    同批 trojan 常共用同一批失效域名，按 host 轮转取样才不会全测同一批。
    """
    try:
        if node_url.startswith("vmess://"):
            import base64 as _b
            raw = "".join(node_url[8:].split())
            d = json.loads(_b.b64decode(raw + "=" * (-len(raw) % 4))
                           .decode("utf-8", "replace"))
            return str(d.get("add") or "")
        rest = node_url.split("://", 1)[1].split("@", 1)[-1]
        return rest.split(":")[0].split("?")[0]
    except Exception:  # noqa: BLE001
        return ""


async def fetch_sub_nodes(sub_urls: Optional[list] = None) -> tuple:
    """拉取订阅（v2ray base64）。

    返回 ``(nodes, errors)``：节点 URL 列表 + 每个失败源的错误说明
    （GitHub 仓库改名/删除时错误要能显示到界面上，否则用户无从下手）。

    订阅源**可配置**（`load_jp_config()['sub_urls']`）—— GitHub 仓库地址
    会随作者改名/仓库删除而失效，必须能在界面上换新地址。
    """
    import base64

    import httpx

    from app.services.proxy_manager import get_effective_proxy_url

    urls = list(sub_urls or load_jp_config()["sub_urls"])
    proxy = get_effective_proxy_url()
    nodes: list = []
    errors: list = []
    for u in urls:
        try:
            r = httpx.get(u, proxy=proxy, timeout=60, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            errors.append("%s → %s" % (u[:80], type(e).__name__))
            logger.warning("订阅拉取失败 %s: %s", u[:80], e)
            continue
        raw = "".join(r.text.split())
        try:
            dec = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            dec = r.text
        keep = ("vmess://", "vless://", "trojan://", "ss://")
        got = [ln.strip() for ln in dec.split("\n") if ln.strip().startswith(keep)]
        nodes.extend(got)
    return nodes, errors


def spread_sample(nodes: list, want: int) -> list:
    """按 host 轮转取样，避免全测同一批失效域名。"""
    by_host: dict = {}
    for n in nodes:
        by_host.setdefault(node_host(n), []).append(n)
    out: list = []
    i = 0
    while len(out) < want:
        added = False
        for lst in by_host.values():
            if i < len(lst):
                cand = lst[i]
                if cand not in out:
                    out.append(cand)
                    added = True
                if len(out) >= want:
                    break
        if not added:
            break
        i += 1
    return out


async def refresh_jp_nodes(sample: Optional[int] = None,
                           keep: int = MAX_JP_NODES,
                           parallel: int = 6,
                           front_socks: str = "",
                           auto_restart: bool = True) -> dict:
    """完整刷新流程：拉订阅 → 实测筛选 → 写盘 → 重启服务。

    返回 ``{ok, total, sampled, ok_count, jp_count, kept, log, errors, updated_at}``。
    本轮无可用节点时**保留原池不动**（宁可继续用旧的，也别把能用的清空）。
    """
    from app.services.proxy_manager import XRAY_BIN

    cfg = load_jp_config()
    want = int(sample or cfg.get("sample") or 40)
    front = front_socks or resolve_front_socks()
    log: list = []

    log.append("拉取订阅 …")
    nodes, errors = await fetch_sub_nodes()
    for e in errors:
        log.append("  ✘ %s" % e)
    if not nodes:
        log.append("订阅为空（或全部拉取失败），保留现有节点池")
        return {"ok": False, "total": 0, "sampled": 0, "ok_count": 0,
                "jp_count": 0, "kept": len(load_jp_nodes()), "log": log,
                "errors": errors, "updated_at": get_nodes_meta()["updated_at"]}

    log.append("订阅共 %d 个节点" % len(nodes))
    picked = spread_sample(nodes, want)
    log.append("按 host 轮转取样 %d 个开始实测（前置 %s）" % (len(picked), front))

    sem = asyncio.Semaphore(parallel)

    async def one(u: str):
        async with sem:
            return await probe_node(u, str(XRAY_BIN), front_socks=front)

    t0 = time.time()
    results = await asyncio.gather(*[one(u) for u in picked],
                                   return_exceptions=True)
    results = [r for r in results if isinstance(r, dict)]
    # 排序：FANZA 可用 > 仅日本出口 > 其他
    results.sort(key=lambda r: 0 if r.get("ok")
                 else (1 if r.get("country") == "JP" else 2))
    ok_list = [r for r in results if r.get("ok")]
    jp_list = [r for r in results if r.get("country") == "JP"]
    log.append("实测 %d 个（%.0fs）：FANZA 可用 %d，仅日本出口 %d"
               % (len(results), time.time() - t0, len(ok_list), len(jp_list)))

    usable = ok_list or jp_list
    # 结果里 url 被截断，按 host 回查完整 URL
    full_by_host: dict = {}
    for n in nodes:
        full_by_host.setdefault(node_host(n), n)
    keep_urls: list = []
    for r in usable[:max(1, keep)]:
        u = full_by_host.get(node_host(r.get("url", "")))
        if u and u not in keep_urls:
            keep_urls.append(u)
            log.append("  ✔ %-26s %-16s %s %s"
                       % (r.get("name", "?")[:26], r.get("ip", ""),
                          r.get("country", ""), r.get("fanza", "")))

    if not keep_urls:
        log.append("本轮无可用节点 —— 保留原节点池不动")
        return {"ok": False, "total": len(nodes), "sampled": len(picked),
                "ok_count": len(ok_list), "jp_count": len(jp_list),
                "kept": len(load_jp_nodes()), "log": log, "errors": errors,
                "updated_at": get_nodes_meta()["updated_at"]}

    save_jp_nodes(keep_urls)
    meta = get_nodes_meta()
    log.append("已写入 %d 个节点（%s）" % (len(keep_urls), meta["updated_at"]))

    if auto_restart:
        svc = get_jp_proxy_service()
        if svc.is_running():
            svc.stop()
        if svc.start(front_socks=front if front.startswith("1") else "socks5://" + front):
            log.append("日本代理服务已重启")
        else:
            log.append("⚠ 日本代理服务启动失败：%s" % (svc.status().get("last_error") or "?"))
    return {"ok": True, "total": len(nodes), "sampled": len(picked),
            "ok_count": len(ok_list), "jp_count": len(jp_list),
            "kept": len(keep_urls), "log": log, "errors": errors,
            "updated_at": meta["updated_at"]}


def parse_node_label(node_url: str) -> str:
    """把节点 URL 解析成可读标签（名称/协议/host），供界面展示。

    只显示 host 与协议尾部，**不暴露完整凭据**（订阅串含密码）。
    """
    try:
        from app.services.proxy_parser import parse_node_url
        node = parse_node_url(node_url)
        name = str(getattr(node, "name", "") or "")
        proto = node_url.split("://", 1)[0]
        return {"name": name[:48], "proto": proto,
                "host": node_host(node_url), "url": node_url}
    except Exception:  # noqa: BLE001
        return {"name": "", "proto": node_url.split("://", 1)[0],
                "host": node_host(node_url), "url": node_url}
