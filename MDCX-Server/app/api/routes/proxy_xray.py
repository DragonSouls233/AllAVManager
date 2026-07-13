"""
Xray 内置代理管理 API

前缀: /api/v1/proxy/xray

GET  /status             - 运行状态、当前节点、端口
POST /start              - 启动 xray
POST /stop               - 停止 xray
POST /restart            - 重启 xray
GET  /nodes              - 节点池列表
POST /nodes              - 手动添加节点 (body: {url: "vmess://..."})
DELETE /nodes/{node_id}  - 移除节点
POST /subscription       - 设置订阅 URL (body: {url})
POST /subscription/refresh - 立即刷新订阅
POST /mode               - 切换分流模式 (body: {mode: "domain"|"global"|"direct"})
POST /select             - 手动选节点 (body: {node_id} | null 走均衡)；可来回切换
POST /speedtest          - TCP 测速所有节点
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.proxy_manager import get_proxy_manager
from app.services.proxy_speedtest import test_all_nodes
from app.services.proxy_subscription import refresh_subscription

router = APIRouter()
logger = logging.getLogger(__name__)


class NodeAddPayload(BaseModel):
    url: str


class SubscriptionPayload(BaseModel):
    url: str | None = None


class ModePayload(BaseModel):
    mode: str  # domain / global / direct


class SelectPayload(BaseModel):
    node_id: str | None = None  # 节点 id；None/"auto" 取消选择走负载均衡


@router.get("/status")
async def get_status() -> dict:
    mgr = get_proxy_manager()
    state = mgr.get_state()
    return {
        "status": "ok",
        "data": state,
    }


@router.get("/nodes")
async def list_nodes() -> dict:
    mgr = get_proxy_manager()
    nodes = mgr.list_nodes()
    return {
        "status": "ok",
        "data": [
            {
                "id": n.id,
                "name": n.name,
                "protocol": n.protocol,
                "address": n.address,
                "port": n.port,
                "latency_ms": n.latency_ms,
                "country": n.country,
            }
            for n in nodes
        ],
    }


@router.post("/nodes")
async def add_node(payload: NodeAddPayload) -> dict:
    mgr = get_proxy_manager()
    try:
        node = mgr.add_node(payload.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": "ok",
        "data": {"id": node.id, "name": node.name, "protocol": node.protocol},
    }


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str) -> dict:
    mgr = get_proxy_manager()
    if not mgr.remove_node(node_id):
        raise HTTPException(status_code=404, detail="node not found")
    return {"status": "ok"}


@router.post("/start")
async def start_proxy() -> dict:
    mgr = get_proxy_manager()
    await mgr.start()
    state = mgr.get_state()
    if not state["running"]:
        return {"status": "failed", "message": state.get("last_error") or "start failed", "data": state}
    return {"status": "ok", "data": state}


@router.post("/stop")
async def stop_proxy() -> dict:
    mgr = get_proxy_manager()
    await mgr.stop()
    return {"status": "ok", "data": mgr.get_state()}


@router.post("/restart")
async def restart_proxy() -> dict:
    mgr = get_proxy_manager()
    await mgr.restart()
    return {"status": "ok", "data": mgr.get_state()}


@router.post("/subscription")
async def set_subscription(payload: SubscriptionPayload) -> dict:
    mgr = get_proxy_manager()
    mgr.set_subscription(payload.url)
    return {"status": "ok"}


@router.post("/subscription/refresh")
async def do_refresh_subscription() -> dict:
    result = await refresh_subscription(restart_xray=True)
    return {
        "status": "ok" if result["ok"] else "failed",
        "message": result.get("error") or f"refreshed {result['count']} nodes",
        "data": result,
    }


@router.post("/mode")
async def set_mode(payload: ModePayload) -> dict:
    mgr = get_proxy_manager()
    try:
        mgr.set_mode(payload.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 已运行则热重启
    state = mgr.get_state()
    if state["running"]:
        await mgr.restart()
    return {"status": "ok", "data": mgr.get_state()}


@router.post("/select")
async def select_node(payload: SelectPayload) -> dict:
    """手动选择当前走代理的节点（来回切换）；node_id=None 取消选择走 leastPing 均衡。"""
    mgr = get_proxy_manager()
    ok = mgr.select_node(payload.node_id)
    if not ok:
        raise HTTPException(status_code=404, detail="node not found")
    # 运行中则热重启使新选择生效
    state = mgr.get_state()
    if state["running"]:
        await mgr.restart()
    return {"status": "ok", "data": mgr.get_state()}


@router.post("/speedtest")
async def do_speedtest() -> dict:
    results = await test_all_nodes()
    return {
        "status": "ok",
        "data": {
            "total": len(results),
            "alive": sum(1 for v in results.values() if v is not None),
            "results": results,
        },
    }
