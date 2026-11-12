"""字幕下载路由（独立 router，路径带 ``{module}`` 段）。

挂载：``/api/v1/subtitles``（见 ``app/api/__init__.py``）。

- 单条失败**一律 HTTP 200 + ok=false + reason**，避免前端 axios 抛错吞掉原因；
  只有「模块不支持」「影片不存在」用 404。
- 与播放器的 ``/player/{id}/subtitles/*`` 完全无关，互不影响。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import subtitle_fetcher as fetcher
from app.services.subtitle_sources.base import (
    SOURCE_LABEL,
    LANG_LABEL,
    registry_lookup,
    srt_target_path,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class DownloadRequest(BaseModel):
    overwrite: bool = False


class BatchRequest(BaseModel):
    """批量参数。

    🔴 不允许「空参数即全库」：批量会真实下载并写盘，必须显式给出范围。
    - 指定影片：``movie_ids`` 非空；
    - 全库：``scope="all"`` + ``confirm=true`` + ``limit``（1~200）三者齐全。
    """

    movie_ids: list[int] | None = None
    scope: str | None = None
    confirm: bool = False
    limit: int | None = None
    only_missing: bool = True
    keyword: str | None = None
    code_prefix: str | None = None
    concurrency: int = Field(3, ge=1, le=4)
    overwrite: bool = False


def _normalize_module(module: str) -> str:
    name = (module or "").strip().lower()
    if name not in fetcher.SUPPORTED_MODULES:
        raise HTTPException(status_code=404, detail=f"不支持的模块: {module}")
    return name


async def _load_movie(module: str, movie_id: int) -> dict:
    try:
        row = await fetcher._load_movie(module, movie_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("字幕: 读取影片失败 [%s/%s] %s", module, movie_id, exc)
        raise HTTPException(status_code=404, detail="影片不存在或模块不可用")
    if row is None:
        raise HTTPException(status_code=404, detail="影片不存在")
    return row


@router.get("/{module}/{movie_id}/status")
async def subtitle_status(module: str, movie_id: int):
    """查该影片的字幕状态（是否有字幕、目标路径、登记来源）。"""
    mod = _normalize_module(module)
    row = await _load_movie(mod, movie_id)
    file_path = row.get("file_path") or ""
    code = row.get("code") or ""

    from app.tasks.base_scanner import find_external_subtitle

    has_subtitle = False
    if file_path:
        try:
            # 网络盘 listdir 可能阻塞数百毫秒，放线程池别卡事件循环
            has_subtitle = await asyncio.to_thread(find_external_subtitle, file_path, code or None)
        except Exception:  # noqa: BLE001
            has_subtitle = False

    target = str(srt_target_path(file_path)) if file_path else None
    target_exists = False
    if target:
        try:
            target_exists = await asyncio.to_thread(lambda: Path(target).is_file())
        except OSError:
            target_exists = False
    entry = await registry_lookup(file_path)
    registry = None
    if entry:
        registry = {
            "source": entry.get("source"),
            "source_label": entry.get("source_label")
            or SOURCE_LABEL.get(entry.get("source") or "", entry.get("source")),
            "language": entry.get("language"),
            "language_label": entry.get("language_label")
            or LANG_LABEL.get(entry.get("language") or "", entry.get("language")),
            "bytes": entry.get("bytes"),
            "at": entry.get("at"),
        }
    return {
        "module": mod,
        "movie_id": movie_id,
        "code": code,
        "file_path": file_path or None,
        "has_subtitle": bool(has_subtitle),
        "target_path": target,
        "target_exists": target_exists,
        "registry": registry,
    }


@router.post("/{module}/{movie_id}/download")
async def download_subtitle(module: str, movie_id: int, payload: DownloadRequest | None = None):
    """下载单个影片的字幕，落盘到视频同目录同名 .srt。"""
    mod = _normalize_module(module)
    await _load_movie(mod, movie_id)
    overwrite = bool(payload.overwrite) if payload else False
    started = time.monotonic()
    try:
        result = await fetcher.fetch_for_movie(mod, movie_id, overwrite=overwrite)
    except LookupError:
        raise HTTPException(status_code=404, detail="影片不存在")
    except Exception as exc:  # noqa: BLE001 - 兜底：仍然 200 + 可读原因
        logger.warning("字幕下载异常 [%s/%s]: %s", mod, movie_id, exc, exc_info=True)
        data = fetcher.FetchResult(
            ok=False, status="failed", movie_id=movie_id,
            reason=fetcher.FailReason.DOWNLOAD_FAILED,
            message=fetcher.REASON_MESSAGE[fetcher.FailReason.DOWNLOAD_FAILED],
            elapsed_ms=int((time.monotonic() - started) * 1000),
        ).to_dict()
        return data
    return result.to_dict()


@router.post("/{module}/batch")
async def start_batch(module: str, payload: BatchRequest | None = None):
    """启动批量补全（同模块同时只允许一个任务）。

    空参数**不再默认全库**：批量会真实下载并写盘，必须明确范围。
    """
    mod = _normalize_module(module)
    body = payload or BatchRequest()

    movie_ids = [int(item) for item in (body.movie_ids or [])]
    if not movie_ids:
        scope = (body.scope or "").strip().lower()
        if scope != "all":
            raise HTTPException(
                status_code=400,
                detail="必须指定影片范围：请传 movie_ids；如需全库，请传 scope=all + confirm=true + limit",
            )
        if not body.confirm:
            raise HTTPException(
                status_code=400,
                detail="全库模式需显式确认：请同时传 confirm=true",
            )
        if body.limit is None:
            raise HTTPException(
                status_code=400,
                detail="全库模式必须指定 limit（1~200）",
            )
        if not 1 <= int(body.limit) <= 200:
            raise HTTPException(
                status_code=400,
                detail="全库模式 limit 必须在 1~200 之间",
            )
        limit = int(body.limit)
    else:
        # 指定影片：上限就是所选数量，避免被 SQL limit 意外截断
        limit = len(movie_ids)

    try:
        return await fetcher.start_batch(
            mod,
            movie_ids=movie_ids or None,
            only_missing=body.only_missing,
            keyword=body.keyword,
            code_prefix=body.code_prefix,
            limit=limit,
            concurrency=body.concurrency,
            overwrite=body.overwrite,
        )
    except fetcher.BatchBusy:
        raise HTTPException(status_code=409, detail="字幕补全任务正在运行，请等待完成或先取消")
    except fetcher.BatchEmpty as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{module}/batch/latest")
async def latest_batch(module: str):
    """最近一次任务（页面刷新后恢复进度）。"""
    mod = _normalize_module(module)
    data = fetcher.latest_batch(mod)
    if data is None:
        raise HTTPException(status_code=404, detail="暂无字幕补全任务")
    return data


@router.get("/{module}/batch/{job_id}")
async def batch_progress(module: str, job_id: str):
    mod = _normalize_module(module)
    data = fetcher.get_batch(job_id)
    if data is None or data.get("module") != mod:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启")
    return data


@router.post("/{module}/batch/{job_id}/cancel")
async def batch_cancel(module: str, job_id: str):
    mod = _normalize_module(module)
    data = fetcher.get_batch(job_id)
    if data is None or data.get("module") != mod:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启")
    try:
        return fetcher.cancel_batch(job_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启")
