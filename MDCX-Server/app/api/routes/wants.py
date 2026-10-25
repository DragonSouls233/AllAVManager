"""想要清单 API 路由（跨模块，存系统库）

GET    /api/v1/wants              → 列表（?status=wanted/found/dropped）
GET    /api/v1/wants/check        → 列表 + 实时入库检查（中字版可替换标记）
POST   /api/v1/wants              → 添加（番号必填，重复记同条会刷新）
PUT    /api/v1/wants/{id}         → 更新（status/title/note/priority/magnet）
DELETE /api/v1/wants/{id}         → 删除

磁力资源（wants_resources 服务，只读搜索 + 转交下载器）：
POST   /api/v1/wants/resources         → 按番号搜磁力资源（?code=&force=）
POST   /api/v1/wants/resources/send    → 把选中磁力发送到激活下载器
POST   /api/v1/wants/resources/clear   → 清空资源缓存
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import wants as svc
from app.services import wants_resources as resources
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


# ============================================================
# 磁力资源（wants_resources）
# ============================================================


class ResourceSearchBody(BaseModel):
    code: str
    force: bool = False  # 跳过缓存强制重搜（用户点「刷新」）


class ResourceSendBody(BaseModel):
    magnet: str
    download_dir: Optional[str] = None
    name: Optional[str] = None


@router.post("/resources")
async def search_resources_endpoint(body: ResourceSearchBody):
    """按番号搜磁力资源（sukebei 源，缓存 30 分钟，串行限速）

    items 按「中字优先 → 有做种 → 做种数 → 大小」排序，
    upgrade_candidate 场景用户要的中字版排最前。
    """
    if not body.code or not body.code.strip():
        raise HTTPException(400, "番号不能为空")
    try:
        return await resources.search_resources(body.code.strip(), force=body.force)
    except Exception as e:
        logger.error(f"[wants] 资源搜索失败: {e}", exc_info=True)
        raise HTTPException(500, f"资源搜索失败：{type(e).__name__}: {e}")


@router.post("/resources/send")
async def send_resource_endpoint(body: ResourceSendBody):
    """把选中磁力发送到当前激活的下载器（aria2/qb/tr）

    只转交任务，下载进度在下载页查看。
    🔴 本端点不回写 want 条目：磁链存回 want 由前端 ResourceDialog 在发送
    成功后调 `PUT /wants/{id}` 完成（本端点的 body 里没有 want_id）。
    """
    result = await resources.send_to_downloader(
        body.magnet, download_dir=body.download_dir, name=body.name)
    if result.get("status") != "ok":
        raise HTTPException(400, result.get("message", "发送下载失败"))
    return result


@router.post("/resources/clear")
async def clear_resources_endpoint():
    """清空资源缓存（设置页/排查用）"""
    n = resources.clear_cache()
    return {"ok": True, "cleared": n}
