"""
naming_mnamer_bridge — naming.py / file_organize.py 与 mnamer 的桥接层

设计原则：
- 不改 naming.py / file_organize.py 的现有 API（保持向后兼容）
- 只新增"智能后备"开关式 API：
    1. naming.py 调用方在模板渲染失败时可调 `try_mnamer_fallback(file_path)`
    2. file_organize.py 可选启用 `enable_mnamer=True` 走智能识别
    3. Web 前端在 Import / UnrecognizedFiles 页面调 `get_mnamer_candidates()`

调用关系：
    naming.py  --(失败/回退)-->  naming_mnamer_bridge
                                       |
                                       v
                            services/mnamer_engine.MnamerEngine
                                       |
                                       v
                            external/mnamer  (整包, MIT)

许可：MIT
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.mnamer_engine import (
    MnamerEngine,
    MnamerResult,
    get_mnamer_engine,
)

logger = logging.getLogger(__name__)


# ============================================================
# 配置适配:从 app.config.models.MnamerConfig 构造 mnamer config dict
# ============================================================
def _build_mnamer_config_dict() -> dict[str, Any]:
    """从 AppConfig.mnamer 读取 API Key 与选项,构造 mnamer SettingStore 可用的 config dict。

    mnamer SettingStore 期望的属性名(见 external/mnamer/mnamer/providers.py:52):
        api_key_omdb / api_key_tmdb / api_key_tvdb / hits / batch / ...

    无 API Key 时返回空 dict(mnamer 内置默认 key 仍可用)。
    """
    try:
        from app.config import get_config
        cfg = get_config().mnamer
    except Exception as e:
        logger.warning("读取 MnamerConfig 失败,用默认配置: %s", e)
        return {}

    config: dict[str, Any] = {"batch": True}
    if cfg.omdb_api_key:
        config["api_key_omdb"] = cfg.omdb_api_key
    if cfg.tmdb_api_key:
        config["api_key_tmdb"] = cfg.tmdb_api_key
    if cfg.tvdb_api_key:
        config["api_key_tvdb"] = cfg.tvdb_api_key
    return config


def _default_hits() -> int:
    """从配置读取默认 hits,失败返回 5。"""
    try:
        from app.config import get_config
        return get_config().mnamer.hits
    except Exception:
        return 5


# ============================================================
# 公开 API（对 naming / file_organize / routes 稳定）
# ============================================================
async def try_mnamer_fallback(
    file_path: str | Path,
    *,
    hits: int | None = None,
) -> MnamerResult | None:
    """
    智能后备：当 Jinja2 模板渲染失败 / 输出为空时调用。

    返回 None 表示不应采用 mnamer（如文件不存在或网络错误）；
    返回 MnamerResult 让调用方决定如何展示候选。

    API Key 从 AppConfig.mnamer 自动读取(§B4)。
    """
    fp = Path(file_path)
    if not fp.exists():
        logger.warning("mnamer 后备:文件不存在 %s", fp)
        return None
    engine = get_mnamer_engine()
    config = _build_mnamer_config_dict()
    effective_hits = hits if hits is not None else _default_hits()
    return await engine.query(fp, config=config, hits=effective_hits)


async def get_mnamer_candidates(
    file_path: str | Path,
    *,
    hits: int | None = None,
) -> list[dict[str, Any]]:
    """
    Web 前端（Import / UnrecognizedFiles）专用：返回 JSON 友好的候选列表。

    返回值示例:
        [
            {"name": "Movie Name (2024)", "year": "2024", "imdb": "tt1234567"},
            ...
        ]

    API Key 从 AppConfig.mnamer 自动读取(§B4)。
    """
    effective_hits = hits if hits is not None else _default_hits()
    result = await try_mnamer_fallback(file_path, hits=effective_hits)
    if result is None:
        return []
    return result.candidates


async def build_mnamer_target(
    file_path: str | Path,
    match_index: int,
) -> str | None:
    """
    给定候选下标,计算目标路径(不执行)。
    用于 file_organize 预览模式。
    """
    fp = Path(file_path)
    config = _build_mnamer_config_dict()
    return await get_mnamer_engine().compute_target_path(
        fp, match_index, config=config, hits=_default_hits()
    )


async def execute_mnamer_rename(
    file_path: str | Path,
    match_index: int,
) -> str | None:
    """
    执行 mnamer 重命名(含目录移动)。
    用于 file_organize.execute 模式中 enable_mnamer=True 的场景。
    返回最终路径,失败返回 None。
    """
    fp = Path(file_path)
    config = _build_mnamer_config_dict()
    return await get_mnamer_engine().rename(
        fp, match_index, config=config, hits=_default_hits()
    )


# ============================================================
# 辅助：检查 mnamer 是否可用
# ============================================================
def is_mnamer_available() -> bool:
    """mnamer 整包是否已正确引入(供启动时健康检查)。"""
    try:
        from mnamer.metadata import Metadata  # noqa: F401
        from mnamer.target import Target  # noqa: F401
        return True
    except ImportError as e:
        logger.warning("mnamer 不可用: %s", e)
        return False


def mnamer_version() -> str:
    """获取 mnamer 上游版本号(无依赖 pyproject 解析,直接读 const.VERSION)。"""
    try:
        from mnamer.const import VERSION
        return VERSION
    except ImportError:
        return "unknown"
