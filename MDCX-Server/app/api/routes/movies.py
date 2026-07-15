"""
媒体管理路由
"""

import json
import time
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import logging

from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor, MovieTag, Tag, Studio, Series, FavoriteItem, FavoriteGroup

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 轻量级内存缓存（不依赖数据库，纯内存，TTL 过期） =====

class _SimpleCache:
    """简单的 TTL 内存缓存，避免列表查询反复打数据库"""
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
        # 防止缓存无限增长
        if len(self._store) > 500:
            # 删除最旧的 20%
            sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k][0])
            for k in sorted_keys[:100]:
                del self._store[k]

    def invalidate(self, prefix: str = "") -> None:
        """按前缀清除缓存"""
        if not prefix:
            self._store.clear()
            return
        keys_to_del = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_del:
            del self._store[k]

_cache = _SimpleCache()


def _parse_sample_images(raw: str | None) -> list[str]:
    """解析 sample_images 字段（JSON 数组或逗号分隔）"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(u) for u in parsed if u]
    except (json.JSONDecodeError, TypeError):
        pass
    # 回退：逗号分隔
    return [u.strip() for u in raw.split(",") if u.strip()]


def _parse_json_list(raw: str | None) -> list[str]:
    """解析 genre/tag 字段（JSON 数组或逗号分隔）为字符串列表"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [x.strip() for x in raw.split(",") if x.strip()]


class ActorBrief(BaseModel):
    """演员简要信息（用于影片详情中的演员列表）"""
    id: int
    name: str

    class Config:
        from_attributes = True


class TagBrief(BaseModel):
    """标签简要信息（用于影片响应中的标签列表）

    is_user: True=用户标签 / False=抓取标签
    """
    id: int
    name: str
    is_user: bool = False

    class Config:
        from_attributes = True


class MovieResponse(BaseModel):
    """视频响应模型"""
    id: int
    code: str
    title: Optional[str] = None
    original_title: Optional[str] = None
    title_jp: Optional[str] = None
    studio_id: Optional[int] = None
    studio: Optional[str] = None  # 从 Studio 表关联获取
    maker: Optional[str] = None
    series_id: Optional[int] = None
    series: Optional[str] = None  # 从 Series 表关联获取
    director: Optional[str] = None
    release_date: Optional[str] = None
    duration: Optional[int] = None
    rating: Optional[float] = None
    plot: Optional[str] = None
    plot_short: Optional[str] = None
    genre: list[str] = []
    tag: list[str] = []
    cover_url: Optional[str] = None
    poster_url: Optional[str] = None
    thumb_url: Optional[str] = None
    trailer_url: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    is_uncensored: Optional[bool] = None
    is_mosaic: Optional[bool] = None
    is_chinese: Optional[bool] = None
    is_leak: Optional[bool] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    sample_images: list[str] = []
    play_count: int = 0
    last_played_at: Optional[str] = None
    status: str
    actors: list[ActorBrief] = []
    tags: list[TagBrief] = []  # 从 MovieTag 关联表查询的结构化标签列表

    class Config:
        from_attributes = True


class MovieListResponse(BaseModel):
    """视频列表响应"""
    total: int
    items: list[MovieResponse]


@router.get("", response_model=MovieListResponse)
async def list_movies(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    maker: Optional[str] = None,
    studio: Optional[str] = None,
    series: Optional[str] = None,
    tag_id: Optional[int] = None,
    tag_ids: Optional[str] = Query(None, description="多个标签ID，逗号分隔，如 '1,2,3'"),
    tag_mode: str = Query("OR", description="标签筛选模式: OR（任一匹配）/ AND（全部匹配）"),
    actor_id: Optional[int] = None,
    is_favorite: Optional[bool] = Query(None, description="仅收藏: true仅收藏 / false仅非收藏 / null全部"),
    favorite_group_id: Optional[int] = Query(None, description="收藏夹分组ID，配合 is_favorite=true 使用"),
    min_rating: Optional[float] = Query(None, description="评分下限（含）"),
    max_rating: Optional[float] = Query(None, description="评分上限（含）"),
    letter: Optional[str] = Query(None, description="番号首字母过滤（A-Z 或 #，#表示数字开头）"),
    sort: Optional[str] = Query(None, description="排序字段: release_date, duration, play_count, title, file_size, rating, last_played_at。前缀-表示降序"),
    seed: Optional[int] = Query(None, description="随机种子，提供时按种子做可复现随机排序"),
    session: AsyncSession = Depends(get_session),
):
    """获取视频列表（带内存缓存，60秒 TTL）

    支持多标签 AND/OR 筛选、收藏过滤、评分区间过滤。
    """
    # 解析多标签
    tag_id_list: list[int] = []
    if tag_ids:
        for part in tag_ids.split(","):
            part = part.strip()
            if part.isdigit():
                tag_id_list.append(int(part))
    if tag_id and tag_id not in tag_id_list:
        tag_id_list.append(tag_id)

    tag_mode_upper = (tag_mode or "OR").upper()
    if tag_mode_upper not in ("AND", "OR"):
        tag_mode_upper = "OR"

    # 搜索/排序/随机/多标签/收藏/评分/字母查询不缓存
    cacheable = (
        not search and not sort and seed is None
        and not tag_id_list and is_favorite is None
        and favorite_group_id is None and min_rating is None and max_rating is None
        and not letter
    )
    cache_key = (
        f"movies:list:{page}:{page_size}:{status}:{maker}:{studio}:{series}:{tag_id}:{actor_id}"
        if cacheable else None
    )
    if cache_key:
        cached = _cache.get(cache_key, ttl=60)
        if cached is not None:
            return cached

    # 构建查询
    query = select(Movie)

    if status:
        query = query.where(Movie.status == status)

    if search:
        # 番号搜索用前缀匹配（可利用索引），标题搜索用 contains
        query = query.where(
            Movie.code.startswith(search) | Movie.title.contains(search)
        )

    if maker:
        query = query.where(Movie.maker == maker)

    if studio:
        # 通过 Studio FK 关联筛选
        query = query.join(Studio, Movie.studio_id == Studio.id).where(Studio.name == studio)

    if series:
        # 通过 Series FK 关联筛选
        query = query.join(Series, Movie.series_id == Series.id).where(Series.name == series)

    # 多标签 AND/OR 筛选
    if tag_id_list:
        if tag_mode_upper == "AND":
            # 必须拥有所有指定标签：用 GROUP BY movie_id HAVING COUNT(DISTINCT tag_id) = N
            query = query.join(MovieTag, Movie.id == MovieTag.movie_id).where(
                MovieTag.tag_id.in_(tag_id_list)
            ).group_by(Movie.id).having(
                func.count(func.distinct(MovieTag.tag_id)) == len(tag_id_list)
            )
        else:
            # OR: 至少匹配一个标签
            query = query.join(MovieTag, Movie.id == MovieTag.movie_id).where(
                MovieTag.tag_id.in_(tag_id_list)
            )

    if actor_id:
        query = query.join(MovieActor, Movie.id == MovieActor.movie_id).where(MovieActor.actor_id == actor_id)

    # 收藏过滤
    if is_favorite is True or favorite_group_id is not None:
        fav_subq = (
            select(FavoriteItem.entity_id)
            .where(FavoriteItem.entity_type == "movie")
        )
        if favorite_group_id is not None:
            fav_subq = fav_subq.where(FavoriteItem.group_id == favorite_group_id)
        query = query.where(Movie.id.in_(fav_subq))
    elif is_favorite is False:
        fav_subq = (
            select(FavoriteItem.entity_id)
            .where(FavoriteItem.entity_type == "movie")
        )
        query = query.where(~Movie.id.in_(fav_subq))

    # 评分区间
    if min_rating is not None:
        query = query.where(Movie.rating >= min_rating)
    if max_rating is not None:
        query = query.where(Movie.rating <= max_rating)

    # 首字母过滤
    if letter:
        norm = letter.strip().upper()
        if norm == "#":
            # 数字开头
            first = func.upper(func.substr(Movie.code, 1, 1))
            query = query.where(first.between("0", "9"))
        elif len(norm) == 1 and norm.isalpha():
            query = query.where(func.upper(func.substr(Movie.code, 1, 1)) == norm)

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    # 排序逻辑
    if seed is not None:
        # 可复现随机排序：用 seed 对 id 做模运算，产生确定性伪随机顺序
        query = query.order_by((Movie.id * seed) % 9973, Movie.id)
    elif sort:
        sort_map = {
            "release_date": Movie.release_date,
            "duration": Movie.duration,
            "play_count": Movie.play_count,
            "title": Movie.title,
            "file_size": Movie.file_size,
            "rating": Movie.rating,
            "last_played_at": Movie.last_played_at,
        }
        if sort.startswith("-"):
            field_name = sort[1:]
            col = sort_map.get(field_name)
            if col is not None:
                query = query.order_by(col.desc().nulls_last(), Movie.id.desc())
            else:
                query = query.order_by(Movie.id.desc())
        else:
            col = sort_map.get(sort)
            if col is not None:
                query = query.order_by(col.asc().nulls_last(), Movie.id.desc())
            else:
                query = query.order_by(Movie.id.desc())
    else:
        query = query.order_by(Movie.id.desc())

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    movies = result.scalars().all()

    # 批量获取演员列表（避免 MissingGreenlet 错误）
    movie_ids = [m.id for m in movies]
    actor_map = {}
    if movie_ids:
        actor_query = (
            select(MovieActor.movie_id, Actor.id, Actor.name)
            .join(Actor, Actor.id == MovieActor.actor_id)
            .where(MovieActor.movie_id.in_(movie_ids))
        )
        actor_result = await session.execute(actor_query)
        for movie_id, actor_id, actor_name in actor_result.fetchall():
            actor_map.setdefault(movie_id, []).append(ActorBrief(id=actor_id, name=actor_name))

    # 批量获取 studio/series 名称
    studio_ids = {m.studio_id for m in movies if m.studio_id}
    series_ids = {m.series_id for m in movies if m.series_id}
    studio_map = {}
    series_map = {}
    if studio_ids:
        studio_result = await session.execute(
            select(Studio.id, Studio.name).where(Studio.id.in_(studio_ids))
        )
        for sid, sname in studio_result.fetchall():
            studio_map[sid] = sname
    if series_ids:
        series_result = await session.execute(
            select(Series.id, Series.name).where(Series.id.in_(series_ids))
        )
        for sid, sname in series_result.fetchall():
            series_map[sid] = sname

    # 批量获取标签列表（从 MovieTag 关联表 + Tag 表 join）
    tag_map: dict[int, list[TagBrief]] = {}
    if movie_ids:
        tag_query = (
            select(MovieTag.movie_id, Tag.id, Tag.name, Tag.is_user)
            .join(Tag, Tag.id == MovieTag.tag_id)
            .where(MovieTag.movie_id.in_(movie_ids))
        )
        tag_result = await session.execute(tag_query)
        for movie_id, tag_id, tag_name, tag_is_user in tag_result.fetchall():
            tag_map.setdefault(movie_id, []).append(
                TagBrief(id=tag_id, name=tag_name, is_user=bool(tag_is_user))
            )

    # 手动构建响应（避免 Pydantic 访问 ORM 懒加载属性）
    items = []
    for m in movies:
        item = MovieResponse(
            id=m.id,
            code=m.code,
            title=m.title,
            original_title=m.original_title,
            title_jp=m.title_jp,
            studio_id=m.studio_id,
            studio=studio_map.get(m.studio_id) if m.studio_id else None,
            maker=m.maker,
            series_id=m.series_id,
            series=series_map.get(m.series_id) if m.series_id else None,
            director=m.director,
            release_date=m.release_date,
            duration=m.duration,
            rating=m.rating,
            plot=m.plot,
            plot_short=m.plot_short,
            genre=_parse_json_list(m.genre),
            tag=_parse_json_list(m.tag),
            cover_url=m.cover_url,
            poster_url=m.poster_url,
            thumb_url=m.thumb_url,
            trailer_url=m.trailer_url,
            source=m.source,
            source_url=m.source_url,
            is_uncensored=m.is_uncensored,
            is_mosaic=m.is_mosaic,
            is_chinese=m.is_chinese,
            is_leak=m.is_leak,
            file_path=m.file_path,
            file_size=m.file_size,
            sample_images=_parse_sample_images(m.sample_images),
            play_count=m.play_count or 0,
            last_played_at=m.last_played_at.isoformat() if m.last_played_at else None,
            status=m.status,
            actors=actor_map.get(m.id, []),
            tags=tag_map.get(m.id, []),
        )
        items.append(item)

    resp = MovieListResponse(
        total=total or 0,
        items=items,
    )

    # 缓存结果
    if cache_key:
        _cache.set(cache_key, resp)

    return resp


