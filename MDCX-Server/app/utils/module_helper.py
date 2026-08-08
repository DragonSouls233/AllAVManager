"""
跨模块数据库查询工具 v2.0

适配新架构：每个模块独立 DB + 独立 Base + 统一表名 (movies/actors/...)
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 当前活动模块列表
ACTIVE_MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub", "anime"]

# 每个模块的模型类映射（模块名 -> (模型文件路径, Movie类名, Actor类名)）
MODULE_MODELS: dict[str, tuple[str, str, str]] = {
    "jav": ("app.db.jav_models", "JavMovie", "JavActor"),
    "fc2": ("app.db.fc2_models", "Fc2Movie", "Fc2Actor"),
    "uncensored": ("app.db.uncensored_models", "UncensoredMovie", "UncensoredActor"),
    "chinese": ("app.db.chinese_models", "ChineseMovie", "ChineseActor"),
    "western": ("app.db.western_models", "WesternMovie", "WesternActor"),
    "pornhub": ("app.db.pornhub_models", "PornhubMovie", "PornhubActor"),
    "anime": ("app.db.anime_models", "AnimeMovie", "AnimeActor"),
}

# 每个模块的 Base 类导入路径
MODULE_BASES: dict[str, str] = {
    "jav": "app.db.jav_models:JAV_BASE",
    "fc2": "app.db.fc2_models:FC2_BASE",
    "uncensored": "app.db.uncensored_models:UNCENSORED_BASE",
    "chinese": "app.db.chinese_models:CHINESE_BASE",
    "western": "app.db.western_models:WESTERN_BASE",
    "pornhub": "app.db.pornhub_models:PORNHUB_BASE",
    "anime": "app.db.anime_models:ANIME_BASE",
}

# 统一表名映射（所有模块使用相同的表名结构）
# 演员表名 -> 影片表名（用于原生 SQL 查询，向后兼容）
MODULE_TABLES: dict[str, tuple[str, str]] = {
    "jav": ("actors", "movies"),
    "fc2": ("actors", "movies"),
    "uncensored": ("actors", "movies"),
    "chinese": ("actors", "movies"),
    "western": ("actors", "movies"),
    "pornhub": ("actors", "movies"),
    "anime": ("actors", "movies"),
}

# 向后兼容：旧代码可能使用 jav_actors/jav_movies 等表名
# 提供重定向映射
LEGACY_TABLE_MAP: dict[str, str] = {
    "jav_actors": "actors",
    "jav_movies": "movies",
    "fc2_actors": "actors",
    "fc2_movies": "movies",
    "uncensored_actors": "actors",
    "uncensored_movies": "movies",
    "chinese_actors": "actors",
    "chinese_movies": "movies",
    "western_actors": "actors",
    "western_movies": "movies",
    "pornhub_actors": "actors",
    "pornhub_movies": "movies",
}

# 核心表列表（每个模块都有的表）
CORE_TABLES = [
    "movies", "actors", "movie_actors",
    "studios", "series",
    "tags", "movie_tags", "actor_tags",
    "tier_config", "actor_tiers",
    "actor_compare_urls",
    "actor_subscriptions", "series_subscriptions",
    "play_history", "import_records", "patch_records",
    "file_organize_jobs", "auto_organize_rules",
    "movie_relations", "user_recommendations",
]


# 所有模块共用的辅助表类名（这些类在每模块中名称相同，如 Studio、Series、Tag 等）
_SHARED_MODEL_CLASSES: dict[str, str] = {
    "movie_actor": "MovieActor",
    "studio": "Studio",
    "series": "Series",
    "tag": "Tag",
    "movie_tag": "MovieTag",
    "actor_tag": "ActorTag",
    "tier_config": "TierConfig",
    "actor_tier": "ActorTier",
    "actor_compare_url": "ActorCompareURL",
    "actor_subscription": "ActorSubscription",
    "series_subscription": "SeriesSubscription",
    "play_history": "PlayHistory",
    "import_record": "ImportRecord",
    "patch_record": "PatchRecord",
    "file_organize_job": "FileOrganizeJob",
    "auto_organize_rule": "AutoOrganizeRule",
    "movie_relation": "MovieRelation",
    "user_recommendation": "UserRecommendation",
}


def get_module_model(module: str, model_type: str = "movie") -> Any:
    """懒加载获取模块模型类

    Args:
        module: 模块名 jav/fc2/uncensored/chinese/western/pornhub
        model_type: "movie" / "actor" 或任意 _SHARED_MODEL_CLASSES 中定义的键
    """
    import importlib

    if module not in MODULE_MODELS:
        raise ValueError(f"未知模块: {module}，有效值: {list(MODULE_MODELS.keys())}")

    mod_path, movie_cls, actor_cls = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)

    if model_type == "movie":
        cls_name = movie_cls
    elif model_type == "actor":
        cls_name = actor_cls
    elif model_type in _SHARED_MODEL_CLASSES:
        cls_name = _SHARED_MODEL_CLASSES[model_type]
    else:
        raise ValueError(
            f"未知模型类型: {model_type}，有效值: movie, actor, "
            f"{', '.join(_SHARED_MODEL_CLASSES.keys())}"
        )

    return getattr(mod, cls_name)


async def get_module_session(module: str):
    """获取模块数据库 session"""
    from app.db.module_db import ModuleDatabase
    mod_db = ModuleDatabase.get_instance(module)
    session = await mod_db.get_session()
    return session


def get_module_base(module: str) -> Any:
    """获取模块的 DeclarativeBase 类"""
    import importlib

    base_ref = MODULE_BASES[module]
    mod_path, attr_name = base_ref.split(":")
    mod = importlib.import_module(mod_path)
    return getattr(mod, attr_name)
