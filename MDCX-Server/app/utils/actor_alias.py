"""
演员别名聚合工具（合并后作品「算在一起」的唯一真相源）

背景
----
演员合并（app/services/actor_merge_service.py）采用 JavBoss 风格策略：
  1) 把 source.name 写入 canonical.alias（逗号分隔）
  2) 迁移 movies.actor 文本中的 source.name -> canonical.name
  3) 硬删除 source 演员行

但历史库里仍存在大量「合并前就已入库、或迁移时 token 形态异常」的影片，
其 movies.actor 仍保留旧名（例：`森沢かな（飯岡かなこ）`）。
若查询只按 canonical.name 单名匹配，这些作品就会漏掉，
表现为「合并后作品数不变 / 作品列表看不到被合并演员的片子」。

因此所有「按演员查作品」的入口统一改用本模块：
    variants = actor_name_variants(actor)      # name + alias 全部变体
    cond     = actor_movie_condition(Movie, variants)

这样无需迁移历史数据，合并后的作品天然聚合在一起。

注意
----
* 采用 LIKE '%变体%' 子串匹配，与改造前各端点的行为保持一致（不会让统计变少）。
* 会剔除「被更短变体覆盖」的冗余变体：若 A 是 B 的子串，则 '%A%' 已覆盖 '%B%'。
* 变体长度 < 2 的直接丢弃，避免单字过度匹配。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from sqlalchemy import func, or_, select

from app.utils.actor_name_utils import clean_alias_parens

# 别名字段分隔符：英文逗号 / 中文逗号 / 顿号 / 分号 / 竖线 / 斜杠
_SEP_RE = re.compile(r"[,，、;；|/／]+")

MIN_VARIANT_LEN = 2

# 纯假名变体最小安全长度：纯假名 3 字以下极易产生误匹配
# （例：「みう」仅 2 假名，LIKE '%みう%' 会命中包含「みう」的其它演员名变体）
# 汉字+假名混合名 2 字即可（例：「杏美」），纯假名则需 4 字以上才安全
_MIN_KANA_ONLY_LEN = 4
_KANA_RE = re.compile(r"^[\u3040-\u30ff\u30fc]+$")


def split_alias(raw: Optional[str]) -> List[str]:
    """把 alias 文本切成名称列表（清洗括号噪声、去空白、去重、保序）"""
    if not raw:
        return []
    out: List[str] = []
    seen = set()
    for part in _SEP_RE.split(str(raw)):
        name = clean_alias_parens(part.strip())
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _prune_redundant(names: Iterable[str]) -> List[str]:
    """剔除冗余变体：长名匹配是短名匹配的子集，若 A 是 B 的子串则丢弃 A（短名）

    注意：方向与直觉相反但正确 —— LIKE '%B%'（长名）只命中含完整长名的行，
    是 LIKE '%A%'（短名，含 A 即命中）的子集，所以必须**保留长的、丢弃短的**。
    否则主名「新井リマ」会被别名「リマ」覆盖丢弃，导致作品统计过度聚合
    （把任何含「リマ」的其他演员作品都算进来）。

    此外剔除纯假名短变体（≤3 字）：「みう」2 假名作为 LIKE 关键词极易误匹配
    其它含「みう」子串的记录。
    """
    uniq: List[str] = []
    seen = set()
    for n in names:
        n = (n or "").strip()
        if len(n) < MIN_VARIANT_LEN:
            continue
        if _KANA_RE.match(n) and len(n) < _MIN_KANA_ONLY_LEN:
            continue
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(n)

    # 长的优先，短的若是长的子串则丢弃（稳定排序，等长保持原序）
    uniq.sort(key=len, reverse=True)
    kept: List[str] = []
    for n in uniq:
        if any(n in long for long in kept):
            continue
        kept.append(n)
    return kept


def actor_name_variants(actor, include_localized: bool = False) -> List[str]:
    """演员的全部检索名（主名 + 合并进来的别名）

    :param include_localized: 是否把 name_jp / name_en 也纳入（默认否，避免过度匹配）
    """
    name = (getattr(actor, "name", None) or "").strip()
    aliases = split_alias(getattr(actor, "alias", None))
    if include_localized:
        for attr in ("name_jp", "name_en"):
            v = getattr(actor, attr, None)
            if v:
                aliases.append(str(v).strip())

    # 主名无条件保留：影片 actor 字段大多存主名，而主名可能比个别别名短
    # （如 387 広瀬りおな <- 别名 広瀬りおなさん），若参与 _prune_redundant
    # 会被更长别名按「子串」剪掉，导致按主名入库的影片全部漏统计。
    variants: List[str] = []
    seen = set()
    if name:
        variants.append(name)
        seen.add(name.lower())

    # 别名之间剪枝（长名优先、子串去重，避免过度聚合）；
    # 同时剔除「已被主名覆盖」的别名（该别名 LIKE 命中集 ⊆ 主名 LIKE 命中集）。
    for a in _prune_redundant(aliases):
        key = a.lower()
        if key in seen:
            continue
        if any(a in kept for kept in variants):
            continue
        seen.add(key)
        variants.append(a)

    if not variants and name:
        # 名字过短（单字）时至少保留主名，否则会查出全库
        variants = [name]
    return variants


def merged_from_names(actor) -> List[str]:
    """仅返回「被合并进来的旧名」（alias 去掉主名本身），用于前端提示"""
    name = (getattr(actor, "name", "") or "").strip().lower()
    return [a for a in split_alias(getattr(actor, "alias", None)) if a.strip().lower() != name]


def actor_movie_condition(movie_cls, variants: List[str], include_folder: bool = True):
    """构造「影片属于该演员（含所有别名）」的 SQLAlchemy 条件

    :return: SQLAlchemy 条件对象；variants 为空时返回 None（调用方需自行处理）
    """
    if not variants:
        return None

    folder_col = getattr(movie_cls, "folder_based_actors", None) if include_folder else None

    clauses = []
    for v in variants:
        like = f"%{v}%"
        clauses.append(movie_cls.actor.like(like))
        if folder_col is not None:
            clauses.append(folder_col.like(like))

    return clauses[0] if len(clauses) == 1 else or_(*clauses)


def actor_movie_condition_for(movie_cls, actor, include_folder: bool = True):
    """便捷入口：直接由 actor 对象构造条件"""
    return actor_movie_condition(movie_cls, actor_name_variants(actor), include_folder=include_folder)


async def count_actor_movies(session, movie_cls, actor, include_folder: bool = True) -> int:
    """实时统计该演员（含所有别名）的作品数

    actors.movie_count 列来自刮削/合并时写入，可能过时；
    详情页与合并后重算统一用本函数取真实值。
    """
    cond = actor_movie_condition_for(movie_cls, actor, include_folder=include_folder)
    if cond is None:
        return 0
    total = await session.scalar(select(func.count(movie_cls.id)).where(cond))
    return int(total or 0)
