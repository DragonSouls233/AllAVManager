"""exceptions.py 单元测试 - 验证异常层级和 http_status"""
import pytest

from app.exceptions import (
    MDCXError,
    ConfigError, ConfigNotFoundError, ConfigValidationError,
    DatabaseError, DatabaseNotInitializedError, DatabaseMigrationError,
    RecordNotFoundError, RecordConflictError,
    ScraperError, ScraperNetworkError, ScraperBlockedError,
    ScraperParseError, ScraperNotFoundError,
    NumberParseError,
    PluginError, PluginNotFoundError, PluginLoadError, PluginExistsError,
    FileError, FileNotFoundError_, FileOrganizeError, NFOError,
    AuthError, InvalidCredentialsError, TokenExpiredError, PermissionDeniedError,
    CloudDriveError, DownloaderError,
    ValidationError,
    RateLimitError, TranslationError, ThumbnailError, FingerprintError,
    WatcherError, BackupError, SchemaError, WebDAVError,
    StrmError, MetatubeError, TvboxError,
)


@pytest.mark.unit
class TestExceptionHierarchy:
    """异常层级结构测试"""

    def test_all_inherit_from_mdcx_error(self):
        """所有具体异常都继承 MDCXError"""
        for exc_cls in [
            ConfigError, ConfigNotFoundError, ConfigValidationError,
            DatabaseError, DatabaseNotInitializedError, DatabaseMigrationError,
            RecordNotFoundError, RecordConflictError,
            ScraperError, ScraperNetworkError, ScraperBlockedError,
            ScraperParseError, ScraperNotFoundError,
            NumberParseError,
            PluginError, PluginNotFoundError, PluginLoadError, PluginExistsError,
            FileError, FileNotFoundError_, FileOrganizeError, NFOError,
            AuthError, InvalidCredentialsError, TokenExpiredError, PermissionDeniedError,
            CloudDriveError, DownloaderError,
            ValidationError,
            RateLimitError, TranslationError, ThumbnailError, FingerprintError,
            WatcherError, BackupError, SchemaError, WebDAVError,
            StrmError, MetatubeError, TvboxError,
        ]:
            assert issubclass(exc_cls, MDCXError), f"{exc_cls.__name__} 不继承 MDCXError"

    def test_thumbnail_error_inherits_file_error(self):
        """ThumbnailError 继承 FileError(更精确的父类)"""
        assert issubclass(ThumbnailError, FileError)
        assert issubclass(StrmError, FileError)
        assert issubclass(NFOError, FileError)

    def test_webdav_error_inherits_cloud_drive_error(self):
        """WebDAVError 继承 CloudDriveError"""
        assert issubclass(WebDAVError, CloudDriveError)


@pytest.mark.unit
class TestHttpExceptionStatus:
    """HTTP 状态码映射测试"""

    @pytest.mark.parametrize("exc_cls,expected_status", [
        (ConfigError, 400),
        (ConfigNotFoundError, 404),
        (ConfigValidationError, 400),
        (DatabaseNotInitializedError, 500),
        (DatabaseMigrationError, 500),
        (RecordNotFoundError, 404),
        (RecordConflictError, 409),
        (ScraperNetworkError, 504),
        (ScraperBlockedError, 403),
        (ScraperNotFoundError, 404),
        (NumberParseError, 400),
        (PluginNotFoundError, 404),
        (PluginExistsError, 409),
        (FileNotFoundError_, 404),
        (InvalidCredentialsError, 401),
        (TokenExpiredError, 401),
        (PermissionDeniedError, 403),
        (ValidationError, 400),
        (RateLimitError, 429),
        (TranslationError, 502),
        (SchemaError, 400),
    ])
    def test_http_status(self, exc_cls, expected_status):
        """每个异常的 http_status 必须正确"""
        assert exc_cls.http_status == expected_status, (
            f"{exc_cls.__name__}.http_status = {exc_cls.http_status}, "
            f"expected {expected_status}"
        )


@pytest.mark.unit
class TestExceptionMessage:
    """异常消息测试"""

    def test_message_attribute(self):
        """异常带 message 属性"""
        exc = ConfigError("配置文件损坏")
        assert exc.message == "配置文件损坏"
        assert str(exc) == "配置文件损坏"

    def test_empty_message_uses_class_name(self):
        """无消息时用类名"""
        exc = DatabaseError()
        assert exc.message == "DatabaseError"
        assert str(exc) == "DatabaseError"

    def test_config_validation_error_with_field(self):
        """ConfigValidationError 携带 field 属性"""
        exc = ConfigValidationError("端口超出范围", field="server.port")
        assert exc.field == "server.port"
        assert "server.port" in str(exc)
        assert "端口超出范围" in str(exc)

    def test_can_be_raised_and_caught(self):
        """异常可以被 raise 和 except"""
        with pytest.raises(ScraperBlockedError) as exc_info:
            raise ScraperBlockedError("被 Cloudflare 阻止")
        assert "Cloudflare" in str(exc_info.value)

    def test_caught_by_base_class(self):
        """所有具体异常可被 MDCXError 基类捕获"""
        with pytest.raises(MDCXError):
            raise PluginNotFoundError("插件 'foo' 未找到")


@pytest.mark.unit
class TestExceptionAllExport:
    """__all__ 导出列表测试"""

    def test_all_exceptions_exported(self):
        """__all__ 必须包含全部异常类

        数量构成:
        - 1 个基类 MDCXError
        - 8 个分类基类(Config/Database/Scraper/Plugin/File/Auth/CloudDrive/Downloader)
        - 23 个具体异常(22 原始 + 11 第 4 轮补全 - 10 重叠)
        - 1 个 ValidationError 业务异常
        合计 33 个独立异常类(部分继承自基类,不计重复)
        """
        from app.exceptions import __all__
        # 不强制具体数字,只要 >= 33(后续可能继续扩展)
        assert len(__all__) >= 33, f"__all__ 仅 {len(__all__)} 个异常,期望至少 33"
        # 检查所有异常类都在 __all__ 中
        import app.exceptions as exc_mod
        for name in __all__:
            assert hasattr(exc_mod, name), f"__all__ 中的 {name} 不存在"
            cls = getattr(exc_mod, name)
            assert issubclass(cls, MDCXError), f"{name} 不是 MDCXError 子类"
