"""
PORNHub 模块 API 路由

功能：
- 演员列表/详情
- 影片列表/详情
- 影片刮削（借助 PornhubCrawler 获取元数据后写入模块 DB）
- 演员资料和头像刮削
- 视频截图生成封面
"""

import asyncio
import logging
import re
from pathlib import Path
from pathlib import Path as _Path
from typing import Optional

import os as _os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request as _Request

from app.db.module_db import ModuleDatabase
from app.services.pornhub_comparison import PornhubComparator, TitleNormalizer, LocalMediaScanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pornhub", tags=["PORNHub模块"])

# 断点续扫并发锁：防止重复点击导致两个扫描同时写库
_pornhub_scan_lock = asyncio.Lock()


def get_pornhub_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("pornhub")


async def _store_pornhub_actor_avatar(actor, profile_avatar_url: "str | None", actor_name: str) -> "str | None":
    """下载头像到本地，并落盘为约定文件 DATA/avatars/pornhub/actor_{id}.jpg。

    修复：原逻辑只把远程 URL 写进 actor.avatar_url，而模块头像端点
    (get_module_actor_avatar_file) 对远程 URL 不服务（仅服务本地文件），
    导致刮削后头像仍显示占位图。现统一按模块端点优先读取的命名
    (actor_{id}.jpg) 落盘，使头像真正显示；avatar_url 同时指向本地文件作为兜底。
    """
    if not profile_avatar_url or not str(profile_avatar_url).startswith("http"):
        return None
    try:
        from app.scraper.pornhub_actor_scraper import download_actor_avatar
        from app.config.manager import DATA_DIR
        import shutil

        local = await download_actor_avatar(actor_name, profile_avatar_url)
        if local:
            dst_dir = DATA_DIR / "avatars" / "pornhub"
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local, dst_dir / f"actor_{actor.id}.jpg")
            actor.avatar_url = local
            return local
    except Exception as e:
        logger.debug(f"头像落盘失败 [{actor_name}]: {e}")
    # 下载失败，保留远程地址（前端兜底不服务，但记录来源供排查）
    actor.avatar_url = profile_avatar_url
    return None


async def _recount_actor_movie_count(session, actor_name: str) -> int:
    """按 movie.actor LIKE '%name%' 重算该演员作品数，与扫描口径一致，避免重复刮削累加。"""
    from app.db.pornhub_models import PornhubMovie
    from sqlalchemy import select, func

    return (await session.scalar(
        select(func.count()).select_from(PornhubMovie).where(
            PornhubMovie.actor.like(f"%{actor_name}%")
        )
    )) or 0



# ========== 对比查重 ==========


@router.get("/compare/status")
async def api_compare_status():
    """获取对比查重服务状态"""
    return {"ready": True, "service": "PornhubComparator"}


@router.post("/compare")
async def api_compare(data: dict):
    """执行 PORNHub 本地 vs 在线对比查重

    请求体：
    {
        "actress_url": "https://www.pornhub.com/model/xxx",
        "local_directory": "可选，指定对比的本地目录",
        "max_pages": 5,
        "similarity_threshold": 0.85
    }
    """
    comparator = PornhubComparator()
    result = await comparator.compare(
        actress_url=data.get("actress_url", ""),
        local_directory=data.get("local_directory"),
        similarity_threshold=data.get("similarity_threshold", 0.85),
        max_pages=data.get("max_pages", 5),
    )
    return result


@router.post("/compare/test-normalize")
async def api_test_normalize(data: dict):
    """测试标题归一化效果"""
    normalizer = TitleNormalizer()
    title = data.get("title", "")
    normalized = normalizer.normalize(title)
    return {"original": title, "normalized": normalized}


@router.post("/compare/scan-local")
async def api_scan_local(data: dict):
    """扫描本地目录中的视频文件"""
    directory = data.get("directory", "")
    scanner = LocalMediaScanner()
    videos = scanner.scan_directory(directory)
    return {"directory": directory, "total": len(videos), "videos": videos[:50]}


# ========== 扫描（断点续扫） ==========


