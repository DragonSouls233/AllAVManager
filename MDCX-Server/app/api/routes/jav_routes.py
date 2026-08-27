"""
JAV 有码模块 API 路由

包含：
- 只读端点（列表/详情）
- 刮削端点（单部/批量/自动）
- NFO 导入端点
"""

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jav", tags=["JAV有码"])


# ---- 真演员判定（2026-08-19）----
# movies.actor 精确 token 集合，用于：
#   * 列表页只显示真演员（排除单字符/素人称呼/匿名占位/假名短名/孤儿垃圾）
#   * 详情页对垃圾条目 404（防止 LIKE 子串匹配命中大量无关作品，如 'a' 命中 254 部）
_real_actor_cache: dict = {"ts": 0.0, "names": None}
_REAL_ACTOR_TTL = 60.0

# 演员作品数缓存：列表页 60s 内不再重复计算（详情页 / 合并操作后自动失效）
_movie_count_cache: dict = {"ts": 0.0, "counts": None}  # {actor_id: real_count}

# 匿名/占位词：刮削或解析时把"空演员"写成的占位文本，不是真人（佚名=匿名）
_ANON_WORDS = {
    "佚名", "匿名", "素人", "無名", "未知",
    "unknown", "Unknown", "N/A", "n/a",
    "anonym", "anonymous", "xxx", "XXX",
}
# 纯假名正则（无空格）
_KANA_PURE_RE = re.compile(r"^[\u3040-\u30ff\u30fc]+$")
# 含空格的假名：如「かな み」—— 去空格后若 ≤3 假名则为垃圾（真演员 3+ 假名名极少含空格）
_KANA_WITH_SPACE_RE = re.compile(r"^[\u3040-\u30ff\u30fc][\s\u3000][\u3040-\u30ff\u30fc]+$")
# 纯半角拉丁单字符：扫描器兜底产生的垃圾（如 'a'/'o'/'e'）
_LATIN_SINGLE_RE = re.compile(r"^[a-zA-Z]$")


async def _real_actor_names(session) -> set:
    """返回 movies.actor 的全部精确 token 集合（真演员名判定依据）。

    带 60s TTL 缓存，避免列表页分页 / 详情页每次请求都全表扫描。
    """
    import time as _time
    from sqlalchemy import select
    from app.db.jav_models import JavMovie
    from app.utils.actor_alias import split_alias

    now = _time.monotonic()
    c = _real_actor_cache
    if c["names"] is not None and now - c["ts"] < _REAL_ACTOR_TTL:
        return c["names"]
    names: set = set()
    rows = await session.execute(
        select(JavMovie.actor).where(JavMovie.actor.isnot(None)).distinct()
    )
    for (actor_field,) in rows:
        names.update(split_alias(actor_field))
    c.update({"ts": now, "names": names})
    return names


def _is_real_actor(actor, real_names: set, real_counts: dict = None) -> bool:
    """真演员判定：排除 1) 单字符解析残留 2) 匿名占位词 3) 素人称呼名
    4) 名字未完整出现在 movies.actor 的孤儿/短名条目 5) 纯假名短名（≤2假名无空格）
    6) 含空格的纯假名（去空格后 ≤3假名，如「かな み」「うみ う」）
    7) 纯半角拉丁单字符（扫描器兜底垃圾）

    real_counts: {actor_id: real_count} 传入后可用实时作品数判断 3-假名垃圾；
    不传时回退到 actor.movie_count（可能过时，但 3-假名+0 作品的垃圾仍可拦）。
    """
    name = (getattr(actor, "name", None) or "").strip()
    if len(name) <= 1:
        return False
    if name in _ANON_WORDS:
        return False
    if name.endswith(("さん", "ちゃん", "くん", "様")):
        return False
    if name not in real_names:
        return False
    if _LATIN_SINGLE_RE.match(name):
        return False
    # 含空格的纯假名 → 去空格后若 ≤3 假名，判垃圾（真演员极少用 3 假名+空格的写法）
    if _KANA_WITH_SPACE_RE.match(name):
        name_no_space = name.replace(" ", "").replace("\u3000", "")
        if len(name_no_space) <= 3:
            return False
    # 无空格的纯假名 ≤2 → 判垃圾（きこ、み 等）
    if _KANA_PURE_RE.match(name) and len(name) <= 2:
        return False
    # 纯假名 3 字（うみう）且作品数为 0 → 判垃圾
    # 注：真演员 3 假名名（まゆみ/ゆきこ）通常有 ≥1 部作品
    if _KANA_PURE_RE.match(name) and len(name) == 3:
        cnt = real_counts.get(actor.id) if real_counts else None
        if cnt is None:
            cnt = getattr(actor, "movie_count", None)
        if cnt is not None and cnt == 0:
            return False
    return True


def _fill_amateur_actor(movie) -> str:
    """素人模式：当影片 actor 为空时，根据 code 前缀匹配公司名"""
    from pathlib import Path as _Path
    from app.config.manager import get_config
    if movie and movie.actor:
        return movie.actor
    try:
        cfg = get_config()
        prefix_map = getattr(cfg.modules.jav, "amateur_prefix_map", None) or {}
        amateur_enabled = getattr(cfg.modules.jav, "amateur_enabled", False)
        amateur_dirs = getattr(cfg.modules.jav, "amateur_media_dirs", None) or []
        if not amateur_enabled or not prefix_map or not amateur_dirs:
            return movie.actor if movie else ""
        # 检查 file_path 是否在素人目录中
        if not movie or not movie.file_path:
            return movie.actor if movie else ""
        fp = _Path(movie.file_path).resolve()
        for d in amateur_dirs:
            try:
                base = _Path(d).resolve()
                if base in fp.parents or fp == base:
                    break
            except Exception:
                continue
        else:
            # 不在任何素人目录中
            return movie.actor if movie else ""
    except Exception:
        return movie.actor if movie else ""
    code = (movie.code or "").upper().strip()
    sorted_prefixes = sorted(prefix_map.keys(), key=len, reverse=True)
    for prefix in sorted_prefixes:
        if code.startswith(prefix.upper()):
            return prefix_map[prefix]
    if movie and movie.actor:
        # 全局去重：去掉重复的演员名
        names = [n.strip() for n in movie.actor.split(",") if n.strip()]
        seen = set()
        deduped = []
        for n in names:
            if n not in seen:
                seen.add(n)
                deduped.append(n)
        return ",".join(deduped)
    return ""


def get_jav_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("jav")


# 空头像占位图（与 modules.py 保持一致，避免前端 @error 裂图差异）
_SVG_EMPTY_AVATAR = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" '
    'viewBox="0 0 120 120"><rect width="120" height="120" rx="60" fill="#374151"/>'
    '<text x="60" y="74" text-anchor="middle" font-size="48" font-family="Arial" '
    'fill="#9ca3af">?</text></svg>'
)


