"""重复番号扫描 API 路由

GET  /api/v1/duplicates/scan?module=jav&module=chinese → 扫描指定模块，返回重复文件清单
GET  /api/v1/duplicates/preview?module=jav              → 同上（别名）
"""

from fastapi import APIRouter, Query

from app.services.duplicate_scanner import scan_duplicates
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/scan")
async def scan_duplicates_endpoint(
    module: list[str] = Query(
        default=["jav"],
        description="要扫描的模块名列表，可重复传参（如 ?module=jav&module=chinese）",
    ),
):
    """扫描指定模块的 media_dirs，找出同番号重复视频文件。

    返回每组重复的：
    - base_code: 基础番号（去除 -C/-UC/-U）
    - files: 每个文件路径、大小、后缀标记
    - keep_index: 推荐保留的文件索引（优先中字版，其次大体积）
    - wasted_bytes: 可释放的磁盘空间

    示例请求：
        GET /api/v1/duplicates/scan?module=jav
        GET /api/v1/duplicates/scan?module=jav&module=chinese
    """
    # 使用服务注册表，以防模块未初始化
    from app.config.manager import get_config

    config = get_config()
    modules_config = getattr(config, "modules", None)

    all_results = []

    for mod_name in module:
        if not modules_config:
            logger.warning(f"[duplicates_scan] modules config 不可用，跳过 {mod_name}")
            continue

        mod_cfg = getattr(modules_config, mod_name, None)
        if not mod_cfg:
            logger.warning(f"[duplicates_scan] 模块配置不存在: {mod_name}")
            continue

        media_dirs = getattr(mod_cfg, "media_dirs", None) or []
        if not media_dirs:
            logger.info(f"[duplicates_scan] 模块 {mod_name} 未配置 media_dirs，跳过")
            continue

        result = await scan_duplicates(mod_name, media_dirs)
        all_results.append(result)

    # 合并多个模块的结果
    if not all_results:
        return {
            "total_files": 0,
            "total_groups": 0,
            "duplicate_files": 0,
            "space_wasted_bytes": 0,
            "space_wasted_display": "0 B",
            "modules": [],
        }

    return {
        "total_files": sum(r["total_files"] for r in all_results),
        "total_groups": sum(r["total_groups"] for r in all_results),
        "duplicate_files": sum(r["duplicate_files"] for r in all_results),
        "space_wasted_bytes": sum(r["space_wasted_bytes"] for r in all_results),
        "space_wasted_display": _format_size_sum(
            sum(r["space_wasted_bytes"] for r in all_results)
        ),
        "modules": all_results,
    }


@router.get("/preview")
async def preview_duplicates(
    module: list[str] = Query(
        default=["jav"],
        description="要扫描的模块名",
    ),
):
    """preview 别名，与 /scan 行为一致"""
    return await scan_duplicates_endpoint(module=module)


def _format_size_sum(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / 1024:.0f} KB"
