"""
扫描控制 API 路由

提供手动扫描触发、扫描记录查询、冷却状态查询接口。
"""

import logging

from fastapi import APIRouter, Depends, Query

from app.api.routes.auth import require_admin
from app.config.manager import get_config
from app.services.scan_control import ScanControlService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
async def get_scan_status(_admin: dict = Depends(require_admin)):
    """获取扫描控制状态（冷却信息、配置参数）"""
    config = get_config()
    service = ScanControlService.get_instance()
    should_scan = await service.should_auto_scan()

    return {
        "should_auto_scan": should_scan,
        "cooldown_hours": config.scan_control.scan_cooldown_hours,
        "reset_days": config.scan_control.scan_reset_days,
        "cooldown_remaining_seconds": service.cooldown_remaining,
    }


@router.post("/trigger")
async def trigger_manual_scan(_admin: dict = Depends(require_admin)):
    """手动触发全模块扫描（不受冷却限制）"""
    service = ScanControlService.get_instance()
    result = await service.trigger_manual_scan()
    return result


@router.get("/records")
async def get_scan_records(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    scan_type: str | None = Query(None),
    status: str | None = Query(None),
    _admin: dict = Depends(require_admin),
):
    """获取扫描记录列表"""
    service = ScanControlService.get_instance()
    records, total = await service.get_scan_records(
        limit=limit, offset=offset, scan_type=scan_type, status=status
    )
    return {"records": records, "total": total, "limit": limit, "offset": offset}
