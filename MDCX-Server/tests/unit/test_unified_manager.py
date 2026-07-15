"""
unified_manager.py 单元测试

测试统一下载管理器和路径模板解析功能。
"""

import pytest
from app.services.unified_manager import (
    resolve_download_path,
    _sanitize_filename,
    DOWNLOAD_PATH_TEMPLATES,
)


class TestSanitizeFilename:
    """_sanitize_filename 测试"""

    def test_normal_name(self):
        """正常文件名保持不变"""
        assert _sanitize_filename("hello") == "hello"

    def test_remove_illegal_chars(self):
        """移除 Windows 非法字符"""
        assert _sanitize_filename('test:file*name') == 'testfilename'

    def test_trim_long_name(self):
        """过长文件名截断"""
        long_name = "a" * 200
        result = _sanitize_filename(long_name)
        assert len(result) <= 120

    def test_empty_name(self):
        """空名称返回默认值"""
        assert _sanitize_filename("") == "download"

    def test_only_special_chars(self):
        """全特殊字符返回默认值"""
        assert _sanitize_filename("\\/:*?<>|") == "download"


class TestResolveDownloadPath:
    """resolve_download_path 测试"""

    def test_jav_template(self):
        """JAV 模块路径模板"""
        path = resolve_download_path(
            "jav",
            actor="松本いちか",
            code="ABC-123",
            title="夏の思い出",
            ext="mp4",
        )
        assert "jav" in path
        assert "松本いちか" in path
        assert "ABC-123" in path
        assert "夏の思い出" in path
        assert path.endswith(".mp4")

    def test_chinese_template(self):
        """国产模块路径模板（含下载视频子目录）"""
        path = resolve_download_path(
            "chinese",
            actor="梁佳芯",
            code="MD-0269",
            title="换妻性爱淫元宵",
            ext="mp4",
        )
        assert "chinese" in path
        assert "梁佳芯" in path
        assert "下载视频" in path
        assert "换妻性爱淫元宵" in path

    def test_fc2_template(self):
        """FC2 模块路径模板（不含 actor）"""
        path = resolve_download_path(
            "fc2",
            code="FC2-123456",
            title="初めての個人撮影",
            ext="mp4",
        )
        assert "fc2" in path
        assert "FC2-123456" in path
        assert "初めての個人撮影" in path
        # FC2 模板没有 {actor}，应该是 unknown 或缺省
        assert "unknown" not in path

    def test_pornhub_template(self):
        """PORNHub 模块路径模板（含 upload_date）"""
        path = resolve_download_path(
            "pornhub",
            actor="lana_rhoades",
            code="",
            title="Perfect Body",
            upload_date="2024-01-15",
            ext="mp4",
        )
        assert "pornhub" in path
        assert "lana_rhoades" in path
        assert "2024-01-15" in path

    def test_unknown_module(self):
        """未知模块使用默认模板"""
        path = resolve_download_path(
            "unknown_module",
            title="test_video",
            ext="mkv",
        )
        assert "unknown_module" in path
        assert "test_video" in path
        assert path.endswith(".mkv")

    def test_missing_variable_fallback(self):
        """缺失变量时使用 unknown 占位"""
        path = resolve_download_path("jav", title="test")
        # actor 缺失时应填入 "unknown"
        assert "unknown" in path

    @pytest.mark.parametrize("module", ["jav", "uncensored", "fc2", "chinese", "pornhub"])
    def test_all_modules_have_template(self, module):
        """所有 5 个模块都有对应的路径模板"""
        assert module in DOWNLOAD_PATH_TEMPLATES, f"模块 {module} 缺少路径模板"
        template = DOWNLOAD_PATH_TEMPLATES[module]
        assert "{ext}" in template, f"模板 {module} 缺少 {ext} 变量"


class TestTemplateVariables:
    """路径模板变量完整性测试"""

    def test_required_variables(self):
        """检查所有模板是否包含必需的变量"""
        required = ["{ext}"]
        optional = ["{actor}", "{code}", "{title}", "{upload_date}"]

        for module, template in DOWNLOAD_PATH_TEMPLATES.items():
            # 所有模板必须包含 {ext}
            for var in required:
                assert var in template, f"{module} 模板缺少必需变量 {var}"

            # 国产模板必须包含 {actor}
            if module == "chinese":
                assert "{actor}" in template, "chinese 模板必须包含 {actor}"
                assert "下载视频" in template, "chinese 模板必须包含 '下载视频'"

            # FC2 模板应该包含 {code}
            if module == "fc2":
                assert "{code}" in template, "fc2 模板应该包含 {code}"
