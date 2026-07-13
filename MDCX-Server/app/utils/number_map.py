"""
番号标题映射

加载 Hazard804 MDCX 的 c_number.json 文件，提供番号到中文标题的快速查找。
作为本地回退数据源，当爬虫未返回标题时使用。
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 全局映射字典
_number_title_map: dict[str, str] = {}
_loaded = False

# c_number.json 文件路径（相对于项目根目录）
C_NUMBER_FILE = Path("data") / "cache" / "c_number.json"


def load_number_map(file_path: Optional[Path] = None) -> dict[str, str]:
    """
    加载番号标题映射文件

    Args:
        file_path: c_number.json 文件路径，默认为 data/cache/c_number.json

    Returns:
        番号到标题的映射字典
    """
    global _number_title_map, _loaded

    if _loaded:
        return _number_title_map

    path = file_path or C_NUMBER_FILE
    if not path.exists():
        logger.warning(f"番号标题映射文件不存在: {path}，跳过加载")
        _loaded = True
        return _number_title_map

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _number_title_map = data
            logger.info(f"已加载 {len(_number_title_map)} 条番号标题映射")
        else:
            logger.warning(f"番号标题映射文件格式错误，期望 dict，实际为 {type(data)}")
    except Exception as e:
        logger.error(f"加载番号标题映射文件失败: {e}")

    _loaded = True
    return _number_title_map


def get_title_by_number(number: str) -> Optional[str]:
    """
    根据番号获取中文标题

    Args:
        number: 番号（如 ABC-123）

    Returns:
        中文标题，如果未找到返回 None
    """
    if not _loaded:
        load_number_map()

    # 直接查找
    if number in _number_title_map:
        return _number_title_map[number]

    # 尝试不带横线的格式
    no_hyphen = number.replace("-", "")
    if no_hyphen in _number_title_map:
        return _number_title_map[no_hyphen]

    # 尝试小写
    lower = number.lower()
    if lower in _number_title_map:
        return _number_title_map[lower]

    return None


def get_map_size() -> int:
    """获取映射数量"""
    return len(_number_title_map)


# ============================================
# 女优别名字典(借鉴 JavSP data/actress_alias.json)
# ============================================
# JavSP 原始格式: {"标准名": ["别名1", "别名2", ...]}
# merger.py 期望格式: {"别名": "标准名"}(field _resolve_actress_aliases 用)
# 标准名本身也作为别名(确保自匹配归一)

_actress_alias_map: dict[str, str] = None  # None 表示未加载
ACTRESS_ALIAS_FILE = Path("data") / "actress_alias.json"


def load_actress_alias_map(file_path: Optional[Path] = None) -> dict[str, str]:
    """加载女优别名字典并转换为 {alias: canonical} 格式

    借鉴 JavSP __main__.py 的加载逻辑。JavSP 原始 JSON 格式为
    {canonical: [aliases]},需翻转为 {alias: canonical} 给 merger.py 用。

    Args:
        file_path: actress_alias.json 文件路径,默认为 data/actress_alias.json

    Returns:
        {别名: 标准名} 映射字典,加载失败返回空 dict
    """
    global _actress_alias_map
    if _actress_alias_map is not None:
        return _actress_alias_map

    path = file_path or ACTRESS_ALIAS_FILE
    _actress_alias_map = {}
    if not path.exists():
        logger.warning(f"女优别名字典不存在: {path},跳过加载")
        return _actress_alias_map

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)  # {canonical: [alias1, alias2, ...]}
        if not isinstance(raw, dict):
            logger.warning(f"女优别名字典格式错误,期望 dict,实际为 {type(raw)}")
            return _actress_alias_map
        # 翻转为 {alias: canonical},标准名本身也作为别名(确保自匹配)
        for canonical, aliases in raw.items():
            _actress_alias_map[canonical] = canonical
            if isinstance(aliases, list):
                for alias in aliases:
                    _actress_alias_map[alias] = canonical
        logger.info(
            f"已加载 {len(_actress_alias_map)} 条女优别名映射(覆盖 {len(raw)} 位女优)"
        )
    except Exception as e:
        logger.error(f"加载女优别名字典失败: {e}")

    return _actress_alias_map


def get_actress_alias_map() -> dict[str, str]:
    """获取女优别名字典(懒加载)"""
    if _actress_alias_map is None:
        load_actress_alias_map()
    return _actress_alias_map or {}


def resolve_actress_name(name: str) -> str:
    """归一化女优名到标准名

    Args:
        name: 原始女优名(可能是别名)

    Returns:
        标准名,未匹配则返回原值
    """
    if not name:
        return name
    alias_map = get_actress_alias_map()
    # 精确匹配
    if name in alias_map:
        return alias_map[name]
    # 大小写不敏感
    lower = name.lower()
    for alias, canonical in alias_map.items():
        if alias.lower() == lower:
            return canonical
    return name
