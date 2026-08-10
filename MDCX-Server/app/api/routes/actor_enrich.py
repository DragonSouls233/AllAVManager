"""
演员资料自动补全 - API 端点

- POST /api/v1/actor-enrich/scan  手动触发一轮补全（可选 ?module=jav 限定模块）
- GET  /api/v1/actor-enrich/status 查看扫描器状态与最近一次结果

后台扫描器由 app/services/actor_profile_enrich_scanner.ensure_scanner_started() 启动。
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import actor_profile_enrich_scanner as scanner

logger = logging.getLogger(__name__)
router = APIRouter()


class EnrichScanResponse(BaseModel):
    status: str
    module: Optional[str] = None
    message: str = ""


class EnrichStatusResponse(BaseModel):
    running: bool
    scanning: bool
    enabled: bool
    interval_seconds: int
    last_run_at: Optional[str] = None
    last_stats: dict = {}


@router.post("/scan", response_model=EnrichScanResponse)
async def trigger_scan(
    module: Optional[str] = Query(None, description="限定模块：jav/fc2/uncensored/chinese/western/pornhub/anime，省略则全部"),
):
    """手动触发一轮演员资料补全扫描（后台异步执行）。"""
    # 确保后台扫描器也在运行
    scanner.ensure_scanner_started()
    # 后台执行一轮（不受 HTTP 请求阻塞）
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(scanner.run_once(module))
    except Exception as e:
        logger.warning(f"触发补全扫描失败: {e}")
        return EnrichScanResponse(status="error", module=module, message=str(e))
    return EnrichScanResponse(
        status="started",
        module=module,
        message=f"已启动{'模块 '+module if module else '全模块'}演员资料补全扫描",
    )


@router.get("/status", response_model=EnrichStatusResponse)
async def scan_status():
    """查看扫描器状态与最近一次扫描结果。"""
    scanner.ensure_scanner_started()
    return EnrichStatusResponse(**scanner.get_status())
