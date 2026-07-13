"""mnamer 与 file_organize 集成测试(§B5)

验证 mnamer 智能重命名引擎与配置系统的端到端集成:
- MnamerConfig → naming_mnamer_bridge → MnamerEngine → mnamer 整包
- try_mnamer_fallback 完整流程(本地 guessit 解析 + 候选结构)
- 配置注入(API Key 传递到 SettingStore)
- enable_mnamer 开关行为

不依赖网络(远端查询可能失败,但本地 guessit 解析必须工作)。
不实际执行 rename(仅验证 compute_target_path 的契约)。
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config.models import Config, MnamerConfig
from app.services.naming_mnamer_bridge import (
    _build_mnamer_config_dict,
    _default_hits,
    build_mnamer_target,
    execute_mnamer_rename,
    get_mnamer_candidates,
    is_mnamer_available,
    try_mnamer_fallback,
)


# ============================================================
# fixtures
# ============================================================
@pytest.fixture
def tmp_video_file(tmp_path: Path) -> Path:
    """伪造的视频文件(文件名含可解析的元信息)"""
    f = tmp_path / "The.Matrix.1999.1080p.BluRay.x264.mkv"
    f.write_bytes(b"fake video content for integration test")
    return f


@pytest.fixture
def tmp_episode_file(tmp_path: Path) -> Path:
    """伪造的剧集文件"""
    f = tmp_path / "Breaking.Bad.S01E01.720p.mkv"
    f.write_bytes(b"fake episode content")
    return f


@pytest.fixture
def mnamer_enabled_config():
    """构造 enabled=True 的 MnamerConfig(通过 patch get_config)"""
    config = Config()
    config.mnamer.enabled = True
    config.mnamer.hits = 3
    return config


# ============================================================
# 前置条件验证
# ============================================================
def test_mnamer_available():
    """mnamer 整包应已正确加载(否则后续测试无意义)"""
    assert is_mnamer_available(), "mnamer 整包未正确加载,检查 app/external/mnamer/ 与 sys.path"


# ============================================================
# 配置适配层测试
# ============================================================
def test_build_config_dict_reads_from_mnamer_config(mnamer_enabled_config):
    """_build_mnamer_config_dict 应从 AppConfig.mnamer 读取 API Key"""
    with patch("app.config.get_config", return_value=mnamer_enabled_config):
        config_dict = _build_mnamer_config_dict()

    assert config_dict["batch"] is True
    # 无 API Key 时不应包含 api_key_* 字段
    assert "api_key_omdb" not in config_dict
    assert "api_key_tmdb" not in config_dict
    assert "api_key_tvdb" not in config_dict


def test_build_config_dict_includes_api_keys():
    """配置了 API Key 时,config_dict 应包含对应字段"""
    config = Config()
    config.mnamer.omdb_api_key = "test_omdb_key"
    config.mnamer.tmdb_api_key = "test_tmdb_key"
    config.mnamer.tvdb_api_key = "test_tvdb_key"

    with patch("app.config.get_config", return_value=config):
        config_dict = _build_mnamer_config_dict()

    assert config_dict["api_key_omdb"] == "test_omdb_key"
    assert config_dict["api_key_tmdb"] == "test_tmdb_key"
    assert config_dict["api_key_tvdb"] == "test_tvdb_key"
    assert config_dict["batch"] is True


def test_default_hits_reads_from_config():
    """_default_hits 应从 MnamerConfig.hits 读取"""
    config = Config()
    config.mnamer.hits = 15
    with patch("app.config.get_config", return_value=config):
        assert _default_hits() == 15


def test_default_hits_fallback_on_error():
    """get_config 失败时 _default_hits 应返回 5"""
    with patch("app.config.get_config", side_effect=RuntimeError("config not loaded")):
        assert _default_hits() == 5


# ============================================================
# try_mnamer_fallback 端到端测试
# ============================================================
@pytest.mark.asyncio
async def test_try_mnamer_fallback_returns_result_for_real_file(tmp_video_file):
    """try_mnamer_fallback 对真实文件应返回 MnamerResult(至少本地 guessit 解析)"""
    result = await try_mnamer_fallback(tmp_video_file, hits=3)

    # 文件存在 + mnamer 可用 → 必须返回非 None
    assert result is not None
    assert result.source == str(tmp_video_file)
    # guessit 至少能解析出文件名相关字段
    assert isinstance(result.parsed, dict)
    assert isinstance(result.candidates, list)
    # 媒体类型应为 movie 或 unknown(无网络时可能无候选)
    assert result.media_type in ("movie", "episode", "unknown")


@pytest.mark.asyncio
async def test_try_mnamer_fallback_nonexistent_file_returns_none(tmp_path):
    """try_mnamer_fallback 对不存在的文件应返回 None"""
    fake = tmp_path / "nonexistent.mkv"
    result = await try_mnamer_fallback(fake)
    assert result is None


@pytest.mark.asyncio
async def test_try_mnamer_fallback_episode_file(tmp_episode_file):
    """try_mnamer_fallback 对剧集文件应识别为 episode 类型"""
    result = await try_mnamer_fallback(tmp_episode_file, hits=2)
    assert result is not None
    # 媒体类型应包含 episode 特征(或 unknown 如果无网络)
    assert result.media_type in ("episode", "unknown")


# ============================================================
# get_mnamer_candidates 测试
# ============================================================
@pytest.mark.asyncio
async def test_get_mnamer_candidates_returns_list(tmp_video_file):
    """get_mnamer_candidates 应返回 list[dict](即便无网络也返回空列表)"""
    candidates = await get_mnamer_candidates(tmp_video_file, hits=3)
    assert isinstance(candidates, list)
    # 每个候选都应是 dict
    for c in candidates:
        assert isinstance(c, dict)


@pytest.mark.asyncio
async def test_get_mnamer_candidates_nonexistent_returns_empty(tmp_path):
    """get_mnamer_candidates 对不存在的文件应返回空列表"""
    candidates = await get_mnamer_candidates(tmp_path / "no.mkv")
    assert candidates == []


# ============================================================
# build_mnamer_target 测试(不执行 rename)
# ============================================================
@pytest.mark.asyncio
async def test_build_mnamer_target_invalid_index_returns_none(tmp_video_file):
    """build_mnamer_target 对越界下标应返回 None(不崩溃)"""
    target = await build_mnamer_target(tmp_video_file, 9999)
    assert target is None


@pytest.mark.asyncio
async def test_build_mnamer_target_nonexistent_file_returns_none(tmp_path):
    """build_mnamer_target 对不存在的文件应返回 None"""
    target = await build_mnamer_target(tmp_path / "no.mkv", 0)
    assert target is None


# ============================================================
# execute_mnamer_rename 测试(不实际移动文件)
# ============================================================
@pytest.mark.asyncio
async def test_execute_mnamer_rename_invalid_index_returns_none(tmp_video_file):
    """execute_mnamer_rename 对越界下标应返回 None(不执行任何操作)"""
    result = await execute_mnamer_rename(tmp_video_file, 9999)
    assert result is None


@pytest.mark.asyncio
async def test_execute_mnamer_rename_nonexistent_file_returns_none(tmp_path):
    """execute_mnamer_rename 对不存在的文件应返回 None"""
    result = await execute_mnamer_rename(tmp_path / "no.mkv", 0)
    assert result is None


# ============================================================
# 配置开关行为测试
# ============================================================
@pytest.mark.asyncio
async def test_mnamer_disabled_config_still_allows_query(tmp_video_file):
    """即使 mnamer.enabled=False,桥接层仍可调用(开关由调用方决定)

    设计:bridge 层不强制检查 enabled,让 file_organize / 前端自行判断。
    bridge 只负责"被调用时正确传递配置"。
    """
    config = Config()
    config.mnamer.enabled = False
    with patch("app.config.get_config", return_value=config):
        # 仍可调用(不因 enabled=False 而拒绝)
        result = await try_mnamer_fallback(tmp_video_file, hits=2)
        assert result is not None


@pytest.mark.asyncio
async def test_mnamer_enabled_config_passes_api_keys(tmp_video_file):
    """enabled=True + API Key 配置时,config_dict 应包含 key"""
    config = Config()
    config.mnamer.enabled = True
    config.mnamer.omdb_api_key = "integration_test_key"

    with patch("app.config.get_config", return_value=config):
        config_dict = _build_mnamer_config_dict()
        assert config_dict.get("api_key_omdb") == "integration_test_key"

        # 实际查询也应工作(API Key 被传递到引擎)
        result = await try_mnamer_fallback(tmp_video_file, hits=2)
        assert result is not None


# ============================================================
# 完整流程模拟(file_organize 视角)
# ============================================================
@pytest.mark.asyncio
async def test_full_flow_query_then_compute_target(tmp_video_file):
    """模拟 file_organize 的完整流程:查询 → 选候选 → 计算目标路径

    这是 file_organize.py 启用 enable_mnamer=True 时应走的路径:
    1. try_mnamer_fallback(file) → MnamerResult
    2. 如果有候选 → 选第 0 个
    3. build_mnamer_target(file, 0) → 目标路径(或 None 如果无候选)
    """
    # Step 1: 查询
    result = await try_mnamer_fallback(tmp_video_file, hits=3)
    assert result is not None

    # Step 2: 如果有候选,计算目标路径
    if result.candidates:
        target = await build_mnamer_target(tmp_video_file, 0)
        # 有候选时,target 应为有效路径字符串
        assert target is not None
        assert isinstance(target, str)
        assert len(target) > 0
    else:
        # 无候选时(无网络),越界下标返回 None
        target = await build_mnamer_target(tmp_video_file, 0)
        assert target is None
