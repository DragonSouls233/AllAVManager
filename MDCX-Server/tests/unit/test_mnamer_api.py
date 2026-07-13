"""mnamer API 路由单元测试

验证 app/api/routes/mnamer.py 的 4 个端点:
- GET  /health     : 健康检查
- POST /candidates : 获取候选(404 / 503 边界)
- POST /target     : 预览目标路径(404 边界)
- POST /rename     : 执行重命名(404 边界)

不依赖网络,仅验证路由层契约。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.mnamer import router


@pytest.fixture
def app() -> FastAPI:
    """构造最小 FastAPI 应用,仅挂载 mnamer 路由"""
    _app = FastAPI()
    _app.include_router(router, prefix="/mnamer")
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ============================================================
# 健康检查
# ============================================================
def test_health_returns_available_and_version(client: TestClient):
    """GET /mnamer/health 返回 available + version 字段"""
    resp = client.get("/mnamer/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "version" in data
    assert isinstance(data["available"], bool)


# ============================================================
# /candidates 边界测试
# ============================================================
def test_candidates_nonexistent_file_returns_404(client: TestClient):
    """POST /mnamer/candidates 对不存在的文件返回 404"""
    resp = client.post(
        "/mnamer/candidates",
        json={"file_path": "Z:/nonexistent/path/movie.mkv", "hits": 5},
    )
    assert resp.status_code == 404
    assert "文件不存在" in resp.json()["detail"]


def test_candidates_invalid_hits_returns_422(client: TestClient):
    """POST /mnamer/candidates hits=0 触发 Pydantic 校验错误 422"""
    resp = client.post(
        "/mnamer/candidates",
        json={"file_path": "C:/test.mkv", "hits": 0},
    )
    assert resp.status_code == 422


def test_candidates_missing_file_path_returns_422(client: TestClient):
    """POST /mnamer/candidates 缺 file_path 触发 422"""
    resp = client.post("/mnamer/candidates", json={"hits": 5})
    assert resp.status_code == 422


def test_candidates_hits_optional_uses_config_default(client: TestClient):
    """POST /mnamer/candidates hits 留空时应接受请求(用配置默认值,不触发 422)"""
    resp = client.post(
        "/mnamer/candidates",
        json={"file_path": "Z:/nonexistent/movie.mkv"},
    )
    # 文件不存在返回 404,证明 hits=None 通过了校验
    assert resp.status_code == 404


# ============================================================
# /target 边界测试
# ============================================================
def test_target_nonexistent_file_returns_404(client: TestClient):
    """POST /mnamer/target 对不存在的文件返回 404"""
    resp = client.post(
        "/mnamer/target",
        json={"file_path": "Z:/nonexistent/movie.mkv", "match_index": 0},
    )
    assert resp.status_code == 404


def test_target_negative_index_returns_422(client: TestClient):
    """POST /mnamer/target match_index=-1 触发 422(ge=0)"""
    resp = client.post(
        "/mnamer/target",
        json={"file_path": "C:/test.mkv", "match_index": -1},
    )
    assert resp.status_code == 422


# ============================================================
# /rename 边界测试
# ============================================================
def test_rename_nonexistent_file_returns_404(client: TestClient):
    """POST /mnamer/rename 对不存在的文件返回 404"""
    resp = client.post(
        "/mnamer/rename",
        json={"file_path": "Z:/nonexistent/movie.mkv", "match_index": 0},
    )
    assert resp.status_code == 404


def test_rename_missing_match_index_returns_422(client: TestClient):
    """POST /mnamer/rename 缺 match_index 触发 422"""
    resp = client.post(
        "/mnamer/rename",
        json={"file_path": "C:/test.mkv"},
    )
    assert resp.status_code == 422


# ============================================================
# 路由注册完整性
# ============================================================
def test_router_has_six_endpoints():
    """路由器应注册 6 个端点:health / candidates / target / rename / config(GET) / config(PUT)"""
    paths = {(list(r.methods)[0], r.path) for r in router.routes}
    assert ("GET", "/health") in paths
    assert ("POST", "/candidates") in paths
    assert ("POST", "/target") in paths
    assert ("POST", "/rename") in paths
    assert ("GET", "/config") in paths
    assert ("PUT", "/config") in paths
    assert len(router.routes) == 6


# ============================================================
# /config 配置端点测试(§B4)
# ============================================================
def test_get_config_returns_masked_keys(client: TestClient):
    """GET /mnamer/config 返回掩码 API Key + has_* 布尔标志"""
    resp = client.get("/mnamer/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "omdb_api_key" in data
    assert "tmdb_api_key" in data
    assert "tvdb_api_key" in data
    assert "hits" in data
    assert "prefer_move" in data
    assert "has_omdb" in data
    assert "has_tmdb" in data
    assert "has_tvdb" in data
    assert isinstance(data["has_omdb"], bool)


def test_update_config_enabled(client: TestClient):
    """PUT /mnamer/config 更新 enabled 字段"""
    resp = client.put("/mnamer/config", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # 验证已生效
    resp2 = client.get("/mnamer/config")
    assert resp2.json()["enabled"] is True


def test_update_config_hits_boundary(client: TestClient):
    """PUT /mnamer/config hits=0 触发 422(ge=1)"""
    resp = client.put("/mnamer/config", json={"hits": 0})
    assert resp.status_code == 422


def test_update_config_hits_valid(client: TestClient):
    """PUT /mnamer/config hits=10 合法更新"""
    resp = client.put("/mnamer/config", json={"hits": 10})
    assert resp.status_code == 200
    resp2 = client.get("/mnamer/config")
    assert resp2.json()["hits"] == 10


def test_update_config_empty_string_clears_key(client: TestClient):
    """PUT /mnamer/config omdb_api_key="" 清除已有 key"""
    # 先设值
    client.put("/mnamer/config", json={"omdb_api_key": "test1234"})
    # 再清空
    resp = client.put("/mnamer/config", json={"omdb_api_key": ""})
    assert resp.status_code == 200
    resp2 = client.get("/mnamer/config")
    assert resp2.json()["has_omdb"] is False
