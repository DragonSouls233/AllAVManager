"""
演员管理路由

API 端点：
- GET  /api/v1/actors        - 演员列表
- GET  /api/v1/actors/:id    - 演员详情
- GET  /api/v1/actors/:id/movies - 演员作品列表
"""

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config_manager
from app.db.database import Database, get_session
from app.db.models import Actor, Movie, MovieActor, ActorTag

logger = logging.getLogger(__name__)

router = APIRouter()


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
    name_en: Optional[str] = None  # 英文名（迁移 013）
    alias: Optional[str] = None  # 别名（迁移 013）
    birth_date: Optional[str] = None
    age: Optional[int] = None
    height: Optional[int] = None
    bust: Optional[int] = None
    waist: Optional[int] = None
    hip: Optional[int] = None
    cup: Optional[str] = None
    birthplace: Optional[str] = None
    hobby: Optional[str] = None
    intro: Optional[str] = None  # 简介（迁移 013）
    avatar_url: Optional[str] = None
    source: Optional[str] = None  # 资料来源（迁移 013）
    source_url: Optional[str] = None  # 来源 URL（迁移 013）
    zodiac: Optional[str] = None  # 星座（迁移 014）
    debut_year: Optional[int] = None  # 出道年份（迁移 014）
    social_links: Optional[dict] = None  # 社交账号 JSON（迁移 014）
    movie_count: Optional[int] = 0

    class Config:
        from_attributes = True


class ActorListResponse(BaseModel):
    """演员列表响应"""
    total: int
    items: list[ActorResponse]


def _build_actor_response(actor: Actor, movie_count: int = 0) -> ActorResponse:
    """统一构建 ActorResponse（避免重复代码 + 确保新字段完整）

    手动构建而非 model_validate，避免 Pydantic 访问 ORM 懒加载属性触发 MissingGreenlet。
    v3.4 新增 zodiac/debut_year/social_links 字段。
    """
    social_links = None
    if actor.social_links:
        try:
            social_links = json.loads(actor.social_links) if isinstance(actor.social_links, str) else actor.social_links
        except (json.JSONDecodeError, TypeError):
            social_links = None
    return ActorResponse(
        id=actor.id, name=actor.name, name_jp=actor.name_jp,
        name_en=actor.name_en, alias=actor.alias,
        birth_date=actor.birth_date, age=actor.age,
        height=actor.height, bust=actor.bust, waist=actor.waist, hip=actor.hip,
        cup=actor.cup, birthplace=actor.birthplace, hobby=actor.hobby, intro=actor.intro,
        avatar_url=actor.avatar_url, source=actor.source, source_url=actor.source_url,
        zodiac=actor.zodiac, debut_year=actor.debut_year, social_links=social_links,
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
    # 高级筛选参数
    cup: Optional[str] = Query(None, description="罩杯筛选: A/B/C/D/E/F/G/H"),
    min_age: Optional[int] = Query(None, description="最小年龄"),
    max_age: Optional[int] = Query(None, description="最大年龄"),
    min_height: Optional[int] = Query(None, description="最小身高"),
    max_height: Optional[int] = Query(None, description="最大身高"),
    birthplace: Optional[str] = Query(None, description="出生地"),
    has_avatar: Optional[bool] = Query(None, description="是否有头像"),
    session: AsyncSession = Depends(get_session),
):
    """
    获取演员列表（带内存缓存，60秒 TTL）

    - 支持搜索（按名字）
    - 支持分页
    - 包含作品数量
    - 支持按作品数排序
    - 支持作品数过滤：all(全部), multi(>=min_movies部,多作品/默认页), single(<min_movies部,素人/单作品)
    """
    # 搜索和过滤不缓存，仅缓存无搜索无过滤的分页查询
    cache_key = f"actors:list:{page}:{page_size}:{sort_by}:{sort_order}:{movie_count_filter}:{min_movies}:{cup}:{min_age}:{max_age}:{min_height}:{max_height}:{birthplace}:{has_avatar}" if not search else None
    if cache_key:
        cached = _cache.get(cache_key, ttl=60)
        if cached is not None:
            return cached
    # 先计算每个演员的作品数（子查询）
    movie_count_subq = (
        select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
        .group_by(MovieActor.actor_id)
        .subquery()
    )

    # 主查询：左连接作品数
    query = select(Actor, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
    query = query.outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)

    if search:
        query = query.where(
            Actor.name.contains(search) | Actor.name_jp.contains(search)
        )

    # 作品数过滤（阈值可配：multi>=min_movies 归默认页, single<min_movies 归素人页）
    if movie_count_filter == "multi":
        query = query.where(func.coalesce(movie_count_subq.c.mc, 0) >= min_movies)
    elif movie_count_filter == "single":
        query = query.where(func.coalesce(movie_count_subq.c.mc, 0) < min_movies)

    # 高级筛选
    if cup:
        query = query.where(Actor.cup == cup)
    if min_age is not None:
        query = query.where(Actor.age >= min_age)
    if max_age is not None:
        query = query.where(Actor.age <= max_age)
    if min_height is not None:
        query = query.where(Actor.height >= min_height)
    if max_height is not None:
        query = query.where(Actor.height <= max_height)
    if birthplace:
        query = query.where(Actor.birthplace.contains(birthplace))
    if has_avatar is True:
        query = query.where(Actor.avatar_url.isnot(None), Actor.avatar_url != "")
    elif has_avatar is False:
        query = query.where((Actor.avatar_url.is_(None)) | (Actor.avatar_url == ""))
    
    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)
    
    # 排序
    if sort_by == "movie_count":
        if sort_order == "desc":
            query = query.order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
        else:
            query = query.order_by(func.coalesce(movie_count_subq.c.mc, 0).asc())
    else:
        if sort_order == "desc":
            query = query.order_by(Actor.name.desc())
        else:
            query = query.order_by(Actor.name.asc())
    
    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    rows = result.fetchall()
    
    # 手动构建响应
    items = []
    for row in rows:
        a = row[0]
        mc = row[1]
        items.append(_build_actor_response(a, mc or 0))

    resp = ActorListResponse(
        total=total or 0,
        items=items,
    )

    if cache_key:
        _cache.set(cache_key, resp)

    return resp


