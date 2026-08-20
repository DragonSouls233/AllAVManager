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
- POST /api/v1/compare/actors/{actor_id}/detect-url  - 自动探测演员的 javbus 女优页 URL 并保存
- POST /api/v1/compare/actors/detect-all      - 批量自动探测所有(或缺配置的)演员的 javbus 女优页 URL
- POST /api/v1/compare/actors/{actor_id}/detect-dir  - 自动探测演员根目录
- POST /api/v1/compare/browse-dir             - 浏览指定路径下的子目录

对比逻辑参考 .参考/javdb 的 ChineseComparator：
1. 未更新：在线有、本地无
2. 中字差异：在线中字、本地非中字（本地是英文版）
"""
import asyncio
import importlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config_manager
from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 模块辅助 =====

def _get_mod_cls(module: str, cls_name: str):
    """获取模块中的任意模型类"""
    mod_path, _, _ = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


# ===== 请求/响应模型 =====

class ScanLocalRequest(BaseModel):
    directories: list[str] = Body(default_factory=list, description="要扫描的目录列表，为空则用配置的媒体目录")


class OnlineCompareRequest(BaseModel):
    actress_url: Optional[str] = Body(None, description="javdb/javbus 演员页 URL")
    keyword: Optional[str] = Body(None, description="搜索关键词（与 actress_url 二选一）")
    actor_name: Optional[str] = Body(None, description="演员名（javbooks 搜索页 URL 需配合演员名执行搜索）")
    directories: list[str] = Body(default_factory=list, description="本地扫描目录，为空则用配置的媒体目录")
    include_database: bool = Body(True, description="是否把数据库影片计入本地集合")
    max_pages: int = Body(10, ge=1, le=50, description="最大爬取页数")
    source: str = Body("javbus", description="数据源: javbus / javdb（默认 javbus，无需 cookie；javdb 需有效 cookie）")
    actor_codes: list[str] = Body(default_factory=list, description="演员白名单(番号列表)；非空时只把这些番号当作「本地」，并跳过全盘文件扫描(避免扫多个 SMB 盘浪费数分钟)")
    fetch_magnets: bool = Body(True, description="对比后是否抓取缺失/中字差异影片的磁力链接（带中文标记）")
    magnet_limit: int = Body(30, ge=0, le=200, description="抓取磁力的影片数量上限")


class RunAllCompareRequest(BaseModel):
    sources: list[str] = Body(["javbus", "javdb", "javbooks"], description="要对比的数据源列表（每个源独立爬取、独立对比）：javbus / javdb / javbooks / avmoo")
    directories: list[str] = Body(default_factory=list, description="覆盖的本地目录，为空则用配置的")
    include_database: bool = Body(True, description="是否计入数据库影片")
    max_pages: int = Body(10, ge=1, le=50, description="最大爬取页数")
    fetch_magnets: bool = Body(True, description="是否抓取缺失/中字差异影片的磁力链接")
    magnet_limit: int = Body(30, ge=0, le=200, description="抓取磁力的影片数量上限")


# ===== 辅助函数 =====

def _resolve_directories(directories: list[str]) -> list[str]:
    """解析扫描目录：为空时回退到配置的媒体目录，再为空则返回空列表（仅数据库扫描）"""
    if directories:
        return directories
    manager = get_config_manager()
    media_dirs = manager.config.scraper.media_dirs or []
    return list(media_dirs)


def _crawler_uncensored(module: str) -> bool:
    """是否无码模块：uncensored 模块走 javbus/javdb 的 uncensored 分区"""
    return (module or "").lower() == "uncensored"


# 对比数据源白名单（javbus/javdb/javbooks/avmoo）
_COMPARE_SOURCES = ("javbus", "javdb", "javbooks", "avmoo")


def _get_list_crawler(source: str, max_pages: int, uncensored: bool):
    """按 source 构建列表爬虫（统一路由，支持 javbus/javdb/javbooks/avmoo）"""
    from app.scraper.comparator import LIST_CRAWLER_SOURCES
    factory = LIST_CRAWLER_SOURCES.get(source)
    if factory is None:
        raise ValueError(f"未知数据源 {source}")
    return factory(max_pages=max_pages, uncensored=uncensored)


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
    module: str = Query("jav"),
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
        session = await get_module_session(module)
        Movie = get_module_model(module, "movie")
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
    module: str = Query("jav"),
):
    """扫描本地文件目录，返回本地番号汇总（普通/中字）"""
    import asyncio

    from app.scraper.comparator import (
        LocalScanner,
        LocalOnlineComparator,
    )

    scanner = LocalScanner()
    directories = _resolve_directories(req.directories)

    # 把同步的 rglob 扫描放到线程池中，避免阻塞 FastAPI 事件循环
    file_codes = []
    errors = []
    # 【按演员对比】模式：actor_codes 非空时，本地只取该演员的 DB 影片，跳过全盘文件扫描。
    # 原因：directories=[] 时 _resolve_directories 会回退到全部默认扫描盘(H:/I:/J:/K:\经典名录/K:\经典系列)，
    # 全是 SMB 网络盘，全盘 rglob 要几分钟，且其中绝大部分不是该演员的，扫描纯属浪费。
    if directories and not req.actor_codes:
        for d in directories:
            try:
                codes = await asyncio.to_thread(scanner.scan_directory, d)
                file_codes.extend(codes)
            except Exception as e:
                errors.append({"directory": d, "error": str(e)})

    db_codes = []
    try:
        session = await get_module_session(module)
        db_codes = await scanner.scan_database(session, module)
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
    module: str = Query("jav"),
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

    from app.scraper.comparator import (
        JavDBListCrawler,
        JavBusListCrawler,
        LocalOnlineComparator,
        LocalScanner,
    )

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
            session = await get_module_session(module)
            db_codes = await scanner.scan_database(session, module)
        except Exception as e:
            logger.warning(f"扫描数据库失败: {e}")

    local_codes = scanner.merge(file_codes, db_codes)

    # 【按演员对比】演员白名单过滤：非空时只保留白名单内的番号
    if req.actor_codes:
        whitelist = set(req.actor_codes)
        before = len(local_codes)
        local_codes = [c for c in local_codes if c.code in whitelist]
        logger.info(f"按演员白名单({len(whitelist)}部)过滤本地: {before} -> {len(local_codes)} 部")

    # 2. 爬取在线列表
    source = req.source.lower().strip()
    if source not in _COMPARE_SOURCES:
        raise HTTPException(status_code=400, detail=f"source 必须为 {' / '.join(_COMPARE_SOURCES)}（默认 javbus）")
    crawler = _get_list_crawler(source, req.max_pages, _crawler_uncensored(module))
    actress_name = ""

    try:
        if req.actress_url:
            online_videos = await crawler.crawl_actress(req.actress_url, actor_name=req.actor_name or "")
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
        from app.scraper.comparator import LIST_CRAWLER_LABELS
        source_name = LIST_CRAWLER_LABELS.get(source, source)
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

    # 4. 抓取缺失/中字差异影片的磁力链接（带中文标记，供前端一键打开/复制）
    if req.fetch_magnets:
        from app.scraper.comparator import attach_magnets
        await attach_magnets(crawler, result.missing_videos, limit=req.magnet_limit)
        await attach_magnets(crawler, result.chinese_mismatch, limit=req.magnet_limit)

    return {
        "status": "ok",
        **result.to_dict(),
    }


@router.post("/database")
async def local_database_summary(
    module: str = Query("jav"),
):
    """仅返回数据库中本地影片的汇总（中字/非中字/有文件路径）"""
    from app.scraper.comparator import LocalScanner, LocalOnlineComparator

    scanner = LocalScanner()
    try:
        session = await get_module_session(module)
        db_codes = await scanner.scan_database(session, module)
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
    source: str = Body("", description="指定数据源 javbus/javdb；为空则用已配置的（默认 javbus）"),
    directories: list[str] = Body(default_factory=list, description="覆盖的本地目录，为空则用配置的"),
    include_database: bool = Body(True, description="是否计入数据库影片"),
    max_pages: int = Body(10, ge=1, le=50, description="最大爬取页数"),
    module: str = Query("jav"),
):
    """按演员对比URL配置执行在线对比

    优先级：
    1. 已配置演员页 URL（javdb/javbus）→ 爬该演员页；
    2. 未配置 URL → 回退按演员名关键词搜索，使「对比」按钮无需手动填 URL 也能用；
    3. 连演员名都没有 → 报错提示。

    一个演员可同时配置 javbus/javdb 两个数据源：传 source 指定对比哪个，
    未传 source 时取已配置的第一个（兼容旧行为）。
    """
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    if source:
        config = await session.scalar(
            select(ActorCompareURL).where(
                ActorCompareURL.actor_id == actor_id,
                ActorCompareURL.source == source,
            )
        )
    else:
        config = await session.scalar(
            select(ActorCompareURL).where(ActorCompareURL.actor_id == actor_id)
        )
    actor = await session.get(Actor, actor_id)
    actor_name = actor.name if actor else None

    # 【按演员对比】查该演员在本地 DB 里的番号集，作为白名单传给 compare_online。
    # 这样本地对比只针对该演员(避免把整个 jav 库 8000+ 部都拿来比)，并跳过全盘文件扫描。
    # 注意：合并后的演员 name 可能形如 "葵つかさ,新ありな"，需要按每个名字 OR 匹配。
    actor_codes: list[str] = []
    if actor_name:
        try:
            Movie = get_module_model(module, "movie")
            names = [n.strip() for n in actor_name.split(",") if n.strip()]
            if names:
                cond = or_(*[Movie.actor.ilike(f"%{n}%") for n in names])
                rows = await session.execute(
                    select(Movie.code).where(cond, Movie.code.isnot(None))
                )
                actor_codes = sorted({r[0] for r in rows.fetchall() if r[0]})
            logger.info(f"演员 {actor_name} 本地已关联影片 {len(actor_codes)} 部, 将以此过滤本地对比集")
        except Exception as e:
            logger.warning(f"查询演员 {actor_name} 本地番号失败: {e}")

    # 默认走 javbus：本服务器实测 javbus 无需 cookie 即可爬取；
    # 仅当用户显式配置了 javdb 且持有有效 cookie 时才用 javdb。
    source = config.source if (config and config.source) else "javbus"

    payload = {
        "directories": directories,
        "include_database": include_database,
        "max_pages": max_pages,
        "source": source,
        "actor_codes": actor_codes,
        "actor_name": actor_name,
    }

    if config and config.url:
        payload["actress_url"] = config.url
        logger.info(f"演员 {actor_name} 使用已配置对比URL: {config.url}")
    elif actor_name:
        # 未配置 URL：回退到按演员名关键词搜索，使「对比」按钮无需手动填 URL 也能用
        payload["keyword"] = actor_name
        logger.info(f"演员 {actor_name} 未配置对比URL，回退到关键词搜索")
    else:
        raise HTTPException(status_code=404, detail="找不到该演员，无法对比")

    if not directories and config and config.local_directory:
        payload["directories"] = [config.local_directory]

    # 复用原有在线对比逻辑
    return await compare_online(
        OnlineCompareRequest(**payload),
        module=module,
    )


@router.post("/actors/{actor_id}/run-all")
async def compare_actor_all_sources(
    actor_id: int,
    req: RunAllCompareRequest = Body(default_factory=RunAllCompareRequest),
    module: str = Query("jav"),
):
    """按演员同时对比多个数据源（javbus / javdb），结果按源分组返回

    每个源独立爬取、独立对比、独立容错（一个源失败不影响另一个）。
    返回结构：
    {
      "status": "ok",
      "actress_name": "...",
      "sources": {
        "javbus": {"status": "ok", ...CompareResult.to_dict()},
        "javdb":  {"status": "error" | "empty" | "ok", ...}
      }
    }
    磁力抓取：对每个源的缺失/中字差异影片抓详情页磁力（带中文标记）。
    """
    from app.scraper.comparator import (
        JavDBListCrawler,
        JavBusListCrawler,
        LocalOnlineComparator,
        LocalScanner,
        attach_magnets,
    )

    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="找不到该演员")
    actor_name = actor.name or ""

    # 已配置的各源 URL
    configs = (await session.execute(
        select(ActorCompareURL).where(ActorCompareURL.actor_id == actor_id)
    )).scalars().all()
    config_map = {c.source: c for c in configs}

    # 该演员本地番号白名单（用于过滤本地集合 + 跳过全盘文件扫描）
    actor_codes: list[str] = []
    if actor_name:
        try:
            Movie = get_module_model(module, "movie")
            names = [n.strip() for n in actor_name.split(",") if n.strip()]
            if names:
                cond = or_(*[Movie.actor.ilike(f"%{n}%") for n in names])
                rows = await session.execute(
                    select(Movie.code).where(cond, Movie.code.isnot(None))
                )
                actor_codes = sorted({r[0] for r in rows.fetchall() if r[0]})
        except Exception as e:
            logger.warning(f"查询演员 {actor_name} 本地番号失败: {e}")

    # 本地集合只算一次（白名单过滤，与 online-by-actor 一致）
    scanner = LocalScanner()
    local_codes: list = []
    try:
        db_codes = await scanner.scan_database(session, module)
        if req.directories and not actor_codes:
            for d in req.directories:
                try:
                    db_codes.extend(await asyncio.to_thread(scanner.scan_directory, d))
                except Exception as e:
                    logger.warning(f"扫描目录失败 {d}: {e}")
        local_codes = scanner.merge(db_codes, [])
        if actor_codes:
            whitelist = set(actor_codes)
            before = len(local_codes)
            local_codes = [c for c in local_codes if c.code in whitelist]
            logger.info(f"[run-all] 按演员白名单({len(whitelist)}部)过滤本地: {before} -> {len(local_codes)}")
    except Exception as e:
        logger.warning(f"[run-all] 本地扫描失败: {e}")

    comparator = LocalOnlineComparator()
    sources: dict = {}
    # 各源并行执行（限制并发，避免同时抓取详情页被反爬拦截），
    # 总耗时从「各源之和」降为「最慢单源」，防止前端超时中断。
    sem = asyncio.Semaphore(2)

    async def _run_one(source: str):
        source = (source or "").lower().strip()
        if source not in _COMPARE_SOURCES:
            return source, {"status": "error", "detail": f"未知数据源 {source}"}
        try:
            crawler = _get_list_crawler(source, req.max_pages, _crawler_uncensored(module))
            cfg = config_map.get(source)
            if cfg and cfg.url:
                online_videos = await crawler.crawl_actress(cfg.url, actor_name=actor_name)
                online_source = cfg.url
            elif actor_name:
                online_videos = await crawler.search_keyword(actor_name)
                online_source = f"search:{actor_name}"
            else:
                return source, {"status": "error", "detail": "未配置URL且无演员名"}

            if not online_videos:
                return source, {
                    "status": "empty",
                    "message": f"未能从 {source} 获取到在线视频列表，可能原因：1) Cookie 失效需重新登录 2) 被 Cloudflare 拦截 3) 网络问题 4) 演员页 URL 格式不正确",
                    "online_count": 0,
                }

            result = comparator.compare(
                online_videos, local_codes,
                online_source=online_source,
                actress_name=actor_name,
            )
            if req.fetch_magnets:
                await attach_magnets(crawler, result.missing_videos, limit=req.magnet_limit)
                await attach_magnets(crawler, result.chinese_mismatch, limit=req.magnet_limit)
            return source, {"status": "ok", **result.to_dict()}
        except Exception as e:
            logger.error(f"[run-all] {source} 对比失败: {e}")
            return source, {"status": "error", "detail": str(e)}

    async def _run_limited(source: str):
        async with sem:
            return await _run_one(source)

    for k, v in await asyncio.gather(*(_run_limited(s) for s in req.sources)):
        sources[k] = v

    return {"status": "ok", "actress_name": actor_name, "sources": sources}


@router.get("/actors")
async def list_compare_actors(
    min_movies: int = Query(10, ge=1, le=100, description="最少作品数"),
    search: Optional[str] = Query(None, description="搜索演员名"),
    module: str = Query("jav"),
):
    """获取可配置对比URL的演员列表（作品数>=min_movies）

    返回每个演员的ID、名称、作品数、已有的对比URL配置、本地目录。
    """
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")
    Movie = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    # 作品数直接取自 actors.movie_count 列（扫描器维护）；
    # MovieActor 关联表在所有模块均为空，不可靠，故不再 join 它。
    # 搜索模式：用户想快速定位并编辑某个演员的配置，放宽作品数下限，
    # 否则 movie_count<10 的演员（库里约 110/531 为 0）永远搜不到、无法编辑。
    if search:
        query = select(Actor, func.coalesce(Actor.movie_count, 0)).where(
            Actor.name.ilike(f"%{search}%")
        )
    else:
        query = (
            select(Actor, func.coalesce(Actor.movie_count, 0))
            .where(func.coalesce(Actor.movie_count, 0) >= min_movies)
        )

    query = query.order_by(func.coalesce(Actor.movie_count, 0).desc())
    result = await session.execute(query)
    rows = result.fetchall()

    # 获取已有的 compare URL 配置（一个演员可能同时配置 javbus/javdb 多个数据源）
    actor_ids = [row[0].id for row in rows]
    compare_configs: dict[int, list[dict]] = {}
    if actor_ids:
        config_result = await session.execute(
            select(ActorCompareURL).where(ActorCompareURL.actor_id.in_(actor_ids))
        )
        for c in config_result.scalars().all():
            cfg = {
                "id": c.id,
                "source": c.source,
                "url": c.url,
                "local_directory": c.local_directory,
                "auto_detected_dir": c.auto_detected_dir,
                "last_compare_at": c.last_compare_at.isoformat() if c.last_compare_at else None,
            }
            compare_configs.setdefault(c.actor_id, []).append(cfg)

    items = []
    for actor, movie_count in rows:
        configs = compare_configs.get(actor.id, [])
        items.append({
            "id": actor.id,
            "name": actor.name,
            "name_jp": actor.name_jp,
            "movie_count": movie_count,
            "compare_config": configs[0] if configs else None,  # 兼容旧前端
            "compare_configs": configs,  # 全部数据源配置（每个演员可同时配 javbus/javdb）
        })

    return {"total": len(items), "items": items}


@router.get("/actors/{actor_id}/url")
async def get_actor_compare_url(
    actor_id: int,
    module: str = Query("jav"),
):
    """获取某个演员的对比URL配置"""
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")

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
    module: str = Query("jav"),
):
    """保存/更新演员的对比URL配置"""
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    if source not in _COMPARE_SOURCES:
        raise HTTPException(status_code=400, detail=f"source 必须为 {' / '.join(_COMPARE_SOURCES)}")

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


async def _upsert_compare_url(session, ActorCompareURL, actor, source: str, url: str, local_directory=None, auto_detected_dir=False):
    """插入或更新演员对比 URL 配置（供探测端点复用）"""
    existing = await session.scalar(
        select(ActorCompareURL).where(
            ActorCompareURL.actor_id == actor.id,
            ActorCompareURL.source == source,
        )
    )
    if existing:
        existing.url = url
        existing.actor_name = actor.name
        existing.auto_detected_dir = auto_detected_dir
        if local_directory is not None:
            existing.local_directory = local_directory
    else:
        session.add(ActorCompareURL(
            actor_id=actor.id,
            actor_name=actor.name,
            source=source,
            url=url,
            local_directory=local_directory,
            auto_detected_dir=auto_detected_dir,
        ))
    return existing


async def _detect_actor_url(crawler, actor_name: str, source: str):
    """统一探测演员页 URL：javbus 用 detect_actress_star，其余用 detect_actress

    Returns:
        (url, id) 或 None
    """
    if source == "javbus":
        return await crawler.detect_actress_star(actor_name)
    return await crawler.detect_actress(actor_name)


@router.post("/actors/{actor_id}/detect-url")
async def detect_actor_compare_url(
    actor_id: int,
    source: str = Query("all", description="探测数据源: javbus/javdb/javbooks/avmoo/all(全部探测)"),
    module: str = Query("jav"),
):
    """自动探测该演员在各数据源的女优页 URL 并保存到对比配置

    探测逻辑：
    - javbus：/searchstar/{演员名} → 解析 /star/{id} 女优链接 → 按姓名匹配最佳候选
    - javdb：App API 演员目录按名反查 / App API 失败降级 /search?q={演员名}&f=actress
    - javbooks：经 avmoo 反查作品番号 → javbooks 搜索页 → 详情页女优链接 → 匹配
    - avmoo：/jav/data/api/search 按演员名 → starId → /star/{id}
    source=all 时全部源都探测，各自成功各自落库。
    成功后该演员点「对比」将走精准女优页（crawl_actress），不再用关键词搜索。
    """
    sources = list(_COMPARE_SOURCES) if source == "all" else [source]
    for s in sources:
        if s not in _COMPARE_SOURCES:
            raise HTTPException(status_code=400, detail=f"source 必须为 {' / '.join(_COMPARE_SOURCES)} / all")
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    actor = await session.get(Actor, actor_id)
    if not actor or not actor.name:
        raise HTTPException(status_code=404, detail="演员不存在或没有姓名")

    results: dict = {}
    for s in sources:
        try:
            crawler = _get_list_crawler(s, 1, _crawler_uncensored(module))
            result = await _detect_actor_url(crawler, actor.name, s)
        except Exception as e:
            logger.error(f"探测 {actor.name} 的 {s} 女优页异常: {e}")
            results[s] = {"status": "error", "message": str(e)}
            continue

        if not result:
            results[s] = {"status": "not_found", "message": f"未能在 {s} 找到与「{actor.name}」匹配的女优页"}
            continue

        star_url, _ = result
        await _upsert_compare_url(session, ActorCompareURL, actor, s, star_url, auto_detected_dir=True)
        results[s] = {"status": "ok", "url": star_url}
    await session.commit()

    if all(r.get("status") == "not_found" or r.get("status") == "error" for r in results.values()):
        first = next(iter(results.values()))
        return {"status": "not_found", "actor_id": actor_id, "actor_name": actor.name, "results": results,
                "message": first.get("message", "未找到匹配的女优页")}
    return {"status": "ok", "actor_id": actor_id, "actor_name": actor.name, "results": results,
            "message": "探测完成：" + "，".join(f"{s}:{'已保存' if r.get('status')=='ok' else '未找到'}" for s, r in results.items())}


@router.post("/actors/detect-all")
async def detect_all_compare_urls(
    min_movies: int = Body(10, description="仅探测作品数 >= 该值的演员"),
    only_missing: bool = Body(True, description="True=只探测尚未配置 URL 的演员；False=全量重探"),
    delay: float = Body(1.0, description="每两个探测之间的请求间隔(秒)，避免触发 Cloudflare"),
    sources: list[str] = Body(["javbus", "javdb", "javbooks", "avmoo"], description="要探测的数据源列表：javbus / javdb / javbooks / avmoo"),
    module: str = Query("jav"),
):
    """批量自动探测所有（或仅缺配置的）演员的各数据源女优页 URL

    按源逐个探测：对每个源，跳过已配置该源 URL 的演员。
    顺序执行（带间隔），每成功一个立即落库，中途失败不影响其余。
    返回 summary：按源统计 探测总数 / 成功 / 未找到 / 跳过(已有) / 失败。
    """
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    sources = [s.lower().strip() for s in sources if s.lower().strip() in _COMPARE_SOURCES]
    if not sources:
        raise HTTPException(status_code=400, detail=f"sources 必须包含 {' / '.join(_COMPARE_SOURCES)}")

    query = select(Actor).where(func.coalesce(Actor.movie_count, 0) >= min_movies)
    rows = (await session.execute(query)).scalars().all()

    # 已配置各源的 actor_id 集合（仅统计 URL 非空的配置；空 URL 视为未配置，会重新探测覆盖）
    configured_sets: dict[str, set[int]] = {}
    if only_missing:
        cfg_rows = (await session.execute(
            select(ActorCompareURL.actor_id, ActorCompareURL.source)
            .where(ActorCompareURL.url.isnot(None), ActorCompareURL.url != "")
        )).all()
        for actor_id, src in cfg_rows:
            configured_sets.setdefault(src, set()).add(actor_id)
    targets = list(rows)

    # 各源爬虫懒加载（探测失败/被拦截不影响其他源）
    crawlers: dict = {}
    for source in sources:
        try:
            crawlers[source] = _get_list_crawler(source, 1, _crawler_uncensored(module))
        except Exception as e:
            logger.warning(f"批量探测 {source} 爬虫初始化失败: {e}")

    summary: dict = {
        "total": len(targets),
        "sources": {},
        "details": [],
    }
    for source in sources:
        st = {"detected": 0, "not_found": 0, "failed": 0, "skipped": 0}
        crawler = crawlers.get(source)
        if crawler is None:
            st["failed"] = len(targets)
            summary["sources"][source] = st
            continue
        for actor in targets:
            if not actor.name:
                continue
            if only_missing and actor.id in configured_sets.get(source, set()):
                st["skipped"] += 1
                continue
            try:
                result = await _detect_actor_url(crawler, actor.name, source)
            except Exception as e:
                logger.warning(f"批量探测 {actor.name} 的 {source} 异常: {e}")
                st["failed"] += 1
                summary["details"].append({"actor_id": actor.id, "actor_name": actor.name, "source": source, "status": "failed", "error": str(e)})
                await asyncio.sleep(delay)
                continue

            if not result:
                st["not_found"] += 1
                summary["details"].append({"actor_id": actor.id, "actor_name": actor.name, "source": source, "status": "not_found"})
                await asyncio.sleep(delay)
                continue

            star_url, _ = result
            await _upsert_compare_url(session, ActorCompareURL, actor, source, star_url, auto_detected_dir=True)
            await session.commit()
            st["detected"] += 1
            summary["details"].append({"actor_id": actor.id, "actor_name": actor.name, "source": source, "status": "ok", "url": star_url})
            await asyncio.sleep(delay)

        summary["sources"][source] = st

    return {"status": "ok", **summary}


@router.post("/actors/{actor_id}/scrape-movies")
async def scrape_actor_movies(
    actor_id: int,
    max_pages: int = Query(5, ge=1, le=20, description="最大抓取页数(每页50部)"),
    module: str = Query("jav"),
):
    """按演员页精确抓取影片列表（P0-1：演员 URL 接入刮削）。

    读取该演员已配置的 javdb /actors/{id} 对比 URL，用 App API
    /api/v1/movies/tags + filter_by 按演员 ID 抓取完整片单（不依赖标题命中），
    返回影片列表供前端展示 / 触发刮削。
    未配置 javdb URL 时返回 400。
    """
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    cfg = await session.scalar(
        select(ActorCompareURL).where(
            ActorCompareURL.actor_id == actor_id,
            ActorCompareURL.source == "javdb",
        )
    )
    url = (cfg.url if cfg else "") or ""
    if not url:
        raise HTTPException(status_code=400, detail=f"{actor.name} 尚未配置 javdb 演员页 URL，请先探测")

    crawler = _get_list_crawler("javdb", max_pages, _crawler_uncensored(module))
    try:
        videos = await crawler.scrape_actor_movies(url, max_pages=max_pages)
    except Exception as e:
        logger.error(f"抓取演员影片列表失败 {actor.name} ({url}): {e}")
        raise HTTPException(status_code=502, detail=f"抓取失败: {e}")

    items = [
        {
            "code": v.code,
            "base_code": v.base_code,
            "title": v.title,
            "url": v.url,
            "date": v.date,
            "has_chinese": v.has_chinese,
        }
        for v in videos
    ]
    return {
        "status": "ok",
        "actor_id": actor_id,
        "actor_name": actor.name,
        "actor_url": url,
        "total": len(items),
        "movies": items,
    }


@router.post("/actors/scrape-movies-all")
async def scrape_all_actor_movies(
    min_movies: int = Query(10, ge=1, le=100, description="最少作品数"),
    max_pages: int = Query(5, ge=1, le=20, description="每演员最大抓取页数(每页50部)"),
    only_with_url: bool = Body(True, description="True=仅抓已配置 javdb URL 的演员"),
    module: str = Query("jav"),
):
    """批量按演员页抓取影片列表（仅已配置 javdb URL 的演员）。

    对每个已配置 javdb /actors/{id} URL 的演员，抓取其完整片单。
    顺序执行（带间隔），单个失败不影响其余。
    返回每演员的影片数与总数。
    """
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")

    query = (
        select(Actor, ActorCompareURL)
        .join(ActorCompareURL, ActorCompareURL.actor_id == Actor.id)
        .where(
            ActorCompareURL.source == "javdb",
            ActorCompareURL.url.isnot(None),
            ActorCompareURL.url != "",
        )
    )
    if only_with_url:
        query = query.where(func.coalesce(Actor.movie_count, 0) >= min_movies)
    rows = (await session.execute(query)).all()

    crawler = _get_list_crawler("javdb", max_pages, _crawler_uncensored(module))
    results: list[dict] = []
    total = 0
    for actor, cfg in rows:
        try:
            videos = await crawler.scrape_actor_movies(cfg.url, max_pages=max_pages)
            results.append({
                "actor_id": actor.id,
                "actor_name": actor.name,
                "url": cfg.url,
                "total": len(videos),
                "status": "ok",
            })
            total += len(videos)
        except Exception as e:
            logger.warning(f"批量抓取影片 {actor.name} 失败: {e}")
            results.append({"actor_id": actor.id, "actor_name": actor.name, "url": cfg.url, "total": 0, "status": "failed", "error": str(e)})
        await asyncio.sleep(1.0)
    return {"status": "ok", "actors": len(results), "total_movies": total, "results": results}


@router.post("/actors/scan")
async def scan_all_compare_actors(
    min_movies: int = Query(10, ge=1, le=100, description="最少作品数"),
    module: str = Query("jav"),
):
    """批量扫描所有符合条件的演员（作品数>=min_movies）并自动探测本地目录

    自动探测逻辑：从数据库中有 file_path 的影片提取父目录，然后向上回溯匹配演员名，
    取演员根目录（而非单个视频子目录）。
    """
    session = await get_module_session(module)
    ActorCompareURL = _get_mod_cls(module, "ActorCompareURL")
    Actor = get_module_model(module, "actor")
    Movie = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    # 作品数直接取自 actors.movie_count 列（MovieActor 关联表为空不可靠）
    query = (
        select(Actor, func.coalesce(Actor.movie_count, 0))
        .where(func.coalesce(Actor.movie_count, 0) >= min_movies)
    )
    result = await session.execute(query)
    actor_rows = result.fetchall()

    scanned = 0
    configured = 0
    dir_found = 0
    for actor, movie_count in actor_rows:
        scanned += 1

        detected_dir = None
        # MovieActor 关联表为空，改用 movie.actor 文本 LIKE 取该演员影片路径
        paths = []
        if actor.name:
            fp_res = await session.execute(
                select(Movie.file_path).where(
                    Movie.actor.like(f"%{actor.name}%"),
                    Movie.file_path.isnot(None),
                    Movie.file_path != "",
                ).limit(500)
            )
            paths = [r[0] for r in fp_res.fetchall() if r[0]]
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
                source="javbus",
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
    module: str = Query("jav"),
):
    """自动探测某个演员的根目录（向上回溯匹配演员名的目录层级，而非视频子目录）"""
    session = await get_module_session(module)
    Actor = get_module_model(module, "actor")
    Movie = get_module_model(module, "movie")
    MovieActor = _get_mod_cls(module, "MovieActor")

    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    # MovieActor 关联表在所有模块均为空，改用 movie.actor 文本 LIKE 匹配
    result = await session.execute(
        select(Movie.file_path)
        .where(
            Movie.actor.like(f"%{actor.name}%"),
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
