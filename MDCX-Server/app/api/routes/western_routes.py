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
            kw = f"%{keyword}%"
            filters.append(or_(WesternMovie.title.like(kw), WesternMovie.actors.like(kw), WesternMovie.site.like(kw)))
        if actor:
            filters.append(WesternMovie.actors.like(f"%{actor}%"))
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
        from app.crawlers.western.theporndb import ThePornDBCrawler
        from app.crawlers.western.aylo_api import AyloAPICrawler
        from app.crawlers.western.vixen_network import VixenNetworkCrawler
        from app.crawlers.western.naughtyamerica import NaughtyAmericaCrawler

        scrapers = [
            (ThePornDBCrawler(), 10),
            (AyloAPICrawler(), 8),
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
        movie.title = matched_result.title
        movie.original_title = matched_result.original_title or matched_result.title
        if matched_result.cover_url:
            movie.cover_url = matched_result.cover_url
        if matched_result.poster_url:
            movie.poster_url = matched_result.poster_url
        if matched_result.duration:
            movie.duration = matched_result.duration
        if matched_result.rating:
            movie.rating = matched_result.rating
        if matched_result.plot:
            movie.plot = matched_result.plot
        if matched_result.release_date:
            movie.release_date = str(matched_result.release_date)
        if matched_result.genres:
            movie.genre = ",".join(matched_result.genres)
        if matched_result.tags:
            movie.tag = ",".join(matched_result.tags)
        if matched_result.studio:
            movie.studio = matched_result.studio

        # 演员
        if matched_result.actors:
            actor_names = [a.name for a in matched_result.actors]
            movie.actors = ",".join(actor_names)
            for ai in matched_result.actors:
                ex = await session.execute(select(WesternActor).where(WesternActor.name == ai.name))
                a = ex.scalar_one_or_none()
                if not a:
                    session.add(WesternActor(name=ai.name, source="scraper", movie_count=1))

        movie.status = "scraped"
        movie.source = matched_result.source
        await session.commit()

        return {
            "status": "ok",
            "message": f"刮削成功: {matched_result.title}",
            "source": matched_result.source,
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
        from sqlalchemy import select
        from app.crawlers.western.theporndb import ThePornDBCrawler

        crawler = ThePornDBCrawler()
        success = 0
        failed = 0
        for m in pending:
            try:
                results = await crawler.search(m.title or "")
                if results:
                    s = await db.get_session()
                    try:
                        mv = (await s.execute(select(WesternMovie).where(WesternMovie.id == m.id))).scalar_one_or_none()
                        if mv:
                            r = results[0]
                            mv.title = r.title
                            if r.cover_url:
                                mv.cover_url = r.cover_url
                            if r.duration:
                                mv.duration = r.duration
                            if r.rating:
                                mv.rating = r.rating
                            if r.actors:
                                mv.actors = ",".join(a.name for a in r.actors)
                                for ai in r.actors:
                                    ex = await s.execute(select(WesternActor).where(WesternActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if not a:
                                        s.add(WesternActor(name=ai.name, source="scraper", movie_count=1))
                            mv.status = "scraped"
                            mv.source = r.source
                            await s.commit()
                            success += 1
                    finally:
                        await s.close()
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"刮削失败 {m.code}: {e}")
                failed += 1
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
async def get_western_external_play_url(movie_id: int, protocol: str = "http"):
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
        config = get_config()
        host = getattr(config.server, "host", "0.0.0.0")
        port = getattr(config.server, "port", 8420)

        if host in ("0.0.0.0", "127.0.0.1", "localhost"):
            base = f"http://localhost:{port}"
        else:
            base = f"http://{host}:{port}"

        if protocol == "http":
            play_url = f"{base}/api/v1/western/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