@router.get("/alphabet")
async def get_alphabet_groups(
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """番号首字母分组导航

    返回 A-Z + # (数字开头) 的分组与每组的影片数量。
    前端用于"番号首字母导航条"快速跳转。
    """
    cache_key = f"movies:alphabet:{status}"
    cached = _cache.get(cache_key, ttl=120)
    if cached is not None:
        return cached

    # 提取 code 首字符：字母归 A-Z，数字归 #
    # SQLite 的 substr 等价于 Python 切片
    first_char = func.upper(func.substr(Movie.code, 1, 1))
    query = select(
        first_char.label("letter"),
        func.count(Movie.id).label("cnt"),
    ).group_by(first_char)

    if status:
        query = query.where(Movie.status == status)

    result = await session.execute(query)
    raw: dict[str, int] = {}
    for letter, cnt in result.fetchall():
        if letter is None:
            continue
        if letter.isdigit():
            raw["#"] = raw.get("#", 0) + (cnt or 0)
        elif letter.isalpha():
            raw[letter] = raw.get(letter, 0) + (cnt or 0)
        else:
            # 其他字符归到 #
            raw["#"] = raw.get("#", 0) + (cnt or 0)

    # 构造 A-Z + # 的完整序列（即使某字母没有影片也返回 0）
    letters = [chr(ord("A") + i) for i in range(26)] + ["#"]
    groups = [{"letter": l, "count": raw.get(l, 0)} for l in letters]
    total = sum(g["count"] for g in groups)

    resp = {"groups": groups, "total": total}
    _cache.set(cache_key, resp)
    return resp


def _image_media_type(p: str) -> str:
    """根据扩展名推断图片 media_type"""
    s = Path(p).suffix.lower()
    if s == '.png':
        return "image/png"
    if s == '.webp':
        return "image/webp"
    if s == '.gif':
        return "image/gif"
    return "image/jpeg"


async def _backfill_cover(movie, path_str: str, session: AsyncSession) -> None:
    """命中目录兜底封面时，回填 movie.cover_url，使前端后续请求直接命中、不再走占位图"""
    try:
        if not movie.cover_url:
            movie.cover_url = path_str
            await session.commit()
    except Exception:
        # 回填失败不应影响本次图片返回
        pass


async def _resolve_cover_path(movie, t_param: Optional[str], session: AsyncSession) -> Optional[str]:
    """智能解析封面路径，返回存在的文件路径或 None。

    解析顺序：
      1) DB 记录的 cover_url / poster_url / thumb_url（绝对路径且存在）
      2) output_dir（服务端 data/movies/<code>/）下的标准图片名
      3) 前端传入的 t 参数
      4) 兜底扫描影片所在目录
    """
    # 1) DB 记录的封面路径
    for attr in ('cover_url', 'poster_url', 'thumb_url'):
        p = getattr(movie, attr, None)
        if p and Path(p).exists() and Path(p).is_file():
            return p

    # 2) 服务端 output_dir 下的标准图片名
    output_dir = getattr(movie, 'output_dir', None)
    if output_dir:
        od = Path(output_dir)
        if od.exists() and od.is_dir():
            for img_name in ('poster.jpg', 'cover.jpg', 'fanart.jpg', 'thumb.jpg'):
                img_path = od / img_name
                if img_path.exists() and img_path.is_file():
                    # 回填 DB 字段，下次直接命中第 1 步
                    try:
                        if img_name in ('poster.jpg', 'cover.jpg'):
                            movie.cover_url = str(img_path)
                        elif img_name == 'thumb.jpg':
                            movie.thumb_url = str(img_path)
                        elif img_name == 'fanart.jpg':
                            movie.poster_url = str(img_path)
                        await session.commit()
                    except Exception:
                        pass
                    return str(img_path)
            # 也试试 <番号>-poster.jpg 等命名
            code = getattr(movie, 'code', '')
            if code:
                for suffix in ('-poster.jpg', '-fanart.jpg', '-thumb.jpg', '-cover.jpg'):
                    img_path = od / f"{code}{suffix}"
                    if img_path.exists() and img_path.is_file():
                        return str(img_path)

    # 3) 前端传来的 t 参数（候选封面绝对路径）
    if t_param:
        tp = Path(t_param)
        if tp.exists() and tp.is_file() and tp.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            await _backfill_cover(movie, str(tp), session)
            return str(tp)

    # 3) 兜底：扫描影片所在目录
    if movie.file_path:
        d = Path(movie.file_path).parent
        if d.exists():
            from app.importer.image_scanner import ImageScanner
            imgs = ImageScanner().scan(str(d))
            for cand in (imgs.poster, imgs.fanart, imgs.thumb):
                if cand and Path(cand).exists() and Path(cand).is_file():
                    await _backfill_cover(movie, cand, session)
                    return cand
            # 仍无语义匹配：取目录里第一张图片作为兜底封面
            for fp in sorted(d.iterdir()):
                if fp.is_file() and fp.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                    await _backfill_cover(movie, str(fp), session)
                    return str(fp)
    return None


def _web_cover_redirect(movie) -> Optional["RedirectResponse"]:
    """封面是相对 web 路径(如 /pics/cover/)或远程 URL 时，直接 302 到该地址由 app/源站提供。

    规则3 兼容：部分历史刮削封面存的是 javbus 相对路径 /pics/cover/* 或远程 URL，
    这些并非本地文件（Path.exists() 必然 False），但 app 本身能直接提供，故 302 兜底，
    避免 /cover/file 等端点对相对路径封面返回 404 导致裂图。
    """
    from fastapi.responses import RedirectResponse
    for attr in ('cover_url', 'poster_url', 'thumb_url'):
        u = getattr(movie, attr, None)
        if u and (u.startswith('/') or u.startswith('http://') or u.startswith('https://')):
            return RedirectResponse(url=u)
    return None


@router.get("/{movie_id}/cover/file")
async def get_movie_cover_file(
    movie_id: int,
    t: Optional[str] = Query(None, description="前端传来的候选封面路径（兜底使用）"),
    session: AsyncSession = Depends(get_session),
):
    """获取电影封面图片文件（智能解析：DB 路径 -> t 参数 -> 目录扫描兜底）"""
    from fastapi.responses import FileResponse
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    path_str = await _resolve_cover_path(movie, t, session)
    if path_str:
        return FileResponse(str(path_str), media_type=_image_media_type(path_str))

    # 兜底：封面为相对 web 路径或远程 URL（如历史 javbus /pics/cover/）时 302 到源地址
    redir = _web_cover_redirect(movie)
    if redir:
        return redir

    raise HTTPException(status_code=404, detail="封面图片不存在")


async def run_cover_backfill(session: AsyncSession, limit: int = 2000) -> dict:
    """为 cover_url 为空的影片回填封面（扫描其所在目录的任意图片）。

    修复历史导入中因 image_scanner 漏判（如 {番号}.jpg 命名、或目录只有视频+图片）导致的
    封面缺失：这些影片 cover_url 为空，前端直接显示占位图。本函数扫描影片目录找回封面并更新。
    """
    from app.importer.image_scanner import ImageScanner

    scanner = ImageScanner()
    # 仅处理 cover_url 为空、且有视频路径（可定位目录）的影片
    rows = await session.execute(
        select(Movie).where(
            Movie.cover_url.is_(None),
            Movie.file_path.isnot(None),
        ).limit(limit)
    )
    movies = rows.scalars().all()

    scanned = 0
    updated = 0
    for m in movies:
        scanned += 1
        d = Path(m.file_path).parent
        if not d.exists():
            continue
        imgs = scanner.scan(str(d))
        cand = imgs.poster or imgs.fanart or imgs.thumb
        if not cand:
            for fp in sorted(d.iterdir()):
                if fp.is_file() and fp.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                    cand = str(fp)
                    break
        if cand and Path(cand).exists() and Path(cand).is_file():
            m.cover_url = cand
            updated += 1
    await session.commit()
    return {"status": "ok", "scanned": scanned, "updated": updated, "remaining_null": scanned - updated}


@router.post("/backfill-covers")
async def backfill_covers(
    limit: int = Query(2000, ge=1, le=20000, description="最多处理多少部影片"),
    session: AsyncSession = Depends(get_session),
):
    """为 cover_url 为空的影片回填封面（扫描其所在目录的任意图片），供手动触发。"""
    return await run_cover_backfill(session, limit)


# ===== file_path 回填 =====
VIDEO_EXTENSIONS_FOR_BACKFILL = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
    ".iso", ".rmvb", ".rm", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm",
    ".vob", ".ogv", ".divx", ".asf", ".tp", ".mts",
}


@router.post("/backfill-file-paths")
async def backfill_file_paths(
    limit: int = Query(5000, ge=1, le=50000, description="最多处理多少部影片"),
    session: AsyncSession = Depends(get_session),
):
    """为 file_path 为空但有 cover_url 的影片回填视频文件路径。

    根因：早期导入使用 conflict_strategy='skip'，已存在的影片不会更新 file_path，
    导致全部影片 file_path 为 NULL，前端无法播放。

    本端点从 cover_url 所在目录扫描视频文件，回填到 file_path 字段。
    """
    # 查询 file_path 为空但有 cover_url 的影片
    rows = await session.execute(
        select(Movie).where(
            or_(Movie.file_path.is_(None), Movie.file_path == ""),
            Movie.cover_url.isnot(None),
        ).limit(limit)
    )
    movies = rows.scalars().all()

    scanned = 0
    updated = 0
    not_found = 0
    dir_missing = 0

    for m in movies:
        scanned += 1
        cover_url = m.cover_url or ""
        if not cover_url:
            continue

        try:
            cover_path = Path(cover_url)
            movie_dir = cover_path.parent
            if not movie_dir.exists():
                dir_missing += 1
                continue

            # 在封面所在目录扫描视频文件
            found_video = None
            for f in movie_dir.iterdir():
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS_FOR_BACKFILL:
                    found_video = str(f)
                    break

            if found_video:
                m.file_path = found_video
                try:
                    m.file_size = Path(found_video).stat().st_size
                except Exception:
                    pass
                updated += 1
            else:
                not_found += 1
        except (PermissionError, OSError):
            dir_missing += 1
            continue

    await session.commit()

    return {
        "status": "ok",
        "scanned": scanned,
        "updated": updated,
        "not_found": not_found,
        "dir_missing": dir_missing,
        "remaining_null": scanned - updated,
    }


@router.get("/{movie_id}/poster/file")
async def get_movie_poster_file(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取电影背景图文件"""
    from fastapi.responses import FileResponse
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    path_str = movie.poster_url
    if path_str:
        from pathlib import Path
        p = Path(path_str)
        if p.exists() and p.is_file():
            media_type = "image/jpeg"
            if p.suffix.lower() in ('.png',):
                media_type = "image/png"
            elif p.suffix.lower() in ('.webp',):
                media_type = "image/webp"
            return FileResponse(str(p), media_type=media_type)

    # 服务端 output_dir 兜底
    if movie.output_dir:
        od = Path(movie.output_dir)
        if od.exists() and od.is_dir():
            for img_name in ('fanart.jpg', 'poster.jpg', 'cover.jpg'):
                img_path = od / img_name
                if img_path.exists() and img_path.is_file():
                    movie.poster_url = str(img_path)
                    await session.commit()
                    return FileResponse(str(img_path), media_type="image/jpeg")

    redir = _web_cover_redirect(movie)
    if redir:
        return redir

    raise HTTPException(status_code=404, detail="背景图不存在")


@router.get("/{movie_id}/thumb/file")
async def get_movie_thumb_file(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取电影缩略图文件（用于 thumbnail 视图模式）

    缩略图通常是 ffmpeg 截取的视频帧，比封面更代表实际内容。
    回退顺序：thumb_url -> cover_url（保证总有图可显示）
    """
    from fastapi.responses import FileResponse
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 优先 thumb_url，回退到 cover_url
    for url_attr in ['thumb_url', 'cover_url']:
        path_str = getattr(movie, url_attr, None)
        if path_str:
            from pathlib import Path
            p = Path(path_str)
            if p.exists() and p.is_file():
                media_type = "image/jpeg"
                if p.suffix.lower() in ('.png',):
                    media_type = "image/png"
                elif p.suffix.lower() in ('.webp',):
                    media_type = "image/webp"
                return FileResponse(str(p), media_type=media_type)

    # 服务端 output_dir 兜底
    if movie.output_dir:
        od = Path(movie.output_dir)
        if od.exists() and od.is_dir():
            for img_name in ('thumb.jpg', 'cover.jpg', 'poster.jpg'):
                img_path = od / img_name
                if img_path.exists() and img_path.is_file():
                    return FileResponse(str(img_path), media_type="image/jpeg")

    redir = _web_cover_redirect(movie)
    if redir:
        return redir

    raise HTTPException(status_code=404, detail="缩略图不存在")


# ===== 视频播放 =====
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".webm"}


