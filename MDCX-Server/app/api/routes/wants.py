"""想要清单 API 路由（跨模块，存系统库）

GET    /api/v1/wants              → 列表（?status=wanted/found/dropped）
GET    /api/v1/wants/check        → 列表 + 实时入库检查（中字版可替换标记）
POST   /api/v1/wants              → 添加（番号必填，重复记同条会刷新）
PUT    /api/v1/wants/{id}         → 更新（status/title/note/priority/magnet）
DELETE /api/v1/wants/{id}         → 删除
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import wants as svc
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class WantCreate(BaseModel):
    code: str
    user_id: Optional[int] = None
    title: Optional[str] = None
    note: Optional[str] = None
    priority: int = 0
    magnet: Optional[str] = None


class WantUpdate(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    note: Optional[str] = None
    priority: Optional[int] = None
    magnet: Optional[str] = None


@router.get("")
async def list_wants_endpoint(
    status: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """列出想要清单"""
    return {"items": await svc.list_wants(user_id=user_id, status=status)}


@router.get("/check")
async def check_wants_endpoint(user_id: Optional[int] = None):
    """列出清单并实时检查入库情况（只读模块库）

    每条附 in_library（已入库模块）/ chinese_available（该 base 番号已有
    中字版）/ upgrade_candidate（本地有非中文版，出了中字版可替换）。
    """
    try:
        return {"items": await svc.check_wants(user_id=user_id)}
    except Exception as e:
        logger.error(f"[wants] 入库检查失败: {e}", exc_info=True)
        raise HTTPException(500, f"入库检查失败：{type(e).__name__}: {e}")


@router.post("")
async def add_want_endpoint(body: WantCreate):
    """添加想要条目"""
    try:
        return await svc.add_want(
            code=body.code,
            user_id=body.user_id,
            title=body.title,
            note=body.note,
            priority=body.priority,
            magnet=body.magnet,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"[wants] 添加失败: {e}", exc_info=True)
        raise HTTPException(500, f"添加失败：{type(e).__name__}: {e}")


@router.put("/{want_id}")
async def update_want_endpoint(want_id: int, body: WantUpdate):
    """更新条目（标记已找到/改备注/改优先级/存磁链）"""
    try:
        return await svc.update_want(
            want_id,
            status=body.status,
            title=body.title,
            note=body.note,
            priority=body.priority,
            magnet=body.magnet,
        )
    except KeyError:
        raise HTTPException(404, "条目不存在")
    except Exception as e:
        logger.error(f"[wants] 更新失败: {e}", exc_info=True)
        raise HTTPException(500, f"更新失败：{type(e).__name__}: {e}")


@router.delete("/{want_id}")
async def delete_want_endpoint(want_id: int):
    """删除条目"""
    ok = await svc.delete_want(want_id)
    if not ok:
        raise HTTPException(404, "条目不存在")
    return {"ok": True}
