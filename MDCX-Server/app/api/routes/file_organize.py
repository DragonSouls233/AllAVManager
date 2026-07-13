"""
文件整理 API 路由（v3.0）

提供 5 种整理模式：hardlink/copy/move/symlink/rename
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services.file_organize import (
    file_organize_service,
    OrganizeType,
    ConflictStrategy,
)

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class PreviewRequest(BaseModel):
    """预览整理任务请求"""
    movie_ids: list[int] = Field(..., min_length=1, max_length=500)
    job_type: str = Field(..., description="hardlink/copy/move/symlink/rename")
    output_dir: str = Field("", description="输出目录（rename 模式忽略）")
    template: str = Field("{{ code }}/{{ code }}", description="Jinja2 命名模板")
    conflict_strategy: str = Field("skip", description="skip/overwrite/rename")


class ExecuteRequest(BaseModel):
    """执行整理任务请求"""
    movie_ids: list[int] = Field(..., min_length=1, max_length=100)
    job_type: str = Field(...)
    output_dir: str = Field("")
    template: str = Field("{{ code }}/{{ code }}")
    conflict_strategy: str = Field("skip")


class JobResponse(BaseModel):
    id: int
    job_type: str
    source_path: str
    target_path: str
    movie_id: int | None = None
    status: str
    conflict_strategy: str
    error_message: str | None = None
    file_size: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None


# ============================================
# 路由
# ============================================

@router.get("/modes", summary="获取支持的整理模式和冲突策略")
async def get_organize_modes():
    """获取支持的整理模式和冲突策略"""
    return {
        "job_types": [
            {"value": t.value, "label": label, "desc": desc}
            for t, label, desc in [
                (OrganizeType.HARDLINK, "硬链接", "同盘符不占额外空间，原文件保留"),
                (OrganizeType.COPY, "复制", "跨盘符或需独立副本，原文件保留"),
                (OrganizeType.MOVE, "移动", "迁移到目标目录，原文件删除"),
                (OrganizeType.SYMLINK, "软链接", "符号链接，跨盘符可用，原文件保留"),
                (OrganizeType.RENAME, "原地点名", "仅重命名，不改变目录"),
            ]
        ],
        "conflict_strategies": [
            {"value": s.value, "label": label, "desc": desc}
            for s, label, desc in [
                (ConflictStrategy.SKIP, "跳过", "目标已存在则不处理"),
                (ConflictStrategy.OVERWRITE, "覆盖", "删除目标后重新整理"),
                (ConflictStrategy.RENAME, "重命名", "目标加 _1/_2 后缀"),
            ]
        ],
    }


@router.post("/preview", summary="预览整理任务")
async def preview_organize(body: PreviewRequest, session: AsyncSession = Depends(get_session)):
    """预览整理任务（不执行，仅生成任务列表）

    返回每个影片的源路径、目标路径、整理模式，便于用户确认后再执行。
    """
    try:
        tasks = await file_organize_service.preview_organize(
            session,
            movie_ids=body.movie_ids,
            job_type=body.job_type,
            output_dir=body.output_dir,
            template=body.template,
            conflict_strategy=body.conflict_strategy,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "total": len(tasks),
        "items": [
            {
                "movie_id": t.movie_id,
                "source_path": t.source_path,
                "target_path": t.target_path,
                "job_type": t.job_type,
                "conflict_strategy": t.conflict_strategy,
            }
            for t in tasks
        ],
    }


@router.post("/execute", summary="执行整理任务")
async def execute_organize(body: ExecuteRequest, session: AsyncSession = Depends(get_session)):
    """执行整理任务

    流程：preview → 用户确认 → execute
    """
    try:
        tasks = await file_organize_service.preview_organize(
            session,
            movie_ids=body.movie_ids,
            job_type=body.job_type,
            output_dir=body.output_dir,
            template=body.template,
            conflict_strategy=body.conflict_strategy,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not tasks:
        return {"executed": 0, "results": [], "message": "无可执行任务"}

    results = await file_organize_service.execute_organize(session, tasks)

    return {
        "executed": len(results),
        "completed": sum(1 for r in results if r.status == "completed"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "results": [
            {
                "job_id": r.job_id,
                "movie_id": r.movie_id,
                "source_path": r.source_path,
                "target_path": r.target_path,
                "job_type": r.job_type,
                "status": r.status,
                "error_message": r.error_message,
                "file_size": r.file_size,
            }
            for r in results
        ],
    }


@router.get("/jobs", summary="列出整理任务")
async def list_jobs(
    status: str | None = Query(None, description="按状态过滤"),
    job_type: str | None = Query(None, description="按模式过滤"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """列出整理任务历史"""
    jobs = await file_organize_service.list_jobs(session, status, job_type, limit, offset)
    return {
        "total": len(jobs),
        "items": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "source_path": j.source_path,
                "target_path": j.target_path,
                "movie_id": j.movie_id,
                "status": j.status,
                "conflict_strategy": j.conflict_strategy,
                "error_message": j.error_message,
                "file_size": j.file_size,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
    }


@router.get("/stats", summary="获取任务统计")
async def get_job_stats(session: AsyncSession = Depends(get_session)):
    """获取各状态任务数量"""
    return await file_organize_service.get_job_stats(session)
