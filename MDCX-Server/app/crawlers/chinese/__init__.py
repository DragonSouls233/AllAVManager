"""国产模块爬虫

🔴 2026-10-04 改为**自动发现**：原实现硬编码 import 4 个模块
    `from app.crawlers.chinese import madou / aggregate` + 两个 importlib
    ⇒ 目录里新增的爬虫（如 madou_wp.py）**根本不会被导入、不会注册**，
    表现为「代码写好了但源列表里看不到」——极难排查。
    现改为遍历目录下的 *.py 自动导入，新增文件只需放进本目录。
    单个源导入失败只告警、不拖垮整个服务（原来一个坏文件会让服务起不来）。
"""
import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__name__).parent if not str(__name__).endswith("__init__") else str(Path(__file__).parent)

# aggregate 内部有 httpx 依赖，先显式导入并放进 __all__
from app.crawlers.chinese import aggregate  # noqa: E402,F401

__all__ = ["aggregate"]

for _mod in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if _mod.name.startswith("_") or _mod.name == "aggregate":
        continue
    try:
        importlib.import_module(f"{__name__}.{_mod.name}")
        __all__.append(_mod.name)
    except Exception as _e:
        logger.warning("国产爬虫 %s 导入失败（已跳过）: %s", _mod.name, _e)