"""
任务管理路由

API 端点：
- GET    /tasks              - 任务列表
- POST   /tasks              - 创建任务
- POST   /tasks/{id}/retry   - 重试任务
- DELETE /tasks/{id}         - 取消任务
- GET    /tasks/scheduled    - 定时任务列表
- POST   /tasks/scheduled    - 创建定时任务
- DELETE /tasks/scheduled/{job_id} - 删除定时任务
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskStatus, TaskType
from app.db.database import get_session
from app.db.models import Task

router = APIRouter()


class TaskCreate(BaseModel):
    """创建任务请求"""
    type: str
    movie_code: Optional[str] = None
    file_path: Optional[str] = None
    site: Optional[str] = None
    options: Optional[dict] = None


class TaskResponse(BaseModel):
    """任务响应模型"""
    id: int
    type: str
    status: str
    movie_code: Optional[str] = None
    file_path: Optional[str] = None
    error_message: Optional[str] = None
    result: Optional[str] = None
    retry_count: int = 0
    created_at: str
    finished_at: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int
    items: list[TaskResponse]


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """获取任务列表"""
    query = select(Task)

    if status:
        query = query.where(Task.status == status)

    if task_type:
        query = query.where(Task.type == task_type)

    # 计算总数
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(Task.created_at.desc())
    result = await session.execute(query)
    tasks = result.scalars().all()

    return TaskListResponse(
        total=total or 0,
        items=[
            TaskResponse(
                id=t.id,
                type=t.type,
                status=t.status,
                movie_code=t.movie_code,
                file_path=t.file_path,
                error_message=t.error_message,
                result=t.result,
                retry_count=t.retry_count or 0,
                created_at=t.created_at.isoformat() if t.created_at else "",
                finished_at=t.completed_at.isoformat() if t.completed_at else None,
            )
            for t in tasks
        ],
    )


@router.post("", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    """创建任务"""
    task = Task(
        type=task_data.type,
        movie_code=task_data.movie_code,
        file_path=task_data.file_path,
        site=task_data.site,
        options=str(task_data.options) if task_data.options else None,
        status=TaskStatus.PENDING.value,
    )

    session.add(task)
    await session.commit()
    await session.refresh(task)

    return TaskResponse(
        id=task.id,
        type=task.type,
        status=task.status,
        movie_code=task.movie_code,
        file_path=task.file_path,
        error_message=None,
        created_at=task.created_at.isoformat() if task.created_at else "",
    )


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    """重试任务"""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task.status = TaskStatus.PENDING.value
    task.retry_count += 1
    task.error_message = None
    await session.commit()

    return {"status": "ok"}


@router.delete("/{task_id}")
async def cancel_task(
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    """取消或删除任务"""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status in [TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value, TaskStatus.FAILED.value]:
        await session.delete(task)
        await session.commit()
        return {"status": "ok", "message": "任务已删除"}
    else:
        task.status = TaskStatus.CANCELLED.value
        await session.commit()
        return {"status": "ok", "message": "任务已取消"}


@router.post("/cleanup")
async def cleanup_tasks(
    status: str = Query("cancelled", description="要清理的任务状态"),
    older_than_hours: int = Query(24, ge=1),
    session: AsyncSession = Depends(get_session),
):
    """清理已完成/失败/取消的任务"""
    from datetime import datetime, timedelta
    
    cutoff = datetime.now() - timedelta(hours=older_than_hours)
    
    query = select(Task).where(
        Task.status == status,
        Task.created_at < cutoff,
    )
    result = await session.execute(query)
    tasks_to_delete = result.scalars().all()
    
    count = len(tasks_to_delete)
    
    for task in tasks_to_delete:
        await session.delete(task)
    
    await session.commit()
    
    return {"status": "ok", "message": f"已清理 {count} 个任务", "deleted_count": count}


# ===== 定时任务管理 =====

class ScheduledJobCreate(BaseModel):
    """创建定时任务请求"""
    job_id: str
    job_type: str  # scrape, import, patch
    cron: Optional[str] = None
    interval: Optional[int] = None
    directories: list[str] = []
    output_dir: Optional[str] = None


class ScheduledJobResponse(BaseModel):
    """定时任务响应"""
    id: str
    job_type: str
    next_run: Optional[str] = None
    trigger: Optional[str] = None


@router.get("/scheduled")
async def list_scheduled_jobs():
    """获取所有定时任务"""
    from app.tasks.scheduled import get_scheduled_task_manager

    manager = get_scheduled_task_manager()
    jobs = manager.get_jobs()

    return {
        "items": jobs,
        "total": len(jobs),
    }


@router.post("/scheduled")
async def create_scheduled_job(
    job_data: ScheduledJobCreate,
):
    """创建定时任务"""
    from app.tasks.scheduled import get_scheduled_task_manager

    manager = get_scheduled_task_manager()

    if job_data.job_type == "scrape":
        if not job_data.directories or not job_data.output_dir:
            raise HTTPException(status_code=400, detail="刮削任务需要指定目录和输出目录")
        manager.add_scrape_job(
            job_id=job_data.job_id,
            directories=job_data.directories,
            output_dir=job_data.output_dir,
            cron=job_data.cron,
            interval=job_data.interval,
        )
    elif job_data.job_type == "import":
        if not job_data.directories:
            raise HTTPException(status_code=400, detail="导入任务需要指定目录")
        manager.add_import_job(
            job_id=job_data.job_id,
            directory=job_data.directories[0],
            cron=job_data.cron,
            interval=job_data.interval,
        )
    elif job_data.job_type == "patch":
        manager.add_patch_job(
            job_id=job_data.job_id,
            cron=job_data.cron,
            interval=job_data.interval,
        )
    else:
        raise HTTPException(status_code=400, detail=f"不支持的任务类型: {job_data.job_type}")

    return {"status": "ok", "job_id": job_data.job_id}


@router.delete("/scheduled/{job_id}")
async def delete_scheduled_job(
    job_id: str,
):
    """删除定时任务"""
    from app.tasks.scheduled import get_scheduled_task_manager

    manager = get_scheduled_task_manager()
    success = manager.remove_job(job_id)

    if not success:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    return {"status": "ok"}
