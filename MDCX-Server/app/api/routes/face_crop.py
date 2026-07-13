"""人脸裁剪路由

提供 AI 智能海报裁剪能力。
参考 mdc-ng 和 Hazard804-mdcx 的 face_crop.py。
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, get_config_manager
from app.db.database import get_session
from app.db.models import Movie
from app.services.face_crop import get_face_cropper, crop_movie_poster
from app.services.websocket import emit_log

router = APIRouter()


class CropRequest(BaseModel):
    """裁剪请求"""
    movie_id: int
    source_url: Optional[str] = None  # 远程源图 URL，None=用现有 cover_url
    target: Optional[str] = None  # poster/cover/both，None=用配置


class BatchCropRequest(BaseModel):
    """批量裁剪请求"""
    movie_ids: list[int]
    target: Optional[str] = None


class CropConfigUpdate(BaseModel):
    """裁剪配置更新"""
    enabled: Optional[bool] = None
    model_path: Optional[str] = None
    target: Optional[str] = None
    min_face_size: Optional[int] = None
    output_quality: Optional[int] = None
    margin_ratio: Optional[float] = None


@router.get("/config")
async def get_face_crop_config():
    """获取人脸裁剪配置"""
    cfg = get_config().face_crop
    return {
        "enabled": cfg.enabled,
        "model_path": cfg.model_path,
        "model_exists": os.path.exists(cfg.model_path) if cfg.model_path else os.path.exists("data/models/face_detection_yunet_fp32.onnx"),
        "target": cfg.target,
        "min_face_size": cfg.min_face_size,
        "output_quality": cfg.output_quality,
        "margin_ratio": cfg.margin_ratio,
    }


@router.put("/config")
async def update_face_crop_config(req: CropConfigUpdate):
    """更新人脸裁剪配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.face_crop.enabled = req.enabled
    if req.model_path is not None:
        current.face_crop.model_path = req.model_path
    if req.target is not None:
        if req.target not in ("poster", "cover", "both"):
            raise HTTPException(status_code=400, detail="target 必须是 poster/cover/both")
        current.face_crop.target = req.target
    if req.min_face_size is not None:
        current.face_crop.min_face_size = max(20, min(500, req.min_face_size))
    if req.output_quality is not None:
        current.face_crop.output_quality = max(50, min(100, req.output_quality))
    if req.margin_ratio is not None:
        current.face_crop.margin_ratio = max(0.0, min(1.0, req.margin_ratio))

    cm.save()
    return {"status": "ok"}


@router.post("/initialize")
async def initialize_face_cropper():
    """初始化人脸裁剪器（下载模型 + 加载）"""
    cropper = await get_face_cropper()
    if cropper is None:
        raise HTTPException(status_code=500, detail="初始化失败，请检查 onnxruntime / opencv 是否安装")
    return {"status": "ok", "message": "人脸裁剪器已就绪"}


@router.post("/crop")
async def crop_poster(
    req: CropRequest,
    session: AsyncSession = Depends(get_session),
):
    """为单个影片裁剪海报"""
    movie = await session.get(Movie, req.movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    # 源图路径
    source = req.source_url or movie.cover_url
    if not source:
        raise HTTPException(status_code=400, detail="影片无封面图，无法裁剪")

    # 本地化处理
    local_source = source
    if source.startswith("http"):
        # 下载远程图到临时文件
        import httpx
        import tempfile
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(source)
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"下载源图失败: HTTP {resp.status_code}")
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                    f.write(resp.content)
                    local_source = f.name
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"下载源图失败: {e}")
    elif not os.path.isabs(local_source):
        # 相对路径：拼接到 output_dir
        cfg = get_config().scraper
        local_source = os.path.join(cfg.output_dir, local_source)

    # 输出路径
    cfg = get_config()
    output_dir = os.path.join(cfg.scraper.output_dir, "posters")
    output_path = os.path.join(output_dir, f"{movie.code}_poster.jpg")

    task_id = f"face-crop-{movie.id}"
    ok = await crop_movie_poster(movie.id, local_source, output_path, task_id=task_id)

    if ok:
        # 更新 movie.poster_url
        movie.poster_url = output_path
        await session.commit()
        return {"status": "ok", "movie_id": movie.id, "poster_path": output_path}
    else:
        raise HTTPException(status_code=500, detail="裁剪失败")


@router.post("/batch-crop")
async def batch_crop(
    req: BatchCropRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量裁剪海报"""
    if not req.movie_ids:
        raise HTTPException(status_code=400, detail="影片 ID 列表不能为空")

    task_id = "face-crop-batch"
    total = len(req.movie_ids)
    success = 0
    failed = 0
    skipped = 0

    await emit_log("INFO", f"开始批量裁剪 {total} 部影片", task_id=task_id, module="face-crop")

    for idx, movie_id in enumerate(req.movie_ids, 1):
        movie = await session.get(Movie, movie_id)
        if not movie:
            skipped += 1
            continue

        source = movie.cover_url
        if not source:
            skipped += 1
            continue

        local_source = source
        if source.startswith("http"):
            continue  # 批量模式下跳过远程图
        elif not os.path.isabs(local_source):
            cfg = get_config()
            local_source = os.path.join(cfg.scraper.output_dir, local_source)

        if not os.path.exists(local_source):
            skipped += 1
            continue

        output_dir = os.path.join(get_config().scraper.output_dir, "posters")
        output_path = os.path.join(output_dir, f"{movie.code}_poster.jpg")

        ok = await crop_movie_poster(movie.id, local_source, output_path, task_id=task_id)
        if ok:
            movie.poster_url = output_path
            await session.commit()
            success += 1
        else:
            failed += 1

        await emit_log(
            "DEBUG",
            f"进度: {idx}/{total} · 成功 {success} / 失败 {failed} / 跳过 {skipped}",
            task_id=task_id,
            module="face-crop",
        )

    await emit_log(
        "SUCCESS" if failed == 0 else "WARNING",
        f"批量裁剪完成 · 成功 {success} / 失败 {failed} / 跳过 {skipped} / 总计 {total}",
        task_id=task_id,
        module="face-crop",
    )

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
    }


@router.get("/status")
async def get_cropper_status():
    """获取裁剪器状态"""
    from app.services.face_crop import _face_cropper
    return {
        "initialized": _face_cropper is not None,
        "backend": "yunet" if _face_cropper and _face_cropper._session else "opencv" if _face_cropper and _face_cropper._cv_cascade else None,
    }
