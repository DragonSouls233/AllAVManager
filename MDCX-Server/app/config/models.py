"""
配置数据模型 - 使用 Pydantic 进行类型验证
"""

import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config.module_models import ModulesConfig


class ServerConfig(BaseModel):
    """服务器配置"""
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="0.0.0.0", title="监听地址")
    port: int = Field(default=8420, ge=1, le=65535, title="监听端口")
    workers: int = Field(default=1, ge=1, le=16, title="工作进程数")
    debug: bool = Field(default=False, title="调试模式")


class DatabaseConfig(BaseModel):
    """数据库配置"""
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        default="sqlite+aiosqlite:///data/database/scraper.db",
        title="数据库连接URL"
    )
    pool_size: int = Field(default=20, ge=1, le=30, title="连接池大小")
    echo: bool = Field(default=False, title="SQL日志")


class ScraperConfig(BaseModel):
    """刮削配置"""
    model_config = ConfigDict(extra="forbid")

    media_dirs: list[str] = Field(
        default_factory=list,
        title="媒体目录列表"
    )
    output_dir: str = Field(
        default="output", 
        title="输出目录（相对服务端根目录）"
    )
    concurrent_limit: int = Field(default=10, ge=1, le=50, title="并发限制")
    retry_count: int = Field(default=3, ge=0, le=10, title="重试次数")
    timeout: int = Field(default=30, ge=5, le=300, title="请求超时(秒)")
    language: Literal["zh", "en", "ja"] = Field(default="zh", title="元数据语言")


class CrawlerConfig(BaseModel):
    """爬虫配置"""
    model_config = ConfigDict(extra="forbid")

    javdb_cookie: str | None = Field(default=None, title="JavDB Cookie")
    javbus_cookie: str | None = Field(default=None, title="JavBus Cookie")
    fc2ppvdb_cookie: str | None = Field(default=None, title="FC2PPVDB Cookie")


