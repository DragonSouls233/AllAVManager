"""115 网盘离线下载路由（§7.6）

对接 115 网盘 Web API，提供：
- 配置管理（Cookie / Token / 自动入库 / 目标文件夹）
- 登录验证与连接状态查询
- 离线下载任务管理（添加 / 列表 / 取消）
- 文件浏览（按文件夹 CID 导航）
- 扫描文件夹

参考 cloud_drive2.py 路由的实现风格。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config.manager import get_config, get_config_manager
from app.services.pan_115 import pan_115_client

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Pydantic 模型 ==============

class Pan115ConfigUpdate(BaseModel):
    """115 网盘配置更新请求"""
    enabled: Optional[bool] = None
    cookies: Optional[str] = None  # 空字符串或 *** 不更新
    token: Optional[str] = None
    auto_link_to_library: Optional[bool] = None
    target_folder_id: Optional[str] = None


class Pan115LoginRequest(BaseModel):
    """手动登录请求（覆盖配置中的凭据）"""
    cookies: Optional[str] = None
    token: Optional[str] = None


class AddOfflineTaskRequest(BaseModel):
    """添加离线下载任务请求"""
    magnet_url: str = Field(..., description="磁力链接 / HTTP / ed2k 链接")
    target_cid: Optional[str] = Field(None, description="保存目录 CID（None 用配置默认值）")


class ScanRequest(BaseModel):
    """扫描文件请求"""
    folder_id: Optional[str] = None
    recursive: bool = True
    max_depth: int = Field(5, ge=1, le=20)


# ============== 配置管理 ==============

@router.get("/config")
async def get_pan115_config():
    """获取 115 网盘配置"""
    cfg = get_config().pan_115
    return {
        "enabled": cfg.enabled,
        "cookies": "***" if cfg.cookies else "",
        "token": "***" if cfg.token else "",
        "auto_link_to_library": cfg.auto_link_to_library,
        "target_folder_id": cfg.target_folder_id or "",
    }


@router.put("/config")
async def update_pan115_config(req: Pan115ConfigUpdate):
    """更新 115 网盘配置"""
    cm = get_config_manager()
    current = cm.config
    cfg = current.pan_115

    if req.enabled is not None:
        cfg.enabled = req.enabled
    # cookies / token 为敏感字段，*** 或空字符串表示不更新
    if req.cookies is not None and req.cookies != "" and req.cookies != "***":
        cfg.cookies = req.cookies
    if req.token is not None and req.token != "" and req.token != "***":
        cfg.token = req.token
    if req.auto_link_to_library is not None:
        cfg.auto_link_to_library = req.auto_link_to_library
    if req.target_folder_id is not None:
        cfg.target_folder_id = req.target_folder_id or None

    cm.save()
    return {"ok": True, "msg": "配置已保存"}


# ============== 登录与连接状态 ==============

@router.get("/status")
async def get_pan115_status():
    """获取 115 网盘连接状态"""
    return await pan_115_client.get_status()


@router.post("/login")
async def pan115_login(req: Pan115LoginRequest = None):
    """手动登录 115 网盘

    不传 body 时使用配置中的凭据。
    """
    # 如果请求体提供了凭据，临时覆盖配置
    if req and (req.cookies or req.token):
        cm = get_config_manager()
        current = cm.config
        if req.cookies:
            current.pan_115.cookies = req.cookies
        if req.token:
            current.pan_115.token = req.token
        cm.save()
        # 重置客户端以便重新建立连接（带新凭据）
        await pan_115_client.reset()

    ok = await pan_115_client.login()
    if not ok:
        raise HTTPException(status_code=401, detail="登录失败，请检查 Cookie / Token 是否有效")
    return {"ok": True, "msg": "登录成功"}


# ============== 离线下载任务 ==============

@router.get("/offline-tasks")
async def list_offline_tasks(
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(30, ge=1, le=100, description="每页数量"),
):
    """列出离线下载任务"""
    try:
        return await pan_115_client.list_offline_tasks(page=page, page_size=page_size)
    except Exception as e:
        logger.error(f"115 列离线任务失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


@router.post("/offline-tasks")
async def add_offline_task(req: AddOfflineTaskRequest):
    """添加离线下载任务（磁力链 / HTTP / ed2k）"""
    try:
        result = await pan_115_client.add_offline_task(req.magnet_url, req.target_cid)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message", "添加失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"115 添加离线任务失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


@router.delete("/offline-tasks/{task_id}")
async def cancel_offline_task(task_id: str):
    """取消（删除）离线下载任务"""
    try:
        return await pan_115_client.cancel_task(task_id)
    except Exception as e:
        logger.error(f"115 取消离线任务失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


# ============== 文件浏览 ==============

@router.get("/files")
async def list_files(
    folder_id: Optional[str] = Query(None, description="文件夹 CID（None 则使用根目录）"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出文件夹下的文件"""
    try:
        return await pan_115_client.list_files(folder_id=folder_id, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"115 列目录失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


# ============== 扫描文件夹 ==============

@router.post("/scan")
async def scan_folder(req: ScanRequest):
    """扫描文件夹下的所有文件（可选递归）"""
    try:
        files = await pan_115_client.scan_folder(
            folder_id=req.folder_id,
            recursive=req.recursive,
            max_depth=req.max_depth,
        )
        return {
            "folder_id": req.folder_id,
            "recursive": req.recursive,
            "max_depth": req.max_depth,
            "total": len(files),
            "files": files,
        }
    except Exception as e:
        logger.error(f"115 扫描失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


# ============== 文件搜索 ==============

@router.get("/files/search")
async def search_files(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    folder_id: Optional[str] = Query(None, description="起始文件夹 CID"),
):
    """在指定文件夹下搜索文件（含子目录）"""
    try:
        files = await pan_115_client.search_files(keyword, folder_id=folder_id)
        return {"total": len(files), "files": files}
    except Exception as e:
        logger.error(f"115 搜索文件失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


# ============== 文件下载与校验 ==============

@router.get("/files/{pickcode}/download-url")
async def get_download_url(pickcode: str):
    """获取文件下载直链（OSS URL，带过期时间）"""
    try:
        return await pan_115_client.get_download_url(pickcode)
    except Exception as e:
        logger.error(f"115 获取下载链接失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


@router.get("/files/{file_id}/sha1")
async def get_file_sha1(file_id: str):
    """获取文件 SHA1 校验值"""
    try:
        return await pan_115_client.get_file_sha1(file_id)
    except Exception as e:
        logger.error(f"115 获取 SHA1 失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


class MoveFileRequest(BaseModel):
    """移动文件请求"""
    file_ids: list[str] = Field(..., description="文件 fid 列表")
    target_cid: str = Field(..., description="目标文件夹 CID")


@router.post("/files/move")
async def move_files(req: MoveFileRequest):
    """移动文件到指定目录"""
    try:
        return await pan_115_client.move_file(req.file_ids, req.target_cid)
    except Exception as e:
        logger.error(f"115 移动文件失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


@router.get("/user-info")
async def get_user_info():
    """获取当前登录用户信息（空间使用、VIP 状态等）"""
    try:
        return await pan_115_client.get_user_info()
    except Exception as e:
        logger.error(f"115 获取用户信息失败: {e}")
        _msg = str(e)
        _code = 503 if ("未启用" in _msg or "未配置" in _msg or "未登录" in _msg) else 502
        raise HTTPException(status_code=_code, detail=_msg)


__all__ = ["router"]
