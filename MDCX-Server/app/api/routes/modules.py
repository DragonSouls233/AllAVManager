"""
模块管理 API 路由
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from app.config.manager import get_config, get_config_manager
from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/modules", tags=["模块管理"])


SCANNER_MAP = {
    "chinese": ("app.tasks.chinese_scanner", "ChineseScanner"),
    "fc2": ("app.tasks.fc2_scanner", "Fc2Scanner"),
    "jav": ("app.tasks.jav_scanner", "JavScanner"),
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
    # 所有注册在 SCANNER_MAP 中的模块都走统一扫描流程
    if module_name in SCANNER_MAP:
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
    "chinese": ("app.db.chinese_models", "ChineseMovie", "ChineseActor"),
    "uncensored": ("app.db.uncensored_models", "UncensoredMovie", "UncensoredActor"),
    "fc2": ("app.db.fc2_models", "Fc2Movie", "Fc2Actor"),
    "pornhub": ("app.db.pornhub_models", "PornhubMovie", "PornhubActor"),
    "western": ("app.db.western_models", "WesternMovie", "WesternActor"),
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
            model_path, model_class, _ = _MODEL_MAP[mod_name]
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
            model_path, model_class, _ = _MODEL_MAP[mod_name]
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


@router.get("/{module_name}/actors")
async def get_module_actors(
    module_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """获取模块演员列表"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()
    try:
        import importlib
        model_path, _, actor_class = _MODEL_MAP[module_name]
        
        if not actor_class:
            return {"total": 0, "items": []}
        
        mod = importlib.import_module(model_path)
        actor_model = getattr(mod, actor_class)
        
        from sqlalchemy import select, func
        stmt = select(actor_model).order_by(actor_model.movie_count.desc())
        
        result = await session.execute(stmt)
        actors = result.scalars().all()
        
        total = len(actors)
        skip = (page - 1) * page_size
        items = actors[skip:skip + page_size]
        
        return {
            "total": total,
            "items": [
                {
                    "id": a.id,
                    "name": a.name,
                    "alias": a.alias,
                    "avatar_url": a.avatar_url,
                    "source": a.source,
                    "movie_count": a.movie_count,
                }
                for a in items
            ]
        }
    finally:
        await session.close()


@router.get("/{module_name}/actors/{actor_id}/avatar/file")
async def get_module_actor_avatar_file(module_name: str, actor_id: int):
    """获取模块演员头像文件"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()
    try:
        import importlib
        model_path, _, actor_class = _MODEL_MAP[module_name]
        
        if not actor_class:
            raise HTTPException(status_code=404, detail="模块不支持演员")
        
        mod = importlib.import_module(model_path)
        actor_model = getattr(mod, actor_class)
        
        from sqlalchemy import select
        stmt = select(actor_model).where(actor_model.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        
        avatar_url = actor.avatar_url
        if not avatar_url:
            raise HTTPException(status_code=404, detail="演员无头像")
        
        # 如果是本地文件路径，读取并返回
        if avatar_url.startswith(("http://", "https://")):
            import httpx
            resp = httpx.get(avatar_url, timeout=30)
            return Response(
                content=resp.content,
                media_type=resp.headers.get("content-type", "image/jpeg"),
                headers={"Content-Disposition": f'inline; filename="actor_{actor_id}.jpg"'}
            )
        else:
            # 本地文件
            from pathlib import Path
            avatar_path = Path(avatar_url)
            if avatar_path.exists():
                return Response(
                    content=avatar_path.read_bytes(),
                    media_type="image/jpeg",
                    headers={"Content-Disposition": f'inline; filename="actor_{actor_id}.jpg"'}
                )
            else:
                raise HTTPException(status_code=404, detail="头像文件不存在")
    finally:
        await session.close()


@router.post("/{module_name}/actors/avatar-scrape/start")
async def start_module_actor_avatar_scrape(
    background_tasks: BackgroundTasks,
    module_name: str,
    min_movies: int = Query(1, ge=1, description="最少作品数"),
):
    """启动模块演员头像刮削"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")
    
    from app.scraper.module_actor_avatar import run_module_avatar_scrape_job
    
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:6]}"
    background_tasks.add_task(run_module_avatar_scrape_job, job_id, module_name, min_movies)
    
    return {
        "status": "started",
        "job_id": job_id,
        "message": f"模块 {module_name} 头像刮削已启动",
    }


@router.get("/{module_name}/actors/avatar-scrape/status/{job_id}")
async def get_module_actor_avatar_scrape_status(module_name: str, job_id: str):
    """获取模块演员头像刮削任务状态"""
    from app.scraper.module_actor_avatar import get_module_avatar_job_status
    
    status = get_module_avatar_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return status


