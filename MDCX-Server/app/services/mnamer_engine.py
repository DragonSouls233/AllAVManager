"""
mnamer_engine — MDCX 异步包装层

将 mnamer 同步 CLI 库转换为 FastAPI 异步服务可调用的引擎：
- MnamerEngine : 顶层入口，单例
- MnamerResult : 候选结果数据类
- rename_file  : 单文件重命名快捷方法
- build_target_path : 仅计算目标路径，不执行

设计原则：
- 严禁将 mnamer 内部细节（Target / Provider / SettingStore）泄露到上层
- 上层只看到 dataclass MnamerResult
- 同步阻塞调用通过 run_in_executor 调度到线程池，不阻塞 event loop
- 包装层薄而稳定，mnamer 升级时只改本文件

来源(原始):O:/MDCX/GitHub-ZIP/P3-Media/mnamer/mnamer-main
许可:MIT(见 external/mnamer/LICENSE.txt)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import sys
from pathlib import Path
from typing import Any

# mnamer 自身在 import 时设置环境变量抑制 rebulk 的 regex 包
# 必须在 import mnamer 之前
os.environ.setdefault("REGEX_DISABLED", "1")

# mnamer 整包拷贝在 app/external/mnamer/,未 pip install,需显式加入 sys.path
# 与 tests/conftest.py 保持一致,确保运行时(非仅 pytest)也能 import
_EXTERNAL_MNAMER = str(Path(__file__).resolve().parent.parent / "external" / "mnamer")
if _EXTERNAL_MNAMER not in sys.path and Path(_EXTERNAL_MNAMER).exists():
    sys.path.insert(0, _EXTERNAL_MNAMER)

# mnamer 内部包（不暴露给上层）
from mnamer.exceptions import (  # noqa: E402
    MnamerException,
    MnamerNetworkException,
    MnamerNotFoundException,
)
from mnamer.metadata import Metadata, MetadataMovie  # noqa: E402
from mnamer.setting_store import SettingStore  # noqa: E402
from mnamer.target import Target  # noqa: E402

logger = logging.getLogger(__name__)


# ============================================================
# 公开数据类（对上层稳定）
# ============================================================
@dataclasses.dataclass
class MnamerResult:
    """mnamer 单次查询的对外结果。"""

    source: str
    """原始文件绝对路径"""

    parsed: dict[str, Any]
    """guessit 解析出的字段（name / year / quality / container 等）"""

    candidates: list[dict[str, Any]]
    """远端候选（已 str() 化为可 JSON 序列化形式），按相关度排序"""

    selected: dict[str, Any] | None
    """若调用方传 `match_index`，则填入选中的候选项；否则 None"""

    target_path: str | None
    """最终目标路径（与 selected 配套）"""

    media_type: str
    """'movie' | 'episode'"""

    error: str | None = None
    """错误信息（无错时 None）"""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ============================================================
# 顶层引擎（单例）
# ============================================================
class MnamerEngine:
    """
    MDCX 异步包装层。

    用法：
        engine = get_mnamer_engine()
        result = await engine.query(Path("/media/movies/abc-123.mp4"))
    """

    def __init__(self) -> None:
        self._settings_cache: dict[str, SettingStore] = {}
        logger.info("MnamerEngine 初始化完成（mnamer 整包已就绪）")

    # -------------------------------------------------------
    # 异步查询
    # -------------------------------------------------------
    async def query(
        self,
        file_path: Path,
        *,
        config: dict[str, Any] | None = None,
        hits: int = 5,
    ) -> MnamerResult:
        """
        异步查询单个文件的元数据候选。

        :param file_path: 待查询的文件绝对路径
        :param config: 可选 mnamer 配置（movie/episode_api_key 等），传 None 用默认
        :param hits: 返回候选数量上限
        :return: MnamerResult
        """
        if not file_path.exists():
            return MnamerResult(
                source=str(file_path),
                parsed={},
                candidates=[],
                selected=None,
                target_path=None,
                media_type="unknown",
                error=f"file not found: {file_path}",
            )

        target = None
        try:
            target = await asyncio.get_event_loop().run_in_executor(
                None, self._build_target, file_path, config, hits
            )
        except MnamerNotFoundException:
            return MnamerResult(
                source=str(file_path),
                parsed=_meta_to_dict(target.metadata) if target is not None else {},
                candidates=[],
                selected=None,
                target_path=None,
                media_type=target.metadata.to_media_type().name.lower() if target is not None else "unknown",
                error="no matches found",
            )
        except MnamerNetworkException:
            return MnamerResult(
                source=str(file_path),
                parsed={},
                candidates=[],
                selected=None,
                target_path=None,
                media_type="unknown",
                error="network error",
            )
        except MnamerException as e:
            logger.exception("mnamer 异常")
            return MnamerResult(
                source=str(file_path),
                parsed={},
                candidates=[],
                selected=None,
                target_path=None,
                media_type="unknown",
                error=f"mnamer exception: {e}",
            )
        except Exception as e:  # 兜底
            logger.exception("query 未预期异常")
            return MnamerResult(
                source=str(file_path),
                parsed={},
                candidates=[],
                selected=None,
                target_path=None,
                media_type="unknown",
                error=f"unexpected: {e}",
            )

        return await self._build_result_from_target(file_path, target, config)

    async def query_batch(
        self,
        file_paths: list[Path],
        *,
        config: dict[str, Any] | None = None,
        hits: int = 5,
    ) -> list[MnamerResult]:
        """批量查询（顺序处理，避免对远端 API 触发并发限流）。"""
        results: list[MnamerResult] = []
        for fp in file_paths:
            results.append(await self.query(fp, config=config, hits=hits))
        return results

    # -------------------------------------------------------
    # 路径计算（不执行 rename）
    # -------------------------------------------------------
    async def compute_target_path(
        self,
        file_path: Path,
        match_index: int,
        *,
        config: dict[str, Any] | None = None,
        hits: int = 5,
    ) -> str | None:
        """
        给定 file_path + 候选下标，计算最终目标路径。
        不执行 rename —— 上层确认后再调用 `rename_file`。
        """
        if not file_path.exists():
            return None
        target = await asyncio.get_event_loop().run_in_executor(
            None, self._build_target, file_path, config, hits
        )
        try:
            matches = target.query()
        except MnamerException:
            return None
        if not matches:
            return None
        if not (0 <= match_index < len(matches)):
            return None
        target.metadata = matches[match_index]
        return str(target.destination)

    # -------------------------------------------------------
    # 同步重命名（在 asyncio.to_thread 包装下安全）
    # -------------------------------------------------------
    async def rename(
        self,
        file_path: Path,
        match_index: int,
        *,
        config: dict[str, Any] | None = None,
        hits: int = 5,
    ) -> str | None:
        """
        异步执行重命名（含目录移动），返回最终路径。
        失败返回 None。
        """
        if not file_path.exists():
            return None
        target = await asyncio.get_event_loop().run_in_executor(
            None, self._build_target, file_path, config, hits
        )
        try:
            matches = target.query()
        except MnamerException:
            return None
        if not matches:
            return None
        if not (0 <= match_index < len(matches)):
            return None
        target.metadata = matches[match_index]
        try:
            await asyncio.get_event_loop().run_in_executor(None, target.relocate)
            return str(target.destination)
        except MnamerException as e:
            logger.error("rename 失败: %s", e)
            return None

    # -------------------------------------------------------
    # 内部：同步构建 Target
    # -------------------------------------------------------
    def _build_target(
        self,
        file_path: Path,
        config: dict[str, Any] | None,
        hits: int,
    ) -> Target:
        settings = self._get_settings(config, hits)
        return Target(file_path, settings)

    def _get_settings(
        self,
        config: dict[str, Any] | None,
        hits: int,
    ) -> SettingStore:
        """从 config 字典构造 SettingStore，无 config 用默认（batch=True 关闭交互）。"""
        cache_key = _settings_cache_key(config, hits)
        if cache_key in self._settings_cache:
            return self._settings_cache[cache_key]
        settings = SettingStore()
        # 默认 batch=True —— 避免 CLI 交互
        if "batch" not in (config or {}):
            settings.batch = True
        # 应用用户 config
        if config:
            for key, val in config.items():
                if hasattr(settings, key):
                    setattr(settings, key, val)
        if hits:
            settings.hits = hits
        self._settings_cache[cache_key] = settings
        return settings

    async def _build_result_from_target(
        self,
        file_path: Path,
        target: Target,
        config: dict[str, Any] | None,
    ) -> MnamerResult:
        """从 target 对象转 MnamerResult(同步部分 run_in_executor)。"""
        try:
            matches = await asyncio.get_event_loop().run_in_executor(
                None, target.query
            )
        except MnamerNotFoundException:
            return MnamerResult(
                source=str(file_path),
                parsed=_meta_to_dict(target.metadata),
                candidates=[],
                selected=None,
                target_path=None,
                media_type=target.metadata.to_media_type().name.lower(),
                error="no matches found",
            )
        except MnamerNetworkException:
            return MnamerResult(
                source=str(file_path),
                parsed=_meta_to_dict(target.metadata),
                candidates=[],
                selected=None,
                target_path=None,
                media_type=target.metadata.to_media_type().name.lower(),
                error="network error",
            )

        candidates = [_meta_to_dict(m) for m in matches]
        return MnamerResult(
            source=str(file_path),
            parsed=_meta_to_dict(target.metadata),
            candidates=candidates,
            selected=None,
            target_path=None,
            media_type=target.metadata.to_media_type().name.lower(),
        )


# ============================================================
# 模块级单例 + 顶层快捷方法
# ============================================================
_engine_singleton: MnamerEngine | None = None


def get_mnamer_engine() -> MnamerEngine:
    """获取单例引擎。"""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = MnamerEngine()
    return _engine_singleton


async def rename_file(
    file_path: str | Path,
    match_index: int,
    *,
    config: dict[str, Any] | None = None,
) -> str | None:
    """快捷方法：异步重命名一个文件。"""
    fp = Path(file_path)
    return await get_mnamer_engine().rename(fp, match_index, config=config)


async def build_target_path(
    file_path: str | Path,
    match_index: int,
    *,
    config: dict[str, Any] | None = None,
) -> str | None:
    """快捷方法：异步计算目标路径（不执行）。"""
    fp = Path(file_path)
    return await get_mnamer_engine().compute_target_path(fp, match_index, config=config)


# ============================================================
# 内部工具
# ============================================================
def _meta_to_dict(meta: Metadata) -> dict[str, Any]:
    """把 mnamer.Metadata 转为可 JSON 序列化的 dict。"""
    base = meta.as_dict()
    # str() 是 "Name (Year)" 形式
    base["display"] = str(meta)
    return base


def _settings_cache_key(config: dict[str, Any] | None, hits: int) -> str:
    """SettingStore 缓存键。"""
    return f"cfg={sorted((config or {}).items())}|hits={hits}"
