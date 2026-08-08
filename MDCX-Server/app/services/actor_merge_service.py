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

from sqlalchemy import select

from app.config.manager import get_config_manager
from app.utils.module_helper import get_module_model, get_module_session

logger = logging.getLogger(__name__)


def _avatar_path(module: str, actor_id: int) -> Path:
    """模块隔离的头像文件路径（与 modules.py 约定一致）"""
    data_dir = get_config_manager().computed.data_dir
    return Path(data_dir) / "avatars" / module / f"actor_{actor_id}.jpg"


def _merge_alias(canonical_alias: Optional[str], canonical_name: str, source_names: List[str],
                 source_aliases: List[str]) -> str:
    """合并别名：现有别名 + canonical 名 + source 名 + source 别名（去重，逗号分隔）"""
    seen = set()
    out = []
    for item in [canonical_alias, canonical_name, *source_names, *source_aliases]:
        if not item:
            continue
        for part in item.split(","):
            a = part.strip()
            if not a:
                continue
            key = a.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(a)
    return ",".join(out)


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
    canonical.alias = _merge_alias(
        canonical.alias,
        canonical.name,
        [s.name for s in source_actors],
        [s.alias for s in source_actors if s.alias],
    )

    # 2) 影片 actor 文本列迁移（逗号分隔精确替换）
    all_names = [s.name for s in source_actors if s.name]
    if all_names:
        movies_stmt = select(MovieModel).where(
            MovieModel.actor.in_(all_names)
            | MovieModel.actor.like(f"%{all_names[0]}%")
        )
        result = await session.execute(movies_stmt)
        movies = result.scalars().all()
        changed_count = 0
        for movie in movies:
            actor_text = movie.actor or ""
            new_text = actor_text
            for name in all_names:
                pattern = re.compile(rf"(^|,){re.escape(name)}(,|$)")
                new_text = pattern.sub(lambda m: (m.group(1) + canonical.name + m.group(2)), new_text)
            if new_text != actor_text:
                movie.actor = new_text
                changed_count += 1

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
    }


async def search_similar_actors(name: str, threshold: float = 0.6, module: str = "jav") -> List[dict]:
    """搜索名称相似的演员（推荐合并候选）"""
    session = await get_module_session(module)
    ActorModel = get_module_model(module, "actor")

    stmt = select(ActorModel).order_by(ActorModel.id)
    result = await session.execute(stmt)
    actors = result.scalars().all()

    similar = []
    for a in actors:
        if a.name == name:
            continue
        ratio = SequenceMatcher(None, name.lower(), (a.name or "").lower()).ratio()
        if ratio >= threshold:
            similar.append({
                "id": a.id,
                "name": a.name,
                "alias": a.alias,
                "name_jp": a.name_jp,
                "name_en": a.name_en,
                "similarity": round(ratio, 3),
            })
        elif a.alias:
            for al in a.alias.split(","):
                al = al.strip()
                if al and SequenceMatcher(None, name.lower(), al.lower()).ratio() >= threshold:
                    similar.append({
                        "id": a.id,
                        "name": a.name,
                        "alias": a.alias,
                        "name_jp": a.name_jp,
                        "name_en": a.name_en,
                        "similarity": round(ratio, 3),
                    })
                    break

    similar.sort(key=lambda x: (-x["similarity"], x["id"]))
    return similar[:50]
