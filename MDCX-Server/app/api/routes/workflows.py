"""
工作流管理路由
"""

from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Workflow, Movie

router = APIRouter()


class WorkflowResponse(BaseModel):
    """工作流响应模型"""
    id: int
    name: str
    description: Optional[str] = None
    enabled: bool
    schedule: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreateWorkflowRequest(BaseModel):
    """创建工作流请求"""
    name: str
    description: Optional[str] = None
    enabled: bool = True
    schedule: Optional[str] = None


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(session: AsyncSession = Depends(get_session)):
    """获取工作流列表"""
    result = await session.execute(select(Workflow))
    workflows = result.scalars().all()
    return [WorkflowResponse.model_validate(w) for w in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: int, session: AsyncSession = Depends(get_session)):
    """获取工作流详情"""
    workflow = await session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return WorkflowResponse.model_validate(workflow)


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    request: CreateWorkflowRequest,
    session: AsyncSession = Depends(get_session),
):
    """创建工作流"""
    workflow = Workflow(
        name=request.name,
        description=request.description,
        enabled=request.enabled,
        schedule=request.schedule,
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return WorkflowResponse.model_validate(workflow)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: int,
    request: CreateWorkflowRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新工作流"""
    workflow = await session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    workflow.name = request.name
    workflow.description = request.description
    workflow.enabled = request.enabled
    workflow.schedule = request.schedule
    
    await session.commit()
    await session.refresh(workflow)
    return WorkflowResponse.model_validate(workflow)


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: int, session: AsyncSession = Depends(get_session)):
    """删除工作流"""
    workflow = await session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    await session.delete(workflow)
    await session.commit()
    return {"status": "ok"}


@router.post("/scan-directory")
async def scan_directory(
    directories: Optional[List[str]] = Body(None, description="要扫描的目录列表，为空则使用配置中的媒体目录"),
    dry_run: bool = Body(False, description="是否仅预览不实际关联"),
    session: AsyncSession = Depends(get_session),
):
    """
    扫描目录并自动关联影片
    
    - 根据文件名提取番号
    - 在数据库中查找匹配的影片
    - 自动关联 file_path
    """
    from pathlib import Path
    from sqlalchemy import update
    from app.scraper.number import extract_number, normalize_number

    VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".iso", ".webm"}

    # 获取目录列表
    scan_dirs = directories
    if not scan_dirs:
        from app.config.manager import get_config_manager
        manager = get_config_manager()
        scan_dirs = manager.config.scraper.media_dirs or []

    if not scan_dirs:
        raise HTTPException(status_code=400, detail="未提供扫描目录，且配置中未设置媒体目录")

    # 扫描所有目录收集文件
    all_files = []
    for directory in scan_dirs:
        scan_dir = Path(directory)
        if not scan_dir.exists() or not scan_dir.is_dir():
            continue
        for f in scan_dir.rglob("*"):
            if f.suffix.lower() in VIDEO_EXTS and f.is_file():
                number_result = extract_number(f.name)
                if number_result.number:
                    normalized = normalize_number(number_result.number)
                    all_files.append({
                        "number": normalized,
                        "original_number": number_result.number,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "filename": f.name,
                    })

    # 获取数据库中所有未关联路径的影片
    query = select(Movie).where(Movie.file_path.is_(None))
    result = await session.execute(query)
    movies_without_path = result.scalars().all()

    # 建立番号到影片的映射
    movie_map = {}
    for movie in movies_without_path:
        if movie.code:
            normalized = normalize_number(movie.code)
            movie_map[normalized] = movie

    # 匹配并关联
    linked = []
    for file_info in all_files:
        normalized = file_info["number"]
        movie = movie_map.get(normalized)
        if movie:
            linked.append({
                "movie_id": movie.id,
                "code": movie.code,
                "title": movie.title,
                "path": file_info["path"],
                "size": file_info["size"],
            })
            if not dry_run:
                await session.execute(
                    update(Movie)
                    .where(Movie.id == movie.id)
                    .values(file_path=file_info["path"], file_size=file_info["size"])
                )
                del movie_map[normalized]

    if not dry_run:
        await session.commit()
        from app.api.routes.movies import _cache
        _cache.invalidate("movies:")

    return {
        "total_files_found": len(all_files),
        "movies_without_path": len(movies_without_path),
        "linked_count": len(linked),
        "not_found_count": len(movie_map),
        "dry_run": dry_run,
        "linked": linked[:50],
    }


@router.post("/run/{workflow_id}")
async def run_workflow(workflow_id: int, session: AsyncSession = Depends(get_session)):
    """手动执行工作流"""
    workflow = await session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    return {"status": "ok", "message": f"工作流 {workflow.name} 已触发"}
