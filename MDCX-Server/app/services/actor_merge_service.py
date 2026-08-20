"""
演员合并服务

参考 JavBoss MergeJavIdols 与 MDCX 片商合并（studio_merge_service）：
1. 验证 canonical / source 演员存在
2. 别名合并：source.name + source.alias → canonical.alias（逗号分隔去重，排除 canonical 自身名称）
3. 影片迁移：movies.actor 文本列（逗号分隔）中的 source.name 替换为 canonical.name
4. 头像继承：canonical 无头像时继承 source 的头像（avatars/{module}/actor_{id}.jpg）
5. 硬删除 source 演员行
"""
import logging
import re
import shutil
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select, or_, func

from app.config.manager import get_config_manager
from app.utils.module_helper import get_module_model, get_module_session

logger = logging.getLogger(__name__)


def _avatar_path(module: str, actor_id: int) -> Path:
    """模块隔离的头像文件路径（与 modules.py 约定一致）"""
    data_dir = get_config_manager().computed.data_dir
    return Path(data_dir) / "avatars" / module / f"actor_{actor_id}.jpg"


def _merge_alias(canonical_alias: Optional[str], canonical_name: str, source_names: List[str],
                 source_aliases: List[str]) -> str:
    """合并别名：仅收集「被合并进来的旧名」（existing alias + source 名 + source 别名）

    注意：不把 canonical_name 自身写进 alias——alias 的语义就是「这些名字合并到了我这里」，
    canonical 主名无需冗余记录。这样前端 merged_from 直接展示 alias 即可得到纯净的合并来源列表。
    每个别名先清洗括号噪声（如「佐伯晴香(熟女)」→「佐伯晴香」），
    再按归一化名（NFKC + 繁体/异体字）去重（如「三上悠亜」与「三上悠亞」视为同一人）。
    """
    from app.utils.actor_name_utils import clean_alias_parens, normalize_actor_name

    canonical_key = normalize_actor_name(canonical_name)
    seen = set()
    out = []
    for item in [canonical_alias, *source_names, *source_aliases]:
        if not item:
            continue
        for part in item.split(","):
            a = clean_alias_parens(part.strip())
            if not a:
                continue
            key = normalize_actor_name(a)
            if not key or key == canonical_key:
                continue  # 跳过主名自身
            if key in seen:
                continue
            seen.add(key)
            out.append(a)
    return ",".join(out)


def _actor_token_cond(col, name: str):
    """精确匹配逗号分隔 actor 字段中的某个演员名（避免子串误命中）"""
    return or_(
        col == name,
        col.like(f"{name},%"),
        col.like(f"%,{name}"),
        col.like(f"%,{name},%"),
    )


