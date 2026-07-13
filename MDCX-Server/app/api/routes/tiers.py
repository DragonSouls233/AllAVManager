"""Tier 分级系统路由

参考 JATLAS 项目的"空间预算"理念：用分级替代模糊喜好，
每个 Tier 设置数量上限，接近上限时预警，超量时标记风险。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Actor, ActorTier, TierConfig, AssetChangeLog, MovieActor

router = APIRouter()


# 默认 Tier 配置（首次访问时自动初始化）
DEFAULT_TIERS = [
    {"tier": "S", "name": "神话级", "max_count": 30, "color": "#FFD700", "sort_order": 1},
    {"tier": "A", "name": "传奇级", "max_count": 80, "color": "#FF6B6B", "sort_order": 2},
    {"tier": "B", "name": "优秀级", "max_count": 200, "color": "#4ECDC4", "sort_order": 3},
    {"tier": "C", "name": "普通级", "max_count": 500, "color": "#95A5A6", "sort_order": 4},
    {"tier": "D", "name": "收藏级", "max_count": 0, "color": "#FFFFFF", "sort_order": 5},  # 0 = 无上限
]


# ============== Pydantic 模型 ==============

class TierConfigItem(BaseModel):
    tier: str
    name: str
    max_count: int
    color: str
    sort_order: int


class TierConfigUpdate(BaseModel):
    items: list[TierConfigItem]


class ActorTierSet(BaseModel):
    tier: str  # S/A/B/C/D
    max_count: Optional[int] = None  # None=用全局, 0=无上限, >0=自定义
    notes: Optional[str] = None


class BatchTierSet(BaseModel):
    actor_ids: list[int]
    tier: str


class ChangeLogResponse(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    entity_name: Optional[str]
    change_type: str
    old_value: Optional[str]
    new_value: Optional[str]
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ============== 内部工具 ==============

async def _ensure_default_tiers(session: AsyncSession):
    """首次访问时初始化默认 Tier 配置"""
    result = await session.execute(select(func.count()).select_from(TierConfig))
    if result.scalar() == 0:
        for item in DEFAULT_TIERS:
            session.add(TierConfig(**item))
        await session.commit()


async def _log_change(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    entity_name: Optional[str],
    change_type: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    description: Optional[str] = None,
):
    """记录资产变化日志"""
    log = AssetChangeLog(
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        change_type=change_type,
        old_value=old_value,
        new_value=new_value,
        description=description,
    )
    session.add(log)


async def _get_actor_movie_count(session: AsyncSession, actor_id: int) -> int:
    """获取演员的影片数量"""
    result = await session.execute(
        select(func.count()).select_from(MovieActor).where(MovieActor.actor_id == actor_id)
    )
    return result.scalar() or 0


# ============== 路由 ==============

@router.get("/config")
async def get_tier_config(session: AsyncSession = Depends(get_session)):
    """获取分级档位配置"""
    await _ensure_default_tiers(session)
    result = await session.execute(
        select(TierConfig).order_by(TierConfig.sort_order)
    )
    items = result.scalars().all()
    return {
        "items": [
            {
                "tier": t.tier,
                "name": t.name,
                "max_count": t.max_count,
                "color": t.color,
                "sort_order": t.sort_order,
            }
            for t in items
        ]
    }


@router.put("/config")
async def update_tier_config(
    req: TierConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    """更新分级档位配置（整体覆盖）"""
    await _ensure_default_tiers(session)
    valid_tiers = {"S", "A", "B", "C", "D"}
    for item in req.items:
        if item.tier not in valid_tiers:
            raise HTTPException(status_code=400, detail=f"无效的 tier: {item.tier}")

    # 删除旧配置，写入新配置
    await session.execute(delete(TierConfig))
    for item in req.items:
        session.add(TierConfig(**item.model_dump()))
    await session.commit()

    return {"status": "ok", "count": len(req.items)}


@router.get("/dashboard")
async def get_tier_dashboard(session: AsyncSession = Depends(get_session)):
    """分级仪表盘：各档位统计 + 风险状态

    返回每个 Tier 的当前演员数、影片总数、上限、使用率、风险等级。
    """
    await _ensure_default_tiers(session)

    # 查询所有 Tier 配置
    tier_result = await session.execute(select(TierConfig).order_by(TierConfig.sort_order))
    tiers = tier_result.scalars().all()

    # 查询每个演员的 tier 和影片数
    # 用一条 SQL：actor_tiers JOIN actors LEFT JOIN movie_actors GROUP BY actor
    stmt = (
        select(
            ActorTier.tier.label("tier"),
            func.count(func.distinct(ActorTier.actor_id)).label("actor_count"),
            func.count(func.distinct(MovieActor.movie_id)).label("total_movies"),
        )
        .select_from(ActorTier)
        .outerjoin(Actor, ActorTier.actor_id == Actor.id)
        .outerjoin(MovieActor, Actor.id == MovieActor.actor_id)
        .group_by(ActorTier.tier)
    )
    result = await session.execute(stmt)
    tier_stats = {row.tier: {"actor_count": row.actor_count, "total_movies": row.total_movies} for row in result.fetchall()}

    # 统计未分级的演员数
    unassigned_result = await session.execute(
        select(func.count()).select_from(Actor).where(
            ~Actor.id.in_(select(ActorTier.actor_id))
        )
    )
    unassigned_count = unassigned_result.scalar() or 0

    # 构造仪表盘数据
    dashboard = []
    for t in tiers:
        stats = tier_stats.get(t.tier, {"actor_count": 0, "total_movies": 0})
        actor_count = stats["actor_count"]
        total_movies = stats["total_movies"]
        max_count = t.max_count

        # 风险等级：基于演员数量 vs 上限
        risk_level = "normal"
        risk_percent = 0
        if max_count > 0:
            risk_percent = round(actor_count / max_count * 100, 1)
            if risk_percent >= 100:
                risk_level = "overflow"  # 超量
            elif risk_percent >= 80:
                risk_level = "warning"  # 接近上限

        dashboard.append({
            "tier": t.tier,
            "name": t.name,
            "color": t.color,
            "sort_order": t.sort_order,
            "actor_count": actor_count,
            "total_movies": total_movies,
            "max_count": max_count,
            "risk_percent": risk_percent,
            "risk_level": risk_level,
        })

    return {
        "tiers": dashboard,
        "unassigned_count": unassigned_count,
    }


@router.get("/risk")
async def get_risk_actors(
    level: Optional[str] = Query(None, description="风险等级过滤: warning/overflow/normal"),
    session: AsyncSession = Depends(get_session),
):
    """风险状态列表：接近上限/超量的演员

    每个演员返回：tier、影片数、上限、使用率、风险等级。
    """
    await _ensure_default_tiers(session)

    # 查询已分级演员的影片数
    stmt = (
        select(
            ActorTier.actor_id.label("actor_id"),
            Actor.name.label("actor_name"),
            ActorTier.tier.label("tier"),
            func.count(func.distinct(MovieActor.movie_id)).label("movie_count"),
            TierConfig.max_count.label("max_count"),
            TierConfig.color.label("color"),
            TierConfig.name.label("tier_name"),
        )
        .select_from(ActorTier)
        .join(Actor, ActorTier.actor_id == Actor.id)
        .outerjoin(MovieActor, Actor.id == MovieActor.actor_id)
        .join(TierConfig, ActorTier.tier == TierConfig.tier)
        .group_by(ActorTier.actor_id, Actor.name, ActorTier.tier, TierConfig.max_count, TierConfig.color, TierConfig.name)
    )
    result = await session.execute(stmt)
    rows = result.fetchall()

    items = []
    for row in rows:
        max_count = row.max_count or 0
        movie_count = row.movie_count or 0
        risk_percent = round(movie_count / max_count * 100, 1) if max_count > 0 else 0
        risk_level = "normal"
        if max_count > 0:
            if risk_percent >= 100:
                risk_level = "overflow"
            elif risk_percent >= 80:
                risk_level = "warning"

        if level and risk_level != level:
            continue

        items.append({
            "actor_id": row.actor_id,
            "actor_name": row.actor_name,
            "tier": row.tier,
            "tier_name": row.tier_name,
            "color": row.color,
            "movie_count": movie_count,
            "max_count": max_count,
            "risk_percent": risk_percent,
            "risk_level": risk_level,
        })

    # 排序：风险高的在前
    items.sort(key=lambda x: (-{"overflow": 2, "warning": 1, "normal": 0}[x["risk_level"]], -x["risk_percent"]))

    return {
        "items": items,
        "total": len(items),
        "warning_count": sum(1 for i in items if i["risk_level"] == "warning"),
        "overflow_count": sum(1 for i in items if i["risk_level"] == "overflow"),
    }


@router.get("/actors/{actor_id}")
async def get_actor_tier(
    actor_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取单个演员的分级"""
    result = await session.execute(
        select(ActorTier).where(ActorTier.actor_id == actor_id)
    )
    tier = result.scalar_one_or_none()
    if not tier:
        return {"actor_id": actor_id, "tier": None, "max_count": None, "notes": None}
    return {
        "actor_id": tier.actor_id,
        "tier": tier.tier,
        "max_count": tier.max_count,
        "notes": tier.notes,
        "updated_at": tier.updated_at,
    }


