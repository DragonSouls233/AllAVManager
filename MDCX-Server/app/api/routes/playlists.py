"""播放列表 API 路由（跨模块连播队列，系统库）

GET    /api/v1/playlists                  → 列表（含条目数）
POST   /api/v1/playlists                  → 创建
GET    /api/v1/playlists/{id}             → 详情（含条目 + 影片元信息）
PUT    /api/v1/playlists/{id}             → 重命名/改描述
DELETE /api/v1/playlists/{id}             → 删除（条目级联）
POST   /api/v1/playlists/{id}/items       → 添加影片 {module, movie_id}
DELETE /api/v1/playlists/{id}/items/{item_id} → 移除条目
POST   /api/v1/playlists/{id}/items/{item_id}/move → 上移/下移 {direction: -1/+1}
GET    /api/v1/playlists/{id}/playback     → 解析为有序可播文件（跳过失效条目）
POST   /api/v1/playlists/{id}/play         → mpv 连播整个列表
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import playlists as svc
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class PlaylistCreate(BaseModel):
    name: str
    user_id: Optional[int] = None
    description: Optional[str] = None


class PlaylistUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ItemAdd(BaseModel):
    module: str = "jav"
    movie_id: int


class ItemMove(BaseModel):
    direction: int  # -1 上移 / +1 下移


@router.get("")
async def list_playlists_endpoint(user_id: Optional[int] = None):
    return {"items": await svc.list_playlists(user_id=user_id)}


@router.post("")
async def create_playlist_endpoint(body: PlaylistCreate):
    try:
        return await svc.create_playlist(
            name=body.name, user_id=body.user_id, description=body.description)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"[playlists] 创建失败: {e}", exc_info=True)
        raise HTTPException(500, f"创建失败：{type(e).__name__}: {e}")


@router.get("/{playlist_id}")
async def get_playlist_endpoint(playlist_id: int):
    try:
        return await svc.get_playlist(playlist_id, with_items=True)
    except KeyError:
        raise HTTPException(404, "播放列表不存在")


@router.put("/{playlist_id}")
async def update_playlist_endpoint(playlist_id: int, body: PlaylistUpdate):
    try:
        return await svc.rename_playlist(
            playlist_id, name=body.name, description=body.description)
    except KeyError:
        raise HTTPException(404, "播放列表不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{playlist_id}")
async def delete_playlist_endpoint(playlist_id: int):
    if not await svc.delete_playlist(playlist_id):
        raise HTTPException(404, "播放列表不存在")
    return {"ok": True}


@router.post("/{playlist_id}/items")
async def add_item_endpoint(playlist_id: int, body: ItemAdd):
    try:
        return await svc.add_item(playlist_id, body.module, body.movie_id)
    except KeyError:
        raise HTTPException(404, "播放列表不存在")
    except Exception as e:
        logger.error(f"[playlists] 添加条目失败: {e}", exc_info=True)
        raise HTTPException(500, f"添加失败：{type(e).__name__}: {e}")


@router.delete("/{playlist_id}/items/{item_id}")
async def remove_item_endpoint(playlist_id: int, item_id: int):
    if not await svc.remove_item(item_id):
        raise HTTPException(404, "条目不存在")
    return {"ok": True}


@router.post("/{playlist_id}/items/{item_id}/move")
async def move_item_endpoint(playlist_id: int, item_id: int, body: ItemMove):
    try:
        return await svc.move_item(item_id, body.direction)
    except KeyError:
        raise HTTPException(404, "条目不存在")


@router.get("/{playlist_id}/playback")
async def playback_endpoint(playlist_id: int):
    """解析播放列表为有序可播文件（跳过无文件/文件失效的）"""
    try:
        return await svc.resolve_playback(playlist_id)
    except KeyError:
        raise HTTPException(404, "播放列表不存在")


@router.post("/{playlist_id}/play")
async def play_endpoint(playlist_id: int):
    """mpv 连播整个列表（按 sort_order，mpv 原生多文件连播）"""
    try:
        resolved = await svc.resolve_playback(playlist_id)
    except KeyError:
        raise HTTPException(404, "播放列表不存在")
    files = resolved.get("files") or []
    if not files:
        raise HTTPException(400, "列表里没有可播放的文件（无文件或文件已失效）")

    from app.services.mpv_player import play_files
    result = await play_files([f["file_path"] for f in files])
    if result.get("status") == "error":
        raise HTTPException(503, result.get("message", "mpv 启动失败"))
    result["skipped"] = resolved.get("skipped", 0)
    result["playlist_name"] = resolved.get("name")
    return result