class CookieCloudConfig(BaseModel):
    """CookieCloud 配置（从浏览器扩展同步 Cookie）

    CookieCloud 协议：
    - 浏览器扩展加密上传 Cookie 到 CookieCloud 服务器
    - 本服务用 server_url + user_id + password 拉取并解密
    - 自动按域名提取对应站点的 Cookie，覆盖到 CrawlerConfig
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 CookieCloud 同步")
    server_url: str = Field(default="https://cookiecloud.example.com", title="CookieCloud 服务器地址")
    user_id: str = Field(default="", title="用户 ID（UUID）")
    password: str = Field(default="", title="加密密码")
    # 站点域名 → CrawlerConfig 字段映射
    # 例如 {"javdb.com": "javdb_cookie", "javbus.com": "javbus_cookie"}
    domain_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "javdb.com": "javdb_cookie",
            "javbus.com": "javbus_cookie",
            "fc2ppvdb.com": "fc2ppvdb_cookie",
        },
        title="域名到 Cookie 字段的映射"
    )
    auto_sync_interval: int = Field(default=3600, ge=300, le=86400, title="自动同步间隔（秒）")
    last_sync_at: str | None = Field(default=None, title="上次同步时间")


class WatcherConfig(BaseModel):
    """目录监控配置（双模：watchdog / polling）

    watchdog（基于 inotify/FSEvents/ReadDirectoryChangesW）：
      - 实时响应，CPU 占用低
      - 但在 NAS、网络挂载盘、SMB/CIFS 共享上可能不工作
      - Windows 上需要管理员权限监听某些目录

    polling（轮询）：
      - 兼容性最好，所有文件系统都能工作
      - 定期扫描目录对比 mtime 变化
      - CPU 占用略高，但可配置间隔
    """
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="auto", title="监控模式", description="auto/watchdog/polling")
    # auto: 优先 watchdog，失败回退 polling
    # watchdog: 仅用 watchdog（网络盘可能不工作）
    # polling: 仅用轮询
    debounce_interval: float = Field(default=5.0, ge=0.5, le=60, title="防抖间隔（秒）")
    poll_interval: int = Field(default=60, ge=10, le=3600, title="轮询间隔（秒，仅 polling 模式）")
    # 轮询时的快照存储（目录 → {path → mtime}），用于对比变化
    recursive: bool = Field(default=True, title="递归监控子目录")
    video_extensions: list[str] = Field(
        default_factory=lambda: [".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v", ".rm", ".rmvb", ".mpg", ".mpeg", ".ts", ".m2ts", ".webm"],
        title="监控的视频文件扩展名"
    )


class ProxyConfig(BaseModel):
    """代理配置"""
    model_config = ConfigDict(extra="forbid")

    http: str | None = Field(default=None, title="HTTP代理")
    socks5: str | None = Field(default=None, title="SOCKS5代理")
    enabled: bool = Field(default=False, title="是否启用代理")
    protocol: str = Field(default="http", title="代理协议", description="http 或 socks5")
    address: str = Field(default="", title="代理地址")
    port: str = Field(default="", title="代理端口")

    @model_validator(mode="after")
    def _sync_proxy_fields(self):
        """自动同步代理字段。

        修复历史问题：enabled=true 但 address/port 为空时，proxy_url 返回 None，
        导致爬虫实际不走代理。本验证器确保：
        1. 如果 enabled=true 且 address/port 非空，自动同步 http/socks5 字段
        2. 如果 enabled=true 但 address/port 为空，且有 http 字段，从 http 字段解析回 address/port
        """
        # 情况 1：address/port 有值，同步到 http/socks5
        if self.enabled and self.address and self.port:
            url = f"{self.protocol}://{self.address}:{self.port}"
            if self.protocol == "http":
                object.__setattr__(self, "http", url)
            elif self.protocol == "socks5":
                object.__setattr__(self, "socks5", url)
        # 情况 2：address/port 为空，但 http/socks5 有值，尝试解析
        elif self.enabled and not self.address and not self.port:
            for proto, raw in (("http", self.http), ("socks5", self.socks5)):
                if raw and "://" in raw:
                    try:
                        # 简单解析 protocol://address:port
                        rest = raw.split("://", 1)[1]
                        if ":" in rest:
                            addr, port_str = rest.rsplit(":", 1)
                            object.__setattr__(self, "protocol", proto)
                            object.__setattr__(self, "address", addr)
                            object.__setattr__(self, "port", port_str)
                    except (ValueError, IndexError):
                        pass
                    break
        return self

    @property
    def proxy_url(self) -> str | None:
        """生成完整的代理URL"""
        if not self.enabled or not self.address or not self.port:
            return None
        return f"{self.protocol}://{self.address}:{self.port}"


class EmbyConfig(BaseModel):
    """Emby配置"""
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, title="Emby服务器地址")
    api_key: str | None = Field(default=None, title="API密钥")
    enabled: bool = Field(default=False, title="是否启用Emby集成")


class JellyfinConfig(BaseModel):
    """Jellyfin配置"""
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, title="Jellyfin服务器地址")
    api_key: str | None = Field(default=None, title="API密钥")
    enabled: bool = Field(default=False, title="是否启用Jellyfin集成")


class LogConfig(BaseModel):
    """日志配置"""
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", title="日志级别"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        title="日志格式"
    )
    file_enabled: bool = Field(default=True, title="是否输出到文件")
    console_enabled: bool = Field(default=True, title="是否输出到控制台")


class TranslateConfig(BaseModel):
    """翻译配置

    支持 6 个引擎:
    - openai: OpenAI ChatCompletions API
    - google: Google Translate 免费端点
    - deepl: DeepL API (真批量)
    - baidu: 百度翻译 (API 签名 + QPS 限流)
    - bing: 微软 Bing 翻译 (含女优名保护词典)
    - claude: Anthropic Claude Messages API

    api_key 格式:
    - openai/deepl/bing/claude: 直接填 API key
    - baidu: "app_id|api_key" (用 | 分隔)
    - google: 无需 api_key
    """
    model_config = ConfigDict(extra="forbid")

    engine: Literal["openai", "google", "deepl", "baidu", "bing", "claude"] = Field(
        default="google", title="翻译引擎"
    )
    api_key: str | None = Field(default=None, title="API密钥")
    api_base: str | None = Field(default=None, title="自定义API端点")
    source_lang: str = Field(default="ja", title="源语言")
    target_lang: str = Field(default="zh", title="目标语言")
    model: str | None = Field(default=None, title="模型名(OpenAI/Claude 使用)")
    timeout: int = Field(default=30, ge=5, le=120, title="请求超时(秒)")


class WebhookConfig(BaseModel):
    """Webhook配置"""
    model_config = ConfigDict(extra="forbid")

    telegram_token: str | None = Field(default=None, title="Telegram Bot Token")
    telegram_chat_id: str | None = Field(default=None, title="Telegram Chat ID")
    discord_url: str | None = Field(default=None, title="Discord Webhook URL")
    wechat_url: str | None = Field(default=None, title="企业微信 Webhook URL")
    enabled: bool = Field(default=False, title="是否启用Webhook")


class AuthConfig(BaseModel):
    """认证配置 - 局域网可信 IP 自动登录"""
    model_config = ConfigDict(extra="forbid")

    # 是否启用局域网 IP 白名单自动放行
    enable_trusted_ip: bool = Field(default=False, title="启用可信IP自动登录")
    # 可信 IP 列表（支持单 IP 和 CIDR，如 192.168.1.0/24）
    trusted_ips: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"],
        title="可信IP列表"
    )


class WebDAVClientConfig(BaseModel):
    """WebDAV 客户端配置（用于从远程 WebDAV 服务器导入影片）"""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 WebDAV 导入")
    url: str | None = Field(default=None, title="WebDAV 服务器地址")
    username: str | None = Field(default=None, title="用户名")
    password: str | None = Field(default=None, title="密码")
    base_path: str = Field(default="/", title="基础路径")
    # 导入后是否将远程路径记入 movie.file_path
    link_mode: Literal["copy", "move", "link"] = Field(
        default="link", title="导入模式: copy=下载到本地 / move=移动 / link=仅记录路径"
    )


class WebDAVServerConfig(BaseModel):
    """WebDAV 服务端配置（暴露本地媒体库给外部客户端）"""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 WebDAV 服务端")
    mount_path: str = Field(default="/webdav", title="URL 挂载路径")
    username: str | None = Field(default=None, title="访问用户名")
    password: str | None = Field(default=None, title="访问密码")
    # 是否按番号虚拟目录: /webdav/{code}.mp4
    virtual_layout: Literal["flat", "by_actor", "by_studio", "by_code"] = Field(
        default="by_code", title="虚拟目录布局"
    )


class FaceCropConfig(BaseModel):
    """AI 人脸裁剪配置（参考 mdc-ng / Hazard804）"""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 AI 人脸裁剪")
    model_path: str | None = Field(default=None, title="YuNet ONNX 模型路径（留空则从 HuggingFace 下载）")
    # 裁剪策略：poster=竖海报(2:3) / cover=横封面(4:3) / both
    target: Literal["poster", "cover", "both"] = Field(default="poster", title="裁剪目标")
    # 人脸检测最小尺寸
    min_face_size: int = Field(default=80, ge=20, le=500, title="最小人脸尺寸")
    # 输出质量
    output_quality: int = Field(default=95, ge=50, le=100, title="输出 JPEG 质量")
    # 边距比例（人脸框外的扩展比例）
    margin_ratio: float = Field(default=0.4, ge=0.0, le=1.0, title="人脸框边距比例")


class NetworkDiagConfig(BaseModel):
    """网络诊断配置"""
    model_config = ConfigDict(extra="forbid")

    timeout: int = Field(default=10, ge=3, le=60, title="超时(秒)")
    # 诊断目标站点列表
    target_sites: list[str] = Field(
        default_factory=lambda: ["javdb", "javbus", "dmm", "fc2ppvdb", "missav"],
        title="诊断目标站点"
    )


class NamingConfig(BaseModel):
    """命名模板配置（参考 Hazard804-mdcx 的 Jinja2 沙箱模板）"""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用自定义命名模板")
    # 文件名模板，例如: "[{{ code }}]{{ title }}"
    file_template: str = Field(
        default="[{{ code }}] {{ title }}",
        title="文件名模板",
    )
    # 目录名模板，例如: "{{ studio }}/{{ release_year }}/{{ code }}"
    dir_template: str = Field(
        default="{{ studio }}/{{ release_year }}/{{ code }}",
        title="目录名模板",
    )
    # 海报名模板
    poster_template: str = Field(
        default="{{ code }}-poster",
        title="海报文件名模板",
    )
    # 缩略图名模板
    thumb_template: str = Field(
        default="{{ code }}-thumb",
        title="缩略图文件名模板",
    )
    # 是否将非法字符替换为下划线（True）或直接删除（False）
    replace_invalid_to_underscore: bool = Field(default=True, title="非法字符替换为下划线")
    # 文件名最大长度（防止超出文件系统路径长度限制）
    max_length: int = Field(default=120, ge=20, le=255, title="文件名最大长度")


class MnamerConfig(BaseModel):
    """mnamer 智能重命名引擎配置（§17+ 移植,§B4）

    mnamer 整包位于 app/external/mnamer/(MIT),本配置控制:
    - 是否启用智能重命名(作为 Jinja2 模板的 fallback)
    - 远端元数据查询的 API Key(OMDB/TMDB/TVDB)
    - 默认候选数量与移动行为

    无 API Key 时仍可工作(仅本地 guessit 解析),但远端查询会失败。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 mnamer 智能重命名")
    # OMDB API Key(www.omdbapi.com),用于 IMDB 元数据查询
    omdb_api_key: str | None = Field(default=None, title="OMDB API Key")
    # TMDB API Key(themoviedb.org),用于电影元数据查询
    tmdb_api_key: str | None = Field(default=None, title="TMDB API Key")
    # TVDB API Key(thetvdb.com),用于剧集元数据查询
    tvdb_api_key: str | None = Field(default=None, title="TVDB API Key")
    # 默认返回候选数量(1-20)
    hits: int = Field(default=5, ge=1, le=20, title="默认候选数量")
    # 重命名时移动文件(True)而非复制(False)
    prefer_move: bool = Field(default=True, title="移动而非复制")


