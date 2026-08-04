"""Gfriends 头像库批量导入 API 路由"""

import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.gfriends_importer import gfriends_importer
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class ImportRequest(BaseModel):
    """Gfriends 批量导入请求"""
    overwrite: bool = False  # 是否覆盖已有头像
    min_movies: int = 0  # 仅导入出演影片数 >= N 的演员（0=全部）
    use_local: bool = False  # 使用本地资料库（离线 Gfriends 副本）而非 GitHub
    module: Optional[str] = None  # 目标模块（不传则导入所有模块）


@router.post("/import")
async def start_import(req: ImportRequest, background_tasks: BackgroundTasks):
    """启动批量导入（后台任务）"""
    job_id = str(uuid.uuid4())[:8]

    async def _run():
        await gfriends_importer.run_import(
            job_id=job_id,
            overwrite=req.overwrite,
            min_movies=req.min_movies,
            use_local=req.use_local,
            module=req.module,
        )

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "started", "msg": "批量导入任务已启动"}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """获取任务状态"""
    return gfriends_importer.get_job_status(job_id)


@router.get("/jobs")
async def list_jobs():
    """列出所有导入任务"""
    return {"jobs": gfriends_importer.list_jobs()}


@router.get("/preview")
async def preview_matches(use_local: bool = False, module: Optional[str] = None):
    """预览匹配情况（不下载）

    从各模块数据库收集无头像的演员，匹配 Gfriends 头像库。
    use_local=true 时使用本地资料库（离线副本），不访问 GitHub。
    module 可指定模块名（jav/fc2/...），不传则扫描所有模块。
    """
    import asyncio
    from app.db.module_db import ModuleDatabase

    if use_local:
        from app.services.gfriends_importer import build_local_index, find_local_avatar
        try:
            build_local_index()
        except Exception as e:
            return {"error": f"加载本地资料库索引失败: {e}"}
        index = None
    else:
        try:
            index = await gfriends_importer._load_index()
        except Exception as e:
            return {"error": f"加载 Gfriends 索引失败: {e}"}

    # 收集所有模块的无头像演员
    ALL_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub"]
    modules_to_check = [module] if module else ALL_MODULES

    all_actors = []  # [(name, name_jp, movie_count, module)]

    for mod_name in modules_to_check:
        try:
            mod_db = ModuleDatabase.get_instance(mod_name)
            async with await mod_db.get_session() as sess:
                from sqlalchemy import text

                # 构建演员表名
                actor_table = "pornhub_actors" if mod_name == "pornhub" else f"{mod_name}_actors"

                # 查询演员（不含已下载头像的过滤逻辑——服务器上头像文件很多，
                # 但数据库以 avatar_url 为空或 None 作为"未匹配"的标准）
                rows = await sess.execute(
                    text(f"""
                        SELECT a.id, a.name, a.name_jp, a.avatar_url,
                               (SELECT COUNT(*) FROM {MODULE_TABLE_MAP[mod_name]} m
                                WHERE m.actor = a.name) as movie_count
                        FROM {actor_table} a
                        WHERE a.avatar_url IS NULL OR a.avatar_url = ''
                        ORDER BY movie_count DESC
                        LIMIT 500
                    """)
                )
                for row in rows:
                    all_actors.append({
                        "id": row.id,
                        "name": row.name,
                        "name_jp": row.name_jp,
                        "movie_count": row.movie_count or 0,
                        "module": mod_name,
                        "avatar_url": row.avatar_url,
                    })
        except Exception as e:
            logger.warning(f"模块 {mod_name} 查询演员失败: {e}")
            continue

    # 用 Gfriends 索引匹配
    matched = 0
    unmatched = 0
    samples = []
    for actor in all_actors:
        if use_local:
            avatar_hit = bool(find_local_avatar(actor["name"], actor.get("name_jp")))
        else:
            avatar_url = gfriends_importer._find_avatar_url(actor["name"], index)
            if not avatar_url and actor.get("name_jp"):
                avatar_url = gfriends_importer._find_avatar_url(actor["name_jp"], index)
            avatar_hit = bool(avatar_url)

        if avatar_hit:
            matched += 1
        else:
            unmatched += 1

        if len(samples) < 30:
            samples.append({
                "id": actor["id"],
                "name": actor["name"],
                "name_jp": actor.get("name_jp"),
                "module": actor["module"],
                "movie_count": actor["movie_count"],
                "matched": avatar_hit,
            })

    return {
        "total_no_avatar": len(all_actors),
        "matched": matched,
        "unmatched": unmatched,
        "match_rate": f"{matched / len(all_actors) * 100:.1f}%" if all_actors else "0%",
        "use_local": use_local,
        "module": module,
        "samples": samples,
    }


