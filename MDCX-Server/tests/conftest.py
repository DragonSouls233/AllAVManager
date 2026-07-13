"""
pytest 全局 fixtures 与配置

设计参考:
- OpenAver `tests/conftest.py`(module-level patch / temp_config_path / samples_dir / fixtures_dir)
- Medusa `tests/conftest.py`(丰富的工厂 fixtures)

pyproject.toml 中已配 `pythonpath = ["."]`,
所以 tests/ 下的测试无需 `sys.path.insert` hack 即可 `from app.xxx import yyy`。
"""
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

# =====================================================================
# 路径常量
# =====================================================================
PROJECT_ROOT = Path(__file__).parent.parent
TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"

# 第三方移植包路径（让 `import mnamer` / `import mdcx` 可用）
# 见 O:\MDCX\MDCX-Server\app\external\README.md
_EXTERNAL_DIR = PROJECT_ROOT / "app" / "external"
for _sub in ("mnamer", "mdcmaster_crawlers", "mdcmaster_tools"):
    _p = str(_EXTERNAL_DIR / _sub)
    if _p not in sys.path and (_EXTERNAL_DIR / _sub).exists():
        sys.path.insert(0, _p)
SAMPLES_DIR = TESTS_DIR / "samples"


# =====================================================================
# Config fixtures
# =====================================================================
@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    """临时 config.yaml,避免污染真实 data/config/config.yaml

    用法:
        def test_something(temp_config_path):
            # 写入测试配置
            temp_config_path.write_text("server:\\n  port: 9999")
            # 重新加载配置
            from app.config.manager import ConfigManager
            ConfigManager._instance = None  # 重置单例
            manager = ConfigManager()
            errors = manager.load()
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"
    config_file.write_text("", encoding="utf-8")

    # monkeypatch CONFIG_FILE 指向临时文件
    from app.config import manager as config_manager
    monkeypatch.setattr(config_manager, "CONFIG_FILE", config_file)

    # 重置单例
    if hasattr(config_manager, "_manager"):
        config_manager._manager = None
    if hasattr(config_manager, "_instance"):
        config_manager._instance = None

    yield config_file

    # 清理
    if hasattr(config_manager, "_manager"):
        config_manager._manager = None
    if hasattr(config_manager, "_instance"):
        config_manager._instance = None


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """隔离的 data 目录,避免污染真实 data/

    用法:
        def test_db(isolated_data_dir):
            # data 目录已指向 tmp_path/data
            from app.db.database import init_database
            db = await init_database(f"sqlite+aiosqlite:///{isolated_data_dir}/test.db")
    """
    data_dir = tmp_path / "data"
    for sub in ("config", "logs", "cache", "backups", "db"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MDCX_DATA_DIR", str(data_dir))
    yield data_dir


# =====================================================================
# 路径 fixtures
# =====================================================================
@pytest.fixture
def fixtures_dir():
    """已录制的 HTTP 响应/HTML/JSON fixtures 目录"""
    return FIXTURES_DIR


@pytest.fixture
def samples_dir():
    """样本数据目录(文件名样本 / NFO 样例 / 图片样例)"""
    return SAMPLES_DIR


@pytest.fixture
def fixtures_response(fixtures_dir):
    """加载录制的 HTTP 响应 fixture

    用法:
        def test_javdb_parse(fixtures_response):
            html = fixtures_response("javdb/SONE-103.html")
            # 解析 html
    """

    def _load(relative_path: str, encoding: str = "utf-8") -> str:
        path = fixtures_dir / "responses" / relative_path
        if not path.exists():
            pytest.skip(f"Fixture not found: {relative_path}")
        return path.read_text(encoding=encoding)

    return _load


@pytest.fixture
def fixtures_json(fixtures_dir):
    """加载 JSON fixture

    用法:
        def test_movie_parse(fixtures_json):
            data = fixtures_json("mock_data/mikami_profile.json")
            assert data["name"] == "三上悠亚"
    """

    def _load(relative_path: str) -> Any:
        path = fixtures_dir / relative_path
        if not path.exists():
            pytest.skip(f"Fixture not found: {relative_path}")
        return json.loads(path.read_text(encoding="utf-8"))

    return _load


# =====================================================================
# 数据库 fixtures
# =====================================================================
@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """临时 SQLite 数据库,带表结构初始化

    用法:
        async def test_movie_repo(test_db):
            from app.db.database import get_database
            db = get_database()
            async with db.session() as session:
                # 数据库操作
                pass
    """
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    monkeypatch.setenv("MDCX_DATABASE_URL", db_url)

    # 重置全局数据库实例
    import app.db.database as db_module
    db_module._database = None

    from app.db.database import init_database
    db = await init_database(db_url)

    yield db

    # 清理
    await db.close()
    db_module._database = None


# =====================================================================
# Mock fixtures
# =====================================================================
@pytest.fixture
def mock_javdb_response(fixtures_response):
    """加载 javdb HTML 响应 fixture"""
    return fixtures_response("javdb/SONE-103.html")


@pytest.fixture
def mock_javbus_response(fixtures_response):
    """加载 javbus HTML 响应 fixture"""
    return fixtures_response("javbus/SSIS-018.html")


@pytest.fixture
def mock_fc2ppvdb_response(fixtures_json):
    """加载 fc2ppvdb JSON 响应 fixture"""
    return fixtures_json("responses/fc2ppvdb/1234567.json")


# =====================================================================
# 工具 fixtures
# =====================================================================
@pytest.fixture
def sample_nfo(fixtures_dir):
    """加载已知良好的 NFO 样例文件(对齐 JavInfo SSIS-018.nfo)"""
    nfo_path = fixtures_dir / "nfo_samples" / "SSIS-018.nfo"
    if not nfo_path.exists():
        # fallback:GitHub-ZIP 中的 JavInfo 样例
        javinfo_nfo = PROJECT_ROOT.parent / "GitHub-ZIP" / "P5-Other" / "JavInfo" / "JavInfo-main" / "SSIS-018.nfo"
        if javinfo_nfo.exists():
            return javinfo_nfo.read_text(encoding="utf-8")
        pytest.skip("NFO sample not found")
    return nfo_path.read_text(encoding="utf-8")


@pytest.fixture
def cleanup_test_files():
    """注册待清理的测试文件

    用法:
        def test_something(cleanup_test_files):
            tmp = Path("test_output.nfo")
            tmp.write_text("...")
            cleanup_test_files(tmp)
            # 测试结束后自动删除
    """
    files_to_clean = []

    def _register(path):
        files_to_clean.append(Path(path))

    yield _register

    for p in files_to_clean:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


# =====================================================================
# pytest hooks
# =====================================================================
def pytest_collection_modifyitems(config, items):
    """自动为测试添加标记

    - tests/unit/ 下的自动加 unit 标记
    - tests/integration/ 下的自动加 integration 标记
    - tests/e2e/ 下的自动加 e2e 标记
    - tests/smoke/ 下的自动加 smoke 标记
    """
    for item in items:
        # 根据路径自动添加 marker
        test_path = Path(item.fspath).relative_to(TESTS_DIR)
        parts = test_path.parts

        if len(parts) >= 2:
            category = parts[0]  # unit / integration / e2e / smoke
            if category in ("unit", "integration", "e2e", "smoke"):
                item.add_marker(getattr(pytest.mark, category))


def pytest_configure(config):
    """注册自定义 marker"""
    for marker in ("unit", "integration", "e2e", "smoke", "slow"):
        config.addinivalue_line(
            "markers",
            f"{marker}: see pyproject.toml [tool.pytest.ini_options].markers",
        )