class EmbyConfig2(BaseModel):
    """Emby 协议兼容配置（参考 MediaStationGo）

    启用后 Infuse/VidHub/SenPlayer/Fileball 等 Emby 客户端可直接接入。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 Emby 协议兼容")
    # 客户端接入时使用的 API Key（无需用户名密码的鉴权方式）
    api_key: str | None = Field(default=None, title="Emby API Key")
    # 服务端名（在客户端列表中显示）
    server_name: str = Field(default="MDCX Media Server", title="服务器名称")
    # 版本号（伪装成 Emby 协议版本，便于客户端兼容）
    version: str = Field(default="4.8.10.0", title="协议版本")
    # 对外暴露的播放协议（http / https）
    play_protocol: Literal["http", "https"] = Field(default="http", title="播放协议")
    # 是否对 Emby 接口隐藏 NSFW 内容（仅显示已收藏的影片）
    nsfw_hidden: bool = Field(default=True, title="隐藏 NSFW 内容")
    # 单页返回的最大条目数（Emby 客户端通常分页加载）
    page_size: int = Field(default=100, ge=10, le=500, title="单页条目数")


class StrmConfig(BaseModel):
    """STRM 文件生成配置

    STRM 文件是包含视频 URL 的文本文件，可被 Emby/Jellyfin/Kodi 等媒体服务器索引，
    让本地媒体库能识别远程流媒体 URL（如同本地文件）。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 STRM 文件生成")
    # STRM 文件输出根目录
    output_dir: str = Field(default="data/strm", title="STRM 输出目录")
    # 是否按目录模板组织（True）或全部平铺（False）
    use_directory_template: bool = Field(default=True, title="按目录模板组织")
    # 流媒体 URL 模板，例如: http://localhost:8420/api/v1/movies/{id}/play/external
    url_template: str = Field(
        default="http://localhost:8420/api/v1/movies/{id}/play/external",
        title="流媒体 URL 模板",
    )
    # 是否在生成 STRM 时同步生成 NFO 文件
    generate_nfo: bool = Field(default=True, title="同步生成 NFO")
    # 是否覆盖已存在的 STRM 文件
    overwrite: bool = Field(default=False, title="覆盖已存在的文件")


