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
async def trigger_manual_scan(
    module: str | None = Query(
        None, description="指定模块名（jav/fc2/uncensored/chinese/pornhub/western/anime），省略则扫描全部"
    ),
    paths: list[str] | None = Query(
        None,
        description="🔴 2026-10-13 分盘扫描：本次只扫这些媒体目录（可重复传）。"
                    "必须落在该模块配置的 media_dirs 范围内；省略则扫该模块全部目录。"
                    '例：paths=T:\\&paths=U:\\ 只扫这两个盘',
    ),
    paths_bracket: list[str] = Query(
        None, alias="paths[]",
        description="兼容 axios 把数组序列化成的 paths[]=X 形式（历史 bug："
                    "axios 用 paths[] 而 FastAPI 只认 paths ⇒ 过滤静默失效、全盘扫）",
    ),
    _admin: dict = Depends(require_admin),
):
    """手动触发扫描（不受冷却限制）：可指定单模块或全部模块

    `paths` 用于把一次大扫描拆成多次（例如 PORNHUB 的 T:/U:/V: 三个盘分开扫），
    避免单次全量遍历把慢网络盘 / 事件循环压垮。
    """
    final_paths = paths or paths_bracket or None
    if paths_bracket and not paths:
        logger.warning(
            f"[scan] 收到 paths[] 形式参数（{paths_bracket}），已按 paths 处理；"
            f"请检查前端是否仍在用 axios 数组序列化"
        )
    service = ScanControlService.get_instance()
    result = await service.trigger_manual_scan(module, final_paths)
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
