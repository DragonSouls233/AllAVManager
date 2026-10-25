"""媒体修复 API 路由（ffmpeg remux/reencode，安全链：备份→验证→原子替换）

POST /api/v1/media-repair/analyze            {file_path} → 诊断（只读，秒级）
POST /api/v1/media-repair/jobs               {file_path, mode, verify_decode} → 建任务
GET  /api/v1/media-repair/jobs?limit=20      → 最近任务列表
GET  /api/v1/media-repair/jobs/{job_id}      → 任务状态+日志（前端轮询）
POST /api/v1/media-repair/jobs/{job_id}/cancel → 取消任务

🔴 安全约定：原文件先改名备份到同目录 .mdcx-broken/，修复产物通过 ffprobe +
（可选）全解码验证后才原子替换；任何一步失败原文件一个字节不动。
"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from app.services.media_repair import (
    MODES,
    analyze_file,
    cancel_job,
    get_job,
    list_jobs,
    start_repair_job,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class AnalyzeRequest(BaseModel):
    file_path: str
    decode_check: bool = False  # 全解码查中段损坏（慢，修复对话框传 True）


class RepairJobRequest(BaseModel):
    file_path: str
    mode: str = "remux"           # remux=不重编码（默认）/ reencode=兜底重编码
    verify_decode: bool = True    # 替换前全解码验证一遍
    decode_check: bool = False    # 内部复查也全解码（诊断过 corrupt 的文件要传 True）


@router.post("/analyze")
async def analyze_endpoint(body: AnalyzeRequest):
    """诊断单文件：类别（truncated/no_moov/corrupt/moov_at_end/healthy…）+ 是否可修。

    只读，不改任何文件。前端修复对话框打开时自动调用（decode_check=True 拿最准结论）。
    """
    if not body.file_path or not body.file_path.strip():
        raise HTTPException(400, "file_path 不能为空")
    return await analyze_file(body.file_path.strip(), decode_check=body.decode_check)


@router.post("/jobs")
async def create_job_endpoint(body: RepairJobRequest):
    """创建修复任务（后台执行，立即返回 job_id）。

    并发 1：同时只能修一个文件（大文件 IO 密集），其余排队。
    前端拿到 job_id 后轮询 GET /jobs/{job_id} 看进度。
    """
    if body.mode not in MODES:
        raise HTTPException(400, f"mode 必须是 {'/'.join(MODES)}")
    if not body.file_path or not body.file_path.strip():
        raise HTTPException(400, "file_path 不能为空")
    return await start_repair_job(
        body.file_path.strip(), mode=body.mode,
        verify_decode=body.verify_decode, decode_check=body.decode_check)


@router.get("/jobs")
async def list_jobs_endpoint(limit: int = Query(20, ge=1, le=100)):
    """最近的任务（新的在前），供前端进页面时恢复进行中任务的状态"""
    return {"items": list_jobs(limit=limit)}


@router.get("/jobs/{job_id}")
async def get_job_endpoint(job_id: str):
    """任务状态 + 日志尾部（前端每 2s 轮询）"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在（可能已被淘汰）")
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str):
    """取消任务：杀掉 ffmpeg 子进程；未开始的直接标记取消"""
    return cancel_job(job_id)
