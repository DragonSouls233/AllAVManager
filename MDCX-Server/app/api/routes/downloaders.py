"""下载器统一路由（§7.11）

对接 qBittorrent / Transmission / Aria2 三种下载器，对外提供统一 RESTful API：
- 配置管理（激活下载器 / 各下载器子配置）
- 连接状态查询
- 任务列表 / 添加任务 / 取消任务 / 暂停 / 恢复
- 测试连接

参考 cloud_drive2.py / pan_115.py 路由的实现风格。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config.manager import get_config, get_config_manager
from app.services.downloader_manager import downloader_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Pydantic 模型 ==============

class QBittorrentConfigUpdate(BaseModel):
    """qBittorrent 配置更新"""
    enabled: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None  # *** 或空字符串不更新
    verify_ssl: Optional[bool] = None
    download_dir: Optional[str] = None


class TransmissionConfigUpdate(BaseModel):
    """Transmission 配置更新"""
    enabled: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    use_ssl: Optional[bool] = None
    rpc_path: Optional[str] = None
    download_dir: Optional[str] = None


class Aria2ConfigUpdate(BaseModel):
    """Aria2 配置更新"""
    enabled: Optional[bool] = None
    rpc_url: Optional[str] = None
    secret: Optional[str] = None  # *** 或空字符串不更新
    download_dir: Optional[str] = None


class DownloaderConfigUpdate(BaseModel):
    """下载器统一配置更新请求"""
    active: Optional[str] = None
    qbittorrent: Optional[QBittorrentConfigUpdate] = None
    transmission: Optional[TransmissionConfigUpdate] = None
    aria2: Optional[Aria2ConfigUpdate] = None


class AddTaskRequest(BaseModel):
    """添加下载任务请求"""
    url: str = Field(..., description="磁力链接 / HTTP 种子 URL")
    download_dir: Optional[str] = Field(None, description="下载目录（None 用默认）")
    name: Optional[str] = Field(None, description="任务名称（可选）")


class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    type: str = Field(..., description="下载器类型：qbittorrent / transmission / aria2")


# ============== 配置管理 ==============

@router.get("/config")
async def get_downloader_config():
    """获取所有下载器配置"""
    cfg = get_config().downloader
    qb = cfg.qbittorrent
    tr = cfg.transmission
    ar = cfg.aria2
    return {
        "active": cfg.active,
        "available": downloader_manager.list_available(),
        "qbittorrent": {
            "enabled": qb.enabled,
            "host": qb.host,
            "port": qb.port,
            "username": qb.username,
            "password": "***" if qb.password else "",
            "verify_ssl": qb.verify_ssl,
            "download_dir": qb.download_dir or "",
        },
        "transmission": {
            "enabled": tr.enabled,
            "host": tr.host,
            "port": tr.port,
            "username": tr.username,
            "password": "***" if tr.password else "",
            "use_ssl": tr.use_ssl,
            "rpc_path": tr.rpc_path,
            "download_dir": tr.download_dir or "",
        },
        "aria2": {
            "enabled": ar.enabled,
            "rpc_url": ar.rpc_url,
            "secret": "***" if ar.secret else "",
            "download_dir": ar.download_dir or "",
        },
    }


@router.put("/config")
async def update_downloader_config(req: DownloaderConfigUpdate):
    """更新下载器配置"""
    cm = get_config_manager()
    current = cm.config
    cfg = current.downloader

    if req.active is not None:
        # 校验 active 取值
        if req.active and req.active not in ("qbittorrent", "transmission", "aria2"):
            raise HTTPException(status_code=400, detail="active 必须为 qbittorrent / transmission / aria2 之一")
        cfg.active = req.active

    # qBittorrent
    if req.qbittorrent is not None:
        qb = cfg.qbittorrent
        u = req.qbittorrent
        if u.enabled is not None:
            qb.enabled = u.enabled
        if u.host is not None:
            qb.host = u.host
        if u.port is not None:
            qb.port = u.port
        if u.username is not None:
            qb.username = u.username
        if u.password is not None and u.password != "" and u.password != "***":
            qb.password = u.password
        if u.verify_ssl is not None:
            qb.verify_ssl = u.verify_ssl
        if u.download_dir is not None:
            qb.download_dir = u.download_dir or None

    # Transmission
    if req.transmission is not None:
        tr = cfg.transmission
        u = req.transmission
        if u.enabled is not None:
            tr.enabled = u.enabled
        if u.host is not None:
            tr.host = u.host
        if u.port is not None:
            tr.port = u.port
        if u.username is not None:
            tr.username = u.username
        if u.password is not None and u.password != "" and u.password != "***":
            tr.password = u.password
        if u.use_ssl is not None:
            tr.use_ssl = u.use_ssl
        if u.rpc_path is not None:
            tr.rpc_path = u.rpc_path
        if u.download_dir is not None:
            tr.download_dir = u.download_dir or None

    # Aria2
    if req.aria2 is not None:
        ar = cfg.aria2
        u = req.aria2
        if u.enabled is not None:
            ar.enabled = u.enabled
        if u.rpc_url is not None:
            ar.rpc_url = u.rpc_url
        if u.secret is not None and u.secret != "" and u.secret != "***":
            ar.secret = u.secret
        if u.download_dir is not None:
            ar.download_dir = u.download_dir or None

    cm.save()

    # 配置更新后，重置已创建的实例（让后续请求懒加载新配置）
    await downloader_manager.close_all()
    return {"ok": True, "msg": "配置已保存"}


# ============== 状态 & 任务 ==============

def _require_active():
    """获取激活下载器实例；不存在则抛 400"""
    inst = downloader_manager.get_active()
    if inst is None:
        raise HTTPException(status_code=400, detail="未配置激活的下载器，请先在配置中启用并选择一个下载器")
    return inst


@router.get("/status")
async def get_downloader_status():
    """获取激活下载器的状态"""
    inst = _require_active()
    try:
        return await inst.get_status()
    except Exception as e:
        logger.error(f"获取下载器状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_downloader_tasks(
    status: Optional[str] = Query(None, description="按状态过滤：pending/downloading/seeding/completed/paused/error"),
):
    """获取任务列表"""
    inst = _require_active()
    try:
        return await inst.list_tasks(status=status)
    except Exception as e:
        logger.error(f"列任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks")
async def add_downloader_task(req: AddTaskRequest):
    """添加下载任务（磁力链 / HTTP 种子 URL）"""
    inst = _require_active()
    try:
        task_id = await inst.add_torrent(req.url, download_dir=req.download_dir, name=req.name)
        return {"ok": True, "task_id": task_id, "msg": "任务已添加"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def cancel_downloader_task(task_id: str):
    """取消（删除）任务"""
    inst = _require_active()
    try:
        ok = await inst.cancel_task(task_id)
        if not ok:
            raise HTTPException(status_code=400, detail="取消任务失败")
        return {"ok": True, "msg": "任务已取消"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/pause")
async def pause_downloader_task(task_id: str):
    """暂停任务"""
    inst = _require_active()
    try:
        ok = await inst.pause_task(task_id)
        if not ok:
            raise HTTPException(status_code=400, detail="暂停任务失败")
        return {"ok": True, "msg": "任务已暂停"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/resume")
async def resume_downloader_task(task_id: str):
    """恢复任务"""
    inst = _require_active()
    try:
        ok = await inst.resume_task(task_id)
        if not ok:
            raise HTTPException(status_code=400, detail="恢复任务失败")
        return {"ok": True, "msg": "任务已恢复"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== 测试连接 ==============

@router.post("/test")
async def test_downloader_connection(req: TestConnectionRequest):
    """测试下载器连接

    临时按配置创建下载器实例并尝试登录/连接，结果以 ok 返回。
    """
    name = req.type
    if name not in ("qbittorrent", "transmission", "aria2"):
        raise HTTPException(status_code=400, detail="type 必须为 qbittorrent / transmission / aria2 之一")

    # 使用已存在的实例或新建临时实例
    inst = downloader_manager.get_downloader(name)
    if inst is None:
        raise HTTPException(status_code=400, detail=f"无法创建下载器实例: {name}")

    # 关闭旧连接，强制使用最新配置
    try:
        await inst.close()
    except Exception:
        pass

    try:
        await inst.start()
        status = await inst.get_status()
        ok = bool(status.get("connected"))
        return {
            "ok": ok,
            "type": name,
            "connected": ok,
            "status": status,
            "msg": "连接成功" if ok else "连接失败（请检查配置）",
        }
    except Exception as e:
        logger.error(f"测试下载器 [{name}] 连接失败: {e}")
        return {
            "ok": False,
            "type": name,
            "connected": False,
            "msg": str(e),
        }


__all__ = ["router"]
