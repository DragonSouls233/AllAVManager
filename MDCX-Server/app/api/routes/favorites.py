"""
收藏夹路由

参考 JavBoss 的多实体收藏设计，单表 FavoriteGroup 通过 entity_type 区分四类：
- movie / actor / studio / series

API 端点：
- GET    /api/v1/favorites/groups          - 列出收藏夹（可按 entity_type 筛选）
- POST   /api/v1/favorites/groups          - 创建收藏夹
- PATCH  /api/v1/favorites/groups/{id}      - 更新收藏夹（名称/排序）
- DELETE /api/v1/favorites/groups/{id}      - 删除收藏夹（级联删除条目）
- GET    /api/v1/favorites/groups/{id}/items - 列出收藏夹内条目（含实体详情）
- POST   /api/v1/favorites/groups/{id}/items - 添加条目到收藏夹
- DELETE /api/v1/favorites/groups/{id}/items/{entity_id} - 从收藏夹移除条目
- PUT    /api/v1/favorites/groups/{id}/item-order - 调整条目排序
- GET    /api/v1/favorites/check            - 检查某实体是否已在任意收藏夹中
"""
import importlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.system_models import FavoriteGroup, FavoriteItem
from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_ENTITY_TYPES = {"movie", "actor", "studio", "series"}


# ===== 请求/响应模型 =====

class CreateGroupRequest(BaseModel):
    name: str
    entity_type: str  # movie/actor/studio/series


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class AddItemRequest(BaseModel):
    entity_id: int


class ItemOrderRequest(BaseModel):
    item_ids: list[int]  # 按顺序排列的条目 ID


class GroupResponse(BaseModel):
    id: int
    name: str
    entity_type: str
    sort_order: int
    item_count: int = 0

    class Config:
        from_attributes = True


class ItemResponse(BaseModel):
    id: int
    group_id: int
    entity_id: int
    entity_type: str
    sort_order: int
    module: str = "jav"
    entity_name: Optional[str] = None
    entity_cover: Optional[str] = None

    class Config:
        from_attributes = True


# ===== 辅助函数 =====

def _get_mod_cls(module: str, cls_name: str):
    """获取模块中的任意模型类"""
    mod_path, _, _ = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


async def _get_entity_info(entity_type: str, entity_id: int, module: str) -> dict:
    """获取实体的名称和封面（必须指定模块）"""
    if not module or module not in MODULE_MODELS:
        return {"name": None, "cover": None}

    sess = await get_module_session(module)
    async with sess:
        if entity_type == "movie":
            cls = get_module_model(module, "movie")
            m = await sess.get(cls, entity_id)
            if m:
                return {"name": m.title or m.code, "cover": getattr(m, "cover_url", None)}
        elif entity_type == "actor":
            cls = get_module_model(module, "actor")
            a = await sess.get(cls, entity_id)
            if a:
                return {"name": a.name, "cover": getattr(a, "avatar_url", None)}
        elif entity_type == "studio":
            cls = _get_mod_cls(module, "Studio")
            s = await sess.get(cls, entity_id)
            if s:
                return {"name": s.name, "cover": None}
        elif entity_type == "series":
            cls = _get_mod_cls(module, "Series")
            s = await sess.get(cls, entity_id)
            if s:
                return {"name": s.name, "cover": None}
        return {"name": None, "cover": None}


# ===== 收藏夹 CRUD =====

@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(
    entity_type: Optional[str] = Query(None, description="筛选实体类型: movie/actor/studio/series"),
    session: AsyncSession = Depends(get_session),
):
    """列出所有收藏夹"""
    query = select(FavoriteGroup).order_by(FavoriteGroup.sort_order, FavoriteGroup.id)
    if entity_type:
        if entity_type not in VALID_ENTITY_TYPES:
            raise HTTPException(status_code=400, detail=f"无效的 entity_type: {entity_type}")
        query = query.where(FavoriteGroup.entity_type == entity_type)

    result = await session.execute(query)
    groups = result.scalars().all()

    group_ids = [g.id for g in groups]
    counts = {}
    if group_ids:
        count_query = (
            select(FavoriteItem.group_id, func.count())
            .where(FavoriteItem.group_id.in_(group_ids))
            .group_by(FavoriteItem.group_id)
        )
        count_result = await session.execute(count_query)
        counts = {row[0]: row[1] for row in count_result.fetchall()}

    return [
        GroupResponse(
            id=g.id,
            name=g.name,
            entity_type=g.entity_type,
            sort_order=g.sort_order,
            item_count=counts.get(g.id, 0),
        )
        for g in groups
    ]


