"""
模块管理 API 路由
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.config.manager import get_config, get_config_manager
from app.db.module_db import ModuleDatabase

router = APIRouter(prefix="/api/v1/modules", tags=["模块管理"])


SCANNER_MAP = {
    "chinese": ("app.tasks.chinese_scanner", "ChineseScanner"),
    "fc2": ("app.tasks.fc2_scanner", "Fc2Scanner"),
    "uncensored": ("app.tasks.uncensored_scanner", "UncensoredScanner"),
    "pornhub": ("app.tasks.pornhub_scanner", "PornhubScanner"),
}


async def _run_scan(module_name: str) -> dict:
    """根据模块名动态导入并执行扫描器"""
    if module_name not in SCANNER_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    config = get_config()
    module_config = getattr(config.modules, module_name, None)
    if not module_config:
        raise HTTPException(status_code=400, detail=f"未找到模块配置: {module_name}")

    media_dirs = getattr(module_config, "media_dirs", [])
    if not media_dirs:
        raise HTTPException(status_code=400, detail=f"模块 {module_name} 未配置媒体目录")

    module_path, class_name = SCANNER_MAP[module_name]
    import importlib
    mod = importlib.import_module(module_path)
    scanner_cls = getattr(mod, class_name)
    scanner = scanner_cls(media_dirs)
    return await scanner.scan()


@router.get("")
async def list_modules():
    """列出所有模块及其状态"""
    config = get_config()
    return [
        {"name": "jav", "enabled": True, "media_dirs": config.jav.media_dirs},
        {"name": "uncensored", "enabled": config.uncensored.enabled,
         "media_dirs": config.uncensored.media_dirs},
        {"name": "fc2", "enabled": config.fc2.enabled,
         "media_dirs": config.fc2.media_dirs},
        {"name": "chinese", "enabled": config.chinese.enabled,
         "media_dirs": config.chinese.media_dirs,
         "actor_from_folder": config.chinese.actor_from_folder},
        {"name": "pornhub", "enabled": config.pornhub.enabled,
         "media_dirs": config.pornhub.media_dirs},
    ]


@router.get("/{module_name}/stats")
async def get_module_stats(module_name: str):
    """获取模块统计信息"""
    if module_name not in ["chinese", "uncensored", "fc2", "pornhub"]:
        return {"name": module_name, "movie_count": 0, "actor_count": 0, "error": "未知模块"}

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()
    try:
        from sqlalchemy import select, func
        from app.db.module_db import ModuleBase
        if not hasattr(ModuleBase, "metadata"):
            return {"name": module_name, "movie_count": 0, "actor_count": 0}

        movie_stmt = select(func.count()).select_from(
            ModuleBase.metadata.tables["movies"]
        ) if "movies" in ModuleBase.metadata.tables else None
        actor_stmt = select(func.count()).select_from(
            ModuleBase.metadata.tables["actors"]
        ) if "actors" in ModuleBase.metadata.tables else None

        movie_count = (await session.execute(movie_stmt)).scalar() if movie_stmt else 0
        actor_count = (await session.execute(actor_stmt)).scalar() if actor_stmt else 0

        return {"name": module_name, "movie_count": movie_count, "actor_count": actor_count}
    finally:
        await session.close()


@router.post("/{module_name}/scan")
async def scan_module(module_name: str):
    """触发模块扫描"""
    if module_name == "chinese":
        return await _run_scan("chinese")
    elif module_name in ("fc2", "uncensored", "pornhub"):
        return await _run_scan(module_name)
    return {"module": module_name, "message": "扫描功能待实现"}


@router.get("/config")
async def get_modules_config():
    """获取 modules 配置"""
    config = get_config()
    return config.modules.model_dump()


@router.put("/config")
async def update_modules_config(updates: dict[str, Any]):
    """更新 modules 配置（嵌套在 modules 前缀下）

    支持部分更新，例如：
    {"chinese": {"enabled": true, "media_dirs": ["/path/to/videos"]}}
    {"fc2": {"enabled": false}}
    """
    manager = get_config_manager()

    def _mutator(cfg: dict[str, Any]) -> None:
        if "modules" not in cfg:
            cfg["modules"] = {}
        for module_name, mod_updates in updates.items():
            if module_name not in cfg["modules"]:
                cfg["modules"][module_name] = {}
            if isinstance(mod_updates, dict):
                cfg["modules"][module_name].update(mod_updates)
            else:
                cfg["modules"][module_name] = mod_updates

    errors = manager.mutate_config(_mutator)
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    return {"status": "ok", "config": manager.config.modules.model_dump()}


@router.patch("/{module_name}/toggle")
async def toggle_module(module_name: str, enabled: bool = True):
    """切换模块启用状态"""
    if module_name not in ("jav", "uncensored", "fc2", "chinese", "pornhub"):
        raise HTTPException(status_code=400, detail=f"未知模块: {module_name}")

    manager = get_config_manager()

    def _mutator(cfg: dict[str, Any]) -> None:
        if "modules" not in cfg:
            cfg["modules"] = {}
        if module_name not in cfg["modules"]:
            cfg["modules"][module_name] = {}
        cfg["modules"][module_name]["enabled"] = enabled

    errors = manager.mutate_config(_mutator)
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    return {"status": "ok", "module": module_name, "enabled": enabled}
