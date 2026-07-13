"""网络诊断路由

参考 Hazard804-mdcx 的 network_check.py：
- 状态枚举 OK/WARNING/FAILED/SKIPPED/CANCELLED
- 站点连通性、代理、Cookie、CF Bypass 诊断
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.config.manager import get_config, get_config_manager
from app.services.network_diag import (
    run_full_diagnosis, check_site_connectivity, check_proxy, check_cookie,
    DiagReport, DiagStatus,
)

router = APIRouter()


class SingleCheckRequest(BaseModel):
    """单项检查请求"""
    check_type: str  # site / proxy / cookie
    site: Optional[str] = None
    timeout: int = 10


@router.get("/sites")
async def get_diag_sites():
    """获取可诊断的站点列表"""
    from app.services.network_diag import SITE_URLS
    cfg = get_config().network_diag
    return {
        "all_sites": [{"name": k, "url": v} for k, v in SITE_URLS.items()],
        "target_sites": cfg.target_sites,
    }


@router.post("/run")
async def run_diagnosis():
    """运行完整网络诊断（异步任务）"""
    task_id = "network-diag"
    # 直接执行（数据量小，可接受同步等待）
    report = await run_full_diagnosis(task_id=task_id)
    return report.to_dict()


@router.post("/check")
async def single_check(req: SingleCheckRequest):
    """单项检查"""
    cfg = get_config()
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()

    if req.check_type == "site":
        if not req.site:
            raise HTTPException(status_code=400, detail="站点检查必须提供 site 参数")
        result = await check_site_connectivity(
            req.site, timeout=req.timeout, proxy_url=proxy_url,
        )
    elif req.check_type == "proxy":
        result = await check_proxy(proxy_url=proxy_url, timeout=req.timeout)
    elif req.check_type == "cookie":
        if not req.site:
            raise HTTPException(status_code=400, detail="Cookie 检查必须提供 site 参数")
        result = await check_cookie(req.site, timeout=req.timeout)
    else:
        raise HTTPException(status_code=400, detail="check_type 必须是 site/proxy/cookie")

    return {
        "name": result.name,
        "status": result.status.value,
        "message": result.message,
        "duration_ms": result.duration_ms,
        "details": result.details,
    }


@router.get("/config")
async def get_diag_config():
    """获取诊断配置"""
    cfg = get_config().network_diag
    return {
        "timeout": cfg.timeout,
        "target_sites": cfg.target_sites,
    }


@router.put("/config")
async def update_diag_config(
    timeout: Optional[int] = None,
    target_sites: Optional[list[str]] = None,
):
    """更新诊断配置"""
    cm = get_config_manager()
    current = cm.config

    if timeout is not None:
        current.network_diag.timeout = max(3, min(60, timeout))
    if target_sites is not None:
        current.network_diag.target_sites = target_sites

    cm.save()
    return {"status": "ok"}
