"""
片商/制片厂合并服务

参考 JavBoss v1.9.0 片商名称/别名管理。
核心流程：
1. 验证 canonical_studio 存在
2. 合并 source_studio 的名称/别名 → canonical_studio
3. 更新所有影片的 studio/maker 字段
4. 更新 canonical 的 movie_count
5. 硬删除 source_studio
"""
import logging
from typing import List, Optional
from difflib import SequenceMatcher

from sqlalchemy import select, String

from app.utils.module_helper import get_module_model, get_module_session

logger = logging.getLogger(__name__)


async def merge_studios(
    canonical_id: int,
    source_ids: List[int],
    module: str = "jav",
) -> dict:
    """合并片商（将 source_ids 合并到 canonical_id）"""
    session = await get_module_session(module)
    StudioModel = get_module_model(module, "studio")
    MovieModel = get_module_model(module, "movie")

    if canonical_id <= 0:
        return {"error": "canonical_id must be positive"}

    clean_ids = list(dict.fromkeys(sid for sid in source_ids if sid > 0 and sid != canonical_id))
    if not clean_ids:
        return {"error": "merge_ids required"}

    canonical = await session.get(StudioModel, canonical_id)
    if not canonical:
        return {"error": f"目标片商 (id={canonical_id}) 不存在"}

    # 收集 source
    source_studios = []
    for sid in clean_ids:
        s = await session.get(StudioModel, sid)
        if s:
            source_studios.append(s)

    if not source_studios:
        return {"error": "所有 source 片商都不存在"}

    # 合并别名
    existing_aliases = set()
    if canonical.alias:
        existing_aliases.update(a.strip() for a in canonical.alias.split(",") if a.strip())
    existing_aliases.add(canonical.name)

    new_aliases = list(existing_aliases)
    for src in source_studios:
        if src.name and src.name not in existing_aliases:
            new_aliases.append(src.name)
            existing_aliases.add(src.name)
        if src.alias:
            for a in src.alias.split(","):
                a = a.strip()
                if a and a not in existing_aliases:
                    new_aliases.append(a)
                    existing_aliases.add(a)

    canonical.alias = ",".join(new_aliases)

    # 更新影片关联
    from sqlalchemy import or_

    stmt = select(MovieModel).where(
        or_(MovieModel.studio.in_([s.name for s in source_studios]),
            MovieModel.maker.in_([s.name for s in source_studios]))
    )
    result = await session.execute(stmt)
    movies = result.scalars().all()

    for movie in movies:
        changed = False
        for src in source_studios:
            if movie.studio == src.name:
                movie.studio = canonical.name
                changed = True
            if movie.maker == src.name:
                movie.maker = canonical.name
                changed = True
        if changed:
            canonical.movie_count += 1

    # 硬删除 source
    for src in source_studios:
        await session.delete(src)

    await session.commit()

    return {
        "canonical_id": canonical_id,
        "canonical_name": canonical.name,
        "merged_ids": [s.id for s in source_studios],
        "merged_names": [s.name for s in source_studios],
        "aliases": canonical.alias,
        "total_movies": canonical.movie_count,
    }


async def search_similar_studios(name: str, threshold: float = 0.7, module: str = "jav") -> List[dict]:
    """搜索名称相似的片商"""
    session = await get_module_session(module)
    StudioModel = get_module_model(module, "studio")

    stmt = select(StudioModel).order_by(StudioModel.movie_count.desc()).limit(200)
    result = await session.execute(stmt)
    studios = result.scalars().all()

    similar = []
    for s in studios:
        if s.name == name:
            continue
        ratio = SequenceMatcher(None, name.lower(), s.name.lower()).ratio()
        if ratio >= threshold:
            similar.append({
                "id": s.id,
                "name": s.name,
                "alias": s.alias,
                "name_jp": s.name_jp,
                "movie_count": s.movie_count,
                "similarity": round(ratio, 3),
            })
        elif s.alias:
            for a in s.alias.split(","):
                a = a.strip()
                if a and SequenceMatcher(None, name.lower(), a.lower()).ratio() >= threshold:
                    similar.append({
                        "id": s.id,
                        "name": s.name,
                        "alias": s.alias,
                        "name_jp": s.name_jp,
                        "movie_count": s.movie_count,
                        "similarity": round(ratio, 3),
                    })
                    break

    similar.sort(key=lambda x: (-x["similarity"], -x["movie_count"]))
    return similar[:50]
