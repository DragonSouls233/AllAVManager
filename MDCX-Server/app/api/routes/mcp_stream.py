"""MCP 协议兼容 + 流媒体聚合搜索 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.mcp_service import MCPService, MCP_CAPABILITIES
from app.services.streaming_aggregator import search_online_source_aggregated

router = APIRouter()
mcp = MCPService()


# ------------------------------------------------------------------ #
# MCP 协议端点
# ------------------------------------------------------------------ #


@router.get("/mcp/capabilities")
async def mcp_capabilities():
    """返回 MCP 协议能力声明。"""
    return MCP_CAPABILITIES


@router.post("/mcp/tools/{tool_name}")
async def mcp_tool_call(tool_name: str, arguments: dict = {}):
    """调用 MCP 工具。"""
    result = await mcp.handle_tool_call(tool_name, arguments)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "tool call failed"))
    return result


@router.get("/mcp/resources/{uri:path}")
async def mcp_resource(uri: str):
    """获取 MCP 资源。"""
    full_uri = f"mdcx://{uri}"
    data = await mcp.get_resource(full_uri)
    if data is None:
        raise HTTPException(status_code=404, detail=f"resource not found: {full_uri}")
    return {"uri": full_uri, "data": data}


# ------------------------------------------------------------------ #
# 流媒体聚合搜索
# ------------------------------------------------------------------ #


@router.get("/stream/search")
async def api_stream_search(code: str = Query(..., description="番号，如 SSIS-001")):
    """聚合搜索番号的在线播放源。"""
    result = await search_online_source_aggregated(code)
    return result
