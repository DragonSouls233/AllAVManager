"""MacCMS v10 采集接口路由（§7.10）

实现苹果 CMS v10 的采集 API 规范，让支持 MacCMS 协议的客户端
（如 TVBox、各种影视 App、其他苹果 CMS 站点互采）能直接接入 MDCX 媒体库。

参考：苹果 CMS v10 采集接口规范
- 所有接口位于 /api.php/provide/vod/
- 通过 ac 参数区分行为：list / detail / videolist
- 返回标准 MacCMS JSON：code/msg/page/pagecount/limit/total/list

挂在 /maccms 路径下，不走 /api/v1 前缀，不走 AuthMiddleware 认证。
通过 query 参数 token 进行简单鉴权（在 TvboxConfig.token 中配置）。

字段映射：
- Movie.code        -> vod_name（影片名/番号）
- Movie.title       -> vod_sub（副标题）
- Movie.cover_url   -> vod_pic（封面图）
- Movie.plot        -> vod_content（简介）
- Movie.release_date -> vod_pubdate（发布日期）
- Movie.duration    -> vod_duration（时长，分钟）
- play_url          -> vod_play_url（播放地址）

端点：
- GET /maccms/api.php/provide/vod/?ac=list                  影片列表
- GET /maccms/api.php/provide/vod/?ac=detail&ids=xxx        影片详情
- GET /maccms/api.php/provide/vod/?ac=videolist&ids=xxx     视频列表（含播放地址）
- GET /maccms/api.php/provide/vod/?wd=xxx                   搜索
- GET /maccms/api.php/provide/vod/?t=xxx                    分类筛选
- GET /maccms/api.php/provide/vod/?h=24                     24小时更新
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor, Studio, Series, FavoriteItem
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ============== 鉴权与工具函数 ==============

def _verify_token(token: Optional[str] = None) -> None:
    """简单 token 校验（query 参数 ?token=xxx）

    - 配置中 token 为空：放行（开放访问）
    - 配置中 token 非空：必须传入匹配的 token
    """
    cfg = get_config().tvbox
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="MacCMS 接口未启用")
    if cfg.token and token != cfg.token:
        raise HTTPException(status_code=401, detail="Token 无效")


def _build_base_url(request: Request) -> str:
    """根据请求构造服务基础 URL"""
    cfg = get_config()
    server_host = getattr(cfg.server, "host", "127.0.0.1")
    server_port = getattr(cfg.server, "port", 8420)
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        proto = request.headers.get("x-forwarded-proto", "http")
        return f"{proto}://{forwarded.split(',')[0].strip()}"
    if server_host in ("0.0.0.0", "127.0.0.1", "localhost"):
        return f"http://localhost:{server_port}"
    return f"http://{server_host}:{server_port}"


def _build_play_url(movie_id: int, base_url: str) -> str:
    """构造播放 URL（指向 /tvbox/stream/{id}，TVBox 端的公开流媒体端点）

    格式遵循 MacCMS 规范：播放源标识$播放URL
    多个集数用 # 分隔，多个播放源用 $$$ 分隔
    """
    cfg = get_config().tvbox
    token_part = f"&token={cfg.token}" if cfg.token else ""
    stream_url = f"{base_url}/tvbox/stream/{movie_id}{token_part}"
    return f"{cfg.play_from}${stream_url}"


def _apply_nsfw_filter(query, nsfw_hidden: bool):
    """NSFW 模式：仅展示已收藏的影片"""
    if not nsfw_hidden:
        return query
    fav_subq = select(FavoriteItem.entity_id).where(FavoriteItem.entity_type == "movie")
    return query.where(Movie.id.in_(fav_subq))


def _apply_category_filter(query, t: Optional[str]):
    """根据 MacCMS 分类 ID 应用筛选（与 TVBox 分类保持一致）"""
    if not t or t in ("0", "all"):
        return query
    if t == "censored":
        return query.where(Movie.is_uncensored == False)  # noqa: E712
    if t == "uncensored":
        return query.where(Movie.is_uncensored == True)  # noqa: E712
    if t == "chinese":
        return query.where(Movie.is_chinese == True)  # noqa: E712
    return query


# ============== MacCMS 列表项构建 ==============

def _movie_to_vod_list_item(movie: Movie) -> dict:
    """Movie -> MacCMS 列表项（ac=list 精简字段）"""
    cfg = get_config().tvbox
    if cfg.nsfw_hidden:
        vod_name = movie.code
        vod_sub = ""
    else:
        vod_name = movie.code
        vod_sub = movie.title or ""
    return {
        "vod_id": str(movie.id),
        "vod_name": vod_name,
        "vod_sub": vod_sub,
        "vod_pic": movie.cover_url or movie.poster_url or "",
        "vod_remarks": movie.release_date or "",
        "vod_pubdate": movie.release_date or "",
    }


def _movie_to_vod_detail_item(movie: Movie, base_url: str, session: AsyncSession) -> dict:
    """Movie -> MacCMS 详情项（ac=detail 完整字段）

    演员列表需在调用处异步查询后填充。
    """
    cfg = get_config().tvbox
    if cfg.nsfw_hidden:
        vod_name = movie.code
        vod_sub = ""
        vod_content = ""
    else:
        vod_name = movie.code
        vod_sub = movie.title or ""
        vod_content = movie.plot or movie.plot_short or ""

    vod_play_url = _build_play_url(movie.id, base_url)

    item = {
        "vod_id": str(movie.id),
        "vod_name": vod_name,
        "vod_sub": vod_sub,
        "vod_pic": movie.cover_url or movie.poster_url or "",
        "vod_content": vod_content,
        "vod_remarks": movie.release_date or "",
        "vod_pubdate": movie.release_date or "",
        "vod_year": (movie.release_date[:4] if movie.release_date and len(movie.release_date) >= 4 else ""),
        "vod_area": "日本",
        "vod_type": "电影",
        "vod_lang": "日语",
        "vod_duration": str(movie.duration // 60) if movie.duration else "",
        "vod_play_from": cfg.play_from,
        "vod_play_url": vod_play_url,
        "vod_actor": "",
        "vod_director": movie.director or "",
        "vod_score": f"{movie.rating:.1f}" if movie.rating else "",
    }
    return item


def _movie_to_vod_video_item(movie: Movie, base_url: str) -> dict:
    """Movie -> MacCMS 视频列表项（ac=videolist 含播放地址）"""
    cfg = get_config().tvbox
    if cfg.nsfw_hidden:
        vod_name = movie.code
    else:
        vod_name = f"[{movie.code}] {movie.title}" if movie.title else movie.code

    vod_play_url = _build_play_url(movie.id, base_url)

    return {
        "vod_id": str(movie.id),
        "vod_name": vod_name,
        "vod_pic": movie.cover_url or movie.poster_url or "",
        "vod_remarks": movie.release_date or "",
        "vod_play_from": cfg.play_from,
        "vod_play_url": vod_play_url,
    }


# ============== MacCMS 标准响应包装 ==============

def _maccms_response(
    list_items: list,
    total: int,
    page: int,
    limit: int,
    code: int = 1,
    msg: str = "数据列表",
) -> dict:
    """构造 MacCMS 标准 JSON 响应

    - code: 1=成功 / 0=失败
    - msg: 提示信息
    - page: 当前页码
    - pagecount: 总页数
    - limit: 每页条数
    - total: 总条目数
    - list: 数据列表
    """
    pagecount = (total + limit - 1) // limit if limit > 0 else 0
    return {
        "code": code,
        "msg": msg,
        "page": page,
        "pagecount": pagecount,
        "limit": limit,
        "total": total,
        "list": list_items,
    }


# ============== MacCMS 端点 ==============

@router.get("/api.php/provide/vod/")
@router.get("/api.php/provide/vod")
async def maccms_provide_vod(
    request: Request,
    token: Optional[str] = None,
    ac: Optional[str] = Query(None, description="行为: list/detail/videolist"),
    ids: Optional[str] = Query(None, description="影片ID，多个用逗号分隔"),
    wd: Optional[str] = Query(None, description="搜索关键字"),
    t: Optional[str] = Query(None, description="分类ID"),
    h: Optional[int] = Query(None, description="最近 h 小时更新"),
    pg: int = Query(1, ge=1, description="页码"),
    pgc: Optional[int] = Query(None, description="总页数（客户端回传）"),
    session: AsyncSession = Depends(get_session),
):
    """MacCMS v10 采集接口入口

    通过 ac 参数区分行为：
    - ac=list: 影片列表（精简字段）
    - ac=detail: 影片详情（完整字段，需传 ids）
    - ac=videolist: 视频列表（含播放地址，需传 ids）
    - 不传 ac: 默认按列表处理
    - wd: 搜索
    - t: 分类筛选
    - h: 最近 h 小时更新
    """
    _verify_token(token)
    cfg = get_config().tvbox
    page_size = cfg.page_size
    base_url = _build_base_url(request)

    # ===== ac=detail / ac=videolist: 按 ids 查询详情 =====
    if ac in ("detail", "videolist"):
        if not ids:
            return _maccms_response([], 0, pg, page_size, msg="ids 不能为空")
        try:
            id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        except ValueError:
            return _maccms_response([], 0, pg, page_size, code=0, msg="ids 格式错误")

        if not id_list:
            return _maccms_response([], 0, pg, page_size, msg="无有效 ID")

        result = await session.execute(
            select(Movie).where(Movie.id.in_(id_list))
        )
        movies = result.scalars().all()

        if ac == "detail":
            items = [_movie_to_vod_detail_item(m, base_url, session) for m in movies]
            # 填充演员
            if not cfg.nsfw_hidden:
                for item, movie in zip(items, movies):
                    actor_result = await session.execute(
                        select(Actor.name)
                        .join(MovieActor, MovieActor.actor_id == Actor.id)
                        .where(MovieActor.movie_id == movie.id)
                        .limit(20)
                    )
                    actors = [r[0] for r in actor_result.fetchall()]
                    item["vod_actor"] = ",".join(actors)
        else:  # videolist
            items = [_movie_to_vod_video_item(m, base_url) for m in movies]

        return _maccms_response(items, len(items), 1, len(items), msg="数据列表")

    # ===== ac=list 或默认: 列表查询 =====
    query = select(Movie).where(Movie.file_path.isnot(None))
    query = _apply_nsfw_filter(query, cfg.nsfw_hidden)

    # 搜索
    if wd:
        kw = f"%{wd}%"
        query = query.where(
            or_(
                Movie.code.like(kw),
                Movie.title.like(kw),
                Movie.original_title.like(kw),
            )
        )

    # 分类筛选
    query = _apply_category_filter(query, t)

    # 最近 h 小时更新
    if h and h > 0:
        threshold = datetime.now() - timedelta(hours=h)
        query = query.where(Movie.updated_at >= threshold)

    # 总数
    count_query = select(func.count(Movie.id)).where(Movie.file_path.isnot(None))
    count_query = _apply_nsfw_filter(count_query, cfg.nsfw_hidden)
    if wd:
        kw = f"%{wd}%"
        count_query = count_query.where(
            or_(
                Movie.code.like(kw),
                Movie.title.like(kw),
                Movie.original_title.like(kw),
            )
        )
    count_query = _apply_category_filter(count_query, t)
    if h and h > 0:
        threshold = datetime.now() - timedelta(hours=h)
        count_query = count_query.where(Movie.updated_at >= threshold)

    total = await session.scalar(count_query) or 0

    # 排序：最新更新优先
    query = query.order_by(Movie.updated_at.desc().nulls_last(), Movie.id.desc())
    query = query.offset((pg - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    movies = result.scalars().all()

    items = [_movie_to_vod_list_item(m) for m in movies]
    return _maccms_response(items, total, pg, page_size, msg="数据列表")


# ============== MacCMS 类型列表（分类列表） ==============

@router.get("/api.php/provide/vod_type/")
@router.get("/api.php/provide/vod_type")
async def maccms_vod_type(token: Optional[str] = None):
    """MacCMS 分类列表（部分客户端会请求）

    返回 type_list，与 TVBox home.html 的分类保持一致。
    """
    _verify_token(token)
    return {
        "code": 1,
        "msg": "分类列表",
        "type_list": [
            {"type_id": "all", "type_name": "全部"},
            {"type_id": "censored", "type_name": "有码"},
            {"type_id": "uncensored", "type_name": "无码"},
            {"type_id": "chinese", "type_name": "中字"},
            {"type_id": "latest", "type_name": "最新"},
            {"type_id": "hot", "type_name": "热门"},
        ],
    }


# ============== MacCMS 站点信息 ==============

@router.get("/api.php/provide/vod_site/")
@router.get("/api.php/provide/vod_site")
async def maccms_vod_site(request: Request, token: Optional[str] = None):
    """MacCMS 站点信息（部分客户端会请求采集源信息）"""
    _verify_token(token)
    cfg = get_config().tvbox
    base_url = _build_base_url(request)
    token_part = f"?token={cfg.token}" if cfg.token else ""
    return {
        "code": 1,
        "msg": "站点信息",
        "site": {
            "site_name": cfg.site_name,
            "site_url": f"{base_url}/maccms/api.php/provide/vod/{token_part}",
            "site_version": "1.0.0",
            "site_protocol": "http",
        },
    }


__all__ = ["router"]
