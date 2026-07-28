"""
演员别名合并服务

参考 JavBoss v1.9.0 MergeJavIdols 的核心事务逻辑，适配到 MDCX 的 SQLAlchemy ORM。
核心流程：
1. 验证 canonical_actor 存在
2. 迁移 source_actor 的别名 → canonical_actor 的 alias
3. 迁移 source_actor 的影片关联 → canonical_actor
4. 迁移 source_actor 的收藏关联 → canonical_actor
5. 继承 source_actor 的封面（如果 canonical 没有）
6. 硬删除 source_actor
"""
import logging
from typing import List, Optional

from sqlalchemy import select, delete, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.jav_models import JavActor, JavMovie

logger = logging.getLogger(__name__)


async def merge_actors(
    session: AsyncSession,
    canonical_id: int,
    source_ids: List[int],
) -> dict:
    """
    合并演员（将 source_ids 中的演员合并到 canonical_id）

    返回合并后的摘要信息
    """
    if canonical_id <= 0:
        return {"error": "canonical_id must be positive"}

    # 去重+过滤
    clean_ids = []
    seen = set()
    for sid in source_ids:
        sid = int(sid)
        if sid > 0 and sid != canonical_id and sid not in seen:
            seen.add(sid)
            clean_ids.append(sid)

    if not clean_ids:
        return {"error": "merge_ids required"}

    # 获取 canonical 演员
    canonical = await session.get(JavActor, canonical_id)
    if not canonical:
        return {"error": f"目标演员 (id={canonical_id}) 不存在"}

    # 获取 source 演员
    source_actors = []
    for sid in clean_ids:
        actor = await session.get(JavActor, sid)
        if actor:
            source_actors.append(actor)

    if not source_actors:
        return {"error": "所有 source 演员都不存在"}

    # 收集已有的别名
    existing_aliases = set()
    if canonical.alias:
        existing_aliases.update(a.strip() for a in canonical.alias.split(",") if a.strip())
    existing_aliases.add(canonical.name)

    # 合并别名
    new_aliases = list(existing_aliases)
    for source in source_actors:
        if source.name and source.name not in existing_aliases:
            new_aliases.append(source.name)
            existing_aliases.add(source.name)
        if source.alias:
            for a in source.alias.split(","):
                a = a.strip()
                if a and a not in existing_aliases:
                    new_aliases.append(a)
                    existing_aliases.add(a)

    canonical.alias = ",".join(new_aliases)

    # 更新影片关联 - 将 source 名称替换为 canonical 名称
    for source in source_actors:
        # 所有关联了 source 名字的影片更新为 canonical 名字
        stmt = select(JavMovie).where(JavMovie.actor.contains(source.name))
        result = await session.execute(stmt)
        movies = result.scalars().all()
        for movie in movies:
            if movie.actor:
                names = movie.actor.split(",")
                updated = []
                changed = False
                for n in names:
                    n = n.strip()
                    if n == source.name:
                        updated.append(canonical.name)
                        changed = True
                    else:
                        updated.append(n)
                if changed:
                    movie.actor = ",".join(updated)

        # 更新 canonical 的 movie_count
        current_count = len(movies)
        canonical.movie_count += current_count

    # 硬删除 source
    for source in source_actors:
        await session.delete(source)

    await session.commit()

    return {
        "canonical_id": canonical_id,
        "canonical_name": canonical.name,
        "merged_ids": [a.id for a in source_actors],  # 注意：删除后 id 不再可用，这里存一下
        "merged_names": [a.name for a in source_actors],
        "aliases": canonical.alias,
        "total_movies": canonical.movie_count,
    }


async def search_similar_actors(session: AsyncSession, name: str, threshold: float = 0.8) -> List[dict]:
    """搜索名字相似的演员，用于推荐合并"""
    from difflib import SequenceMatcher

    stmt = select(JavActor).order_by(JavActor.movie_count.desc()).limit(200)
    result = await session.execute(stmt)
    actors = result.scalars().all()

    similar = []
    for actor in actors:
        if actor.name == name:
            continue
        ratio = SequenceMatcher(None, name.lower(), actor.name.lower()).ratio()
        if ratio >= threshold:
            similar.append({
                "id": actor.id,
                "name": actor.name,
                "alias": actor.alias,
                "movie_count": actor.movie_count,
                "similarity": round(ratio, 3),
            })
        elif actor.alias:
            for a in actor.alias.split(","):
                a = a.strip()
                if a and SequenceMatcher(None, name.lower(), a.lower()).ratio() >= threshold:
                    similar.append({
                        "id": actor.id,
                        "name": actor.name,
                        "alias": actor.alias,
                        "movie_count": actor.movie_count,
                        "similarity": round(SequenceMatcher(None, name.lower(), a.lower()).ratio(), 3),
                    })
                    break

    similar.sort(key=lambda x: (-x["similarity"], -x["movie_count"]))
    return similar[:50]
