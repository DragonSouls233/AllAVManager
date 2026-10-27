"""跨模块观影队列 API（v3.0）

三个队列，全部跨模块聚合：
- ``unseen``      未看：从未播放过且未标记为已观看
- ``watch_later`` 稍后看：用户显式加入待看队列
- ``flagged``     已标记：人工标记的重点/待处理条目

依赖 movies 表新增的两列 ``watch_later`` / ``flagged``（Bool），
由 ``ModuleDatabase._migrate_schema`` 自动为旧库补齐，无需手写迁移。
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update

from app.utils.module_helper import (
    MODULE_MODELS,
    get_module_model,
    get_module_session,
)

router = APIRouter()

QUEUES = ("unseen", "watch_later", "flagged")
QUEUE_FIELDS = ("watch_later", "flagged")

_MODULE_LABELS = {
    "jav": "JAV有码",
    "uncensored": "JAV无码",
    "fc2": "FC2",
    "pornhub": "PORNHUB",
    "anime": "里番",
    "western": "欧美",
    "chinese": "国产",
}


# ======================================================================
# 内部工具
# ======================================================================

def _available_modules() -> list[str]:
    """返回磁盘上真实存在库文件的模块，避免为未使用模块凭空建库。

    ``ModuleDatabase.get_instance`` 首调用即会创建 db 文件，因此这里先用
    同样的路径规则判存在性，不存在直接跳过。
    """
    from app.config.manager import get_config

    try:
        db_url = get_config().database.url
        base_dir = Path(db_url.split("///")[-1]).parent if "///" in db_url else Path("data/database")
    except Exception:
        base_dir = Path("data/database")

    out: list[str] = []
    for m in MODULE_MODELS:
        p = base_dir / f"{m}.db"
        try:
            if p.exists() and p.stat().st_size > 0:
                out.append(m)
        except OSError:
            continue
    return out


def _resolve_modules(module: str) -> list[str]:
    """`all` → 全部可用模块；否则单模块。未知模块名抛 400。"""
    available = _available_modules()
    if module == "all":
        # 没有任何库文件时返回空，绝不 fallback 到某个默认模块（会凭空建库）
        return available
    if module not in MODULE_MODELS:
        raise HTTPException(400, f"未知模块: {module}，有效值: {list(MODULE_MODELS)} 或 all")
    return [module] if module in available else []


def _queue_condition(Movie, queue: str):
    """生成队列过滤条件"""
    if queue == "unseen":
        # 从未播过（play_count 为空或 0），且没被标成已观看
        return and_(
            or_(Movie.play_count.is_(None), Movie.play_count == 0),
            or_(Movie.view_status.is_(None), Movie.view_status != "watched"),
        )
    if queue == "watch_later":
        return Movie.watch_later == True  # noqa: E712
    if queue == "flagged":
        return Movie.flagged == True  # noqa: E712
    raise HTTPException(400, f"未知队列: {queue}，有效值: {list(QUEUES)}")


def _serialize(m, module: str) -> dict:
    return {
        "id": m.id,
        "module": module,
        "module_label": _MODULE_LABELS.get(module, module),
        "code": m.code,
        "title": m.title,
        "cover_url": m.cover_url,
        "thumb_url": m.thumb_url,
        "actor": m.actor,
        "studio": m.studio,
        "release_date": m.release_date,
        "duration": m.duration,
        "rating": m.rating,
        "play_count": m.play_count or 0,
        "view_status": m.view_status,
        "watch_later": bool(m.watch_later),
        "flagged": bool(m.flagged),
        "status": m.status,
        "file_path": m.file_path,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "last_played_at": m.last_played_at.isoformat() if m.last_played_at else None,
    }


_SORT_COLUMNS = {
    "updated_at": lambda M: M.updated_at,
    "created_at": lambda M: M.created_at,
    "release_date": lambda M: M.release_date,
    "code": lambda M: M.code,
    "rating": lambda M: M.rating,
}


async def _collect(module: str, queue: str, limit: int, offset: int, sort_by: str,
                   desc: bool, session=None):
    """单模块取候选；多模块场景下多取一些供外层归并排序

    🔴 ``session`` 必须复用：每个裸 session 在请求结束前一直占用连接池槽位，
    按队列逐个建 session 会在多模块聚合时耗尽池（pool 5 + overflow 10）。
    """
    Movie = get_module_model(module, "movie")
    session = session or await get_module_session(module)
    col_fn = _SORT_COLUMNS.get(sort_by, _SORT_COLUMNS["updated_at"])
    col = col_fn(Movie)
    stmt = (
        select(Movie)
        .where(_queue_condition(Movie, queue))
        .order_by(col.desc() if desc else col.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(m, module) for m in rows]


async def _count(module: str, queue: str, session=None) -> int:
    Movie = get_module_model(module, "movie")
    session = session or await get_module_session(module)
    r = await session.execute(
        select(func.count(Movie.id)).where(_queue_condition(Movie, queue))
    )
    return int(r.scalar() or 0)


def _sort_key(item: dict, sort_by: str):
    v = item.get(sort_by)
    return (v is None, v if v is not None else "")


# ======================================================================
# 请求模型
# ======================================================================

class ToggleRequest(BaseModel):
    module: str = Field(..., description="模块名")
    movie_id: int = Field(..., description="影片 id")
    field: str = Field(..., description="watch_later / flagged")
    value: bool | None = Field(None, description="true/false；None 表示取反")


class BatchToggleRequest(BaseModel):
    module: str
    movie_ids: list[int] = Field(..., min_length=1, max_length=1000)
    field: str
    value: bool


# ======================================================================
# 路由
# ======================================================================

@router.get("/stats", summary="三队列跨模块统计")
async def get_queue_stats(module: str = Query("all", description="模块名或 all")):
    """统计 unseen / watch_later / flagged 三个队列的数量"""
    modules = _resolve_modules(module)
    per_module: dict[str, dict[str, int]] = {}
    totals = {q: 0 for q in QUEUES}

    for m in modules:
        try:
            # 单模块单 session：避免 N 队列 × M 模块 的 session 数把连接池占满
            session = await get_module_session(m)
            counts = {q: await _count(m, q, session) for q in QUEUES}
        except Exception:
            continue
        per_module[m] = {"label": _MODULE_LABELS.get(m, m), **counts}
        for q in QUEUES:
            totals[q] += counts[q]

    return {"totals": totals, "per_module": per_module}


@router.get("/movies", summary="列出队列影片")
async def list_queue_movies(
    queue: str = Query("unseen", description="unseen / watch_later / flagged"),
    module: str = Query("all", description="模块名或 all"),
    limit: int = Query(48, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("updated_at", description="updated_at/created_at/release_date/code/rating"),
    sort_dir: str = Query("desc", description="asc / desc"),
):
    """列出某队列的影片。多模块时逐模块取 candidates 再归并排序切片。"""
    if queue not in QUEUES:
        raise HTTPException(400, f"未知队列: {queue}，有效值: {list(QUEUES)}")
    if sort_by not in _SORT_COLUMNS:
        raise HTTPException(400, f"无效排序字段: {sort_by}，有效值: {list(_SORT_COLUMNS)}")

    modules = _resolve_modules(module)
    desc = sort_dir != "asc"

    if len(modules) <= 1:
        if not modules:
            return {"queue": queue, "total": 0, "items": []}
        m = modules[0]
        session = await get_module_session(m)
        items = await _collect(m, queue, limit, offset, sort_by, desc, session)
        return {"queue": queue, "total": await _count(m, queue, session), "items": items}

    # 多模块归并：每模块取 offset+limit 条候选后统一排序再切片，
    # 保证浅分页准确；深分页属近似（避免全表拉取到应用层）。
    take = min(offset + limit, 2000)
    merged: list[dict] = []
    for m in modules:
        try:
            session = await get_module_session(m)
            merged.extend(await _collect(m, queue, take, 0, sort_by, desc, session))
        except Exception:
            continue
    merged.sort(key=lambda i: _sort_key(i, sort_by), reverse=desc)
    return {
        "queue": queue,
        "total": None,  # 多模块精确 total 由 /stats 提供，避免 N 次全表 count
        "items": merged[offset: offset + limit],
    }


@router.post("/toggle", summary="切换单部影片队列标记")
async def toggle_queue_flag(body: ToggleRequest):
    """设置/取反某部影片的 watch_later 或 flagged 标记"""
    if body.field not in QUEUE_FIELDS:
        raise HTTPException(400, f"无效字段: {body.field}，有效值: {list(QUEUE_FIELDS)}")

    Movie = get_module_model(body.module, "movie")
    session = await get_module_session(body.module)
    movie = await session.get(Movie, body.movie_id)
    if not movie:
        raise HTTPException(404, f"影片 {body.movie_id} 不存在")

    current = bool(getattr(movie, body.field))
    new_value = (not current) if body.value is None else body.value
    setattr(movie, body.field, new_value)
    await session.commit()

    return {
        "module": body.module,
        "movie_id": body.movie_id,
        "field": body.field,
        "value": new_value,
    }


@router.post("/batch", summary="批量设置队列标记")
async def batch_toggle_queue_flag(body: BatchToggleRequest):
    """批量设置同一模块多部影片的队列标记"""
    if body.field not in QUEUE_FIELDS:
        raise HTTPException(400, f"无效字段: {body.field}，有效值: {list(QUEUE_FIELDS)}")

    Movie = get_module_model(body.module, "movie")
    session = await get_module_session(body.module)
    result = await session.execute(
        update(Movie).where(Movie.id.in_(body.movie_ids)).values({body.field: body.value})
    )
    await session.commit()

    return {
        "module": body.module,
        "field": body.field,
        "value": body.value,
        "updated": result.rowcount or 0,
        "total_requested": len(body.movie_ids),
    }


@router.post("/clear", summary="清空某队列标记")
async def clear_queue(
    field: str = Query(..., description="watch_later / flagged"),
    module: str = Query(..., description="模块名，不支持 all"),
):
    """把指定模块内该字段的所有 true 复位为 false"""
    if field not in QUEUE_FIELDS:
        raise HTTPException(400, f"无效字段: {field}，有效值: {list(QUEUE_FIELDS)}")
    if module not in MODULE_MODELS:
        raise HTTPException(400, f"未知模块: {module}")

    Movie = get_module_model(module, "movie")
    session = await get_module_session(module)
    result = await session.execute(
        update(Movie).where(Movie.__table__.c[field] == True).values({field: False})  # noqa: E712
    )
    await session.commit()
    return {"module": module, "field": field, "cleared": result.rowcount or 0}


@router.get("/export", summary="导出队列 CSV")
async def export_queue_csv(
    queue: str = Query("watch_later", description="watch_later / flagged / unseen"),
    module: str = Query("all", description="模块名或 all"),
    limit: int = Query(5000, ge=1, le=20000),
):
    """导出队列清单为 CSV（UTF-8 BOM，Excel 直开中文不乱码）"""
    if queue not in QUEUES:
        raise HTTPException(400, f"未知队列: {queue}，有效值: {list(QUEUES)}")

    modules = _resolve_modules(module)
    rows: list[dict] = []
    for m in modules:
        try:
            session = await get_module_session(m)
            rows.extend(await _collect(m, queue, limit, 0, "updated_at", True, session))
        except Exception:
            continue

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["模块", "番号", "标题", "演员", "厂商", "发行日期", "时长(分)",
         "评分", "播放次数", "观看状态", "文件路径", "更新时间"]
    )
    for r in rows[:limit]:
        writer.writerow([
            r["module_label"], r["code"], r["title"] or "", r["actor"] or "",
            r["studio"] or "", r["release_date"] or "", r["duration"] or "",
            r["rating"] if r["rating"] is not None else "", r["play_count"],
            r["view_status"] or "", r["file_path"] or "", r["updated_at"] or "",
        ])

    buf.seek(0)
    filename = f"queue-{queue}-{module}.csv"
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
