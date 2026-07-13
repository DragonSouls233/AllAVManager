"""
自动备份管理路由

API 端点：
- POST /api/v1/backup/create        — 立即创建备份
- GET  /api/v1/backup/list           — 列出所有备份
- GET  /api/v1/backup/stats          — 备份统计
- POST /api/v1/backup/{name}/restore — 从备份恢复
- DELETE /api/v1/backup/{name}       — 删除备份
- GET  /api/v1/backup/download/{name} — 下载备份文件
- GET  /api/v1/backup/config        — 获取备份配置
- PUT  /api/v1/backup/config        — 更新备份配置
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config.manager import get_config, get_config_manager
from app.services.backup import backup_service

router = APIRouter()


class CreateBackupRequest(BaseModel):
    """创建备份请求"""
    note: str = Field(default="", title="备份备注")


class BackupConfigUpdate(BaseModel):
    """备份配置更新"""
    enabled: bool | None = Field(default=None, title="启用自动备份")
    interval: str | None = Field(default=None, title="备份频率")
    schedule_time: str | None = Field(default=None, title="执行时间")
    schedule_day: int | None = Field(default=None, title="执行日期")
    max_backups: int | None = Field(default=None, title="最大保留数")
    backup_database: bool | None = Field(default=None, title="备份数据库")
    backup_config: bool | None = Field(default=None, title="备份配置")
    backup_logs: bool | None = Field(default=None, title="备份日志")
    compress: bool | None = Field(default=None, title="压缩备份")
    backup_dir: str | None = Field(default=None, title="备份目录")


@router.post("/create")
async def create_backup(req: CreateBackupRequest = None):
    """立即创建备份"""
    if req is None:
        req = CreateBackupRequest()
    try:
        result = await backup_service.create_backup(note=req.note)
        return {"ok": True, "backup": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建备份失败: {e}")


@router.get("/list")
async def list_backups():
    """列出所有备份"""
    return {"backups": backup_service.list_backups()}


@router.get("/stats")
async def backup_stats():
    """备份统计"""
    return backup_service.get_backup_stats()


@router.post("/{name}/restore")
async def restore_backup(name: str):
    """从备份恢复"""
    try:
        result = await backup_service.restore_backup(name)
        return {"ok": True, "result": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复失败: {e}")


@router.delete("/{name}")
async def delete_backup(name: str):
    """删除备份"""
    deleted = backup_service.delete_backup(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="备份不存在")
    return {"ok": True, "deleted": name}


@router.get("/download/{name}")
async def download_backup(name: str):
    """下载备份文件"""
    from pathlib import Path
    from app.config.manager import get_config_manager

    manager = get_config_manager()
    backup_dir = manager.computed.backups_dir
    file_path = backup_dir / name

    # 安全检查
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="备份不存在")
    if not str(file_path.resolve()).startswith(str(backup_dir.resolve())):
        raise HTTPException(status_code=400, detail="路径越界")

    if file_path.is_file():
        return FileResponse(str(file_path), filename=name)
    else:
        # 目录 → 打包下载
        import tempfile
        import tarfile
        tmp = Path(tempfile.mktemp(suffix=".tar.gz"))
        with tarfile.open(str(tmp), "w:gz") as tar:
            tar.add(str(file_path), arcname=name)
        return FileResponse(str(tmp), filename=f"{name}.tar.gz")


@router.get("/config")
async def get_backup_config():
    """获取备份配置"""
    cfg = get_config().backup
    return cfg.model_dump()


@router.put("/config")
async def update_backup_config(req: BackupConfigUpdate):
    """更新备份配置

    2026-07-08 修复:确保配置变更立即生效(原版 setattr 后 save + 调度器重启,
    但如果用户没在启动前 enabled,首次保存后 stop_scheduled → start_scheduled
    仍可能因 _scheduler is None 而不启动新调度器——现在改成"先 stop,无条件 restart")。
    """
    from app.config.manager import get_config, get_config_manager
    config = get_config()
    changes = req.model_dump(exclude_none=True)

    # 应用变更（in-place 改 Pydantic 嵌套实例）
    backup_cfg = config.backup
    for key, value in changes.items():
        setattr(backup_cfg, key, value)

    # 持久化到 config.yaml
    get_config_manager().save()

    # 强制重启调度器：无论之前 enabled 与否,都重置
    # 这样保证前端关掉 enabled=true 开关 → false 后,旧调度器被关掉
    backup_service.stop_scheduled()
    if backup_cfg.enabled:
        backup_service.start_scheduled()
    logger.info(f"备份配置已更新并重启调度器: enabled={backup_cfg.enabled}, interval={backup_cfg.interval}, max_backups={backup_cfg.max_backups}")

    return {"ok": True, "config": backup_cfg.model_dump(), "changes": changes}
