"""
跨模块数据库查询工具

提供统一的模块数据库 session 和模型获取，避免每个路由文件重复定义。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 所有模块及其模型映射
MODULE_MODELS = {
    "jav": ("app.db.jav_models", "JavMovie", "JavActor"),
    "fc2": ("app.db.fc2_models", "Fc2Movie", "Fc2Actor"),
    "uncensored": ("app.db.uncensored_models", "UncensoredMovie", "UncensoredActor"),
    "chinese": ("app.db.chinese_models", "ChineseMovie", "ChineseActor"),
    "western": ("app.db.western_models", "WesternMovie", "WesternActor"),
    "pornhub": ("app.db.pornhub_models", "PornhubMovie", "PornhubActor"),
}

# 演员表名和影片表名（用于原生 SQL 查询）
MODULE_TABLES = {
    "jav": ("jav_actors", "jav_movies"),
    "fc2": ("fc2_actors", "fc2_movies"),
    "uncensored": ("uncensored_actors", "uncensored_movies"),
    "chinese": ("chinese_actors", "chinese_movies"),
    "western": ("western_actors", "western_movies"),
    "pornhub": ("pornhub_actors", "pornhub_movies"),
}


def get_module_model(module: str, model_type: str = "movie"):
    """懒加载获取模块模型类
    
    Args:
        module: 模块名 jav/fc2/uncensored/chinese/western/pornhub
        model_type: movie 或 actor
    """
    import importlib
    mod_path, movie_cls, actor_cls = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)
    return getattr(mod, movie_cls if model_type == "movie" else actor_cls)


async def get_module_session(module: str):
    """获取模块数据库 session"""
    from app.db.module_db import ModuleDatabase
    mod_db = ModuleDatabase.get_instance(module)
    session = await mod_db.get_session()
    return session
