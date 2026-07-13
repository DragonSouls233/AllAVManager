"""
日志管理路由

API 端点：
- GET  /api/v1/logs          - 获取日志列表（支持分页/级别过滤/搜索）
- GET  /api/v1/logs/stream   - SSE 实时日志流
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.config.manager import get_config_manager

logger = logging.getLogger(__name__)

router = APIRouter()

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@router.get("")
async def get_logs(
    level: Optional[str] = Query(None, description="日志级别过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页条数"),
):
    """
    获取系统日志

    - 支持按级别过滤（DEBUG/INFO/WARNING/ERROR）
    - 支持关键词搜索
    - 支持分页
    """
    manager = get_config_manager()
    log_file = manager.computed.logs_dir / "app.log"

    if not log_file.exists():
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    try:
        content = log_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        # 级别过滤
        if level and level.upper() in LOG_LEVELS:
            level_upper = level.upper()
            lines = [l for l in lines if f"[{level_upper}]" in l]

        # 搜索过滤
        if search:
            search_lower = search.lower()
            lines = [l for l in lines if search_lower in l.lower()]

        total = len(lines)

        # 分页（倒序，最新的在前）
        lines.reverse()
        start = (page - 1) * page_size
        end = start + page_size
        items = lines[start:end]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    except Exception as e:
        logger.error(f"读取日志失败: {e}")
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "error": str(e)}


@router.get("/stream")
async def stream_logs(request: Request):
    """SSE 实时日志流"""
    manager = get_config_manager()
    log_file = manager.computed.logs_dir / "app.log"

    async def generate():
        last_size = 0
        while True:
            try:
                if await request.is_disconnected():
                    break

                if log_file.exists():
                    current_size = log_file.stat().st_size
                    if current_size > last_size:
                        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(last_size)
                            new_content = f.read()
                            if new_content:
                                for line in new_content.splitlines():
                                    yield f"data: {line}\n\n"
                        last_size = current_size
                    elif current_size < last_size:
                        # 日志文件被轮��
                        last_size = 0

                import asyncio
                await asyncio.sleep(1)

            except Exception:
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
