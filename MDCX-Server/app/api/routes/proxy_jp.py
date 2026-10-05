# -*- coding: utf-8 -*-
"""日本节点（DMM/FANZA 出口）管理 API

前缀: /api/v1/proxy/jp

GET  /status      - 服务状态、节点池、出口 IP 实测
GET  /nodes       - 节点池列表（可读标签，不含凭据）
GET  /config      - 订阅源 / 刷新周期 / 取样数
PUT  /config      - 保存配置（换订阅源、改周期）
POST /nodes       - 手工添加节点
DELETE /nodes     - 清空节点池
POST /start|stop|restart - 启停日本代理
POST /test        - 测试订阅源可达性（换地址后先试这个，别直接刷新浪费时间）
POST /refresh     - 立即刷新节点池（拉订阅→实测→写盘→重启）

为什么需要「换订阅源」的配置项
------------------------------
默认源是 GitHub 上的免费节点仓库（`Au1rxx/free-vpn-subscriptions`）。免费仓库
会改名/删仓/改分支，地址一失效刷新就静默拿不到节点（表现为「DMM 突然 0 命中」）。
所以订阅地址必须是**可配置项**，失效时在界面上换新地址即可，不该要求改代码重部署。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import jp_proxy as jp

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfigPayload(BaseModel):
    sub_urls: list[str] | None = None
    refresh_hours: int | None = None
    sample: int | None = None
    auto_start: bool | None = None


class NodePayload(BaseModel):
    url: str = Field(..., min_length=8, max_length=4096)


class RefreshPayload(BaseModel):
    sample: int | None = None
    keep: int | None = None
    parallel: int | None = None
    auto_restart: bool = True


class TestSubPayload(BaseModel):
    sub_urls: list[str] | None = None


async def _probe_exit_ip() -> dict:
    """实测日本出口 IP（能拿到真实国家才算链路通）。

    🔴 不做这一步的话，界面只能显示「xray 进程活着」，而进程活着 ≠ 出口是日本
    （链式前置挂了就会静默失败，用户看不出问题在哪）。
    """
    url = jp.get_jp_proxy_url(auto_start=False)
    if not url:
        return {"ok": False, "error": "日本出口未运行"}
    try:
        import httpx
        async with httpx.AsyncClient(proxy=url, timeout=20) as c:
            last = ""
            for u in ("https://api.ip.sb/geoip", "https://ipinfo.io/json",
                      "https://ipapi.co/json/"):
                try:
                    r = await c.get(u, timeout=10)
                    j = r.json()
                    ip = j.get("ip") or j.get("query") or ""
                    cc = (j.get("country_code") or j.get("country") or "").upper()[:2]
                    return {"ok": True, "ip": ip, "country": cc,
                            "city": j.get("city") or "", "via": url}
                except Exception as e:  # noqa: BLE001
                    last = type(e).__name__
                    continue
            return {"ok": False, "error": "出口 IP 探测失败: %s" % last}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:80])}


@router.get("/status")
async def get_status(check_exit: bool = True):
    """日本出口总状态：服务、节点池、配置、真实出口 IP。"""
    svc = jp.get_jp_proxy_service()
    st = svc.status()
    cfg = jp.load_jp_config()
    meta = jp.get_nodes_meta()
    exit_ip = await _probe_exit_ip() if check_exit else {"skipped": True}
    return {
        "service": st,
        "nodes": meta,
        "config": cfg,
        "exit_ip": exit_ip,
        "in_source_order": _in_order(),
        "max_nodes": jp.MAX_JP_NODES,
        "socks_port_base": jp.JP_SOCKS_PORT,
        "http_port": jp.JP_HTTP_PORT,
    }


def _in_order() -> bool:
    """dmm_web 是否在当前刮削源序里（需 force 绕 60s 缓存）。"""
    try:
        from app.scraper.canon import jp_fallback_order
        return bool(jp_fallback_order())
    except Exception:  # noqa: BLE001
        return False


@router.get("/nodes")
async def get_nodes():
    """节点池列表（不含凭据，仅展示名称/协议/host）。"""
    out = []
    for i, u in enumerate(jp.load_jp_nodes()):
        lb = jp.parse_node_label(u)
        lb["index"] = i
        lb["port"] = jp.JP_SOCKS_PORT + i
        lb["alive"] = jp.JPProxyService._port_alive(lb["port"], timeout=0.4)
        # 🔴 build_config 只为前 MAX_JP_NODES 个节点生成 inbound，超出的节点
        # 永远不会被用到（历史遗留：手工加节点时没拦住超额）。必须标出来，
        # 否则界面显示 5 个节点、实际只跑 4 个，看不出差别。
        lb["enabled"] = i < jp.MAX_JP_NODES
        lb.pop("url", None)  # 不外泄完整订阅串（含密码）
        out.append(lb)
    return {"count": len(out), "enabled": min(len(out), jp.MAX_JP_NODES),
            "nodes": out, "updated_at": jp.get_nodes_meta()["updated_at"]}


@router.get("/config")
async def get_config():
    return jp.load_jp_config()


@router.put("/config")
async def put_config(payload: ConfigPayload):
    try:
        cfg = jp.save_jp_config(
            sub_urls=payload.sub_urls,
            refresh_hours=payload.refresh_hours,
            sample=payload.sample,
            auto_start=payload.auto_start,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "config": cfg}


@router.post("/nodes")
async def add_node(payload: NodePayload):
    u = payload.url.strip()
    if not u.startswith(("vmess://", "vless://", "trojan://", "ss://")):
        raise HTTPException(status_code=400, detail="只支持 vmess/vless/trojan/ss 节点")
    cur = jp.load_jp_nodes()
    if u in cur:
        raise HTTPException(status_code=400, detail="该节点已存在")
    if len(cur) >= jp.MAX_JP_NODES:
        raise HTTPException(
            status_code=400,
            detail="节点池已满（上限 %d 个），请先删除或刷新" % jp.MAX_JP_NODES)
    jp.save_jp_nodes(cur + [u])
    return {"ok": True, "count": len(cur) + 1}


@router.delete("/nodes")
async def clear_nodes():
    n = len(jp.load_jp_nodes())
    jp.save_jp_nodes([])
    return {"ok": True, "cleared": n}


@router.post("/start")
async def start():
    svc = jp.get_jp_proxy_service()
    if not svc.start():
        raise HTTPException(status_code=500,
                            detail=svc.status().get("last_error") or "启动失败")
    return {"ok": True, "service": svc.status(),
            "exit_ip": await _probe_exit_ip()}


@router.post("/stop")
async def stop():
    jp.get_jp_proxy_service().stop()
    return {"ok": True, "service": jp.get_jp_proxy_service().status()}


@router.post("/restart")
async def restart():
    svc = jp.get_jp_proxy_service()
    if svc.is_running():
        svc.stop()
    if not svc.start():
        raise HTTPException(status_code=500,
                            detail=svc.status().get("last_error") or "重启失败")
    return {"ok": True, "service": svc.status(),
            "exit_ip": await _probe_exit_ip()}


@router.post("/test")
async def test_subscriptions(payload: TestSubPayload):
    """测试订阅源可达性 + 能解出多少节点。

    🔴 换地址后**先测这个**再刷新：刷新要起临时 xray 逐个实测（几十秒），
    而地址写错时 3 秒就能测出来。
    """
    urls = payload.sub_urls or jp.load_jp_config()["sub_urls"]
    try:
        nodes, errors = await jp.fetch_sub_nodes(urls)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500,
                            detail="%s: %s" % (type(e).__name__, str(e)[:120]))
    hosts = {jp.node_host(n) for n in nodes if jp.node_host(n)}
    return {"ok": bool(nodes), "total": len(nodes), "host_count": len(hosts),
            "errors": errors, "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}


@router.post("/refresh")
async def refresh(payload: RefreshPayload):
    """立即刷新节点池。可能耗时数十秒（要逐个起临时 xray 实测）。"""
    try:
        res = await jp.refresh_jp_nodes(
            sample=payload.sample,
            keep=int(payload.keep or jp.MAX_JP_NODES),
            parallel=int(payload.parallel or 6),
            auto_restart=payload.auto_restart,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("刷新日本节点失败")
        raise HTTPException(status_code=500,
                            detail="%s: %s" % (type(e).__name__, str(e)[:160]))
    res["service"] = jp.get_jp_proxy_service().status()
    res["exit_ip"] = await _probe_exit_ip()
    return res
