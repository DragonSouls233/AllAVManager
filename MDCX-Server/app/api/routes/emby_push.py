"""
Emby 元数据推送路由 - v3.1

提供手动推送刮削结果到 Emby 的 API，补齐自动推送之外的闭环：
- 手动推送单个影片元数据
- 批量推送影片
- 推送演员头像
- 刷新 Emby 媒体库
- 检查 Emby 连接状态
- 搜索 Emby 项目

配合 workflow.py 中的自动推送（刮削完成后触发），形成完整闭环。
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class BatchPushRequest(BaseModel):
    """批量推送请求"""
    limit: int = 50
    offset: int = 0
    studio: Optional[str] = None  # 按制作商过滤


class PushResponse(BaseModel):
    """推送响应"""
    status: str  # ok | skipped | error
    message: str = ""
    emby_item_id: Optional[str] = None
    pushed_fields: list[str] = []


class BatchPushResponse(BaseModel):
    """批量推送响应"""
    total: int
    success: int
    failed: int
    skipped: int
    details: list[dict] = []


class ActorPushRequest(BaseModel):
    """演员推送请求"""
    actor_id: int
    image_path: Optional[str] = None  # 本地图片路径，None 则用 avatar_url


class PushServerConfig(BaseModel):
    """推送目标 Emby 服务器配置"""
    url: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None


# ============================================
# 辅助函数
# ============================================

def _get_emby_client():
    """从配置创建 EmbyClient 实例"""
    config = get_config()
    if not config.emby.enabled or not config.emby.url or not config.emby.api_key:
        raise HTTPException(status_code=400, detail="Emby 未配置或未启用")
    from app.utils.emby import EmbyClient, EmbyConfig
    emby_config = EmbyConfig(
        url=config.emby.url,
        api_key=config.emby.api_key,
        verify_ssl=False,
    )
    return EmbyClient(emby_config)


# ============================================
# 推送目标配置
# ============================================

@router.get("/config")
async def get_push_config():
    """获取推送目标 Emby 服务器配置（config.emby）"""
    cfg = get_config().emby
    return {
        "url": cfg.url,
        "api_key": cfg.api_key,
        "enabled": cfg.enabled,
    }


@router.put("/config")
async def update_push_config(req: PushServerConfig):
    """更新推送目标 Emby 服务器配置"""
    from app.config.manager import get_config_manager
    cm = get_config_manager()
    current = cm.config
    if req.url is not None:
        current.emby.url = req.url.strip() or None
    if req.api_key is not None:
        current.emby.api_key = req.api_key.strip() or None
    if req.enabled is not None:
        current.emby.enabled = req.enabled
    cm.save()
    return {"status": "ok"}


def _find_poster_path(movie_dir: str) -> Optional[str]:
    """在影片目录中查找海报文件"""
    if not movie_dir:
        return None
    base = Path(movie_dir)
    for name in ("poster.jpg", "poster.png", "fanart.jpg", "cover.jpg", "cover.png"):
        candidate = base / name
        if candidate.exists():
            return str(candidate)
    return None


async def _build_actors_list(movie: Movie, session: AsyncSession) -> list[dict]:
    """从数据库构建演员列表"""
    actors = []
    stmt = (
        select(Actor, MovieActor.role)
        .join(MovieActor, MovieActor.actor_id == Actor.id)
        .where(MovieActor.movie_id == movie.id)
    )
    result = await session.execute(stmt)
    for actor, role in result:
        entry = {"name": actor.name, "type": "Actor"}
        if role:
            entry["role"] = role
        actors.append(entry)
    return actors


def _build_studios_list(movie: Movie) -> list[str]:
    """构建制作商列表"""
    studios = []
    if movie.maker:
        studios.append(movie.maker)
    return studios


def _parse_genres(movie: Movie) -> list[str]:
    """解析 movie.genre（JSON 数组字符串）"""
    import json
    if not movie.genre:
        return []
    try:
        return json.loads(movie.genre) if isinstance(movie.genre, str) else list(movie.genre)
    except Exception:
        return []


# ============================================
# 路由
# ============================================

@router.get("/status")
async def emby_status():
    """检查 Emby 连接状态"""
    config = get_config()
    if not config.emby.enabled:
        return {"enabled": False, "connected": False, "message": "Emby 集成未启用"}

    if not config.emby.url or not config.emby.api_key:
        return {"enabled": True, "connected": False, "message": "URL 或 API Key 未配置"}

    try:
        client = _get_emby_client()
        info = await client.get_system_info()
        return {
            "enabled": True,
            "connected": True,
            "server_name": info.get("ServerName", ""),
            "version": info.get("Version", ""),
            "url": config.emby.url,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {
            "enabled": True,
            "connected": False,
            "url": config.emby.url,
            "message": str(e),
        }


@router.post("/movie/{movie_id}", response_model=PushResponse)
async def push_movie(movie_id: int, session: AsyncSession = Depends(get_session)):
    """手动推送单个影片元数据到 Emby

    流程：
    1. 从数据库读取影片
    2. 通过 file_path 在 Emby 中查找对应项目
    3. 推送标题、简介、标签、演员、制作商、发行日期、评分、海报
    4. 触发 Emby 项目刷新
    """
    client = _get_emby_client()

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        return PushResponse(status="skipped", message="影片未关联文件路径")

    # 通过路径查找 Emby 项目
    movie_dir = str(Path(movie.file_path).parent) if movie.file_path else ""
    try:
        emby_item = await client.get_item_by_path(movie.file_path)
        if not emby_item and movie_dir:
            emby_item = await client.get_item_by_path(movie_dir)
    except Exception as e:
        logger.warning(f"Emby 查找项目失败: {e}")
        emby_item = None

    if not emby_item:
        return PushResponse(
            status="skipped",
            message=f"Emby 中未找到路径对应的项目: {movie.file_path}",
        )

    # 构建推送数据
    actors = await _build_actors_list(movie, session)
    studios = _build_studios_list(movie)
    genres = _parse_genres(movie)
    poster_path = _find_poster_path(movie_dir)

    pushed_fields = []
    try:
        success = await client.push_scraped_result(
            item_id=emby_item.id,
            title=movie.title or movie.code,
            overview=movie.plot,
            genres=genres if genres else None,
            actors=actors if actors else None,
            studios=studios if studios else None,
            premiere_date=str(movie.release_date) if movie.release_date else None,
            community_rating=movie.rating,
            image_path=poster_path,
        )
        if success:
            pushed_fields = ["title", "overview", "genres", "actors", "studios", "premiere_date", "rating"]
            if poster_path:
                pushed_fields.append("poster")
            return PushResponse(
                status="ok",
                message=f"已推送 {movie.code} 到 Emby",
                emby_item_id=emby_item.id,
                pushed_fields=pushed_fields,
            )
        return PushResponse(status="error", message="推送失败，请检查 Emby 日志")
    except Exception as e:
        logger.error(f"推送影片 {movie_id} 到 Emby 失败: {e}")
        return PushResponse(status="error", message=str(e))


@router.post("/batch", response_model=BatchPushResponse)
async def batch_push(req: BatchPushRequest, session: AsyncSession = Depends(get_session)):
    """批量推送影片元数据到 Emby

    可选过滤：按制作商
    """
    client = _get_emby_client()

    stmt = select(Movie).where(Movie.file_path.isnot(None))
    if req.studio:
        stmt = stmt.where(Movie.maker == req.studio)
    stmt = stmt.limit(req.limit).offset(req.offset)

    result = await session.execute(stmt)
    movies = list(result.scalars())

    if not movies:
        return BatchPushResponse(total=0, success=0, failed=0, skipped=0)

    total = len(movies)
    success = 0
    failed = 0
    skipped = 0
    details = []

    for movie in movies:
        try:
            if not movie.file_path:
                skipped += 1
                details.append({"code": movie.code, "status": "skipped", "reason": "无文件路径"})
                continue

            emby_item = await client.get_item_by_path(movie.file_path)
            if not emby_item:
                skipped += 1
                details.append({"code": movie.code, "status": "skipped", "reason": "Emby 中未找到"})
                continue

            movie_dir = str(Path(movie.file_path).parent)
            actors = await _build_actors_list(movie, session)
            studios = _build_studios_list(movie)
            genres = _parse_genres(movie)
            poster_path = _find_poster_path(movie_dir)

            ok = await client.push_scraped_result(
                item_id=emby_item.id,
                title=movie.title or movie.code,
                overview=movie.plot,
                genres=genres if genres else None,
                actors=actors if actors else None,
                studios=studios if studios else None,
                premiere_date=str(movie.release_date) if movie.release_date else None,
                community_rating=movie.rating,
                image_path=poster_path,
            )
            if ok:
                success += 1
                details.append({"code": movie.code, "status": "ok", "emby_id": emby_item.id})
            else:
                failed += 1
                details.append({"code": movie.code, "status": "failed"})
        except Exception as e:
            failed += 1
            details.append({"code": movie.code, "status": "error", "reason": str(e)})

    return BatchPushResponse(
        total=total, success=success, failed=failed, skipped=skipped, details=details
    )


@router.post("/refresh/{movie_id}")
async def refresh_movie(movie_id: int, session: AsyncSession = Depends(get_session)):
    """触发 Emby 中对应项目的元数据刷新"""
    client = _get_emby_client()

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片未关联文件路径")

    emby_item = await client.get_item_by_path(movie.file_path)
    if not emby_item:
        raise HTTPException(status_code=404, detail="Emby 中未找到对应项目")

    ok = await client.refresh_item(
        emby_item.id,
        recursive=False,
        metadata_refresh=True,
        image_refresh=True,
        replace_all_metadata=False,
    )
    return {"status": "ok" if ok else "error", "emby_item_id": emby_item.id}


@router.post("/actor/{actor_id}")
async def push_actor(
    actor_id: int,
    req: ActorPushRequest,
    session: AsyncSession = Depends(get_session),
):
    """推送演员头像到 Emby

    流程：
    1. 从数据库读取演员
    2. 在 Emby 中搜索同名 Person
    3. 上传头像（本地路径或 avatar_url）
    """
    client = _get_emby_client()

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    # 在 Emby 中查找 Person
    person = await client.get_person_by_name(actor.name)
    if not person:
        raise HTTPException(status_code=404, detail=f"Emby 中未找到演员: {actor.name}")

    person_id = person.get("Id")
    if not person_id:
        raise HTTPException(status_code=500, detail="Emby 返回的 Person 缺少 Id")

    # 上传头像
    image_path = req.image_path
    image_url = actor.avatar_url if not image_path else None

    if not image_path and not image_url:
        return {"status": "skipped", "message": "演员无头像可推送"}

    ok = await client.update_person_image(
        person_id=person_id,
        image_url=image_url,
        image_path=image_path,
    )
    return {
        "status": "ok" if ok else "error",
        "emby_person_id": person_id,
        "actor_name": actor.name,
    }


@router.get("/search")
async def search_emby(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
):
    """搜索 Emby 媒体库"""
    client = _get_emby_client()
    from app.utils.emby import EmbyItemType
    items = await client.search_items(q, item_types=[EmbyItemType.MOVIE], limit=limit)
    return {
        "total": len(items),
        "items": [
            {
                "id": it.id,
                "name": it.name,
                "type": it.type.value,
                "path": it.path,
                "overview": (it.overview[:200] + "...") if it.overview and len(it.overview) > 200 else it.overview,
                "genres": it.genres or [],
                "studios": it.studios or [],
            }
            for it in items
        ],
    }


@router.post("/refresh-library")
async def refresh_library():
    """触发 Emby 媒体库全量刷新（扫描新文件）

    会自动获取用户列表并刷新所有 Views。
    """
    config = get_config()
    client = _get_emby_client()

    # 获取用户列表
    import httpx
    user_id = None
    async with httpx.AsyncClient(timeout=10, verify=False) as http:
        resp = await http.get(
            f"{config.emby.url.rstrip('/')}/Users",
            headers={"X-Emby-Token": config.emby.api_key},
        )
        if resp.status_code == 200:
            users = resp.json()
            if users:
                user_id = users[0].get("Id")

    if not user_id:
        raise HTTPException(status_code=400, detail="无法获取 Emby 用户 ID")

    views = await client.get_user_views(user_id)
    refreshed = 0
    for view in views:
        view_id = view.get("Id")
        if view_id:
            try:
                await client.refresh_item(
                    view_id,
                    recursive=True,
                    metadata_refresh=False,
                    image_refresh=False,
                )
                refreshed += 1
            except Exception as e:
                logger.warning(f"刷新 View {view_id} 失败: {e}")

    return {"status": "ok", "refreshed_views": refreshed, "total_views": len(views)}
