"""
演员管理路由

API 端点：
- GET  /api/v1/actors        - 演员列表
- GET  /api/v1/actors/:id    - 演员详情
- GET  /api/v1/actors/:id/movies - 演员作品列表
"""

import asyncio
import importlib
import json
import logging
import re
import shutil
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func, or_

from app.config.manager import get_config_manager
from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 模块数据库辅助 =====

async def _get_mod_session(module: str):
    """获取模块数据库 session"""
    return await get_module_session(module)


def _get_mod_model(module: str, typ: str = "movie"):
    """获取模块模型类（movie/actor）"""
    return get_module_model(module, typ)


def _get_mod_cls(module: str, cls_name: str):
    """获取模块中的任意模型类（如 ActorTag, MovieActor, Studio, Series, Tag 等）"""
    mod_path, _, _ = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


# ===== 轻量级内存缓存 =====

class _SimpleCache:
    """简单的 TTL 内存缓存"""
    def __init__(self):
        self._store: dict[str, tuple[float, any]] = {}

    def get(self, key: str, ttl: int = 60) -> any:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > ttl:
            del self._store[key]
            return None
        return val

    def set(self, key: str, value: any) -> None:
        self._store[key] = (time.time(), value)
        if len(self._store) > 500:
            sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k][0])
            for k in sorted_keys[:100]:
                del self._store[k]

    def invalidate(self, prefix: str = "") -> None:
        if not prefix:
            self._store.clear()
            return
        keys_to_del = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_del:
            del self._store[k]

_cache = _SimpleCache()


def invalidate_actors_cache():
    """清除演员列表缓存（供其他模块调用，如头像刮削）"""
    _cache.invalidate("actors:")


# ===== Response Models =====

class ActorResponse(BaseModel):
    """演员响应模型"""
    id: int
    name: str
    name_jp: Optional[str] = None
    name_en: Optional[str] = None
    alias: Optional[str] = None
    birth_date: Optional[str] = None
    age: Optional[int] = None
    height: Optional[int] = None
    bust: Optional[int] = None
    waist: Optional[int] = None
    hip: Optional[int] = None
    cup: Optional[str] = None
    birthplace: Optional[str] = None
    hobby: Optional[str] = None
    intro: Optional[str] = None
    avatar_url: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    zodiac: Optional[str] = None
    debut_year: Optional[int] = None
    social_links: Optional[dict] = None
    movie_count: Optional[int] = 0

    class Config:
        from_attributes = True


class ActorListResponse(BaseModel):
    """演员列表响应"""
    total: int
    items: list[ActorResponse]


def _build_actor_response(actor, movie_count: int = 0) -> ActorResponse:
    """统一构建 ActorResponse（避免重复代码 + 确保新字段完整）

    手动构建而非 model_validate，避免 Pydantic 访问 ORM 懒加载属性触发 MissingGreenlet。
    """
    social_links = None
    if getattr(actor, "social_links", None):
        try:
            raw = actor.social_links
            social_links = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            social_links = None
    return ActorResponse(
        id=actor.id, name=actor.name, name_jp=getattr(actor, "name_jp", None),
        name_en=getattr(actor, "name_en", None), alias=getattr(actor, "alias", None),
        birth_date=getattr(actor, "birth_date", None), age=getattr(actor, "age", None),
        height=getattr(actor, "height", None), bust=getattr(actor, "bust", None),
        waist=getattr(actor, "waist", None), hip=getattr(actor, "hip", None),
        cup=getattr(actor, "cup", None), birthplace=getattr(actor, "birthplace", None),
        hobby=getattr(actor, "hobby", None), intro=getattr(actor, "intro", None),
        avatar_url=getattr(actor, "avatar_url", None),
        source=getattr(actor, "source", None), source_url=getattr(actor, "source_url", None),
        zodiac=getattr(actor, "zodiac", None), debut_year=getattr(actor, "debut_year", None),
        social_links=social_links,
        movie_count=movie_count,
    )


class ActorMovieResponse(BaseModel):
    """演员作品响应"""
    id: int
    code: str
    title: Optional[str] = None
    release_date: Optional[str] = None
    cover_url: Optional[str] = None

    class Config:
        from_attributes = True


class ActorTagResponse(BaseModel):
    """演员标签响应（v3.4 新增）"""
    id: int
    actor_id: int
    name: str
    color: Optional[str] = None
    is_user: bool = True

    class Config:
        from_attributes = True


class ActorTagCreateRequest(BaseModel):
    """演员标签创建请求（v3.4 新增）"""
    name: str
    color: Optional[str] = None


class ActorDetailResponse(BaseModel):
    """演员详情响应"""
    actor: ActorResponse
    movie_count: int
    recent_movies: list[ActorMovieResponse]


class ActorScrapeResult(BaseModel):
    """演员资料刮削结果"""
    status: str = "ok"
    message: str = ""
    scraped_fields: dict = {}
    actor: Optional[dict] = None


