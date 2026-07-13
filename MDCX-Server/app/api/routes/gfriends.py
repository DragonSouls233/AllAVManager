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
async def preview_matches(use_local: bool = False):
    """预览匹配情况（不下载）

    返回本地无头像的演员列表 + Gfriends 是否匹配。
    use_local=true 时使用本地资料库（离线副本），不访问 GitHub。
    """
    import asyncio
    from sqlalchemy import select
    from app.db.database import get_database
    from app.db.models import Actor, MovieActor
    from sqlalchemy import func

    if use_local:
        from app.services.gfriends_importer import build_local_index, find_local_avatar
        try:
            build_local_index()
        except Exception as e:
            return {"error": f"加载本地资料库索引失败: {e}"}
        index = None
    else:
        # 加载在线索引
        try:
            index = await gfriends_importer._load_index()
        except Exception as e:
            return {"error": f"加载 Gfriends 索引失败: {e}"}

    db = get_database()
    async with db.session() as session:
        # 查询无头像的演员
        result = await session.execute(
            select(Actor).where(Actor.avatar_url.is_(None)).order_by(Actor.name).limit(200)
        )
        actors = result.scalars().all()

        matched = 0
        unmatched = 0
        samples = []
        for actor in actors:
            if use_local:
                avatar_hit = bool(find_local_avatar(actor.name, actor.name_jp))
            else:
                avatar_url = gfriends_importer._find_avatar_url(actor.name, index)
                if not avatar_url and actor.name_jp:
                    avatar_url = gfriends_importer._find_avatar_url(actor.name_jp, index)
                avatar_hit = bool(avatar_url)

            if avatar_hit:
                matched += 1
                if len(samples) < 20:
                    samples.append({"id": actor.id, "name": actor.name, "name_jp": actor.name_jp, "matched": True})
            else:
                unmatched += 1
                if len(samples) < 20:
                    samples.append({"id": actor.id, "name": actor.name, "name_jp": actor.name_jp, "matched": False})

        return {
            "total_no_avatar": len(actors),
            "matched": matched,
            "unmatched": unmatched,
            "match_rate": f"{matched / len(actors) * 100:.1f}%" if actors else "0%",
            "use_local": use_local,
            "samples": samples,
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
        # 切换运行时检测的本地路径（立即生效，不需重启）
        set_local_library_path(path_str)
        # 探测路径是否合法
        if path_str:
            from pathlib import Path as _Path
            p = _Path(path_str)
            content_dir = p / "Content" if not path_str.rstrip("/\\").endswith("Content") else p
            if not content_dir.exists():
                # 允许保存，但不阻断；前端会显示警告
                logger.warning(f"本地资料库路径不存在: {content_dir}")

    # 写入配置（更新内存 + 持久化）
    for k, v in update_data.items():
        setattr(cfg, k, v)
    manager.save()  # 持久化到 config.yaml

    return {"status": "ok", "updated": update_data}


@router.post("/config/test-local")
async def test_local_library():
    """测试当前配置的本地资料库是否可访问，并返回资料库统计信息"""
    from pathlib import Path as _Path
    from app.services.gfriends_importer import build_local_index, detect_local_library
    # 重新探测（会用最新配置）
    detected = detect_local_library()
    if not detected:
        return {"available": False, "error": "未找到本地资料库（请填写路径）"}
    try:
        build_local_index()  # 重建索引
        from app.services.gfriends_importer import get_local_library_status
        return get_local_library_status()
    except Exception as e:
        return {"available": False, "error": str(e)}


__all__ = ["router"]
