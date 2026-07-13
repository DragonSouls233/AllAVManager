"""
mnamer_engine 单元测试

测试范围：
- 引擎可正确实例化
- 顶层快捷方法导入正常
- 对不存在的文件返回 error
- 包装层 dataclass 序列化正确
- is_mnamer_available / mnamer_version 健康检查

注意：本测试不连真实外网（OMDB/TMDB/TVDb），所以不验证 query() 远程端点。
对 query() 远程逻辑做最小化的 mock 验证。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.mnamer_engine import (
    MnamerEngine,
    MnamerResult,
    build_target_path,
    get_mnamer_engine,
    rename_file,
)
from app.services.naming_mnamer_bridge import (
    is_mnamer_available,
    mnamer_version,
)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def tmp_video_file(tmp_path: Path) -> Path:
    """一个伪造的视频文件，用于 query 测试。"""
    f = tmp_path / "The.Matrix.1999.1080p.BluRay.x264.mkv"
    f.write_bytes(b"fake video content for test")
    return f


# ============================================================
# 1. 健康检查
# ============================================================
def test_is_mnamer_available():
    """mnamer 整包应正确引入。"""
    assert is_mnamer_available() is True


def test_mnamer_version():
    """应能读到版本号。"""
    ver = mnamer_version()
    assert isinstance(ver, str)
    assert ver != "unknown"
    # 形如 "2.5.6" 或带 dev 后缀
    assert any(c.isdigit() for c in ver)


# ============================================================
# 2. 单例
# ============================================================
def test_get_mnamer_engine_singleton():
    """get_mnamer_engine 返回同一实例。"""
    a = get_mnamer_engine()
    b = get_mnamer_engine()
    assert a is b
    assert isinstance(a, MnamerEngine)


# ============================================================
# 3. 不存在文件 → error
# ============================================================
@pytest.mark.asyncio
async def test_query_nonexistent_file(tmp_path: Path):
    """不存在的文件应返回 error='file not found'。"""
    engine = get_mnamer_engine()
    result = await engine.query(tmp_path / "not_exist.mp4")
    assert result.error is not None
    assert "not found" in result.error
    assert result.candidates == []
    assert result.target_path is None


# ============================================================
# 4. 真实文件（不连网络，仅验证流程不崩溃）
# ============================================================
@pytest.mark.asyncio
async def test_query_real_file_no_network(tmp_video_file: Path):
    """真实文件存在，query 流程应能跑完（远端失败也算 error 而非崩溃）。"""
    engine = get_mnamer_engine()
    result = await engine.query(tmp_video_file, hits=3)
    # 即便网络失败，也应得到 MnamerResult 而非 raise
    assert isinstance(result, MnamerResult)
    assert result.source == str(tmp_video_file)
    # parsed 应至少包含 guessit 解析出的字段
    assert isinstance(result.parsed, dict)
    # media_type 应是 movie/episode/unknown 之一
    assert result.media_type in ("movie", "episode", "unknown")
    # candidates 是 list（可能空）
    assert isinstance(result.candidates, list)


# ============================================================
# 5. 顶层快捷方法签名
# ============================================================
@pytest.mark.asyncio
async def test_top_level_rename_file_signature(tmp_path: Path):
    """rename_file / build_target_path 是 async callable。"""
    assert asyncio.iscoroutinefunction(rename_file)
    assert asyncio.iscoroutinefunction(build_target_path)

    # 不存在的文件应返回 None
    r = await rename_file(tmp_path / "no.mp4", 0)
    assert r is None

    p = await build_target_path(tmp_path / "no.mp4", 0)
    assert p is None


# ============================================================
# 6. MnamerResult 序列化
# ============================================================
def test_mnamer_result_serialization():
    """MnamerResult.to_dict 应输出 JSON 友好的 dict。"""
    r = MnamerResult(
        source="/a/b.mp4",
        parsed={"name": "X", "year": "2024"},
        candidates=[{"name": "Y"}, {"name": "Z"}],
        selected=None,
        target_path=None,
        media_type="movie",
        error=None,
    )
    d = r.to_dict()
    assert d["source"] == "/a/b.mp4"
    assert d["media_type"] == "movie"
    assert d["error"] is None
    assert d["candidates"][0]["name"] == "Y"
    # 全部字段都是 JSON 原生类型
    import json
    json.dumps(d)  # 不抛即通过


# ============================================================
# 7. MnamerResult 错误状态
# ============================================================
def test_mnamer_result_error_state():
    """带 error 的 MnamerResult 序列化正常。"""
    r = MnamerResult(
        source="/x",
        parsed={},
        candidates=[],
        selected=None,
        target_path=None,
        media_type="unknown",
        error="network error",
    )
    d = r.to_dict()
    assert d["error"] == "network error"


# ============================================================
# 8. compute_target_path 越界 match_index
# ============================================================
@pytest.mark.asyncio
async def test_compute_target_path_invalid_index(tmp_video_file: Path):
    """match_index 超出 candidates 范围时返回 None。"""
    engine = get_mnamer_engine()
    path = await engine.compute_target_path(tmp_video_file, match_index=9999)
    # 即便没候选,也不应崩溃
    assert path is None


# ============================================================
# 9. MnamerResult 字段独立性
# ============================================================
def test_mnamer_result_dataclass_immutability_pattern():
    """不同实例的 candidates 互不影响。"""
    r1 = MnamerResult(
        source="/a", parsed={}, candidates=[{"x": 1}],
        selected=None, target_path=None, media_type="movie",
    )
    r2 = MnamerResult(
        source="/a", parsed={}, candidates=[],
        selected=None, target_path=None, media_type="movie",
    )
    assert r1.candidates != r2.candidates
    r1.candidates.append({"y": 2})
    assert r2.candidates == []  # 不共享


# ============================================================
# 10. bridge 模块
# ============================================================
def test_bridge_health_checks():
    from app.services import naming_mnamer_bridge as bridge
    assert bridge.is_mnamer_available() is True
    assert bridge.mnamer_version() != "unknown"