class BatchActorProfileScrapeRequest(BaseModel):
    """批量演员资料刮削请求"""
    actor_ids: list[int] = []
    min_movies: int = Query(2, ge=1, description="最少作品数")
    sources: Optional[list[str]] = Query(
        None,
        description="刮削来源: dmm_actress/javwiki/avopen/avwikidb/wikidata/wikipedia/gfriends"
    )
    include_avatar: bool = Query(True, description="是否包含头像刮削")


class BatchActorProfileScrapeResponse(BaseModel):
    """批量演员资料刮削响应"""
    total: int
    success: int
    failed: int
    results: list[dict]


# ===== API Endpoints =====

@router.get("", response_model=ActorListResponse)
async def list_actors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: str = Query("name", description="排序字段: name/movie_count"),
    sort_order: str = Query("asc", description="排序方向: asc/desc"),
    movie_count_filter: Optional[str] = Query(None, description="作品数过滤: all/multi/single"),
    min_movies: int = Query(2, ge=1, le=20, description="多作品阈值(部): multi>=此值归默认页, single<此值归素人页"),
    cup: Optional[str] = Query(None, description="罩杯筛选: A/B/C/D/E/F/G/H"),
    min_age: Optional[int] = Query(None, description="最小年龄"),
    max_age: Optional[int] = Query(None, description="最大年龄"),
    min_height: Optional[int] = Query(None, description="最小身高"),
    max_height: Optional[int] = Query(None, description="最大身高"),
    birthplace: Optional[str] = Query(None, description="出生地"),
    has_avatar: Optional[bool] = Query(None, description="是否有头像"),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员列表（带内存缓存，60秒 TTL）"""
    actor_cls = get_module_model(module, "actor")
    movie_cls = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        # 作品数子查询
        movie_count_subq = (
            select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
            .group_by(MovieActor.actor_id)
            .subquery()
        )

        # 主查询
        query = select(actor_cls, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
        query = query.outerjoin(movie_count_subq, actor_cls.id == movie_count_subq.c.actor_id)

        if search:
            query = query.where(
                actor_cls.name.contains(search) | actor_cls.name_jp.contains(search)
            )

        if movie_count_filter == "multi":
            query = query.where(func.coalesce(movie_count_subq.c.mc, 0) >= min_movies)
        elif movie_count_filter == "single":
            query = query.where(func.coalesce(movie_count_subq.c.mc, 0) < min_movies)

        if cup:
            query = query.where(actor_cls.cup == cup)
        if min_age is not None:
            query = query.where(actor_cls.age >= min_age)
        if max_age is not None:
            query = query.where(actor_cls.age <= max_age)
        if min_height is not None:
            query = query.where(actor_cls.height >= min_height)
        if max_height is not None:
            query = query.where(actor_cls.height <= max_height)
        if birthplace:
            query = query.where(actor_cls.birthplace.contains(birthplace))
        if has_avatar is True:
            query = query.where(actor_cls.avatar_url.isnot(None), actor_cls.avatar_url != "")
        elif has_avatar is False:
            query = query.where((actor_cls.avatar_url.is_(None)) | (actor_cls.avatar_url == ""))

        count_query = select(func.count()).select_from(query.subquery())
        total = await sess.scalar(count_query)

        if sort_by == "movie_count":
            if sort_order == "desc":
                query = query.order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
            else:
                query = query.order_by(func.coalesce(movie_count_subq.c.mc, 0).asc())
        else:
            if sort_order == "desc":
                query = query.order_by(actor_cls.name.desc())
            else:
                query = query.order_by(actor_cls.name.asc())

        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await sess.execute(query)
        rows = result.fetchall()

        items = []
        for row in rows:
            a = row[0]
            mc = row[1]
            items.append(_build_actor_response(a, mc or 0))

        return ActorListResponse(total=total or 0, items=items)


@router.get("/stats/overview")
async def get_actor_stats(
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员统计概览"""
    actor_cls = get_module_model(module, "actor")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        total = await sess.scalar(select(func.count(actor_cls.id))) or 0

        with_avatar = await sess.scalar(
            select(func.count(actor_cls.id)).where(actor_cls.avatar_url.isnot(None))
        ) or 0

        top_query = (
            select(actor_cls.name, func.count(MovieActor.movie_id).label("movie_count"))
            .join(MovieActor, actor_cls.id == MovieActor.actor_id)
            .group_by(actor_cls.id)
            .order_by(func.count(MovieActor.movie_id).desc())
            .limit(10)
        )
        result = await sess.execute(top_query)
        top_actors = [{"name": row[0], "movie_count": row[1]} for row in result.fetchall()]

        return {
            "total": total,
            "with_avatar": with_avatar,
            "top_actors": top_actors,
        }


# ===== 演员头像刮削（必须在 /{actor_id} 之前注册） =====