class NsfwConfig(BaseModel):
    """NSFW 模式配置（参考 mdc-ng）"""
    model_config = ConfigDict(extra="forbid")

    # 是否启用 NSFW 模式（隐藏敏感内容）
    enabled: bool = Field(default=False, title="启用 NSFW 模式")
    # 隐藏封面（用占位图替换）
    hide_cover: bool = Field(default=True, title="隐藏封面")
    # 隐藏标题（用编号替换）
    hide_title: bool = Field(default=False, title="隐藏标题")
    # 隐藏演员头像
    hide_actor_avatar: bool = Field(default=True, title="隐藏演员头像")
    # 截图模糊处理
    blur_thumbnails: bool = Field(default=True, title="截图模糊处理")
    # 模糊强度（CSS filter 的 px 值）
    blur_intensity: int = Field(default=20, ge=1, le=50, title="模糊强度")


class MosaicConfig(BaseModel):
    """马赛克类型识别配置（参考 Hazard804-mdcx 的 mosaic.py）

    根据番号规则判断影片马赛克类型，影响爬虫选站：
    - 国产：番号通常无规则或 "国产" 关键字
    - 无码：FC2-PPV、Tokyo Hot、Caribbean 等系列前缀
    - 有码：标准番号 ABC-123
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, title="启用马赛克类型自动识别")
    # 是否在刮削时自动写入 is_uncensored / is_mosaic 字段
    auto_update_movie: bool = Field(default=True, title="自动更新影片字段")


class SitePriorityConfig(BaseModel):
    """站点优先级配置"""
    model_config = ConfigDict(extra="forbid")

    # 全局默认优先级（站点未单独配置时使用）
    default_priority: int = Field(default=50, ge=1, le=100, title="默认优先级")
    # 同一字段多源冲突时的合并策略：highest（取最高优先级源）/ first_available（按优先级取首个非空）
    field_merge_strategy: Literal["highest", "first_available"] = Field(
        default="highest", title="字段合并策略"
    )


class CloudDrive2Config(BaseModel):
    """CloudDrive2 配置（对接 CloudDrive2 服务的 API）

    CloudDrive2 是一个开源的云盘聚合服务，支持 115、阿里云盘、百度网盘等。
    通过此配置可以浏览云端文件、流式播放、批量扫描并导入到本地数据库。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 CloudDrive2 集成")
    url: str = Field(default="http://localhost:19798", title="CloudDrive2 服务器地址")
    username: str = Field(default="", title="用户名")
    password: str = Field(default="", title="密码")
    # 基础路径（云盘挂载根路径，如 /115 或 /aliyun）
    base_path: str = Field(default="/", title="基础路径")
    # 扫描时识别的视频扩展名
    video_extensions: list[str] = Field(
        default_factory=lambda: [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".webm"],
        title="视频文件扩展名",
    )
    # 流式播放时使用的本地代理端口（0 = 不启用本地代理）
    proxy_port: int = Field(default=0, ge=0, le=65535, title="本地流式代理端口")
    # 连接超时（秒）
    timeout: int = Field(default=30, ge=5, le=120, title="连接超时")


class QBittorrentConfig(BaseModel):
    """qBittorrent Web API 配置（§7.11）

    通过 qBittorrent 的 Web API（/api/v2/*）对接，支持添加种子/磁力链、
    查询任务、暂停/恢复/删除任务。认证方式为用户名+密码登录获取 Cookie。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 qBittorrent")
    host: str = Field(default="127.0.0.1", title="qBittorrent 主机地址")
    port: int = Field(default=8080, ge=1, le=65535, title="qBittorrent Web UI 端口")
    username: str = Field(default="admin", title="用户名")
    password: str = Field(default="adminadmin", title="密码")
    # 是否禁用 HTTPS 校验（自签名证书时使用）
    verify_ssl: bool = Field(default=True, title="校验 SSL 证书")
    # 默认下载目录（留空则使用 qBittorrent 默认下载路径）
    download_dir: str | None = Field(default=None, title="默认下载目录")


class TransmissionConfig(BaseModel):
    """Transmission RPC 配置（§7.11）

    通过 Transmission 的 RPC 端点（/transmission/rpc）对接。
    采用 session-header 鉴权机制（401 冲突 → X-Transmission-Session-Id）。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 Transmission")
    host: str = Field(default="127.0.0.1", title="Transmission 主机地址")
    port: int = Field(default=9091, ge=1, le=65535, title="Transmission RPC 端口")
    username: str = Field(default="", title="用户名（可空）")
    password: str = Field(default="", title="密码（可空）")
    # 是否启用 HTTPS
    use_ssl: bool = Field(default=False, title="使用 HTTPS")
    # RPC 路径（默认 /transmission/rpc）
    rpc_path: str = Field(default="/transmission/rpc", title="RPC 路径")
    # 默认下载目录
    download_dir: str | None = Field(default=None, title="默认下载目录")


