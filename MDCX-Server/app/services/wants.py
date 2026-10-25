"""想要清单服务：待找片子的记录与入库情况检查

与 favorites（已入库收藏）互补：本服务管**还没找到**的番号。核心能力：
- CRUD（ normalized_code 匹配键，ssis-001 与 SSIS-001 同条）
- check：实时查各模块 movies 表，给每条 want 标出
  - in_library          已入库（返回模块名）
  - chinese_available   该 base 番号已有中字版（is_chinese=1）入库
  - upgrade_candidate   本地已有非中文版（file_path 在 + is_chinese=0），
                        即「出了中字版可以替换」——订阅中字替换的判定基础

base 番号匹配：剥离 -C/-UC/-U/-LTX 等版本后缀后比对（SSIS-001 与 SSIS-001-C
是不同影片，但属于同一 base）。全只读，不写任何模块库。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select, or_

from app.db.database import get_database
from app.db.system_models import WantsItem
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 版本后缀：与 duplicate_scanner 的 -C/-UC/-U 口径一致，另加 -LTX（高清无码）
_SUFFIX_RE = re.compile(r"[-_.\s]?(?:LTX|ltx|UC|uc|C|U)$")


def normalize_code(code: str) -> str:
    """番号归一化：大写 + 去首尾/内部空白。仅用于匹配键，不改用户原文。"""
    if not code:
        return ""
    return re.sub(r"\s+", "", str(code)).upper()


def base_code(code: str) -> str:
    """剥掉版本后缀取 base 番号：SSIS-001-C → SSIS-001，ABC-123-UC → ABC-123。

    只剥一次（ABC-123-C-LTX 这类双后缀少见，且剥多了会误伤正常番号）。
    """
    c = normalize_code(code)
    if not c:
        return ""
    return _SUFFIX_RE.sub("", c) or c


async def list_wants(
    user_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict]:
    """列出想要清单（不含入库检查，纯列表）"""
    db = get_database()
    async with db.session() as session:
        stmt = select(WantsItem)
        if user_id is None:
            stmt = stmt.where(WantsItem.user_id.is_(None))
        else:
            stmt = stmt.where(
                or_(WantsItem.user_id == user_id, WantsItem.user_id.is_(None))
            )
        if status:
            stmt = stmt.where(WantsItem.status == status)
        stmt = stmt.order_by(WantsItem.priority.desc(), WantsItem.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]


def _to_dict(row: WantsItem) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "code": row.code,
        "normalized_code": row.normalized_code,
        "base_code": base_code(row.code),
        "title": row.title,
        "note": row.note,
        "status": row.status,
        "priority": row.priority,
        "magnet": row.magnet,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def add_want(
    code: str,
    user_id: Optional[int] = None,
    title: Optional[str] = None,
    note: Optional[str] = None,
    priority: int = 0,
    magnet: Optional[str] = None,
) -> dict:
    """添加想要条目。同 (user_id, normalized_code) 已存在则更新原记录。"""
    normalized = normalize_code(code)
    if not normalized:
        raise ValueError("番号不能为空")
    db = get_database()
    async with db.session() as session:
        if user_id is None:
            stmt = select(WantsItem).where(
                WantsItem.user_id.is_(None),
                WantsItem.normalized_code == normalized,
            )
        else:
            stmt = select(WantsItem).where(
                WantsItem.user_id == user_id,
                WantsItem.normalized_code == normalized,
            )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            # 已记录：刷新为 wanted（用户重新想要），并更新可选字段
            existing.status = "wanted"
            if title is not None:
                existing.title = title
            if note is not None:
                existing.note = note
            if priority:
                existing.priority = priority
            if magnet is not None:
                existing.magnet = magnet
            existing.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(existing)
            return _to_dict(existing)

        item = WantsItem(
            user_id=user_id,
            code=str(code).strip(),
            normalized_code=normalized,
            title=title,
            note=note,
            status="wanted",
            priority=priority or 0,
            magnet=magnet,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return _to_dict(item)


async def update_want(
    want_id: int,
    user_id: Optional[int] = None,
    status: Optional[str] = None,
    title: Optional[str] = None,
    note: Optional[str] = None,
    priority: Optional[int] = None,
    magnet: Optional[str] = None,
) -> dict:
    """更新条目（status/title/note/priority/magnet，只改传了的字段）"""
    db = get_database()
    async with db.session() as session:
        item = await session.get(WantsItem, want_id)
        if item is None:
            raise KeyError(f"想要条目不存在: {want_id}")
        if status is not None:
            item.status = status
        if title is not None:
            item.title = title
        if note is not None:
            item.note = note
        if priority is not None:
            item.priority = priority
        if magnet is not None:
            item.magnet = magnet
        item.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(item)
        return _to_dict(item)


async def delete_want(want_id: int) -> bool:
    """删除条目"""
    db = get_database()
    async with db.session() as session:
        item = await session.get(WantsItem, want_id)
        if item is None:
            return False
        await session.delete(item)
        await session.commit()
        return True


async def check_wants(user_id: Optional[int] = None) -> list[dict]:
    """批量检查清单条目的入库情况（只读模块库）。

    每条返回 in_library / chinese_available / upgrade_candidate：
    - in_library: 精确番号已入库（模块名，多个取第一个）
    - chinese_available: base 番号已有 is_chinese=1 的影片
    - upgrade_candidate: base 番号存在「本地有文件的非中文版」——
      出了中字版且本地是旧版，就是可替换对象
    """
    from app.utils.module_helper import get_module_model, get_module_session

    items = await list_wants(user_id=user_id)
    if not items:
        return []

    # 一次性收集所有 base 番号，按模块批量查（避免每条 want 全模块轮询）
    base_codes = {i["base_code"] for i in items if i["base_code"]}

    # module -> {base_code: {"total": n, "chinese": n, "local_non_cn": n}}
    per_module: dict[str, dict[str, dict[str, int]]] = {}

    # 逐模块查（模块库各自独立 session）
    for module in ("jav", "fc2", "uncensored", "chinese", "western", "pornhub"):
        try:
            Movie = get_module_model(module, "movie")
        except Exception:
            continue  # 模块未启用
        try:
            sess = await get_module_session(module)
        except Exception:
            continue
        try:
            async with sess:
                rows = (await sess.execute(
                    select(Movie.code, Movie.file_path, Movie.is_chinese)
                )).all()
        except Exception as e:
            logger.debug(f"[wants] 模块 {module} 查询失败: {e}")
            continue
        stats: dict[str, dict[str, int]] = {}
        for code, file_path, is_chinese in rows:
            if not code:
                continue
            bc = base_code(code)
            if bc not in base_codes:
                continue
            s = stats.setdefault(bc, {"total": 0, "chinese": 0, "local_non_cn": 0})
            s["total"] += 1
            if is_chinese:
                s["chinese"] += 1
            elif file_path:
                s["local_non_cn"] += 1
        if stats:
            per_module[module] = stats

    results = []
    for item in items:
        bc, nc = item["base_code"], item["normalized_code"]
        in_library = None
        chinese_available = False
        upgrade_candidate = False
        for module, stats in per_module.items():
            s = stats.get(bc)
            if not s:
                continue
            if in_library is None and s["total"] > 0:
                in_library = module
            if s["chinese"] > 0:
                chinese_available = True
            if s["local_non_cn"] > 0:
                upgrade_candidate = True
        out = dict(item)
        out.update({
            "in_library": in_library,
            "chinese_available": chinese_available,
            "upgrade_candidate": upgrade_candidate,
        })
        results.append(out)
    return results


__all__ = [
    "normalize_code", "base_code",
    "list_wants", "add_want", "update_want", "delete_want", "check_wants",
]