def _avatar_placeholder():
    from fastapi.responses import Response
    return Response(content=_SVG_EMPTY_AVATAR, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-cache"})


# ========== 演员合并 ==========


@router.post("/actors/merge")
async def api_merge_actors(data: dict):
    """合并演员（将 source_ids 合并到 canonical_id）"""
    # 注意：merge_actors 内部自建 module session，这里不要再传 session，
    # 否则会作为位置参数误入 canonical_id（历史 bug：AttributeError/TypeError 500）
    from app.services.actor_merge_service import merge_actors
    result = await merge_actors(
        canonical_id=data.get("canonical_id", 0),
        source_ids=data.get("source_ids", []),
    )
    return result


@router.get("/actors/similar")
async def api_search_similar_actors(name: str = Query(..., description="搜索相似演员")):
    """搜索名字相似的演员（推荐合并候选）"""
    from app.services.actor_merge_service import search_similar_actors
    result = await search_similar_actors(name)
    return {"items": result, "total": len(result)}


@router.get("/actors/{actor_id}/merge-candidates")
async def api_merge_candidates(actor_id: int):
    """获取指定演员的合并候选列表"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavActor
        from sqlalchemy import select
        from app.services.actor_merge_service import search_similar_actors

        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        candidates = await search_similar_actors(actor.name)
        return {"actor": {"id": actor.id, "name": actor.name, "alias": actor.alias, "movie_count": actor.movie_count},
                "candidates": candidates, "total": len(candidates)}
    finally:
        await session.close()


# ========== 番号提取测试 ==========


@router.post("/code-extract-test")
async def api_code_extract_test(data: dict):
    """测试从文件名提取番号

    参考 JavBoss v1.8.0 番号提取测试工具
    """
    filename = data.get("filename", "")
    if not filename:
        return {"error": "filename is required"}

    from app.scraper.number import extract_number, extract_number_from_path
    # 提取番号（先尝试直接文件名）
    result = extract_number(filename)
    codes = []
    if result and result.number:
        codes.append({
            "code": result.number,
            "type": "direct",
            "is_chinese": result.is_chinese,
            "is_uncensored": result.is_uncensored,
        })
    return {
        "filename": filename,
        "extracted_codes": codes,
        "count": len(codes),
    }


# ========== 只读端点 ==========


@router.get("/actors")
async def list_actors(
    search: Optional[str] = Query(None, description="按名字/日文名/别名搜索"),
    movie_count_filter: Optional[str] = Query(None, description="作品数过滤: all/multi/single"),
    min_movies: int = Query(2, ge=1, le=20, description="多作品阈值(部): multi>=此值归多作品, single<此值归素人"),
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=240),
):
    """列出有码演员列表（只显示真演员；支持作品数分类过滤与分页）"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavActor, JavMovie
        from sqlalchemy import select
        from app.utils.actor_alias import count_actor_movies

        # 真演员过滤（2026-08-19）：排除刮削/文件夹解析产生的垃圾与素人匿名条目。
        # 1) 单字符名（'a'/'o'/'e'/'杏'/'桜' 等解析残留）
        # 2) 匿名占位词（佚名/匿名/Unknown 等）
        # 3) 素人称呼名（以 さん/ちゃん/くん/様 结尾）
        # 4) 孤儿/短名条目：名字未完整出现在任何电影 actor 字段
        # 5) 纯假名短名（≤2 假名，素人片匿名角色常见写法）
        # 规则在 Python 侧统一判定（SQL 无法表达匿名词/假名短名），全量拉取后过滤再分页。
        real_names = await _real_actor_names(session)
        rows = (await session.execute(select(JavActor))).scalars().all()

        # 作品数实时计算（2026-08-19）：先算全部（垃圾也在内），再过滤。
        # 60s TTL 缓存；详情页 / 合并操作后自动失效。
        import time as _tm
        now = _tm.monotonic()
        c = _movie_count_cache
        counts_map = c["counts"]
        if counts_map is None or now - c["ts"] >= _REAL_ACTOR_TTL:
            counts_map = {}
            for a in rows:
                cnt = await count_actor_movies(session, JavMovie, a)
                counts_map[a.id] = cnt
            c.update({"ts": now, "counts": counts_map})

        # 真演员过滤（传入 real_counts 供 3-假名规则使用）
        items = [a for a in rows if _is_real_actor(a, real_names, counts_map)]
        if search:
            key = search.strip().lower()
            items = [a for a in items if
                     key in (a.name or "").lower()
                     or key in (a.name_jp or "").lower()
                     or key in (a.name_en or "").lower()
                     or (a.alias and key in a.alias.lower())]

        # 用实时数过滤 + 排序（降序：作品多的在前）
        if movie_count_filter == "multi":
            items = [a for a in items if counts_map.get(a.id, 0) >= min_movies]
        elif movie_count_filter == "single":
            items = [a for a in items if counts_map.get(a.id, 0) < min_movies]
        items.sort(key=lambda a: counts_map.get(a.id, 0), reverse=True)

        total = len(items)
        page_items = items[(page - 1) * page_size: page * page_size]
        # alias / merged_from：让列表页能直观标出「这个演员合并过哪些旧名」
        from app.utils.actor_alias import merged_from_names
        return {"total": total, "items": [{"id": a.id, "name": a.name, "movie_count": counts_map.get(a.id, 0),
                 "module_type": "jav",
                 "alias": a.alias, "merged_from": merged_from_names(a),
                 "source": a.source, "avatar_url": a.avatar_url} for a in page_items]}
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取有码演员详情"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavActor
        from sqlalchemy import select
        stmt = select(JavActor).where(JavActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        # 真演员防护（2026-08-19）：垃圾条目（单字符/素人称呼/孤儿）不再对外展示，
        # 避免详情页按 LIKE 子串匹配命中大量无关作品（如 'a' 命中 254 部）。
        real_names = await _real_actor_names(session)
        if not _is_real_actor(actor, real_names):
            raise HTTPException(status_code=404, detail="演员不存在")
        from app.db.jav_models import JavMovie
        from app.utils.actor_alias import count_actor_movies, merged_from_names
        real_count = await count_actor_movies(session, JavMovie, actor)
        return {"id": actor.id, "name": actor.name, "alias": actor.alias,
                    "merged_from": merged_from_names(actor),
                    "module_type": "jav",
                    "avatar_url": actor.avatar_url, "source": actor.source,
                    "source_site": actor.source_site,
                    "movie_count": real_count,
                    "created_at": str(actor.created_at)}
    finally:
        await session.close()


@router.get("/actors/{actor_id}/movies")
async def get_actor_movies(
    actor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    starring_first: bool = Query(True, description="主演片（标题含演员名）优先"),
):
    """获取演员作品列表

    主演/共演区分（2026-08-19）：
    - 主演片：标题（title/original_title）含演员任一名变体（如「辻井みう」作品标题直接写她名字）
    - 共演片：仅 actor 字段含该演员（如 534/535 的大量固定搭档共演片，封面是其他演员，
      页面看起来"全是各种其他演员"）——默认主演片排前，并返回 is_starring 标记与统计。
    """
    from app.db.jav_models import JavActor, JavMovie
    from sqlalchemy import select, func, or_, case

    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        # 真演员防护（2026-08-19）：垃圾条目不返回其"作品列表"（LIKE 子串误匹配）
        real_names = await _real_actor_names(session)
        if not _is_real_actor(actor, real_names):
            raise HTTPException(status_code=404, detail="演员不存在")

        offset = (page - 1) * page_size
        # 搜索含有演员名的影片：主名 + alias 全部变体
        # （演员合并后旧名仍残留在 movies.actor 里，只查主名会漏掉被合并演员的作品）
        from app.utils.actor_alias import actor_movie_condition_for, actor_name_variants
        cond = actor_movie_condition_for(JavMovie, actor)
        variants = actor_name_variants(actor)

        # 主演判定：标题（title/original_title）含任一演员名变体
        title_cols = [JavMovie.title]
        if hasattr(JavMovie, "original_title"):
            title_cols.append(JavMovie.original_title)
        starring_clauses = []
        for v in variants:
            for col in title_cols:
                starring_clauses.append(col.like(f"%{v}%"))
        starring_cond = or_(*starring_clauses) if starring_clauses else None

        total = (await session.execute(select(func.count(JavMovie.id)).where(cond))).scalar() or 0
        if starring_cond is not None:
            starring_total = (await session.execute(
                select(func.count(JavMovie.id)).where(cond, starring_cond)
            )).scalar() or 0
        else:
            starring_total = 0

        stmt = select(JavMovie).where(cond)
        if starring_first and starring_cond is not None:
            # 主演片排前，其余按日期倒序
            stmt = stmt.order_by(
                case((starring_cond, 0), else_=1),
                JavMovie.release_date.desc().nulls_last(),
                JavMovie.id.desc(),
            )
        else:
            stmt = stmt.order_by(
                JavMovie.release_date.desc().nulls_last(), JavMovie.id.desc()
            )
        stmt = stmt.offset(offset).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()

        # 主演标记：标题含演员名（与 starring_cond 同规则）
        def _is_starring(m) -> bool:
            texts = [m.title or ""]
            if hasattr(m, "original_title") and m.original_title:
                texts.append(m.original_title or "")
            return any(v and any(v in t for t in texts) for v in variants)

        items = []
        for m in rows:
            items.append({
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url, "poster_url": m.poster_url,
                "release_date": str(m.release_date) if m.release_date else None,
                "duration": m.duration, "rating": m.rating,
                "studio": m.studio, "maker": getattr(m, "maker", None),
                "genre": m.genre,
                "is_chinese": m.is_chinese,
                "is_uncensored": m.is_uncensored,
                "is_leak": m.is_leak,
                "is_4k": m.is_4k,
                "module_type": "jav",
                "is_starring": _is_starring(m),
                "file_path": m.file_path,
            })
        return {
            "items": items, "total": total, "page": page, "page_size": page_size,
            "starring_total": starring_total,
            "co_star_total": total - starring_total,
        }
    finally:
        await session.close()


@router.get("/actors/{actor_id}/timeline")
async def get_actor_timeline(actor_id: int):
    """获取演员作品时间线

    返回结构必须与前端 ActorDetail.vue 时间线视图严格对齐：
    total / years / details / unknown / year_range / debut_year 缺一不可，
    否则前端 v-if="timeline.total > 0" 直接判空，时间线永远显示"暂无作品"。
    MovieActor 关联表恒为空，只能靠 movie.actor 字段模糊匹配（与 actors.py 一致）。
    """
    from app.db.jav_models import JavActor, JavMovie
    from sqlalchemy import select
    from collections import defaultdict

    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        # 真演员防护（2026-08-19）：垃圾条目不返回时间线
        real_names = await _real_actor_names(session)
        if not _is_real_actor(actor, real_names):
            raise HTTPException(status_code=404, detail="演员不存在")

        # 查该演员全部作品（含无日期），用于 total 与完整年份分组
        # 条件含 alias 全部变体，保证合并后的作品一并计入时间线
        from app.utils.actor_alias import actor_movie_condition_for
        movies = (await session.execute(
            select(JavMovie).where(actor_movie_condition_for(JavMovie, actor))
        )).scalars().all()

        total = len(movies)

        year_map = defaultdict(list)
        unknown_movies = []
        for m in movies:
            if m.release_date:
                try:
                    y = int(str(m.release_date)[:4])
                except (ValueError, TypeError):
                    y = None
                if y:
                    year_map[y].append(m)
                else:
                    unknown_movies.append(m)
            else:
                unknown_movies.append(m)

        # 年份降序（与前端柱状图一致）
        sorted_years = sorted(year_map.keys(), reverse=True)
        years_data = [{"year": y, "count": len(year_map[y])} for y in sorted_years]

        # 每年来源详情：按日期降序，避免详情与柱状图数量不一致
        details = []
        for y in sorted_years:
            ms = sorted(
                year_map[y],
                key=lambda x: str(x.release_date) if x.release_date else "",
                reverse=True,
            )
            details.append({
                "year": y,
                "count": len(ms),
                "movies": [{
                    "id": m.id, "code": m.code, "title": m.title,
                    "cover_url": m.cover_url,
                    "release_date": m.release_date,
                    "is_chinese": m.is_chinese,
                    "is_uncensored": m.is_uncensored,
                    "is_leak": m.is_leak,
                    "is_4k": m.is_4k,
                    "module_type": "jav",
                } for m in ms],
            })

        first_year = sorted_years[-1] if sorted_years else None
        last_year = sorted_years[0] if sorted_years else None
        debut_year = actor.debut_year or first_year

        unknown_data = {
            "year": None,
            "count": len(unknown_movies),
            "movies": [{
                "id": m.id, "code": m.code, "title": m.title,
                "cover_url": m.cover_url,
                "release_date": m.release_date,
                "is_chinese": m.is_chinese,
                "is_uncensored": m.is_uncensored,
                "is_leak": m.is_leak,
                "is_4k": m.is_4k,
                "module_type": "jav",
            } for m in unknown_movies],
        } if unknown_movies else None

        return {
            "actor_id": actor_id,
            "actor_name": actor.name,
            "total": total,
            "years": years_data,
            "details": details,
            "unknown": unknown_data,
            "year_range": [first_year, last_year],
            "debut_year": debut_year,
            "module_type": "jav",
        }
    finally:
        await session.close()


@router.get("/actors/{actor_id}/tags")
async def get_actor_tags(actor_id: int):
    """获取演员标签"""
    from app.db.jav_models import JavActor
    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"tags": [], "module_type": "jav"}
    finally:
        await session.close()


@router.get("/actors/{actor_id}/avatar/file")
async def get_actor_avatar_file(actor_id: int):
    """获取演员头像文件"""
    from app.db.jav_models import JavActor
    from fastapi.responses import FileResponse
    from pathlib import Path as _Path

    db = get_jav_db()
    session = await db.get_session()
    try:
        actor = await session.get(JavActor, actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        # 优先返回规范目录头像（真实文件路径）
        # 注意: 模块演员模型(JavActor 等)没有 avatar_path 列，getattr 默认 "" → _Path("") 等价
        # Path(".")，其 exists() 为 True；若直接 FileResponse(".") 会抛
        # RuntimeError: File at path . is not a file → HTTP 500。必须校验绝对路径 + is_file()。
        avatar_path = getattr(actor, "avatar_path", "") or ""
        if avatar_path and _Path(avatar_path).is_absolute() and _Path(avatar_path).is_file():
            return FileResponse(str(avatar_path), media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})

        # 优先读取约定文件 DATA/avatars/jav/actor_{id}.jpg（按模块隔离）
        try:
            from app.config.manager import get_config_manager
            avatar_file = _Path(get_config_manager().computed.data_dir) / "avatars" / "jav" / f"actor_{actor_id}.jpg"
            if avatar_file.exists():
                return FileResponse(str(avatar_file), media_type="image/jpeg",
                                    headers={"Cache-Control": "public, max-age=86400"})
        except Exception:
            pass

        # 回退: avatar_url 为真实本地绝对路径时直接返回（gfriends 导入写入的正是此路径）
        avatar_url_field = getattr(actor, "avatar_url", None)
        if avatar_url_field:
            av = str(avatar_url_field).strip()
            if av.startswith(("http://", "https://")):
                # 远程 URL 需前端代理，本端点仅服务本地文件，回退占位图
                pass
            elif _Path(av).is_absolute() and _Path(av).exists():
                return FileResponse(av, media_type="image/jpeg",
                                    headers={"Cache-Control": "public, max-age=86400"})

        return _avatar_placeholder()
    finally:
        await session.close()


@router.get("/movies")
async def list_movies(
    skip: int = 0,
    limit: int = 20,
    keyword: Optional[str] = Query(None, description="搜索标题/番号"),
    actor: Optional[str] = Query(None, description="按演员名过滤"),
    status_filter: Optional[str] = Query(None, alias="status", description="过滤状态 pending/scraped"),
    # 2026-08-08 新增: 详情页跳转筛选参数（对齐通用 /api/v1/movies 端点）
    series: Optional[str] = Query(None, description="按系列精确过滤"),
    maker: Optional[str] = Query(None, description="按片商/制作商过滤（匹配 maker 或 studio）"),
    genre: Optional[str] = Query(None, description="按类别过滤（genre 字段包含）"),
    code_prefix: Optional[str] = Query(None, description="番号前缀精确过滤"),
    source_filter: Optional[str] = Query(None, alias="source", description="按刮削来源过滤（nfo_cache/javbus/javdb/local 等）"),
    is_chinese: Optional[int] = Query(None, description="1=仅中文"),
    is_uncensored: Optional[int] = Query(None, description="1=仅无码"),
    solo: Optional[int] = Query(None, description="1=仅单人作品（actor 字段恰好一个演员）"),
    info_state: Optional[str] = Query(None, description="complete=信息全 / incomplete=信息不全（NFO+封面+预览图）"),
    sort: Optional[str] = Query(None, description="排序字段: created_at, release_date, duration, rating, code。前缀-表示降序；code 为番号自然排序（ABC-001 < ABC-002 < ABC-010）"),
):
    """列出有码模块影片列表"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select, func, or_, case, Integer
        import re

        # 番号自然排序键：字母前缀 + 数字部分（ABC-001 < ABC-002 < ABC-010）
        def _code_sort_key(code: str) -> tuple:
            m = re.match(r"([A-Za-z]*)(\d*)", code or "")
            return (m.group(1).upper(), int(m.group(2)) if m.group(2) else 0)

        # 构建查询条件
        filters = []
        if keyword:
            kw = f"%{keyword}%"
            filters.append(or_(JavMovie.title.like(kw), JavMovie.code.like(kw)))
        if actor:
            filters.append(JavMovie.actor.like(f"%{actor}%"))
        if status_filter:
            filters.append(JavMovie.status == status_filter)
        if series:
            filters.append(JavMovie.series == series)
        if maker:
            filters.append(or_(JavMovie.maker == maker, JavMovie.studio == maker))
        if genre:
            filters.append(JavMovie.genre.contains(genre))
        if code_prefix:
            filters.append(JavMovie.code.startswith(code_prefix))
        if source_filter:
            filters.append(JavMovie.source == source_filter)
        if is_chinese:
            filters.append(JavMovie.is_chinese == 1)
        if is_uncensored:
            filters.append(JavMovie.is_uncensored == 1)
        if solo:
            # v3.1 单人筛选：actor 字段非空且不含分隔符（不靠 MovieActor 表，其恒为空）
            filters.append(JavMovie.actor.isnot(None))
            filters.append(JavMovie.actor != "")
            filters.append(~JavMovie.actor.contains(","))
            filters.append(~JavMovie.actor.contains("，"))
            filters.append(~JavMovie.actor.contains("、"))

        if info_state in ("complete", "incomplete"):
            # 信息全/不全筛选：需要文件系统检查 NFO，无法纯 SQL 完成。
            # 先按 DB 列预筛候选，再逐部判断 NFO 存在，最后手动分页。
            base = list(filters)
            if info_state == "complete":
                base.append(JavMovie.cover_url.isnot(None))
                base.append(JavMovie.sample_images.isnot(None))
                base.append(JavMovie.sample_images != "")
            stmt = select(JavMovie)
            if base:
                stmt = stmt.where(*base)
            all_rows = (await session.execute(stmt)).scalars().all()

            from app.utils.media_helpers import get_movie_local_dir

            def _is_complete(m) -> bool:
                has_cover = bool(m.cover_url or m.poster_url)
                has_sample = bool(m.sample_images and m.sample_images.strip()
                                  and m.sample_images.strip() not in ("[]", "null"))
                has_nfo = False
                if m.code:
                    try:
                        has_nfo = (get_movie_local_dir("jav", m.code) / "movie.nfo").exists()
                    except Exception:
                        has_nfo = False
                return has_cover and has_sample and has_nfo

            if info_state == "complete":
                matched = [m for m in all_rows if _is_complete(m)]
            else:
                matched = [m for m in all_rows if not _is_complete(m)]
            # info_state 分支为内存筛选，排序也走内存（番号自然序/发行日期）
            if sort == "code":
                matched.sort(key=lambda m: _code_sort_key(m.code))
            elif sort == "-code":
                matched.sort(key=lambda m: _code_sort_key(m.code), reverse=True)
            elif sort == "release_date":
                matched.sort(key=lambda m: (m.release_date or "", m.code))
            elif sort == "-release_date":
                matched.sort(key=lambda m: (m.release_date or "", m.code), reverse=True)
            total = len(matched)
            movies = matched[skip:skip + limit]
        else:
            total_stmt = select(func.count(JavMovie.id))
            if filters:
                total_stmt = total_stmt.where(*filters)
            total_result = await session.execute(total_stmt)
            total = total_result.scalar()

            stmt = select(JavMovie)
            if filters:
                stmt = stmt.where(*filters)
            # 动态排序（默认按入库时间倒序）
            sort_map = {
                "created_at": JavMovie.created_at,
                "release_date": JavMovie.release_date,
                "duration": JavMovie.duration,
                "rating": JavMovie.rating,
            }
            if sort in ("code", "-code"):
                dash = func.instr(JavMovie.code, "-")
                alpha = func.upper(case((dash > 1, func.substr(JavMovie.code, 1, dash - 1)), else_=""))
                num = func.cast(func.substr(JavMovie.code, func.max(dash + 1, 1)), Integer)
                if sort == "-code":
                    stmt = stmt.order_by(alpha.desc().nulls_last(), num.desc().nulls_last(),
                                         JavMovie.code.desc(), JavMovie.id.desc())
                else:
                    stmt = stmt.order_by(alpha.asc().nulls_last(), num.asc().nulls_last(),
                                         JavMovie.code.asc(), JavMovie.id.desc())
            elif sort:
                field = sort[1:] if sort.startswith("-") else sort
                col = sort_map.get(field)
                if col is not None:
                    if sort.startswith("-"):
                        stmt = stmt.order_by(col.desc().nulls_last(), JavMovie.id.desc())
                    else:
                        stmt = stmt.order_by(col.asc().nulls_last(), JavMovie.id.desc())
                else:
                    stmt = stmt.order_by(JavMovie.created_at.desc(), JavMovie.id.desc())
            else:
                stmt = stmt.order_by(JavMovie.created_at.desc(), JavMovie.id.desc())
            stmt = stmt.offset(skip).limit(limit)
            result = await session.execute(stmt)
            movies = result.scalars().all()

        # 统计待刮削数量
        pending_stmt = select(func.count(JavMovie.id)).where(JavMovie.status == "pending")
        pending_result = await session.execute(pending_stmt)
        pending_count = pending_result.scalar()

        return {
            "total": total,
            "pending_count": pending_count or 0,
            "items": [
                {"id": m.id, "code": m.code, "title": m.title,
                 "module_type": "jav",
                 "source_platform": m.source,
                 "series": m.series,
                 "cover_url": m.cover_url, "actor": _fill_amateur_actor(m),
                 "file_path": m.file_path, "status": m.status,
                 # 版本标识（列表页 badge 依赖）：中文/无码/4K/流出
                 "is_chinese": m.is_chinese, "is_uncensored": m.is_uncensored,
                 "is_4k": m.is_4k, "is_leak": m.is_leak}
                for m in movies
            ],
        }
    finally:
        await session.close()


def _parse_sample_images(raw: Optional[str]) -> list:
    """解析 sample_images JSON 字符串为列表"""
    if not raw:
        return []
    try:
        import json
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取有码影片详情"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select
        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 2026-08-08: 演员名字 → id 映射（详情页点演员应跳数字 id，而非按名字）
        actor_ids: dict = {}
        if movie.actor:
            from app.db.jav_models import JavActor
            names = [n.strip() for n in movie.actor.split(",") if n.strip()]
            if names:
                rows = (await session.execute(
                    select(JavActor.id, JavActor.name).where(JavActor.name.in_(names))
                )).all()
                actor_ids = {name: aid for aid, name in rows}

        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "module_type": "jav",
            "original_title": movie.original_title,
            "is_chinese": movie.is_chinese, "is_uncensored": movie.is_uncensored,
            "is_mosaic": movie.is_mosaic, "is_leak": movie.is_leak, "is_4k": movie.is_4k,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "thumb_url": movie.thumb_url, "sample_images": _parse_sample_images(movie.sample_images),
            "actor": _fill_amateur_actor(movie), "actor_ids": actor_ids, "studio": movie.studio,
            "series": movie.series, "label": movie.label,
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "genre": movie.genre, "tag": movie.tag,
            "source": movie.source, "source_url": movie.source_url,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "fingerprint": movie.fingerprint,
            "play_count": movie.play_count, "last_played_at": str(movie.last_played_at) if movie.last_played_at else None,
            "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
            "updated_at": str(movie.updated_at),
        }
    finally:
        await session.close()


@router.patch("/movies/{movie_id}")
async def update_jav_movie(movie_id: int, body: dict):
    """编辑影片数据

    前端详情页「编辑影片数据」保存走本端点。
    与通用 PATCH /api/v1/movies/{id} 不同，本端点直接写 jav 模块的
    文本字段（movie.actor / movie.studio / movie.series），因为 jav 详情
    链路（get_movie / related / actor_alias 作品数统计）读取的是这些文本列；
    同时同步 MovieActor 关联表、查建 Studio/Series 外键，并重算受影响演员
    的 movie_count，保证编辑后各处数据一致。
    """
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select
    from app.db.jav_models import JavMovie, JavActor, MovieActor, Studio, Series

    db = get_jav_db()
    session = await db.get_session()
    try:
        movie = await session.get(JavMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 番号唯一校验
        if "code" in body and body["code"] is not None:
            new_code = str(body["code"]).strip()
            if not new_code:
                raise HTTPException(status_code=400, detail="番号不能为空")
            dup = await session.scalar(
                select(JavMovie.id).where(JavMovie.code == new_code, JavMovie.id != movie_id)
            )
            if dup:
                raise HTTPException(status_code=409, detail=f"番号 {new_code} 已被其他影片占用")
            movie.code = new_code

        # 文本字段
        for field in ("title", "original_title", "release_date", "director",
                      "maker", "studio", "series", "plot", "file_path"):
            if field in body:
                val = body[field]
                movie.__setattr__(field, (str(val).strip() if val not in (None, "") else None))

        # 数字字段
        if "duration" in body and body["duration"] not in (None, ""):
            try:
                movie.duration = int(body["duration"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="时长必须是整数")
        if "rating" in body and body["rating"] not in (None, ""):
            try:
                r = float(body["rating"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="评分必须是数字")
            movie.rating = max(0.0, min(10.0, r))

        # genre：逗号分隔字符串（jav 详情/相关端点按逗号切分）
        if "genre" in body:
            raw = body["genre"]
            if raw in (None, ""):
                movie.genre = None
            else:
                parts = [str(x).strip() for x in raw] if isinstance(raw, list) \
                    else [p.strip() for p in str(raw).split(",")]
                movie.genre = ", ".join(p for p in parts if p) if any(parts) else None

        # actors：写文本字段 + 同步 MovieActor 关联表
        old_names = {n.strip() for n in (movie.actor or "").split(",") if n.strip()}
        new_names: set = set()
        if "actors" in body:
            raw = body["actors"]
            if raw in (None, ""):
                names = []
            else:
                names = [str(x).strip() for x in raw] if isinstance(raw, list) \
                    else [p.strip() for p in str(raw).split(",")]
            # 防污染（2026-08-26）：拒绝长度 ≤2 的短名，防止 "AI"/"あさみ"/"しずく" 等
            # 短名被当作演员后，在 LIKE 查询中会误匹配大量无关影片。
            names = [n for n in names if n and len(n) >= 3]
            new_names = set(names)
            movie.actor = ", ".join(names) if names else None

            await session.execute(sa_delete(MovieActor).where(MovieActor.movie_id == movie_id))
            for nm in names:
                actor = await session.scalar(select(JavActor).where(JavActor.name == nm))
                if not actor:
                    actor = JavActor(name=nm, movie_count=0)
                    session.add(actor)
                    await session.flush()
                session.add(MovieActor(movie_id=movie_id, actor_id=actor.id))

        # studio / series：查建外键（文本字段已在上方写入）
        for fk_field, Model in (("studio", Studio), ("series", Series)):
            if fk_field in body:
                name_val = body[fk_field]
                name = str(name_val).strip() if name_val not in (None, "") else None
                if name:
                    obj = await session.scalar(select(Model).where(Model.name == name))
                    if not obj:
                        obj = Model(name=name, movie_count=0)
                        session.add(obj)
                        await session.flush()
                    movie.__setattr__(f"{fk_field}_id", obj.id)
                else:
                    movie.__setattr__(f"{fk_field}_id", None)

        await session.commit()

        # 重算受影响演员的作品数（LIKE 文本字段计数，编辑后保持统计一致）
        affected = new_names | old_names
        if affected:
            from app.utils.actor_alias import count_actor_movies
            actors = (await session.execute(
                select(JavActor).where(JavActor.name.in_(list(affected)))
            )).scalars().all()
            for actor in actors:
                actor.movie_count = await count_actor_movies(session, JavMovie, actor)
            await session.commit()

        # 可选 NFO 回写（失败不阻断保存）
        if body.get("sync_nfo", True):
            try:
                from app.output.nfo import NFOGenerator
                mv = await session.get(JavMovie, movie_id)
                out_dir = str(mv.output_dir) if mv.output_dir else (str(mv.file_path.parent) if mv.file_path else "")
                if out_dir:
                    gen = NFOGenerator(output_dir=out_dir)
                    gen.generate_from_movie(movie=mv, movie_dir=None, kodi_compatible=True,
                                            actor_names=sorted(new_names) if new_names else None)
            except Exception as e:
                logger.warning("jav 影片 %s NFO 回写失败: %s", movie_id, e)

        await session.refresh(movie)
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "module_type": "jav",
            "original_title": movie.original_title,
            "actor": _fill_amateur_actor(movie), "studio": movie.studio,
            "series": movie.series, "maker": movie.maker,
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "genre": movie.genre,
            "plot": movie.plot, "file_path": movie.file_path,
            "updated_at": str(movie.updated_at),
        }
    finally:
        await session.close()


# ========== 相关推荐与演员端点（通用详情页使用） ==========


@router.get("/movies/{movie_id}/related")
async def get_jav_related_movies(movie_id: int):
    """获取JAV影片的相关推荐（同演员/同系列/同类别）"""
    from sqlalchemy import select, or_, and_
    from app.db.jav_models import JavMovie

    db = get_jav_db()
    session = await db.get_session()
    try:
        movie = await session.get(JavMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        related_ids = {movie_id}
        actor_movies = []
        series_movies = []
        genre_movies = []
        limit = 12

        # 同演员
        if movie.actor:
            actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
            if actor_names:
                filters = [JavMovie.actor.contains(name) for name in actor_names]
                stmt = select(JavMovie).where(
                    and_(or_(*filters), JavMovie.id != movie_id)
                ).order_by(JavMovie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        actor_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "jav", "cover_url": m.cover_url,
                        })

        # 同系列
        if movie.series:
            stmt = select(JavMovie).where(
                and_(JavMovie.series == movie.series, JavMovie.id != movie_id)
            ).order_by(JavMovie.id.desc()).limit(limit)
            result = await session.execute(stmt)
            for m in result.scalars().all():
                if m.id not in related_ids:
                    related_ids.add(m.id)
                    series_movies.append({
                        "id": m.id, "code": m.code, "title": m.title,
                        "module_type": "jav", "cover_url": m.cover_url,
                    })

        # 同类别
        if movie.genre:
            genre_parts = [g.strip() for g in movie.genre.split(",") if g.strip()]
            if genre_parts:
                genre_filters = [JavMovie.genre.contains(gp) for gp in genre_parts[:5]]
                stmt = select(JavMovie).where(
                    and_(or_(*genre_filters), JavMovie.id != movie_id)
                ).order_by(JavMovie.id.desc()).limit(limit)
                result = await session.execute(stmt)
                for m in result.scalars().all():
                    if m.id not in related_ids:
                        related_ids.add(m.id)
                        genre_movies.append({
                            "id": m.id, "code": m.code, "title": m.title,
                            "module_type": "jav", "cover_url": m.cover_url,
                        })

        return {
            "actor_movies": actor_movies[:limit],
            "series_movies": series_movies[:limit],
            "genre_movies": genre_movies[:limit],
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/actors")
async def get_jav_movie_actors(movie_id: int):
    """获取JAV影片关联的演员列表"""
    from app.db.jav_models import JavMovie, JavActor

    db = get_jav_db()
    session = await db.get_session()
    try:
        movie = await session.get(JavMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        if not movie.actor:
            return {"items": []}
        actor_names = [a.strip() for a in movie.actor.split(",") if a.strip()]
        items = []
        for name in actor_names:
            stmt = select(JavActor).where(JavActor.name == name)
            result = await session.execute(stmt)
            actor = result.scalar_one_or_none()
            if actor:
                items.append({"id": actor.id, "name": actor.name, "avatar_url": actor.avatar_url})
            else:
                items.append({"id": name, "name": name, "avatar_url": None})
        return {"items": items}
    finally:
        await session.close()


# ========== 刮削端点 ==========


@router.post("/movies/{movie_id}/scrape")
async def scrape_jav_movie(movie_id: int):
    """刮削指定有码影片的元数据

    使用 JavDB/JavBus 等爬虫从网络获取元数据，
    然后写入 JAV 模块 DB（JavMovie + JavActor）。
    """
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie, JavActor
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 使用 ScraperEngine 刮削
        from app.scraper.engine import get_scraper_engine
        engine = get_scraper_engine()
        scrape_result = await engine.scrape_number(movie.code)

        if not scrape_result or not scrape_result.title:
            return {"status": "error", "message": f"刮削失败: 未找到 {movie.code} 的数据"}

        # 映射 ScrapeResult → JavMovie 字段
        movie.title = scrape_result.title
        if scrape_result.original_title:
            movie.original_title = scrape_result.original_title

        # ── 资源下载：将远程封面/预览图/头像下载到本地 ──
        from app.utils.media_helpers import (
            ensure_movie_media_local,
            ensure_actor_avatar_local,
        )

        # 下载封面/背景图/缩略图到 L:/data/movies/jav/{code}/
        local_media = await ensure_movie_media_local(
            module_name="jav", code=movie.code,
            cover_url=scrape_result.cover_url,
            fanart_url=scrape_result.poster_url,
            thumb_url=scrape_result.thumb_url,
        )
        # 封面统一裁剪为竖版 2:3 人物海报（横向大图/过窄图就地主裁）
        try:
            from app.utils.media_helpers import crop_cover_to_portrait, get_movie_cover_path
            crop_cover_to_portrait(get_movie_cover_path("jav", movie.code))
        except Exception:
            pass
        # 存本地路径到数据库
        if local_media.get("cover"):
            movie.cover_url = local_media["cover"]
        if local_media.get("fanart"):
            movie.poster_url = local_media["fanart"]
        if local_media.get("thumb"):
            movie.thumb_url = local_media["thumb"]
        if scrape_result.poster_url:
            movie.poster_url = scrape_result.poster_url
        if scrape_result.release_date:
            movie.release_date = str(scrape_result.release_date)
        if scrape_result.duration:
            movie.duration = scrape_result.duration
        if scrape_result.rating:
            movie.rating = scrape_result.rating
        if scrape_result.plot:
            movie.plot = scrape_result.plot
        if scrape_result.studio:
            movie.studio = scrape_result.studio
        if scrape_result.series:
            movie.series = scrape_result.series
        if scrape_result.label:
            movie.label = scrape_result.label
        if scrape_result.is_mosaic is not None:
            movie.is_mosaic = scrape_result.is_mosaic
        if scrape_result.is_uncensored is not None:
            movie.is_uncensored = scrape_result.is_uncensored
        if scrape_result.is_chinese is not None:
            movie.is_chinese = scrape_result.is_chinese

        # 兜底：爬虫未提取出 is_chinese/is_uncensored（如 JavDB 不写 is_chinese）时，
        # 从视频文件名/目录名后缀（[中字] / -C / -UC / -无码 等）补全。仅做加法，不覆盖已有 True。
        try:
            from app.tasks.base_scanner import detect_version_flags
            from pathlib import Path
            _name_candidates = []
            if getattr(movie, "file_path", None):
                _fp = str(movie.file_path)
                _name_candidates.append(_fp)
                _parent = Path(_fp).parent.name
                if _parent:
                    _name_candidates.append(_parent)
            if getattr(movie, "code", None):
                _name_candidates.append(str(movie.code))
            for _cand in _name_candidates:
                try:
                    _flags = detect_version_flags(_cand)
                except Exception:
                    continue
                if not movie.is_chinese and _flags.get("is_chinese"):
                    movie.is_chinese = True
                if not movie.is_uncensored and _flags.get("is_uncensored"):
                    movie.is_uncensored = True
                if not getattr(movie, "is_leak", None) and _flags.get("is_leak"):
                    movie.is_leak = True
                if not getattr(movie, "is_4k", None) and _flags.get("is_4k"):
                    movie.is_4k = True
        except Exception:
            pass
        if scrape_result.genres:
            movie.genre = ",".join(scrape_result.genres)
        if scrape_result.tags:
            movie.tag = ",".join(scrape_result.tags)
        if scrape_result.sample_images:
            import json
            movie.sample_images = json.dumps(scrape_result.sample_images, ensure_ascii=False)

        # 演员
        if scrape_result.actors:
            seen_names: set[str] = set()
            actor_names: list[str] = []
            for a in scrape_result.actors:
                name = a.name.strip()
                if name and name not in seen_names:
                    seen_names.add(name)
                    actor_names.append(name)
            movie.actor = ",".join(actor_names)

            for actor_info in scrape_result.actors:
                existing = await session.execute(
                    select(JavActor).where(JavActor.name == actor_info.name)
                )
                db_actor = existing.scalar_one_or_none()
                if db_actor:
                    db_actor.movie_count += 1
                    if not db_actor.avatar_url and actor_info.avatar_url:
                        # 下载头像到 L:/data/avatars/{name}.jpg
                        local_avatar = await ensure_actor_avatar_local(
                            actor_info.name, actor_info.avatar_url
                        )
                        db_actor.avatar_url = local_avatar or actor_info.avatar_url
                    if not db_actor.source_site:
                        db_actor.source_site = scrape_result.source
                else:
                    # 下载头像到 L:/data/avatars/{name}.jpg
                    local_avatar = await ensure_actor_avatar_local(
                        actor_info.name, actor_info.avatar_url
                    )
                    session.add(JavActor(
                        name=actor_info.name,
                        avatar_url=local_avatar or actor_info.avatar_url,
                        source="scraper",
                        source_site=scrape_result.source,
                        movie_count=1,
                    ))

        # 来源信息
        movie.source = scrape_result.source
        if scrape_result.source_url:
            movie.source_url = scrape_result.source_url
        movie.status = "scraped"
        await session.commit()

        return {
            "status": "ok",
            "message": f"刮削成功: {scrape_result.title}",
            "source": scrape_result.source,
            "actors": [a.name for a in scrape_result.actors] if scrape_result.actors else [],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JAV 刮削失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/force-scrape")
async def force_scrape_jav_movie(data: dict):
    """特殊刮削：按番号 + 指定 JAVDB/JAVBUS 链接强制重刮

    解决同番号多个条目导致自动刮削匹配到错误信息的问题：
    1. 用户提供正确的详情页链接（或指定站点），后端直接抓取该链接，
       不经过搜索，避免匹配到错误条目；
    2. 刮削前先清理影片文件夹下已刮削的旧数据（NFO/图片），再重新刮削。
    """
    import shutil
    from pathlib import Path as _Path
    from sqlalchemy import select
    from app.db.jav_models import JavMovie, JavActor
    from app.utils.media_helpers import (
        get_movie_local_dir,
        ensure_movie_media_local,
        ensure_actor_avatar_local,
    )

    code = str(data.get("code") or "").strip().upper()
    url = str(data.get("url") or "").strip()
    site = str(data.get("site") or "").strip().lower()
    movie_id = data.get("movie_id")

    if not code:
        raise HTTPException(status_code=400, detail="番号不能为空")

    # 站点判定：URL 域名优先，其次 site 参数
    low_url = url.lower()
    if "javdb" in low_url:
        site = "javdb"
    elif "javbus" in low_url:
        site = "javbus"
    if site not in ("javdb", "javbus"):
        raise HTTPException(status_code=400, detail="请提供 JAVDB 或 JAVBUS 的详情链接，或指定站点")

    db = get_jav_db()
    session = await db.get_session()
    try:
        # 定位影片
        if movie_id:
            movie = await session.get(JavMovie, movie_id)
        else:
            movie = await session.scalar(select(JavMovie).where(JavMovie.code == code))
        if not movie:
            raise HTTPException(status_code=404, detail=f"库中未找到番号 {code} 的影片，请确认番号正确")

        # ── 1. 清理已刮削到文件夹下的旧数据 ──
        removed = []
        media_dir = get_movie_local_dir("jav", movie.code)
        try:
            if media_dir.exists():
                shutil.rmtree(media_dir, ignore_errors=True)
                removed.append(str(media_dir))
        except Exception as e:
            logger.warning(f"清理媒体目录失败 {media_dir}: {e}")
        if movie.file_path:
            video_dir = _Path(movie.file_path).parent
            try:
                for nfo in video_dir.glob("*.nfo"):
                    nfo.unlink(missing_ok=True)
                    removed.append(str(nfo))
            except Exception as e:
                logger.warning(f"清理 NFO 失败 {video_dir}: {e}")
        # 清空库中旧媒体引用，避免残留 404
        movie.cover_url = None
        movie.poster_url = None
        movie.thumb_url = None
        movie.sample_images = None
        await session.commit()

        # ── 2. 刮削 ──
        if url:
            # 直接按用户提供的详情链接刮削（不搜索，避免匹配错条目）
            if site == "javdb":
                from app.crawlers.javdb import JavDBCrawler
                crawler = JavDBCrawler()
            else:
                from app.crawlers.javbus import JavBusCrawler
                crawler = JavBusCrawler()
            scrape_result = await crawler.scrape_url(url, code)
        else:
            # 无链接：指定站点按番号搜索刮削
            from app.scraper.engine import get_scraper_engine
            engine = get_scraper_engine()
            scrape_result = await engine.scrape_number(code, sources=[site], module="jav")

        if not scrape_result or not scrape_result.title:
            return {
                "status": "error",
                "message": f"刮削失败: {site} 未返回 {code} 的数据（请检查链接是否正确、站点是否可达）",
                "removed": removed,
            }

        # ── 3. 写库（字段映射与 scrape_jav_movie 一致） ──
        old_actor_names = {n.strip() for n in (movie.actor or "").split(",") if n.strip()}
        movie.title = scrape_result.title
        if scrape_result.original_title:
            movie.original_title = scrape_result.original_title
        if scrape_result.release_date:
            movie.release_date = str(scrape_result.release_date)
        if scrape_result.duration:
            movie.duration = scrape_result.duration
        if scrape_result.rating:
            movie.rating = scrape_result.rating
        if scrape_result.plot:
            movie.plot = scrape_result.plot
        if scrape_result.studio:
            movie.studio = scrape_result.studio
        if scrape_result.series:
            movie.series = scrape_result.series
        if scrape_result.label:
            movie.label = scrape_result.label
        if scrape_result.is_mosaic is not None:
            movie.is_mosaic = scrape_result.is_mosaic
        if scrape_result.is_uncensored is not None:
            movie.is_uncensored = scrape_result.is_uncensored
        if scrape_result.is_chinese is not None:
            movie.is_chinese = scrape_result.is_chinese
        if scrape_result.genres:
            movie.genre = ",".join(scrape_result.genres)
        if scrape_result.tags:
            movie.tag = ",".join(scrape_result.tags)
        if scrape_result.sample_images:
            import json
            movie.sample_images = json.dumps(scrape_result.sample_images, ensure_ascii=False)

        # 媒体下载到标准落盘目录 {data}/movies/jav/{code}/
        local_media = await ensure_movie_media_local(
            module_name="jav", code=movie.code,
            cover_url=scrape_result.cover_url,
            fanart_url=scrape_result.poster_url,
            thumb_url=scrape_result.thumb_url,
        )
        if local_media.get("cover"):
            movie.cover_url = local_media["cover"]
        if local_media.get("fanart"):
            movie.poster_url = local_media["fanart"]
        if local_media.get("thumb"):
            movie.thumb_url = local_media["thumb"]

        # 演员：写文本字段 + 复用/创建 JavActor + 重算作品数
        new_actor_names: set = set()
        if scrape_result.actors:
            actor_names = [a.name for a in scrape_result.actors]
            movie.actor = ",".join(actor_names)
            new_actor_names = {n for n in actor_names if n}
            for actor_info in scrape_result.actors:
                if not actor_info.name:
                    continue
                existing = await session.scalar(select(JavActor).where(JavActor.name == actor_info.name))
                if existing:
                    if not existing.avatar_url and actor_info.avatar_url:
                        local_avatar = await ensure_actor_avatar_local(
                            actor_info.name, actor_info.avatar_url
                        )
                        existing.avatar_url = local_avatar or actor_info.avatar_url
                    if not existing.source_site:
                        existing.source_site = scrape_result.source
                else:
                    local_avatar = await ensure_actor_avatar_local(
                        actor_info.name, actor_info.avatar_url
                    )
                    session.add(JavActor(
                        name=actor_info.name,
                        avatar_url=local_avatar or actor_info.avatar_url,
                        source="scraper",
                        source_site=scrape_result.source,
                        movie_count=0,
                    ))
        else:
            movie.actor = None

        # 来源信息
        movie.source = scrape_result.source
        if scrape_result.source_url:
            movie.source_url = scrape_result.source_url
        movie.status = "scraped"
        await session.commit()

        # 重算受影响演员作品数（重刮可能改变演员列表，不能累加）
        affected = new_actor_names | old_actor_names
        if affected:
            from app.utils.actor_alias import count_actor_movies
            actors = (await session.execute(
                select(JavActor).where(JavActor.name.in_(list(affected)))
            )).scalars().all()
            for actor in actors:
                actor.movie_count = await count_actor_movies(session, JavMovie, actor)
            await session.commit()

        # ── 4. 生成 NFO（回写到视频所在目录，失败不阻断） ──
        nfo_path = None
        try:
            from app.output.nfo import NFOGenerator
            out_dir = str(movie.output_dir) if movie.output_dir else (str(_Path(movie.file_path).parent) if movie.file_path else "")
            if out_dir:
                gen = NFOGenerator(output_dir=out_dir)
                nfo_path = gen.generate_from_movie(
                    movie=movie, movie_dir=None, kodi_compatible=True,
                    actor_names=sorted(new_actor_names) if new_actor_names else None,
                )
        except Exception as e:
            logger.warning("JAV 特殊刮削 NFO 生成失败: %s", e)

        return {
            "status": "ok",
            "message": f"刮削成功: {scrape_result.title}",
            "source": scrape_result.source,
            "actors": sorted(new_actor_names),
            "removed": removed,
            "nfo": nfo_path,
        }
    finally:
        await session.close()


@router.post("/movies/scrape-all-pending")
async def scrape_all_pending_jav(background_tasks: BackgroundTasks):
    """后台批量刮削所有 status=pending 的 JAV 影片"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.status == "pending").order_by(JavMovie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待刮削的影片", "total": 0}

    async def _run():
        from app.db.jav_models import JavMovie, JavActor
        from app.scraper.engine import get_scraper_engine
        from sqlalchemy import select

        engine = get_scraper_engine()
        success = 0
        failed = 0
        for m in pending:
            try:
                scrape_result = await engine.scrape_number(m.code)
                if scrape_result and scrape_result.title:
                    s = await db.get_session()
                    try:
                        st = select(JavMovie).where(JavMovie.id == m.id)
                        r = await s.execute(st)
                        mv = r.scalar_one_or_none()
                        if mv:
                            mv.title = scrape_result.title
                            if scrape_result.original_title:
                                mv.original_title = scrape_result.original_title
                            if scrape_result.cover_url:
                                mv.cover_url = scrape_result.cover_url
                            if scrape_result.poster_url:
                                mv.poster_url = scrape_result.poster_url
                            if scrape_result.release_date:
                                mv.release_date = str(scrape_result.release_date)
                            if scrape_result.duration:
                                mv.duration = scrape_result.duration
                            if scrape_result.rating:
                                mv.rating = scrape_result.rating
                            if scrape_result.plot:
                                mv.plot = scrape_result.plot
                            if scrape_result.studio:
                                mv.studio = scrape_result.studio
                            if scrape_result.series:
                                mv.series = scrape_result.series
                            if scrape_result.label:
                                mv.label = scrape_result.label
                            if scrape_result.genres:
                                mv.genre = ",".join(scrape_result.genres)
                            if scrape_result.tags:
                                mv.tag = ",".join(scrape_result.tags)
                            if scrape_result.actors:
                                mv.actor = ",".join(a.name for a in scrape_result.actors)
                                for ai in scrape_result.actors:
                                    ex = await s.execute(select(JavActor).where(JavActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if not a:
                                        s.add(JavActor(
                                            name=ai.name,
                                            avatar_url=ai.avatar_url,
                                            source="scraper",
                                            source_site=scrape_result.source,
                                            movie_count=1,
                                        ))
                            mv.source = scrape_result.source
                            mv.status = "scraped"
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"JAV 刮削失败 {m.code}: {e}")
                failed += 1
        logger.info(f"JAV 批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "total": len(pending),
        "message": f"JAV 批量刮削已启动，共 {len(pending)} 部待刮削影片",
    }


# ========== NFO 导入端点 ==========


@router.post("/movies/import-nfo")
async def import_jav_nfo(
    background_tasks: BackgroundTasks,
    media_dir: Optional[str] = Query(None, description="指定扫描目录，不传则使用配置中的所有 JAV 媒体目录"),
    recursive: bool = Query(True, description="是否递归扫描子目录"),
):
    """从 JAV 媒体目录扫描 NFO 文件并导入到 JavMovie 表

    扫描视频文件同目录下的 *.nfo 文件，解析元数据（标题、封面、演员、简介等），
    写入 JAV 模块数据库（JavMovie + JavActor）。
    已有 scraped 状态的影片不会覆盖。
    """
    from app.config.manager import get_config

    config = get_config()

    # 确定扫描目录
    if media_dir:
        dirs = [media_dir]
    else:
        dirs = config.modules.jav.media_dirs

    if not dirs:
        return {"status": "error", "message": "未配置 JAV 媒体目录，请先在配置中设置"}

    # 收集所有 NFO 文件
    import os
    from pathlib import Path

    nfo_files: list[str] = []
    for d in dirs:
        d_path = Path(d)
        if not d_path.exists():
            logger.warning(f"媒体目录不存在: {d}")
            continue

        if recursive:
            walk_gen = os.walk(d_path)
        else:
            walk_gen = [(str(d_path), [], [f.name for f in d_path.iterdir() if f.is_file()])]

        for root, _, files in walk_gen:
            for f in files:
                if f.lower().endswith(".nfo"):
                    nfo_path = os.path.join(root, f)
                    nfo_files.append(nfo_path)

    if not nfo_files:
        return {"status": "ok", "message": f"在 {len(dirs)} 个目录中未找到任何 NFO 文件", "total": 0}

    async def _run_import():
        """后台执行 NFO 导入"""
        from app.db.jav_models import JavMovie, JavActor
        from app.importer.nfo_parser import NFOParser
        from sqlalchemy import select

        parser = NFOParser()
        imported = 0
        skipped = 0
        errors = 0

        for nfo_path in nfo_files:
            try:
                # 解析 NFO
                imported_movie = parser.parse(nfo_path)
                if not imported_movie or not imported_movie.code:
                    skipped += 1
                    continue

                code = imported_movie.code.upper()
                s = await db.get_session()
                try:
                    # 检查是否已存在
                    st = select(JavMovie).where(JavMovie.code == code)
                    r = await s.execute(st)
                    mv = r.scalar_one_or_none()

                    if mv:
                        # 已存在的影片只补全缺失字段
                        updates = []
                        if mv.title is None and imported_movie.title:
                            mv.title = imported_movie.title
                            updates.append("title")
                        if mv.original_title is None and imported_movie.original_title:
                            mv.original_title = imported_movie.original_title
                            updates.append("original_title")
                        if mv.plot is None and imported_movie.plot:
                            mv.plot = imported_movie.plot
                            updates.append("plot")
                        if mv.release_date is None and imported_movie.release_date:
                            mv.release_date = imported_movie.release_date.strftime("%Y-%m-%d")
                            updates.append("release_date")
                        if mv.duration is None and imported_movie.duration:
                            mv.duration = imported_movie.duration
                            updates.append("duration")
                        if mv.studio is None and imported_movie.studio:
                            mv.studio = imported_movie.studio
                            updates.append("studio")
                        if mv.series is None and imported_movie.series:
                            mv.series = imported_movie.series
                            updates.append("series")
                        if imported_movie.genres and mv.genre is None:
                            mv.genre = ",".join(imported_movie.genres)
                            updates.append("genre")
                        if imported_movie.actors and mv.actor is None:
                            mv.actor = ",".join(imported_movie.actors)
                            updates.append("actor")
                        if imported_movie.is_chinese is not None and mv.is_chinese is None:
                            mv.is_chinese = imported_movie.is_chinese
                        if imported_movie.is_uncensored is not None and mv.is_uncensored is None:
                            mv.is_uncensored = imported_movie.is_uncensored
                        if mv.source is None or mv.source == "folder":
                            mv.source = "nfo"

                        # 封面图片：检查 NFO 同目录下的同名图片
                        nfo_dir = Path(nfo_path).parent
                        for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg"]:
                            img_path = nfo_dir / img_name
                            if img_path.exists() and mv.cover_url is None:
                                mv.cover_url = str(img_path)
                                updates.append("cover_url")
                                break

                        if updates:
                            await s.commit()
                            imported += 1
                        else:
                            skipped += 1
                    else:
                        # 新建影片
                        cover_url = None
                        nfo_dir = Path(nfo_path).parent
                        for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg"]:
                            img_path = nfo_dir / img_name
                            if img_path.exists():
                                cover_url = str(img_path)
                                break

                        new_movie = JavMovie(
                            code=code,
                            title=imported_movie.title or code,
                            original_title=imported_movie.original_title,
                            plot=imported_movie.plot,
                            release_date=imported_movie.release_date.strftime("%Y-%m-%d") if imported_movie.release_date else None,
                            duration=imported_movie.duration,
                            studio=imported_movie.studio,
                            series=imported_movie.series,
                            genre=",".join(imported_movie.genres) if imported_movie.genres else None,
                            actor=",".join(imported_movie.actors) if imported_movie.actors else None,
                            cover_url=cover_url,
                            is_chinese=imported_movie.is_chinese if imported_movie.is_chinese else False,
                            is_uncensored=imported_movie.is_uncensored if imported_movie.is_uncensored else False,
                            is_leak=imported_movie.is_leak if imported_movie.is_leak else False,
                            is_4k=imported_movie.is_4k if imported_movie.is_4k else False,
                            source="nfo",
                            status="pending",
                        )
                        s.add(new_movie)

                        # 演员同步
                        if imported_movie.actors:
                            for actor_name in imported_movie.actors:
                                ex = await s.execute(select(JavActor).where(JavActor.name == actor_name))
                                if not ex.scalar_one_or_none():
                                    s.add(JavActor(name=actor_name, source="nfo"))

                        await s.commit()
                        imported += 1

                finally:
                    await s.close()

            except Exception as e:
                logger.debug(f"NFO 导入失败 [{nfo_path}]: {e}")
                errors += 1

        logger.info(f"JAV NFO 导入完成: 导入/更新 {imported}, 跳过 {skipped}, 错误 {errors}")

    background_tasks.add_task(_run_import)

    return {
        "status": "started",
        "total": len(nfo_files),
        "message": f"NFO 导入已启动，共发现 {len(nfo_files)} 个 NFO 文件",
    }


# ========== 封面/预览图文件代理 ==========

import os as _os
from pathlib import Path as _Path
from fastapi import Request as _Request


@router.get("/movies/{movie_id}/cover/file")
async def get_jav_cover_file(movie_id: int, decrypt: int = Query(0, description="1=返回前就地 XOR 解密（预览乱码封面用）")):
    """获取 JAV 模块影片封面图片文件

    纯本地查找，绝不连接外网。
    返回优先级：
    1. {data_base}/movies/jav/{code}/poster.jpg（规范目录下本地文件，刮削时已下载）
    2. DB 中 cover_url/poster_url/thumb_url 的本地路径
    3. 视频所在目录下的 poster.jpg/cover.jpg 等
    4. 内置 SVG 占位图

    decrypt=1 时对返回文件就地 XOR 解密（JavDB CDN 混淆），
    用于「封面问题修复」页预览乱码封面的修复效果。
    """
    from fastapi.responses import FileResponse, Response
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )

    def _resp(path, media_type, cache=True):
        """返回本地文件；decrypt=1 时先读入内存做 XOR 解密再返回"""
        if decrypt:
            try:
                from app.utils.media_helpers import maybe_decrypt_javdb_image
                data = maybe_decrypt_javdb_image(_Path(path).read_bytes())
                return Response(
                    content=data,
                    media_type="image/jpeg",
                    headers={"Cache-Control": "no-cache"},
                )
            except Exception:
                pass
        return FileResponse(
            str(path),
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"} if cache else {"Cache-Control": "no-cache"},
        )

    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 1) 规范目录：{data_base}/movies/jav/{code}/poster.jpg（最快命中）
        if movie.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path("jav", movie.code)
                if fast_file_exists(str(p)):
                    return _resp(p, _image_media_type(str(p)))

        # 2) DB 中 cover_url/poster_url/thumb_url 的本地路径
        for attr in ("cover_url", "poster_url", "thumb_url"):
            url = getattr(movie, attr, None)
            if not url:
                continue
            if not url.startswith(("http://", "https://", "/")):
                if fast_file_exists(url):
                    return _resp(url, _image_media_type(url))

        # 2.5) DB 中 cover_url/poster_url/thumb_url 是远程 URL 时，尝试下载到规范目录
        if movie.code:
            # 从 cover_url 提取域名作为 referer（防盗链绕过）
            cover_url_str = movie.cover_url or movie.poster_url or movie.thumb_url or ""
            ref_domain = ""
            if cover_url_str.startswith(("http://", "https://")):
                try:
                    from urllib.parse import urlparse
                    ref_domain = f"{urlparse(cover_url_str).scheme}://{urlparse(cover_url_str).netloc}/"
                except Exception:
                    pass
            for attr in ("cover_url", "poster_url", "thumb_url"):
                url = getattr(movie, attr, None)
                if url and url.startswith(("http://", "https://")):
                    # 确定目标文件名
                    target = get_movie_cover_path("jav", movie.code)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                            resp = await asyncio.wait_for(
                                client.get(url, headers={"Referer": ref_domain} if ref_domain else None),
                                timeout=15.0,
                            )
                            if resp.status_code == 200 and len(resp.content) > 500:
                                from app.utils.media_helpers import maybe_decrypt_javdb_image
                                content = maybe_decrypt_javdb_image(resp.content)
                                with open(target, "wb") as f:
                                    f.write(content)
                                # 同时尝试下载 fanart 和 thumb
                                if attr == "cover_url" and movie.poster_url and movie.poster_url.startswith(("http://", "https://")):
                                    try:
                                        fanart_target = get_movie_fanart_path("jav", movie.code)
                                        fresp = await asyncio.wait_for(
                                            client.get(movie.poster_url, headers={"Referer": ref_domain} if ref_domain else None),
                                            timeout=10.0,
                                        )
                                        if fresp.status_code == 200 and len(fresp.content) > 500:
                                            fanart_target.parent.mkdir(parents=True, exist_ok=True)
                                            with open(fanart_target, "wb") as f:
                                                f.write(maybe_decrypt_javdb_image(fresp.content))
                                    except Exception:
                                        pass
                                if fast_file_exists(str(target)):
                                    return _resp(target, _image_media_type(str(target)))
                    except Exception:
                        pass
                    break  # 只尝试第一个有效的远程 URL

        # 3) 视频所在目录下的 poster.jpg/cover.jpg/fanart.jpg/thumb.jpg
        if movie.file_path:
            try:
                video_dir = _Path(movie.file_path).parent
                for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg", "thumb.jpg"]:
                    img_path = video_dir / img_name
                    if await asyncio.wait_for(
                        asyncio.to_thread(lambda p=img_path: p.exists() and p.is_file()),
                        timeout=3.0,
                    ):
                        return _resp(img_path, _image_media_type(img_name))
            except asyncio.TimeoutError:
                logger.debug(f"JAV封面: 扫描视频目录超时 [movie_id={movie_id}]")

        # 4) 全部找不到：返回内置 SVG 占位图（不连外网）
        from fastapi.responses import HTMLResponse
        _placeholder = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360" '
            'viewBox="0 0 240 360"><rect fill="#f0f0f0" width="240" height="360"/>'
            '<text x="120" y="180" text-anchor="middle" fill="#bbb" '
            'font-size="14">暂无封面</text></svg>'
        )
        return HTMLResponse(content=_placeholder, media_type="image/svg+xml",
                            headers={"Cache-Control": "no-cache"})
    finally:
        await session.close()