@router.get("/{movie_id}/play")
async def play_video(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取视频播放地址
    
    返回视频流URL，支持 HTML5 video 直接播放
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = file_path.suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持播放 {ext} 格式")

    media_type = "video/mp4"
    if ext == ".mkv":
        media_type = "video/x-matroska"
    elif ext == ".avi":
        media_type = "video/x-msvideo"
    elif ext == ".mov":
        media_type = "video/quicktime"
    elif ext == ".ts":
        media_type = "video/mp2t"
    elif ext == ".webm":
        media_type = "video/webm"

    # 记录播放次数
    movie.play_count = (movie.play_count or 0) + 1
    movie.last_played_at = datetime.now()
    await session.commit()
    _cache.invalidate("movies:")

    return {
        "movie_id": movie_id,
        "code": movie.code,
        "title": movie.title,
        "video_url": f"/api/v1/movies/{movie_id}/play/file",
        "media_type": media_type,
        "file_size": movie.file_size,
        "play_count": movie.play_count,
    }


@router.get("/{movie_id}/play/file")
async def play_video_file(
    movie_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    视频文件流播放

    支持 Range 请求（拖动进度条/快进/快退）
    - 普通 GET: 200 OK + 完整文件 + Content-Length
    - Range GET (e.g. bytes=0-1023): 206 Partial Content + Content-Range
    """
    from starlette.responses import StreamingResponse, Response

    movie = await session.get(Movie, movie_id)
    if not movie or not movie.file_path:
        raise HTTPException(status_code=404, detail="视频不存在")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = file_path.suffix.lower()
    media_type = "video/mp4"
    if ext == ".mkv":
        media_type = "video/x-matroska"
    elif ext == ".avi":
        media_type = "video/x-msvideo"
    elif ext == ".webm":
        media_type = "video/webm"
    elif ext == ".mov":
        media_type = "video/quicktime"
    elif ext == ".ts":
        media_type = "video/mp2t"

    file_size = file_path.stat().st_size

    # 解析 Range header（如 "bytes=0-1023"）
    range_header = request.headers.get("range") or request.headers.get("Range")
    range_start = 0
    range_end = file_size - 1
    status_code = 200
    content_range = None

    if range_header:
        try:
            # 仅处理 "bytes=START-END" 格式
            units, _, range_spec = range_header.partition("=")
            if units.strip() == "bytes" and range_spec:
                start_str, _, end_str = range_spec.partition("-")
                if start_str == "":
                    # 后缀范围 bytes=-N (取最后 N 字节)
                    suffix_len = int(end_str) if end_str else 0
                    range_start = max(0, file_size - suffix_len)
                    range_end = file_size - 1
                else:
                    range_start = int(start_str)
                    if end_str:
                        range_end = min(int(end_str), file_size - 1)
                    else:
                        range_end = file_size - 1
                if range_start > range_end or range_start >= file_size:
                    raise HTTPException(status_code=416, detail="Range Not Satisfiable")
                status_code = 206
                content_range = f"bytes {range_start}-{range_end}/{file_size}"
        except HTTPException:
            raise
        except Exception:
            # Range 解析失败，回退到完整返回
            range_start = 0
            range_end = file_size - 1
            status_code = 200

    chunk_size = 1024 * 1024  # 1MB

    def iter_range():
        with open(file_path, "rb") as f:
            f.seek(range_start)
            remaining = range_end - range_start + 1
            while remaining > 0:
                data = f.read(min(chunk_size, remaining))
                if not data:
                    break
                yield data
                remaining -= len(data)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(range_end - range_start + 1),
        "Cache-Control": "no-cache",
    }
    if content_range:
        headers["Content-Range"] = content_range

    return StreamingResponse(
        iter_range(),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


@router.get("/{movie_id}/thumbnails")
async def get_movie_thumbnails(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取影片缩略图列表（已生成的截图）"""
    from app.services.thumbnail import get_thumbnails
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    thumbs = get_thumbnails(movie_id)
    return {"movie_id": movie_id, "thumbnails": thumbs, "count": len(thumbs)}


@router.post("/{movie_id}/thumbnails/generate")
async def generate_movie_thumbnails(
    movie_id: int,
    force: bool = Query(False, description="强制重新生成"),
    session: AsyncSession = Depends(get_session),
):
    """为影片生成缩略图截图（需要 ffmpeg）"""
    from app.services.thumbnail import generate_thumbnails
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片没有关联文件")

    thumbs = generate_thumbnails(movie_id, movie.file_path, movie.file_size, force)
    if not thumbs:
        return {"status": "empty", "message": "未生成截图（ffmpeg 未安装或文件无法读取）", "thumbnails": []}

    return {"status": "ok", "movie_id": movie_id, "thumbnails": thumbs, "count": len(thumbs)}


@router.get("/dirs")
async def get_movie_directories(
    session: AsyncSession = Depends(get_session),
):
    """获取数据库中所有影片的目录列表（用于补刮目录选择）"""
    from sqlalchemy import text as sql_text
    result = await session.execute(
        sql_text(
            "SELECT DISTINCT output_dir FROM movies "
            "WHERE output_dir IS NOT NULL AND output_dir != '' "
            "ORDER BY output_dir"
        )
    )
    dirs = [row[0] for row in result.fetchall()]
    return {"dirs": dirs}


@router.get("/scan")
async def scan_movies(
    directory: str = Query(..., description="要扫描的目录路径"),
    session: AsyncSession = Depends(get_session),
):
    """扫描目录中的视频文件"""
    from pathlib import Path
    from app.scraper.number import extract_number

    scan_dir = Path(directory)
    if not scan_dir.exists() or not scan_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在: {directory}")

    # 支持的视频扩展名
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".iso"}

    files = []
    for f in scan_dir.rglob("*"):
        if f.suffix.lower() in video_exts and f.is_file():
            number_result = extract_number(f.name)
            files.append({
                "path": str(f),
                "filename": f.name,
                "size": f.stat().st_size,
                "number": number_result.number,
                "number_type": number_result.number_type.value if number_result.number_type else None,
                "has_number": bool(number_result.number),
            })

    return {
        "directory": directory,
        "total": len(files),
        "files": files,
    }


@router.post("/scan-and-link")
async def scan_and_link(
    directories: list[str] = Body(..., description="要扫描的目录列表"),
    dry_run: bool = Body(False, description="是否仅预览不实际关联"),
    session: AsyncSession = Depends(get_session),
):
    """
    扫描目录并自动关联影片路径

    - 根据文件名提取番号
    - 在数据库中查找匹配的影片
    - 自动关联 file_path
    """
    from pathlib import Path
    from sqlalchemy import update
    from app.scraper.number import extract_number, normalize_number

    VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".iso", ".webm"}

    # 1. 扫描所有目录收集文件
    all_files = []  # [(number, path, size), ...]
    for directory in directories:
        scan_dir = Path(directory)
        if not scan_dir.exists() or not scan_dir.is_dir():
            continue
        for f in scan_dir.rglob("*"):
            if f.suffix.lower() in VIDEO_EXTS and f.is_file():
                number_result = extract_number(f.name)
                if number_result.number:
                    # 标准化番号用于匹配
                    normalized = normalize_number(number_result.number)
                    all_files.append({
                        "number": normalized,
                        "original_number": number_result.number,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "filename": f.name,
                    })

    # 2. 获取数据库中所有未关联路径的影片
    query = select(Movie).where(Movie.file_path.is_(None))
    result = await session.execute(query)
    movies_without_path = result.scalars().all()

    # 3. 建立番号到影片的映射
    movie_map = {}  # normalized_code -> movie
    for movie in movies_without_path:
        if movie.code:
            normalized = normalize_number(movie.code)
            movie_map[normalized] = movie

    # 4. 匹配并关联
    linked = []
    not_found = []
    for file_info in all_files:
        normalized = file_info["number"]
        movie = movie_map.get(normalized)
        if movie:
            linked.append({
                "movie_id": movie.id,
                "code": movie.code,
                "title": movie.title,
                "path": file_info["path"],
                "size": file_info["size"],
            })
            if not dry_run:
                # 实际更新数据库
                await session.execute(
                    update(Movie)
                    .where(Movie.id == movie.id)
                    .values(file_path=file_info["path"], file_size=file_info["size"])
                )
                # 从映射中移除，避免重复关联
                del movie_map[normalized]

    # 提交更改
    if not dry_run:
        await session.commit()
        _cache.invalidate("movies:")

    return {
        "total_files_found": len(all_files),
        "movies_without_path": len(movies_without_path),
        "linked_count": len(linked),
        "not_found_count": len(movie_map),  # 影片库中找不到对应番号
        "dry_run": dry_run,
        "linked": linked[:50],  # 限制返回数量
    }


@router.post("/auto-link-files")
async def auto_link_files(
    session: AsyncSession = Depends(get_session),
):
    """
    扫描配置中的媒体目录，自动关联视频文件到电影

    - 从配置中读取媒体目录列表
    - 递归扫描目录中的视频文件
    - 从文件名提取番号
    - 在数据库中查找匹配的电影
    - 如果电影没有 file_path，则关联该文件路径
    """
    from app.config.manager import get_config_manager
    from app.scraper.number import extract_number, normalize_number

    VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.wmv', '.rmvb', '.flv', '.ts', '.m2ts', '.mpg', '.mpeg'}

    # 从配置获取媒体目录
    manager = get_config_manager()
    media_dirs = manager.config.scraper.media_dirs

    if not media_dirs:
        raise HTTPException(status_code=400, detail="未配置媒体目录，请在配置中设置 scraper.media_dirs")

    stats = {"scanned": 0, "matched": 0, "linked": 0, "skipped": 0, "errors": []}
    linked_details = []

    for media_dir in media_dirs:
        dir_path = Path(media_dir)
        if not dir_path.exists():
            stats["errors"].append(f"目录不存在: {media_dir}")
            continue

        for video_file in dir_path.rglob("*"):
            if video_file.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if not video_file.is_file():
                continue

            stats["scanned"] += 1

            # 从文件名提取番号
            try:
                number_result = extract_number(video_file.name)
            except Exception as e:
                stats["skipped"] += 1
                continue

            if not number_result or not number_result.number:
                stats["skipped"] += 1
                continue

            stats["matched"] += 1
            normalized = normalize_number(number_result.number)

            # 查找电影（按标准化番号匹配）
            result = await session.execute(
                select(Movie).where(Movie.code == normalized)
            )
            movie_obj = result.scalar_one_or_none()

            if movie_obj:
                # 需要更新 file_path 的情况：
                # 1) file_path 为空（新影片未关联）
                # 2) file_path 指向的文件不存在（改名/移动后失效）
                need_link = False
                if not movie_obj.file_path:
                    need_link = True
                else:
                    old_path = Path(movie_obj.file_path)
                    if not old_path.exists() or not old_path.is_file():
                        need_link = True

                if need_link:
                    movie_obj.file_path = str(video_file)
                    try:
                        movie_obj.file_size = video_file.stat().st_size
                    except OSError:
                        pass
                    # 同步更新 output_dir（文件移了输出目录也该跟着变）
                    parent_dir = str(video_file.parent)
                    if not movie_obj.output_dir or movie_obj.output_dir != parent_dir:
                        movie_obj.output_dir = parent_dir
                    stats["linked"] += 1
                linked_details.append({
                    "movie_id": movie_obj.id,
                    "code": movie_obj.code,
                    "file_path": str(video_file),
                })

    await session.commit()
    _cache.invalidate("movies:")

    stats["linked_details"] = linked_details[:50]
    return stats


