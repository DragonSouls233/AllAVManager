"""
国产模块 API 路由
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request as _Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.db.chinese_models import ChineseMovie, ChineseActor
from app.services.chinese_rename_service import get_rules, update_rules, clean_title

import os as _os
from pathlib import Path as _Path

router = APIRouter(prefix="/chinese", tags=["国产模块"])

# ===== 命名规则管理 =====

@router.get("/name-rules")
async def api_get_name_rules():
    return get_rules()

@router.put("/name-rules")
async def api_update_name_rules(data: dict):
    return update_rules(data)

@router.post("/name-rules/clean")
async def api_clean_title(data: dict):
    title = data.get("title", "")
    result = clean_title(title)
    return {"original": data.get("title", ""), "cleaned": result}


def get_chinese_db() -> "ModuleDatabase":
    from app.db.module_db import ModuleDatabase
    try:
        return ModuleDatabase.get_instance("chinese")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("get_chinese_db failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Database init error: {e}")


@router.get("/actors")
async def list_actors():
    """列出国产模块演员列表"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseActor
        from sqlalchemy import select
        stmt = select(ChineseActor).order_by(ChineseActor.movie_count.desc())
        result = await session.execute(stmt)
        actors = result.scalars().all()
        return [{"id": a.id, "name": a.name, "movie_count": a.movie_count, "source": a.source, "avatar_url": a.avatar_url, "module_type": "chinese"} for a in actors]
    finally:
        await session.close()


@router.get("/actors/{actor_id}")
async def get_actor(actor_id: int):
    """获取国产演员详情"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseActor
        from sqlalchemy import select
        stmt = select(ChineseActor).where(ChineseActor.id == actor_id)
        result = await session.execute(stmt)
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status_code=404, detail="演员不存在")
        return {"id": actor.id, "name": actor.name, "alias": actor.alias,
                "avatar_url": actor.avatar_url, "source": actor.source,
                "module_type": "chinese",
                "movie_count": actor.movie_count,
                "created_at": str(actor.created_at)}
    finally:
        await session.close()


@router.post("/actors/scan-folders")
async def sync_folder_actors():
    """从媒体目录的文件夹名同步演员"""
    from app.config.manager import get_config
    config = get_config()
    from app.tasks.chinese_scanner import ChineseScanner
    scanner = ChineseScanner(config.modules.chinese.media_dirs)
    result = await scanner.scan()
    return result


@router.get("/movies")
async def list_movies(skip: int = 0, limit: int = 20,
    keyword: Optional[str] = Query(None, description="搜索标题"),
    actor: Optional[str] = Query(None, description="按演员名过滤"),
    # 2026-08-08 新增: 详情页跳转筛选参数
    series: Optional[str] = Query(None, description="按系列精确过滤"),
    maker: Optional[str] = Query(None, description="按片商/制作商过滤（匹配 maker 或 studio）"),
    genre: Optional[str] = Query(None, description="按类别过滤（genre 字段包含）"),
    code_prefix: Optional[str] = Query(None, description="番号前缀精确过滤")):
    """列出国产模块影片列表"""
    db = get_chinese_db()
    try:
        session = await db.get_session()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session error: {e}")
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select, func, or_
        filters = []
        if actor:
            filters.append(ChineseMovie.folder_based_actors.like(f"%{actor}%"))
        if keyword:
            kw = f"%{keyword}%"
            filters.append(or_(ChineseMovie.title.like(kw), ChineseMovie.code.like(kw)))
        if series:
            filters.append(ChineseMovie.series == series)
        if maker:
            filters.append(or_(ChineseMovie.maker == maker, ChineseMovie.studio == maker))
        if genre:
            filters.append(ChineseMovie.genre.contains(genre))
        if code_prefix:
            filters.append(ChineseMovie.code.startswith(code_prefix))

        total_stmt = select(func.count(ChineseMovie.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total_result = await session.execute(total_stmt)
        total = total_result.scalar()
        stmt = select(ChineseMovie)
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.order_by(ChineseMovie.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        movies = result.scalars().all()
        return {"total": total, "items": [
            {"id": m.id, "code": m.code, "title": m.title,
             "folder_name": m.folder_name,
             "folder_based_actors": m.folder_based_actors,
             "studio": m.studio, "cover_url": m.cover_url,
             "module_type": "chinese",
             "file_path": m.file_path, "status": m.status}
            for m in movies
        ]}
    finally:
        await session.close()


@router.get("/movies/{movie_id}")
async def get_movie(movie_id: int):
    """获取国产影片详情"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select
        stmt = select(ChineseMovie).where(ChineseMovie.id == movie_id)
        result = await session.execute(stmt)
        movie = result.scalar_one_or_none()
        if not movie:
            raise HTTPException(status_code=404, detail="影片不存在")
        return {
            "id": movie.id, "code": movie.code, "title": movie.title,
            "folder_name": movie.folder_name,
            "folder_based_actors": movie.folder_based_actors,
            "studio": movie.studio, "cover_url": movie.cover_url,
            "poster_url": movie.poster_url, "release_date": movie.release_date,
            "duration": movie.duration, "rating": movie.rating,
            "plot": movie.plot, "genre": movie.genre, "tag": movie.tag,
            "module_type": "chinese",
            "file_path": movie.file_path, "file_size": movie.file_size,
            "play_count": movie.play_count, "view_status": movie.view_status,
            "status": movie.status, "created_at": str(movie.created_at),
        }
    finally:
        await session.close()


# ========== 播放端点 ==========


@router.get("/movies/{movie_id}/play")
async def play_chinese_movie(movie_id: int):
    """获取国产影片播放信息"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select

        stmt = select(ChineseMovie).where(ChineseMovie.id == movie_id)
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
async def play_chinese_video_file(movie_id: int, request: _Request):
    """国产影片视频流播放（支持 Range 请求）"""
    from starlette.responses import StreamingResponse, Response

    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select

        stmt = select(ChineseMovie).where(ChineseMovie.id == movie_id)
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
async def get_chinese_external_play_url(movie_id: int, protocol: str = "http"):
    """获取国产影片外部播放地址"""
    db = get_chinese_db()
    session = await db.get_session()
    try:
        from app.db.chinese_models import ChineseMovie
        from sqlalchemy import select

        stmt = select(ChineseMovie).where(ChineseMovie.id == movie_id)
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
            play_url = f"{base}/api/v1/chinese/movies/{movie_id}/play/file"
            return {"protocol": "http", "play_url": play_url, "player_command": play_url, "copy_text": play_url}
        else:
            return {"protocol": "direct", "play_url": movie.file_path, "player_command": movie.file_path, "copy_text": movie.file_path}
    finally:
        await session.close()
