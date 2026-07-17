"""
模块管理 API 路由
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config.manager import get_config, get_config_manager
from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/modules", tags=["模块管理"])


SCANNER_MAP = {
    "chinese": ("app.tasks.chinese_scanner", "ChineseScanner"),
    "fc2": ("app.tasks.fc2_scanner", "Fc2Scanner"),
    "uncensored": ("app.tasks.uncensored_scanner", "UncensoredScanner"),
    "pornhub": ("app.tasks.pornhub_scanner", "PornhubScanner"),
    "western": ("app.tasks.western_scanner", "WesternScanner"),
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
        {"name": "jav", "enabled": True, "media_dirs": getattr(config.modules.jav, "media_dirs", [])},
        {"name": "uncensored", "enabled": getattr(config.modules.uncensored, "enabled", False),
         "media_dirs": getattr(config.modules.uncensored, "media_dirs", [])},
        {"name": "fc2", "enabled": getattr(config.modules.fc2, "enabled", False),
         "media_dirs": getattr(config.modules.fc2, "media_dirs", [])},
        {"name": "chinese", "enabled": getattr(config.modules.chinese, "enabled", False),
         "media_dirs": getattr(config.modules.chinese, "media_dirs", []),
         "actor_from_folder": getattr(config.modules.chinese, "actor_from_folder", False)},
        {"name": "pornhub", "enabled": getattr(config.modules.pornhub, "enabled", False),
         "media_dirs": getattr(config.modules.pornhub, "media_dirs", [])},
        {"name": "western", "enabled": getattr(config.modules.western, "enabled", False),
         "media_dirs": getattr(config.modules.western, "media_dirs", [])},
    ]


@router.get("/{module_name}/stats")
async def get_module_stats(module_name: str):
    """获取模块统计信息"""
    if module_name not in ["chinese", "uncensored", "fc2", "pornhub", "western"]:
        return {"name": module_name, "movie_count": 0, "actor_count": 0, "error": "未知模块"}

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()
    try:
        from sqlalchemy import select, func
        import importlib
        # 根据模块名动态加载对应的 Movie 和 Actor 模型
        model_map = {
            "chinese": ("app.db.chinese_models", "ChineseMovie", "ChineseActor"),
            "uncensored": ("app.db.uncensored_models", "UncensoredMovie", "UncensoredActor"),
            "fc2": ("app.db.fc2_models", "Fc2Movie", "Fc2Actor"),
            "pornhub": ("app.db.pornhub_models", "PornhubMovie", "PornhubActor"),
            "western": ("app.db.western_models", "WesternMovie", "WesternActor"),
        }
        mod_path, movie_cls, actor_cls = model_map[module_name]
        mod = importlib.import_module(mod_path)
        movie_model = getattr(mod, movie_cls)
        actor_model = getattr(mod, actor_cls) if hasattr(mod, actor_cls) else None

        movie_stmt = select(func.count()).select_from(movie_model.__table__)
        movie_count = (await session.execute(movie_stmt)).scalar() or 0

        actor_count = 0
        if actor_model:
            try:
                actor_stmt = select(func.count()).select_from(actor_model.__table__)
                actor_count = (await session.execute(actor_stmt)).scalar() or 0
            except Exception:
                pass

        return {"name": module_name, "movie_count": movie_count, "actor_count": actor_count}
    finally:
        await session.close()


@router.post("/{module_name}/scan")
async def scan_module(module_name: str):
    """触发模块扫描"""
    if module_name == "chinese":
        return await _run_scan("chinese")
    elif module_name in ("fc2", "uncensored", "pornhub", "western"):
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

    保存配置后会自动触发对应模块的扫描，无需重启服务端。
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

    # 自动触发已配置目录的模块扫描，用户无需再手动触发或重启
    _module_scan_tasks = []
    config = manager.config
    for mod_name in updates:
        if mod_name not in SCANNER_MAP:
            continue
        mod_cfg = getattr(config.modules, mod_name, None)
        if not mod_cfg:
            continue
        if not getattr(mod_cfg, "enabled", False):
            continue
        dirs = getattr(mod_cfg, "media_dirs", None) or []
        valid_dirs = [d for d in dirs if Path(d).exists()]
        if not valid_dirs:
            continue
        _module_scan_tasks.append(
            asyncio.create_task(_delayed_module_scan(mod_name, valid_dirs))
        )

    if _module_scan_tasks:
        logger.info(
            f"模块配置更新，已对 {len(_module_scan_tasks)} 个模块发起自动扫描: "
            + ", ".join(t.get_name() or str(id(t)) for t in _module_scan_tasks)
        )

    return {"status": "ok", "config": manager.config.modules.model_dump()}


async def _delayed_module_scan(module_name: str, media_dirs: list[str]) -> None:
    """延迟执行模块扫描（给配置写入一点时间缓冲）"""
    await asyncio.sleep(1)
    try:
        module_path, class_name = SCANNER_MAP[module_name]
        import importlib
        mod = importlib.import_module(module_path)
        scanner_cls = getattr(mod, class_name)
        scanner = scanner_cls(media_dirs)
        result = await scanner.scan()
        added = result.get("movies_added", 0)
        total = result.get("total", 0)
        logger.info(f"模块 [{module_name}] 自动扫描完成: 共发现 {total} 个文件，新增 {added} 条记录")
    except Exception as e:
        logger.warning(f"模块 [{module_name}] 自动扫描失败: {e}")


@router.patch("/{module_name}/toggle")
async def toggle_module(module_name: str, enabled: bool = True):
    """切换模块启用状态"""
    if module_name not in ("jav", "uncensored", "fc2", "chinese", "pornhub", "western"):
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


# ===== 跨模块聚合查询 =====

_MODEL_MAP = {
    "chinese": ("app.db.chinese_models", "ChineseMovie"),
    "uncensored": ("app.db.uncensored_models", "UncensoredMovie"),
    "fc2": ("app.db.fc2_models", "Fc2Movie"),
    "pornhub": ("app.db.pornhub_models", "PornhubMovie"),
    "western": ("app.db.western_models", "WesternMovie"),
}


@router.get("/unified/movies")
async def unified_list_movies(module_name: str = Query(None, description="按模块筛选，不传则返回全部"),
                              skip: int = 0, limit: int = 20):
    """跨模块聚合影片列表

    支持按 module_name 筛选单个模块，或不传参数返回所有模块聚合结果。
    每个影片记录附带 module_name 字段标识来源。
    """
    all_items = []
    modules_to_query = [module_name] if module_name else list(_MODEL_MAP.keys())

    for mod_name in modules_to_query:
        if mod_name not in _MODEL_MAP:
            continue
        db = ModuleDatabase.get_instance(mod_name)
        session = await db.get_session()
        try:
            import importlib
            model_path, model_class = _MODEL_MAP[mod_name]
            mod = importlib.import_module(model_path)
            model = getattr(mod, model_class)

            from sqlalchemy import select
            stmt = select(model).order_by(model.created_at.desc()).offset(skip).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            for r in rows:
                all_items.append({
                    "id": r.id,
                    "module_name": mod_name,
                    "code": getattr(r, "code", None),
                    "title": getattr(r, "title", None),
                    "cover_url": getattr(r, "cover_url", None),
                    "actor": getattr(r, "actor", None),
                    "file_path": getattr(r, "file_path", None),
                    "status": getattr(r, "status", "pending"),
                    "created_at": str(getattr(r, "created_at", "")),
                })
        finally:
            await session.close()

    # 按创建时间排序后截取
    all_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(all_items)
    return {"total": total, "items": all_items[skip: skip + limit]}


@router.get("/unified/search")
async def unified_search(keyword: str = Query(..., min_length=1), limit: int = 50):
    """跨模块全局搜索

    在所有已启用模块中搜索 keyword（匹配番号或标题）
    """
    results = []
    config = get_config()
    # 检查各模块是否启用
    enabled_map = {
        "chinese": getattr(config.modules, "chinese", None),
        "uncensored": getattr(config.modules, "uncensored", None),
        "fc2": getattr(config.modules, "fc2", None),
        "pornhub": getattr(config.modules, "pornhub", None),
        "western": getattr(config.modules, "western", None),
    }

    for mod_name, mod_config in enabled_map.items():
        if mod_name not in _MODEL_MAP:
            continue
        if mod_config is not None and getattr(mod_config, "enabled", True) is False:
            continue

        db = ModuleDatabase.get_instance(mod_name)
        session = await db.get_session()
        try:
            import importlib
            model_path, model_class = _MODEL_MAP[mod_name]
            mod = importlib.import_module(model_path)
            model = getattr(mod, model_class)

            from sqlalchemy import select, or_
            stmt = select(model).where(
                or_(
                    getattr(model, "code", "").like(f"%{keyword}%"),
                    getattr(model, "title", "").like(f"%{keyword}%"),
                )
            ).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            for r in rows:
                results.append({
                    "id": r.id,
                    "module_name": mod_name,
                    "code": getattr(r, "code", None),
                    "title": getattr(r, "title", None),
                    "cover_url": getattr(r, "cover_url", None),
                    "status": getattr(r, "status", "pending"),
                })
        finally:
            await session.close()

    return {"total": len(results), "items": results}
