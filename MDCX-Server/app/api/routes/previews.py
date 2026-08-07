"""影片预览图（extrafanart）本地读取路由 —— 全模块通用

设计原则：**本地优先，绝不外链**。

刮削时已把封面与预览图下载到规范目录：
    {data_base}/movies/{module}/{code}/
        ├── poster.jpg          竖版海报
        ├── fanart.jpg          横版大图
        ├── thumb.jpg           缩略图
        ├── movie.nfo
        └── extrafanart/
            ├── 01.jpg
            ├── 02.jpg
            └── ...

本路由把这些本地文件通过 HTTP 暴露给前端详情页，
彻底绕开 DMM / javbus 的 Referer 防盗链问题，
且下载一次之后不再产生任何外网请求。

端点：
    GET /api/v1/previews/{module}/{movie_id}              预览图清单
    GET /api/v1/previews/{module}/{movie_id}/main/file    主封面大图
    GET /api/v1/previews/{module}/{movie_id}/{index}/file 第 index 张预览图
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.utils.media_helpers import (
    get_movie_extrafanart_dir,
    get_movie_main_image_path,
    list_movie_preview_files,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 支持的模块（与 MODULE_DIR_MAP 保持一致）
SUPPORTED_MODULES = {"jav", "fc2", "uncensored", "chinese", "pornhub", "western"}

# 目录扫描结果缓存：避免同一部影片的 N 张图触发 N 次目录遍历
# key = "{module}:{code}:{file_path}" → (写入时间戳, 路径列表)
_SCAN_CACHE: dict[str, tuple[float, list[str]]] = {}
_SCAN_CACHE_TTL = 60.0
_SCAN_CACHE_MAX = 2000


def _media_type(path: str) -> str:
    """按扩展名推断 Content-Type"""
    ext = Path(path).suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".avif":
        return "image/avif"
    return "image/jpeg"


def _normalize_module(module: str) -> str:
    """校验并归一化模块名"""
    name = (module or "").strip().lower()
    if name not in SUPPORTED_MODULES:
        raise HTTPException(status_code=404, detail=f"不支持的模块: {module}")
    return name


async def _load_movie_brief(module: str, movie_id: int) -> Optional[dict]:
    """读取影片的番号 / 文件路径 / 远程样图字段（跨模块通用）"""
    from sqlalchemy import select

    from app.db.module_db import ModuleDatabase
    from app.utils.module_helper import get_module_model

    try:
        Movie = get_module_model(module, "movie")
    except Exception as exc:
        logger.warning(f"预览图: 无法加载模块模型 [{module}] {exc}")
        raise HTTPException(status_code=404, detail=f"模块不可用: {module}")

    db = ModuleDatabase.get_instance(module)
    session = await db.get_session()
    try:
        result = await session.execute(select(Movie).where(Movie.id == movie_id))
        movie = result.scalar_one_or_none()
        if movie is None:
            return None
        return {
            "code": getattr(movie, "code", None),
            "title": getattr(movie, "title", None),
            "file_path": getattr(movie, "file_path", None),
            "sample_images": getattr(movie, "sample_images", None),
        }
    finally:
        await session.close()


def _scan_local_previews(
    module: str,
    code: Optional[str],
    file_path: Optional[str],
    use_cache: bool = True,
) -> list[str]:
    """扫描本地预览图（带 TTL 缓存）"""
    cache_key = f"{module}:{code}:{file_path}"
    now = time.time()

    if use_cache:
        cached = _SCAN_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _SCAN_CACHE_TTL:
            return cached[1]

    files = list_movie_preview_files(module, code, file_path)

    if len(_SCAN_CACHE) > _SCAN_CACHE_MAX:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[cache_key] = (now, files)
    return files


def _parse_remote_samples(raw: Optional[str]) -> list[str]:
    """解析 DB 中 sample_images JSON，仅保留 http(s) 外链"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [
        str(item)
        for item in parsed
        if item and isinstance(item, str) and item.lower().startswith(("http://", "https://"))
    ]


@router.get("/{module}/{movie_id}")
async def list_movie_previews(
    module: str,
    movie_id: int,
    refresh: bool = Query(False, description="跳过缓存重新扫描磁盘"),
):
    """获取影片的预览图清单（本地优先）

    返回 source 字段说明数据来源：
    - local  : 本地 extrafanart 目录已有图片，images 为后端代理 URL（推荐）
    - remote : 本地无图，回退为 DB 中的远程外链（可能因防盗链失败）
    - none   : 本地与远程都没有
    """
    mod = _normalize_module(module)

    info = await _load_movie_brief(mod, movie_id)
    if info is None:
        raise HTTPException(status_code=404, detail="影片不存在")

    code = info["code"]
    file_path = info["file_path"]

    local_files = _scan_local_previews(mod, code, file_path, use_cache=not refresh)
    main_image = get_movie_main_image_path(mod, code)

    base = f"/api/v1/previews/{mod}/{movie_id}"
    payload = {
        "module": mod,
        "movie_id": movie_id,
        "code": code,
        "extrafanart_dir": str(get_movie_extrafanart_dir(mod, code)) if code else None,
        "has_local_cover": bool(main_image),
        "cover": f"{base}/main/file" if main_image else None,
        "cover_path": main_image,
    }

    if local_files:
        payload.update({
            "source": "local",
            "count": len(local_files),
            "images": [f"{base}/{i}/file" for i in range(len(local_files))],
            "paths": local_files,
        })
        return payload

    remote = _parse_remote_samples(info["sample_images"])
    payload.update({
        "source": "remote" if remote else "none",
        "count": len(remote),
        "images": remote,
        "paths": [],
    })
    return payload


@router.get("/{module}/{movie_id}/main/file")
async def get_movie_main_image(module: str, movie_id: int):
    """获取影片主封面大图（fanart → thumb → cover → poster）"""
    mod = _normalize_module(module)

    info = await _load_movie_brief(mod, movie_id)
    if info is None:
        raise HTTPException(status_code=404, detail="影片不存在")

    path = get_movie_main_image_path(mod, info["code"])
    if not path:
        raise HTTPException(status_code=404, detail="本地无封面大图")

    return FileResponse(
        path,
        media_type=_media_type(path),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{module}/{movie_id}/{index}/file")
async def get_movie_preview_file(module: str, movie_id: int, index: int):
    """获取影片第 index 张本地预览图（index 从 0 开始）"""
    mod = _normalize_module(module)

    if index < 0:
        raise HTTPException(status_code=404, detail="预览图序号非法")

    info = await _load_movie_brief(mod, movie_id)
    if info is None:
        raise HTTPException(status_code=404, detail="影片不存在")

    files = _scan_local_previews(mod, info["code"], info["file_path"])
    if not files:
        raise HTTPException(status_code=404, detail="本地无预览图")
    if index >= len(files):
        raise HTTPException(status_code=404, detail="预览图序号越界")

    target = files[index]
    return FileResponse(
        target,
        media_type=_media_type(target),
        headers={"Cache-Control": "public, max-age=86400"},
    )
