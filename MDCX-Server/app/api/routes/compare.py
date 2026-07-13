"""
本地与在线对比路由

API 端点：
- POST /api/v1/compare/scan-local            - 扫描本地文件目录（返回本地番号汇总）
- POST /api/v1/compare/online                - 在线对比（爬取 javdb 演员页/搜索 + 对比本地）
- POST /api/v1/compare/database               - 仅数据库本地汇总（用于前端展示本地状态）
- POST /api/v1/compare/search-directories     - 按演员名搜索本地媒体目录
- GET /api/v1/compare/actors                  - 获取可配置对比URL的演员列表
- GET /api/v1/compare/actors/{actor_id}/url   - 获取某个演员的对比URL配置
- PUT /api/v1/compare/actors/{actor_id}/url   - 保存/更新演员的对比URL配置
- POST /api/v1/compare/actors/scan            - 批量扫描所有10+作品的演员并自动检测目录
- POST /api/v1/compare/actors/{actor_id}/run  - 按演员配置执行在线对比
- POST /api/v1/compare/actors/{actor_id}/detect-dir  - 自动探测演员根目录
- POST /api/v1/compare/browse-dir             - 浏览指定路径下的子目录

对比逻辑参考 .参考/javdb 的 ChineseComparator：
1. 未更新：在线有、本地无
2. 中字差异：在线中字、本地非中字（本地是英文版）
"""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config_manager
from app.db.database import get_session
from app.scraper.comparator import (
    JavDBListCrawler,
    JavBusListCrawler,
    LocalOnlineComparator,
    LocalScanner,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 请求/响应模型 =====

class ScanLocalRequest(BaseModel):
    directories: list[str] = Body(default_factory=list, description="要扫描的目录列表，为空则用配置的媒体目录")


class OnlineCompareRequest(BaseModel):
    actress_url: Optional[str] = Body(None, description="javdb/javbus 演员页 URL")
    keyword: Optional[str] = Body(None, description="搜索关键词（与 actress_url 二选一）")
    directories: list[str] = Body(default_factory=list, description="本地扫描目录，为空则用配置的媒体目录")
    include_database: bool = Body(True, description="是否把数据库影片计入本地集合")
    max_pages: int = Body(10, ge=1, le=50, description="最大爬取页数")
    source: str = Body("javdb", description="数据源: javdb / javbus")


# ===== 辅助函数 =====

def _resolve_directories(directories: list[str]) -> list[str]:
    """解析扫描目录：为空时回退到配置的媒体目录，再为空则返回空列表（仅数据库扫描）"""
    if directories:
        return directories
    manager = get_config_manager()
    media_dirs = manager.config.scraper.media_dirs or []
    return list(media_dirs)


def _find_actor_root_dir(actor_name: str, file_path: str) -> Optional[str]:
    """从影片文件路径向上回溯，找到匹配演员名的目录层级作为根目录

    例如 file_path = V:\\140-150\\楪カレン\\[2021-03-13][EBOD-806]\\file.mp4
    会依次检查：
      V:\\140-150\\楪カレン\\[2021-03-13][EBOD-806]  ← 不匹配
      V:\\140-150\\楪カレン                                  ← 匹配！以此作为根目录
      V:\\140-150                                           ← 不匹配
    如果都不匹配，返回 file_path 的父目录。
    """
    p = Path(file_path)
    if not p.exists():
        return None
    if p.is_file():
        p = p.parent

    name_norm = re.sub(r"[\s_\-·・、.，,./]+", "", actor_name.lower())
    parts = list(p.parts)
    # 从最深开始往上找
    for i in range(len(parts), 0, -1):
        candidate = Path(*parts[:i])
        dir_name_norm = re.sub(r"[\s_\-·・、.，,./]+", "", candidate.name.lower())
        if name_norm in dir_name_norm or dir_name_norm in name_norm:
            return str(candidate)

    return str(p)


# ===== API 端点 =====

class SearchDirectoriesRequest(BaseModel):
    actor_name: str = Body(..., description="演员名（用于匹配本地目录名）")
    max_depth: int = Body(4, ge=1, le=8, description="在媒体目录下递归的最大层级")


@router.post("/search-directories")
async def search_directories(
    req: SearchDirectoriesRequest,
    session: AsyncSession = Depends(get_session),
):
    """按演员名搜索本地媒体目录，返回名称匹配的目录路径列表

    用于「对比」页：输入演员名 → 自动定位该演员的本地文件夹 → 再与在线演员页对比。
    优先使用配置的 media_dirs，如果未配置则从数据库中有 file_path 的影片提取父目录。
    """
    manager = get_config_manager()
    media_dirs = manager.config.scraper.media_dirs or []

    # 优先从配置的媒体目录搜索
    search_roots = list(media_dirs)

    # 如果未配置 media_dirs，从数据库有 file_path 的影片提取父目录作为搜索根
    if not search_roots:
        from app.db.models import Movie
        result = await session.execute(
            select(Movie.file_path).where(
                Movie.file_path.isnot(None),
                Movie.file_path != "",
            ).limit(5000)
        )
        parent_dirs: set[str] = set()
        for (fp,) in result.fetchall():
            if fp:
                p = Path(fp).parent
                if p.exists() and p.is_dir():
                    parent_dirs.add(str(p))
        search_roots = sorted(parent_dirs)

    if not search_roots:
        raise HTTPException(status_code=400, detail="未配置媒体目录，且数据库中没有关联文件的影片记录")

    # 归一化：去空格、转小写、去除常见分隔符
    def norm(s: str) -> str:
        return re.sub(r"[\s_\-·・、.，,./]+", "", s.lower())

    target = norm(req.actor_name)
    if not target:
        raise HTTPException(status_code=400, detail="演员名不能为空")

    matches: list[str] = []
    seen: set[str] = set()
    for root in search_roots:
        base = Path(root)
        if not base.exists() or not base.is_dir():
            continue
        for d in base.rglob("*"):
            if not d.is_dir():
                continue
            depth = len(d.relative_to(base).parts)
            if depth > req.max_depth:
                continue
            name = norm(d.name)
            if target in name or name in target:
                p = str(d)
                if p not in seen:
                    seen.add(p)
                    matches.append(p)
    matches.sort()
    return {
        "actor_name": req.actor_name,
        "search_root_count": len(search_roots),
        "matched_count": len(matches),
        "directories": matches,
    }


@router.post("/scan-local")
async def scan_local(
    req: ScanLocalRequest,
    session: AsyncSession = Depends(get_session),
):
    """扫描本地文件目录，返回本地番号汇总（普通/中字）"""
    import asyncio

    scanner = LocalScanner()
    directories = _resolve_directories(req.directories)

    # 把同步的 rglob 扫描放到线程池中，避免阻塞 FastAPI 事件循环
    file_codes = []
    errors = []
    for d in directories:
        try:
            codes = await asyncio.to_thread(scanner.scan_directory, d)
            file_codes.extend(codes)
        except Exception as e:
            errors.append({"directory": d, "error": str(e)})

    db_codes = []
    try:
        db_codes = await scanner.scan_database(session)
    except Exception as e:
        errors.append({"database": True, "error": str(e)})

    merged = scanner.merge(file_codes, db_codes)
    comparator = LocalOnlineComparator()
    # 仅生成本地汇总
    result = comparator.compare([], merged, online_source="local-scan")

    return {
        "directories": directories,
        "local_summary": result.local_summary,
        "items": [c.__dict__ for c in merged],
        "errors": errors,
    }


@router.post("/online")
async def compare_online(
    req: OnlineCompareRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    在线对比：爬取 javdb 列表（演员页或搜索）并与本地对比

    返回：
    - missing_videos：未更新（在线有、本地无）
    - chinese_mismatch：中字差异（在线中字、本地非中字）
    - local_only：本地有、在线无
    - local_summary：本地汇总
    """
    if not req.actress_url and not req.keyword:
        raise HTTPException(status_code=400, detail="必须提供 actress_url 或 keyword")

    # 1. 采集本地集合（文件 + 数据库）
    import asyncio
    scanner = LocalScanner()
    directories = _resolve_directories(req.directories)

    file_codes = []
    for d in directories:
        try:
            codes = await asyncio.to_thread(scanner.scan_directory, d)
            file_codes.extend(codes)
        except Exception as e:
            logger.warning(f"扫描目录失败 {d}: {e}")

    db_codes = []
    if req.include_database:
        try:
            db_codes = await scanner.scan_database(session)
        except Exception as e:
            logger.warning(f"扫描数据库失败: {e}")

    local_codes = scanner.merge(file_codes, db_codes)

    # 2. 爬取在线列表
    source = req.source.lower().strip()
    if source == "javbus":
        crawler = JavBusListCrawler(max_pages=req.max_pages)
    else:
        crawler = JavDBListCrawler(max_pages=req.max_pages)
    actress_name = ""

    try:
        if req.actress_url:
            online_videos = await crawler.crawl_actress(req.actress_url)
            online_source = req.actress_url
            if hasattr(crawler, '_extract_actress_name'):
                actress_name = crawler._extract_actress_name(req.actress_url)
        else:
            online_videos = await crawler.search_keyword(req.keyword)
            online_source = f"search:{req.keyword}"
    except Exception as e:
        logger.error(f"{source} 爬取失败: {e}")
        raise HTTPException(status_code=502, detail=f"{source} 爬取失败: {e}")

    if not online_videos:
        source_name = "JavBus" if source == "javbus" else "JavDB"
        return {
            "status": "empty",
            "message": f"未能从 {source_name} 获取到在线视频列表，可能原因：1) Cookie 失效需重新登录 2) 被 Cloudflare 拦截 3) 网络问题 4) 演员页 URL 格式不正确",
            "online_source": online_source if 'online_source' in locals() else "",
            "online_count": 0,
        }

    # 3. 对比
    comparator = LocalOnlineComparator()
    result = comparator.compare(
        online_videos,
        local_codes,
        online_source=online_source,
        actress_name=actress_name,
    )

    return {
        "status": "ok",
        **result.to_dict(),
    }


@router.post("/database")
async def local_database_summary(
    session: AsyncSession = Depends(get_session),
):
    """仅返回数据库中本地影片的汇总（中字/非中字/有文件路径）"""
    scanner = LocalScanner()
    try:
        db_codes = await scanner.scan_database(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    comparator = LocalOnlineComparator()
    result = comparator.compare([], db_codes, online_source="database")
    return {
        "local_summary": result.local_summary,
        "items": [c.__dict__ for c in db_codes],
    }


# ============== 演员对比URL管理 ==============


@router.post("/online-by-actor")
async def compare_online_by_actor(
    actor_id: int = Body(..., embed=True, description="演员ID"),
    directories: list[str] = Body(default_factory=list, description="覆盖的本地目录，为空则用配置的"),
    include_database: bool = Body(True, description="是否计入数据库影片"),
    max_pages: int = Body(10, ge=1, le=50, description="最大爬取页数"),
    session: AsyncSession = Depends(get_session),
):
    """按演员对比URL配置执行在线对比"""
    from app.db.models import ActorCompareURL

    config = await session.scalar(
        select(ActorCompareURL).where(ActorCompareURL.actor_id == actor_id)
    )
    if not config or not config.url:
        raise HTTPException(status_code=404, detail="该演员未配置对比URL")

    payload = {
        "directories": directories,
        "include_database": include_database,
        "max_pages": max_pages,
        "source": config.source,
    }
    if config.source == "javbus":
        payload["actress_url"] = config.url
    else:
        payload["actress_url"] = config.url

    if not directories and config.local_directory:
        payload["directories"] = [config.local_directory]

    # 复用原有在线对比逻辑
    return await compare_online(
        OnlineCompareRequest(**payload),
        session=session,
    )


@router.get("/actors")
async def list_compare_actors(
    min_movies: int = Query(10, ge=1, le=100, description="最少作品数"),
    search: Optional[str] = Query(None, description="搜索演员名"),
    session: AsyncSession = Depends(get_session),
):
    """获取可配置对比URL的演员列表（作品数>=min_movies）
    
    返回每个演员的ID、名称、作品数、已有的对比URL配置、本地目录。
    """
    from app.db.models import ActorCompareURL, Actor, Movie, MovieActor

    # 子查询：计算每个演员的作品数
    movie_count_subq = (
        select(
            MovieActor.actor_id,
            func.count(Movie.id).label("movie_count"),
        )
        .join(Movie, MovieActor.movie_id == Movie.id)
        .group_by(MovieActor.actor_id)
        .subquery()
    )

    # 查询作品数 >= min_movies 的演员
    query = (
        select(Actor, func.coalesce(movie_count_subq.c.movie_count, 0))
        .outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)
        .where(movie_count_subq.c.movie_count >= min_movies)
    )

    if search:
        query = query.where(Actor.name.ilike(f"%{search}%"))

    query = query.order_by(movie_count_subq.c.movie_count.desc())
    result = await session.execute(query)
    rows = result.fetchall()

    # 获取已有的 compare URL 配置
    actor_ids = [row[0].id for row in rows]
    compare_configs = {}
    if actor_ids:
        config_result = await session.execute(
            select(ActorCompareURL).where(ActorCompareURL.actor_id.in_(actor_ids))
        )
        for c in config_result.scalars().all():
            compare_configs[c.actor_id] = {
                "id": c.id,
                "source": c.source,
                "url": c.url,
                "local_directory": c.local_directory,
                "auto_detected_dir": c.auto_detected_dir,
                "last_compare_at": c.last_compare_at.isoformat() if c.last_compare_at else None,
            }

    items = []
    for actor, movie_count in rows:
        items.append({
            "id": actor.id,
            "name": actor.name,
            "name_jp": actor.name_jp,
            "movie_count": movie_count,
            "compare_config": compare_configs.get(actor.id),
        })

    return {"total": len(items), "items": items}


@router.get("/actors/{actor_id}/url")
async def get_actor_compare_url(
    actor_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取某个演员的对比URL配置"""
    from app.db.models import ActorCompareURL

    config = await session.scalar(
        select(ActorCompareURL).where(ActorCompareURL.actor_id == actor_id)
    )
    if not config:
        return {"configured": False}
    return {
        "configured": True,
        "id": config.id,
        "actor_id": config.actor_id,
        "actor_name": config.actor_name,
        "source": config.source,
        "url": config.url,
        "local_directory": config.local_directory,
        "auto_detected_dir": config.auto_detected_dir,
        "last_compare_at": config.last_compare_at.isoformat() if config.last_compare_at else None,
        "created_at": config.created_at.isoformat() if config.created_at else None,
    }


@router.put("/actors/{actor_id}/url")
async def save_actor_compare_url(
    actor_id: int,
    source: str = Body(..., description="数据源: javbus/javdb"),
    url: str = Body(..., description="演员页URL"),
    local_directory: Optional[str] = Body(None, description="本地目录路径"),
    session: AsyncSession = Depends(get_session),
):
    """保存/更新演员的对比URL配置"""
    from app.db.models import ActorCompareURL, Actor

    if source not in ("javbus", "javdb"):
        raise HTTPException(status_code=400, detail="source 必须为 javbus 或 javdb")

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    existing = await session.scalar(
        select(ActorCompareURL).where(
            ActorCompareURL.actor_id == actor_id,
            ActorCompareURL.source == source,
        )
    )

    if existing:
        existing.url = url
        existing.actor_name = actor.name
        if local_directory is not None:
            existing.local_directory = local_directory
            existing.auto_detected_dir = False
    else:
        new_config = ActorCompareURL(
            actor_id=actor_id,
            actor_name=actor.name,
            source=source,
            url=url,
            local_directory=local_directory,
            auto_detected_dir=False,
        )
        session.add(new_config)

    await session.commit()
    return {"status": "ok", "message": f"已保存 {actor.name} 的 {source} 对比URL"}


@router.post("/actors/scan")
async def scan_all_compare_actors(
    min_movies: int = Query(10, ge=1, le=100, description="最少作品数"),
    session: AsyncSession = Depends(get_session),
):
    """批量扫描所有符合条件的演员（作品数>=min_movies）并自动探测本地目录
    
    自动探测逻辑：从数据库中有 file_path 的影片提取父目录，然后向上回溯匹配演员名，
    取演员根目录（而非单个视频子目录）。
    """
    from app.db.models import ActorCompareURL, Actor, Movie, MovieActor

    # 查询作品数 >= min_movies 的演员
    movie_count_subq = (
        select(
            MovieActor.actor_id,
            func.count(Movie.id).label("movie_count"),
        )
        .join(Movie, MovieActor.movie_id == Movie.id)
        .group_by(MovieActor.actor_id)
        .subquery()
    )

    query = (
        select(Actor, func.coalesce(movie_count_subq.c.movie_count, 0))
        .outerjoin(movie_count_subq, Actor.id == movie_count_subq.c.actor_id)
        .where(movie_count_subq.c.movie_count >= min_movies)
    )
    result = await session.execute(query)
    actor_rows = result.fetchall()

    # 获取有 file_path 的影片，按演员分组
    fp_result = await session.execute(
        select(Movie.file_path, MovieActor.actor_id)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(
            Movie.file_path.isnot(None),
            Movie.file_path != "",
        )
        .limit(20000)
    )

    actor_paths: dict[int, list[str]] = {}
    for fp, aid in fp_result.fetchall():
        if fp and aid:
            if aid not in actor_paths:
                actor_paths[aid] = []
            actor_paths[aid].append(fp)

    scanned = 0
    configured = 0
    dir_found = 0
    for actor, movie_count in actor_rows:
        scanned += 1

        detected_dir = None
        paths = actor_paths.get(actor.id, [])
        if paths:
            # 对所有 file_path 找演员根目录，取最常见的那个
            root_candidates: dict[str, int] = {}
            for fp in paths:
                root = _find_actor_root_dir(actor.name, fp)
                if root:
                    root_candidates[root] = root_candidates.get(root, 0) + 1
            if root_candidates:
                detected_dir = max(root_candidates, key=root_candidates.get)

        existing = await session.scalar(
            select(ActorCompareURL).where(ActorCompareURL.actor_id == actor.id)
        )
        if existing:
            configured += 1
            if detected_dir and not existing.local_directory:
                existing.local_directory = detected_dir
                existing.auto_detected_dir = True
        else:
            new_config = ActorCompareURL(
                actor_id=actor.id,
                actor_name=actor.name,
                source="javdb",
                url="",
                local_directory=detected_dir,
                auto_detected_dir=bool(detected_dir),
            )
            session.add(new_config)
            if detected_dir:
                dir_found += 1

    await session.commit()
    return {
        "scanned": scanned,
        "already_configured": configured,
        "new_with_dir": dir_found,
        "new_total": scanned - configured,
        "message": f"扫描了 {scanned} 个演员，已配置 {configured} 个，新发现 {scanned - configured} 个",
    }


@router.post("/actors/{actor_id}/detect-dir")
async def detect_actor_local_dir(
    actor_id: int,
    session: AsyncSession = Depends(get_session),
):
    """自动探测某个演员的根目录（向上回溯匹配演员名的目录层级，而非视频子目录）"""
    from app.db.models import Actor, Movie, MovieActor

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    result = await session.execute(
        select(Movie.file_path)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(
            MovieActor.actor_id == actor_id,
            Movie.file_path.isnot(None),
            Movie.file_path != "",
        )
        .limit(500)
    )

    file_paths = [row[0] for row in result.fetchall() if row[0]]
    if not file_paths:
        return {"found": False, "directories": [], "message": "未找到该演员关联的影片文件目录"}

    # 对所有 file_path 找演员根目录
    root_candidates: dict[str, int] = {}
    all_dirs: set[str] = set()
    for fp in file_paths:
        p = Path(fp).parent
        if p.exists() and p.is_dir():
            all_dirs.add(str(p))
        root = _find_actor_root_dir(actor.name, fp)
        if root:
            root_candidates[root] = root_candidates.get(root, 0) + 1

    # 返回出现频率最高的根目录作为推荐
    if root_candidates:
        best = max(root_candidates, key=root_candidates.get)
        return {
            "found": True,
            "matched": best,
            "count": root_candidates[best],
            "total_files": len(file_paths),
            "directories": sorted(all_dirs),
        }

    return {
        "found": False,
        "directories": sorted(all_dirs),
        "message": "找到影片目录，但未能匹配演员名，请手动选择",
    }


@router.post("/browse-dir")
async def browse_directory(
    path: str = Body(..., embed=True, description="浏览哪个路径下的子目录"),
):
    """浏览指定路径，返回子目录列表"""
    base = Path(path)
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=400, detail="路径不存在或不是目录")

    try:
        subdirs = []
        for item in sorted(base.iterdir()):
            if item.is_dir():
                subdirs.append(str(item))
        return {
            "current_path": str(base.resolve()),
            "parent_path": str(base.parent.resolve()) if base.parent != base else None,
            "subdirectories": subdirs,
            "count": len(subdirs),
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