@router.put("/actors/{actor_id}")
async def set_actor_tier(
    actor_id: int,
    req: ActorTierSet,
    session: AsyncSession = Depends(get_session),
):
    """设置演员分级"""
    valid_tiers = {"S", "A", "B", "C", "D"}
    if req.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"无效的 tier: {req.tier}，必须是 S/A/B/C/D")

    # 检查演员是否存在
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="演员不存在")

    # 查询现有 tier
    result = await session.execute(
        select(ActorTier).where(ActorTier.actor_id == actor_id)
    )
    existing = result.scalar_one_or_none()
    old_tier = existing.tier if existing else None

    if existing:
        existing.tier = req.tier
        existing.max_count = req.max_count if req.max_count is not None else 0
        existing.notes = req.notes
    else:
        existing = ActorTier(
            actor_id=actor_id,
            tier=req.tier,
            max_count=req.max_count if req.max_count is not None else 0,
            notes=req.notes,
        )
        session.add(existing)

    # 记录日志
    await _log_change(
        session, "actor", actor_id, actor.name,
        "tier_changed",
        old_value=old_tier,
        new_value=req.tier,
        description=f"演员 {actor.name} 分级从 {old_tier or '未分级'} 变更为 {req.tier}",
    )

    await session.commit()
    return {"status": "ok", "actor_id": actor_id, "tier": req.tier, "old_tier": old_tier}


