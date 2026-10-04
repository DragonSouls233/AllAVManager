"""演员筛选条件构造器（``movies.actor LIKE '%name%'`` 的正确替代）

## 为什么需要这个模块（2026-10-04 实测）

`movie_actors` 关联表补齐后，**查询层却完全没享受到收益** ——
`app/api/routes/` 下仍有 14 处用裸 `LIKE '%name%'` 筛演员：

    jav_routes.py:674   pornhub_routes.py:83/377   uncensored_routes.py:342
    fc2_routes.py:297    chinese_routes.py:231      western_routes.py:55/58
    movies.py:2349       compare.py:547/670/1251/1317   actors.py:1830

裸 `LIKE` 有两个实测危害：

1. **子串误匹配** —— 查 `Anna Cherry` 会返回 2 部影片，而它们全是
   `Anna Cherry7` 的（该演员在关联表里 0 行）。同理查 `Anna` 会返回 3 部。
2. **大小写不敏感** —— SQLite 的 ``LIKE`` 默认对 ASCII 大小写不敏感，
   这与「用户输入的名字应精确匹配演员表」的产品预期不一致（虽然
   在此场景下影响小于第 1 条）。

## 方案取舍（实测三口径对比，见 ``scripts/_probe_actor_filter.py``）

| 口径 | 子串误匹配 | 大小写 | 是否依赖关联表已回填 |
|---|---|---|---|
| A 裸 ``LIKE '%name%'``     | ❌ 误命中 | ❌ 不敏感 | 否 |
| B **token 边界 LIKE**      | ✅ 精确   | ❌ 不敏感 | 否 |
| C 关联表精确 JOIN           | ✅ 精确   | ✅ 可控   | **是** |

选 **B**，因为 C 有一个硬伤：关联表覆盖率极不均匀 ——
实测 ``anime`` 库 800 部影片 / 0 演员 / 0 关联，用 C 查任何演员名都返回空，
等于把「按演员筛选」功能整体关掉；``chinese`` 也类似（3 部 / 8 演员 / 0 关联）。

B 在所有**已回填**模块上与 C 结果**逐条一致**，同时对未回填模块仍然可用。

## token 边界的实现

把 ``movies.actor`` 的分隔符归一成 ``,``，两侧补逗号，再要求 ``%,name,%``：

    ',' || replace(...coalesce(col,'')...) || ',' LIKE '%,Anna Cherry7,%'

于是 ``"Lexi Luna,Anna Cherry7"`` 归一为 ``",Lexi Luna,Anna Cherry7,"``：

- 查 ``Anna Cherry7`` → 命中（前后都是逗号）
- 查 ``Anna Cherry``  → **不命中**（右侧是 ``7`` 不是逗号）
- 查 ``Anna``         → **不命中**

⚠️ **不能把空格当分隔符** —— 演员名本身含空格（``Lexi Luna`` / ``Anna Cherry``），
归一时若把空格换成逗号会把名字切碎，导致真演员反而查不到。

## 分隔符口径必须与写入端一致

:func:`app.db.movie_actor_sync.split_actor_names` 用的是
``"，" "、" "/" ";" "|"`` 五个分隔符。这里**复用同一个常量**
（:data:`ACTOR_NAME_SEPARATORS`），否则查询端和写入端口径漂移，
会出现「写进去了但查不到」或「查到没写进去的」。
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import InstrumentedAttribute

logger = logging.getLogger(__name__)

#: 演员名分隔符 —— **写入端与查询端的唯一真相源**。
#: 与 :func:`app.db.movie_actor_sync.split_actor_names` 共用，
#: 不要在任何一侧另写一份。
ACTOR_NAME_SEPARATORS: tuple[str, ...] = ("，", "、", "/", ";", "|")


def normalize_separators(text: Optional[str]) -> str:
    """把演员字段里的各种分隔符归一成半角逗号（Python 侧口径，供测试用）。"""
    if not text:
        return ""
    for sep in ACTOR_NAME_SEPARATORS:
        text = text.replace(sep, ",")
    return text


def _boundary_expr(column: InstrumentedAttribute) -> object:
    """构造 token 边界匹配的 SQL 表达式。

    ``,`` + normalize(col) + ``,`` LIKE ``%,name,%``

    逐层 ``replace`` 嵌套而不是用 ``translate()`` —— 后者在 SQLite 上
    的行为依赖字符集，跨库不可移植。
    """
    expr = column
    # 由内向外：每个分隔符换成 ","
    for sep in ACTOR_NAME_SEPARATORS:
        expr = func_replace(expr, sep, ",")
    # coalesce 必须在 replace 之内，否则 NULL 会让整条 replace 返回 NULL，
    # 那样 `',' || NULL || ','` → NULL，条件恒不成立（静默查不到）。
    expr = func_coalesce(expr, "")
    # 两侧补逗号 → 首尾 token 也有左/右边界
    expr = literal(",") + expr + literal(",")
    return expr


def func_replace(col, old: str, new: str):
    """薄封装，便于单测打桩 / 未来换方言。"""
    from sqlalchemy import func

    return func.replace(col, old, new)


def func_coalesce(col, default: str):
    from sqlalchemy import func

    return func.coalesce(col, default)


def literal(value: str):
    from sqlalchemy import literal as sa_literal

    return sa_literal(value)


def actor_name_condition(
    column: InstrumentedAttribute,
    name: str,
    *,
    exact: bool = True,
) -> object:
    """构造「按演员名筛选影片」的 SQL 条件。

    Args:
        column: 演员文本列（``Movie.actor`` / ``extracted_actor`` 等）
        name: 演员名。可含空格与点号（``Anna Cherry7`` / ``Rosi Lane.II``）
        exact: True（默认）= token 边界精确匹配；
            False = 旧行为裸子串匹配，仅在调用方明确需要模糊搜索时用。

    Returns:
        可直接塞进 ``select().where()`` 的条件表达式。

    ⚠️ 调用方若用 ``exact=False``，会退化为已知的子串误匹配行为
    （查 ``Anna`` 会命中 ``Anna Cherry7``）。仅用于「搜索框联想」这类
    本来就要模糊的场景。
    """
    if name is None:
        raise ValueError("actor name 不能为 None")
    n = name.strip()
    if not n:
        raise ValueError("actor name 不能为空")

    if not exact:
        return column.like(f"%{n}%")

    # 归一化查询词：查询方也可能带中文分隔符（前端多选拼接）
    q = normalize_separators(n).strip(",")
    if not q:
        raise ValueError(f"actor name 归一化后为空: {name!r}")

    # 多个名字（多选筛选）→ OR 关系，逐个走 token 边界
    names = [x.strip() for x in q.split(",") if x.strip()]
    conds = [
        _boundary_expr(column).like(f"%,{x},%")
        for x in names
    ]
    if len(conds) == 1:
        return conds[0]
    return or_(*conds)


def actor_name_conditions_for_columns(
    columns: list[InstrumentedAttribute],
    name: str,
    *,
    exact: bool = True,
) -> object:
    """多列并存时（chinese 同时有 ``actor`` / ``extracted_actor`` /
    ``folder_based_actors``）任一列命中即算命中。"""
    conds = [actor_name_condition(c, name, exact=exact) for c in columns]
    if len(conds) == 1:
        return conds[0]
    return or_(*conds)


def find_actor_column(MovieCls) -> Optional[str]:
    """返回该模块**实际有数据**的演员文本列名。

    ⚠️ 不能只按「列存在」取第一个 —— chinese 同时有 ``actor``（全 NULL）
    和 ``extracted_actor``（有数据），按存在性取会拿到空列，
    于是筛选恒返回空。这正是 2026-10-04 排查 chinese 时踩的坑。
    """
    from app.db.movie_actor_sync import _actor_columns

    return (_actor_columns(MovieCls) or [None])[0]


def actor_movie_ids_condition(
    module: str,
    actor_name: str,
    *,
    movie_cls=None,
) -> Optional[object]:
    """构造「该演员的影片 ID」条件 —— **关联表 ∪ 边界 LIKE**。

    用于语义是"这个演员名下有哪几部片子"的场景（对比白名单、
    本地目录探测）。这类场景**关联表最准**：``Movie.actor`` 文本是
    多源刮削后拼接的，可能重复、可能残留旧名。

    但关联表覆盖率不均匀（实测 ``anime`` 800 部影片 / 0 关联、
    ``chinese`` 3 部 / 0 关联），只用关联表会让这些模块**查不到
    任何东西** —— 原代码注释"MovieActor 关联表在所有模块均为空，
    改用 movie.actor 文本 LIKE"正是为此。

    2026-10-04 关联表已回填，那句前提部分失效。这里取**并集**而非
    二选一，天然同时覆盖两种情况，且不需要先查一次"关联表有没有这个
    演员"（那会多一次往返 + 把异步/同步复杂度泄到调用方）：

        Movie.id IN (关联表子查询)  OR  <token 边界 LIKE 条件>

    关联表有行时并集与关联表一致；没有行时并集退化为边界 LIKE。
    ⚠️ 并集只会**多**不会**少**，唯一风险是"关联表与文本列不一致"
    时捞回文本列里的旧关联 —— 那正是补刮后残留的真实关联，不算错。

    Returns:
        作用于 ``Movie.id`` 的条件表达式；无法构造时返回 ``None``，
        调用方应跳过该筛选而不是让整个查询失败。
    """
    if actor_name is None or not str(actor_name).strip():
        return None

    from app.utils.module_helper import get_module_model

    if movie_cls is None:
        movie_cls = get_module_model(module, "movie")

    names = [n.strip() for n in normalize_separators(str(actor_name)).split(",")
             if n.strip()]
    if not names:
        return None

    conds: list[object] = []

    # ---- 1. 关联表精确子查询（模型缺失时静默跳过）----
    try:
        Actor = get_module_model(module, "actor")
        MovieActor = get_module_model(module, "movie_actor")
        aid_sub = select(Actor.id).where(
            func.lower(Actor.name).in_([n.lower() for n in names])
        )
        conds.append(movie_cls.id.in_(select(MovieActor.movie_id).where(
            MovieActor.actor_id.in_(aid_sub)
        )))
    except Exception as e:
        logger.debug(f"[{module}] 关联表子查询不可用，仅用 LIKE: {e}")

    # ---- 2. token 边界 LIKE（覆盖未回填模块 / 无关联表模型）----
    cols = [c for c in (getattr(movie_cls, a, None)
                        for a in ("actor", "extracted_actor",
                                  "folder_based_actors"))
            if c is not None]
    if cols:
        conds.append(actor_name_conditions_for_columns(
            cols, ", ".join(names), exact=True))

    if not conds:
        return None
    if len(conds) == 1:
        return conds[0]
    return or_(*conds)

