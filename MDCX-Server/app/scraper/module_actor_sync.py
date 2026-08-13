"""
模块演员同步器

从影片记录的 actor 文本字段提取演员名，写入对应模块的 Actor 表。
用于 uncensored / fc2 / western / pornhub / jav / chinese 等模块：
- 爬虫刮削后写入 movie.actor 字段的演员名，可能未同步到 Actor 表
- jav 演员存在"改名"情况（同一文件夹内不同时期艺名不同，如 三浦歩美→愛弓りょう），
  仅靠扫描目录名建演员会漏掉改名后的名字，需从影片 actor 字段反查补齐

说明：同步出的演员 source 统一为 "folder"（本地存在对应影片），
避免与"纯刮削占位"(source="scraper") 混淆，前端过滤 scraper 时不会误伤。
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 模块 → (模型模块路径, Movie类名, Actor类名, actor字段名)
_MODEL_MAP = {
    "uncensored": ("app.db.uncensored_models", "UncensoredMovie", "UncensoredActor", "actor"),
    "fc2": ("app.db.fc2_models", "Fc2Movie", "Fc2Actor", "actor"),
    "western": ("app.db.western_models", "WesternMovie", "WesternActor", "actors"),
    "pornhub": ("app.db.pornhub_models", "PornhubMovie", "PornhubActor", "actor"),
    "chinese": ("app.db.chinese_models", "ChineseMovie", "ChineseActor", "extracted_actor"),
    "jav": ("app.db.jav_models", "JavMovie", "JavActor", "actor"),
}

# 形如 {'name': '愛弓りょう'}, {'name': '安堂はるの'} 的 JSON 风格字段
_JSON_STYLE_RE = re.compile(r"['\"]name['\"]\s*:\s*['\"]([^'\"]+)['\"]")


def parse_actor_names(text: str) -> list[str]:
    """从文本字段解析演员名列表

    jav 的 actor 字段存在两种格式：
    1. 逗号/顿号分隔的纯文本（扫描、批量刮削写入）："三浦歩美,安堂はるの"
    2. JSON 风格（importer/sync 写入）：{'name': '愛弓りょう'}, {'name': '安堂はるの'}
    """
    if not text or not text.strip():
        return []
    # 1. 优先按 JSON 风格提取 name
    json_names = [m.group(1).strip() for m in _JSON_STYLE_RE.finditer(text)]
    if json_names:
        return json_names
    # 2. 回退按分隔符拆分
    parts = re.split(r"[,，、/&|\\n]+", text)
    names = []
    for p in parts:
        name = p.strip()
        if name and len(name) <= 100:
            names.append(name)
    return names


async def sync_actors_from_movies(module_name: str) -> dict:
    """从影片记录同步演员到 Actor 表

    遍历模块中所有影片，提取 actor 字段中的演员名，
    写入或更新 Actor 表（去重 + 统计 movie_count）。

    Returns:
        {"actors_added": int, "actors_updated": int, "actors_found": int}
    """
    if module_name not in _MODEL_MAP:
        return {"error": f"不支持的模块: {module_name}"}

    from app.db.module_db import ModuleDatabase
    import importlib

    mod_path, movie_cls, actor_cls, actor_field = _MODEL_MAP[module_name]
    mod = importlib.import_module(mod_path)
    MovieModel = getattr(mod, movie_cls)
    ActorModel = getattr(mod, actor_cls)

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()

    result = {"actors_added": 0, "actors_updated": 0, "actors_found": 0}

    try:
        from sqlalchemy import select, func

        # 1. 收集所有影片中的演员名
        all_movie_actors: dict[str, int] = {}  # name → count

        stmt = select(MovieModel)
        movies = (await session.execute(stmt)).scalars().all()

        for movie in movies:
            actor_text = getattr(movie, actor_field, None)
            if not actor_text:
                continue
            names = parse_actor_names(actor_text)
            for name in names:
                all_movie_actors[name] = all_movie_actors.get(name, 0) + 1

        result["actors_found"] = len(all_movie_actors)
        if not all_movie_actors:
            return result

        # 2. 获取已有 Actor 记录
        existing = await session.execute(select(ActorModel))
        existing_map = {a.name: a for a in existing.scalars().all()}

        # 3. 新增或更新
        for name, count in all_movie_actors.items():
            if name in existing_map:
                actor = existing_map[name]
                if actor.movie_count != count:
                    actor.movie_count = count
                    result["actors_updated"] += 1
            else:
                session.add(ActorModel(
                    name=name,
                    movie_count=count,
                    source="folder",
                ))
                result["actors_added"] += 1

        await session.commit()
        logger.info(
            f"[{module_name}] 演员同步完成: "
            f"发现 {result['actors_found']} 人, "
            f"新增 {result['actors_added']}, "
            f"更新 {result['actors_updated']}"
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"[{module_name}] 演员同步失败: {e}")
        raise
    finally:
        await session.close()

    return result


async def sync_actor_single(module_name: str, actor_name: str) -> bool:
    """同步单个演员的 movie_count"""
    if module_name not in _MODEL_MAP:
        return False

    from app.db.module_db import ModuleDatabase
    import importlib

    mod_path, movie_cls, actor_cls, actor_field = _MODEL_MAP[module_name]
    mod = importlib.import_module(mod_path)
    MovieModel = getattr(mod, movie_cls)
    ActorModel = getattr(mod, actor_cls)

    db = ModuleDatabase.get_instance(module_name)
    session = await db.get_session()

    try:
        from sqlalchemy import select, func

        # 统计该演员出现的影片数
        movies_with_actor = await session.execute(
            select(func.count()).select_from(MovieModel).where(
                getattr(MovieModel, actor_field).like(f"%{actor_name}%")
            )
        )
        count = movies_with_actor.scalar() or 0

        # 更新或创建 Actor 记录
        existing = await session.execute(
            select(ActorModel).where(ActorModel.name == actor_name)
        )
        actor = existing.scalar_one_or_none()
        if actor:
            actor.movie_count = count
        else:
            session.add(ActorModel(
                name=actor_name,
                movie_count=count,
                source="folder",
            ))
        await session.commit()
        return True
    except Exception as e:
        await session.rollback()
        logger.error(f"[{module_name}] 同步单个演员失败 {actor_name}: {e}")
        return False
    finally:
        await session.close()