@router.post("/batch")
async def batch_set_tier(
    req: BatchTierSet,
    session: AsyncSession = Depends(get_session),
):
    """批量设置演员分级"""
    valid_tiers = {"S", "A", "B", "C", "D"}
    if req.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"无效的 tier: {req.tier}")

    if not req.actor_ids:
        raise HTTPException(status_code=400, detail="演员 ID 列表不能为空")

    success = []
    for actor_id in req.actor_ids:
        actor = await session.get(Actor, actor_id)
        if not actor:
            continue

        result = await session.execute(
            select(ActorTier).where(ActorTier.actor_id == actor_id)
        )
        existing = result.scalar_one_or_none()
        old_tier = existing.tier if existing else None

        if existing:
            existing.tier = req.tier
        else:
            session.add(ActorTier(actor_id=actor_id, tier=req.tier, max_count=0))

        await _log_change(
            session, "actor", actor_id, actor.name,
            "tier_changed",
            old_value=old_tier,
            new_value=req.tier,
            description=f"批量分级：{actor.name} → {req.tier}",
        )
        success.append(actor_id)

    await session.commit()
    return {"status": "ok", "success_count": len(success), "actor_ids": success}


@router.delete("/actors/{actor_id}")
async def remove_actor_tier(
    actor_id: int,
    session: AsyncSession = Depends(get_session),
):
    """移除演员分级（回到未分级状态）"""
    result = await session.execute(
        select(ActorTier).where(ActorTier.actor_id == actor_id)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        return {"status": "ok", "message": "本就未分级"}

    actor = await session.get(Actor, actor_id)
    old_tier = existing.tier

    await session.delete(existing)
    await _log_change(
        session, "actor", actor_id, actor.name if actor else None,
        "tier_changed",
        old_value=old_tier,
        new_value=None,
        description=f"演员 {actor.name if actor else actor_id} 移除分级 {old_tier}",
    )
    await session.commit()
    return {"status": "ok", "actor_id": actor_id, "old_tier": old_tier}


# ============== 资产变化日志 ==============

@router.get("/logs")
async def get_change_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    entity_type: Optional[str] = Query(None, description="实体类型: movie/actor/tag/studio/series"),
    change_type: Optional[str] = Query(None, description="变化类型: added/removed/tier_changed/rating_changed/scraped"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
):
    """资产变化日志（分页+筛选）"""
    query = select(AssetChangeLog)
    count_query = select(func.count()).select_from(AssetChangeLog)

    if entity_type:
        query = query.where(AssetChangeLog.entity_type == entity_type)
        count_query = count_query.where(AssetChangeLog.entity_type == entity_type)

    if change_type:
        query = query.where(AssetChangeLog.change_type == change_type)
        count_query = count_query.where(AssetChangeLog.change_type == change_type)

    if start_date:
        try:
            sd = datetime.fromisoformat(start_date)
            query = query.where(AssetChangeLog.created_at >= sd)
            count_query = count_query.where(AssetChangeLog.created_at >= sd)
        except ValueError:
            pass

    if end_date:
        try:
            ed = datetime.fromisoformat(end_date + "T23:59:59")
            query = query.where(AssetChangeLog.created_at <= ed)
            count_query = count_query.where(AssetChangeLog.created_at <= ed)
        except ValueError:
            pass

    # 总数
    total = (await session.execute(count_query)).scalar() or 0

    # 分页查询
    query = query.order_by(AssetChangeLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    items = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "entity_name": log.entity_name,
                "change_type": log.change_type,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "description": log.description,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in items
        ],
    }


@router.delete("/logs")
async def clear_change_logs(
    before_days: int = Query(30, ge=1, description="清除多少天前的日志"),
    session: AsyncSession = Depends(get_session),
):
    """清除旧日志"""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=before_days)
    result = await session.execute(
        delete(AssetChangeLog).where(AssetChangeLog.created_at < cutoff)
    )
    await session.commit()
    return {"status": "ok", "deleted": result.rowcount}