@router.post("/avatar-scrape/start")
async def start_avatar_scrape(
    background_tasks: BackgroundTasks,
    min_movies: int = Query(2, ge=1, description="最少作品数，只刮削达到此数量的演员"),
    use_local_library: bool = Query(False, description="优先使用本地资料库（离线 Gfriends 副本），不再从 JavBus 等站点抓取"),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """启动演员头像智能补充刮削"""
    from app.scraper.actor_avatar import run_avatar_scrape_job
    from app.db.module_db import ModuleDatabase

    mod_db = ModuleDatabase.get_instance(module)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:6]}"

    background_tasks.add_task(run_avatar_scrape_job, job_id, mod_db, min_movies, use_local_library)

    return {
        "status": "started",
        "job_id": job_id,
        "message": f"头像刮削已启动，只处理 {min_movies} 部以上且无头像的演员",
    }


@router.get("/avatar-scrape/status/{job_id}")
async def get_avatar_scrape_status(job_id: str):
    """获取头像刮削任务状态"""
    from app.scraper.actor_avatar import get_avatar_job_status

    status = get_avatar_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="任务不存在")

    if status.get("status") in ("completed", "cancelled") and status.get("finished_at"):
        invalidate_actors_cache()

    return status


@router.post("/avatar-scrape/cancel/{job_id}")
async def cancel_avatar_scrape(job_id: str):
    """取消头像刮削任务"""
    from app.scraper.actor_avatar import cancel_avatar_job

    success = cancel_avatar_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"status": "cancelled", "job_id": job_id}