@router.get("/stats/overview")
async def get_actor_stats(
    session: AsyncSession = Depends(get_session),
):
    """
    获取演员统计概览

    - 总数
    - 有头像的演员数
    - 作品最多的演员 TOP 10
    """
    # 总数
    total = await session.scalar(select(func.count(Actor.id))) or 0

    # 有头像的
    with_avatar = await session.scalar(
        select(func.count(Actor.id)).where(Actor.avatar_url.isnot(None))
    ) or 0

    # 作品最多的 TOP 10
    top_query = (
        select(Actor.name, func.count(MovieActor.movie_id).label("movie_count"))
        .join(MovieActor, Actor.id == MovieActor.actor_id)
        .group_by(Actor.id)
        .order_by(func.count(MovieActor.movie_id).desc())
        .limit(10)
    )
    result = await session.execute(top_query)
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
):
    """
    启动演员头像智能补充刮削

    - 只刮削 >= min_movies 部作品且无头像的演员
    - 后台异步执行，通过 /avatar-scrape/status 查看进度
    - use_local_library=true 时优先从本地资料库（O:/MDCX/GitHub-ZIP/P1-High）匹配头像
    """
    from app.scraper.actor_avatar import run_avatar_scrape_job
    from app.db.database import get_database

    db = get_database()
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:6]}"

    background_tasks.add_task(run_avatar_scrape_job, job_id, db, min_movies, use_local_library)

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

    # 任务完成时清除演员列表缓存，确保前端能看到最新头像
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
    session: AsyncSession = Depends(get_session),
):
    """
    预览需要补充头像的演员列表（不执行刮削）

    返回符合条件的演员数量和前 20 个演员
    """
    from app.scraper.actor_avatar import actor_needs_avatar

    movie_count_subq = (
        select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
        .group_by(MovieActor.actor_id)
        .subquery()
    )

    # 候选：>= min_movies 部 + 名字有效(不含佚名/空名)
    # avatar_url 是否为空不再作为 SQL 过滤条件 —— 远程 URL / 失效路径
    # 同样属于"无有效本地头像", 由 actor_needs_avatar 在 Python 层判定
    query = (
        select(Actor, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
        .outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)
        .where(
            func.coalesce(movie_count_subq.c.mc, 0) >= min_movies,
            Actor.name != "佚名",
            Actor.name.isnot(None),
            Actor.name != "",
        )
        .order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
    )
    result = await session.execute(query)
    rows = result.fetchall()

    # 仅保留无有效本地头像者(空值 / 远程URL / 本地文件缺失)
    filtered = [r for r in rows if actor_needs_avatar(r[0])]
    total = len(filtered)

    actors = [
        {
            "id": row[0].id,
            "name": row[0].name,
            "name_jp": row[0].name_jp,
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
    session: AsyncSession = Depends(get_session),
):
    """
    从 JavDB 抓取演员资料并更新数据库

    抓取字段: 出生日期、年龄、身高、胸围、腰围、臀围、罩杯、出生地、日文名
    """
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    scraped = await _scrape_javdb_actor_profile(actor)

    if not scraped:
        return ActorScrapeResult(
            status="not_found",
            message="未在 JavDB 找到该演员的资料页面",
            scraped_fields={},
        )

    # 更新数据库
    for field, value in scraped.items():
        if hasattr(actor, field):
            setattr(actor, field, value)

    await session.commit()
    await session.refresh(actor)
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
    session: AsyncSession = Depends(get_session),
):
    """
    获取演员详情
    
    包含基本信息和最近作品
    """
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")
    
    # 统计作品数
    count_query = select(func.count(MovieActor.movie_id)).where(MovieActor.actor_id == actor_id)
    movie_count = await session.scalar(count_query) or 0
    
    # 获取最近作品
    movies_query = (
        select(Movie)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(MovieActor.actor_id == actor_id)
        .order_by(Movie.release_date.desc())
        .limit(10)
    )
    result = await session.execute(movies_query)
    recent_movies = result.scalars().all()
    
    # 手动构建响应（避免 Pydantic 访问 ORM 懒加载属性触发 MissingGreenlet）
    actor_resp = _build_actor_response(actor)
    movie_resps = []
    for m in recent_movies:
        movie_resps.append(ActorMovieResponse(
            id=m.id, code=m.code, title=m.title,
            release_date=m.release_date, cover_url=m.cover_url,
        ))

    return ActorDetailResponse(
        actor=actor_resp,
        movie_count=movie_count,
        recent_movies=movie_resps,
    )


