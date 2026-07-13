"""命名模板路由

提供 Jinja2 沙箱命名模板的预览、验证、配置能力。
参考 Hazard804-mdcx 的命名模板设计。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager
from app.services import naming

router = APIRouter()


class PreviewRequest(BaseModel):
    """预览请求"""
    template: str
    sample_data: Optional[dict] = None


class ValidateRequest(BaseModel):
    """验证请求"""
    template: str


class NamingConfigUpdate(BaseModel):
    """命名配置更新"""
    enabled: Optional[bool] = None
    file_template: Optional[str] = None
    dir_template: Optional[str] = None
    poster_template: Optional[str] = None
    thumb_template: Optional[str] = None
    replace_invalid_to_underscore: Optional[bool] = None
    max_length: Optional[int] = None


class RenderForMovieRequest(BaseModel):
    """为影片渲染请求"""
    template: str
    movie_dict: dict
    actors: Optional[list[str]] = None
    extension: Optional[str] = None
    is_directory: bool = False


@router.get("/config")
async def get_naming_config():
    """获取命名模板配置"""
    cfg = get_config().naming
    return {
        "enabled": cfg.enabled,
        "file_template": cfg.file_template,
        "dir_template": cfg.dir_template,
        "poster_template": cfg.poster_template,
        "thumb_template": cfg.thumb_template,
        "replace_invalid_to_underscore": cfg.replace_invalid_to_underscore,
        "max_length": cfg.max_length,
    }


@router.put("/config")
async def update_naming_config(req: NamingConfigUpdate):
    """更新命名模板配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.naming.enabled = req.enabled
    if req.file_template is not None:
        ok, err = naming.validate_template(req.file_template)
        if not ok:
            raise HTTPException(status_code=400, detail=f"file_template 语法错误: {err}")
        current.naming.file_template = req.file_template
    if req.dir_template is not None:
        ok, err = naming.validate_template(req.dir_template)
        if not ok:
            raise HTTPException(status_code=400, detail=f"dir_template 语法错误: {err}")
        current.naming.dir_template = req.dir_template
    if req.poster_template is not None:
        ok, err = naming.validate_template(req.poster_template)
        if not ok:
            raise HTTPException(status_code=400, detail=f"poster_template 语法错误: {err}")
        current.naming.poster_template = req.poster_template
    if req.thumb_template is not None:
        ok, err = naming.validate_template(req.thumb_template)
        if not ok:
            raise HTTPException(status_code=400, detail=f"thumb_template 语法错误: {err}")
        current.naming.thumb_template = req.thumb_template
    if req.replace_invalid_to_underscore is not None:
        current.naming.replace_invalid_to_underscore = req.replace_invalid_to_underscore
    if req.max_length is not None:
        current.naming.max_length = max(20, min(255, req.max_length))

    cm.save()
    return {"status": "ok"}


@router.post("/preview")
async def preview(req: PreviewRequest):
    """预览模板渲染效果（使用内置示例数据或自定义数据）"""
    result = naming.preview_template(req.template, req.sample_data)
    return result


@router.post("/validate")
async def validate(req: ValidateRequest):
    """验证模板语法"""
    ok, err = naming.validate_template(req.template)
    return {"ok": ok, "error": err}


@router.post("/render")
async def render_for_movie(req: RenderForMovieRequest):
    """为指定影片数据渲染命名"""
    try:
        if req.is_directory:
            result = naming.render_dirpath(req.template, req.movie_dict, req.actors)
        else:
            result = naming.render_filename(
                req.template, req.movie_dict, req.actors, req.extension or "",
            )
        return {"ok": True, "result": result, "error": ""}
    except Exception as e:
        return {"ok": False, "result": "", "error": f"{type(e).__name__}: {e}"}


@router.get("/defaults")
async def get_default_templates():
    """获取默认模板示例"""
    return {"templates": naming.get_default_templates()}


@router.get("/variables")
async def get_variables():
    """获取所有可用模板变量"""
    return {
        "variables": naming.get_available_variables(),
        "filters": naming.get_available_filters(),
    }
