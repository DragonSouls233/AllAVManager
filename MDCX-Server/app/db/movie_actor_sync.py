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


# --------------------------------------------------------------------------
# 归一化索引（2026-10 新增）：同一人多种写法 => 同一个 canon_key
# --------------------------------------------------------------------------

#: module -> (构建时间戳, {canon_key: (actor_id, canonical_name)})
_CANON_INDEX: dict[str, tuple[float, dict[str, tuple[int, str]]]] = {}

#: 索引 TTL（秒）。只影响「新增演员」后多久对其它协程可见；
#: 本协程新建的会立即写回缓存，所以批量刮削不会因此重复插入。
_CANON_TTL = 300.0


def invalidate_canon_index(module: str | None = None) -> None:
    """清空归一化索引。批量改名 / 合并演员后必须调用，否则拿到的是旧映射。"""
    if module is None:
        _CANON_INDEX.clear()
    else:
        _CANON_INDEX.pop(module, None)


def _remember_canon(module: str, name: str, actor_id: int, canonical: str) -> None:
    """把新建/已知演员登记进缓存，保持索引与库同步。"""
    try:
        from app.utils.actor_name_canon import canon_key

        k = canon_key(name)
        if not k:
            return
        entry = _CANON_INDEX.get(module)
        idx = entry[1] if entry else {}
        cur = idx.get(k)
        # 已存在且不是同一个 id 时不覆盖（先入库的通常信息更全）
        if cur is None or int(actor_id) == cur[0] or actor_id < cur[0]:
            idx[k] = (int(actor_id), canonical)
        _CANON_INDEX[module] = (_time.time(), idx)
    except Exception:  # pragma: no cover - 归一化是辅助逻辑，永不影响主流程
        pass


async def _canon_index(session, module: str, ActorCls) -> dict[str, tuple[int, str]]:
    """取（必要时构建）该模块的 归一键 -> (actor_id, 规范名) 映射。

    canonical 取「movie_count 最大、其次 id 最小」的那条 —— 与存量合并脚本
    `_merge_actor_alias.py::pick()` 的规则一致，保证「新建时选的规范名」
    和「合并存量时保留的行」是同一条，不会出现一边合并到 A、一边又建 B。
    """
    import time as _time_mod  # 局部导入，避免与模块级 import 混淆

    entry = _CANON_INDEX.get(module)
    if entry and (_time_mod.time() - entry[0]) < _CANON_TTL:
        return entry[1]

    from app.utils.actor_name_canon import canon_key

    rows = (
        await session.execute(select(ActorCls.id, ActorCls.name, ActorCls.movie_count))
    ).all()
    best: dict[str, tuple[int, int, str]] = {}
    for aid, name, mc in rows:
        if not name:
            continue
        k = canon_key(name)
        if not k:
            continue
        rank = (int(mc or 0), -int(aid))          # movie_count 降序、id 升序
        cur = best.get(k)
        if cur is None or rank > (cur[0], -cur[1]):
            best[k] = (int(mc or 0), int(aid), str(name))
    idx = {k: (v[1], v[2]) for k, v in best.items()}
    _CANON_INDEX[module] = (_time_mod.time(), idx)
    return idx


async def _find_by_canon_key(session, module: str, ActorCls, name: str):
    """按归一键查已有演员；命中则返回 ORM 对象，未命中返回 None。永不抛错。"""
    try:
        from app.utils.actor_name_canon import canon_key

        hit = (await _canon_index(session, module, ActorCls)).get(canon_key(name))
        if not hit:
            return None
        return (
            await session.execute(select(ActorCls).where(ActorCls.id == hit[0]))
        ).scalars().first()
    except Exception as e:  # pragma: no cover
        logger.debug("归一化查找失败 [%s] %r: %s", module, name, e)
        return None


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
                    # 🔴 归一化兜底（2026-10 新增）：库里同一个人的**简繁 / 括号别名 /
                    #    异体字 / 假名汉字化** 写法此前一律当新演员插入。
                    #    实测成因：森沢かな(78部) / 森沢かな（飯岡かなこ）(70部) /
                    #    森泽佳奈(52部) 被拆成三条，影片重叠 0~5 但厂牌完全一致。
                    #    精确匹配与 lower() 兜底都抓不到「簡体↔繁体」和「かな↔佳奈」。
                    found = await _find_by_canon_key(session, module, ActorCls, name)
                if found is None:
                    # 🔴 马甲兜底（2026-10 新增）：基础表 actor_base.aliases 收了
                    #    35378 条「别名 -> 规范名」（gfriends/avleague/wiki/javdb/dmm），
                    #    能吃掉「本名 vs 化名」这种 canon_key 吃不掉的**身份差异**。
                    #    查不到就静默降级，绝不让归一化阻塞落盘。
                    alias_hit = None
                    try:
                        from app.utils.actor_base_alias import resolve_alias

                        alias_hit = resolve_alias(name)
                    except Exception:
                        alias_hit = None
                    if alias_hit and alias_hit != name:
                        name = alias_hit
                        found = (
                            await session.execute(select(ActorCls).where(ActorCls.name == name))
                        ).scalar_one_or_none()
                        if found is None:
                            found = await _find_by_canon_key(session, module, ActorCls, name)
                if found is None:
                    new_actor = ActorCls(name=name, source=source, movie_count=0)
                    session.add(new_actor)
                    await session.flush()
                    # 新建后立刻并入缓存，否则同一批里的后几部片还会再插一条
                    _remember_canon(module, name, new_actor.id, name)
                    found = new_actor
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


