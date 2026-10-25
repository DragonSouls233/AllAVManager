"""播放列表服务：跨模块连播队列

- 列表/条目 CRUD（条目 = (module, movie_id)，jav + PH 可混排）
- resolve_items：把条目解析成有序 file_path 列表（跳过无文件/文件已失效的），
  供 mpv 多文件连播（mpv 原生支持，按序播放）
- 条目去重：同 (playlist, module, movie_id) 唯一；重复添加时上移到末尾
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func

from app.db.database import get_database, init_database
from app.db.system_models import Playlist, PlaylistItem
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _playlist_dict(p: Playlist, item_count: int = 0) -> dict:
    return {
        "id": p.id,
        "user_id": p.user_id,
        "name": p.name,
        "description": p.description,
        "item_count": item_count,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _item_dict(i: PlaylistItem, meta: Optional[dict] = None) -> dict:
    d = {
        "id": i.id,
        "module": i.module,
        "movie_id": i.movie_id,
        "sort_order": i.sort_order,
        "added_at": i.added_at.isoformat() if i.added_at else None,
    }
    if meta:
        d.update(meta)  # code/title/cover_url/file_path/missing
    return d


async def _get_item_meta(module: str, movie_ids: list[int]) -> dict[int, dict]:
    """批量取影片元信息（code/title/cover/file_path），模块库各自查"""
    from app.utils.module_helper import get_module_model, get_module_session

    if not movie_ids:
        return {}
    meta: dict[int, dict] = {}
    try:
        Movie = get_module_model(module, "movie")
        sess = await get_module_session(module)
        async with sess:
            rows = (await sess.execute(
                select(Movie.id, Movie.code, Movie.title, Movie.cover_url, Movie.file_path)
                .where(Movie.id.in_(movie_ids))
            )).all()
            for mid, code, title, cover, fp in rows:
                meta[mid] = {
                    "code": code, "title": title,
                    "cover_url": cover, "file_path": fp,
                    "missing": not bool(fp),
                }
    except Exception as e:
        logger.debug(f"[playlists] 模块 {module} 元信息查询失败: {e}")
    return meta


async def list_playlists(user_id: Optional[int] = None) -> list[dict]:
    """列出播放列表（含条目数）"""
    db = get_database()
    async with db.session() as session:
        stmt = select(Playlist)
        if user_id is None:
            stmt = stmt.where(Playlist.user_id.is_(None))
        else:
            stmt = stmt.where(
                (Playlist.user_id == user_id) | (Playlist.user_id.is_(None))
            )
        stmt = stmt.order_by(Playlist.updated_at.desc().nullslast(), Playlist.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
        out = []
        for p in rows:
            cnt = (await session.execute(
                select(func.count(PlaylistItem.id)).where(PlaylistItem.playlist_id == p.id)
            )).scalar_one()
            out.append(_playlist_dict(p, cnt))
        return out


async def get_playlist(playlist_id: int, with_items: bool = True) -> dict:
    """取单个播放列表（可选带条目 + 影片元信息）"""
    db = get_database()
    async with db.session() as session:
        p = await session.get(Playlist, playlist_id)
        if p is None:
            raise KeyError(f"播放列表不存在: {playlist_id}")
        d = _playlist_dict(p)
        if with_items:
            items = (await session.execute(
                select(PlaylistItem).where(PlaylistItem.playlist_id == p.id)
                .order_by(PlaylistItem.sort_order)
            )).scalars().all()
            d["item_count"] = len(items)
            # 逐条取影片元信息（清单一般几十条，逐条查询可接受；
            # 条目跨模块，无法用一次 IN 查询覆盖）
            d["items"] = []
            for it in items:
                m = await _get_item_meta(it.module, [it.movie_id])
                d["items"].append(_item_dict(it, m.get(it.movie_id)))
        return d


async def create_playlist(
    name: str,
    user_id: Optional[int] = None,
    description: Optional[str] = None,
) -> dict:
    """创建播放列表"""
    name = (name or "").strip()
    if not name:
        raise ValueError("列表名不能为空")
    db = get_database()
    async with db.session() as session:
        p = Playlist(user_id=user_id, name=name, description=description)
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return _playlist_dict(p, 0)


async def rename_playlist(
    playlist_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """重命名/改描述"""
    db = get_database()
    async with db.session() as session:
        p = await session.get(Playlist, playlist_id)
        if p is None:
            raise KeyError(f"播放列表不存在: {playlist_id}")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("列表名不能为空")
            p.name = name
        if description is not None:
            p.description = description
        await session.commit()
        await session.refresh(p)
        return _playlist_dict(p)


async def delete_playlist(playlist_id: int) -> bool:
    """删除播放列表（条目级联删）"""
    db = get_database()
    async with db.session() as session:
        p = await session.get(Playlist, playlist_id)
        if p is None:
            return False
        await session.delete(p)
        await session.commit()
        return True


async def add_item(playlist_id: int, module: str, movie_id: int) -> dict:
    """添加影片到列表（重复则上移到末尾）"""
    db = get_database()
    async with db.session() as session:
        p = await session.get(Playlist, playlist_id)
        if p is None:
            raise KeyError(f"播放列表不存在: {playlist_id}")
        existing = (await session.execute(
            select(PlaylistItem).where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.module == module,
                PlaylistItem.movie_id == movie_id,
            )
        )).scalar_one_or_none()
        # 新 sort_order = 当前最大值 + 1
        max_order = (await session.execute(
            select(func.coalesce(func.max(PlaylistItem.sort_order), -1))
            .where(PlaylistItem.playlist_id == playlist_id)
        )).scalar_one()
        if existing:
            existing.sort_order = max_order + 1
            item = existing
        else:
            item = PlaylistItem(
                playlist_id=playlist_id, module=module,
                movie_id=movie_id, sort_order=max_order + 1,
            )
            session.add(item)
        await session.commit()
        await session.refresh(item)
        return _item_dict(item)


async def remove_item(item_id: int) -> bool:
    """移除条目"""
    db = get_database()
    async with db.session() as session:
        item = await session.get(PlaylistItem, item_id)
        if item is None:
            return False
        await session.delete(item)
        await session.commit()
        return True


async def move_item(item_id: int, direction: int) -> dict:
    """上移/下移条目（direction: -1 上移 / +1 下移，与相邻交换 sort_order）"""
    db = get_database()
    async with db.session() as session:
        item = await session.get(PlaylistItem, item_id)
        if item is None:
            raise KeyError(f"条目不存在: {item_id}")
        siblings = (await session.execute(
            select(PlaylistItem).where(PlaylistItem.playlist_id == item.playlist_id)
            .order_by(PlaylistItem.sort_order)
        )).scalars().all()
        idx = next((k for k, s in enumerate(siblings) if s.id == item_id), None)
        if idx is None:
            raise KeyError(f"条目不存在: {item_id}")
        target = idx + direction
        if target < 0 or target >= len(siblings):
            return _item_dict(item)  # 已到边界，原样返回
        # 交换 sort_order
        other = siblings[target]
        item.sort_order, other.sort_order = other.sort_order, item.sort_order
        await session.commit()
        await session.refresh(item)
        return _item_dict(item)


async def resolve_playback(playlist_id: int) -> dict:
    """解析播放列表为有序可播文件（跳过无文件/文件失效的条目）

    Returns:
        {"playlist_id", "name", "total", "playable", "skipped",
         "files": [{"module", "movie_id", "code", "file_path"}]}
    """
    import os

    data = await get_playlist(playlist_id, with_items=True)
    files, skipped = [], 0
    for it in data.get("items", []):
        fp = it.get("file_path")
        if not fp or not os.path.isfile(str(fp)):
            skipped += 1
            continue
        files.append({
            "module": it["module"],
            "movie_id": it["movie_id"],
            "code": it.get("code"),
            "file_path": str(fp),
        })
    return {
        "playlist_id": playlist_id,
        "name": data["name"],
        "total": len(data.get("items", [])),
        "playable": len(files),
        "skipped": skipped,
        "files": files,
    }


__all__ = [
    "list_playlists", "get_playlist", "create_playlist", "rename_playlist",
    "delete_playlist", "add_item", "remove_item", "move_item", "resolve_playback",
]
