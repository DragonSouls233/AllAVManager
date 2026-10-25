"""诊断包导出 API：一键收集日志/配置/环境信息打成脱敏 zip。

GET /api/v1/diagnostics/bundle → zip 文件（attachment）

只读导出，不碰任何业务数据。配置与日志已脱敏（密钥/cookie/磁力/媒体
文件名），NAS 盘符与目录结构保留用于排查——详见服务模块 docstring。
"""

import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from urllib.parse import quote

from app.services.diagnostics_bundle import build_bundle
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/bundle")
async def export_bundle():
    """生成并下载诊断包 zip。

    采集约 1-3 秒（读日志尾部 + 各库 count + NAS 探测）。
    """
    t0 = time.monotonic()
    data, filename = await build_bundle()
    logger.info(f"[diagnostics] 诊断包导出 {filename} "
                f"({len(data) // 1024} KB, {time.monotonic() - t0:.1f}s)")
    # 文件名是 ASCII（mdcx-diagnostics-<时间戳>.zip），直接放 header 安全
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; '
                                   f"filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(len(data)),
        },
    )