# ==========================================================================
# 扫描器链路：文本列 → 关联表回填（2026-10-04 新增）
# ==========================================================================

#: 演员文本列候选，按"可信度从高到低"排列。
#: - ``actor``：刮削写入的正式列（jav / uncensored / pornhub / western / anime / fc2）
#: - ``extracted_actor``：chinese 扫描器从**目录名**推断的列
#: - ``folder_based_actors``：chinese 的另一份目录推断副本
#:
#: 🔴 chinese 模块**三列并存**且 ``actor`` 全为 NULL（真实库实测 3/3 部都是
#: NULL，只有 extracted_actor 有值）。所以不能"取第一个存在的列"——
#: 必须按优先级把**所有非空的列都读出来合并**，否则 chinese 会静默扫到 0 部。
_ACTOR_COLUMNS = ("actor", "extracted_actor", "folder_based_actors")


def _actor_columns(MovieCls) -> list[str]:
    """返回该模块实际存在、且按可信度排序的演员文本列。"""
    have = {c.name for c in MovieCls.__table__.columns}
    return [c for c in _ACTOR_COLUMNS if c in have]


async def backfill_links_from_text(
    session,
    module: str,
    *,
    limit: Optional[int] = None,
    recount: bool = False,
) -> dict:
    """把 ``movies`` 演员文本列整体回填成 ``movie_actors`` 关联行。

    这是扫描器链路的补齐入口 —— 实测 7 个模块里 6 个的 ``movie_actors``
    为 0 行：只有 chinese_scanner 写了关联表，jav / uncensored / pornhub
    只写 ``movies.actor`` 文本 + ``actors`` 表，导致：

    - ``actors.movie_count`` 只能用文本 ``LIKE '%name%'`` 统计；
    - SQLite 的 ``LIKE`` **默认大小写不敏感** ⇒ ``Ruth lee`` 与 ``Ruth Lee``
      被当成两个人，各虚增一次（实测 pornhub 库 id=12 / id=201 就是这么来的）；
    - 子串匹配会把 ``Anna Cherry`` 也算进 ``Anna Cherry7`` 的影片。

    关联表按 (movie_id, actor_id) 唯一约束写入，天然幂等，可重复执行。

    Args:
        limit: 最多处理多少部影片（调试用；``None`` = 全量）
        recount: 是否顺带重算 ``movie_count``。全量回填时建议 False，
            最后调一次 :func:`recount_actor_movie_counts` 即可（避免 N 次查询）。
    """
    from sqlalchemy import or_, select

    from app.utils.module_helper import get_module_model

    MovieCls = get_module_model(module, "movie")
    cols = _actor_columns(MovieCls)
    out = {
        "module": module,
        "columns": cols,
        "scanned": 0,
        "linked": 0,
        "no_valid_name": 0,
        "skipped_no_column": not cols,
    }
    if not cols:
        return out

    # 一条 WHERE 覆盖所有列（任一列非空即纳入），而不是逐列查再合并 ——
    # 逐列查会让 chinese 这类多列模块的影片被重复处理。
    where = or_(*[
        or_(getattr(MovieCls, c).isnot(None), getattr(MovieCls, c) != "")
        for c in cols
    ])
    stmt = select(
        MovieCls.id, *[getattr(MovieCls, c) for c in cols]
    ).where(where)
    if limit:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    out["scanned"] = len(rows)

    for row in rows:
        movie_id = row[0]
        # 合并所有列的名字：dedup 交给 split_actor_names（按 lower 去重）
        names: list[str] = []
        for raw in row[1:]:
            if raw:
                names.extend(split_actor_names(raw))
        n = await sync_movie_actors(
            session, module, movie_id, names,
            source="backfill", recount=recount,
        )
        if n:
            out["linked"] += n
        else:
            out["no_valid_name"] += 1

    return out