@router.get("/{actor_id}/movies")
async def get_actor_movies(
    actor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """
    获取演员作品列表
    
    - 支持分页
    - 按发行日期倒序
    """
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")
    
    # 构建查询
    query = (
        select(Movie)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(MovieActor.actor_id == actor_id)
    )
    
    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)
    
    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(Movie.release_date.desc())
    result = await session.execute(query)
    movies = result.scalars().all()
    
    # 手动构建响应（避免 Pydantic 访问 ORM 懒加载属性触发 MissingGreenlet）
    movie_items = []
    for m in movies:
        movie_items.append(ActorMovieResponse(
            id=m.id, code=m.code, title=m.title,
            release_date=m.release_date, cover_url=m.cover_url,
        ))

    return {
        "actor_id": actor_id,
        "actor_name": actor.name,
        "total": total or 0,
        "items": movie_items,
    }


@router.get("/{actor_id}/timeline")
async def get_actor_timeline(
    actor_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取演员作品时间线（v3.4 新增）

    按年份分组统计作品数量，用于前端时间线视图（ECharts 柱状图 + 年份作品列表）。

    返回结构：
    - years: [{year, count}] 按年份排序的统计（柱状图数据）
    - details: [{year, movies: [ActorMovieResponse]}] 每年的作品列表
    - total: 总作品数
    - year_range: [最早年份, 最晚年份]
    - debut_year: 出道年份（从 actor.debut_year 或最早作品年份推断）
    """
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    # 查询该演员所有作品的发行日期
    query = (
        select(Movie)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(MovieActor.actor_id == actor_id)
        .order_by(Movie.release_date.asc())
    )
    result = await session.execute(query)
    movies = result.scalars().all()

    # 按年份分组
    from collections import defaultdict
    year_map = defaultdict(list)
    unknown_year_movies = []
    for m in movies:
        year = None
        if m.release_date:
            try:
                # release_date 可能是 "YYYY-MM-DD" 或 "YYYY/MM/DD" 等
                year = int(str(m.release_date)[:4])
            except (ValueError, TypeError):
                pass
        if year:
            year_map[year].append(m)
        else:
            unknown_year_movies.append(m)

    # 构建响应
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

    # 未知年份的作品单独返回
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

    # 出道年份：优先用 actor.debut_year，否则用最早作品年份
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
    session: AsyncSession = Depends(get_session),
):
    """获取演员的所有标签"""
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    result = await session.execute(
        select(ActorTag).where(ActorTag.actor_id == actor_id).order_by(ActorTag.created_at.desc())
    )
    tags = result.scalars().all()
    return [ActorTagResponse(id=t.id, actor_id=t.actor_id, name=t.name, color=t.color, is_user=t.is_user) for t in tags]


@router.post("/{actor_id}/tags", response_model=ActorTagResponse)
async def add_actor_tag(
    actor_id: int,
    body: ActorTagCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """为演员添加标签（如"业界第一"/"传奇"/"国民老婆"等自由文本）"""
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="标签名过长（最多 50 字符）")

    # 检查重复
    existing = await session.execute(
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
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return ActorTagResponse(id=tag.id, actor_id=tag.actor_id, name=tag.name, color=tag.color, is_user=tag.is_user)


@router.delete("/{actor_id}/tags/{tag_id}")
async def delete_actor_tag(
    actor_id: int,
    tag_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除演员标签"""
    tag = await session.get(ActorTag, tag_id)
    if not tag or tag.actor_id != actor_id:
        raise HTTPException(status_code=404, detail="标签不存在")

    await session.delete(tag)
    await session.commit()
    return {"status": "ok", "message": "标签已删除"}


@router.get("/tags/popular")
async def list_popular_tags(
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """获取热门演员标签（用于标签输入建议）"""
    result = await session.execute(
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
    session: AsyncSession = Depends(get_session),
):
    """
    更新演员信息

    - 支持更新: name, name_jp, avatar_url, birth_date, age, height, bust, waist, hip, cup, birthplace,
      name_en, alias, hobby, intro, zodiac, debut_year, social_links（v3.4 扩展）
    """
    actor = await session.get(Actor, actor_id)
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

    # social_links 需 JSON 序列化（v3.4 新增）
    if "social_links" in body and body["social_links"] is not None:
        sl = body["social_links"]
        actor.social_links = json.dumps(sl, ensure_ascii=False) if isinstance(sl, dict) else sl

    await session.commit()
    await session.refresh(actor)
    _cache.invalidate("actors:")  # 清除列表缓存
    actor_resp = _build_actor_response(actor)

    return {"status": "ok", "actor": actor_resp}


# ===== 头像管理 =====

AVATAR_DIR_NAME = "avatars"


def _get_avatar_dir() -> Path:
    """获取头像存储目录"""
    manager = get_config_manager()
    return manager.computed.data_dir / AVATAR_DIR_NAME


def _get_avatar_path(actor_id: int) -> Path:
    """获取演员头像文件路径(绝对, 不依赖 server 启动目录)"""
    return _get_avatar_dir().resolve() / f"actor_{actor_id}.jpg"


@router.post("/{actor_id}/avatar")
async def upload_actor_avatar(
    actor_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """
    上传并裁剪演员头像

    - 上传图片后自动进行人脸检测和裁剪
    - 支持 jpg/png/webp 格式
    - 裁剪后的头像统一为 400x400 像素
    """
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    # 验证文件类型
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式的图片")

    # 保存临时文件
    avatar_dir = _get_avatar_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if file.filename else "jpg"
    temp_path = avatar_dir / f"actor_{actor_id}_temp.{ext}"
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        # 人脸裁剪（延迟导入，避免启动时加载 numpy）
        from app.utils.face_crop import get_face_cropper
        output_path = _get_avatar_path(actor_id)
        cropper = get_face_cropper()
        result = cropper.crop_face(str(temp_path), str(output_path))

        if result:
            # 裁剪成功，更新数据库
            actor.avatar_url = str(output_path)
            await session.commit()
            await session.refresh(actor)
            _cache.invalidate("actors:")  # 清除列表缓存
            return {
                "status": "ok",
                "message": "头像上传并裁剪成功",
                "avatar_path": str(output_path),
            }
        else:
            # 裁剪失败但图片已保存（作为原始图）
            shutil.copy2(temp_path, output_path)
            actor.avatar_url = str(output_path)
            await session.commit()
            await session.refresh(actor)
            _cache.invalidate("actors:")  # 清除列表缓存
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
    session: AsyncSession = Depends(get_session),
):
    """获取演员头像文件

    查找顺序：
    1. DATA/avatars/actor_{id}.jpg（批量导入 / 手动上传的成品）
    2. 数据库 avatar_url 字段（仅当它是**实际文件路径**，不是 API 路径时）
    3. Gfriends 本地资料库实时查找（按 name / name_jp 匹配，无需导入即可显示）
    """
    from pathlib import Path
    from fastapi.responses import FileResponse

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    # 1. 优先: DATA/avatars/actor_{id}.jpg (导入/上传时已落盘)
    avatar_path = _get_avatar_path(actor_id)
    if avatar_path.exists() and avatar_path.is_file():
        return FileResponse(str(avatar_path), media_type="image/jpeg")

    # 2. 数据库 avatar_url 字段（跳过 API 路径,只处理实际文件路径 / 已含盘符或斜杠）
    if actor.avatar_url:
        url = actor.avatar_url.strip()
        # 明确排除 API 路径 (会造成把 /api/v1/... 当路径打开)
        is_api_path = url.startswith("/api/") or url.startswith("api/")
        is_http = url.startswith("http://") or url.startswith("https://")
        if not is_api_path and not is_http:
            try:
                p = Path(url)
                if p.exists() and p.is_file():
                    media_type = _get_image_media_type(p)
                    return FileResponse(str(p), media_type=media_type)
            except (OSError, ValueError):
                pass  # 无效路径,继续走下一步

    # 3. Gfriends 本地资料库实时查找 (未执行批量导入也能显示)
    try:
        from app.services.gfriends_importer import find_local_avatar
        local_path = find_local_avatar(actor.name, actor.name_jp)
        if local_path and local_path.exists() and local_path.is_file():
            media_type = _get_image_media_type(local_path)
            return FileResponse(str(local_path), media_type=media_type)
    except Exception:
        pass  # 本地库未配置或异常,继续

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
    session: AsyncSession = Depends(get_session),
):
    """删除演员头像"""
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    avatar_path = _get_avatar_path(actor_id)
    if avatar_path.exists():
        avatar_path.unlink()

    actor.avatar_url = None
    await session.commit()
    _cache.invalidate("actors:")  # 清除列表缓存

    return {"status": "ok", "message": "头像已删除"}


# ===== 批量演员资料刮削 =====

@router.post("/scrape-profiles/batch", response_model=BatchActorProfileScrapeResponse)
async def batch_scrape_actor_profiles(
    body: BatchActorProfileScrapeRequest = Body(...),
    session: AsyncSession = Depends(get_session),
):
    """
    批量刮削演员资料

    - 自动查找需要补充资料的演员（2部以上）
    - 支持指定刮削来源
    - 支持头像刮削
    - 来源优先级: JavDB > DMM Actress > JavWiki > AV Open > AVWikiDB > Gfriends
    """
    from app.scraper.actor_profile_scrapers import get_actor_profile_scraper, ActorProfile
    from app.utils.http_client import AsyncHttpClient

    # 1. 获取需要刮削的演员
    movie_count_subq = (
        select(MovieActor.actor_id, func.count(MovieActor.movie_id).label("mc"))
        .group_by(MovieActor.actor_id)
        .subquery()
    )

    if body.actor_ids:
        # 指定演员ID列表
        query = (
            select(Actor, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
            .outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)
            .where(Actor.id.in_(body.actor_ids))
        )
    else:
        # 自动查找需要补充资料的演员
        query = (
            select(Actor, func.coalesce(movie_count_subq.c.mc, 0).label("movie_cnt"))
            .outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)
            .where(
                func.coalesce(movie_count_subq.c.mc, 0) >= body.min_movies,
                Actor.name != "佚名",
                Actor.name.isnot(None),
                Actor.name != "",
            )
            .order_by(func.coalesce(movie_count_subq.c.mc, 0).desc())
            .limit(100)  # 限制单次刮削数量
        )

    result = await session.execute(query)
    actors_data = result.fetchall()

    total = len(actors_data)
    success = 0
    failed = 0
    results = []

    # 2. 获取刮削器
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
            # 刮削资料
            profile = await scraper.get_profile(
                name=actor.name,
                name_jp=actor.name_jp,
                preferred_sources=body.sources,
            )

            if profile and profile.name:
                scraped_fields = {}

                # 更新资料字段
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
                            # 只更新空字段
                            if not current_value or current_value == "":
                                setattr(actor, actor_field, value)
                                scraped_fields[actor_field] = value

                # 社交账号需 JSON 序列化存储（v3.4 新增）
                if profile.social_links and not actor.social_links:
                    actor.social_links = json.dumps(profile.social_links, ensure_ascii=False)
                    scraped_fields["social_links"] = profile.social_links

                # 更新头像
                if body.include_avatar and profile.avatar_url and not actor.avatar_url:
                    # 下载并保存头像
                    avatar_path = await _download_actor_avatar(
                        actor.id, profile.avatar_url, actor.name
                    )
                    if avatar_path:
                        actor.avatar_url = str(avatar_path)
                        scraped_fields["avatar_url"] = str(avatar_path)
                        result_item["avatar_updated"] = True

                if scraped_fields:
                    await session.commit()
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

        # 限速
        await asyncio.sleep(0.5)

    # 清除缓存
    _cache.invalidate("actors:")

    return BatchActorProfileScrapeResponse(
        total=total,
        success=success,
        failed=failed,
        results=results,
    )


