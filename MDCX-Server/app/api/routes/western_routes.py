"""
欧美模块 API 路由

参考来源：
- 现有: chinese_routes.py (路由模式)
- P0: CommunityScrapers/scrapers/IAFD/IAFD.py (演员数据来源)

整合说明：
- 路由框架: 沿用 MDCX 模块路由模式
- 演员数据: 支持 IAFD/ThePornDB 来源
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request as _Request

from app.db.module_db import ModuleDatabase

import os as _os
from pathlib import Path as _Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/western", tags=["欧美模块"])


def get_western_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("western")


@router.get("/movies")
async def list_movies(
    skip: int = 0,
    limit: int = 20,
    keyword: Optional[str] = Query(None, description="搜索标题/演员"),
    actor: Optional[str] = Query(None, description="按演员名过滤"),
    # 2026-08-08 新增: 详情页跳转筛选参数
    series: Optional[str] = Query(None, description="按系列精确过滤"),
    maker: Optional[str] = Query(None, description="按片商/制作商过滤（匹配 maker 或 studio）"),
    genre: Optional[str] = Query(None, description="按类别过滤（genre 字段包含）"),
    code_prefix: Optional[str] = Query(None, description="番号前缀精确过滤"),
):
    """列出欧美影片"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select, func, or_

        filters = []
        if keyword:
            kw = f"%{keyword.replace('%', '').replace('_', '')}%"
            filters.append(or_(WesternMovie.title.like(kw), WesternMovie.actors.like(kw), WesternMovie.site.like(kw)))
        if actor:
            safe_actor = actor.replace('%', '').replace('_', '')
            filters.append(WesternMovie.actors.like(f"%{safe_actor}%"))
        if series:
            filters.append(WesternMovie.series == series)
        if maker:
            filters.append(or_(WesternMovie.maker == maker, WesternMovie.studio == maker))
        if genre:
            filters.append(WesternMovie.genre.contains(genre))
        if code_prefix:
            filters.append(WesternMovie.code.startswith(code_prefix))

        total_stmt = select(func.count(WesternMovie.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total = (await session.execute(total_stmt)).scalar() or 0

        stmt = select(WesternMovie)
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.order_by(WesternMovie.created_at.desc()).offset(skip).limit(limit)
        movies = (await session.execute(stmt)).scalars().all()

        pending_stmt = select(func.count(WesternMovie.id)).where(WesternMovie.status == "pending")
        pending_count = (await session.execute(pending_stmt)).scalar() or 0

        return {"total": total, "pending_count": pending_count, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "site": m.site, "network": m.network, "studio": m.studio,
             "cover_url": m.cover_url, "file_path": m.file_path,
             "module_type": "western",
             "status": m.status, "release_date": m.release_date}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取欧美影片详情"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select
        movie = (await session.execute(select(WesternMovie).where(WesternMovie.id == movie_id))).scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "original_title": movie.original_title,
            "site": movie.site, "network": movie.network, "studio": movie.studio,
            "cover_url": movie.cover_url, "poster_url": movie.poster_url,
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "genre": movie.genre, "tag": movie.tag, "actors": movie.actors,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "module_type": "western",
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "source": movie.source,
            "source_url": movie.source_url,
            "created_at": str(movie.created_at),
        }
    finally:
        await session.close()


# ========== 封面端点（纯本地查找，不连外网） ==========


@router.get("/movies/{movie_id}/cover/file")
async def get_western_cover_file(movie_id: int):
    """获取欧美影片封面图片文件"""
    from fastapi.responses import FileResponse, HTMLResponse
    from app.utils.media_helpers import (
        fast_file_exists,
        get_movie_cover_path,
        get_movie_fanart_path,
        get_movie_thumb_path,
    )

    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie

        movie = await session.get(WesternMovie, movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 1) 规范目录：{data_base}/movies/western/{code}/poster.jpg
        if movie.code:
            for get_path in (get_movie_cover_path, get_movie_fanart_path, get_movie_thumb_path):
                p = get_path("western", movie.code)
                if fast_file_exists(str(p)):
                    ext = _Path(str(p)).suffix.lower()
                    mt = "image/jpeg"
                    if ext == ".png":
                        mt = "image/png"
                    elif ext == ".webp":
                        mt = "image/webp"
                    return FileResponse(str(p), media_type=mt,
                                        headers={"Cache-Control": "public, max-age=86400"})

        # 2) DB 中 cover_url/poster_url/thumb_url
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
            elif movie.code:
                target_path = get_movie_cover_path("western", movie.code)
                try:
                    from app.utils.media_helpers import download_image_to_local
                    saved_path = await download_image_to_local(url, target_path)
                    if saved_path and fast_file_exists(saved_path):
                        ext = _Path(saved_path).suffix.lower()
                        mt = "image/jpeg"
                        if ext == ".png":
                            mt = "image/png"
                        elif ext == ".webp":
                            mt = "image/webp"
                        return FileResponse(saved_path, media_type=mt,
                                            headers={"Cache-Control": "public, max-age=86400"})
                except Exception:
                    pass

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


@router.get("/actors")
async def list_actors():
    """列出欧美演员"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternActor
        from sqlalchemy import select
        stmt = select(WesternActor).order_by(WesternActor.movie_count.desc())
        actors = (await session.execute(stmt)).scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count,
                 "source": a.source, "avatar_url": a.avatar_url,
                 "gender": a.gender, "country": a.country,
                 "module_type": "western"}
                for a in actors]
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取欧美演员详情"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternActor
        from sqlalchemy import select
        actor = (await session.execute(select(WesternActor).where(WesternActor.id == actor_id))).scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {
            "id": actor.id, "name": actor.name, "alias": actor.alias,
            "avatar_url": actor.avatar_url, "source": actor.source,
            "gender": actor.gender, "birthdate": actor.birthdate,
            "country": actor.country, "ethnicity": actor.ethnicity,
            "measurements": actor.measurements, "height": actor.height,
            "weight": actor.weight, "twitter": actor.twitter,
            "instagram": actor.instagram, "movie_count": actor.movie_count,
            "module_type": "western",
        }
    finally:
        await session.close()


@router.post("/scan")
async def scan_media():
    """扫描欧美媒体目录"""
    from app.config.manager import get_config
    config = get_config()
    media_dirs = getattr(config.modules.western, "media_dirs", []) if hasattr(config, "modules") else []
    if not media_dirs:
        raise HTTPException(status_code=400, detail="未配置媒体目录")
    from app.tasks.western_scanner import WesternScanner
    scanner = WesternScanner(media_dirs)
    result = await scanner.scan()
    return result


# ========== 刮削 ==========


@router.post("/movies/{movie_id}/scrape")
async def scrape_western_movie(movie_id: int):
    """刮削指定欧美影片的元数据

    使用 Western 爬虫的 search 功能按关键词搜索，
    获取元数据后写入模块 DB。
    """
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie, WesternActor
        from sqlalchemy import select

        movie = (await session.execute(select(WesternMovie).where(WesternMovie.id == movie_id))).scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")

        # 用标题作为关键词搜索
        keyword = movie.title or ""
        if not keyword:
            return {"status": "error", "message": "影片无标题，无法搜索"}

        # 提取更精确的搜索关键词：去掉频道名/品牌前缀，取核心标题
        # 例: "Anna Ralphs - [Hegre.com] - [2023] - Cum Inside Me" → "Anna Ralphs Cum Inside Me"
        # 例: "Blacked.19.10.12.Lana.Sharapova.4k-C" → "Blacked Lana Sharapova"
        import re as _re
        clean_title = _re.sub(r'\[.*?\]', '', keyword)  # 去掉 [xxx] 内容
        clean_title = _re.sub(r'[-_]\s*[0-9]+[kK]', '', clean_title)  # 去掉 -4K, -1080p 等
        clean_title = _re.sub(r'-C$', '', clean_title)  # 去掉尾部 -C（中文版标记）
        clean_title = clean_title.replace('.', ' ').replace('_', ' ').replace('  ', ' ').strip()
        if clean_title:
            keyword = clean_title

        # 尝试多个 Western 爬虫搜索（带超时控制，避免某个爬虫卡死）
        # 优先 WesternAggregateCrawler（内含 IAFD 全网搜索 + ThePornDB + Aylo）
        from app.crawlers.western_aggregate import WesternAggregateCrawler
        from app.crawlers.western.vixen_network import VixenNetworkCrawler
        from app.crawlers.western.naughtyamerica import NaughtyAmericaCrawler

        scrapers = [
            (WesternAggregateCrawler(), 25),
            (VixenNetworkCrawler(), 10),
            (NaughtyAmericaCrawler(), 5),
        ]

        matched_result = None
        for scraper, timeout in scrapers:
            try:
                results = await asyncio.wait_for(scraper.search(keyword), timeout=timeout)
                if results:
                    matched_result = results[0]
                    break
            except asyncio.TimeoutError:
                logger.debug(f"Western 爬虫 {scraper.name} 超时 ({timeout}s)")
                continue
            except Exception:
                continue

        if not matched_result:
            return {"status": "error", "message": f"未找到 {keyword} 的匹配数据"}

        # 写入模块 DB
        from app.utils.media_helpers import ensure_movie_media_local, ensure_actor_avatar_local
        from app.output.nfo import NFOGenerator
        old_actors = movie.actors.split(",") if movie.actors else []
        movie.title = matched_result.title
        movie.original_title = matched_result.original_title or matched_result.title
        local_media = await ensure_movie_media_local(
            module_name="western", code=movie.code,
            cover_url=matched_result.cover_url,
            fanart_url=getattr(matched_result, "poster_url", None) or getattr(matched_result, "fanart_url", None),
            thumb_url=getattr(matched_result, "thumb_url", None),
            referer=matched_result.cover_url,
        )
        if local_media.get("cover"):
            movie.cover_url = local_media["cover"]
        elif matched_result.cover_url:
            movie.cover_url = matched_result.cover_url
        if local_media.get("fanart"):
            movie.poster_url = local_media["fanart"]
        elif matched_result.poster_url:
            movie.poster_url = matched_result.poster_url
        if local_media.get("thumb"):
            movie.thumb_url = local_media["thumb"]
        if matched_result.studio:
            movie.studio = matched_result.studio
        if matched_result.rating:
            try:
                movie.rating = float(matched_result.rating)
            except (ValueError, TypeError):
                pass
        if matched_result.duration:
            movie.duration = matched_result.duration
        if matched_result.release_date:
            rd = str(matched_result.release_date)
            movie.release_date = rd[:10] if len(rd) > 10 else rd
        if matched_result.plot:
            movie.plot = matched_result.plot[:2000] if len(matched_result.plot) > 2000 else matched_result.plot
        if matched_result.genres:
            movie.genre = ",".join(matched_result.genres)
        if matched_result.tags:
            movie.tag = ",".join(matched_result.tags)

        # 演员
        if matched_result.actors:
            new_actor_names = set()
            actor_names = [a.name for a in matched_result.actors]
            movie.actors = ",".join(actor_names)
            from app.db.western_models import WesternActor
            for ai in matched_result.actors:
                new_actor_names.add(ai.name)
                actor_stmt = select(WesternActor).where(WesternActor.name == ai.name)
                actor_result = await session.execute(actor_stmt)
                existing_actor = actor_result.scalar_one_or_none()
                if not existing_actor:
                    new_actor = WesternActor(name=ai.name, source="scraper", movie_count=1)
                    session.add(new_actor)
                    if getattr(ai, "avatar_url", None):
                        local_avatar = await ensure_actor_avatar_local(ai.name, ai.avatar_url)
                        if local_avatar:
                            new_actor.avatar_url = local_avatar
                else:
                    if existing_actor.movie_count < 100:
                        existing_actor.movie_count += 1
                    if not existing_actor.avatar_url and getattr(ai, "avatar_url", None):
                        local_avatar = await ensure_actor_avatar_local(ai.name, ai.avatar_url)
                        existing_actor.avatar_url = local_avatar or ai.avatar_url
            remove_count = 0
            for name in old_actors:
                n = name.strip()
                if n and n not in new_actor_names:
                    actor_stmt = select(WesternActor).where(WesternActor.name == n)
                    actor_result = await session.execute(actor_stmt)
                    actor_obj = actor_result.scalar_one_or_none()
                    if actor_obj and actor_obj.movie_count > 0:
                        actor_obj.movie_count -= 1
                        if remove_count < 30:
                            remove_count += 1
        movie.status = "scraped"
        movie.source = matched_result.source
        await session.commit()
        mv_dir = None
        if hasattr(movie, "output_dir") and movie.output_dir:
            mv_dir = str(movie.output_dir)
        elif hasattr(movie, "file_path") and movie.file_path:
            mv_dir = _os.path.dirname(str(movie.file_path))
        try:
            if mv_dir and _os.path.isdir(mv_dir):
                actor_names = [a.strip() for a in (movie.actor or "").split(",") if a.strip()]
                NFOGenerator(output_dir=mv_dir).generate_from_movie(
                    movie, movie_dir=None, kodi_compatible=True, actor_names=actor_names
                )
        except Exception as nfo_err:
            logger.debug(f"Western NFO 生成失败 [{movie.code}]: {nfo_err}")
        return {
            "status": "ok",
            "message": f"刮削成功: {matched_result.title}",
            "source": matched_result.source,
            "actors": actor_names if matched_result.actors else [],
        }

    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await session.close()


@router.post("/movies/scrape-all-pending")
async def scrape_all_pending_western(background_tasks: BackgroundTasks):
    """后台批量刮削所有 status=pending 的欧美影片"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select
        pending = (await session.execute(
            select(WesternMovie).where(WesternMovie.status == "pending").order_by(WesternMovie.id.desc())
        )).scalars().all()
    finally:
        await session.close()

    if not pending:
        return {"status": "ok", "message": "没有待刮削的影片", "total": 0}

    async def _run():
        from app.db.western_models import WesternMovie, WesternActor
        from app.utils.media_helpers import ensure_movie_media_local, ensure_actor_avatar_local
        from app.output.nfo import NFOGenerator
        from sqlalchemy import select
        from app.crawlers.western_aggregate import WesternAggregateCrawler
        from app.crawlers.western.vixen_network import VixenNetworkCrawler
        from app.crawlers.western.naughtyamerica import NaughtyAmericaCrawler

        scrapers = [
            (WesternAggregateCrawler(), 25),
            (VixenNetworkCrawler(), 10),
            (NaughtyAmericaCrawler(), 5),
        ]
        success = 0
        failed = 0
        for m in pending:
            keyword = m.title or ""
            if not keyword:
                failed += 1
                continue
            import re as _re
            clean_title = _re.sub(r'\[.*?\]', '', keyword)
            clean_title = _re.sub(r'[-_]\s*[0-9]+[kK]', '', clean_title)
            clean_title = _re.sub(r'-C$', '', clean_title)
            clean_title = clean_title.replace('.', ' ').replace('_', ' ').replace('  ', ' ').strip()
            search_kw = clean_title or keyword

            matched_result = None
            for scraper, timeout in scrapers:
                try:
                    results = await asyncio.wait_for(scraper.search(search_kw), timeout=timeout)
                    if results:
                        matched_result = results[0]
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    continue

            if not matched_result:
                failed += 1
                continue

            s = await db.get_session()
            try:
                mv = (await s.execute(select(WesternMovie).where(WesternMovie.id == m.id))).scalar_one_or_none()
                if mv:
                    old_actors = mv.actors.split(",") if mv.actors else []
                    mv.title = matched_result.title
                    local_media = await ensure_movie_media_local(
                        module_name="western", code=mv.code,
                        cover_url=matched_result.cover_url,
                        fanart_url=getattr(matched_result, "poster_url", None) or getattr(matched_result, "fanart_url", None),
                        thumb_url=getattr(matched_result, "thumb_url", None),
                        referer=matched_result.cover_url,
                    )
                    if local_media.get("cover"):
                        mv.cover_url = local_media["cover"]
                    elif matched_result.cover_url:
                        mv.cover_url = matched_result.cover_url
                    if local_media.get("fanart"):
                        mv.poster_url = local_media["fanart"]
                    elif matched_result.poster_url:
                        mv.poster_url = matched_result.poster_url
                    if local_media.get("thumb"):
                        mv.thumb_url = local_media["thumb"]
                    if matched_result.duration:
                        mv.duration = matched_result.duration
                    if matched_result.rating:
                        mv.rating = matched_result.rating
                    if matched_result.plot:
                        mv.plot = matched_result.plot
                    if matched_result.genres:
                        mv.genre = ",".join(matched_result.genres)
                    if matched_result.actors:
                        new_actor_names = set()
                        mv.actors = ",".join(a.name for a in matched_result.actors)
                        for ai in matched_result.actors:
                            new_actor_names.add(ai.name)
                            ex = await s.execute(select(WesternActor).where(WesternActor.name == ai.name))
                            a = ex.scalar_one_or_none()
                            if not a:
                                new_a = WesternActor(name=ai.name, source="scraper", movie_count=1)
                                s.add(new_a)
                                if getattr(ai, "avatar_url", None):
                                    local_avatar = await ensure_actor_avatar_local(ai.name, ai.avatar_url)
                                    if local_avatar:
                                        new_a.avatar_url = local_avatar
                            else:
                                if a.movie_count < 100:
                                    a.movie_count += 1
                                if not a.avatar_url and getattr(ai, "avatar_url", None):
                                    local_avatar = await ensure_actor_avatar_local(ai.name, ai.avatar_url)
                                    a.avatar_url = local_avatar or ai.avatar_url
                        for name in old_actors:
                            n = name.strip()
                            if n and n not in new_actor_names:
                                actor_stmt = select(WesternActor).where(WesternActor.name == n)
                                actor_result = await s.execute(actor_stmt)
                                actor_obj = actor_result.scalar_one_or_none()
                                if actor_obj and actor_obj.movie_count > 0:
                                    actor_obj.movie_count -= 1
                    mv.status = "scraped"
                    mv.source = matched_result.source
                    await s.commit()
                    mv_dir = None
                    if hasattr(mv, "output_dir") and mv.output_dir:
                        mv_dir = str(mv.output_dir)
                    elif hasattr(mv, "file_path") and mv.file_path:
                        mv_dir = _os.path.dirname(str(mv.file_path))
                    try:
                        if mv_dir and _os.path.isdir(mv_dir):
                            actor_names = [a.strip() for a in (mv.actor or "").split(",") if a.strip()]
                            NFOGenerator(output_dir=mv_dir).generate_from_movie(
                                mv, movie_dir=None, kodi_compatible=True, actor_names=actor_names
                            )
                    except Exception as nfo_err:
                        logger.debug(f"Western 批量NFO生成失败 [{mv.code}]: {nfo_err}")
                    success += 1
            except Exception as e:
                logger.debug(f"刮削失败 {m.code}: {e}")
                failed += 1
            finally:
                await s.close()
        logger.info(f"Western 批量刮削完成: 成功 {success}, 失败 {failed}")

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "total": len(pending),
        "message": f"Western 批量刮削已启动，共 {len(pending)} 部待刮削影片",
    }


# ========== 播放端点 ==========


@router.get("/movies/{movie_id}/play")
async def play_western_movie(movie_id: int):
    """获取欧美影片播放信息"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select

        stmt = select(WesternMovie).where(WesternMovie.id == movie_id)
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
async def play_western_video_file(movie_id: int, request: _Request):
    """欧美影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select

        stmt = select(WesternMovie).where(WesternMovie.id == movie_id)
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
async def get_western_external_play_url(movie_id: int, request: _Request, protocol: str = "http"):
    """获取欧美影片外部播放地址"""
    db = get_western_db()
    session = await db.get_session()
    try:
        from app.db.western_models import WesternMovie
        from sqlalchemy import select

        stmt = select(WesternMovie).where(WesternMovie.id == movie_id)
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
            play_url = f"{base}/api/v1/western/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