async def merge_actor_name_variants(
    session,
    module: str,
    *,
    dry_run: bool = True,
) -> dict:
    """合并仅大小写不同的演员行（``Ruth lee`` → ``Ruth Lee``）。

    真因：``sync_movie_actors`` 只在**精确匹配失败**后才做一次
    ``func.lower()`` 兜底查找，而扫描器走的是自己的 ``_sync_actors``，
    用 ``WHERE name = :n`` 精确匹配 —— SQLite 的 ``=`` 对 TEXT 是
    **大小写敏感**的，但两条链路的调用时机不同 ⇒ 同一个演员被插入两次
    （``actors.name`` 上并没有 UNIQUE 约束拦得住）。

    合并策略：保留 ``id`` 最小的行（先入库的通常信息更全），
    把其余行的 ``movie_actors`` 关联改挂到保留行，再删掉多余行。
    ``actor_tags`` / ``actor_tiers`` / ``actor_compare_sources`` 等
    外键表也一并改挂，否则删行会留下悬挂引用。

    ⚠️ 默认 ``dry_run=True``：这是**破坏性**操作（会 DELETE 演员行）。
    """
    from sqlalchemy import delete, select, update

    from app.utils.module_helper import get_module_model

    ActorCls = get_module_model(module, "actor")
    out: dict = {
        "module": module,
        "dry_run": dry_run,
        "groups": [],
        "merged": 0,
        "relinked": 0,
    }

    # 一次取回全部 (id, name)，在 Python 侧按 lower(name) 分组。
    # 🔴 不写成 SQL 的 `GROUP BY lower(name)`：那样要再回查一次取
    # 保留行，且 name 为 NULL/空串时语义容易踩坑。这里按万级数据量
    # 一次全取完全可接受。
    rows = (await session.execute(select(ActorCls.id, ActorCls.name))).all()
    groups: dict[str, list[tuple[int, str]]] = {}
    for aid, name in rows:
        if not name:
            continue
        groups.setdefault(str(name).strip().lower(), []).append((int(aid), str(name)))

    dups = {k: v for k, v in groups.items() if len(v) > 1}
    if not dups:
        return out

    MovieActorCls = get_module_model(module, "movie_actor")

    # 需要改挂的外键表（不同模块表集不同，缺表就跳过）
    fk_models = []
    for kind in ("tag", "tier", "compare_source"):
        try:
            fk_models.append(get_module_model(module, kind))
        except Exception:
            continue

    for _key, items in dups.items():
        items.sort(key=lambda t: t[0])
        keep_id, keep_name = items[0]
        drop_ids = [aid for aid, _ in items[1:]]
        out["groups"].append({
            "keep": {"id": keep_id, "name": keep_name},
            "drop": [{"id": i, "name": n} for i, n in items[1:]],
        })
        if dry_run:
            continue

        for did in drop_ids:
            # 关联表改挂：目标 (movie_id, keep_id) 可能已存在 ⇒ 先查再决定插/删
            mids = (
                await session.execute(
                    select(MovieActorCls.movie_id).where(
                        MovieActorCls.actor_id == did
                    )
                )
            ).scalars().all()
            for mid in mids:
                exists = (
                    await session.execute(
                        select(MovieActorCls).where(
                            MovieActorCls.movie_id == mid,
                            MovieActorCls.actor_id == keep_id,
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    session.add(MovieActorCls(movie_id=mid, actor_id=keep_id))
                else:
                    await session.execute(
                        delete(MovieActorCls).where(
                            MovieActorCls.movie_id == mid,
                            MovieActorCls.actor_id == did,
                        )
                    )
            await session.flush()
            out["relinked"] += len(mids)

            # 其他外键表同样改挂
            for model in fk_models:
                acol = getattr(model, "actor_id", None)
                if acol is None:
                    continue
                try:
                    await session.execute(
                        update(model).where(acol == did).values(actor_id=keep_id)
                    )
                except Exception:
                    # 唯一约束冲突（tag/tier 有 uq_actor_tag / uq_actor_tier）⇒ 删重复行
                    try:
                        await session.execute(delete(model).where(acol == did))
                    except Exception:
                        pass

            await session.execute(delete(ActorCls).where(ActorCls.id == did))
            out["merged"] += 1

    return out