class Aria2Config(BaseModel):
    """Aria2 JSON-RPC 配置（§7.11）

    通过 aria2 的 JSON-RPC 接口对接（method=aria2.addUri / aria2.tellActive 等）。
    认证方式为 RPC secret token。可作为迅雷的通用替代方案。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 Aria2")
    # 完整 RPC URL，例如 http://localhost:6800/jsonrpc
    rpc_url: str = Field(default="http://localhost:6800/jsonrpc", title="Aria2 RPC URL")
    # RPC secret（aria2.conf 中 rpc-secret 配置项；留空则不鉴权）
    secret: str = Field(default="", title="RPC secret token")
    # 默认下载目录
    download_dir: str | None = Field(default=None, title="默认下载目录")


class DownloaderConfig(BaseModel):
    """下载器统一配置（§7.11）

    支持对接 qBittorrent / Transmission / Aria2 三种主流下载器。
    active 字段决定当前激活的下载器（qbittorrent / transmission / aria2）。
    """
    model_config = ConfigDict(extra="forbid")

    # 当前激活的下载器名称（qbittorrent / transmission / aria2）
    active: str = Field(default="", title="当前激活的下载器")
    qbittorrent: QBittorrentConfig = Field(default_factory=QBittorrentConfig, title="qBittorrent 配置")
    transmission: TransmissionConfig = Field(default_factory=TransmissionConfig, title="Transmission 配置")
    aria2: Aria2Config = Field(default_factory=Aria2Config, title="Aria2 配置")


class Pan115Config(BaseModel):
    """115 网盘离线下载配置（§7.6）

    对接 115 网盘 Web API（公开端点，无需 SDK），支持：
    - 离线下载任务管理（添加磁力链/HTTP 链接、查询、取消）
    - 文件列表浏览（按文件夹 ID 导航）
    - 离线下载完成后可选自动入库到本地媒体库

    认证方式：通过浏览器抓取的 cookies 或 access token。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 115 网盘离线下载")
    # 登录 Cookie 字符串（从浏览器抓取，多个用 ; 分隔，如 UID=xxx; CID=xxx; SEID=xxx）
    cookies: str | None = Field(default=None, title="115 网盘 Cookie")
    # Access Token（部分接口可用，留空则使用 Cookie 认证）
    token: str | None = Field(default=None, title="115 网盘 Access Token")
    # 离线下载完成后是否自动入库到本地媒体库
    auto_link_to_library: bool = Field(default=False, title="离线下载后自动入库")
    # 离线下载目标文件夹 ID（115 网盘的文件夹 ID，留空则使用根目录）
    target_folder_id: str | None = Field(default=None, title="离线下载目标文件夹 ID")


