"""影片-演员关联表（movie_actors）同步工具

## 为什么需要这个模块（2026-10-04 实测）

`movie_actors` 关联表在 6 个模块模型里**都存在**（`_module_mixins.py::MovieActorMixin`），
但实测生产库除 pornhub（23 行）外**全部为 0 行**，于是：

- `actors.movie_count` 恒为 0（`api/routes/actors.py:261` 直接读该列）
- 按演员查影片只能回退 `movies.actor` 文本 `LIKE '%name%'`
  （`actors.py:566/674` 的注释都写明"关联表始终为空"）
- 文本 LIKE 无法区分 `Anna Cherry` 与 `Anna Cherry7`，也无法处理多演员拆分

真因不是"表不存在"，而是**写入点覆盖不全**：

| 落库路径 | 是否写 movie_actors |
|---|---|
| `scraper/workflow.py::_save_to_module_db` | ✅ 写了（仅 batch_scrape / jav_routes 调用） |
| `patcher/strategy.py::_update_module_database`（**补刮主路径**） | ❌ 裸 SQL UPDATE，不碰关联表 |
| `tasks/*_scanner.py`（6 个扫描器） | ❌ 只有 chinese_scanner 写 |

补刮是修复存量数据的主力入口，却完全不维护关联表 ⇒ 表永远补不齐。
本模块提供幂等的同步函数，供上述各路径复用。
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

# 并行补刮时同一演员可能被多个协程同时创建，靠这层进程内锁避免
# "唯一约束冲突" 异常（name 有 UNIQUE 索引，但先查后插仍有竞态窗口）。
import asyncio

_NAME_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(module: str) -> asyncio.Lock:
    lock = _NAME_LOCKS.get(module)
    if lock is None:
        lock = _NAME_LOCKS[module] = asyncio.Lock()
    return lock


def split_actor_names(raw: object) -> list[str]:
    """把演员字段拆成去重后的名字列表。

    兼容三种形态：
      - ``"Anna Cherry,Danny"``（movies.actor 文本列，逗号分隔）
      - ``"Anna Cherry"``（单个名字，可能含空格/点号，如 ``Anna Cherry.7``）
      - ``["Anna Cherry", "Danny"]``（已是列表）
    """
    if raw is None:
        return []
    items: Iterable[object]
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        text = str(raw)
        # 优先按中英文逗号 / 顿号 / 斜杠切；不按空格切，避免切坏 "Anna Cherry"
        for sep in ("，", "、", "/", ";", "|"):
            text = text.replace(sep, ",")
        items = text.split(",")

    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        name = str(it).strip().strip(".").strip()
        if not name or len(name) > 100:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


async def sync_movie_actors(
    session,
    module: str,
    movie_id: int,
    names: object,
    *,
    source: str = "scraper",
    recount: bool = True,
) -> int:
    """幂等同步某部影片的演员关联，返回成功关联的演员数。

    Args:
        session: 目标模块库的 SQLAlchemy 异步 session（调用方负责 commit）
        module: 模块名（jav / fc2 / uncensored / western / pornhub / chinese）
        movie_id: 目标影片在该模块 movies 表的主键
        names: 演员名，可以是列表，也可以是逗号分隔文本（见 :func:`split_actor_names`）
        source: 新建演员记录时写入的 source 标记
        recount: 是否重算受影响演员的 ``movie_count``（写操作较多时可关掉批量重算）

    失败不抛出：演员关联是辅助数据，绝不能因为它让整个补刮事务回滚。
    """
    try:
        from app.utils.module_helper import get_module_model

        ActorCls = get_module_model(module, "actor")
        MovieActorCls = get_module_model(module, "movie_actor")
    except Exception as e:  # pragma: no cover - 模块名/模型缺失
        logger.debug("movie_actor 模型解析失败 [%s]: %s", module, e)
        return 0

    if not movie_id:
        return 0

    name_list = split_actor_names(names)
    if not name_list:
        return 0

    try:
        from app.utils.actor_name_guard import is_plausible_actor_name
    except Exception:
        is_plausible_actor_name = None  # type: ignore[assignment]

    async with _lock_for(module):
        linked = 0
        touched_actor_ids: list[int] = []
        for name in name_list:
            if is_plausible_actor_name is not None and not is_plausible_actor_name(name):
                logger.debug("演员名未通过守卫，跳过关联 [%s] %r", module, name)
                continue
            try:
                found = (
                    await session.execute(select(ActorCls).where(ActorCls.name == name))
                ).scalar_one_or_none()
                if found is None:
                    # 大小写不敏感兜底：库里可能是 "anna cherry"
                    found = (
                        await session.execute(
                            select(ActorCls).where(
                                func.lower(ActorCls.name) == name.lower()
                            )
                        )
                    ).scalars().first()
                if found is None:
                    found = ActorCls(name=name, source=source, movie_count=0)
                    session.add(found)
                    await session.flush()
                actor_id = found.id
                if not actor_id:
                    continue
                touched_actor_ids.append(actor_id)

                exists = (
                    await session.execute(
                        select(MovieActorCls).where(
                            MovieActorCls.movie_id == movie_id,
                            MovieActorCls.actor_id == actor_id,
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    session.add(MovieActorCls(movie_id=movie_id, actor_id=actor_id))
                linked += 1
            except Exception as e:
                # 单个演员失败不影响其余，也不影响主事务
                logger.debug("演员关联失败 [%s] movie=%s %r: %s", module, movie_id, name, e)

        if recount and touched_actor_ids:
            for aid in set(touched_actor_ids):
                try:
                    cnt = (
                        await session.execute(
                            select(func.count(MovieActorCls.movie_id)).where(
                                MovieActorCls.actor_id == aid
                            )
                        )
                    ).scalar_one()
                    # 用 ORM 赋值而不是 Core update，避免同一 session 混用两种方式
                    actor_obj = (
                        await session.execute(select(ActorCls).where(ActorCls.id == aid))
                    ).scalar_one_or_none()
                    if actor_obj is not None:
                        actor_obj.movie_count = int(cnt or 0)
                except Exception as e:
                    logger.debug("movie_count 重算失败 [%s] actor=%s: %s", module, aid, e)

    return linked


async def recount_actor_movie_counts(session, module: str) -> dict:
    """全量重算某模块所有演员的 movie_count（一次性修复脚本用）。"""
    from app.utils.module_helper import get_module_model

    ActorCls = get_module_model(module, "actor")
    MovieActorCls = get_module_model(module, "movie_actor")

    rows = (
        await session.execute(
            select(MovieActorCls.actor_id, func.count(MovieActorCls.movie_id))
            .group_by(MovieActorCls.actor_id)
        )
    ).all()
    counts = {int(a): int(c) for a, c in rows}

    actors = (await session.execute(select(ActorCls))).scalars().all()
    changed = 0
    for a in actors:
        want = counts.get(a.id, 0)
        if (a.movie_count or 0) != want:
            a.movie_count = want
            changed += 1
    await session.commit()
    return {"actors": len(actors), "changed": changed, "linked": len(counts)}


def existing_actor_names(text: Optional[str]) -> list[str]:
    """兼容入口：从 movies.actor 文本列取名字列表。"""
    return split_actor_names(text)
