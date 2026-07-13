"""
统一异常层级

设计参考 mnamer(`mnamer/exceptions.py`)和 Medusa 的异常体系,
为 MDCX 项目建立统一的异常基类,便于:
- API 层用 `except MDCXError` 捕获所有业务异常,转为 HTTPException
- 日志层用异常类型而非字符串消息判断错误类别
- 调用方按需细化捕获粒度(如只捕获 `ScraperError`)

使用建议:
- 业务代码抛异常时,优先使用本模块的具体异常类,而非 RuntimeError/ValueError
- HTTP 路由层用 `except MDCXError as e: raise HTTPException(status_code=e.http_status, detail=str(e))`
- 不要滥用 `MDCXError` 基类本身,优先选具体子类
"""


class MDCXError(Exception):
    """所有 MDCX 业务异常的基类

    Attributes:
        http_status: 默认对应的 HTTP 状态码(子类可覆盖)
        message: 错误消息(已格式化)
    """

    http_status: int = 500

    def __init__(self, message: str = "", *args) -> None:
        self.message = message or self.__class__.__name__
        super().__init__(self.message, *args)

    def __str__(self) -> str:
        return self.message


# ============================================
# 配置类异常
# ============================================
class ConfigError(MDCXError):
    """配置错误(加载失败/校验失败/字段非法)"""
    http_status = 400


class ConfigNotFoundError(ConfigError):
    """配置文件不存在(首次启动场景)"""
    http_status = 404


class ConfigValidationError(ConfigError):
    """配置校验失败(类型错误/字段缺失)"""

    def __init__(self, message: str, field: str = "") -> None:
        self.field = field
        full = f"[{field}] {message}" if field else message
        super().__init__(full)


# ============================================
# 数据库异常
# ============================================
class DatabaseError(MDCXError):
    """数据库异常基类"""
    http_status = 500


class DatabaseNotInitializedError(DatabaseError):
    """数据库未初始化(未调用 init_database)"""
    http_status = 500


class DatabaseMigrationError(DatabaseError):
    """数据库迁移失败"""


class RecordNotFoundError(DatabaseError):
    """记录不存在(对应 404)"""
    http_status = 404


class RecordConflictError(DatabaseError):
    """记录冲突(如唯一约束冲突,对应 409)"""
    http_status = 409


# ============================================
# 刮削器异常
# ============================================
class ScraperError(MDCXError):
    """刮削器异常基类"""
    http_status = 502


class ScraperNetworkError(ScraperError):
    """网络请求失败(连接超时/响应异常)"""
    http_status = 504


class ScraperBlockedError(ScraperError):
    """被目标网站反爬阻止(403/Cloudflare/验证码)"""
    http_status = 403


class ScraperParseError(ScraperError):
    """页面解析失败(选择器失效/字段缺失)"""


class ScraperNotFoundError(ScraperError):
    """目标番号在当前源站无结果"""
    http_status = 404


# ============================================
# 番号识别异常
# ============================================
class NumberParseError(MDCXError):
    """番号识别失败(无法从文件名提取有效番号)"""
    http_status = 400


# ============================================
# 插件异常
# ============================================
class PluginError(MDCXError):
    """插件异常基类"""
    http_status = 500


class PluginNotFoundError(PluginError):
    """插件不存在"""
    http_status = 404


class PluginLoadError(PluginError):
    """插件加载失败(META 缺失/类未继承基类)"""


class PluginExistsError(PluginError):
    """插件已存在(同名重复安装)"""
    http_status = 409


# ============================================
# 文件/IO 异常
# ============================================
class FileError(MDCXError):
    """文件操作异常基类"""
    http_status = 500


class FileNotFoundError_(FileError):
    """文件不存在(避免覆盖内置 FileNotFoundError)"""
    http_status = 404


class FileOrganizeError(FileError):
    """文件整理失败(硬链接/复制/移动失败)"""


class NFOError(FileError):
    """NFO 文件读取/写入/解析错误"""


# ============================================
# 认证/授权异常
# ============================================
class AuthError(MDCXError):
    """认证授权异常基类"""
    http_status = 401


class InvalidCredentialsError(AuthError):
    """用户名/密码错误"""
    http_status = 401


class TokenExpiredError(AuthError):
    """Token 已过期"""


class PermissionDeniedError(AuthError):
    """权限不足(无权访问资源)"""
    http_status = 403


# ============================================
# 网盘/下载器异常
# ============================================
class CloudDriveError(MDCXError):
    """网盘客户端异常(115/CloudDrive2/WebDAV)"""
    http_status = 502


class DownloaderError(MDCXError):
    """下载器异常(qBittorrent/Transmission/Aria2)"""
    http_status = 502


# ============================================
# 业务规则异常
# ============================================
class ValidationError(MDCXError):
    """业务校验失败(如 view_status 非法值)"""
    http_status = 400


# ============================================
# 限流 / 翻译 / 缩略图 / 指纹 / 监控 / 备份(借鉴 OpenAver + Medusa 业务异常)
# ============================================
class RateLimitError(MDCXError):
    """站点频率限制(429)

    与 ScraperBlockedError(403)区分:
    - 429 应触发退避重试(exponential backoff)
    - 403 直接放弃(被识别为爬虫)
    """
    http_status = 429


class TranslationError(MDCXError):
    """翻译服务异常(API key 无效 / 配额超限 / 网络失败)"""
    http_status = 502


class ThumbnailError(FileError):
    """缩略图生成失败(ffmpeg 失败 / 图片损坏)

    FFmpeg 子进程异常应独立于通用 FileError,便于精准捕获。
    """


class FingerprintError(MDCXError):
    """视频指纹计算失败(pHash 算法异常)"""


class WatcherError(MDCXError):
    """目录监控异常(watchdog 初始化失败 / polling 异常)"""


class BackupError(MDCXError):
    """备份/恢复失败(数据库备份失败 / 配置恢复失败)"""


class SchemaError(MDCXError):
    """Schema 校验失败(API 契约测试不通过)"""
    http_status = 400


class WebDAVError(CloudDriveError):
    """WebDAV 专有异常(认证失败 / 路径不存在)"""


class StrmError(FileError):
    """STRM 文件生成/重写失败"""


class MetatubeError(MDCXError):
    """Metatube 协议兼容层异常"""


class TvboxError(MDCXError):
    """TVBox/MacCMS 接口异常"""


__all__ = [
    # 基类
    "MDCXError",
    # 配置
    "ConfigError", "ConfigNotFoundError", "ConfigValidationError",
    # 数据库
    "DatabaseError", "DatabaseNotInitializedError", "DatabaseMigrationError",
    "RecordNotFoundError", "RecordConflictError",
    # 刮削器
    "ScraperError", "ScraperNetworkError", "ScraperBlockedError",
    "ScraperParseError", "ScraperNotFoundError",
    # 番号
    "NumberParseError",
    # 插件
    "PluginError", "PluginNotFoundError", "PluginLoadError", "PluginExistsError",
    # 文件
    "FileError", "FileNotFoundError_", "FileOrganizeError", "NFOError",
    # 认证
    "AuthError", "InvalidCredentialsError", "TokenExpiredError", "PermissionDeniedError",
    # 网盘/下载器
    "CloudDriveError", "DownloaderError",
    # 业务
    "ValidationError",
    # 限流/翻译/缩略图/指纹/监控/备份(第 4 轮补全)
    "RateLimitError", "TranslationError", "ThumbnailError", "FingerprintError",
    "WatcherError", "BackupError", "SchemaError", "WebDAVError",
    "StrmError", "MetatubeError", "TvboxError",
]