@router.post("/scan")
async def trigger_pornhub_resumable_scan(background_tasks: BackgroundTasks,
                                         rescan: bool = Query(False, description="重置 checkpoint 全量重扫")):
    """后台执行 PORNHub 断点续扫（目录级 checkpoint，可反复运行，绝不 600s 掐断）

    仅扫描尚未处理完的目录；重复点击不会重复入库（existing_codes 幂等跳过）。
    rescan=true 时忽略已有 checkpoint，从零全量重扫。
    """
    from app.config.manager import get_config
    cfg = get_config()
    media_dirs = []
    try:
        media_dirs = getattr(cfg.modules.pornhub, "media_dirs", []) or []
    except Exception:
        pass
    if not media_dirs:
        logger.warning("PORNHub 断点续扫被拒绝: 未配置 media_dirs")
        raise HTTPException(status_code=400, detail="PORNHub 模块未配置 media_dirs")

    if _pornhub_scan_lock.locked():
        logger.warning("PORNHub 断点续扫被拒绝: 已有扫描在运行中")
        raise HTTPException(status_code=409, detail="PORNHub 扫描已在运行中")

    logger.info(f"PORNHub 断点续扫已后台启动: rescan={rescan}, media_dirs={media_dirs}")

    async def _run():
        from app.tasks.pornhub_resumable import ResumablePornhubScanner
        try:
            async with _pornhub_scan_lock:
                scanner = ResumablePornhubScanner(media_dirs, batch_size=200, rescan=rescan)
                result = await scanner.scan()
            logger.info(
                f"PORNHub 断点续扫完成: 共发现 {result.get('total', 0)} 文件，"
                f"新增 {result.get('movies_added', 0)}，跳过已处理目录 {result.get('skipped_dirs', 0)}"
            )
        except Exception as e:
            # 后台任务异常必须落日志，否则静默失败无从排查
            logger.error(f"PORNHub 断点续扫异常: {e}", exc_info=True)

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "rescan": rescan,
        "message": "PORNHub 断点续扫已后台启动" + ("（全量重扫）" if rescan else "（仅未完成目录）"),
    }


# ========== 演员 ==========


@router.get("/actors")
async def list_actors():
    """列出 PORNHub 演员列表"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubActor
        from sqlalchemy import select
        stmt = select(PornhubActor).order_by(PornhubActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "nationality": a.nationality,
                 "avatar_url": a.avatar_url, "movie_count": a.movie_count, "source": a.source, "module_type": "pornhub"} for a in actors]
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取 PORNHub 演员详情"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubActor
        from sqlalchemy import select
        stmt = select(PornhubActor).where(PornhubActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"id": actor.id, "name": actor.name, "alias": actor.alias,
                "nationality": actor.nationality,
                "avatar_url": actor.avatar_url, "source": actor.source,
                "module_type": "pornhub",
                "movie_count": actor.movie_count,
                "created_at": str(actor.created_at)}
    finally:
        await session.close()


# ========== 影片 ==========


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20, unscraped_only: bool = Query(False, description="仅列出未刮削的影片"),
    actor: Optional[str] = Query(None, description="按演员名过滤"),
    # 2026-08-08 新增: 详情页跳转筛选参数
    series: Optional[str] = Query(None, description="按系列精确过滤"),
    maker: Optional[str] = Query(None, description="按片商/制作商过滤（匹配 maker 或 studio）"),
    genre: Optional[str] = Query(None, description="按类别过滤（genre 字段包含）"),
    code_prefix: Optional[str] = Query(None, description="番号前缀精确过滤")):
    """列出 PORNHub 模块影片列表"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select, func, or_

        filters = []
        if unscraped_only:
            filters.append(PornhubMovie.status == "pending")
        if actor:
            filters.append(PornhubMovie.actor.like(f"%{actor}%"))
        if series:
            filters.append(PornhubMovie.series == series)
        if maker:
            filters.append(or_(PornhubMovie.maker == maker, PornhubMovie.studio == maker))
        if genre:
            filters.append(PornhubMovie.genre.contains(genre))
        if code_prefix:
            filters.append(PornhubMovie.code.startswith(code_prefix))

        total_stmt = select(func.count(PornhubMovie.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()

        stmt = select(PornhubMovie).order_by(PornhubMovie.created_at.desc()).offset(skip).limit(limit)
        if filters:
            stmt = stmt.where(*filters)
        result = await session.execute(stmt)
        movies = result.scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "source_views": m.source_views, "source_score": m.source_score,
             "uploader": m.uploader, "categories": m.categories,
             "cover_url": m.cover_url, "actor": m.actor,
             "module_type": "pornhub",
             "file_path": m.file_path, "status": m.status}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取 PORNHub 影片详情"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select
        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "original_title": movie.original_title,
            "source_id": movie.source_id, "source_views": movie.source_views,
            "source_score": movie.source_score, "source_downloads": movie.source_downloads,
            "uploader": movie.uploader, "categories": movie.categories,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "actor": movie.actor, "studio": movie.studio,
            "module_type": "pornhub",
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "tags": getattr(movie, "tag", None), "source": movie.source, "source_url": movie.source_url,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
        }
    finally:
        await session.close()


# ========== 封面端点（纯本地查找，不连外网） ==========