@router.get("/avatar-scrape/preview")
async def preview_avatar_scrape(
    min_movies: int = Query(2, ge=1),
    use_local_library: bool = Query(False, description="是否计入本地资料库可用状态"),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """预览需要补充头像的演员列表（不执行刮削）"""
    from app.scraper.actor_avatar import actor_needs_avatar

    actor_cls = get_module_model(module, "actor")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        movie_count_subq = (
            select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
            .group_by(MovieActor.actor_id)
            .subquery()
        )

        query = (
            select(actor_cls, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
            .outerjoin(movie_count_subq, actor_cls.id == movie_count_subq.c.actor_id)
            .where(
                func.coalesce(movie_count_subq.c.mc, 0) >= min_movies,
                actor_cls.name != "佚名",
                actor_cls.name.isnot(None),
                actor_cls.name != "",
            )
            .order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
        )
        result = await sess.execute(query)
        rows = result.fetchall()

        filtered = [r for r in rows if actor_needs_avatar(r[0])]
        total = len(filtered)

        actors = [
            {
                "id": row[0].id,
                "name": row[0].name,
                "name_jp": getattr(row[0], "name_jp", None),
                "movie_count": row[1],
            }
            for row in filtered[:20]
        ]

        return {
            "total": total,
            "min_movies": min_movies,
            "actors": actors,
        }


@router.get("/avatar-scrape/library")
async def avatar_scrape_library():
    """本地头像资料库状态（离线 Gfriends 副本，对应 O:/MDCX/GitHub-ZIP/P1-High）"""
    from app.services.gfriends_importer import get_local_library_status
    return get_local_library_status()


@router.post("/{actor_id}/scrape-profile", response_model=ActorScrapeResult)
async def scrape_actor_profile(
    actor_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """从 JavDB 抓取演员资料并更新数据库"""
    actor_cls = get_module_model(module, "actor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        scraped = await _scrape_javdb_actor_profile(actor)

        if not scraped:
            return ActorScrapeResult(
                status="not_found",
                message="未在 JavDB 找到该演员的资料页面",
                scraped_fields={},
            )

        for field, value in scraped.items():
            if hasattr(actor, field):
                setattr(actor, field, value)

        await sess.commit()
        await sess.refresh(actor)
        _cache.invalidate("actors:")

        actor_resp = _build_actor_response(actor)
        return ActorScrapeResult(
            status="ok",
            message=f"成功抓取 {len(scraped)} 个字段",
            scraped_fields=scraped,
            actor=actor_resp.model_dump(),
        )


@router.get("/{actor_id}", response_model=ActorDetailResponse)
async def get_actor(
    actor_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员详情"""
    actor_cls = get_module_model(module, "actor")
    movie_cls = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        movie_count = getattr(actor, "movie_count", None) or 0

        recent_q = (
            select(movie_cls)
            .join(MovieActor, movie_cls.id == MovieActor.movie_id)
            .where(MovieActor.actor_id == actor_id)
            .order_by(movie_cls.release_date.desc().nulls_last())
            .limit(10)
        )
        result = await sess.execute(recent_q)
        recent_movies = result.scalars().all()

        movie_resps = []
        for m in recent_movies:
            movie_resps.append(ActorMovieResponse(
                id=m.id, code=m.code, title=m.title,
                release_date=str(m.release_date) if getattr(m, "release_date", None) else None,
                cover_url=getattr(m, "cover_url", None),
            ))

        actor_resp = _build_actor_response(actor, movie_count)
        return ActorDetailResponse(actor=actor_resp, movie_count=movie_count, recent_movies=movie_resps)


@router.get("/{actor_id}/movies")
async def get_actor_movies(
    actor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员作品列表"""
    actor_cls = get_module_model(module, "actor")
    movie_cls = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        # 优先用关联表，回退到 actor 文本字段 LIKE 查询
        query = (
            select(movie_cls)
            .join(MovieActor, movie_cls.id == MovieActor.movie_id)
            .where(MovieActor.actor_id == actor_id)
        )
        count_query = select(func.count()).select_from(query.subquery())
        total = await sess.scalar(count_query)

        if total == 0:
            # 回退到 actor 文本字段 LIKE（folder_based_actors 仅 chinese 模块存在，需防御）
            name_part = f"%{actor.name}%"
            folder_col = getattr(movie_cls, "folder_based_actors", None)
            cond = (
                or_(movie_cls.actor.like(name_part), folder_col.like(name_part))
                if folder_col is not None
                else movie_cls.actor.like(name_part)
            )
            count_query = select(func.count(movie_cls.id)).where(cond)
            total = await sess.scalar(count_query) or 0
            query = select(movie_cls).where(cond).order_by(movie_cls.release_date.desc().nulls_last(), movie_cls.id.desc())

        query = query.offset((page - 1) * page_size).limit(page_size)
        if total > 0 and not str(query.whereclause).startswith("movies.actor"):
            query = query.order_by(movie_cls.release_date.desc().nulls_last())

        result = await sess.execute(query)
        movies = result.scalars().all()

        movie_items = []
        for m in movies:
            movie_items.append(ActorMovieResponse(
                id=m.id, code=m.code, title=m.title,
                release_date=str(m.release_date) if getattr(m, "release_date", None) else None,
                cover_url=getattr(m, "cover_url", None),
            ))

        return {"actor_id": actor_id, "actor_name": actor.name, "total": total or 0, "items": movie_items}


@router.get("/{actor_id}/timeline")
async def get_actor_timeline(
    actor_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员作品时间线（v3.4 新增）"""
    actor_cls = get_module_model(module, "actor")
    movie_cls = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        # 扫描器将演员名以逗号分隔存于 movie.actor 字段，并不维护
        # MovieActor 关联表（关联表始终为空），故不能用 join 关联表查询，
        # 改用 actor 字段的模糊匹配（与 jav_routes 的 timeline 一致）。
        query = (
            select(movie_cls)
            .where(movie_cls.actor.like(f"%{actor.name}%"))
            .order_by(movie_cls.release_date.asc())
        )
        result = await sess.execute(query)
        movies = result.scalars().all()

        year_map = defaultdict(list)
        unknown_year_movies = []
        for m in movies:
            year = None
            if m.release_date:
                try:
                    year = int(str(m.release_date)[:4])
                except (ValueError, TypeError):
                    pass
            if year:
                year_map[year].append(m)
            else:
                unknown_year_movies.append(m)

        years_sorted = sorted(year_map.keys())
        years_data = [{"year": y, "count": len(year_map[y])} for y in years_sorted]
        details = []
        for y in years_sorted:
            ms = year_map[y]
            details.append({
                "year": y,
                "count": len(ms),
                "movies": [
                    ActorMovieResponse(
                        id=m.id, code=m.code, title=m.title,
                        release_date=m.release_date, cover_url=m.cover_url,
                    )
                    for m in ms
                ],
            })

        unknown_data = {
            "year": None,
            "count": len(unknown_year_movies),
            "movies": [
                ActorMovieResponse(
                    id=m.id, code=m.code, title=m.title,
                    release_date=m.release_date, cover_url=m.cover_url,
                )
                for m in unknown_year_movies
            ],
        } if unknown_year_movies else None

        debut_year = actor.debut_year or (years_sorted[0] if years_sorted else None)

        return {
            "actor_id": actor_id,
            "actor_name": actor.name,
            "total": len(movies),
            "years": years_data,
            "details": details,
            "unknown": unknown_data,
            "year_range": [years_sorted[0], years_sorted[-1]] if years_sorted else [None, None],
            "debut_year": debut_year,
        }


# ===== 演员标签管理（v3.4 新增）=====

@router.get("/{actor_id}/tags", response_model=list[ActorTagResponse])
async def list_actor_tags(
    actor_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员的所有标签"""
    actor_cls = get_module_model(module, "actor")
    ActorTag = _get_mod_cls(module, "ActorTag")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        result = await sess.execute(
            select(ActorTag).where(ActorTag.actor_id == actor_id).order_by(ActorTag.created_at.desc())
        )
        tags = result.scalars().all()
        return [ActorTagResponse(id=t.id, actor_id=t.actor_id, name=t.name, color=t.color, is_user=t.is_user) for t in tags]


@router.post("/{actor_id}/tags", response_model=ActorTagResponse)
async def add_actor_tag(
    actor_id: int,
    body: ActorTagCreateRequest,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """为演员添加标签"""
    actor_cls = get_module_model(module, "actor")
    ActorTag = _get_mod_cls(module, "ActorTag")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="标签名不能为空")
        if len(name) > 50:
            raise HTTPException(status_code=400, detail="标签名过长（最多 50 字符）")

        existing = await sess.execute(
            select(ActorTag).where(ActorTag.actor_id == actor_id, ActorTag.name == name)
        )
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="标签已存在")

        tag = ActorTag(
            actor_id=actor_id,
            name=name,
            color=body.color,
            is_user=True,
        )
        sess.add(tag)
        await sess.commit()
        await sess.refresh(tag)
        return ActorTagResponse(id=tag.id, actor_id=tag.actor_id, name=tag.name, color=tag.color, is_user=tag.is_user)


@router.delete("/{actor_id}/tags/{tag_id}")
async def delete_actor_tag(
    actor_id: int,
    tag_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """删除演员标签"""
    ActorTag = _get_mod_cls(module, "ActorTag")

    sess = await get_module_session(module)
    async with sess:
        tag = await sess.get(ActorTag, tag_id)
        if not tag or tag.actor_id != actor_id:
            raise HTTPException(status_code=404, detail="标签不存在")

        await sess.delete(tag)
        await sess.commit()
        return {"status": "ok", "message": "标签已删除"}


@router.get("/tags/popular")
async def list_popular_tags(
    limit: int = Query(50, ge=1, le=200),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取热门演员标签（用于标签输入建议）"""
    ActorTag = _get_mod_cls(module, "ActorTag")

    sess = await get_module_session(module)
    async with sess:
        result = await sess.execute(
            select(ActorTag.name, func.count(ActorTag.id).label("usage_count"))
            .group_by(ActorTag.name)
            .order_by(func.count(ActorTag.id).desc())
            .limit(limit)
        )
        rows = result.fetchall()
        return {"items": [{"name": r[0], "usage_count": r[1]} for r in rows]}


@router.patch("/{actor_id}")
async def update_actor(
    actor_id: int,
    body: dict = Body(...),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """更新演员信息"""
    actor_cls = get_module_model(module, "actor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        updatable_fields = [
            "name", "name_jp", "name_en", "alias", "avatar_url", "birth_date", "age",
            "height", "bust", "waist", "hip", "cup", "birthplace", "hobby", "intro",
            "zodiac", "debut_year",
        ]
        for field in updatable_fields:
            if field in body and body[field] is not None:
                setattr(actor, field, body[field])

        if "social_links" in body and body["social_links"] is not None:
            sl = body["social_links"]
            actor.social_links = json.dumps(sl, ensure_ascii=False) if isinstance(sl, dict) else sl

        await sess.commit()
        await sess.refresh(actor)
        _cache.invalidate("actors:")
        actor_resp = _build_actor_response(actor)

        return {"status": "ok", "actor": actor_resp}


# ===== 头像管理 =====

AVATAR_DIR_NAME = "avatars"


def _get_avatar_dir(module: str = None) -> Path:
    """获取头像存储目录(可按模块隔离: avatars/{module})"""
    manager = get_config_manager()
    base = manager.computed.data_dir / AVATAR_DIR_NAME
    if module:
        return base / module
    return base


def _get_avatar_path(actor_id: int, module: str = "jav") -> Path:
    """获取演员头像文件路径(绝对, 不依赖 server 启动目录, 按模块隔离)"""
    return _get_avatar_dir(module).resolve() / f"actor_{actor_id}.jpg"


@router.post("/{actor_id}/avatar")
async def upload_actor_avatar(
    actor_id: int,
    file: UploadFile = File(...),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """上传并裁剪演员头像"""
    actor_cls = get_module_model(module, "actor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式的图片")

    avatar_dir = _get_avatar_dir(module)
    avatar_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if file.filename else "jpg"
    temp_path = avatar_dir / f"actor_{actor_id}_temp.{ext}"
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        from app.utils.face_crop import get_face_cropper
        output_path = _get_avatar_path(actor_id, module)
        cropper = get_face_cropper()
        result = cropper.crop_face(str(temp_path), str(output_path))

        async with sess:
            actor_to_update = await sess.get(actor_cls, actor_id)
            if result:
                actor_to_update.avatar_url = str(output_path)
                await sess.commit()
                _cache.invalidate("actors:")
                return {
                    "status": "ok",
                    "message": "头像上传并裁剪成功",
                    "avatar_path": str(output_path),
                }
            else:
                shutil.copy2(temp_path, output_path)
                actor_to_update.avatar_url = str(output_path)
                await sess.commit()
                _cache.invalidate("actors:")
                return {
                    "status": "ok",
                    "message": "头像已上传（人脸检测未找到面部，使用原图）",
                    "avatar_path": str(output_path),
                }

    except Exception as e:
        logger.error(f"头像上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"头像上传失败: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.get("/{actor_id}/avatar/file")
async def get_actor_avatar_file(
    actor_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """获取演员头像文件"""
    actor_cls = get_module_model(module, "actor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

    # 1. 优先: DATA/avatars/{module}/actor_{id}.jpg（按模块隔离）
    avatar_path = _get_avatar_path(actor_id, module)
    if avatar_path.exists() and avatar_path.is_file():
        return FileResponse(str(avatar_path), media_type="image/jpeg")

    # 1.1 兼容旧约定: 仅 jav 模块回退到全局 avatars/actor_{id}.jpg
    if module == "jav":
        legacy_path = _get_avatar_dir() / f"actor_{actor_id}.jpg"
        if legacy_path.exists() and legacy_path.is_file():
            return FileResponse(str(legacy_path), media_type="image/jpeg")

    # 2. 数据库 avatar_url 字段
    if actor.avatar_url:
        url = actor.avatar_url.strip()
        is_api_path = url.startswith("/api/") or url.startswith("api/")
        is_http = url.startswith("http://") or url.startswith("https://")
        if not is_api_path and not is_http:
            try:
                p = Path(url)
                if p.exists() and p.is_file():
                    media_type = _get_image_media_type(p)
                    return FileResponse(str(p), media_type=media_type)
            except (OSError, ValueError):
                pass

    # 3. Gfriends 本地资料库实时查找
    try:
        from app.services.gfriends_importer import find_local_avatar
        local_path = find_local_avatar(actor.name, getattr(actor, "name_jp", None))
        if local_path and local_path.exists() and local_path.is_file():
            media_type = _get_image_media_type(local_path)
            return FileResponse(str(local_path), media_type=media_type)
    except Exception:
        pass

    # 4) 搜索各模块 media_dirs
    if actor.name:
        try:
            from app.config.manager import get_config
            from app.utils.media_helpers import collect_media_dirs, scan_media_dirs_for_avatar
            cfg = get_config()
            media_dirs = collect_media_dirs(cfg)
            avatar_path = scan_media_dirs_for_avatar(media_dirs, actor.name, getattr(actor, "name_jp", None))
            if avatar_path:
                media_type = _get_image_media_type(Path(avatar_path))
                return FileResponse(avatar_path, media_type=media_type)
        except Exception:
            pass

    raise HTTPException(status_code=404, detail="头像不存在")


def _get_image_media_type(path) -> str:
    """根据文件扩展名返回 media type"""
    suffix = Path(path).suffix.lower()
    if suffix == '.png':
        return "image/png"
    elif suffix == '.webp':
        return "image/webp"
    elif suffix == '.gif':
        return "image/gif"
    return "image/jpeg"


@router.delete("/{actor_id}/avatar")
async def delete_actor_avatar(
    actor_id: int,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """删除演员头像"""
    actor_cls = get_module_model(module, "actor")

    sess = await get_module_session(module)
    async with sess:
        actor = await sess.get(actor_cls, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        avatar_path = _get_avatar_path(actor_id, module)
        if avatar_path.exists():
            avatar_path.unlink()
        # 同时清理 jav 历史全局头像
        if module == "jav":
            legacy_path = _get_avatar_dir() / f"actor_{actor_id}.jpg"
            if legacy_path.exists():
                legacy_path.unlink()

        actor.avatar_url = None
        await sess.commit()
        _cache.invalidate("actors:")

        return {"status": "ok", "message": "头像已删除"}


# ===== 批量演员资料刮削 =====

@router.post("/scrape-profiles/batch", response_model=BatchActorProfileScrapeResponse)
async def batch_scrape_actor_profiles(
    body: BatchActorProfileScrapeRequest = Body(...),
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """批量刮削演员资料"""
    from app.scraper.actor_profile_scrapers import get_actor_profile_scraper, ActorProfile
    from app.utils.http_client import AsyncHttpClient

    actor_cls = get_module_model(module, "actor")
    MovieActor = _get_mod_cls(module, "MovieActor")

    sess = await get_module_session(module)
    async with sess:
        movie_count_subq = (
            select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
            .group_by(MovieActor.actor_id)
            .subquery()
        )

        if body.actor_ids:
            query = (
                select(actor_cls, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
                .outerjoin(movie_count_subq, actor_cls.id == movie_count_subq.c.actor_id)
                .where(actor_cls.id.in_(body.actor_ids))
            )
        else:
            query = (
                select(actor_cls, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
                .outerjoin(movie_count_subq, actor_cls.id == movie_count_subq.c.actor_id)
                .where(
                    func.coalesce(movie_count_subq.c.mc, 0) >= body.min_movies,
                    actor_cls.name != "佚名",
                    actor_cls.name.isnot(None),
                    actor_cls.name != "",
                )
                .order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
                .limit(100)
            )

        result = await sess.execute(query)
        actors_data = result.fetchall()

    total = len(actors_data)
    success = 0
    failed = 0
    results = []

    scraper = get_actor_profile_scraper()

    for row in actors_data:
        actor = row[0]
        movie_cnt = row[1]

        result_item = {
            "actor_id": actor.id,
            "name": actor.name,
            "movie_count": movie_cnt,
            "status": "pending",
            "scraped_fields": {},
            "avatar_updated": False,
        }

        try:
            profile = await scraper.get_profile(
                name=actor.name,
                name_jp=getattr(actor, "name_jp", None),
                preferred_sources=body.sources,
            )

            if profile and profile.name:
                scraped_fields = {}

                field_mapping = {
                    "birth_date": "birth_date",
                    "age": "age",
                    "height": "height",
                    "bust": "bust",
                    "waist": "waist",
                    "hip": "hip",
                    "cup": "cup",
                    "birthplace": "birthplace",
                    "name_jp": "name_jp",
                    "alias": "alias",
                    "hobby": "hobby",
                    "intro": "intro",
                    "zodiac": "zodiac",
                    "debut_year": "debut_year",
                }

                for profile_field, actor_field in field_mapping.items():
                    if hasattr(profile, profile_field):
                        value = getattr(profile, profile_field)
                        if value and hasattr(actor, actor_field):
                            current_value = getattr(actor, actor_field)
                            if not current_value or current_value == "":
                                setattr(actor, actor_field, value)
                                scraped_fields[actor_field] = value

                if profile.social_links and not getattr(actor, "social_links", None):
                    actor.social_links = json.dumps(profile.social_links, ensure_ascii=False)
                    scraped_fields["social_links"] = profile.social_links

                if body.include_avatar and profile.avatar_url and not getattr(actor, "avatar_url", None):
                    avatar_path = await _download_actor_avatar(
                        actor.id, profile.avatar_url, actor.name, module
                    )
                    if avatar_path:
                        actor.avatar_url = str(avatar_path)
                        scraped_fields["avatar_url"] = str(avatar_path)
                        result_item["avatar_updated"] = True

                if scraped_fields:
                    async with sess:
                        await sess.commit()
                    success += 1
                    result_item["status"] = "success"
                    result_item["scraped_fields"] = scraped_fields
                    result_item["source"] = profile.source
                else:
                    failed += 1
                    result_item["status"] = "no_update"
            else:
                failed += 1
                result_item["status"] = "not_found"

        except Exception as e:
            logger.error(f"刮削演员 {actor.name} 失败: {e}")
            failed += 1
            result_item["status"] = "error"
            result_item["error"] = str(e)

        results.append(result_item)
        await asyncio.sleep(0.5)

    _cache.invalidate("actors:")

    return BatchActorProfileScrapeResponse(
        total=total,
        success=success,
        failed=failed,
        results=results,
    )


async def _download_actor_avatar(
    actor_id: int, url: str, actor_name: str = "", module: str = "jav"
) -> Optional[Path]:
    """下载演员头像到本地(按模块隔离: avatars/{module}/actor_{id}.jpg)"""
    from app.config.manager import get_config_manager

    manager = get_config_manager()
    avatar_dir = manager.computed.data_dir / "avatars"
    if module:
        avatar_dir = avatar_dir / module
    avatar_dir.mkdir(parents=True, exist_ok=True)

    output_path = (avatar_dir / f"actor_{actor_id}.jpg").resolve()

    async with AsyncHttpClient(timeout=30) as client:
        try:
            match = re.match(r'https?://([^/]+)', url)
            referer_domain = f"https://{match.group(1)}" if match else "https://www.dmm.co.jp"

            headers = {
                "Referer": f"{referer_domain}/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

            content = await client.get_bytes(url, headers=headers)
            if content and len(content) > 500:
                with open(output_path, "wb") as f:
                    f.write(content)
                logger.info(f"演员 {actor_name} 头像已下载: {output_path}")
                return output_path

        except Exception as e:
            logger.error(f"下载头像失败 {url}: {e}")

    return None


# ===== 演员资料抓取 =====

_JAVDB_LABEL_MAP = {
    "出生日期": "birth_date",
    "出生年月日": "birth_date",
    "年龄": "age",
    "身高": "height",
    "罩杯": "cup",
    "胸围": "bust",
    "腰围": "waist",
    "臀围": "hip",
    "三围": "measurements",
    "出生地": "birthplace",
    "出身地": "birthplace",
    "日文名": "name_jp",
    "日语名称": "name_jp",
}


def _get_javdb_cookie_headers() -> Optional[dict]:
    """从配置获取 JavDB Cookie headers"""
    try:
        from app.config.manager import get_config, get_config_manager
        cfg = get_config()
        if hasattr(cfg, "crawler") and cfg.crawler.javdb_cookie:
            return {"cookie": cfg.crawler.javdb_cookie, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        mgr = get_config_manager()
        if mgr.config.javdb:
            return {"cookie": mgr.config.javdb, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    except Exception:
        pass
    return None


def _parse_int(text: str) -> Optional[int]:
    """安全解析数字"""
    if not text:
        return None
    text = text.strip()
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    return None


def _parse_cup(text: str) -> Optional[str]:
    """解析罩杯"""
    if not text:
        return None
    text = text.strip().upper()
    match = re.search(r"([A-Z])", text)
    if match:
        return match.group(1)
    return None


def _parse_birth_date(text: str) -> Optional[str]:
    """解析出生日期"""
    if not text:
        return None
    text = text.strip()
    match = re.search(r"(\d{4})[-/\年.](\d{1,2})[-/\月.](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return None


async def _scrape_javdb_actor_profile(actor) -> dict:
    """从 JavDB 抓取演员资料"""
    from parsel import Selector
    from app.utils.http_client import AsyncHttpClient

    result: dict = {}
    cookie_headers = _get_javdb_cookie_headers() or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with AsyncHttpClient(timeout=20) as client:
        search_name = getattr(actor, "name_jp", None) or actor.name
        search_url = f"https://javdb.com/search?q={search_name}&f=actor"
        logger.info(f"搜索 JavDB 演员: {search_name}")

        try:
            search_html = await client.get_text(search_url, headers=cookie_headers)
        except Exception as e:
            logger.error(f"JavDB 搜索失败: {e}")
            return result

        sel = Selector(search_html)

        actor_links = []
        for link in sel.xpath('//a[contains(@href, "/actors/")]/@href').getall():
            parts = link.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "actors" and parts[1] not in ["censored", "uncensored"]:
                actor_links.append(link)

        if not actor_links:
            actor_links = []
            for link in sel.css('a[href*="/actors/"]::attr(href)').getall():
                parts = link.strip("/").split("/")
                if len(parts) >= 3 and parts[0] == "actors" and parts[1] not in ["censored", "uncensored"]:
                    actor_links.append(link)

        if not actor_links:
            logger.info(f"未找到 JavDB 演员页面: {search_name}")
            return result

        actor_path = actor_links[0]
        actor_url = f"https://javdb.com{actor_path}"
        logger.info(f"访问演员页面: {actor_url}")

        try:
            profile_html = await client.get_text(actor_url, headers=cookie_headers)
        except Exception as e:
            logger.error(f"获取演员详情页失败: {e}")
            return result

        profile_sel = Selector(profile_html)

        page_title = profile_sel.css("title::text").get()
        if page_title:
            title_part = page_title.split("|")[0].strip()
            if title_part and not getattr(actor, "name_jp", None):
                result["name_jp"] = title_part

        label_value_pairs: list[tuple[str, str]] = []

        blocks = profile_sel.xpath('//*[contains(@class, "panel-block") or contains(@class, "info") or contains(@class, "item")]')
        for block in blocks:
            texts = block.xpath('.//text()').getall()
            joined = " ".join(t.strip() for t in texts if t.strip())
            for label in _JAVDB_LABEL_MAP:
                if label in joined:
                    idx = joined.find(label)
                    rest = joined[idx + len(label):]
                    rest = rest.replace(":", "").replace("：", "").strip()
                    next_label_pos = len(rest)
                    for other_label in _JAVDB_LABEL_MAP:
                        if other_label == label:
                            continue
                        pos = rest.find(other_label)
                        if pos > 0 and pos < next_label_pos:
                            next_label_pos = pos
                    value = rest[:next_label_pos].strip()
                    if value and len(value) < 50:
                        label_value_pairs.append((label, value))

        rows = profile_sel.xpath('//tr')
        for row in rows:
            th = row.xpath('.//th//text()').get()
            td = row.xpath('.//td//text()').get()
            if th and td:
                th_text = th.strip()
                td_text = td.strip()
                for label in _JAVDB_LABEL_MAP:
                    if label in th_text:
                        label_value_pairs.append((label, td_text))

        all_text_lines = profile_html.split("\n")
        for line in all_text_lines:
            line = line.strip()
            if not line or "<" in line or ">" in line:
                continue
            for label in _JAVDB_LABEL_MAP:
                if label in line and len(line) < 100:
                    idx = line.find(label)
                    rest = line[idx + len(label):]
                    rest = rest.replace(":", "").replace("：", "").strip()
                    if rest and len(rest) < 50 and rest != "-":
                        label_value_pairs.append((label, rest))

        seen_labels: set[str] = set()
        for label, value in label_value_pairs:
            if label in seen_labels:
                continue
            seen_labels.add(label)

            field = _JAVDB_LABEL_MAP[label]
            if field == "birth_date":
                parsed = _parse_birth_date(value)
                if parsed:
                    result["birth_date"] = parsed
            elif field == "age":
                parsed = _parse_int(value)
                if parsed:
                    result["age"] = parsed
            elif field == "height":
                parsed = _parse_int(value)
                if parsed:
                    result["height"] = parsed
            elif field == "bust":
                parsed = _parse_int(value)
                if parsed:
                    result["bust"] = parsed
            elif field == "waist":
                parsed = _parse_int(value)
                if parsed:
                    result["waist"] = parsed
            elif field == "hip":
                parsed = _parse_int(value)
                if parsed:
                    result["hip"] = parsed
            elif field == "cup":
                parsed = _parse_cup(value)
                if parsed:
                    result["cup"] = parsed
            elif field == "measurements":
                nums = re.findall(r"\d+", value)
                if len(nums) >= 3:
                    result["bust"] = int(nums[0])
                    result["waist"] = int(nums[1])
                    result["hip"] = int(nums[2])
            elif field == "birthplace":
                result["birthplace"] = value
            elif field == "name_jp":
                if not getattr(actor, "name_jp", None):
                    result["name_jp"] = value

        logger.info(f"抓取到演员 {actor.name} 资料: {result}")
        return result