@router.post("/refresh-folders")
async def refresh_folders(
    directories: list[str] = Body(..., description="要扫描的根目录列表"),
    dry_run: bool = Body(False, description="是否仅预览，不实际修改数据库"),
    clear_missing: bool = Body(True, description="是否清理已不存在文件的影片 file_path"),
    session: AsyncSession = Depends(get_session),
):
    """
    重新扫描文件夹，自动更新影片文件路径

    适用场景：
    - 视频文件从一个盘符迁移到另一个盘符后，自动更新 file_path
    - 清理已删除视频文件的影片记录
    - 新增扫描目录中的新视频文件

    流程：
    1. 递归扫描所有指定目录中的视频文件
    2. 按番号匹配数据库中的影片
    3. 更新 file_path（路径变更）、output_dir（目录变更）
    4. 清理 file_path 指向不存在文件的影片
    5. 返回变更报告
    """
    from app.scraper.number import extract_number, normalize_number

    VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.ts', '.m2ts', '.iso', '.webm', '.rmvb', '.mpg', '.mpeg'}

    # ===== 阶段 1：扫描所有目录，收集视频文件 =====
    scan_start = datetime.now()
    scanned_dirs = 0
    scanned_files = 0
    file_map: dict[str, list[dict]] = {}  # normalized_code -> [file_info, ...]

    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            continue
        scanned_dirs += 1
        for f in dir_path.rglob("*"):
            if f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if not f.is_file():
                continue
            scanned_files += 1
            try:
                number_result = extract_number(f.name)
            except Exception:
                continue
            if not number_result or not number_result.number:
                continue
            normalized = normalize_number(number_result.number)
            file_info = {
                "path": str(f),
                "size": f.stat().st_size,
                "parent": str(f.parent),
                "filename": f.name,
            }
            if normalized not in file_map:
                file_map[normalized] = []
            file_map[normalized].append(file_info)

    # ===== 阶段 2：查询所有影片，建立 code -> movie 映射 =====
    result = await session.execute(select(Movie))
    all_movies = result.scalars().all()
    movie_map: dict[str, Movie] = {}
    for m in all_movies:
        if m.code:
            normalized = normalize_number(m.code)
            movie_map[normalized] = m

    # ===== 阶段 3：匹配并生成变更 =====
    updated = []       # file_path 发生变更
    path_unchanged = 0 # file_path 不变
    cleared = []       # file_path 被清理（文件不存在）
    not_found = []     # 扫描到的文件，数据库中没有对应影片
    skipped_no_code = 0 # 扫描到的文件，无法提取番号

    matched_codes = set()

    for normalized, files in file_map.items():
        movie = movie_map.get(normalized)
        if movie is None:
            for fi in files:
                not_found.append({
                    "code": normalized,
                    "path": fi["path"],
                    "filename": fi["filename"],
                })
            continue

        matched_codes.add(normalized)
        best_file = files[0]  # 取第一个匹配的文件
        new_path = best_file["path"]
        new_size = best_file["size"]
        new_parent = best_file["parent"]

        old_path = movie.file_path or ""
        if old_path == new_path:
            path_unchanged += 1
            continue

        updated.append({
            "movie_id": movie.id,
            "code": movie.code,
            "title": movie.title or "",
            "old_path": old_path,
            "new_path": new_path,
        })

        if not dry_run:
            movie.file_path = new_path
            movie.file_size = new_size
            movie.output_dir = new_parent

    # ===== 阶段 4：清理已不存在文件的影片 =====
    if clear_missing:
        for normalized, movie in movie_map.items():
            if normalized in matched_codes:
                continue
            if not movie.file_path:
                continue
            old_path = Path(movie.file_path)
            if old_path.exists() and old_path.is_file():
                continue
            cleared.append({
                "movie_id": movie.id,
                "code": movie.code,
                "title": movie.title or "",
                "old_path": movie.file_path,
            })
            if not dry_run:
                movie.file_path = None
                movie.file_size = None

    # ===== 提交 =====
    if not dry_run:
        await session.commit()
        _cache.invalidate("movies:")

    scan_duration = (datetime.now() - scan_start).total_seconds()

    return {
        "dry_run": dry_run,
        "scan_duration_seconds": round(scan_duration, 2),
        "scanned_dirs": scanned_dirs,
        "scanned_files": scanned_files,
        "files_with_code": sum(len(v) for v in file_map.values()),
        "unique_codes": len(file_map),
        "total_movies_in_db": len(all_movies),
        "updated_count": len(updated),
        "unchanged_count": path_unchanged,
        "cleared_count": len(cleared),
        "not_found_count": len(not_found),
        "updated": updated[:100],
        "cleared": cleared[:100],
        "not_found": not_found[:100],
    }


@router.get("/{movie_id}/play/external")
async def get_external_player_url(
    movie_id: int,
    request: Request,
    protocol: str = Query("http", description="播放协议: http, smb, direct, webdav, hls"),
    session: AsyncSession = Depends(get_session),
):
    """
    获取外部播放器（如 PotPlayer）的播放地址

    支持的协议:
    - http: HTTP 流媒体，格式如 http://<server>:8420/api/v1/movies/{id}/play/file
    - smb: SMB 协议，格式如 \\\\server\\share\\path\\file.mp4
    - direct: 直接返回文件路径
    - webdav: WebDAV 协议，格式如 http://<server>:8420/webdav/{path}
    - hls: HLS 流媒体切片，格式如 http://<server>:8420/api/v1/movies/{id}/hls/playlist.m3u8

    PotPlayer 支持 HTTP、WebDAV 和 HLS 流播放
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    # 从请求头获取服务器地址（修复局域网访问时 localhost 错误的问题）
    # 优先用 X-Forwarded-Host（反向代理场景），否则用 Host header
    forwarded_host = request.headers.get("x-forwarded-host")
    host_header = request.headers.get("host", "")
    if forwarded_host:
        base_url = f"http://{forwarded_host}" if not forwarded_host.startswith("http") else forwarded_host
    elif host_header:
        base_url = f"http://{host_header}" if not host_header.startswith("http") else host_header
    else:
        # 回退到配置
        from app.config.manager import get_config
        config = get_config()
        server_host = getattr(config.server, 'host', '127.0.0.1')
        server_port = getattr(config.server, 'port', 8420)
        if server_host in ('0.0.0.0', '127.0.0.1', 'localhost'):
            base_url = f"http://localhost:{server_port}"
        else:
            base_url = f"http://{server_host}:{server_port}"

    if protocol == "http":
        # HTTP 流媒体地址 - PotPlayer 可以直接打开
        play_url = f"{base_url}/api/v1/movies/{movie_id}/play/file"
        return {
            "protocol": "http",
            "play_url": play_url,
            "player_command": play_url,
            "copy_text": play_url,
        }

    elif protocol == "smb":
        # SMB 协议 - 将文件路径转换为 UNC 路径
        path_str = str(file_path)
        if ":" in path_str and path_str[1] == ":":
            # Windows 路径 -> 转换为 UNC
            drive = path_str[0].upper()
            rest = path_str[2:].replace("/", "\\")
            unc_path = f"\\\\localhost\\{drive}$\\{rest}"
            return {
                "protocol": "smb",
                "play_url": unc_path,
                "player_command": unc_path,
                "copy_text": unc_path,
            }
        else:
            # Linux 路径 -> 保持原样
            return {
                "protocol": "smb",
                "play_url": path_str,
                "player_command": path_str,
                "copy_text": path_str,
            }

    elif protocol == "webdav":
        # WebDAV 协议 - 通过 WebDAV 端点访问文件
        # WebDAV URL 格式: http://localhost:8420/webdav/{文件路径}
        path_str = str(file_path)
        # 将路径转换为 URL 安全格式
        import urllib.parse
        # 对于 Windows 路径 D:\xxx\yyy.mp4，转换为 /D/xxx/yyy.mp4
        if ":" in path_str and path_str[1] == ":":
            webdav_path = "/" + path_str[0].upper() + path_str[2:].replace("\\", "/")
        else:
            webdav_path = path_str.replace("\\", "/")
        webdav_url = f"{base_url}/webdav{urllib.parse.quote(webdav_path)}"
        return {
            "protocol": "webdav",
            "play_url": webdav_url,
            "player_command": webdav_url,
            "copy_text": webdav_url,
            "note": "PotPlayer 支持 WebDAV 协议，需要在网络设置中配置",
        }

    elif protocol == "hls":
        # HLS 流媒体切片 - 返回 m3u8 播放列表
        hls_url = f"{base_url}/api/v1/movies/{movie_id}/hls/playlist.m3u8"
        return {
            "protocol": "hls",
            "play_url": hls_url,
            "player_command": hls_url,
            "copy_text": hls_url,
            "note": "HLS 流媒体，首次播放可能需要等待切片生成",
        }

    else:  # direct
        # 直接返回文件路径
        return {
            "protocol": "direct",
            "play_url": str(file_path),
            "player_command": str(file_path),
            "copy_text": str(file_path),
        }


# ===== WebDAV 支持 =====

@router.get("/{movie_id}/webdav")
async def get_webdav_url(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取视频文件的 WebDAV 访问地址
    
    PotPlayer 和其他播放器支持通过 WebDAV 协议访问远程文件
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    from app.config.manager import get_config
    config = get_config()
    server_host = getattr(config.server, 'host', '127.0.0.1')
    server_port = getattr(config.server, 'port', 8420)

    use_localhost = server_host in ('0.0.0.0', '127.0.0.1', 'localhost')
    base_url = f"http://localhost:{server_port}" if use_localhost else f"http://{server_host}:{server_port}"

    import urllib.parse
    path_str = str(file_path)
    if ":" in path_str and path_str[1] == ":":
        webdav_path = "/" + path_str[0].upper() + path_str[2:].replace("\\", "/")
    else:
        webdav_path = path_str.replace("\\", "/")
    
    webdav_url = f"{base_url}/webdav{urllib.parse.quote(webdav_path)}"
    
    return {
        "movie_id": movie_id,
        "code": movie.code,
        "webdav_url": webdav_url,
        "copy_text": webdav_url,
        "note": "复制此 URL 到 PotPlayer 或其他支持 WebDAV 的播放器中打开",
    }


# ===== HLS 流媒体支持 =====

import os
import re
import shutil
from fastapi.responses import FileResponse, StreamingResponse
from fastapi import Request

# HLS 切片缓存目录
HLS_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "hls_cache"
HLS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

async def generate_hls_m3u8(movie_id: int, file_path: Path, force_transcode: bool = False) -> str:
    """
    生成 HLS m3u8 播放列表
    
    使用 ffmpeg 将视频文件切片为 HLS 格式
    
    参数:
        movie_id: 影片ID
        file_path: 视频文件路径
        force_transcode: 是否强制转码为 H.264+AAC（解决浏览器解码问题）
    """
    import subprocess
    import shutil
    
    # 检查 ffmpeg 是否可用
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="FFmpeg 未安装，请先安装 FFmpeg")
    
    # 创建影片专属目录
    movie_hls_dir = HLS_CACHE_DIR / str(movie_id)
    movie_hls_dir.mkdir(parents=True, exist_ok=True)
    
    # 输出文件路径
    m3u8_path = movie_hls_dir / "playlist.m3u8"
    
    # 如果 m3u8 已存在且文件未变更，直接返回
    if m3u8_path.exists() and not force_transcode:
        # 检查文件修改时间
        file_mtime = file_path.stat().st_mtime
        m3u8_mtime = m3u8_path.stat().st_mtime
        if m3u8_mtime > file_mtime:
            return str(m3u8_path)
    
    # 获取视频信息，判断是否需要转码
    codec_info = get_video_codec_info(str(file_path))
    needs_transcode = force_transcode or not is_browser_compatible(codec_info)
    
    # 使用 ffmpeg 生成 HLS 切片
    cmd = [
        "ffmpeg",
        "-i", str(file_path),
        "-hls_time", "10",
        "-hls_list_size", "0",
        "-hls_flags", "append_list",
        "-y",  # 覆盖现有文件
    ]
    
    if needs_transcode:
        # 强制转码为浏览器兼容格式：H.264 + AAC
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "faststart",
        ])
    else:
        # 直接复制流，不转码
        cmd.extend([
            "-c:v", "copy",
            "-c:a", "copy",
        ])
    
    cmd.append(str(m3u8_path))
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",  # 避免 Windows gbk 编码崩
            timeout=300  # 5分钟超时
        )
        if result.returncode != 0:
            # 清理可能的部分输出
            for f in movie_hls_dir.glob("*"):
                f.unlink()
            raise HTTPException(
                status_code=500,
                detail=f"HLS 切片生成失败: {result.stderr}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="HLS 切片生成超时")
    
    return str(m3u8_path)


# ===== HLS 自适应码率（v3.5 新增） =====

# 自适应码率预设（分辨率 -> 码率）
HLS_QUALITY_PRESETS = [
    {"name": "1080p", "width": 1920, "height": 1080, "bitrate": 5000, "label": "1080p 高清"},
    {"name": "720p", "width": 1280, "height": 720, "bitrate": 2800, "label": "720p 标清"},
    {"name": "480p", "width": 854, "height": 480, "bitrate": 1400, "label": "480p 流畅"},
]


def _select_adaptive_qualities(codec_info: dict) -> list[dict]:
    """
    根据原始视频分辨率选择要生成的画质版本

    策略：
    - 原始 >= 1080p: 生成 1080p + 720p + 480p
    - 原始 >= 720p: 生成 720p + 480p
    - 原始 >= 480p: 生成 480p
    - 原始 < 480p: 只生成原画（不转码）
    """
    src_height = codec_info.get("height") or 0
    if not src_height:
        return []  # 无法获取分辨率，不生成自适应版本

    selected = []
    for preset in HLS_QUALITY_PRESETS:
        if src_height >= preset["height"]:
            selected.append(preset)
    return selected


async def generate_hls_master_playlist(movie_id: int, file_path: Path) -> str:
    """
    生成 HLS 自适应码率 master playlist（v3.5 新增）

    使用 ffmpeg 一次性生成多码率版本，输出结构：
        data/hls_cache/{movie_id}/
            master.m3u8              # 主播放列表
            1080p/playlist.m3u8      # 1080p 子列表
            1080p/segment_000.ts
            720p/playlist.m3u8       # 720p 子列表
            480p/playlist.m3u8       # 480p 子列表

    master.m3u8 内容示例：
        #EXTM3U
        #EXT-X-VERSION:6
        #EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,NAME="1080p"
        1080p/playlist.m3u8
        #EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,NAME="720p"
        720p/playlist.m3u8
    """
    import subprocess

    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="FFmpeg 未安装")

    movie_hls_dir = HLS_CACHE_DIR / str(movie_id)
    movie_hls_dir.mkdir(parents=True, exist_ok=True)
    master_path = movie_hls_dir / "master.m3u8"

    # 缓存检查：master.m3u8 已存在且视频未变更
    if master_path.exists():
        file_mtime = file_path.stat().st_mtime
        master_mtime = master_path.stat().st_mtime
        if master_mtime > file_mtime:
            return str(master_path)

    # 获取视频信息
    codec_info = get_video_codec_info(str(file_path))
    qualities = _select_adaptive_qualities(codec_info)

    if not qualities:
        # 无法获取分辨率或分辨率太低，降级为单码率
        raise HTTPException(
            status_code=400,
            detail="视频分辨率信息获取失败或不支持自适应码率，请使用单码率 HLS"
        )

    # 构建 ffmpeg 命令（使用 filter_complex split + scale 生成多码率）
    n = len(qualities)
    filter_parts = [f"[0:v]split={n}[v_input]"]
    # 实际上 split 输出为 [v0][v1][v2]
    split_outputs = "".join([f"[v{i}]" for i in range(n)])
    filter_complex = f"[0:v]split={n}{split_outputs}"
    for i, q in enumerate(qualities):
        filter_complex += f";[v{i}]scale={q['width']}:{q['height']}[v{i}out]"

    cmd = [
        "ffmpeg",
        "-i", str(file_path),
        "-filter_complex", filter_complex,
    ]

    # 为每个画质添加输出
    for i, q in enumerate(qualities):
        cmd.extend([
            f"-map", f"[v{i}out]",
            f"-map", "0:a?",
            f"-c:v:{i}", "libx264",
            f"-preset", "fast",
            f"-crf", "23",
            f"-b:v:{i}", f"{q['bitrate']}k",
            f"-maxrate:v:{i}", f"{int(q['bitrate'] * 1.2)}k",
            f"-bufsize:v:{i}", f"{q['bitrate'] * 2}k",
            f"-c:a:{i}", "aac",
            f"-b:a:{i}", "128k",
        ])

    cmd.extend([
        "-f", "hls",
        "-hls_time", "10",
        "-hls_list_size", "0",
        "-hls_flags", "append_list",
        "-hls_segment_filename", str(movie_hls_dir / "%v" / "segment_%03d.ts"),
        "-master_pl_name", "master.m3u8",
        "-var_stream_map", " ".join([f"v:{i},a:{i}" for i in range(n)]),
        "-y",
        str(movie_hls_dir / "%v" / "playlist.m3u8"),
    ])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # 避免 Windows gbk 编码崩
            timeout=900,  # 15分钟超时(多码率生成更慢)
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"HLS 自适应码率生成失败: {result.stderr[-500:]}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="HLS 自适应码率生成超时（15分钟）")

    # ffmpeg 生成的 master.m3u8 默认在输出目录下
    if not master_path.exists():
        # 某些 ffmpeg 版本可能不自动生成 master.m3u8，手动生成
        master_content = "#EXTM3U\n#EXT-X-VERSION:6\n"
        for i, q in enumerate(qualities):
            bandwidth = q["bitrate"] * 1000
            master_content += (
                f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},'
                f'RESOLUTION={q["width"]}x{q["height"]},'
                f'NAME="{q["label"]}"\n'
                f'{q["name"]}/playlist.m3u8\n'
            )
        master_path.write_text(master_content, encoding="utf-8")

    return str(master_path)


def get_video_codec_info(file_path: str) -> dict:
    """
    获取视频文件的编码信息
    
    返回:
        {
            'video_codec': str,      # 视频编码 (如 h264, hevc, vp9)
            'audio_codec': str,      # 音频编码 (如 aac, mp3, opus)
            'width': int,            # 宽度
            'height': int,           # 高度
            'duration': float,       # 时长(秒)
            'bitrate': int,          # 比特率(bps)
        }
    """
    import subprocess
    import json
    
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        file_path,
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",  # 避免 Windows gbk 编码崩
            timeout=30
        )
        if result.returncode != 0:
            return {}
        
        info = json.loads(result.stdout)
        video_stream = None
        audio_stream = None
        
        for stream in info.get('streams', []):
            if stream.get('codec_type') == 'video':
                video_stream = stream
            elif stream.get('codec_type') == 'audio':
                audio_stream = stream
        
        return {
            'video_codec': video_stream.get('codec_name') if video_stream else None,
            'audio_codec': audio_stream.get('codec_name') if audio_stream else None,
            'width': video_stream.get('width') if video_stream else None,
            'height': video_stream.get('height') if video_stream else None,
            'duration': float(info.get('format', {}).get('duration', 0)),
            'bitrate': int(info.get('format', {}).get('bit_rate', 0)) if info.get('format', {}).get('bit_rate') else None,
        }
    except Exception:
        return {}


def is_browser_compatible(codec_info: dict) -> bool:
    """
    判断视频编码是否兼容浏览器
    
    浏览器普遍支持:
    - 视频: H.264 (avc1)
    - 音频: AAC, MP3
    
    浏览器不支持或支持有限:
    - 视频: HEVC (h265), VP9, AV1
    - 音频: AC3, DTS, TrueHD
    """
    video_codec = codec_info.get('video_codec', '').lower()
    audio_codec = codec_info.get('audio_codec', '').lower()
    
    # 视频编码兼容列表
    compatible_video = {'h264', 'avc1', 'vp8'}
    # 音频编码兼容列表
    compatible_audio = {'aac', 'mp3', 'opus', 'vorbis'}
    
    if not video_codec or not audio_codec:
        return False
    
    return video_codec in compatible_video and audio_codec in compatible_audio


@router.get("/{movie_id}/hls/playlist.m3u8")
async def get_hls_playlist(
    movie_id: int,
    transcode: bool = Query(False, description="是否强制转码为 H.264+AAC"),
    session: AsyncSession = Depends(get_session),
    request: Request = None,
):
    """
    获取 HLS 播放列表 (.m3u8)
    
    支持动态生成 HLS 切片，首次请求可能需要等待切片生成
    
    参数:
        transcode: 是否强制转码为 H.264+AAC 格式（解决浏览器解码问题）
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    # 生成 HLS 切片（支持自动/强制转码）
    m3u8_path = await generate_hls_m3u8(movie_id, file_path, transcode)
    
    # 返回 m3u8 文件
    return FileResponse(
        m3u8_path,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
        }
    )