MODULE_TABLE_MAP = {
    "jav": "jav_movies",
    "fc2": "fc2_movies",
    "uncensored": "uncensored_movies",
    "chinese": "chinese_movies",
    "western": "western_movies",
    "pornhub": "movies",
}


@router.get("/library")
async def local_library_status():
    """本地头像资料库状态（离线 Gfriends 副本，对应 O:/MDCX/GitHub-ZIP/P1-High）"""
    from app.services.gfriends_importer import get_local_library_status
    return get_local_library_status()


# ============================================
# 2026-07-08 修复 2: 本地资料库配置端点
# ============================================

class GfriendsConfigUpdate(BaseModel):
    """Gfriends 配置更新请求"""
    enabled: Optional[bool] = None
    mode: Optional[str] = None  # "online" | "local"
    local_library_path: Optional[str] = None
    prefer_local: Optional[bool] = None
    normalize_names: Optional[bool] = None
    concurrent_downloads: Optional[int] = None
    download_timeout: Optional[int] = None


@router.get("/config")
async def get_gfriends_config():
    """获取当前 Gfriends 配置（包含本地资料库路径）"""
    from app.config.manager import get_config_manager
    from app.services.gfriends_importer import get_local_library_status
    cfg = get_config_manager().computed.config.gfriends
    lib_status = get_local_library_status()
    return {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "local_library_path": cfg.local_library_path,
        "prefer_local": cfg.prefer_local,
        "normalize_names": cfg.normalize_names,
        "concurrent_downloads": cfg.concurrent_downloads,
        "download_timeout": cfg.download_timeout,
        "library_status": lib_status,
    }


@router.post("/config")
async def update_gfriends_config(req: GfriendsConfigUpdate):
    """更新 Gfriends 配置（持久化到 config.yaml）"""
    from app.config.manager import get_config_manager
    from app.services.gfriends_importer import set_local_library_path

    manager = get_config_manager()
    cfg = manager.computed.config.gfriends

    update_data = req.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="无有效字段")

    # 校验 mode
    if "mode" in update_data and update_data["mode"] not in ("online", "local"):
        raise HTTPException(status_code=400, detail="mode 必须是 online 或 local")

    # 校验 local_library_path
    if "local_library_path" in update_data:
        path_str = update_data["local_library_path"].strip()
        update_data["local_library_path"] = path_str
        set_local_library_path(path_str)
        if path_str:
            from pathlib import Path as _Path
            p = _Path(path_str)
            content_dir = p / "Content" if not path_str.rstrip("/\\").endswith("Content") else p
            if not content_dir.exists():
                logger.warning(f"本地资料库路径不存在: {content_dir}")

    for k, v in update_data.items():
        setattr(cfg, k, v)
    manager.save()

    return {"status": "ok", "updated": update_data}


@router.post("/config/test-local")
async def test_local_library():
    """测试当前配置的本地资料库是否可访问，并返回资料库统计信息"""
    from pathlib import Path as _Path
    from app.services.gfriends_importer import build_local_index, detect_local_library
    detected = detect_local_library()
    if not detected:
        return {"available": False, "error": "未找到本地资料库（请填写路径）"}
    try:
        build_local_index()
        from app.services.gfriends_importer import get_local_library_status
        return get_local_library_status()
    except Exception as e:
        return {"available": False, "error": str(e)}


__all__ = ["router"]
