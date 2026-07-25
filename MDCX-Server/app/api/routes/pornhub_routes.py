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
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pornhub", tags=["PORNHub模块"])


def get_pornhub_db() -> ModuleDatabase:
    return ModuleDatabase.get_instance("pornhub")


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
                 "avatar_url": a.avatar_url, "movie_count": a.movie_count, "source": a.source} for a in actors]
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
                "movie_count": actor.movie_count,
                "created_at": str(actor.created_at)}
    finally:
        await session.close()


# ========== 影片 ==========


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20, unscraped_only: bool = Query(False, description="仅列出未刮削的影片")):
    """列出 PORNHub 模块影片列表"""
    db = get_pornhub_db()
    session = await db.get_session()
    try:
        from app.db.pornhub_models import PornhubMovie
        from sqlalchemy import select, func

        total_stmt = select(func.count(PornhubMovie.id))
        if unscraped_only:
            total_stmt = total_stmt.where(PornhubMovie.status == "pending")
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()

        stmt = select(PornhubMovie).order_by(PornhubMovie.created_at.desc()).offset(skip).limit(limit)
        if unscraped_only:
            stmt = stmt.where(PornhubMovie.status == "pending")
        result = await session.execute(stmt)
        movies = result.scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "source_views": m.source_views, "source_score": m.source_score,
             "uploader": m.uploader, "categories": m.categories,
             "cover_url": m.cover_url, "actor": m.actor,
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
            "release_date": movie.release_date, "duration": movie.duration,
            "rating": movie.rating, "plot": movie.plot,
            "tags": movie.tags, "source": movie.source, "source_url": movie.source_url,
            "file_path": movie.file_path, "file_size": movie.file_size,
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
        }
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
            movie.tags = ",".join(scrape_result.tags)
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
                    db_actor.movie_count += 1
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
                                mv.tags = ",".join(result.tags)
                            if result.actors:
                                mv.actor = ",".join(a.name for a in result.actors)
                                for ai in result.actors:
                                    ex = await s.execute(select(PornhubActor).where(PornhubActor.name == ai.name))
                                    a = ex.scalar_one_or_none()
                                    if not a:
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

        from app.scraper.module_actor_profile import ModuleActorProfileScraper
        scraper = ModuleActorProfileScraper(module_name="pornhub")
        profile = await scraper.get_profile(actor.name)

        if not profile:
            # 通过 JavDB 搜索获取头像
            avatar_url = await _scrape_avatar_from_javdb(actor.name)
            if avatar_url:
                actor.avatar_url = avatar_url
            await session.commit()
            return {"status": "partial", "message": f"未找到演员 {actor.name} 的详细资料，已尝试获取头像"}

        actor.alias = profile.alias or actor.alias
        if profile.avatar_url:
            actor.avatar_url = profile.avatar_url
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
        from app.scraper.module_actor_profile import ModuleActorProfileScraper
        from sqlalchemy import select

        scraper = ModuleActorProfileScraper(module_name="pornhub")
        success = 0
        failed = 0
        for a in actors:
            try:
                profile = await scraper.get_profile(a.name)
                s = await db.get_session()
                try:
                    st = select(PornhubActor).where(PornhubActor.id == a.id)
                    r = await s.execute(st)
                    act = r.scalar_one_or_none()
                    if act:
                        if profile:
                            if profile.alias:
                                act.alias = profile.alias
                            if profile.avatar_url:
                                act.avatar_url = profile.avatar_url
                            if profile.country and not act.nationality:
                                act.nationality = profile.country
                        else:
                            avatar_url = await _scrape_avatar_from_javdb(act.name)
                            if avatar_url:
                                act.avatar_url = avatar_url
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
        from app.scraper.module_actor_profile import ModuleActorProfileScraper
        profile_scraper = ModuleActorProfileScraper(module_name="pornhub")

        s = await db.get_session()
        try:
            actors = await s.execute(select(PornhubActor))
            for actor_row in actors.scalars().all():
                if actor_row.avatar_url and actor_row.nationality:
                    continue
                try:
                    profile = await profile_scraper.get_profile(actor_row.name)
                    if profile:
                        if profile.avatar_url:
                            actor_row.avatar_url = profile.avatar_url
                        if profile.country and not actor_row.nationality:
                            actor_row.nationality = profile.country
                    else:
                        avatar_url = await _scrape_avatar_from_javdb(actor_row.name)
                        if avatar_url:
                            actor_row.avatar_url = avatar_url
                    await s.commit()
                    logger.info(f"PORNHub 工作流：演员资料已获取 {actor_row.name}")
                except Exception as e:
                    logger.debug(f"演员资料获取失败 {actor_row.name}: {e}")
                await asyncio.sleep(0.3)
        finally:
            await s.close()

        # 3. 生成视频截图封面
        from app.utils.bin_tools import get_ffmpeg_path
        from app.config.manager import DATA_DIR
        import subprocess

        ffmpeg = get_ffmpeg_path()
        if ffmpeg and Path(ffmpeg).exists():
            s2 = await db.get_session()
            try:
                pending_movies = await s2.execute(
                    select(PornhubMovie).where(PornhubMovie.status == "pending")
                )
                for mv in pending_movies.scalars().all():
                    if not mv.file_path or not Path(mv.file_path).exists():
                        continue
                    try:
                        output_dir = DATA_DIR / "movies" / "pornhub" / mv.code
                        output_dir.mkdir(parents=True, exist_ok=True)
                        cover_path = output_dir / "poster.jpg"

                        r = subprocess.run(
                            [ffmpeg, "-y", "-ss", "00:00:05", "-i", mv.file_path,
                             "-vframes", "1", "-vf", "scale=480:-1", str(cover_path)],
                            capture_output=True, text=True, timeout=60,
                            encoding="utf-8", errors="replace",
                        )
                        if r.returncode == 0 and cover_path.exists():
                            mv.cover_url = str(cover_path)
                            mv.poster_url = str(cover_path)
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