@router.get("/movies/{movie_id}/cover/file")
async def get_pornhub_cover_file(movie_id: int):
    """获取 PORNHub 影片封面图片文件"""
    from fastapi.responses import FileResponse, HTMLResponse
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )

    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie

        movie = await session.get(PornhubMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 1) 规范目录：{data_base}/movies/pornhub/{code}/poster.jpg
        if movie.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path("pornhub", movie.code)
                if fast_file_exists(str(p)):
                    ext = _Path(str(p)).suffix.lower()
                    mt = "image/jpeg"
                    if ext == ".png":
                        mt = "image/png"
                    elif ext == ".webp":
                        mt = "image/webp"
                    return FileResponse(str(p), media_type=mt,
                                        headers={"Cache-Control": "public, max-age=86400"})

        # 2) DB 中 cover_url/poster_url/thumb_url 的本地路径
        for attr in ("cover_url", "poster_url", "thumb_url"):
            url = getattr(movie, attr, None)
            if not url:
                continue
            if not url.startswith(("http://", "https://", "/")):
                if fast_file_exists(url):
                    ext = _Path(url).suffix.lower()
                    mt = "image/jpeg"
                    if ext == ".png":
                        mt = "image/png"
                    elif ext == ".webp":
                        mt = "image/webp"
                    return FileResponse(url, media_type=mt,
                                        headers={"Cache-Control": "public, max-age=86400"})

        # 3) 视频目录下
        if movie.file_path:
            try:
                video_dir = _Path(movie.file_path).parent
                for img_name in ["poster.jpg", "poster.png", "cover.jpg", "fanart.jpg", "thumb.jpg"]:
                    img_path = video_dir / img_name
                    if await asyncio.wait_for(
                        asyncio.to_thread(lambda p=img_path: p.exists() and p.is_file()),
                        timeout=3.0,
                    ):
                        ext = _Path(str(img_path)).suffix.lower()
                        mt = "image/jpeg"
                        if ext == ".png":
                            mt = "image/png"
                        elif ext == ".webp":
                            mt = "image/webp"
                        return FileResponse(str(img_path), media_type=mt,
                                            headers={"Cache-Control": "public, max-age=86400"})
            except asyncio.TimeoutError:
                pass

        # 4) SVG 占位图
        placeholder = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360" '
            'viewBox="0 0 240 360"><rect fill="#f0f0f0" width="240" height="360"/>'
            '<text x="120" y="180" text-anchor="middle" fill="#bbb" '
            'font-size="14">暂无封面</text></svg>'
        )
        return HTMLResponse(content=placeholder, media_type="image/svg+xml",
                            headers={"Cache-Control": "no-cache"})
    finally:
        await session.close()


# ========== 刮削 ==========


