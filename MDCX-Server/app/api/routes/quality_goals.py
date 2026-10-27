"""高清版目标 API /quality-goals

给某部片子设定「想要更高清版本」，替换文件后检测达成情况。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db.system_db import SystemDatabase
from app.db.system_models import QualityGoal
from app.services import quality_goals as qg
from app.utils.module_helper import MODULE_MODELS

router = APIRouter()

_STATUS_OPEN = "open"
_STATUS_FULFILLED = "fulfilled"
_STATUS_DROPPED = "dropped"
VALID_STATUSES = (_STATUS_OPEN, _STATUS_FULFILLED, _STATUS_DROPPED)


async def _session():
    return await SystemDatabase.get_instance().get_session()


def _serialize(goal) -> dict:
    """快照序列化：不跑 ffprobe，列表页秒开"""
    return {
        "id": goal.id,
        "module": goal.module,
        "code": goal.code,
        "title": goal.title,
        "target_height": goal.target_height,
        "target_label": qg.height_label(goal.target_height),
        "current_height": goal.current_height,
        "current_width": goal.current_width,
        "current_label": qg.height_label(goal.current_height),
        # 由「上次快照」算出是否达成，列表页不必跑 ffprobe
        "reached": bool(goal.current_height and goal.current_height >= goal.target_height),
        "file_path": goal.file_path,
        "detected_at": goal.detected_at.isoformat() if goal.detected_at else None,
        "status": goal.status,
        "note": goal.note,
        "fulfilled_at": goal.fulfilled_at.isoformat() if goal.fulfilled_at else None,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
    }


# ======================================================================
# 请求模型
# ======================================================================

class GoalCreate(BaseModel):
    module: str = Field(..., description="jav/fc2/uncensored/pornhub/anime/western/chinese")
    codes: list[str] = Field(..., min_length=1, max_length=200, description="番号列表，支持批量")
    target_height: int = Field(2160, ge=1, le=4320, description="目标垂直像素，如 2160=4K")
    note: str = Field("", max_length=200)


class GoalUpdate(BaseModel):
    target_height: int | None = Field(None, ge=1, le=4320)
    status: str | None = Field(None, description="open / fulfilled / dropped")
    note: str | None = Field(None, max_length=200)


# ======================================================================
# 路由
# ======================================================================

@router.get("/presets", summary="目标档位预设")
async def list_presets():
    return {"presets": [{"height": h, "label": lb} for h, lb in qg.TARGET_PRESETS]}


@router.get("/stats", summary="目标达成统计")
async def goal_stats():
    session = await _session()
    rows = (await session.execute(
        select(QualityGoal.status, func.count(QualityGoal.id)).group_by(QualityGoal.status)
    )).all()
    counts = {s: 0 for s in VALID_STATUSES}
    total = 0
    for status, n in rows:
        counts[status] = n
        total += n
    return {"total": total, "by_status": counts}


@router.get("", summary="列出目标（读快照，不探测）")
async def list_goals(
    status: str | None = Query(None, description="open / fulfilled / dropped"),
    module: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    if status and status not in VALID_STATUSES:
        raise HTTPException(400, f"无效 status: {status}，有效值: {list(VALID_STATUSES)}")

    session = await _session()
    stmt = select(QualityGoal).order_by(QualityGoal.created_at.desc())
    if status:
        stmt = stmt.where(QualityGoal.status == status)
    if module:
        stmt = stmt.where(QualityGoal.module == module)
    goals = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    return {
        "items": [_serialize(g) for g in goals],
        "total": len(goals),
    }


@router.post("", summary="新增目标（支持批量番号）")
async def create_goals(body: GoalCreate):
    if body.module not in MODULE_MODELS:
        raise HTTPException(400, f"未知模块: {body.module}，有效值: {list(MODULE_MODELS)}")

    session = await _session()
    created, skipped = [], []

    for raw in body.codes:
        code = (raw or "").strip()
        if not code:
            continue
        norm = qg.normalize_code(code)
        exists = (await session.execute(
            select(QualityGoal).where(
                QualityGoal.module == body.module,
                QualityGoal.normalized_code == norm,
            )
        )).scalars().first()
        if exists:
            skipped.append(code)
            continue

        goal = QualityGoal(
            module=body.module,
            code=code,
            normalized_code=norm,
            target_height=body.target_height,
            note=body.note,
            status=_STATUS_OPEN,
        )
        session.add(goal)
        created.append(code)

    await session.commit()
    return {
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "target_height": body.target_height,
        "target_label": qg.height_label(body.target_height),
    }


@router.patch("/{goal_id}", summary="修改目标")
async def update_goal(goal_id: int, body: GoalUpdate):
    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(400, f"无效 status: {body.status}，有效值: {list(VALID_STATUSES)}")

    session = await _session()
    goal = await session.get(QualityGoal, goal_id)
    if not goal:
        raise HTTPException(404, f"目标 {goal_id} 不存在")

    if body.target_height is not None:
        goal.target_height = body.target_height
        # 目标调高后若原本已达成，退回待达成状态重新观察
        if goal.current_height and goal.current_height < body.target_height:
            goal.status = _STATUS_OPEN
            goal.fulfilled_at = None
    if body.status is not None:
        goal.status = body.status
        goal.fulfilled_at = datetime.utcnow() if body.status == _STATUS_FULFILLED else None
    if body.note is not None:
        goal.note = body.note
    goal.updated_at = datetime.utcnow()

    await session.commit()
    return _serialize(goal)


@router.delete("/{goal_id}", summary="删除目标")
async def delete_goal(goal_id: int):
    session = await _session()
    goal = await session.get(QualityGoal, goal_id)
    if not goal:
        raise HTTPException(404, f"目标 {goal_id} 不存在")
    await session.delete(goal)
    await session.commit()
    return {"deleted": goal_id}


@router.post("/{goal_id}/check", summary="检测单个目标")
async def check_one(goal_id: int):
    """现场 ffprobe 该目标的当前文件，判断是否达到目标分辨率"""
    session = await _session()
    goal = await session.get(QualityGoal, goal_id)
    if not goal:
        raise HTTPException(404, f"目标 {goal_id} 不存在")
    result = await qg.evaluate_goal(goal, session, probe=True)
    await session.commit()
    return result


@router.post("/check", summary="批量检测全部待达成目标")
async def check_all(
    limit: int = Query(100, ge=1, le=1000, description="本次最多检测数量"),
):
    """对所有 open 目标跑一遍 ffprobe 检测。

    ⚠️ 每个目标一次子进程，数量大时很慢，用 limit 封顶。
    """
    session = await _session()
    goals = (await session.execute(
        select(QualityGoal)
        .where(QualityGoal.status == _STATUS_OPEN)
        .order_by(QualityGoal.created_at.asc())
        .limit(limit)
    )).scalars().all()

    results = []
    fulfilled_now = 0
    for g in goals:
        res = await qg.evaluate_goal(g, session, probe=True)
        results.append(res)
        if g.status == _STATUS_FULFILLED:
            fulfilled_now += 1
    await session.commit()

    return {
        "checked": len(results),
        "fulfilled_now": fulfilled_now,
        "items": results,
    }