@router.post("/groups", response_model=GroupResponse)
async def create_group(
    req: CreateGroupRequest,
    session: AsyncSession = Depends(get_session),
):
    """创建收藏夹"""
    if req.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的 entity_type: {req.entity_type}")

    group = FavoriteGroup(name=req.name, entity_type=req.entity_type)
    session.add(group)
    await session.commit()
    await session.refresh(group)

    return GroupResponse(
        id=group.id, name=group.name, entity_type=group.entity_type,
        sort_order=group.sort_order, item_count=0,
    )


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: int,
    req: UpdateGroupRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新收藏夹（名称/排序）"""
    group = await session.get(FavoriteGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    if req.name is not None:
        group.name = req.name
    if req.sort_order is not None:
        group.sort_order = req.sort_order

    await session.commit()
    return {"status": "ok"}


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除收藏夹（级联删除条目）"""
    group = await session.get(FavoriteGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    await session.delete(group)
    await session.commit()
    return {"status": "ok"}


# ===== 收藏夹条目管理 =====

@router.get("/groups/{group_id}/items", response_model=list[ItemResponse])
async def list_items(
    group_id: int,
    session: AsyncSession = Depends(get_session),
):
    """列出收藏夹内所有条目（含实体名称/封面）"""
    group = await session.get(FavoriteGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    result = await session.execute(
        select(FavoriteItem)
        .where(FavoriteItem.group_id == group_id)
        .order_by(FavoriteItem.sort_order, FavoriteItem.id)
    )
    items = result.scalars().all()

    resp = []
    for item in items:
        mod = getattr(item, "module", "") or "jav"
        info = await _get_entity_info(item.entity_type, item.entity_id, mod)
        resp.append(ItemResponse(
            id=item.id,
            group_id=item.group_id,
            entity_id=item.entity_id,
            entity_type=item.entity_type,
            sort_order=item.sort_order,
            module=mod,
            entity_name=info["name"],
            entity_cover=info["cover"],
        ))
    return resp


@router.post("/groups/{group_id}/items")
async def add_item(
    group_id: int,
    req: AddItemRequest,
    module: str = Query("jav", description="模块名 jav/fc2/uncensored/chinese/western/pornhub"),
    session: AsyncSession = Depends(get_session),
):
    """添加条目到收藏夹"""
    group = await session.get(FavoriteGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    existing = await session.scalar(
        select(FavoriteItem).where(
            and_(
                FavoriteItem.group_id == group_id,
                FavoriteItem.entity_id == req.entity_id,
                FavoriteItem.module == (module or "jav"),
            )
        )
    )
    if existing:
        return {"status": "exists", "message": "该条目已在收藏夹中"}

    max_sort = await session.scalar(
        select(func.max(FavoriteItem.sort_order)).where(FavoriteItem.group_id == group_id)
    )

    item = FavoriteItem(
        group_id=group_id,
        entity_id=req.entity_id,
        entity_type=group.entity_type,
        module=module or "jav",
        sort_order=(max_sort or 0) + 1,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    info = await _get_entity_info(item.entity_type, item.entity_id, module or "jav")

    return {
        "status": "ok",
        "item": ItemResponse(
            id=item.id,
            group_id=item.group_id,
            entity_id=item.entity_id,
            entity_type=item.entity_type,
            sort_order=item.sort_order,
            entity_name=info["name"],
            entity_cover=info["cover"],
        ),
    }


@router.delete("/groups/{group_id}/items/{entity_id}")
async def delete_item(
    group_id: int,
    entity_id: int,
    module: str = Query("jav", description="模块名 jav/fc2/uncensored/chinese/western/pornhub"),
    session: AsyncSession = Depends(get_session),
):
    """从收藏夹移除条目"""
    result = await session.execute(
        delete(FavoriteItem).where(
            and_(
                FavoriteItem.group_id == group_id,
                FavoriteItem.entity_id == entity_id,
                FavoriteItem.module == (module or "jav"),
            )
        )
    )
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="条目不存在")
    return {"status": "ok"}


@router.put("/groups/{group_id}/item-order")
async def update_item_order(
    group_id: int,
    req: ItemOrderRequest,
    session: AsyncSession = Depends(get_session),
):
    """调整收藏夹内条目的排序"""
    group = await session.get(FavoriteGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    for idx, item_id in enumerate(req.item_ids):
        item = await session.get(FavoriteItem, item_id)
        if item and item.group_id == group_id:
            item.sort_order = idx + 1

    await session.commit()
    return {"status": "ok"}


# ===== 查询辅助 =====

@router.get("/check")
async def check_favorite(
    entity_type: str = Query(...),
    entity_id: int = Query(...),
    module: str = Query("jav", description="模块名 jav/fc2/uncensored/chinese/western/pornhub"),
    session: AsyncSession = Depends(get_session),
):
    """检查某实体是否已在任意收藏夹中"""
    where_clause = and_(
        FavoriteItem.entity_type == entity_type,
        FavoriteItem.entity_id == entity_id,
        FavoriteItem.module == (module or "jav"),
    )

    result = await session.execute(
        select(FavoriteItem.group_id, FavoriteGroup.name)
        .join(FavoriteGroup, FavoriteItem.group_id == FavoriteGroup.id)
        .where(where_clause)
    )
    groups = [{"group_id": row[0], "group_name": row[1]} for row in result.fetchall()]
    return {"entity_id": entity_id, "in_favorites": len(groups) > 0, "groups": groups}