class MetatubeConfig(BaseModel):
    """Metatube 插件配置（Jellyfin metatube 协议兼容）

    实现 metatube-community/metatube-sdk-go 的 HTTP API 兼容层，
    让 Jellyfin 可以直接调用 MDCX 作为元数据提供者。

    参考：https://github.com/metatube-community/metatube-sdk-go
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 Metatube 兼容")
    # 路由前缀（默认 /metatube，对应 Jellyfin 插件配置的 base url）
    base_path: str = Field(default="/metatube", title="路由前缀")
    # 插件名称（显示在 Jellyfin 中）
    plugin_name: str = Field(default="MDCX", title="插件名称")
    # 鉴权 token（空则不鉴权）
    token: str = Field(default="", title="访问令牌（空则不鉴权）")
    # 默认图片质量（1-100）
    image_quality: int = Field(default=85, ge=1, le=100, title="图片质量")
    # 是否返回图片 Base64（True）或直接重定向（False）
    image_base64: bool = Field(default=False, title="图片返回 Base64")
    # 默认搜索数量限制
    search_limit: int = Field(default=20, ge=1, le=100, title="搜索结果数量")
    # 是否允许 NSFW 内容
    allow_nsfw: bool = Field(default=True, title="允许 NSFW 内容")


class TvboxConfig(BaseModel):
    """TVBox / MacCMS 开放接口配置（§7.10）

    让 TVBox / MacCMS 客户端能直接接入 MDCX 媒体库。
    - TVBox 接口挂在 /tvbox/* 下（独立挂载，不走 /api/v1 前缀）
    - MacCMS 接口挂在 /maccms/* 下（独立挂载，不走 /api/v1 前缀）

    参考：
    - TVBox: https://github.com/CatVodTVOfficial/TVBoxOSC
    - MacCMS v10 API: 苹果 CMS v10 采集接口规范
    """
    model_config = ConfigDict(extra="forbid")

    # 是否启用 TVBox / MacCMS 开放接口
    enabled: bool = Field(default=False, title="启用 TVBox/MacCMS 接口")
    # 可选的访问令牌（query 参数 token=xxx 校验，留空则不鉴权）
    token: str | None = Field(default=None, title="访问令牌（留空则不鉴权）")
    # 列表分页大小
    page_size: int = Field(default=20, ge=1, le=100, title="分页大小")
    # 是否默认隐藏 NSFW 内容（仅展示已收藏的影片）
    nsfw_hidden: bool = Field(default=True, title="隐藏 NSFW 内容")
    # 站点名称（在 TVBox/MacCMS 客户端中显示）
    site_name: str = Field(default="MDCX 媒体库", title="站点名称")
    # 播放源标识（vod_play_from 字段值）
    play_from: str = Field(default="MDCX", title="播放源标识")


class ThemesConfig(BaseModel):
    """皮肤主题配置（§7.8 皮肤插件机制）

    主题插件化，用户可自定义 UI 配色。与明暗模式（light/dark）解耦：
    - active_theme 指定当前颜色皮肤（accent 主题色 + 圆角 + 字号）
    - 明暗模式由前端 theme.js 管理（light/dark/system 三态切换）
    - custom_themes_json 以 JSON 字符串存储用户自定义主题列表
    """
    model_config = ConfigDict(extra="forbid")

    # 当前激活的主题名（对应 themes/ 目录下的预设或自定义主题名）
    active_theme: str = Field(default="default", title="当前激活主题")
    # 自定义主题列表的 JSON 字符串（序列化的主题对象数组）
    custom_themes_json: str | None = Field(
        default=None, title="自定义主题 JSON 字符串"
    )
    # 是否自动检测系统深浅色（联动 theme.js 的 system 模式）
    auto_detect_system: bool = Field(
        default=True, title="自动检测系统深浅色"
    )


class PostgresConfig(BaseModel):
    """PostgreSQL 配置（Level 2 多用户并发场景）"""
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="127.0.0.1", title="PostgreSQL 主机")
    port: int = Field(default=5432, ge=1, le=65535, title="PostgreSQL 端口")
    username: str = Field(default="mdcx", title="用户名")
    password: str = Field(default="", title="密码")
    database: str = Field(default="mdcx", title="数据库名")
    # 连接池大小（asyncpg）
    pool_size: int = Field(default=10, ge=1, le=50, title="连接池大小")
    # SSL 模式：disable / prefer / require / verify-ca / verify-full
    ssl_mode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = Field(
        default="prefer", title="SSL 模式"
    )


class RedisConfig(BaseModel):
    """Redis 配置（Level 3 缓存层）

    用于：
    - 站点请求频率限制（防封禁）
    - 热门影片元数据缓存
    - WebSocket 多实例消息广播（pub/sub）
    - 分布式任务队列状态
    """
    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="redis://127.0.0.1:6379/0", title="Redis 连接 URL")
    # 连接超时（秒）
    connect_timeout: int = Field(default=5, ge=1, le=30, title="连接超时")
    # 默认缓存 TTL（秒），0 表示不缓存
    default_ttl: int = Field(default=3600, ge=0, le=86400, title="默认缓存 TTL")
    # 是否启用键前缀（多实例共享同一 Redis 时使用）
    key_prefix: str = Field(default="mdcx:", title="键前缀")


class OpenSearchConfig(BaseModel):
    """OpenSearch 配置（Level 4 全文搜索）

    用于：
    - 影片标题/简介全文搜索（支持中日英分词）
    - 演员名称模糊匹配
    - 标签聚合统计
    - 替代 SQLite FTS5，支持分布式部署
    """
    model_config = ConfigDict(extra="forbid")

    hosts: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:9200"],
        title="OpenSearch 主机列表",
    )
    username: str | None = Field(default=None, title="用户名（可空）")
    password: str | None = Field(default=None, title="密码（可空）")
    # 索引前缀（多实例共享同一集群时使用）
    index_prefix: str = Field(default="mdcx_", title="索引前缀")
    # 是否使用 SSL
    use_ssl: bool = Field(default=False, title="使用 SSL")
    # 是否验证 SSL 证书
    verify_certs: bool = Field(default=True, title="验证 SSL 证书")


class DeploymentConfig(BaseModel):
    """四档渐进式部署配置（§7.12 参考 MediaStationGo）

    根据部署规模自动选择合适的存储/缓存/搜索后端：
    - Level 1 (single)：SQLite + 内存缓存（默认，零配置，单机使用）
    - Level 2 (multi_user)：+PostgreSQL（多用户并发，连接池更高效）
    - Level 3 (cluster)：+Redis（缓存层 + 分布式任务队列 + WebSocket pub/sub）
    - Level 4 (enterprise)：+OpenSearch（全文搜索，大规模媒体库秒级检索）

    通过 level 字段切换部署档位，各档位未启用的后端配置将被忽略。
    """
    model_config = ConfigDict(extra="forbid")

    # 部署档位
    level: Literal["single", "multi_user", "cluster", "enterprise"] = Field(
        default="single",
        title="部署档位",
        description="single=单机SQLite / multi_user=+PostgreSQL / cluster=+Redis / enterprise=+OpenSearch",
    )
    # PostgreSQL 配置（level >= multi_user 时生效，覆盖 DatabaseConfig.url）
    postgres: PostgresConfig = Field(default_factory=PostgresConfig, title="PostgreSQL 配置")
    # Redis 配置（level >= cluster 时生效）
    redis: RedisConfig = Field(default_factory=RedisConfig, title="Redis 配置")
    # OpenSearch 配置（level >= enterprise 时生效）
    opensearch: OpenSearchConfig = Field(default_factory=OpenSearchConfig, title="OpenSearch 配置")
    # 是否启用集群模式（多实例共享状态，需配合 Redis）
    cluster_mode: bool = Field(default=False, title="启用集群模式")
    # 实例 ID（集群模式下用于标识当前实例，留空则自动生成）
    instance_id: str | None = Field(default=None, title="实例 ID（集群模式）")
    # 任务队列模式：memory（单机）/ redis（分布式）
    task_queue_mode: Literal["memory", "redis"] = Field(
        default="memory", title="任务队列模式"
    )

    @property
    def effective_db_url(self) -> str | None:
        """根据部署档位返回实际使用的数据库 URL（PostgreSQL 优先）"""
        if self.level in ("multi_user", "cluster", "enterprise"):
            pg = self.postgres
            ssl = f"?sslmode={pg.ssl_mode}" if pg.ssl_mode != "disable" else ""
            return f"postgresql+asyncpg://{pg.username}:{pg.password}@{pg.host}:{pg.port}/{pg.database}{ssl}"
        return None  # 使用 DatabaseConfig 默认的 SQLite


class BackupConfig(BaseModel):
    """自动备份配置（Phase 6 生产级部署）

    定期备份数据库与配置文件，保留最近 N 份，支持手动触发与恢复。

    默认配置（2026-07-08 改）：启用 daily 模式，每天 03:00 自动备份，最多保留 7 份。
    用户在前端 Backup.vue 关闭/调整后，写入 config.yaml 持久化。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, title="启用自动备份")
    # 备份频率：daily（每天 24h 1 次）/ weekly（每周）/ hourly（每小时，一般不推荐）
    interval: Literal["hourly", "daily", "weekly"] = Field(
        default="daily", title="备份频率"
    )
    # 备份执行时间（daily/weekly 时为 HH:MM 格式，weekly 时为周几的 0-6）
    schedule_time: str = Field(default="03:00", title="执行时间（HH:MM）")
    schedule_day: int = Field(default=0, ge=0, le=6, title="执行日期（weekly 模式，0=周日）")
    # 最大保留备份数（超出后自动删除最旧的，7 = 保留最近 7 天）
    max_backups: int = Field(default=7, ge=1, le=100, title="最大保留备份数")
    # 备份内容
    backup_database: bool = Field(default=True, title="备份数据库")
    backup_config: bool = Field(default=True, title="备份配置文件")
    backup_logs: bool = Field(default=False, title="备份日志文件")
    # 压缩级别（0=不压缩，1-9 gzip 级别）
    compress: bool = Field(default=True, title="压缩备份")
    # 备份目录（留空则使用 data/backups）
    backup_dir: str = Field(default="", title="自定义备份目录")


class SubscriptionDownloaderConfig(BaseModel):
    """订阅自动下载配置（v4.1）

    配合 actor_subscriptions / series_subscriptions 使用，定期检查订阅源的新片并自动下载。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用订阅自动下载")
    check_interval_minutes: int = Field(default=30, ge=1, le=1440, title="检查间隔（分钟）")
    max_concurrent_downloads: int = Field(default=2, ge=1, le=10, title="最大并发下载数")
    auto_organize_after_download: bool = Field(default=True, title="下载完成后自动整理")
    preferred_quality_default: str = Field(default="1080p", title="默认偏好画质")


class PosterEnhancerConfig(BaseModel):
    """海报增强配置（v4.1 水印 / 4K 提升）

    为刮削到的海报添加水印（影片类型/番号等），可选 4K 超分提升。
    Amazon Japan 源用于获取更高清的封面图。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用海报增强")
    enable_watermark: bool = Field(default=True, title="启用水印")
    watermark_position: str = Field(default="bottom-right", title="水印位置")
    watermark_opacity: float = Field(default=0.7, ge=0.0, le=1.0, title="水印透明度")
    watermark_font: str = Field(default="Arial", title="水印字体")
    watermark_font_size: int = Field(default=24, ge=8, le=72, title="水印字号")
    watermark_color: str = Field(default="#FFFFFF", title="水印颜色")
    watermark_template: str = Field(default="{movie_type}", title="水印模板")
    enable_4k_upscale: bool = Field(default=False, title="启用 4K 超分提升")
    amazon_japan_source: bool = Field(default=True, title="使用 Amazon Japan 源")


class ProxyPlayConfig(BaseModel):
    """代理播放配置（v4.1 流媒体代理）

    通过本服务代理流式播放远程/云端媒体文件，避免直接暴露源站凭证。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, title="启用代理播放")
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400, title="缓存 TTL（秒）")
    stream_chunk_size: int = Field(default=1048576, ge=1024, le=10485760, title="流式分块大小（字节）")


class MovieGraphConfig(BaseModel):
    """影片关联图谱配置（v4.1）

    控制 movie_relations 表的构建参数：每片最大关系数、最小权重阈值。
    """
    model_config = ConfigDict(extra="forbid")

    max_relations_per_movie: int = Field(default=20, ge=1, le=100, title="每片最大关系数")
    min_weight_threshold: float = Field(default=0.1, ge=0.0, le=1.0, title="最小权重阈值")


class RecommendationConfig(BaseModel):
    """AI 推荐配置（v4.1）

    基于 user_recommendations 表的个性化推荐，权重四因子：
    演员 / 标签 / 系列 / 厂商，权重总和应为 1.0。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, title="启用 AI 推荐")
    refresh_interval_hours: int = Field(default=24, ge=1, le=168, title="刷新间隔（小时）")
    top_k: int = Field(default=20, ge=1, le=100, title="推荐数量")
    weight_actor: float = Field(default=0.4, ge=0.0, le=1.0, title="演员权重")
    weight_tag: float = Field(default=0.3, ge=0.0, le=1.0, title="标签权重")
    weight_series: float = Field(default=0.2, ge=0.0, le=1.0, title="系列权重")
    weight_studio: float = Field(default=0.1, ge=0.0, le=1.0, title="厂商权重")


class FanartConfig(BaseModel):
    """fanart.tv 集成配置（v4.1 C1）

    调用 fanart.tv API 获取影片的 Fanart 背景图、海报、清晰艺术图等资源。
    API 文档：https://fanart.tv/api/
    需要 personal API key（在 https://fanart.tv/personal/ 注册获取）。
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, title="启用 fanart.tv 集成")
    api_key: str = Field(default="", title="fanart.tv Personal API Key")
    # API 基础地址（一般无需修改）
    base_url: str = Field(default="https://webservice.fanart.tv/v3", title="API 基础地址")
    # 请求超时（秒）
    timeout: int = Field(default=15, ge=3, le=60, title="请求超时")
    # 下载图片保存到的子目录（相对于影片文件所在目录）
    image_subdir: str = Field(default="extrafanart", title="图片保存子目录名")
    # 是否在刮削时自动下载 fanart 背景图
    auto_download: bool = Field(default=False, title="刮削时自动下载背景图")


class GfriendsConfig(BaseModel):
    """Gfriends 头像库配置（2026-07-08 修复 2）

    两种模式：
    1. 在线模式（默认）：从 GitHub 拉取 Filetree.json + 头像文件
    2. 本地模式：使用已下载到本地的 Gfriends 资料库（O:/MDCX/GitHub-ZIP/...）
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, title="启用 Gfriends 头像库")
    # 模式选择：online=在线下载, local=本地资料库
    mode: Literal["online", "local"] = Field(default="online", title="模式")
    # 本地资料库根目录（包含 Content/ 子目录）
    # 例如 O:/MDCX/GitHub-ZIP/P1-High/gfriends-master/gfriends-master
    local_library_path: str = Field(default="", title="本地资料库根目录")
    # 是否优先使用本地（在线回退）
    prefer_local: bool = Field(default=True, title="优先使用本地资料库")
    # 自动重命名本地资料库时使用的归一化方式
    normalize_names: bool = Field(default=True, title="启用演员名归一化匹配")
    # 并发下载数（仅在线模式）
    concurrent_downloads: int = Field(default=5, ge=1, le=20, title="并发下载数")
    # 单个头像下载超时（秒）
    download_timeout: int = Field(default=30, ge=5, le=300, title="下载超时（秒）")


class Config(BaseModel):
    """主配置模型"""
    model_config = ConfigDict(extra="forbid")

    # 基础配置
    app_name: str = Field(default="龙魂视频管理系统", title="应用名称")

    # 嵌套配置
    modules: ModulesConfig = Field(default_factory=ModulesConfig, title="模块管理配置")
    server: ServerConfig = Field(default_factory=ServerConfig, title="服务器配置")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, title="数据库配置")
    scraper: ScraperConfig = Field(default_factory=ScraperConfig, title="刮削配置")
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig, title="爬虫配置")
    cookiecloud: CookieCloudConfig = Field(default_factory=CookieCloudConfig, title="CookieCloud配置")
    watcher: WatcherConfig = Field(default_factory=WatcherConfig, title="目录监控配置")
    proxy: ProxyConfig = Field(default_factory=ProxyConfig, title="代理配置")
    emby: EmbyConfig = Field(default_factory=EmbyConfig, title="Emby配置")
    jellyfin: JellyfinConfig = Field(default_factory=JellyfinConfig, title="Jellyfin配置")
    translate: TranslateConfig = Field(default_factory=TranslateConfig, title="翻译配置")
    webhook: WebhookConfig = Field(default_factory=WebhookConfig, title="Webhook配置")
    log: LogConfig = Field(default_factory=LogConfig, title="日志配置")
    auth: AuthConfig = Field(default_factory=AuthConfig, title="认证配置")
    webdav_client: WebDAVClientConfig = Field(default_factory=WebDAVClientConfig, title="WebDAV客户端")
    webdav_server: WebDAVServerConfig = Field(default_factory=WebDAVServerConfig, title="WebDAV服务端")
    face_crop: FaceCropConfig = Field(default_factory=FaceCropConfig, title="人脸裁剪")
    network_diag: NetworkDiagConfig = Field(default_factory=NetworkDiagConfig, title="网络诊断")
    naming: NamingConfig = Field(default_factory=NamingConfig, title="命名模板")
    mnamer: MnamerConfig = Field(default_factory=MnamerConfig, title="mnamer智能重命名")
    emby_compat: EmbyConfig2 = Field(default_factory=EmbyConfig2, title="Emby协议兼容")
    strm: StrmConfig = Field(default_factory=StrmConfig, title="STRM文件生成")
    nsfw: NsfwConfig = Field(default_factory=NsfwConfig, title="NSFW模式")
    mosaic: MosaicConfig = Field(default_factory=MosaicConfig, title="马赛克识别")
    site_priority: SitePriorityConfig = Field(default_factory=SitePriorityConfig, title="站点优先级配置")
    cloud_drive2: CloudDrive2Config = Field(default_factory=CloudDrive2Config, title="CloudDrive2配置")
    downloader: DownloaderConfig = Field(default_factory=DownloaderConfig, title="下载器统一配置")
    pan_115: Pan115Config = Field(default_factory=Pan115Config, title="115网盘离线下载配置")
    metatube: MetatubeConfig = Field(default_factory=MetatubeConfig, title="Metatube插件配置")
    tvbox: TvboxConfig = Field(default_factory=TvboxConfig, title="TVBox/MacCMS开放接口配置")
    themes: ThemesConfig = Field(default_factory=ThemesConfig, title="皮肤主题配置")
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig, title="部署档位配置（§7.12）")
    backup: BackupConfig = Field(default_factory=BackupConfig, title="自动备份配置")
    subscription_downloader: SubscriptionDownloaderConfig = Field(default_factory=SubscriptionDownloaderConfig, title="订阅自动下载配置")
    poster_enhancer: PosterEnhancerConfig = Field(default_factory=PosterEnhancerConfig, title="海报增强配置")
    proxy_play: ProxyPlayConfig = Field(default_factory=ProxyPlayConfig, title="代理播放配置")
    movie_graph: MovieGraphConfig = Field(default_factory=MovieGraphConfig, title="影片关联图谱配置")
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig, title="AI推荐配置")
    fanart: FanartConfig = Field(default_factory=FanartConfig, title="fanart.tv集成配置")
    gfriends: GfriendsConfig = Field(default_factory=GfriendsConfig, title="Gfriends 头像库配置")

    @field_validator("scraper", mode="before")
    @classmethod
    def validate_media_dirs(cls, v: dict) -> dict:
        """验证媒体目录"""
        if isinstance(v, dict) and "media_dirs" in v:
            # 确保目录路径存在
            dirs = v["media_dirs"]
            if isinstance(dirs, str):
                v["media_dirs"] = [dirs]
        return v


class ComputedConfig:
    """计算配置 - 从主配置派生的值"""

    def __init__(self, config: Config):
        self.config = config

    @property
    def data_dir(self) -> Path:
        """数据目录"""
        return Path("data")

    @property
    def config_dir(self) -> Path:
        """配置目录"""
        return self.data_dir / "config"

    @property
    def database_dir(self) -> Path:
        """数据库目录"""
        return self.data_dir / "database"

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        """缓存目录"""
        return self.data_dir / "cache"

    @property
    def backups_dir(self) -> Path:
        """备份目录"""
        return self.data_dir / "backups"

    @property
    def database_path(self) -> Path:
        """数据库文件路径"""
        return self.database_dir / "scraper.db"
