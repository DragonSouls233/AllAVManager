"""媒体健康扫描 API 路由（只读）

GET /api/v1/media-health/scan?module=jav&probe=0 → 扫描模块影片文件健康状态

四态：drive_missing（盘符未就绪）/ file_missing（文件不存在）/
      probe_failed（ffprobe 探测失败）/ no_path（无 file_path 记录）
🔴 只读：不写、不删、不移动任何文件，扫描结果只是报告。
"""

from fastapi import APIRouter, Query

from app.services.media_health import (
    DETAIL_LIMIT,
    PROBE_LIMIT_DEFAULT,
    scan_media_health,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/scan")
async def scan_endpoint(
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
    probe: bool = Query(
        False,
        description="对存在的文件跑 ffprobe 深检（发现损坏/0字节/下载中断的文件）。"
        "慢：每部一次子进程，默认封顶 500 部，超出记 probe_skipped",
    ),
    probe_limit: int = Query(
        PROBE_LIMIT_DEFAULT, ge=0, le=5000,
        description="深检文件数封顶，0 = 只做存在性快检",
    ),
):
    """扫描模块影片文件健康状态（只读）。

    返回五态汇总 + 每类最多 200 条明细（*_total 为全量计数）。

    示例：
        GET /api/v1/media-health/scan?module=jav
        GET /api/v1/media-health/scan?module=jav&probe=1&probe_limit=200
    """
    try:
        return await scan_media_health(module, probe=probe, probe_limit=probe_limit)
    except Exception as e:
        logger.error(f"[media_health] 扫描失败 module={module}: {e}", exc_info=True)
        return {
            "module": module,
            "error": f"扫描失败：{type(e).__name__}: {e}",
            "scanned": 0,
            "ok": 0,
            "no_path": 0,
            "drive_missing": [],
            "file_missing": [],
            "probe_failed": [],
            "drive_missing_total": 0,
            "file_missing_total": 0,
            "probe_failed_total": 0,
            "probe_skipped": 0,
            "probe_errors": 0,
            "duration_ms": 0,
            "issue_total": 0,
        }


@router.get("/limits")
async def limits_endpoint():
    """返回扫描限制参数（前端展示「最多列 200 条」之类的提示）"""
    return {"detail_limit": DETAIL_LIMIT, "probe_limit_default": PROBE_LIMIT_DEFAULT}
