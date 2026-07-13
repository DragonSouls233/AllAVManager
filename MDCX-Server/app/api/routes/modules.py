"""
模块管理 API 路由
"""

from fastapi import APIRouter

from app.config.manager import get_config
from app.db.module_db import ModuleDatabase

router = APIRouter(prefix="/api/v1/modules", tags=["模块管理"])


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
        from app.tasks.chinese_scanner import ChineseScanner
        from app.config.manager import get_config
        config = get_config()
        scanner = ChineseScanner(config.chinese.media_dirs)
        return await scanner.scan()

    return {"module": module_name, "message": "扫描功能待实现"}
