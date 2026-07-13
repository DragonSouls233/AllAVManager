"""STRM 文件生成路由（管理 API）

走 /api/v1/strm 前缀，受 MDCX Bearer Token 保护。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager
from app.services import strm as strm_service

router = APIRouter()


class StrmConfigUpdate(BaseModel):
    """STRM 配置更新"""
    enabled: Optional[bool] = None
    output_dir: Optional[str] = None
    use_directory_template: Optional[bool] = None
    url_template: Optional[str] = None
    generate_nfo: Optional[bool] = None
    overwrite: Optional[bool] = None


class GenerateBatchRequest(BaseModel):
    """批量生成请求"""
    movie_ids: Optional[list[int]] = None
    overwrite: Optional[bool] = None


@router.get("/config")
async def get_strm_config():
    """获取 STRM 配置"""
    cfg = get_config().strm
    return {
        "enabled": cfg.enabled,
        "output_dir": cfg.output_dir,
        "use_directory_template": cfg.use_directory_template,
        "url_template": cfg.url_template,
        "generate_nfo": cfg.generate_nfo,
        "overwrite": cfg.overwrite,
        "statistics": strm_service.get_strm_statistics(),
    }


@router.put("/config")
async def update_strm_config(req: StrmConfigUpdate):
    """更新 STRM 配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.strm.enabled = req.enabled
    if req.output_dir is not None:
        current.strm.output_dir = req.output_dir
    if req.use_directory_template is not None:
        current.strm.use_directory_template = req.use_directory_template
    if req.url_template is not None:
        if "{id}" not in req.url_template:
            raise HTTPException(status_code=400, detail="url_template 必须包含 {id} 占位符")
        current.strm.url_template = req.url_template
    if req.generate_nfo is not None:
        current.strm.generate_nfo = req.generate_nfo
    if req.overwrite is not None:
        current.strm.overwrite = req.overwrite

    cm.save()
    return {"status": "ok"}


@router.post("/generate")
async def generate_strm(req: GenerateBatchRequest):
    """批量生成 STRM 文件（异步任务）"""
    if not get_config().strm.enabled:
        raise HTTPException(status_code=400, detail="STRM 生成未启用")

    result = await strm_service.generate_strm_batch(
        movie_ids=req.movie_ids,
        overwrite=req.overwrite,
    )
    return result


@router.post("/cleanup")
async def cleanup_strm():
    """清理 STRM 输出目录"""
    result = await strm_service.cleanup_strm_files()
    return result


@router.get("/statistics")
async def strm_statistics():
    """STRM 目录统计"""
    return strm_service.get_strm_statistics()