async def _download_actor_avatar(
    actor_id: int, url: str, actor_name: str = ""
) -> Optional[Path]:
    """下载演员头像到本地"""
    from app.config.manager import get_config_manager

    manager = get_config_manager()
    avatar_dir = manager.computed.data_dir / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)

    output_path = (avatar_dir / f"actor_{actor_id}.jpg").resolve()

    async with AsyncHttpClient(timeout=30) as client:
        try:
            # 提取域名用于 Referer
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
        # 尝试新配置路径
        cfg = get_config()
        if hasattr(cfg, "crawler") and cfg.crawler.javdb_cookie:
            return {"cookie": cfg.crawler.javdb_cookie, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        # 回退旧配置路径
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
    # 提取数字
    import re
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    return None


def _parse_cup(text: str) -> Optional[str]:
    """解析罩杯"""
    if not text:
        return None
    text = text.strip().upper()
    # 匹配 A-Z 罩杯
    import re
    match = re.search(r"([A-Z])", text)
    if match:
        return match.group(1)
    return None


def _parse_birth_date(text: str) -> Optional[str]:
    """解析出生日期"""
    if not text:
        return None
    text = text.strip()
    # 常见格式: 1990-01-15, 1990/01/15, 1990年01月15日
    import re
    match = re.search(r"(\d{4})[-/\年.](\d{1,2})[-/\月.](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return None


async def _scrape_javdb_actor_profile(actor: Actor) -> dict:
    """
    从 JavDB 抓取演员资料

    返回: 解析到的资料字段字典
    """
    from parsel import Selector
    from app.utils.http_client import AsyncHttpClient

    result: dict = {}
    cookie_headers = _get_javdb_cookie_headers() or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with AsyncHttpClient(timeout=20) as client:
        # 1. 搜索演员页面
        search_name = actor.name_jp or actor.name
        search_url = f"https://javdb.com/search?q={search_name}&f=actor"
        logger.info(f"搜索 JavDB 演员: {search_name}")

        try:
            search_html = await client.get_text(search_url, headers=cookie_headers)
        except Exception as e:
            logger.error(f"JavDB 搜索失败: {e}")
            return result

        sel = Selector(search_html)

        # 2. 提取第一个演员链接
        # JavDB 搜索结果: <a href="/actors/{id}/{name}">
        # 过滤掉分类链接如 /actors/censored, /actors/uncensored
        actor_links = []
        for link in sel.xpath('//a[contains(@href, "/actors/")]/@href').getall():
            # 真实演员链接格式: /actors/{id}/{name} (至少3个部分)
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

        # 3. 获取演员详情页
        try:
            profile_html = await client.get_text(actor_url, headers=cookie_headers)
        except Exception as e:
            logger.error(f"获取演员详情页失败: {e}")
            return result

        # 4. 解析资料
        profile_sel = Selector(profile_html)

        # 页面标题中的日文名
        page_title = profile_sel.css("title::text").get()
        if page_title:
            title_part = page_title.split("|")[0].strip()
            if title_part and not actor.name_jp:
                result["name_jp"] = title_part

        # 解析表格/面板中的 label-value 对
        # JavDB 用多种格式展示，尝试多种 XPath
        label_value_pairs: list[tuple[str, str]] = []

        # 格式1: div.panel-block / div.item 中的 label + value
        blocks = profile_sel.xpath('//*[contains(@class, "panel-block") or contains(@class, "info") or contains(@class, "item")]')
        for block in blocks:
            texts = block.xpath('.//text()').getall()
            joined = " ".join(t.strip() for t in texts if t.strip())
            for label in _JAVDB_LABEL_MAP:
                if label in joined:
                    # 提取 label 之后的值
                    idx = joined.find(label)
                    rest = joined[idx + len(label):]
                    # 清理分隔符
                    rest = rest.replace(":", "").replace("：", "").strip()
                    # 取第一部分（到下一个 label 之前）
                    # 找下一个 label 的位置
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

        # 格式2: table 中的 th/td 对
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

        # 格式3: 直接包含关键字的行
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

        # 去重，保留第一个
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
                # 格式: 88 - 60 - 90 或 88/60/90
                import re
                nums = re.findall(r"\d+", value)
                if len(nums) >= 3:
                    result["bust"] = int(nums[0])
                    result["waist"] = int(nums[1])
                    result["hip"] = int(nums[2])
            elif field == "birthplace":
                result["birthplace"] = value
            elif field == "name_jp":
                if not actor.name_jp:
                    result["name_jp"] = value

        logger.info(f"抓取到演员 {actor.name} 资料: {result}")
        return result
