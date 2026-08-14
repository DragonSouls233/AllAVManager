"""观影历史 + AI 观影报告路由"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.services import viewing_report as svc

router = APIRouter()


class RecordPlayRequest(BaseModel):
    movie_id: int
    user_id: Optional[int] = None
    duration_watched: int = 0       # 本次观看秒数
    progress: float = 0.0           # 0-1
    completed: bool = False
    total_duration: Optional[int] = None
    module: str = "jav"             # jav/uncensored/fc2/...
    # 前端播放器上报的兼容字段（position=当前播放位置秒数, duration=影片总时长）
    position: Optional[int] = None
    duration: Optional[int] = None


@router.post("/play")
async def record_play(
    request: Request,
    body: RecordPlayRequest,
):
    """记录一次播放（前端播放器定期上报）"""
    ip = request.client.host if request.client else None
    # 兼容前端字段：position/duration 缺失时回退到 duration_watched/progress
    duration_watched = body.duration_watched
    progress = body.progress
    if body.position is not None:
        duration_watched = body.position
        if body.duration:
            progress = min(1.0, body.position / body.duration)
    await svc.record_play(
        movie_id=body.movie_id,
        user_id=body.user_id,
        duration_watched=duration_watched,
        progress=progress,
        completed=body.completed,
        total_duration=body.total_duration,
        ip_address=ip,
        module=body.module,
    )
    return {"ok": True}


@router.get("/history")
async def history(
    user_id: Optional[int] = None,
    movie_id: Optional[int] = None,
    module: str = Query("jav"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询观影历史"""
    return await svc.list_play_history(
        user_id=user_id,
        module=module,
        limit=limit,
        offset=offset,
        movie_id=movie_id,
    )


@router.get("/report")
async def report(
    user_id: Optional[int] = None,
    module: str = Query("jav"),
    days: int = Query(30, ge=1, le=365),
):
    """生成 AI 观影报告"""
    try:
        return await svc.generate_report(user_id=user_id, module=module, days=days)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("生成观影报告失败")
        raise HTTPException(500, f"生成观影报告失败: {e}")