def _image_media_type(path: str) -> str:
    ext = _Path(path).suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


# ========== 播放端点 ==========

import os as _os
from pathlib import Path as _Path
from fastapi import Request as _Request

_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m2ts", ".m4v", ".3gp", ".ogv"}


@router.get("/movies/{movie_id}/play")
async def play_jav_movie(movie_id: int):
    """获取 JAV 影片播放信息（含 file_path）"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        file_exists = False
        if movie.file_path:
            file_exists = _Path(movie.file_path).exists()

        return {
            "id": movie.id,
            "code": movie.code,
            "title": movie.title,
            "file_path": movie.file_path,
            "file_size": movie.file_size,
            "file_exists": file_exists,
            "cover_url": movie.cover_url,
            "duration": movie.duration,
            "status": movie.status,
        }
    finally:
        await session.close()


@router.get("/movies/{movie_id}/play/file")
async def play_jav_video_file(movie_id: int, request: _Request):
    """JAV 影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
    finally:
        await session.close()

    if not movie or not movie.file_path:
        raise HTTPException(status_code=404, detail="视频不存在")

    file_path = _Path(movie.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = file_path.suffix.lower()
    media_type = "video/mp4"
    if ext == ".mkv":
        media_type = "video/x-matroska"
    elif ext == ".webm":
        media_type = "video/webm"
    elif ext == ".mov":
        media_type = "video/quicktime"
    elif ext == ".ts":
        media_type = "video/mp2t"
    elif ext == ".avi":
        media_type = "video/x-msvideo"

    file_size = file_path.stat().st_size

    range_header = request.headers.get("range")
    if range_header:
        try:
            range_str = range_header.replace("bytes=", "")
            parts = range_str.split("-")
            start = int(parts[0])
            end = int(parts[1]) if parts[1] else file_size - 1

            if start >= file_size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

            chunk_size = end - start + 1

            async def _iter_chunk():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        to_read = min(8192, remaining)
                        data = f.read(to_read)
                        if not data:
                            break
                        yield data
                        remaining -= len(data)

            return StreamingResponse(
                _iter_chunk(),
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(chunk_size),
                    "Accept-Ranges": "bytes",
                },
            )
        except (ValueError, IndexError):
            pass

    async def _iter_full():
        with open(file_path, "rb") as f:
            while True:
                data = f.read(8192)
                if not data:
                    break
                yield data

    from app.utils.http_headers import safe_content_disposition
    return StreamingResponse(
        _iter_full(),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": safe_content_disposition(file_path),
        },
    )