async def merge_actors(
    canonical_id: int,
    source_ids: List[int],
    module: str = "jav",
) -> dict:
    """合并演员（将 source_ids 合并到 canonical_id）

    - source.name 自动成为 canonical 的别名（写入 alias 字段）
    - 所有影片 actor 文本列中的 source.name 替换为 canonical.name
    - canonical 无头像时继承 source 的头像
    """
    session = await get_module_session(module)
    ActorModel = get_module_model(module, "actor")
    MovieModel = get_module_model(module, "movie")

    if canonical_id <= 0:
        return {"error": "canonical_id must be positive"}

    clean_ids = list(dict.fromkeys(sid for sid in source_ids if sid > 0 and sid != canonical_id))
    if not clean_ids:
        return {"error": "merge_ids required"}

    canonical = await session.get(ActorModel, canonical_id)
    if not canonical:
        return {"error": f"目标演员 (id={canonical_id}) 不存在"}

    source_actors = []
    for sid in clean_ids:
        s = await session.get(ActorModel, sid)
        if s:
            source_actors.append(s)
    if not source_actors:
        return {"error": "所有 source 演员都不存在"}

    # 1) 别名合并（JavBoss 风格：source.name 作为 canonical 别名）
    #    注意：跳过含逗号的 source.name —— 那类行是「多演员合一名」的脏数据
    #    （如「春陽モカ,新井リマ」），若拆分写入 alias 会把其他演员名也挂到 canonical 名下，
    #    导致 canonical 的作品统计把其他演员的片全部算进来。影片 token 迁移不受影响。
    canonical.alias = _merge_alias(
        canonical.alias,
        canonical.name,
        [s.name for s in source_actors if s.name and "," not in s.name],
        [s.alias for s in source_actors if s.alias],
    )

    # 2) 影片 actor 文本列迁移（逗号分隔精确替换 + 去重）
    all_names = [s.name for s in source_actors if s.name]
    changed_count = 0
    if all_names:
        cond = _actor_token_cond(MovieModel.actor, all_names[0])
        for nm in all_names[1:]:
            cond = cond | _actor_token_cond(MovieModel.actor, nm)
        result = await session.execute(select(MovieModel).where(cond))
        movies = result.scalars().all()
        for movie in movies:
            actor_text = movie.actor or ""
            parts = [p.strip() for p in actor_text.split(",") if p.strip()]
            new_parts: list[str] = []
            changed = False
            for p in parts:
                if p in all_names:
                    p = canonical.name
                    changed = True
                new_parts.append(p)
            # 去重 canonical 名（同一影片可能同时含 source 与 canonical）
            seen = set()
            dedup: list[str] = []
            for p in new_parts:
                if p in seen:
                    changed = True
                    continue
                seen.add(p)
                dedup.append(p)
            new_text = ",".join(dedup)
            if changed and new_text != actor_text:
                movie.actor = new_text
                changed_count += 1

    # 5) 重算 canonical 作品数：基于「主名 + 全部别名」的实际影片数。
    #    - 不再简单累加 movie_count 字段（该字段来自刮削，常与实际关联数不符，累加会虚高）
    #    - 也不能只按 canonical.name 统计：历史库里仍有影片保留旧名（token 形态异常、
    #      或合并前入库未迁移），只按主名会漏算，表现为「合并了但作品数没变」。
    #    这里与详情页/作品列表使用同一条件（app/utils/actor_alias），保证三处数字一致。
    from app.utils.actor_alias import count_actor_movies
    canonical.movie_count = await count_actor_movies(session, MovieModel, canonical)

    # 3) 头像继承：canonical 无头像则用 source 的（仅文件，DB 无头像路径列）
    canonical_avatar = _avatar_path(module, canonical_id)
    if not canonical_avatar.exists():
        for src in source_actors:
            src_avatar = _avatar_path(module, src.id)
            if src_avatar.exists():
                try:
                    canonical_avatar.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_avatar, canonical_avatar)
                    logger.info(f"[actor-merge] 头像继承: actor_{src.id}.jpg -> actor_{canonical_id}.jpg")
                    break
                except Exception as e:
                    logger.debug(f"[actor-merge] 头像继承失败: {e}")

    # 4) 硬删除 source
    for src in source_actors:
        await session.delete(src)

    await session.commit()

    return {
        "canonical_id": canonical_id,
        "canonical_name": canonical.name,
        "merged_ids": [s.id for s in source_actors],
        "merged_names": [s.name for s in source_actors],
        "aliases": canonical.alias,
        "movies_updated": changed_count if all_names else 0,
        "movie_count": canonical.movie_count,
    }


def _actor_name_similarity(name: str, other: str) -> float:
    """计算两个演员名的相似度（0~1）

    - 完全相等 -> 1.0
    - 一方包含另一方（如 '森沢かな' ⊂ '森沢かな（飯岡かなこ）'）-> 0.9
    - 其余走 SequenceMatcher 模糊比
    """
    nl = (name or "").lower().strip()
    ol = (other or "").lower().strip()
    if not nl or not ol:
        return 0.0
    if nl == ol:
        return 1.0
    if nl in ol or ol in nl:
        return 0.9
    return SequenceMatcher(None, nl, ol).ratio()


async def search_similar_actors(name: str, threshold: float = 0.6, module: str = "jav") -> List[dict]:
    """搜索名称相似的演员（推荐合并候选）

    包含与查询名完全相等/互相包含的演员（可被选为目标或候选）；
    不再跳过精确匹配。
    """
    session = await get_module_session(module)
    ActorModel = get_module_model(module, "actor")

    stmt = select(ActorModel).order_by(ActorModel.id)
    result = await session.execute(stmt)
    actors = result.scalars().all()

    similar = []
    for a in actors:
        ratio = _actor_name_similarity(name, a.name)
        if ratio < threshold and a.alias:
            for al in a.alias.split(","):
                al = al.strip()
                if al:
                    r2 = _actor_name_similarity(name, al)
                    if r2 >= threshold:
                        ratio = max(ratio, r2)
                        break
        if ratio >= threshold:
            similar.append({
                "id": a.id,
                "name": a.name,
                "alias": a.alias,
                "name_jp": a.name_jp,
                "name_en": a.name_en,
                "similarity": round(ratio, 3),
            })

    similar.sort(key=lambda x: (-x["similarity"], x["id"]))
    return similar[:50]