@router.post("/movies/{movie_id}/scrape")
async def scrape_pornhub_movie(movie_id: int):
    """刮削指定 PORNHub 影片的元数据

    使用 PornhubCrawler 从 pornhub.com 获取元数据，
    然后写入 PORNHub 模块 DB（PornhubMovie + PornhubActor）。
    """
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie, PornhubActor
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        viewkey = movie.code
        if viewkey.startswith("ph"):
            viewkey = viewkey[2:]

        from app.crawlers.pornhub import PornhubCrawler
        crawler = PornhubCrawler()
        scrape_result = await crawler.scrape(movie.code)

        if not scrape_result or not scrape_result.title:
            return {"status": "error", "message": f"刮削失败: 未找到 {movie.code} 的数据"}

        movie.title = scrape_result.title
        movie.original_title = scrape_result.title
        if scrape_result.cover_url:
            movie.cover_url = scrape_result.cover_url
        if scrape_result.duration:
            movie.duration = scrape_result.duration
        if scrape_result.rating:
            movie.source_score = scrape_result.rating
        if scrape_result.votes:
            movie.source_views = scrape_result.votes
        if scrape_result.studio:
            movie.uploader = scrape_result.studio
        if scrape_result.genres:
            movie.categories = ",".join(scrape_result.genres)
        if scrape_result.tags:
            movie.tag = ",".join(scrape_result.tags)
        if scrape_result.plot:
            movie.plot = scrape_result.plot

        if scrape_result.actors:
            actor_names = [a.name for a in scrape_result.actors]
            movie.actor = ",".join(actor_names)

            for actor_info in scrape_result.actors:
                existing = await session.execute(
                    select(PornhubActor).where(PornhubActor.name == actor_info.name)
                )
                db_actor = existing.scalar_one_or_none()
                if db_actor:
                    # 按 movie.actor LIKE 重算，与扫描口径一致，避免重复刮削累加
                    db_actor.movie_count = await _recount_actor_movie_count(session, actor_info.name)
                else:
                    session.add(PornhubActor(
                        name=actor_info.name,
                        source="scraper",
                        movie_count=1,
                    ))

        movie.status = "scraped"
        movie.source = "pornhub"
        await session.commit()

        return {
            "status": "ok",
            "message": f"刮削成功: {scrape_result.title}",
            "actors": [a.name for a in scrape_result.actors] if scrape_result.actors else [],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PORNHub 刮削失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/scrape-all-pending")
async def scrape_all_pending_pornhub(background_tasks: BackgroundTasks):
    """后台批量刮削所有 status=pending 的 PORNHub 影片"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.status == "pending").order_by(PornhubMovie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待刮削的影片", "total": 0}

    async def _run():
        from app.crawlers.pornhub import PornhubCrawler
        from app.db.pornhub_models import PornhubMovie, PornhubActor
        from sqlalchemy import select

        crawler = PornhubCrawler()
        success = 0
        failed = 0
        for m in pending:
            try:
                result = await crawler.scrape(m.code)
                if result and result.title:
                    s = await db.get_session()
                    try:
                        st = select(PornhubMovie).where(PornhubMovie.id == m.id)
                        r = await s.execute(st)
                        mv = r.scalar_one_or_none()
                        if mv:
                            mv.title = result.title
                            if result.cover_url:
                                mv.cover_url = result.cover_url
                            if result.duration:
                                mv.duration = result.duration
                            if result.rating:
                                mv.source_score = result.rating
                            if result.votes:
                                mv.source_views = result.votes
                            if result.studio:
                                mv.uploader = result.studio
                            if result.genres:
                                mv.categories = ",".join(result.genres)
                            if result.tags:
                                mv.tag = ",".join(result.tags)
                            if result.actors:
                                mv.actor = ",".join(a.name for a in result.actors)
                                for ai in result.actors:
                                    ex = await s.execute(select(PornhubActor).where(PornhubActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if a:
                                        # 按 movie.actor LIKE 重算，与扫描/单部刮削口径一致
                                        a.movie_count = await _recount_actor_movie_count(s, ai.name)
                                    else:
                                        s.add(PornhubActor(name=ai.name, source="scraper", movie_count=1))
                            mv.status = "scraped"
                            mv.source = "pornhub"
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"刮削失败 {m.code}: {e}")
                failed += 1
        logger.info(f"PORNHub 批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "total": len(pending),
        "message": f"PORNHub 批量刮削已启动，共 {len(pending)} 部待刮削影片",
    }


# ========== 演员资料刮削 ==========


@router.post("/actors/{actor_id}/scrape-profile")
async def scrape_pornhub_actor_profile(actor_id: int):
    """刮削单个 PORNHub 演员的个人资料和头像"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubActor
        from sqlalchemy import select

        stmt = select(PornhubActor).where(PornhubActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        from app.scraper.pornhub_actor_scraper import scrape_actor_profile
        profile = await scrape_actor_profile(actor.name, actor.nationality)

        if not profile:
            # 通过 JavDB 搜索获取头像并落盘
            avatar_url = await _scrape_avatar_from_javdb(actor.name)
            await _store_pornhub_actor_avatar(actor, avatar_url, actor.name)
            await session.commit()
            return {"status": "partial", "message": f"未找到演员 {actor.name} 的详细资料，已尝试获取头像"}

        actor.alias = profile.alias or actor.alias
        # 头像：下载到本地并落盘 actor_{id}.jpg（与模块端点读取一致）
        await _store_pornhub_actor_avatar(actor, profile.avatar_url, actor.name)
        # 国籍：优先用文件夹提取的，如果 profile 有 country 且数据库为空则补充
        if profile.country and not actor.nationality:
            actor.nationality = profile.country

        await session.commit()

        return {
            "status": "ok",
            "message": f"演员 {actor.name} 资料刮削成功",
            "profile": {
                "name": profile.name,
                "alias": profile.alias,
                "avatar_url": profile.avatar_url,
                "birth_date": profile.birth_date,
                "height": profile.height,
                "measurements": profile.measurements,
                "birthplace": profile.birthplace,
                "country": profile.country,
                "ethnicity": profile.ethnicity,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"演员资料刮削失败 [{actor_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/actors/scrape-all-profiles")
async def scrape_all_pornhub_actor_profiles(background_tasks: BackgroundTasks):
    """后台批量刮削所有 PORNHub 演员的个人资料"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubActor
        from sqlalchemy import select
        stmt = select(PornhubActor).where(PornhubActor.source != "manual").order_by(PornhubActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
    finally:
        await session.close()

    if not actors:
        return {"status": "ok", "message": "没有演员需要刮削", "total": 0}

    async def _run():
        from app.db.pornhub_models import PornhubActor
        from app.scraper.pornhub_actor_scraper import scrape_actor_profile
        from sqlalchemy import select

        success = 0
        failed = 0
        for a in actors:
            try:
                profile = await scrape_actor_profile(a.name, a.nationality)
                s = await db.get_session()
                try:
                    st = select(PornhubActor).where(PornhubActor.id == a.id)
                    r = await s.execute(st)
                    act = r.scalar_one_or_none()
                    if act:
                        if profile:
                            if profile.alias:
                                act.alias = profile.alias
                            await _store_pornhub_actor_avatar(act, profile.avatar_url, act.name)
                            if profile.country and not act.nationality:
                                act.nationality = profile.country
                        else:
                            avatar_url = await _scrape_avatar_from_javdb(act.name)
                            await _store_pornhub_actor_avatar(act, avatar_url, act.name)
                        await s.commit()
                        success += 1
                finally:
                    await s.close()
            except Exception as e:
                logger.debug(f"演员资料刮削失败 {a.name}: {e}")
                failed += 1
            await asyncio.sleep(0.5)
        logger.info(f"PORNHub 演员资料批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "total": len(actors),
        "message": f"PORNHub 演员资料批量刮削已启动，共 {len(actors)} 位演员",
    }


async def _scrape_avatar_from_javdb(actor_name: str) -> str | None:
    """从 JavDB 搜索演员头像"""
    try:
        from app.utils.http_client import AsyncHttpClient
        from urllib.parse import quote
        import re

        search_url = f"https://javdb.com/search?q={quote(actor_name)}&f=actor"
        async with AsyncHttpClient(timeout=15) as client:
            html = await client.get_text(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://javdb.com/",
            })
            if not html:
                return None

            # 查找演员头像链接
            m = re.search(r'<img[^>]*class="[^"]*avatar[^"]*"[^>]*src="([^"]+)"', html, re.I)
            if m:
                return m.group(1)
            # 兜底：找第一个演员卡片里的图片
            m2 = re.search(r'<div[^>]*class="[^"]*actor[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"', html, re.I | re.DOTALL)
            if m2:
                return m2.group(1)
            return None
    except Exception as e:
        logger.debug(f"JavDB 头像搜索失败 [{actor_name}]: {e}")
        return None


# ========== 视频截图生成封面 ==========


@router.post("/movies/{movie_id}/generate-cover")
async def generate_pornhub_movie_cover(movie_id: int):
    """从视频文件截取一帧作为封面"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select
        from app.config.manager import DATA_DIR
        import subprocess

        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        file_path = movie.file_path
        if not file_path or not Path(file_path).exists():
            return {"status": "error", "message": f"视频文件不存在: {file_path}"}

        from app.utils.bin_tools import get_ffmpeg_path
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg or not Path(ffmpeg).exists():
            return {"status": "error", "message": "ffmpeg 未找到，无法生成截图"}

        output_dir = DATA_DIR / "movies" / "pornhub" / movie.code
        output_dir.mkdir(parents=True, exist_ok=True)
        cover_path = output_dir / "poster.jpg"

        # 用 ffmpeg 在视频 30% 位置截取一帧
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-ss", "00:00:05",
                "-i", file_path,
                "-vframes", "1",
                "-vf", "scale=480:-1",
                str(cover_path),
            ],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )

        if result.returncode != 0 or not cover_path.exists():
            # 回退：截取第一帧
            result2 = subprocess.run(
                [
                    ffmpeg, "-y",
                    "-i", file_path,
                    "-vframes", "1",
                    "-vf", "scale=480:-1",
                    str(cover_path),
                ],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            if result2.returncode != 0 or not cover_path.exists():
                return {"status": "error", "message": "截图生成失败"}

        movie.cover_url = str(cover_path)
        movie.poster_url = str(cover_path)
        await session.commit()

        return {
            "status": "ok",
            "message": f"封面截图已生成: {cover_path}",
            "cover_url": str(cover_path),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"截图生成失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/generate-all-covers")
async def generate_all_pornhub_covers(background_tasks: BackgroundTasks):
    """后台批量生成所有 pending 影片的视频截图封面"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.status == "pending").order_by(PornhubMovie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待生成封面的影片", "total": 0}

    async def _run():
        from app.db.pornhub_models import PornhubMovie
        from app.config.manager import DATA_DIR
        from app.utils.bin_tools import get_ffmpeg_path
        from sqlalchemy import select
        import subprocess

        ffmpeg = get_ffmpeg_path()
        if not ffmpeg or not Path(ffmpeg).exists():
            logger.error("ffmpeg 未找到，无法批量生成封面")
            return

        success = 0
        failed = 0
        for m in pending:
            try:
                if not m.file_path or not Path(m.file_path).exists():
                    failed += 1
                    continue

                output_dir = DATA_DIR / "movies" / "pornhub" / m.code
                output_dir.mkdir(parents=True, exist_ok=True)
                cover_path = output_dir / "poster.jpg"

                result = subprocess.run(
                    [ffmpeg, "-y", "-ss", "00:00:05", "-i", m.file_path,
                     "-vframes", "1", "-vf", "scale=480:-1", str(cover_path)],
                    capture_output=True, text=True, timeout=60,
                    encoding="utf-8", errors="replace",
                )

                if result.returncode != 0 or not cover_path.exists():
                    result = subprocess.run(
                        [ffmpeg, "-y", "-i", m.file_path,
                         "-vframes", "1", "-vf", "scale=480:-1", str(cover_path)],
                        capture_output=True, text=True, timeout=60,
                        encoding="utf-8", errors="replace",
                    )
                    if result.returncode != 0 or not cover_path.exists():
                        failed += 1
                        continue

                s = await db.get_session()
                try:
                    st = select(PornhubMovie).where(PornhubMovie.id == m.id)
                    r = await s.execute(st)
                    mv = r.scalar_one_or_none()
                    if mv:
                        mv.cover_url = str(cover_path)
                        mv.poster_url = str(cover_path)
                        await s.commit()
                        success += 1
                finally:
                    await s.close()

            except Exception as e:
                logger.debug(f"截图失败 {m.code}: {e}")
                failed += 1

        logger.info(f"PORNHub 截图封面批量生成完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "total": len(pending),
        "message": f"PORNHub 截图封面批量生成已启动，共 {len(pending)} 部待处理影片",
    }


# ========== 完整工作流 ==========


@router.post("/movies/generate-cover-enhanced/{movie_id}")
async def generate_pornhub_movie_cover_enhanced(movie_id: int, width: int = Query(480, ge=200, le=1920), quality: int = Query(85, ge=10, le=100)):
    """增强版封面生成：20%-80% 区间多帧采样 + 最优帧选择

    - 在视频时长的 20%-80% 区间均匀取 3 帧
    - 通过清晰度、亮度、色彩综合评分选择最优帧
    - 输出为 {原视频名}_cover.jpg
    """
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        file_path = movie.file_path
        if not file_path or not Path(file_path).exists():
            return {"status": "error", "message": f"视频文件不存在: {file_path}"}

        # 封面输出到视频同目录，命名: {原视频名}_cover.jpg
        video_dir = Path(file_path).parent
        cover_name = Path(file_path).stem

        from app.utils.pornhub_cover_generator import generate_cover
        result_data = await generate_cover(
            video_path=file_path,
            output_dir=str(video_dir),
            cover_name=cover_name,
            width=width,
            quality=quality,
            sample_points=3,
            sample_range=(0.2, 0.8),
            force=False,
        )

        if result_data["status"] == "ok":
            # 更新数据库封面路径
            movie.cover_url = result_data["cover_path"]
            movie.poster_url = result_data["cover_path"]
            movie.status = "scraped"
            await session.commit()
            logger.info("增强封面已更新 DB: %s -> %s", movie.code, result_data["cover_path"])

        result_data["movie_code"] = movie.code
        return result_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"增强封面生成失败 [{movie_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/generate-all-covers-enhanced")
async def generate_all_pornhub_covers_enhanced(background_tasks: BackgroundTasks):
    """后台批量增强封面生成（所有 pending 影片）"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.status == "pending").order_by(PornhubMovie.id.desc())
        result = await session.execute(stmt)
        pending = result.scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待生成封面的影片", "total": 0}

    async def _run():
        from app.db.pornhub_models import PornhubMovie
        from app.utils.pornhub_cover_generator import generate_cover

        db_inner = get_pornhub_db()
        s = await db_inner.get_session()
        total = len(pending)
        success = 0
        failed = 0
        try:
            for i, mv in enumerate(pending):
                if not mv.file_path or not Path(mv.file_path).exists():
                    failed += 1
                    continue

                video_dir = Path(mv.file_path).parent
                cover_name = Path(mv.file_path).stem

                result_data = await generate_cover(
                    video_path=mv.file_path,
                    output_dir=str(video_dir),
                    cover_name=cover_name,
                    width=480,
                    quality=85,
                )

                if result_data["status"] == "ok":
                    # 重新从本会话取出受管实例，避免操作已关闭会话的游离对象导致写入丢失
                    movie_row = (await s.execute(
                        select(PornhubMovie).where(PornhubMovie.id == mv.id)
                    )).scalar_one_or_none()
                    if movie_row:
                        movie_row.cover_url = result_data["cover_path"]
                        movie_row.poster_url = result_data["cover_path"]
                        movie_row.status = "scraped"
                    success += 1
                    logger.info("[%d/%d] 封面已生成: %s", i + 1, total, mv.code)
                else:
                    failed += 1
                    logger.warning("[%d/%d] 封面生成失败: %s - %s", i + 1, total, mv.code, result_data.get("message"))

                if (i + 1) % 5 == 0:
                    await s.commit()

            await s.commit()
        finally:
            await s.close()

        logger.info("批量封面生成完成: 成功 %d, 失败 %d, 总计 %d", success, failed, total)

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "message": f"已启动 {len(pending)} 部影片的批量封面生成",
        "total": len(pending),
    }


@router.post("/actors/scrape-profile-enhanced/{actor_id}")
async def scrape_actor_profile_enhanced(actor_id: int):
    """增强版演员资料刮削（更多字段 + 头像下载到本地）"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubActor
        from sqlalchemy import select

        stmt = select(PornhubActor).where(PornhubActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")

        from app.scraper.pornhub_actor_scraper import (
            scrape_actor_profile,
            download_actor_avatar,
            check_profile_completeness,
        )

        profile = await scrape_actor_profile(actor.name, actor.nationality)

        if not profile:
            return {"status": "error", "message": f"未找到演员 {actor.name} 的任何资料"}

        # 更新数据库
        updates = {}
        if profile.alias:
            actor.alias = profile.alias
            updates["alias"] = profile.alias
        if profile.country and not actor.nationality:
            actor.nationality = profile.country
            updates["nationality"] = profile.country

        # 头像：下载到本地并落盘 actor_{id}.jpg（与模块端点读取一致）
        local_avatar = await _store_pornhub_actor_avatar(actor, profile.avatar_url, actor.name)
        if local_avatar:
            updates["avatar_url"] = local_avatar

        await session.commit()

        completeness = check_profile_completeness(profile)

        return {
            "status": "ok",
            "message": f"演员 {actor.name} 资料刮削成功",
            "profile": {
                "name": profile.name,
                "alias": profile.alias,
                "avatar_url": profile.avatar_url,
                "avatar_local": local_avatar,
                "birth_date": profile.birth_date,
                "debut_year": profile.debut_year,
                "height": profile.height,
                "measurements": profile.measurements,
                "birthplace": profile.birthplace,
                "country": profile.country,
                "ethnicity": profile.ethnicity,
                "movie_count": profile.movie_count,
                "video_count": profile.video_count,
                "photo_count": profile.photo_count,
                "rank": profile.rank,
                "profile_url": profile.profile_url,
            },
            "completeness": completeness,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"演员增强资料刮削失败 [{actor_id}]: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/actors/scrape-all-profiles-enhanced")
async def scrape_all_actor_profiles_enhanced(background_tasks: BackgroundTasks):
    """后台批量增强版演员资料刮削（完整资料 + 头像下载）"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubActor
        from sqlalchemy import select

        stmt = select(PornhubActor).where(PornhubActor.source != "manual").order_by(PornhubActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
    finally:
        await session.close()

    if not actors:
        return {"status": "ok", "message": "没有演员需要刮削", "total": 0}

    async def _run():
        from app.db.pornhub_models import PornhubActor
        from app.scraper.pornhub_actor_scraper import (
            scrape_actor_profile,
            download_actor_avatar,
            check_profile_completeness,
            AVATAR_DIR,
        )

        db_inner = get_pornhub_db()
        s = await db_inner.get_session()
        total = len(actors)
        success = 0
        skipped = 0
        failed = 0
        error_log = []

        try:
            for i, actor_row in enumerate(actors):
                # 去重校验：如果资料完整且已有头像本地文件，跳过（按名或按 id 命名均可）
                safe_name = re.sub(r'[\\/:*?"<>|]', '_', actor_row.name)
                name_local = Path(AVATAR_DIR) / f"{safe_name}.jpg"
                id_local = Path(AVATAR_DIR) / f"actor_{actor_row.id}.jpg"
                if actor_row.avatar_url and actor_row.nationality and (name_local.exists() or id_local.exists()):
                    skipped += 1
                    continue

                try:
                    profile = await scrape_actor_profile(actor_row.name, actor_row.nationality)

                    # 重新从本会话取出受管实例，避免操作已关闭会话的游离对象导致写入丢失
                    act = (await s.execute(
                        select(PornhubActor).where(PornhubActor.id == actor_row.id)
                    )).scalar_one_or_none()
                    if not act:
                        failed += 1
                        error_log.append({"name": actor_row.name, "error": "演员记录不存在"})
                        continue

                    if profile:
                        if profile.alias:
                            act.alias = profile.alias
                        await _store_pornhub_actor_avatar(act, profile.avatar_url, act.name)
                        if profile.country and not act.nationality:
                            act.nationality = profile.country

                        completeness = check_profile_completeness(profile)
                        logger.info(
                            "[%d/%d] %s: 资料获取成功 (完整度 %d%%)",
                            i + 1, total, act.name, completeness["completeness"]
                        )
                        success += 1
                    else:
                        failed += 1
                        error_log.append({
                            "name": actor_row.name,
                            "error": "刮削返回空",
                        })
                        logger.warning("[%d/%d] %s: 刮削失败", i + 1, total, actor_row.name)

                    if (i + 1) % 5 == 0:
                        await s.commit()
                        await asyncio.sleep(0.3)

                except Exception as e:
                    failed += 1
                    error_log.append({"name": actor_row.name, "error": str(e)})
                    logger.error("[%d/%d] %s: 异常 - %s", i + 1, total, actor_row.name, e)

            await s.commit()
        finally:
            await s.close()

        logger.info("批量演员刮削完成: 成功 %d, 跳过 %d, 失败 %d, 总计 %d", success, skipped, failed, total)
        if error_log:
            logger.warning("刮削失败的演员: %s", error_log)

    background_tasks.add_task(_run)

    return {
            "status": "started",
            "message": f"已启动 {len(actors)} 个演员的批量资料刮削",
            "total": len(actors),
        }


@router.post("/workflow/run-all")
async def run_pornhub_full_workflow(background_tasks: BackgroundTasks):
    """完整工作流：扫描目录 → 刮削影片 → 下载演员头像 → 生成截图封面"""
    async def _run():
        from app.config.manager import get_config
        from app.db.pornhub_models import PornhubMovie, PornhubActor
        from sqlalchemy import select

        cfg = get_config()
        media_dirs = cfg.modules.pornhub.media_dirs if hasattr(cfg, 'modules') and hasattr(cfg.modules, 'pornhub') else []

        if not media_dirs:
            logger.warning("PORNHub 模块未配置 media_dirs，跳过扫描")
            return

        # 1. 扫描目录
        logger.info("PORNHub 工作流：开始扫描目录")
        from app.tasks.pornhub_scanner import PornhubScanner
        scanner = PornhubScanner(media_dirs)
        scan_result = await scanner.scan()
        logger.info(f"PORNHub 工作流：扫描完成，新增 {scan_result.get('movies_added', 0)} 部影片")

        # 2. 刮削演员资料（头像 + 国籍）
        db = get_pornhub_db()
        from app.scraper.pornhub_actor_scraper import scrape_actor_profile, download_actor_avatar

        s = await db.get_session()
        try:
            actors = await s.execute(select(PornhubActor))
            for actor_row in actors.scalars().all():
                if actor_row.avatar_url and actor_row.nationality:
                    continue
                try:
                    profile = await scrape_actor_profile(actor_row.name, actor_row.nationality)
                    if profile:
                        await _store_pornhub_actor_avatar(actor_row, profile.avatar_url, actor_row.name)
                        if profile.country and not actor_row.nationality:
                            actor_row.nationality = profile.country
                    else:
                        avatar_url = await _scrape_avatar_from_javdb(actor_row.name)
                        await _store_pornhub_actor_avatar(actor_row, avatar_url, actor_row.name)
                    await s.commit()
                    logger.info(f"PORNHub 工作流：演员资料已获取 {actor_row.name}")
                except Exception as e:
                    logger.debug(f"演员资料获取失败 {actor_row.name}: {e}")
                await asyncio.sleep(0.3)
        finally:
            await s.close()

        # 3. 生成视频截图封面（增强版：多帧采样 + 最优帧选择）
        from app.utils.pornhub_cover_generator import generate_cover

        s2 = await db.get_session()
        try:
            pending_movies = await s2.execute(
                select(PornhubMovie).where(PornhubMovie.status == "pending")
            )
            for mv in pending_movies.scalars().all():
                if not mv.file_path or not Path(mv.file_path).exists():
                    continue
                try:
                    video_dir = Path(mv.file_path).parent
                    cover_name = Path(mv.file_path).stem
                    result_data = await generate_cover(
                        video_path=mv.file_path,
                        output_dir=str(video_dir),
                        cover_name=cover_name,
                        width=480,
                        quality=85,
                    )
                    if result_data["status"] == "ok":
                        mv.cover_url = result_data["cover_path"]
                        mv.poster_url = result_data["cover_path"]
                        mv.status = "scraped"
                        await s2.commit()
                except Exception as e:
                    logger.debug(f"截图失败 {mv.code}: {e}")
        finally:
            await s2.close()

        logger.info("PORNHub 工作流：全部完成")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "message": "PORNHub 完整工作流已启动（扫描目录 → 刮削演员 → 生成封面）",
    }


# ========== 播放端点 ==========


@router.get("/movies/{movie_id}/play")
async def play_pornhub_movie(movie_id: int):
    """获取 PORNHub 影片播放信息"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
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
async def play_pornhub_video_file(movie_id: int, request: _Request):
    """PORNHub 影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
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
async def get_pornhub_external_play_url(movie_id: int, request: _Request, protocol: str = "http"):
    """获取 PORNHub 影片外部播放地址"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select

        stmt = select(PornhubMovie).where(PornhubMovie.id == movie_id)
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
            play_url = f"{base}/api/v1/pornhub/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