@router.get("/{movie_id}/hls/master.m3u8")
async def get_hls_master_playlist(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取 HLS 自适应码率主播放列表（v3.5 新增）

    生成多码率 HLS（1080p/720p/480p），前端通过 hls.js 自动根据网络情况切换。
    首次请求需要等待 ffmpeg 转码生成，可能较慢（视视频时长而定）。

    master.m3u8 包含多个 EXT-X-STREAM-INF，每个指向不同码率的子 playlist。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    master_path = await generate_hls_master_playlist(movie_id, file_path)

    return FileResponse(
        master_path,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
        }
    )


@router.get("/{movie_id}/hls/qualities")
async def get_hls_qualities(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取影片可用的 HLS 画质列表（v3.5 新增）

    返回自适应码率可用的画质版本，前端可用于显示画质选择菜单。
    若 master.m3u8 未生成，返回空列表。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    movie_hls_dir = HLS_CACHE_DIR / str(movie_id)
    master_path = movie_hls_dir / "master.m3u8"

    if not master_path.exists():
        # 尝试获取预计可用的画质
        if not movie.file_path:
            return {"movie_id": movie_id, "items": [], "generated": False}
        file_path = Path(movie.file_path)
        if not file_path.exists():
            return {"movie_id": movie_id, "items": [], "generated": False}
        codec_info = get_video_codec_info(str(file_path))
        qualities = _select_adaptive_qualities(codec_info)
        return {
            "movie_id": movie_id,
            "items": qualities,
            "generated": False,
            "hint": "访问 /hls/master.m3u8 触发生成"
        }

    # 解析 master.m3u8
    import re as _re
    content = master_path.read_text(encoding="utf-8")
    qualities = []
    current_inf = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = line[len("#EXT-X-STREAM-INF:"):]
            bw = _re.search(r"BANDWIDTH=(\d+)", attrs)
            res = _re.search(r"RESOLUTION=(\d+)x(\d+)", attrs)
            name = _re.search(r'NAME="([^"]+)"', attrs)
            current_inf = {
                "bandwidth": int(bw.group(1)) if bw else 0,
                "width": int(res.group(1)) if res else 0,
                "height": int(res.group(2)) if res else 0,
                "label": name.group(1) if name else "",
            }
        elif line and not line.startswith("#") and current_inf:
            current_inf["url"] = line
            qualities.append(current_inf)
            current_inf = {}

    return {"movie_id": movie_id, "items": qualities, "generated": True}


@router.get("/{movie_id}/codec-info")
async def get_movie_codec_info(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    获取影片的编码信息
    
    返回视频编码、音频编码、分辨率、时长等信息，用于判断浏览器兼容性
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not movie.file_path:
        raise HTTPException(status_code=404, detail="影片没有关联文件")

    file_path = Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    codec_info = get_video_codec_info(str(file_path))
    is_compatible = is_browser_compatible(codec_info)

    return {
        "movie_id": movie_id,
        "code": movie.code,
        "codec_info": codec_info,
        "browser_compatible": is_compatible,
        "recommendation": "直接播放" if is_compatible else "建议使用 HLS 转码播放",
    }


@router.get("/{movie_id}/hls/{segment}")
async def get_hls_segment(
    movie_id: int,
    segment: str,
    session: AsyncSession = Depends(get_session),
):
    """
    获取 HLS 切片文件 (.ts)
    """
    # 安全检查：防止路径遍历
    if not re.match(r"^segment_\d{3}\.ts$", segment):
        raise HTTPException(status_code=400, detail="无效的切片文件名")

    movie_hls_dir = HLS_CACHE_DIR / str(movie_id)
    segment_path = movie_hls_dir / segment

    if not segment_path.exists():
        raise HTTPException(status_code=404, detail="切片文件不存在")

    return FileResponse(
        segment_path,
        media_type="video/MP2T",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        }
    )


@router.get("/{movie_id}/hls/{quality}/{filename}")
async def get_hls_quality_file(
    movie_id: int,
    quality: str,
    filename: str,
    session: AsyncSession = Depends(get_session),
):
    """
    获取自适应码率 HLS 的子 playlist 或切片文件（v3.5 新增）

    - {quality}: 画质标识（1080p/720p/480p）
    - {filename}: playlist.m3u8 或 segment_XXX.ts
    """
    # 安全校验：quality 只允许字母数字
    if not re.match(r"^[0-9a-zA-Z]+$", quality):
        raise HTTPException(status_code=400, detail="无效的画质标识")

    # filename 校验：playlist.m3u8 或 segment_XXX.ts
    is_playlist = filename == "playlist.m3u8"
    is_segment = bool(re.match(r"^segment_\d{3}\.ts$", filename))
    if not (is_playlist or is_segment):
        raise HTTPException(status_code=400, detail="无效的文件名")

    movie_hls_dir = HLS_CACHE_DIR / str(movie_id)
    file_path = movie_hls_dir / quality / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{quality}/{filename} 不存在")

    if is_playlist:
        return FileResponse(
            str(file_path),
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            }
        )
    return FileResponse(
        str(file_path),
        media_type="video/MP2T",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        }
    )