@router.get("/movies/{movie_id}/play/external")
async def get_jav_external_play_url(movie_id: int, request: _Request, protocol: str = "http"):
    """获取 JAV 影片外部播放地址"""
    db = get_jav_db()
    session = await db.get_session()
    try:
        from app.db.jav_models import JavMovie
        from sqlalchemy import select

        stmt = select(JavMovie).where(JavMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie or not movie.file_path:
            raise HTTPException(status_code=404, detail="影片没有关联文件")
        if not _Path(movie.file_path).exists():
            raise HTTPException(status_code=404, detail="视频文件不存在")

        from app.config.manager import get_config
        from app.utils.play_url import build_play_base_url
        config = get_config()
        host = getattr(config.server, "host", "0.0.0.0")
        port = getattr(config.server, "port", 8420)

        base = build_play_base_url(request, host, port)

        if protocol == "http":
            play_url = f"{base}/api/v1/jav/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()


# ========== 文件夹归属检测 / 回填 ==========
# 用途：演员文件夹里存放的一定是该演员的作品。很多素人企划片的 movies.actor 只写了
# "佚名"/素人名/艺名，导致演员页作品数少于文件夹里的实际文件数。此功能扫描所有
# JAV 有码文件夹，找出「文件夹归属演员未写入 actor 字段」的影片并支持一键回填。


@router.get("/folder-check")
async def folder_check(actor: Optional[str] = Query(None, description="仅关注某演员（可模糊）")):
    """检测全部影片的文件夹归属 vs actor 字段差异"""
    from app.utils.folder_actor_check import analyze

    result = await analyze(actor_filter=actor)
    return result


class FolderFillRequest(BaseModel):
    actor: Optional[str] = Field(None, description="仅回填指定演员相关的影片；空 = 全部")


@router.post("/folder-check/fill")
async def folder_check_fill(data: FolderFillRequest, background_tasks: BackgroundTasks):
    """一键回填：把文件夹归属演员追加写入 movies.actor 并重算 movie_count"""
    actor_filter = (data.actor or "").strip() or None

    async def _run():
        from app.utils.folder_actor_check import apply_fill

        updated = await apply_fill(actor_filter=actor_filter)
        logger.info("folder-check/fill 完成，更新 %s 部（actor=%s）", updated, actor_filter)

    background_tasks.add_task(_run)
    return {"status": "started", "actor": actor_filter}


# ========== 封面问题检测与批量修复 ==========
# 背景：JavDB 等 CDN 对 JPEG 做 XOR 混淆（key=data[0]），旧下载链路未解密，
# 导致大量封面落盘为乱码（文件头 CE-31-16-... 而非 FFD8），图片无法打开。
# 本模块提供：
#   1) GET /jav/covers/problems —— 全量扫描，列出本地存在但损坏/乱码的封面
#   2) POST /jav/covers/fix     —— 批量修复（就地 XOR 解密 + 解密后仍损坏的自动重下）

# 封面文件规约（规范目录 {data_base}/movies/jav/{code}/ 下）
_COVER_NAMES = ("poster.jpg", "fanart.jpg", "thumb.jpg", "cover.jpg")

# 刮削来源 → 详情页基址（构造防盗链 Referer，与 movies.py 保持一致）
_SOURCE_DETAIL_BASE_JAV = {
    "javbus": "https://www.javbus.com",
    "javdb": "https://javdb.com",
    "javdatabase": "https://javdatabase.com",
    "avmoo": "https://avmoo.shop",
    "avsox": "https://avsox.click",
    "fanart": "https://fanart.tv",
}

# 问题类型 → 中文说明（前端展示用）
_COVER_PROBLEM_LABELS = {
    "xor_garbled": "CDN 混淆乱码（可解密修复）",
    "decoded_broken": "解码失败/半截文件",
    "too_small": "文件过小（下载残留）",
}


def _inspect_cover_problem(path) -> Optional[str]:
    """检测单个封面文件的问题类型。

    Returns:
        None             = 图片正常
        "xor_garbled"    = JavDB XOR 混淆乱码（maybe_decrypt_javdb_image 可原地修复）
        "decoded_broken" = 非混淆但 PIL 无法解码（半截下载/格式损坏）
        "too_small"      = 体积过小或分辨率过低（下载残留/占位图）

    性能：只用 read(8) 做快速预筛——XOR 混淆与「头非 JPEG」类问题无需 PIL，
    仅对头正常（FFD8）的 JPEG 才做完整解码校验，避免网络盘全量 PIL 解码。
    """
    try:
        p = _Path(path)
        if not p.exists() or not p.is_file():
            return None  # 缺失文件不在本次范围（由缺图补刮流程处理）
        if p.stat().st_size < 2000:
            return "too_small"
        with open(p, "rb") as f:
            head = f.read(8)
    except OSError:
        return "decoded_broken"
    if len(head) < 3:
        return "decoded_broken"
    # XOR 混淆特征：key = data[0]，且 data[1]^key=0xFF、data[2]^key=0xD8
    if head[:2] != b"\xff\xd8" and (
        (head[1] ^ head[0]) == 0xFF and (head[2] ^ head[0]) == 0xD8
    ):
        return "xor_garbled"
    # 头不是 JPEG（FFD8）→ 大概率损坏（乱码/半截），交给 PIL 兜底判定
    # （PNG 等其它合法格式头也非 FFD8，PIL 能解码则视为正常）
    from app.utils.media_helpers import _is_image_broken
    if head[:2] != b"\xff\xd8":
        return "decoded_broken" if _is_image_broken(p) else None
    # JPEG 头正常 → 完整解码校验（verify+load，兜住半截 JPEG）
    if not _is_image_broken(p):
        return None
    return "decoded_broken"


def _decrypt_file_inplace(path) -> bool:
    """就地 XOR 解密单个封面文件，返回是否实际解密（内容被改写）。"""
    from app.utils.media_helpers import maybe_decrypt_javdb_image
    try:
        p = _Path(path)
        data = p.read_bytes()
        new_data = maybe_decrypt_javdb_image(data)
        if new_data == data:
            return False
        p.write_bytes(new_data)
        return True
    except OSError:
        return False


# 封面扫描结果缓存（避免筛选/刷新时反复全量扫描网络盘）
_cover_scan_cache: dict = {"ts": 0.0, "problems": None, "type_counts": None}
_COVER_SCAN_TTL = 120.0

# 封面批量修复进度（后台任务写入，前端轮询显示实时进度）
_cover_fix_state: dict = {
    "running": False, "done": 0, "total": 0,
    "failed": 0, "no_url": 0, "started_at": 0.0,
}


def _scan_cover_dir_sync(entry, movie_by_code: dict) -> Optional[dict]:
    """同步扫描单个番号目录的问题封面（放入线程池并发执行）。

    返回 None = 该目录没有问题封面。
    """
    code = entry.name
    files: list[dict] = []
    for name in _COVER_NAMES:
        p = entry / name
        if not p.exists():
            continue
        t = _inspect_cover_problem(p)
        if not t:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        files.append({"name": name, "type": t, "size": size})
    if not files:
        return None
    movie = movie_by_code.get(code)
    return {
        "movie_id": movie["movie_id"] if movie else None,
        "code": code,
        "title": movie["title"] if movie else code,
        "cover_url": movie["cover_url"] if movie else "",
        "files": files,
    }


async def _scan_cover_problems(type_filter: Optional[str] = None, limit: int = 2000, force: bool = False):
    """全量扫描 JAV 规范目录下的问题封面。

    只检查「文件存在但不完整」的图（缺失图由缺图补刮流程处理）。
    性能优化：
    1. 快速预筛免 PIL（_inspect_cover_problem 只 read 文件头）
    2. asyncio.to_thread 并发扫描目录（网络盘 I/O 并行）
    3. 结果 TTL 缓存（120s），前端刷新/筛选不再重复全量扫描
    Returns: (problems, type_counts)
    """
    import time as _time
    from sqlalchemy import select
    from app.db.jav_models import JavMovie
    from app.utils.media_helpers import get_module_movies_dir

    now = _time.monotonic()
    cache = _cover_scan_cache
    if not force and cache["problems"] is not None and now - cache["ts"] < _COVER_SCAN_TTL:
        problems, type_counts = cache["problems"], cache["type_counts"]
    else:
        # 1) 先查库建 code 索引（关闭会话后再做慢速磁盘扫描）
        db = get_jav_db()
        session = await db.get_session()
        try:
            rows = await session.execute(
                select(
                    JavMovie.id, JavMovie.code, JavMovie.title,
                    JavMovie.cover_url, JavMovie.poster_url,
                )
            )
            movie_by_code: dict[str, dict] = {}
            for mid, code, title, cover_url, poster_url in rows:
                if not code:
                    continue
                movie_by_code[code] = {
                    "movie_id": mid,
                    "code": code,
                    "title": title or code,
                    "cover_url": cover_url or poster_url or "",
                }
        finally:
            await session.close()

        # 2) 收集全部番号目录，并发检测（网络盘 I/O 是主要瓶颈）
        base = get_module_movies_dir("jav")
        problems: list[dict] = []
        if base.exists():
            entries = [e for e in base.iterdir() if e.is_dir()]
            results = await asyncio.gather(
                *(asyncio.to_thread(_scan_cover_dir_sync, e, movie_by_code) for e in entries)
            )
            problems = [r for r in results if r is not None]

        # 3) 统计 + 缓存
        type_counts = {"xor_garbled": 0, "decoded_broken": 0, "too_small": 0}
        for it in problems:
            for f in it["files"]:
                type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1
        cache.update({"ts": now, "problems": problems, "type_counts": type_counts})

    if type_filter:
        problems = [
            it for it in problems
            if any(f["type"] == type_filter for f in it["files"])
        ]
    problems.sort(key=lambda it: it["code"])
    return problems, type_counts


@router.get("/covers/problems")
async def list_cover_problems(
    type_filter: Optional[str] = Query(None, description="按问题类型过滤：xor_garbled / decoded_broken / too_small"),
    limit: int = Query(500, ge=1, le=5000),
    force: bool = Query(False, description="True=跳过缓存强制重新全量扫描"),
):
    """全量扫描 JAV 封面，列出本地存在但损坏/乱码的图片"""
    problems, type_counts = await _scan_cover_problems(type_filter=type_filter, limit=limit, force=force)
    return {
        "total": len(problems),
        "type_counts": type_counts,
        "problems": problems[:limit],
    }


class CoverFixRequest(BaseModel):
    codes: Optional[list[str]] = Field(None, description="要修复的番号列表；空 = 自动扫描全部有问题的")
    decrypt: bool = Field(True, description="先就地 XOR 解密乱码封面（纯本地，不联网）")
    redownload: bool = Field(True, description="解密后仍损坏的文件自动重新下载")
    fast: bool = Field(True, description="重下时跳过刮削，直接使用数据库已有的远程 URL（快；无 URL 才回退刮削）")


async def _redownload_one_images(movie, code: str, fast: bool = True) -> str:
    """对单部影片重下封面：刮削 → DB URL 兜底 → 落盘（含解密）→ 竖版裁剪。

    fast=True（默认）：跳过刮削，直接用 DB 里已有的 cover/poster URL 重下，
    半截文件（decoded_broken）多为 CDN 下载中断，重下即可修复，无需重新刮削；
    DB 无 URL 时才回退刮削。

    Returns:
        "ok" / "no_url" / "error"
    """
    from app.utils.media_helpers import (
        ensure_movie_media_local,
        crop_cover_to_portrait,
        get_movie_cover_path,
    )
    try:
        # 1) fast 模式：直接用 DB 已有远程 URL（无需刮削，批量修复快）
        cover_url = fanart_url = thumb_url = None
        referer = None
        if fast:
            cover_url = getattr(movie, "cover_url", None) or getattr(movie, "poster_url", None)
            fanart_url = getattr(movie, "fanart_url", None)
            thumb_url = getattr(movie, "thumb_url", None)

        # 2) 快速直下拿不到 URL → 回退刮削
        if not cover_url:
            from app.scraper.engine import ScraperEngine
            engine = ScraperEngine()
            result = await engine.scrape_number(code, module="jav")
            if result and result.is_valid() and not getattr(result, "cover_url", None):
                fb = await engine.scrape_number(
                    code, sources=["javdb", "avmoo", "avsox", "dmm_web"], module="jav"
                )
                if fb and fb.is_valid() and getattr(fb, "cover_url", None):
                    result = fb

            if result and result.is_valid():
                cover_url = getattr(result, "cover_url", None) or getattr(result, "poster_url", None)
                fanart_url = getattr(result, "fanart_url", None)
                thumb_url = getattr(result, "thumb_url", None)
                src = getattr(result, "source", None)
                base = _SOURCE_DETAIL_BASE_JAV.get(src or "")
                if base and code:
                    referer = f"{base}/{code}"
        # 3) 刮削拿不到图 → 回退 DB 里已有的远程 URL（来源 URL 往往有效，重下即可修复）
        if not cover_url:
            cover_url = getattr(movie, "cover_url", None) or getattr(movie, "poster_url", None)
        if not referer and cover_url:
            from urllib.parse import urlparse
            p = urlparse(cover_url)
            if p.scheme and p.netloc:
                referer = f"{p.scheme}://{p.netloc}"
        if not cover_url:
            return "no_url"

        await ensure_movie_media_local(
            module_name="jav",
            code=code,
            cover_url=cover_url,
            fanart_url=fanart_url or cover_url,
            thumb_url=thumb_url or cover_url,
            referer=referer,
        )
        crop_cover_to_portrait(get_movie_cover_path("jav", code))

        # 回写数据库封面 URL
        if cover_url:
            from sqlalchemy import select
            from app.db.jav_models import JavMovie
            s2 = await get_jav_db().get_session()
            try:
                m = (await s2.execute(select(JavMovie).where(JavMovie.id == movie.id))).scalar_one_or_none()
                if m is not None:
                    m.cover_url = cover_url
                    m.poster_url = cover_url
                    await s2.commit()
            finally:
                await s2.close()
        return "ok"
    except Exception as e:
        logger.warning(f"封面重下失败 {code}: {e}")
        return "error"


@router.post("/covers/fix")
async def fix_cover_problems(data: CoverFixRequest, background_tasks: BackgroundTasks):
    """批量修复问题封面（后台执行）

    每部影片：
    1. 就地 XOR 解密乱码文件（decrypt=True，纯本地秒级完成）
    2. 解密后仍损坏的文件自动重下（redownload=True，走刮削 + DB URL 兜底）
    """
    from sqlalchemy import select
    from app.db.jav_models import JavMovie
    from app.utils.media_helpers import get_movie_local_dir

    codes = [c.strip() for c in (data.codes or []) if c and c.strip()]
    if not codes:
        problems, _ = await _scan_cover_problems()
        codes = [p["code"] for p in problems]
    if not codes:
        return {"status": "no_problems", "accepted": 0, "codes": []}

    import time as _time
    _cover_fix_state.update({
        "running": True, "done": 0, "total": len(codes),
        "failed": 0, "no_url": 0, "started_at": _time.time(),
    })

    async def _run():
        total = len(codes)
        for idx, code in enumerate(codes, start=1):
            try:
                movie_dir = get_movie_local_dir("jav", code)
                fixed_decrypt = 0
                remaining: list[dict] = []

                # 1) 就地 XOR 解密乱码封面 + 复查
                if movie_dir.exists():
                    for name in _COVER_NAMES:
                        p = movie_dir / name
                        if not p.exists():
                            continue
                        t = _inspect_cover_problem(p)
                        if t == "xor_garbled" and data.decrypt and _decrypt_file_inplace(p):
                            fixed_decrypt += 1
                        t2 = _inspect_cover_problem(p)
                        if t2:
                            remaining.append({"name": name, "type": t2})

                # 2) 解密后仍损坏 → 自动重下
                redownloaded = False
                if remaining and data.redownload:
                    s2 = await get_jav_db().get_session()
                    try:
                        movie = (await s2.execute(
                            select(JavMovie).where(JavMovie.code == code)
                        )).scalar_one_or_none()
                    finally:
                        await s2.close()
                    if movie:
                        ret = await _redownload_one_images(movie, code, fast=data.fast)
                        redownloaded = True
                        remaining = []
                        if movie_dir.exists():
                            for name in _COVER_NAMES:
                                p = movie_dir / name
                                if p.exists():
                                    t = _inspect_cover_problem(p)
                                    if t:
                                        remaining.append({"name": name, "type": t})
                        if ret == "no_url":
                            _cover_fix_state["no_url"] += 1

                logger.info(
                    "封面修复 %s：解密 %s 个，重下=%s，仍损坏=%s（%s/%s）",
                    code, fixed_decrypt, redownloaded,
                    [f["name"] for f in remaining], idx, total,
                )
            except Exception as e:
                logger.warning(f"封面修复失败 {code}: {e}")
                _cover_fix_state["failed"] += 1
            _cover_fix_state["done"] = idx
        # 修复完成 → 失效扫描缓存，下次查询自动重新全量扫描
        _cover_fix_state["running"] = False
        _cover_scan_cache["ts"] = 0.0

    background_tasks.add_task(_run)
    return {"status": "started", "accepted": len(codes), "codes": codes}


@router.get("/covers/fix/status")
async def cover_fix_status():
    """批量封面修复的后台任务进度"""
    return _cover_fix_state


# ---- 全量补全 nfo_cache ----
# 根因：movies.py 的 scrape_by_code/scrape_movie 遇到 NFO 缓存就直接返回
# source="nfo_cache"，从不请求外部站点。导致 NFO 导入的影片元数据不全、
# 番号预览图（{code}-poster/fanart/thumb.jpg）缺失。
#
# 本端点对每部 nfo_cache 影片执行：
#   ① 强制远程刮削（绕过 NFO 缓存），拿最新元数据 + 高清封面 URL
#   ② 下载封面到规范数据目录 poster.jpg/fanart.jpg/thumb.jpg（含 XOR 解密）
#   ③ 写番号预览图到视频源目录（复用 cover_refill._write_covers）
#   ④ 更新 DB：source / scraped_at / cover_url / 演员 / 系列 / NFO 等
# 前端通过 /jav/scrape/refill-nfo-cache/status 轮询实时进度。

_nfo_refill_state: dict = {
    "running": False, "done": 0, "total": 0,
    "scraped": 0, "no_source": 0, "failed": 0,
    "local_only": 0, "started_at": 0.0,
    "failed_list": [],     # 失败的番号清单：[{"code":..., "reason":...}, ...]，含 no_source/failed
    "failed_file": None,   # 任务结束后失败清单落盘路径（txt，每行 code | reason）
}


# ---- 刮削源熔断状态 ----
# JAVBUS 等站点被反爬限流/CDN 挂起时，curl_cffi 请求可能长时间不返回甚至
# 原生阻塞无法取消。连续失败达到阈值即临时熔断该源，后续补全自动跳过它，
# 优先使用 JAVDB API 等健康源，避免整批任务被一个坏源拖死。
_source_fail_streak: dict[str, int] = {}
_source_blackout_until: dict[str, float] = {}
_SOURCE_FAIL_THRESHOLD = 5       # 仅"确定性故障"连续失败 N 次才触发熔断（无有效结果不计）
_SOURCE_BLACKOUT_SECS = 180      # 熔断时长（秒）


def _source_in_blackout(src: str) -> bool:
    import time as _t
    return _source_blackout_until.get(src, 0.0) > _t.monotonic()


def _record_source_result(src: str, ok: bool, fatal: bool = False) -> None:
    """记录单源刮削结果；仅"确定性故障"（超时/HTTP 失败/异常）连续失败达到阈值才熔断。

    站点正常响应但未找到该片（is_valid=False，fatal=False）不计入熔断——
    "该站没这片" ≠ "该站挂了"，JAVDB 上明明有数据的番号绝不能因别的片没收录而被熔断。
    """
    import time as _t
    if ok:
        _source_fail_streak[src] = 0
        _source_blackout_until.pop(src, None)
        return
    if not fatal:
        return
    _source_fail_streak[src] = _source_fail_streak.get(src, 0) + 1
    if _source_fail_streak[src] >= _SOURCE_FAIL_THRESHOLD:
        _source_blackout_until[src] = _t.monotonic() + _SOURCE_BLACKOUT_SECS
        logger.warning(
            f"源 {src} 连续故障 {_SOURCE_FAIL_THRESHOLD} 次，熔断 "
            f"{_SOURCE_BLACKOUT_SECS}s（后续补全自动切到其余源，优先 JAVDB API）"
        )
        _source_fail_streak[src] = 0


class RefillNfoCacheRequest(BaseModel):
    codes: Optional[list[str]] = Field(
        None,
        description="要补全的番号列表；不传则自动选择所有 source=nfo_cache 的影片",
    )
    limit: int = Field(200, ge=1, le=5000, description="自动选择时的最大数量")
    local_first: bool = Field(
        True,
        description="先尝试复制视频目录已有的番号预览图到数据目录（纯本地，秒级，不联网）",
    )
    scrape: bool = Field(
        True,
        description="复制本地图后仍缺封面/preview 的影片强制远程刮削",
    )
    concurrency: int = Field(5, ge=1, le=20, description="刮削并发度")
    sources: list[str] = Field(
        default_factory=lambda: ["javdb", "javbus", "avmoo", "javbooks", "javdatabase", "avsox", "dmm_web"],
        description="刮削源优先级顺序：JAVDB 官方 App API → JAVBUS → AVMOO → 4 辅助。按序逐个尝试，首个有效结果即用；某源超时(60s)/限流自动跳到下一源，连续失败自动熔断 10 分钟",
    )


async def _is_movie_nfo_only(session, movie) -> bool:
    """判定影片是否仅走 NFO 缓存（source=nfo_cache 且 DB 里没封面 URL）。"""
    src = getattr(movie, "source", None)
    if src != "nfo_cache":
        return False
    if getattr(movie, "cover_url", None) or getattr(movie, "poster_url", None):
        return False
    return True


def _pick_video_dir(movie) -> Path | None:
    """取影片所在视频目录（DB file_path 的 parent）。"""
    fp = getattr(movie, "file_path", None)
    if not fp:
        return None
    fp = str(fp)
    if fp == "N/A" or not fp:
        return None
    p = Path(fp)
    if not p.exists() or not p.parent.exists():
        return None
    return p.parent


def _copy_local_previews(video_dir: Path, code: str) -> int:
    """把视频目录的 {code}-*.jpg 复制到数据目录（规范名）。

    Returns: 复制成功的文件数（0/1/2/3 对应 poster/fanart/thumb）
    """
    from pathlib import Path as _Path
    import shutil
    from app.utils.media_helpers import get_movie_local_dir, _is_image_broken
    from app.tasks.base_scanner import _resolve_asset_target

    movie_dir = get_movie_local_dir("jav", code)
    if not movie_dir.exists():
        try:
            movie_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return 0
    if not video_dir.exists():
        return 0

    ready = 0
    try:
        for src in video_dir.iterdir():
            if not src.is_file():
                continue
            stem = src.name
            suffix = src.suffix.lower()
            if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            if _is_image_broken(src):
                continue
            dst_name = _resolve_asset_target(stem, code)
            if dst_name not in ("poster.jpg", "fanart.jpg", "thumb.jpg"):
                continue
            dst = movie_dir / dst_name
            if dst.exists() and not _is_image_broken(dst):
                if dst_name in ("poster.jpg", "fanart.jpg", "thumb.jpg"):
                    ready += 1
                continue
            try:
                shutil.copy2(src, dst)
                ready += 1
            except OSError:
                continue
        # 反向：视频目录的 extrafanart 预览图复制到数据目录
        src_ex = video_dir / "extrafanart"
        if src_ex.is_dir():
            dst_ex = movie_dir / "extrafanart"
            dst_ex.mkdir(parents=True, exist_ok=True)
            for f in src_ex.iterdir():
                if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                    continue
                df = dst_ex / f.name
                if df.exists():
                    continue
                try:
                    shutil.copy2(f, df)
                    ready += 1
                except OSError:
                    continue
    except OSError:
        pass
    return ready


def _movie_has_local_media(movie_dir: Path) -> bool:
    try:
        if not movie_dir.is_dir():
            return False
        for f in movie_dir.iterdir():
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                return True
    except Exception:
        pass
    return False


def _movie_has_full_preview_set(movie_dir: Path) -> bool:
    """三张预览图 poster/fanart/thumb 全部存在且不损坏，且 extrafanart 有样图。

    用户：预览图就是番号文件夹里的 extrafanart。若 extrafanart 为空，
    即使三张主图齐全也视为未补全，触发远程刮削重新下载样图。
    """
    try:
        if not movie_dir.is_dir():
            return False
        from app.utils.media_helpers import _is_image_broken
        for name in ("poster.jpg", "fanart.jpg", "thumb.jpg"):
            p = movie_dir / name
            if not p.is_file() or _is_image_broken(p):
                return False
        # extrafanart 至少 1 张有效样图
        ex = movie_dir / "extrafanart"
        if ex.is_dir():
            for f in ex.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                    return True
        return False
    except Exception:
        return False


@router.post("/scrape/refill-nfo-cache")
async def refill_nfo_cache(
    data: RefillNfoCacheRequest,
    background_tasks: BackgroundTasks,
):
    """批量补全 nfo_cache 影片（后台执行）。

    每部影片：
      1) 若 local_first：把视频目录已有的 {code}-*.jpg 复制到数据目录
      2) 若数据目录仍缺封面 且 scrape：强制远程刮削 + 下载 + 写番号预览图 + 落库
    不处理已走远程刮削的影片（source != nfo_cache 或 DB 已有 cover_url）。
    """
    from sqlalchemy import select
    from app.db.jav_models import JavMovie

    db = get_jav_db()
    session = await db.get_session()
    try:
        if data.codes:
            q = select(JavMovie).where(JavMovie.code.in_(data.codes))
        else:
            q = select(JavMovie).where(JavMovie.source == "nfo_cache").order_by(JavMovie.id)
        rows = (await session.execute(q)).scalars().all()
    finally:
        await session.close()

    targets = []
    for m in rows:
        if m.code:
            targets.append((m.id, m.code))
        if len(targets) >= data.limit:
            break

    if not targets:
        return {"status": "ok", "message": "没有需要补全的 nfo_cache 影片", "total": 0, "queued": 0}

    if _nfo_refill_state.get("running"):
        return {
            "status": "busy",
            "message": "已有任务在跑，请先 /cancel 再发起新任务",
            "total": _nfo_refill_state.get("total", 0),
            "queued": 0,
        }

    import time as _time
    _nfo_refill_state.update({
        "running": True, "done": 0, "total": len(targets),
        "scraped": 0, "no_source": 0, "failed": 0, "local_only": 0,
        "cancel_requested": False,
        "failed_list": [],
        "failed_file": None,
        "started_at": _time.time(),
    })

    async def _run():
        import asyncio as _asyncio
        from app.scraper.engine import ScraperEngine
        from app.utils.media_helpers import get_movie_local_dir
        from app.api.routes.movies import _apply_scrape_result
        from sqlalchemy import select as _select
        from app.db.jav_models import JavMovie

        # 新任务开始：重置刮削源熔断状态，避免上一任务积累的熔断（跨任务延续）
        # 误伤本次任务——"上次 JAVBUS 挂了"不代表"这次 JAVDB 也挂了"。
        _source_fail_streak.clear()
        _source_blackout_until.clear()

        # 一次性 SQL 取全 file_path，避免 7000+ 次单独 DB 查询
        mid_to_fp: dict[int, str] = {}
        if targets:
            db2 = get_jav_db()
            s2 = await db2.get_session()
            try:
                rows = (await s2.execute(
                    _select(JavMovie.id, JavMovie.file_path).where(JavMovie.id.in_([t[0] for t in targets]))
                )).all()
                for r in rows:
                    mid_to_fp[r[0]] = r[1]
            finally:
                await s2.close()

        # 预取 video_dir（同步 O(1) 计算，Path 检查放 worker 内）
        prefetch: dict[int, Path | None] = {}
        for mid, _code in targets:
            fp = mid_to_fp.get(mid)
            if fp and fp != "N/A":
                try:
                    p = Path(fp)
                    if p.parent.exists():
                        prefetch[mid] = p.parent
                    else:
                        prefetch[mid] = None
                except Exception:
                    prefetch[mid] = None
            else:
                prefetch[mid] = None

        sem = _asyncio.Semaphore(data.concurrency)
        _counters = {"scraped": 0, "no_source": 0, "failed": 0, "local_only": 0}

        async def _refill_apply_result(mid, code, result):
            """DB 落库段（写 NFO/封面 + 更新 movie 记录）。

            独立成协程以便调用方用「可放弃超时」包裹：jav.db 位于 L 盘网络路径，
            aiosqlite 底层 sqlite 线程可能因网络 IO 永久阻塞，导致这里任意一个
            await 永不返回。调用方 wait(timeout) 超时后丢弃该任务（不等待取消），
            worker 继续前进，避免单个卡死拖死整批 gather。
            """
            s = await db.get_session()
            try:
                m = await s.get(JavMovie, mid)
                if m is None:
                    return "failed: DB 记录不存在"
                resp = await _apply_scrape_result(s, m, result, "jav", skip_samples=True)
                if resp.get("status") == "ok":
                    await s.commit()
                    return "ok"
                await s.rollback()
                return f"failed: {resp.get('message', '写入失败')}"
            finally:
                await s.close()

        def _flush_failed_file():
            """把当前失败清单落盘为 txt（同步执行，事件循环内无并发写冲突）。

            任务进行中每 50 部刷新一次 + 任务结束时再写一次；文件放
            L:\\data\\logs\\refill_nfo_cache_failed_*.txt，用户可直接打开。
            """
            _fl = list(_nfo_refill_state.get("failed_list") or [])
            if not _fl:
                return
            try:
                from app.config.manager import DATA_DIR as _DD
                _lf = _DD / "logs"
                _lf.mkdir(parents=True, exist_ok=True)
                _ff = _lf / f"refill_nfo_cache_failed_{_time.strftime('%Y%m%d_%H%M%S')}.txt"
                with open(_ff, "w", encoding="utf-8") as _fh:
                    for _item in _fl:
                        _fh.write(f"{_item.get('code')} | {_item.get('reason')}\n")
                _nfo_refill_state["failed_file"] = str(_ff)
                logger.info(f"[refill] 失败清单已落盘: {_ff} ({len(_fl)} 条)")
            except Exception as e:
                logger.warning(f"[refill] 失败清单落盘失败: {e}")

        async def _refill_one(mid, code, video_dir):
            _start_t = _time.monotonic()
            try:
                movie_dir = get_movie_local_dir("jav", code)

                # 步骤 1：复制视频目录的番号预览图到数据目录（to_thread + 可放弃超时）
                if data.local_first and video_dir is not None:
                    try:
                        _ctask = _asyncio.create_task(
                            _asyncio.to_thread(_copy_local_previews, video_dir, code)
                        )
                        _cdone, _crest = await _asyncio.wait({_ctask}, timeout=20.0)
                        if _ctask not in _cdone:
                            _ctask.cancel()
                            logger.warning(f"[refill] 复制本地预览图超时 20s {code}")
                        else:
                            try:
                                _ctask.result()
                            except Exception:
                                pass
                    except Exception as e:
                        logger.warning(f"[refill] 复制本地预览图失败 {code}: {e}")

                # 步骤 2：若数据目录缺 fanart/thumb（或任意缺图） 且 scrape=True → 强制远程刮削
                # 按源优先级顺序尝试（默认 JAVDB API 第一），首个有效结果即返回。
                # 每个源用独立 ScraperEngine + task/`asyncio.wait` 实现「可放弃超时」：
                # curl_cffi 原生阻塞等不可协作取消的调用会让 wait_for 的取消链挂住，
                # 这里超时后直接丢弃等待，让僵尸协程后台自灭，worker 继续下一个源。
                # JAVBUS 连续失败自动熔断（_record_source_result），避免整批被坏源拖死。
                if data.scrape and not _movie_has_full_preview_set(movie_dir):
                    result = None
                    for src in data.sources:
                        if _source_in_blackout(src):
                            logger.info(f"[refill] {code} 跳过熔断中的源 {src}")
                            continue
                        async with sem:
                            _t0 = _time.monotonic()
                            try:
                                task = _asyncio.create_task(
                                    ScraperEngine().scrape_number(
                                        code, module="jav", sources=[src]
                                    )
                                )
                                done, _pend = await _asyncio.wait(
                                    {task}, timeout=60.0
                                )
                                if task in done:
                                    r = task.result()
                                else:
                                    task.cancel()  # 不等待取消生效，僵尸任务后台自灭
                                    r = None
                                    _record_source_result(src, False)
                                    logger.warning(
                                        f"[refill] 源 {src} 刮削 {code} 超时 60s（已放弃等待，跳到下一源）"
                                    )
                            except Exception as e:
                                r = None
                                _record_source_result(src, False, fatal=True)
                                logger.warning(
                                    f"[refill] 源 {src} 刮削 {code} 异常: "
                                    f"{type(e).__name__}: {e}"
                                )
                            _dt = _time.monotonic() - _t0
                        if r and r.is_valid():
                            result = r
                            _record_source_result(src, True)
                            logger.info(
                                f"[refill] {code} 刮削成功 source={src} 耗时 {_dt:.1f}s"
                            )
                            break
                        _record_source_result(src, False)
                        logger.warning(
                            f"[refill] {code} 源 {src} 无有效结果 {_dt:.1f}s"
                        )
                    if not result:
                        _counters["no_source"] += 1
                        _nfo_refill_state["failed_list"].append(
                            {"code": code, "reason": "no_source: 全部刮削源无有效结果"}
                        )
                        return "no_source"

                    # DB 落库段：120s 可放弃超时。落库协程内含封面网络下载 + DB 写，
                    # 若图片 CDN 挂起/被反爬会拖慢落库；wait 超时后丢弃任务（不等待取消），
                    # worker 继续前进，避免单个卡死拖死整批 gather。
                    # 注：样本图(12张)下载已通过 _apply_scrape_result(skip_samples=True) 跳过，
                    # 批量任务里由图片阶段统一处理，避免串行网络下载撑爆 120s。
                    _dbtask = _asyncio.create_task(
                        _refill_apply_result(mid, code, result)
                    )
                    _ddone, _drest = await _asyncio.wait({_dbtask}, timeout=120.0)
                    if _dbtask not in _ddone:
                        _dbtask.cancel()
                        _counters["failed"] += 1
                        _nfo_refill_state["failed_list"].append(
                            {"code": code, "reason": "failed: DB 落库超时 120s（网络图片下载卡住，已放弃）"}
                        )
                        logger.warning(f"[refill] {code} DB 落库超时 120s（已放弃等待，进入图片阶段）")
                    else:
                        _db_res = _dbtask.result()
                        if _db_res != "ok":
                            _counters["failed"] += 1
                            _nfo_refill_state["failed_list"].append(
                                {"code": code, "reason": _db_res}
                            )
                            logger.warning(f"[refill] {code} 落库失败: {_db_res}")
                            return "failed"

                    try:
                        from app.utils.media_helpers import ensure_movie_media_local
                        # 图片映射：poster=竖版封面(frontcover)，fanart=横版大图(fullcover)，thumb=缩略图
                        # javdbapi 把 fullcover_url 放 cover_url、frontcover_url 放 poster_url，
                        # 这里统一用 poster_url 做竖版、cover_url 做横版大图，避免三图同一张
                        # 下载纳入 sem + 90s 可放弃超时：netcdn.space 等 CDN 反爬时(HTTP 521)
                        # 单张图重试可能卡 2-3 分钟，必须整体限时避免整批 worker 挂起。
                        async with sem:
                            _t0 = _time.monotonic()
                            _mtask = _asyncio.create_task(
                                ensure_movie_media_local(
                                    module_name="jav",
                                    code=code,
                                    cover_url=getattr(result, "poster_url", None) or getattr(result, "cover_url", None),
                                    fanart_url=getattr(result, "cover_url", None),
                                    thumb_url=getattr(result, "thumb_url", None) or getattr(result, "poster_url", None) or getattr(result, "cover_url", None),
                                )
                            )
                            _mdone, _mrest = await _asyncio.wait({_mtask}, timeout=90.0)
                            if _mtask not in _mdone:
                                _mtask.cancel()  # 不等待取消生效，僵尸下载后台自灭
                                logger.warning(f"下载媒体超时 90s {code}")
                            else:
                                try:
                                    _mtask.result()
                                except Exception:
                                    pass  # 内部已记录日志，仅避免异常无人检索
                            logger.info(
                                f"[refill] {code} 下载媒体阶段 耗时 {_time.monotonic() - _t0:.1f}s"
                            )
                    except Exception as e:
                        logger.warning(f"下载封面失败 {code}: {e}")

                    # 步骤 3：写视频目录番号预览图（{code}-poster/-fanart/-thumb）
                    if video_dir is not None:
                        try:
                            from app.services.cover_refill import _make_poster
                            movie_dir_for_write = get_movie_local_dir("jav", code)
                            src_map: dict[str, str] = {
                                "poster": "poster.jpg",
                                "fanart": "fanart.jpg",
                                "thumb": "thumb.jpg",
                            }
                            # 用同步 IO 写文件，避免异步上下文里混用
                            def _write_previews_to_video_dir() -> None:
                                for kind, fname in src_map.items():
                                    src = movie_dir_for_write / fname
                                    if not src.is_file():
                                        continue
                                    try:
                                        data = src.read_bytes()
                                    except Exception:
                                        continue
                                    if kind == "poster":
                                        # 2:3 竖版裁切（与 _write_covers 一致）
                                        try:
                                            data = _make_poster(data, code)
                                        except Exception:
                                            pass
                                    out_name = f"{code}-{kind}.jpg"
                                    out_path = video_dir / out_name
                                    if not out_path.is_file():
                                        try:
                                            out_path.write_bytes(data)
                                        except OSError:
                                            pass
                                # 同步 extrafanart 预览图到视频目录（用户：番号文件夹里的 extrafanart 是存放预览图的地方）
                                _src_ex = movie_dir_for_write / "extrafanart"
                                _dst_ex = video_dir / "extrafanart"
                                if _src_ex.is_dir():
                                    _dst_ex.mkdir(parents=True, exist_ok=True)
                                    for _f in _src_ex.iterdir():
                                        if _f.is_file() and _f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                                            _dst_f = _dst_ex / _f.name
                                            if not _dst_f.exists():
                                                try:
                                                    _dst_f.write_bytes(_f.read_bytes())
                                                except OSError:
                                                    pass
                            # 写视频目录用 to_thread（同步 IO），且用可放弃超时包裹：
                            # 网络盘/异常目录下同步文件 IO 可能永久挂起，to_thread 无法被
                            # wait_for 取消，只能等超时后丢弃该任务，worker 继续前进。
                            _wtask = _asyncio.create_task(
                                _asyncio.to_thread(_write_previews_to_video_dir)
                            )
                            _wdone, _wrest = await _asyncio.wait({_wtask}, timeout=30.0)
                            if _wtask not in _wdone:
                                _wtask.cancel()
                                logger.warning(f"写视频目录番号预览图超时 30s {code}")
                            else:
                                try:
                                    _wtask.result()
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.warning(f"写视频目录番号预览图失败 {code}: {e}")

                    _counters["scraped"] += 1
                    return "scraped"
                else:
                    # 已补全（三图齐全且有样图，无需远程刮削）
                    # → 标记 source=local，使其离开 nfo_cache 待补全队列（下次统计/查询不再出现）
                    if _movie_has_full_preview_set(movie_dir):
                        try:
                            s = await db.get_session()
                            try:
                                m = await s.get(JavMovie, mid)
                                if m is not None and m.source == "nfo_cache":
                                    m.source = "local"
                                    m.status = "scraped"
                                    await s.commit()
                            finally:
                                await s.close()
                        except Exception as e:
                            logger.warning(f"标记 local 失败 {code}: {e}")
                    _counters["local_only"] += 1
                    return "local_only"

            except Exception as e:
                logger.warning(f"补全 nfo_cache 失败 {code}: {e}")
                _counters["failed"] += 1
                _nfo_refill_state["failed_list"].append(
                    {"code": code, "reason": f"failed: {type(e).__name__}: {e}"}
                )
                return "failed"

        # 用 wait 并发执行，避免 7000 部串行；sem 控制并发度
        async def _worker(idx: int, mid, code):
            _st = _time.monotonic()
            try:
                status = await _refill_one(mid, code, prefetch.get(mid))
            except Exception as e:
                # 兜底：任何未捕获异常都记入失败清单并推进进度，避免进度停滞
                status = "failed"
                _counters["failed"] += 1
                _nfo_refill_state["failed_list"].append(
                    {"code": code, "reason": f"failed: worker异常 {type(e).__name__}: {e}"}
                )
                logger.warning(f"[refill] {code} worker 异常: {type(e).__name__}: {e}")
            logger.info(
                f"[refill] {code} 完成 status={status} "
                f"耗时 {_time.monotonic() - _st:.1f}s "
                f"(done={idx + 1}/{total} scraped={_counters['scraped']} "
                f"local_only={_counters['local_only']} no_source={_counters['no_source']})"
            )
            # 每部完成后立刻推进进度（避免一批才更新导致前端长时间看到 0）
            _nfo_refill_state["done"] = idx + 1
            _nfo_refill_state["scraped"] = _counters["scraped"]
            _nfo_refill_state["no_source"] = _counters["no_source"]
            _nfo_refill_state["failed"] = _counters["failed"]
            _nfo_refill_state["local_only"] = _counters["local_only"]
            # 每 50 部刷新失败清单文件，任务进行中也能随时查看
            if (idx + 1) % 50 == 0:
                _flush_failed_file()
            return status

        total = len(targets)
        tasks = [_worker(i, mid, code) for i, (mid, code) in enumerate(targets)]
        # batch 不能太大：同批 worker 在 DB 落库段是并发的（无信号量限制），
        # 200 并发会打爆 jav.db 连接池（50 连接 → QueuePool 30s 超时 → failed）。
        # 40 并发在连接池容量内，且任一 worker 卡死也只影响本批 40 个。
        batch_size = 40
        for i in range(0, total, batch_size):
            if _nfo_refill_state.get("cancel_requested"):
                logger.info("refill-nfo-cache: cancel requested at batch %d", i)
                break
            # asyncio.wait 只接受 Task/Future，协程必须用 ensure_future 包装，
            # 否则抛 TypeError: Passing coroutines is forbidden（整批任务崩溃假死）
            batch = [_asyncio.ensure_future(t) for t in tasks[i : i + batch_size]]
            # 每批整体给 25 分钟硬上限：即便个别 worker 异常拖沓，整批也必须返回，
            # 避免无限挂起导致后续批次永不启动（进度冻结、无日志）。
            _gd, _gp = await _asyncio.wait(batch, timeout=1500.0)
            for _t in _gp:
                _t.cancel()
            _nfo_refill_state["done"] = min(i + len(batch), total)
            _nfo_refill_state["scraped"] = _counters["scraped"]
            _nfo_refill_state["no_source"] = _counters["no_source"]
            _nfo_refill_state["failed"] = _counters["failed"]
            _nfo_refill_state["local_only"] = _counters["local_only"]

        # 任务结束：落盘最终失败清单，供用户手动补数据
        _flush_failed_file()
        _nfo_refill_state["running"] = False

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "message": f"已排队补全 {len(targets)} 部 nfo_cache 影片（后台执行）",
        "total": len(targets),
        "queued": len(targets),
    }