@router.get("/{module_name}/actors/avatar-scrape/preview")
async def preview_module_actor_avatar_scrape(
    module_name: str,
    min_movies: int = Query(1, ge=1),
):
    """预览需要补充头像的演员列表"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")
    
    from app.scraper.module_actor_avatar import ModuleActorAvatarScraper
    
    scraper = ModuleActorAvatarScraper(module_name=module_name, min_movies=min_movies)
    actors = await scraper._find_actors_without_avatar()
    
    return {
        "count": len(actors),
        "module": module_name,
        "actors": [
            {
                "id": a.id,
                "name": a.name,
                "movie_count": a.movie_count,
            }
            for a in actors[:20]
        ]
    }


# ===== 模块演员同步与刮削 API =====


@router.post("/{module_name}/actors/sync")
async def sync_module_actors(module_name: str):
    """从影片记录同步演员到 Actor 表"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    from app.scraper.module_actor_sync import sync_actors_from_movies

    try:
        result = await sync_actors_from_movies(module_name)
        return {"status": "ok", "module": module_name, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{module_name}/actors/{actor_id}/scrape-profile")
async def scrape_module_actor_profile(module_name: str, actor_id: int):
    """刮削单个演员的个人资料"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()
    try:
        import importlib
        model_path, _, actor_class = _MODEL_MAP[module_name]
        mod = importlib.import_module(model_path)
        actor_model = getattr(mod, actor_class)

        from sqlalchemy import select
        stmt = select(actor_model).where(actor_model.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()

        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        actor_name = actor.name
    finally:
        await session.close()

    # 使用模块资料刮削器
    from app.scraper.module_actor_profile import get_module_actor_profile_scraper
    scraper = get_module_actor_profile_scraper(module_name)
    profile = await scraper.get_profile(actor_name)

    if not profile:
        return {"status": "not_found", "message": f"未找到 {actor_name} 的个人资料"}

    # 更新数据库
    session2 = await db.get_session()
    try:
        import importlib
        model_path, _, actor_class = _MODEL_MAP[module_name]
        mod = importlib.import_module(model_path)
        actor_model = getattr(mod, actor_class)

        from sqlalchemy import select
        stmt = select(actor_model).where(actor_model.id == actor_id)
        result = await session2.execute(stmt)
        db_actor = result.scalar_one_or_none()

        if not db_actor:
            return {"status": "error", "message": "演员记录已不存在"}

        # 更新字段
        if profile.alias and not db_actor.alias:
            db_actor.alias = profile.alias
        if profile.avatar_url and not getattr(db_actor, "avatar_url", None):
            db_actor.avatar_url = profile.avatar_url

        # Western 模块特有字段
        if module_name == "western":
            if profile.birth_date:
                db_actor.birthdate = profile.birth_date
            if profile.country:
                db_actor.country = profile.country
            if profile.ethnicity:
                db_actor.ethnicity = profile.ethnicity
            if profile.measurements:
                db_actor.measurements = profile.measurements
            if profile.height:
                db_actor.height = str(profile.height)
            if profile.weight:
                db_actor.weight = profile.weight
            if profile.gender:
                db_actor.gender = profile.gender
            if profile.twitter:
                db_actor.twitter = profile.twitter
            if profile.instagram:
                db_actor.instagram = profile.instagram

        # PORNHub 模块：补充国籍
        if module_name == "pornhub" and profile.country and not getattr(db_actor, "nationality", None):
            db_actor.nationality = profile.country

        db_actor.source = profile.source
        await session2.commit()

        return {
            "status": "ok",
            "actor_id": actor_id,
            "name": actor_name,
            "profile": {
                "name": profile.name,
                "alias": profile.alias,
                "avatar_url": profile.avatar_url,
                "birth_date": profile.birth_date,
                "height": profile.height,
                "bust": profile.bust,
                "waist": profile.waist,
                "hip": profile.hip,
                "cup": profile.cup,
                "birthplace": profile.birthplace,
                "country": profile.country,
                "ethnicity": profile.ethnicity,
                "measurements": profile.measurements,
                "weight": profile.weight,
                "gender": profile.gender,
                "source": profile.source,
            }
        }
    finally:
        await session2.close()


@router.post("/{module_name}/actors/scrape-profiles")
async def batch_scrape_module_actor_profiles(
    background_tasks: BackgroundTasks,
    module_name: str,
    min_movies: int = Query(1, ge=1, description="最少作品数"),
    limit: int = Query(50, ge=1, le=200, description="最多刮削数"),
):
    """批量刮削模块演员个人资料（后台任务）"""
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    job_id = f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    from app.scraper.module_actor_profile import get_module_actor_profile_scraper
    scraper = get_module_actor_profile_scraper(module_name)

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()
    try:
        import importlib
        model_path, _, actor_class = _MODEL_MAP[module_name]
        mod = importlib.import_module(model_path)
        actor_model = getattr(mod, actor_class)

        from sqlalchemy import select
        stmt = select(actor_model).where(
            actor_model.movie_count >= min_movies
        ).order_by(actor_model.movie_count.desc()).limit(limit)

        result = await session.execute(stmt)
        actors_to_scrape = result.scalars().all()
    finally:
        await session.close()

    if not actors_to_scrape:
        return {"status": "ok", "message": "没有需要刮削的演员", "total": 0}

    # 后台执行
    async def _run_batch():
        logger.info(f"[{module_name}] 批量演员资料刮削启动: {len(actors_to_scrape)} 人")
        success = 0
        failed = 0
        for actor in actors_to_scrape:
            try:
                profile = await scraper.get_profile(actor.name)
                if profile:
                    # 更新数据库
                    s = await db.get_session()
                    try:
                        mod2 = importlib.import_module(model_path)
                        am = getattr(mod2, actor_class)
                        st = select(am).where(am.id == actor.id)
                        r = await s.execute(st)
                        a = r.scalar_one_or_none()
                        if a:
                            if profile.alias and not a.alias:
                                a.alias = profile.alias
                            if profile.avatar_url and not getattr(a, "avatar_url", None):
                                a.avatar_url = profile.avatar_url
                            if module_name == "western":
                                if profile.birth_date:
                                    a.birthdate = profile.birth_date
                                if profile.country:
                                    a.country = profile.country
                                if profile.measurements:
                                    a.measurements = profile.measurements
                                if profile.height:
                                    a.height = str(profile.height)
                            a.source = profile.source
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"[{module_name}] 刮削 {actor.name} 失败: {e}")
                failed += 1
            await asyncio.sleep(1.0)
        logger.info(f"[{module_name}] 批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run_batch)

    return {
        "status": "started",
        "job_id": job_id,
        "total": len(actors_to_scrape),
        "message": f"模块 {module_name} 演员资料批量刮削已启动，共 {len(actors_to_scrape)} 人",
    }


@router.post("/{module_name}/actors/batch-scrape")
async def batch_scrape_module_actors(
    background_tasks: BackgroundTasks,
    module_name: str,
):
    """一键批量操作：同步演员 → 刮削资料 → 下载头像

    整合 sync + profile scrape + avatar scrape 三个步骤
    """
    if module_name not in _MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的模块: {module_name}")

    job_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    async def _run_batch():
        # Step 1: Sync actors from movies
        logger.info(f"[{module_name}] 批量操作 Step 1/3: 同步演员")
        from app.scraper.module_actor_sync import sync_actors_from_movies
        try:
            sync_result = await sync_actors_from_movies(module_name)
            logger.info(f"[{module_name}] 同步完成: {sync_result}")
        except Exception as e:
            logger.error(f"[{module_name}] 同步失败: {e}")

        # Step 2: Scrape profiles
        logger.info(f"[{module_name}] 批量操作 Step 2/3: 刮削资料")
        from app.scraper.module_actor_profile import get_module_actor_profile_scraper
        scraper = get_module_actor_profile_scraper(module_name)

        db = ModuleDatabase.get_instance(module_name)
        session = await db.get_session()
        try:
            import importlib
            model_path, _, actor_class = _MODEL_MAP[module_name]
            mod = importlib.import_module(model_path)
            actor_model = getattr(mod, actor_class)

            from sqlalchemy import select
            stmt = select(actor_model).where(actor_model.movie_count >= 1).order_by(actor_model.movie_count.desc()).limit(50)
            result = await session.execute(stmt)
            actors = result.scalars().all()
        finally:
            await session.close()

        profile_success = 0
        for actor in actors[:50]:
            try:
                profile = await scraper.get_profile(actor.name)
                if profile:
                    s = await db.get_session()
                    try:
                        mod2 = importlib.import_module(model_path)
                        am = getattr(mod2, actor_class)
                        st = select(am).where(am.id == actor.id)
                        r = await s.execute(st)
                        a = r.scalar_one_or_none()
                        if a:
                            if profile.avatar_url and not getattr(a, "avatar_url", None):
                                a.avatar_url = profile.avatar_url
                            if module_name == "western":
                                if profile.birth_date:
                                    a.birthdate = profile.birth_date
                                if profile.country:
                                    a.country = profile.country
                                if profile.measurements:
                                    a.measurements = profile.measurements
                            a.source = profile.source
                            await s.commit()
                            profile_success += 1
                    finally:
                        await s.close()
            except Exception:
                pass
            await asyncio.sleep(0.5)

        # Step 3: Download avatars
        logger.info(f"[{module_name}] 批量操作 Step 3/3: 下载头像")
        from app.scraper.module_actor_avatar import ModuleActorAvatarScraper
        avatar_scraper = ModuleActorAvatarScraper(module_name=module_name, min_movies=1)
        try:
            avatar_result = await avatar_scraper.scrape_all()
            logger.info(f"[{module_name}] 头像下载完成: {avatar_result.get('success', 0)}")
        except Exception as e:
            logger.error(f"[{module_name}] 头像下载失败: {e}")

        logger.info(f"[{module_name}] 批量刮削完成")

    background_tasks.add_task(_run_batch)

    return {
        "status": "started",
        "job_id": job_id,
        "message": f"模块 {module_name} 一键批量刮削已启动（同步演员→刮削资料→下载头像）",
    }
