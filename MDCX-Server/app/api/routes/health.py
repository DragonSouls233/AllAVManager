"""
健康检查路由

端点：
- GET /api/v1/health       — 存活检查
- GET /api/v1/health/ready — 就绪检查
- GET /api/v1/health/live  — 存活检查（别名）
- GET /api/v1/health/metrics — Prometheus 格式指标（供 ServiceMonitor 抓取）
- GET /api/v1/version      — 版本/补丁信息
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config.manager import get_config, PROJECT_ROOT

router = APIRouter()

_VERSION_CACHE: dict | None = None


def _load_version() -> dict:
    """读取 VERSION.json（带缓存，避免每次请求都读文件）"""
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE
    vpath = PROJECT_ROOT / "VERSION.json"
    try:
        _VERSION_CACHE = json.loads(vpath.read_text(encoding="utf-8"))
    except Exception:
        _VERSION_CACHE = {"version": "unknown", "patch_level": "unknown"}
    return _VERSION_CACHE


@router.get("/version")
async def version_info():
    """返回当前版本和已应用补丁列表"""
    return _load_version()


@router.get("")
async def health_check():
    """健康检查"""
    config = get_config()
    return {
        "status": "ok",
        "app_name": config.app_name,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/ready")
async def readiness_check():
    """就绪检查"""
    from app.db.database import get_database

    try:
        db = get_database()
        # 简单查询测试数据库连接
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}


@router.get("/live")
async def liveness_check():
    """存活检查"""
    return {"status": "alive"}


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标端点（exposition format，供 Prometheus / ServiceMonitor 抓取）"""
    from app.services.metrics import generate_metrics_text, get_content_type, collect_db_metrics

    # 刷新数据库指标（异步采集）
    await collect_db_metrics()

    text = generate_metrics_text()
    return Response(content=text, media_type=get_content_type())