@router.get("/{movie_id}/related")
async def get_related_movies(
    movie_id: int,
    limit: int = Query(12, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """获取相关电影推荐（同系列/同演员/同厂商/同类别）

    返回三个推荐区：
    - actor_movies: 演员出演的其他作品（按类别相似度排序）
    - series_movies: 同系列其他作品
    - genre_movies: 同类别其他作品
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="电影不存在")

    related_ids = {movie_id}

    # 辅助函数：构建简单影片信息
    def _build_item(m):
        return {
            "id": m.id,
            "code": m.code,
            "title": m.title,
            "release_date": m.release_date,
            "cover_url": m.cover_url,
            "maker": m.maker,
        }

    # ===== 1. 演员作品推荐 =====
    actor_movies = []
    actor_ids_result = await session.execute(
        select(MovieActor.actor_id).where(MovieActor.movie_id == movie_id)
    )
    actor_id_list = [r[0] for r in actor_ids_result.fetchall()]
    if actor_id_list:
        result = await session.execute(
            select(Movie)
            .join(MovieActor, Movie.id == MovieActor.movie_id)
            .where(
                MovieActor.actor_id.in_(actor_id_list),
                Movie.id != movie_id,
            )
            .order_by(Movie.release_date.desc())
            .limit(limit)
        )
        for m in result.scalars().all():
            if m.id not in related_ids:
                related_ids.add(m.id)
                actor_movies.append(_build_item(m))

    # ===== 2. 同系列作品 =====
    series_movies = []
    if movie.series_id:
        result = await session.execute(
            select(Movie)
            .where(Movie.series_id == movie.series_id, Movie.id != movie_id)
            .order_by(Movie.release_date.desc())
            .limit(limit)
        )
        for m in result.scalars().all():
            series_movies.append(_build_item(m))

    # ===== 3. 同类别推荐（按 genre 相似度） =====
    genre_movies = []
    genre_list = _parse_json_list(movie.genre)
    if genre_list:
        # 批量匹配：用 LIKE 模糊匹配 genre 字段
        from sqlalchemy import or_
        genre_conditions = [Movie.genre.like(f"%{g}%") for g in genre_list[:5]]
        result = await session.execute(
            select(Movie)
            .where(
                or_(*genre_conditions),
                Movie.id != movie_id,
                ~Movie.id.in_(related_ids),
            )
            .order_by(Movie.release_date.desc())
            .limit(limit)
        )
        for m in result.scalars().all():
            if m.id not in related_ids:
                related_ids.add(m.id)
                genre_movies.append(_build_item(m))

    return {
        "movie_id": movie_id,
        "actor_movies": actor_movies[:limit],
        "series_movies": series_movies[:limit],
        "genre_movies": genre_movies[:limit],
    }


@router.patch("/{movie_id}")
async def update_movie(
    movie_id: int,
    body: dict = Body(...),
    session: AsyncSession = Depends(get_session),
):
    """更新视频信息

    支持的可写字段:
      - 文本/数字: title, original_title, rating, status, file_path
      - FK/Name 字段: studio (按名称查/建), series (按名称查/建), director, maker
      - JSON 字符串字段: genre (list[str]), tag (list[str]), actors (list[str]),
                          sample_images (list[str])
      - 控制项: code (允许修改, 需唯一), sync_nfo (bool, 默认 true, 修改后回写 movie.nfo)

    若 ``sync_nfo=True`` 且能定位到 movie_dir, 修改后会调
    :meth:`NFOGenerator.generate_from_movie` 重写 ``movie.nfo``, 与 Emby/Jellyfin 同步。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 文本字段
    for text_field in ("title", "original_title", "title_jp", "plot", "plot_short",
                       "director", "maker", "cover_url", "poster_url", "thumb_url",
                       "trailer_url", "source_url", "release_date"):
        if text_field in body and body[text_field] is not None:
            setattr(movie, text_field, body[text_field] or None)

    # 评分
    if "rating" in body:
        val = body["rating"]
        if val is None or val == "":
            movie.rating = None
        else:
            try:
                r = float(val)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="rating 必须是 0-10 的数字")
            movie.rating = max(0.0, min(10.0, r))

    # 整数字段
    if "duration" in body and body["duration"] is not None:
        try:
            movie.duration = int(body["duration"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="duration 必须是整数")

    # 布尔字段
    for b_field in ("is_mosaic", "is_uncensored", "is_chinese", "is_leak"):
        if b_field in body and body[b_field] is not None:
            setattr(movie, b_field, bool(body[b_field]))

    # 状态
    if "status" in body and body["status"] is not None:
        movie.status = body["status"]

    # 文件路径
    if "file_path" in body:
        movie.file_path = body["file_path"] or None
        if movie.file_path:
            try:
                fp = Path(movie.file_path)
                if fp.exists() and fp.is_file():
                    movie.file_size = fp.stat().st_size
                # 同步更新 output_dir 到视频所在目录
                movie.output_dir = str(fp.parent)
            except Exception:
                pass

    # 番号(允许修改, 需唯一)
    if "code" in body and body["code"] is not None and body["code"] != movie.code:
        new_code = str(body["code"]).strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="code 不能为空")
        # 唯一性
        existing = await session.scalar(select(Movie).where(Movie.code == new_code, Movie.id != movie_id))
        if existing:
            raise HTTPException(status_code=409, detail=f"番号 {new_code} 已被其他影片占用")
        movie.code = new_code

    # studio(按名称查/建)
    if "studio" in body and body["studio"] is not None:
        studio_name = str(body["studio"]).strip()
        if studio_name:
            existing_studio = await session.scalar(select(Studio).where(Studio.name == studio_name))
            if existing_studio:
                movie.studio_id = existing_studio.id
            else:
                new_studio = Studio(name=studio_name, movie_count=0)
                session.add(new_studio)
                await session.flush()
                movie.studio_id = new_studio.id
        else:
            movie.studio_id = None

    # series(按名称查/建)
    if "series" in body and body["series"] is not None:
        series_name = str(body["series"]).strip()
        if series_name:
            existing_series = await session.scalar(select(Series).where(Series.name == series_name))
            if existing_series:
                movie.series_id = existing_series.id
            else:
                new_series = Series(name=series_name, movie_count=0)
                session.add(new_series)
                await session.flush()
                movie.series_id = new_series.id
        else:
            movie.series_id = None

    # JSON 列表字段
    def _set_json(field_name: str, raw):
        if raw is None:
            setattr(movie, field_name, None)
            return
        if isinstance(raw, str):
            # 接受 JSON 字符串或逗号分隔
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    setattr(movie, field_name, json.dumps(parsed, ensure_ascii=False))
                    return
            except Exception:
                pass
            setattr(movie, field_name, json.dumps([s.strip() for s in raw.split(",") if s.strip()], ensure_ascii=False))
            return
        if isinstance(raw, list):
            setattr(movie, field_name, json.dumps(raw, ensure_ascii=False))
            return
        setattr(movie, field_name, json.dumps([str(raw)], ensure_ascii=False))

    if "genre" in body:
        _set_json("genre", body["genre"])
    if "tag" in body:
        _set_json("tag", body["tag"])
    if "sample_images" in body:
        _set_json("sample_images", body["sample_images"])

    # 演员(按名称清空 + 重写 MovieActor)
    actor_names_for_nfo: list[str] = []
    if "actors" in body and body["actors"] is not None:
        raw_actors = body["actors"]
        if isinstance(raw_actors, str):
            try:
                parsed = json.loads(raw_actors)
                if isinstance(parsed, list):
                    raw_actors = parsed
            except Exception:
                raw_actors = [s.strip() for s in raw_actors.split(",") if s.strip()]
        if not isinstance(raw_actors, list):
            raw_actors = []

        # 删旧关联
        await session.execute(
            selectinload(Movie).selectinload  # placeholder, 实际用 delete
        ) if False else None
        from sqlalchemy import delete as sa_delete
        await session.execute(sa_delete(MovieActor).where(MovieActor.movie_id == movie_id))

        actor_names_for_nfo = []
        for nm in raw_actors:
            nm = str(nm).strip()
            if not nm: continue
            actor = await session.scalar(select(Actor).where(Actor.name == nm))
            if not actor:
                actor = Actor(name=nm, movie_count=0)
                session.add(actor)
                await session.flush()
            session.add(MovieActor(movie_id=movie_id, actor_id=actor.id))
            actor_names_for_nfo.append(nm)

    await session.commit()
    await session.refresh(movie)

    # 回写 NFO
    sync_nfo = body.get("sync_nfo", True)
    nfo_status: dict = {"attempted": bool(sync_nfo), "written": False, "path": None, "error": None}
    if sync_nfo:
        try:
            # 预加载关联用于 NFO
            from sqlalchemy.orm import selectinload as _sel
            mv = await session.scalar(
                select(Movie)
                .where(Movie.id == movie_id)
                .options(_sel(Movie.studio_ref), _sel(Movie.series_ref))
            )
            from app.output.nfo import NFOGenerator
            gen = NFOGenerator(output_dir=str(Path(mv.output_dir) if mv.output_dir else (Path(mv.file_path).parent if mv.file_path else "")))
            nfo_path = gen.generate_from_movie(
                movie=mv,
                movie_dir=None,  # 让 generate_from_movie 内部用 output_dir 优先, fallback file_path.parent
                kodi_compatible=True,
                actor_names=actor_names_for_nfo if actor_names_for_nfo else None,
            )
            nfo_status["written"] = bool(nfo_path)
            nfo_status["path"] = nfo_path
        except Exception as e:
            nfo_status["error"] = str(e)
            import logging as _lg
            _lg.getLogger(__name__).warning(f"NFO 回写失败: {e}")

    _cache.invalidate("movies:")
    # 显式查关联名, 避免懒加载 MissingGreenlet
    studio_name = None
    series_name = None
    if movie.studio_id:
        studio_name = await session.scalar(select(Studio.name).where(Studio.id == movie.studio_id))
    if movie.series_id:
        series_name = await session.scalar(select(Series.name).where(Series.id == movie.series_id))
    actor_query = (
        select(Actor.id, Actor.name)
        .join(MovieActor, Actor.id == MovieActor.actor_id)
        .where(MovieActor.movie_id == movie_id)
    )
    actor_result = await session.execute(actor_query)
    actors = [ActorBrief(id=row[0], name=row[1]) for row in actor_result.fetchall()]

    resp = MovieResponse(
        id=movie.id,
        code=movie.code,
        title=movie.title,
        title_jp=movie.title_jp,
        studio_id=movie.studio_id,
        studio=studio_name,
        maker=movie.maker,
        series_id=movie.series_id,
        series=series_name,
        director=movie.director,
        release_date=movie.release_date,
        duration=movie.duration,
        rating=movie.rating,
        plot=movie.plot,
        plot_short=movie.plot_short,
        genre=_parse_json_list(movie.genre),
        tag=_parse_json_list(movie.tag),
        cover_url=movie.cover_url,
        poster_url=movie.poster_url,
        thumb_url=movie.thumb_url,
        trailer_url=movie.trailer_url,
        source=movie.source,
        source_url=movie.source_url,
        is_mosaic=movie.is_mosaic,
        is_chinese=movie.is_chinese,
        is_uncensored=movie.is_uncensored,
        is_leak=movie.is_leak,
        file_path=movie.file_path,
        file_size=movie.file_size,
        sample_images=_parse_sample_images(movie.sample_images),
        status=movie.status,
        actors=actors,
    )

    return {"status": "ok", "movie": resp, "nfo_sync": nfo_status}


@router.post("/{movie_id}/reload-nfo")
async def reload_movie_from_nfo(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """从本地 movie.nfo 重新导入, 全量覆盖 DB 字段.

    流程:
    1. 找到 movie.nfo 路径(从 movie.file_path 父目录 或 movie.output_dir 找)
    2. NFOParser 解析为 update body
    3. 复用 PATCH 逻辑回写 DB(然后再回写 NFO, 此时等价于原样)

    找不到 NFO 时返回 404 提示。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 决定 nfo 路径
    nfo_path = None
    base_dirs = []
    if movie.output_dir:
        base_dirs.append(Path(movie.output_dir))
    if movie.file_path:
        base_dirs.append(Path(movie.file_path).parent)
    for d in base_dirs:
        for name in ("movie.nfo", f"{movie.code}.nfo"):
            p = d / name
            if p.exists():
                nfo_path = p
                break
        if nfo_path:
            break

    if not nfo_path:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 movie.nfo(查过 {[str(d) for d in base_dirs]})",
        )

    # 解析为 update body
    from app.importer.nfo_parser import NFOParser
    update_body = NFOParser().parse_to_dict(nfo_path)
    if not update_body:
        raise HTTPException(status_code=400, detail=f"NFO 解析失败: {nfo_path}")

    # 调用 PATCH 内部逻辑(此处为了避免循环调用 HTTP, 直接走核心更新)
    # 因为 PATCH 端点已支持全集字段, 这里简化: 重用更新逻辑
    # 为避免重复维护, 直接构造 PATCH 请求体并以内部函数形式调用
    # 此处偷懒: 我们重新实现核心更新(简化版, 不重复 sync_nfo)

    # 1) code 唯一性
    if "code" in update_body and update_body["code"] != movie.code:
        new_code = str(update_body["code"]).strip()
        existing = await session.scalar(select(Movie).where(Movie.code == new_code, Movie.id != movie_id))
        if existing:
            raise HTTPException(status_code=409, detail=f"番号 {new_code} 已被占用, 跳过覆盖")
        movie.code = new_code

    # 2) 文本/数字字段
    for f in ("title", "original_title", "title_jp", "plot", "plot_short",
              "director", "maker", "cover_url", "poster_url", "thumb_url",
              "trailer_url", "source_url", "release_date"):
        if f in update_body:
            setattr(movie, f, update_body[f] or None)
    if "duration" in update_body:
        try: movie.duration = int(update_body["duration"])
        except Exception:
            logger.warning("无法解析 duration 字段: %s", update_body["duration"])
    if "rating" in update_body and update_body["rating"] is not None:
        try: movie.rating = max(0.0, min(10.0, float(update_body["rating"])))
        except Exception:
            logger.warning("无法解析 rating 字段: %s", update_body["rating"])

    # 3) studio/series by name
    for name_field, rel in (("studio", "studio_id"), ("series", "series_id")):
        if name_field in update_body:
            v = str(update_body[name_field]).strip()
            if not v:
                setattr(movie, rel, None); continue
            Model = Studio if name_field == "studio" else Series
            existing_obj = await session.scalar(select(Model).where(Model.name == v))
            if existing_obj:
                setattr(movie, rel, existing_obj.id)
            else:
                obj = Model(name=v, movie_count=0)
                session.add(obj); await session.flush()
                setattr(movie, rel, obj.id)

    # 4) JSON 列表
    for json_field in ("genre", "tag"):
        if json_field in update_body:
            v = update_body[json_field]
            if isinstance(v, list):
                setattr(movie, json_field, json.dumps(v, ensure_ascii=False))
            elif v is None:
                setattr(movie, json_field, None)

    # 5) 布尔
    for b in ("is_chinese", "is_uncensored", "is_leak"):
        if b in update_body and update_body[b] is not None:
            setattr(movie, b, bool(update_body[b]))

    # 6) 演员
    actor_names: list[str] = []
    if "actors" in update_body:
        raw = update_body["actors"]
        if isinstance(raw, list):
            from sqlalchemy import delete as sa_delete
            await session.execute(sa_delete(MovieActor).where(MovieActor.movie_id == movie_id))
            for nm in raw:
                nm = str(nm).strip()
                if not nm: continue
                actor = await session.scalar(select(Actor).where(Actor.name == nm))
                if not actor:
                    actor = Actor(name=nm, movie_count=0)
                    session.add(actor); await session.flush()
                session.add(MovieActor(movie_id=movie_id, actor_id=actor.id))
                actor_names.append(nm)

    await session.commit()
    await session.refresh(movie)

    # 7) 回写 NFO(可选, 这里跳过——刚才是从 NFO 读的, 再写一遍等价)
    _cache.invalidate("movies:")

    # 构造响应
    # 显式查关联名, 避免懒加载 MissingGreenlet
    studio_name = None
    series_name = None
    if movie.studio_id:
        studio_name = await session.scalar(select(Studio.name).where(Studio.id == movie.studio_id))
    if movie.series_id:
        series_name = await session.scalar(select(Series.name).where(Series.id == movie.series_id))

    actor_query = (
        select(Actor.id, Actor.name)
        .join(MovieActor, Actor.id == MovieActor.actor_id)
        .where(MovieActor.movie_id == movie_id)
    )
    actor_result = await session.execute(actor_query)
    actors = [ActorBrief(id=row[0], name=row[1]) for row in actor_result.fetchall()]

    resp = MovieResponse(
        id=movie.id, code=movie.code, title=movie.title, title_jp=movie.title_jp,
        studio_id=movie.studio_id,
        studio=studio_name,
        maker=movie.maker,
        series_id=movie.series_id,
        series=series_name,
        director=movie.director, release_date=movie.release_date, duration=movie.duration,
        rating=movie.rating, plot=movie.plot, plot_short=movie.plot_short,
        genre=_parse_json_list(movie.genre), tag=_parse_json_list(movie.tag),
        cover_url=movie.cover_url, poster_url=movie.poster_url, thumb_url=movie.thumb_url,
        trailer_url=movie.trailer_url, source=movie.source, source_url=movie.source_url,
        is_mosaic=movie.is_mosaic, is_chinese=movie.is_chinese, is_uncensored=movie.is_uncensored,
        is_leak=movie.is_leak, file_path=movie.file_path, file_size=movie.file_size,
        sample_images=_parse_sample_images(movie.sample_images),
        status=movie.status, actors=actors,
    )
    return {
        "status": "ok",
        "movie": resp,
        "nfo_source": str(nfo_path),
        "applied_fields": sorted(update_body.keys()),
    }


@router.delete("/{movie_id}")
async def delete_movie(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除视频"""
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    await session.delete(movie)
    await session.commit()
    _cache.invalidate("movies:")  # 清除列表缓存

    return {"status": "ok"}


@router.post("/batch-delete")
async def batch_delete_movies(
    ids: list[int],
    session: AsyncSession = Depends(get_session),
):
    """批量删除视频"""
    from sqlalchemy import delete as sa_delete

    stmt = sa_delete(Movie).where(Movie.id.in_(ids))
    result = await session.execute(stmt)
    await session.commit()
    _cache.invalidate("movies:")  # 清除列表缓存

    return {"status": "ok", "deleted": result.rowcount}


# 各刮削源详情页基地址，用于构造防盗链 Referer
_SOURCE_DETAIL_BASE = {
    "javbus": "https://www.javbus.com",
    "javdb": "https://javdb.com",
    "javdatabase": "https://javdatabase.com",
    "avmoo": "https://avmoo.shop",
    "avsox": "https://avsox.click",
    "fanart": "https://fanart.tv",
}


def _detail_referer(source: str | None, code: str | None) -> str | None:
    """构造详情页 Referer（如 javbus 需 https://www.javbus.com/{code} 才能下载封面）。

    source 为站点标识（如 'javbus'）时返回详情页 URL；为完整 URL 时原样返回；
    其余返回 None（调用方回退到封面 URL 的源站域名）。
    """
    if not source:
        return None
    if source.startswith("http://") or source.startswith("https://"):
        return source
    base = _SOURCE_DETAIL_BASE.get(source)
    if base and code:
        return f"{base}/{code}"
    return None


async def _persist_scraped_media(result, code: str):
    """下载刮削封面+预览图到服务端 output_dir/<番号>/，并生成 NFO（规则3）。

    返回 (封面本地路径, 预览图本地路径列表)。下载失败返回 (None, [])，
    由调用方回退到远程 URL，不影响元数据落地。
    """
    import logging
    import re
    logger = logging.getLogger(__name__)
    try:
        from app.config.manager import get_config
        from app.output.images import ImageProcessor
        from app.output.nfo import generate_nfo
        output_dir = Path(get_config().scraper.output_dir).resolve()
    except Exception as e:
        logger.warning(f"解析刮削输出目录失败: {e}")
        return None, []

    safe_code = re.sub(r'[<>:"/\\|?*]', '', code or "movie")
    movie_dir = output_dir / safe_code
    movie_dir.mkdir(parents=True, exist_ok=True)

    # 防盗链 Referer：javbus 等站点的封面 CDN(/pics/cover/*) 必须带「详情页 Referer」
    # 才放行，仅带源站域名 Referer 仍会 403。故优先构造 详情页 Referer。
    referer = _detail_referer(getattr(result, "source", None), code)
    if not referer:
        cover_url = getattr(result, "cover_url", None)
        if cover_url:
            from urllib.parse import urlparse
            p = urlparse(cover_url)
            if p.scheme and p.netloc:
                referer = f"{p.scheme}://{p.netloc}"

    cover_local = None
    sample_local = []
    try:
        # 相对路径封面(如 javbus /pics/cover/*)需补全为绝对 URL 才能下载
        from urllib.parse import urljoin
        raw_cover = getattr(result, "cover_url", None)
        cover_src = raw_cover
        if raw_cover and raw_cover.startswith('/'):
            base = getattr(result, "source", None)
            if base and not base.startswith('/'):
                cover_src = urljoin(base.rstrip('/') + '/', raw_cover.lstrip('/'))

        async with ImageProcessor(str(movie_dir)) as proc:
            if cover_src:
                # 文件名统一为 cover.jpg，与补刮引擎(patch)的 {image_type}.jpg 约定一致，
                # 避免检测时误报 cover 缺失（patch 检测按 cover.jpg 判定）
                cover_local = await proc.download_cover(
                    cover_src, str(movie_dir), filename="cover.jpg", referer=referer
                )
            samples = getattr(result, "sample_images", None) or []
            if samples:
                sample_local = await proc.download_samples(
                    samples[:6], str(movie_dir), referer=referer
                )
        try:
            generate_nfo(result, str(movie_dir))
        except Exception as e:
            logger.warning(f"NFO 生成失败({code}): {e}")
    except Exception as e:
        logger.warning(f"刮削图片下载失败({code}): {e}")
    return cover_local, sample_local, str(movie_dir)


async def _apply_scrape_result(session, movie, result) -> dict:
    """将刮削结果落地到 movie 记录（字段 + 封面/预览图 + 演员 + NFO 引用）。

    被 scrape_movie 与 scrape_by_code 共用。调用方需自行 commit 前保证 movie 已存在于 session。
    """
    from sqlalchemy import delete as sa_delete
    from app.db.models import Studio, Series, Actor, MovieActor

    if not (result and result.is_valid()):
        return {"status": "failed", "message": "刮削失败，未找到匹配数据"}

    cover_local, sample_local, movie_dir = await _persist_scraped_media(result, movie.code)
    # 记录刮削产物落盘目录（始终更新，以便从 C:\output 迁移到服务端目录）
    if movie_dir:
        movie.output_dir = movie_dir

    if result.title:
        movie.title = result.title
    if result.original_title:
        movie.original_title = result.original_title
    if result.studio:
        studio_obj = await session.scalar(select(Studio).where(Studio.name == result.studio))
        if studio_obj:
            movie.studio_id = studio_obj.id
        else:
            new_studio = Studio(name=result.studio, movie_count=0)
            session.add(new_studio)
            await session.flush()
            movie.studio_id = new_studio.id
    if result.series:
        series_obj = await session.scalar(select(Series).where(Series.name == result.series))
        if series_obj:
            movie.series_id = series_obj.id
        else:
            new_series = Series(name=result.series, movie_count=0)
            session.add(new_series)
            await session.flush()
            movie.series_id = new_series.id
    if result.directors:
        movie.director = result.directors[0]
    if result.release_date:
        movie.release_date = result.release_date
    if result.duration:
        movie.duration = result.duration
    if result.rating is not None:
        movie.rating = result.rating
    if result.plot:
        movie.plot = result.plot
    if result.genres:
        movie.genre = json.dumps(result.genres, ensure_ascii=False)
    if result.cover_url:
        movie.cover_url = cover_local or result.cover_url
    if result.poster_url:
        movie.poster_url = cover_local or result.poster_url
    if cover_local:
        movie.thumb_url = cover_local
    if result.trailer_url:
        movie.trailer_url = result.trailer_url
    if result.source:
        movie.source = result.source
    if result.is_uncensored is not None:
        movie.is_uncensored = result.is_uncensored
    if result.is_mosaic is not None:
        movie.is_mosaic = result.is_mosaic
    if result.is_chinese is not None:
        movie.is_chinese = result.is_chinese
    if result.sample_images:
        movie.sample_images = json.dumps(sample_local or result.sample_images, ensure_ascii=False)

    # 处理演员
    actor_names = list(result.all_actors) if result.all_actors else [
        a.name for a in (result.actors or []) if getattr(a, "name", None)
    ]
    if actor_names:
        await session.execute(
            sa_delete(MovieActor).where(MovieActor.movie_id == movie.id)
        )
        for actor_name in actor_names:
            if not actor_name or actor_name.strip() in ("佚名", ""):
                continue
            actor_obj = await session.scalar(
                select(Actor).where(Actor.name == actor_name.strip())
            )
            if not actor_obj:
                actor_obj = Actor(name=actor_name.strip())
                session.add(actor_obj)
                await session.flush()
            session.add(MovieActor(movie_id=movie.id, actor_id=actor_obj.id))

    movie.status = "scraped"
    movie.scraped_at = datetime.now()
    return {"status": "ok", "message": "刮削成功", "source": result.source}


# ===== NFO 缓存刮削辅助 =====

def _scrape_result_from_nfo(nfo_path: str, code: str):
    """从 NFO 文件构造 ScrapeResult（作为外部刮削的缓存替代，避免重复请求外部站点）"""
    from app.importer.nfo_parser import NFOParser
    from app.crawlers.base import ScrapeResult, ActorInfo

    parser = NFOParser()
    nfo_data = parser.parse_to_dict(nfo_path)
    if not nfo_data:
        return None

    title = nfo_data.get("title") or code
    if not title:
        return None

    # 解析 genre
    genres = []
    gv = nfo_data.get("genre")
    if isinstance(gv, str):
        try:
            genres = json.loads(gv)
        except Exception:
            genres = [g.strip() for g in gv.split(",") if g.strip()]
    elif isinstance(gv, list):
        genres = gv

    # 解析 tag
    tags = []
    tv = nfo_data.get("tag")
    if isinstance(tv, str):
        try:
            tags = json.loads(tv)
        except Exception:
            tags = [t.strip() for t in tv.split(",") if t.strip()]
    elif isinstance(tv, list):
        tags = tv

    # 解析 sample_images
    si = nfo_data.get("sample_images")
    sample_images = si if isinstance(si, list) else []

    # actors → ActorInfo
    raw_actors = nfo_data.get("actors") or []
    if isinstance(raw_actors, str):
        raw_actors = [a.strip() for a in raw_actors.split(",") if a.strip()]
    actors = [ActorInfo(name=str(a)) for a in raw_actors if a]

    # directors
    dv = nfo_data.get("director")
    if isinstance(dv, str):
        directors = [d.strip() for d in dv.split(",") if d.strip()]
    elif isinstance(dv, list):
        directors = dv
    else:
        directors = []

    # release_date 解析
    release_date = None
    rd = nfo_data.get("release_date")
    if rd:
        if isinstance(rd, str):
            from datetime import datetime as _dt
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                try:
                    release_date = _dt.strptime(rd, fmt).date()
                    break
                except Exception:
                    pass

    return ScrapeResult(
        code=code,
        title=title,
        source="nfo_cache",
        original_title=nfo_data.get("original_title") or nfo_data.get("title_jp"),
        studio=nfo_data.get("studio"),
        maker=nfo_data.get("maker"),
        series=nfo_data.get("series"),
        release_date=release_date,
        duration=nfo_data.get("duration"),
        plot=nfo_data.get("plot") or nfo_data.get("plot_short"),
        genres=genres,
        tags=tags,
        actors=actors,
        all_actors=[a.name for a in actors],
        directors=directors,
        is_mosaic=nfo_data.get("is_mosaic"),
        is_uncensored=nfo_data.get("is_uncensored"),
        is_chinese=nfo_data.get("is_chinese"),
        cover_url=nfo_data.get("cover_url"),
        poster_url=nfo_data.get("poster_url"),
        trailer_url=nfo_data.get("trailer_url"),
        sample_images=sample_images,
        rating=nfo_data.get("rating"),
        confidence=0.9,
        is_exact_match=True,
    )


async def _try_scrape_from_nfo(movie) -> Optional[dict]:
    """尝试从已有 NFO 读取刮削结果 → 返回 ScrapeResult 或 None

    优先查 movie.output_dir，fallback 到 config.scraper.output_dir（兼容旧数据 C 盘路径）。
    """
    from app.config.manager import get_config

    # 候选目录列表
    candidates = []
    if getattr(movie, "output_dir", None):
        candidates.append(Path(movie.output_dir))
    # fallback: config 的 scraper 输出目录（已解析为绝对路径）
    try:
        cfg_dir = Path(get_config().scraper.output_dir)
        if cfg_dir not in candidates:
            candidates.append(cfg_dir)
    except Exception:
        pass

    for base in candidates:
        nfo_path = base / "movie.nfo"
        if nfo_path.exists():
            return _scrape_result_from_nfo(str(nfo_path), movie.code)
    return None


@router.post("/scrape-by-code")
async def scrape_by_code(
    code: str = Body(..., embed=True, description="番号"),
    sources: Optional[list[str]] = Body(None, embed=True, description="指定刮削来源站点"),
    force: bool = Body(False, embed=True, description="跳过 NFO 缓存，强制从外部站点重新刮削"),
    session: AsyncSession = Depends(get_session),
):
    """
    按番号刮削并写入/更新影片库

    优先复用对比页「未更新」列表中缺失的影片：刮削成功后创建或更新 Movie 记录，
    并下载封面与预览图（extrafanart）到服务端目录。

    默认优先从已有 movie.nfo 读取缓存（避免重复请求外部站点被限流）。
    """
    from app.scraper.engine import ScraperEngine
    from app.scraper.number import normalize_number
    from app.db.models import Movie

    # 查找已有影片（按原始番号或标准化番号匹配）
    norm = normalize_number(code)
    movie = await session.scalar(select(Movie).where(Movie.code == code))
    if movie is None and norm != code:
        movie = await session.scalar(select(Movie).where(Movie.code == norm))

    # --- NFO 缓存优先 ---
    if not force and movie is not None:
        nfo_result = await _try_scrape_from_nfo(movie)
        if nfo_result:
            resp = await _apply_scrape_result(session, movie, nfo_result)
            if resp["status"] == "ok":
                await session.commit()
                await session.refresh(movie)
                _cache.invalidate("movies:")
                resp["movie_id"] = movie.id
                resp["code"] = code
                resp["source"] = "nfo_cache"
                resp["message"] = "从 NFO 缓存恢复（未请求外部站点）"
            return resp

    engine = ScraperEngine()
    try:
        result = await engine.scrape_number(code, sources=sources)
    except Exception as e:
        return {"status": "error", "message": f"刮削过程中发生错误: {str(e)}"}
    # -- 外部刮削逻辑 --

    if not (result and result.is_valid()):
        return {"status": "failed", "message": "刮削失败，未找到匹配数据", "code": code}

    # 如果 NFO 缓存阶段没找到 movie，这里再查一次（兼容首次刮削新番号）
    if movie is None:
        if norm != code:
            movie = await session.scalar(select(Movie).where(Movie.code == norm))
    if movie is None:
        try:
            movie = Movie(code=code)
            session.add(movie)
            await session.flush()
        except IntegrityError:
            # 并发竞争：auto-scan 或其他请求已插入同番号记录
            await session.rollback()
            movie = await session.scalar(select(Movie).where(Movie.code == code))
            if movie is None and norm != code:
                movie = await session.scalar(select(Movie).where(Movie.code == norm))
            if movie is None:
                return {"status": "error", "message": f"创建影片记录失败（code={code}）", "code": code}

    resp = await _apply_scrape_result(session, movie, result)
    if resp["status"] == "ok":
        await session.commit()
        await session.refresh(movie)
        _cache.invalidate("movies:")
        resp["movie_id"] = movie.id
        resp["code"] = code
    return resp


@router.post("/{movie_id}/scrape")
async def scrape_movie(
    movie_id: int,
    force: bool = Query(False, description="跳过 NFO 缓存，强制从外部站点重新刮削"),
    session: AsyncSession = Depends(get_session),
):
    """
    刮削单个电影的元数据

    默认优先从已有 movie.nfo 读取缓存数据（避免重复请求外部站点被限流）。
    传 force=true 可强制从外部站点重新刮削。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")
    
    if not movie.code:
        raise HTTPException(status_code=400, detail="视频没有番号，无法刮削")
    
    from app.scraper.engine import ScraperEngine
    from datetime import datetime

    # --- NFO 缓存优先 ---
    if not force:
        nfo_result = await _try_scrape_from_nfo(movie)
        if nfo_result:
            resp = await _apply_scrape_result(session, movie, nfo_result)
            if resp["status"] == "ok":
                await session.commit()
                await session.refresh(movie)
                _cache.invalidate("movies:")
                resp["source"] = "nfo_cache"
                resp["message"] = "从 NFO 缓存恢复（未请求外部站点）"
            return resp

    engine = ScraperEngine()

    try:
        # 执行外部刮削
        result = await engine.scrape_number(movie.code)

        resp = await _apply_scrape_result(session, movie, result)
        if resp["status"] == "ok":
            await session.commit()
            await session.refresh(movie)
            _cache.invalidate("movies:")
            resp["source"] = "external"

        return resp

    except Exception as e:
        return {
            "status": "error",
            "message": f"刮削过程中发生错误: {str(e)}",
        }


@router.get("/{movie_id}", response_model=MovieResponse)
async def get_movie(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取视频详情（含演员列表）—— 带 30 秒缓存"""
    cache_key = f"movies:detail:{movie_id}"
    cached = _cache.get(cache_key, ttl=30)
    if cached is not None:
        return cached

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 批量获取演员列表
    actor_query = (
        select(Actor.id, Actor.name)
        .join(MovieActor, Actor.id == MovieActor.actor_id)
        .where(MovieActor.movie_id == movie_id)
    )
    actor_result = await session.execute(actor_query)
    actors = [ActorBrief(id=row[0], name=row[1]) for row in actor_result.fetchall()]

    # 批量获取 studio/series 名称（一次查询替代两次独立查询）
    studio_name = None
    series_name = None
    lookup_ids = {}
    if movie.studio_id:
        lookup_ids["studio"] = movie.studio_id
    if movie.series_id:
        lookup_ids["series"] = movie.series_id
    if lookup_ids:
        name_result = await session.execute(
            select(Studio.id, Studio.name).where(Studio.id.in_(
                [v for v in lookup_ids.values() if v]
            ))
        )
        name_map = {row[0]: row[1] for row in name_result.fetchall()}
        if movie.studio_id:
            studio_name = name_map.get(movie.studio_id)
        if movie.series_id and movie.series_id in name_map:
            series_name = name_map.get(movie.series_id)

    # 获取标签列表
    tag_query = (
        select(Tag.id, Tag.name, Tag.is_user)
        .join(MovieTag, MovieTag.tag_id == Tag.id)
        .where(MovieTag.movie_id == movie_id)
    )
    tag_result = await session.execute(tag_query)
    tags = [
        TagBrief(id=row[0], name=row[1], is_user=bool(row[2]))
        for row in tag_result.fetchall()
    ]

    resp = MovieResponse(
        id=movie.id,
        code=movie.code,
        title=movie.title,
        original_title=movie.original_title,
        title_jp=movie.title_jp,
        studio_id=movie.studio_id,
        studio=studio_name,
        maker=movie.maker,
        series_id=movie.series_id,
        series=series_name,
        director=movie.director,
        release_date=movie.release_date,
        duration=movie.duration,
        rating=movie.rating,
        plot=movie.plot,
        plot_short=movie.plot_short,
        genre=_parse_json_list(movie.genre),
        tag=_parse_json_list(movie.tag),
        cover_url=movie.cover_url,
        poster_url=movie.poster_url,
        thumb_url=movie.thumb_url,
        trailer_url=movie.trailer_url,
        source=movie.source,
        source_url=movie.source_url,
        is_uncensored=movie.is_uncensored,
        is_mosaic=movie.is_mosaic,
        is_chinese=movie.is_chinese,
        is_leak=movie.is_leak,
        file_path=movie.file_path,
        file_size=movie.file_size,
        sample_images=_parse_sample_images(movie.sample_images),
        play_count=movie.play_count or 0,
        last_played_at=movie.last_played_at.isoformat() if movie.last_played_at else None,
        status=movie.status,
        actors=actors,
        tags=tags,
    )
    _cache.set(cache_key, resp)
    return resp