@router.get("/scrape/refill-nfo-cache/status")
async def refill_nfo_cache_status():
    """批量补全 nfo_cache 的后台任务进度"""
    return _nfo_refill_state


@router.post("/scrape/refill-nfo-cache/cancel")
async def refill_nfo_cache_cancel():
    """请求取消正在跑的批量补全任务（已启动的批会跑完，新批不再启动）。"""
    _nfo_refill_state["cancel_requested"] = True
    return {"status": "cancel_requested", "running": _nfo_refill_state.get("running", False)}


# ---- 本地预览图兜底（仅复制，不联网）----
_local_sync_state: dict = {
    "running": False, "done": 0, "total": 0,
    "copied": 0, "no_video_dir": 0, "failed": 0, "started_at": 0.0,
}


class LocalSyncRequest(BaseModel):
    codes: Optional[list[str]] = Field(
        None,
        description="要复制的番号列表；不传则自动扫描全部 source=nfo_cache 的影片",
    )
    limit: int = Field(500, ge=1, le=5000, description="自动选择时的最大数量")


@router.post("/covers/sync-local")
async def sync_local_previews(
    data: LocalSyncRequest,
    background_tasks: BackgroundTasks,
):
    """把视频目录已有的番号预览图（{code}-*.jpg）复制到数据目录（不联网）。

    纯本地操作，秒级完成。适合作为「先补齐本地已有图、再单独远程刮削」的轻量步骤。
    """
    from sqlalchemy import select
    from app.db.jav_models import JavMovie

    db = get_jav_db()
    session = await db.get_session()
    try:
        if data.codes:
            q = select(JavMovie).where(JavMovie.code.in_(data.codes))
        else:
            q = select(JavMovie).where(JavMovie.source == "nfo_cache").order_by(JavMovie.id)
        rows = (await session.execute(q)).scalars().all()
    finally:
        await session.close()

    targets = [(m.id, m.code or "") for m in rows if (m.code or "")]
    if data.limit and len(targets) > data.limit:
        targets = targets[: data.limit]

    if not targets:
        return {"status": "ok", "message": "没有需要复制的影片", "total": 0, "queued": 0}

    import time as _time
    _local_sync_state.update({
        "running": True, "done": 0, "total": len(targets),
        "copied": 0, "no_video_dir": 0, "failed": 0,
        "started_at": _time.time(),
    })

    async def _run():
        nonlocal_copied = 0
        nonlocal_no_video = 0
        nonlocal_failed = 0
        nonlocal_marked = 0
        for idx, (mid, code) in enumerate(targets, start=1):
            try:
                video_dir = await _pick_video_dir_async(db, mid)
                if video_dir is None:
                    nonlocal_no_video += 1
                else:
                    n = _copy_local_previews(video_dir, code)
                    nonlocal_copied += n
                    # 复制后若三图齐全且有样图 → 标记 source=local，离开待补全队列
                    if n > 0:
                        from app.utils.media_helpers import get_movie_local_dir
                        movie_dir = get_movie_local_dir("jav", code)
                        if _movie_has_full_preview_set(movie_dir):
                            try:
                                s = await db.get_session()
                                try:
                                    m = await s.get(JavMovie, mid)
                                    if m is not None and m.source == "nfo_cache":
                                        m.source = "local"
                                        m.status = "scraped"
                                        await s.commit()
                                        nonlocal_marked += 1
                                finally:
                                    await s.close()
                            except Exception as e:
                                logger.warning(f"标记 local 失败 {code}: {e}")
            except Exception as e:
                logger.warning(f"复制本地图失败 {code}: {e}")
                nonlocal_failed += 1
            _local_sync_state["done"] = idx
            _local_sync_state["copied"] = nonlocal_copied
            _local_sync_state["no_video_dir"] = nonlocal_no_video
            _local_sync_state["failed"] = nonlocal_failed
            _local_sync_state["marked"] = nonlocal_marked
        _local_sync_state["running"] = False

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "message": f"已排队复制 {len(targets)} 部影片的本地图",
        "total": len(targets),
        "queued": len(targets),
    }


@router.get("/covers/sync-local/status")
async def local_sync_status():
    """本地预览图复制进度"""
    return _local_sync_state


async def _pick_video_dir_async(db, mid: int) -> Path | None:
    """异步查影片 video_dir（从 DB file_path 取 parent）。"""
    from sqlalchemy import select
    from app.db.jav_models import JavMovie

    session = await db.get_session()
    try:
        m = await session.get(JavMovie, mid)
    finally:
        await session.close()

    if m is None:
        return None
    return _pick_video_dir(m)
