"""
配置管理器 - 加载、保存、验证配置

线程安全设计(借鉴 OpenAver CD-66b-1):
- 模块级 threading.Lock 保护 config.yaml 的 read-modify-write
- public locked / private unlocked 严格分层
- mutate_config() 在单一 critical section 内完成 RMW,消除 lost-update 竞态
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import ValidationError

from app.config.models import ComputedConfig, Config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 配置文件路径
# 优先使用环境变量（MDCX_DATA_DIR 优先于 SCRAPER_DATA_DIR，二者皆可绝对或相对项目根），
# 否则回退到项目根下的 data/ —— 与 tools/bind_media_gui.py 的解析规则完全一致，
# 且不再依赖「启动时的当前工作目录」，避免从不同目录启动服务端时读错 config.yaml。
#
# PROJECT_ROOT 计算（修复历史 bug：原用 .parent.parent.parent 源码模式下正确，
# 但 PyInstaller 打包后 __file__ 变成 _MEIPASS\app\config\manager.py，
# .parent.parent.parent 会算成 _MEIPASS/ 临时目录，导致 data/ 写到临时目录丢失）。
#
# 正确逻辑：优先 sys.frozen（PyInstaller 标志），否则用 __file__ 的 3 层 .parent。
# 同时检测 app/ 在哪个位置（_MEIPASS 或 cwd），找到真正的 MDCX-Server 根。
import sys

if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
    _internal = _exe_dir / "_internal"
    if (_internal / "app" / "__init__.py").exists():
        _project_root = _internal
    elif (_exe_dir / "app" / "__init__.py").exists():
        _project_root = _exe_dir
    else:
        _project_root = Path(__file__).resolve().parent.parent.parent
else:
    _project_root = Path(__file__).resolve().parent.parent.parent

PROJECT_ROOT = _project_root


def _resolve_data_dir() -> Path:
    """解析数据目录路径。

    优先级：
      1. 环境变量 MDCX_DATA_DIR / SCRAPER_DATA_DIR（绝对或相对项目根）
      2. 项目根下的 data/ 目录
      3. 如果项目根下的 data/ 不存在，遍历所有有效盘符查找 \\MDCX-Server\\data
         （兼容开发机和服务器盘符不一致的场景）

    返回确认存在的绝对路径，若找不到则抛出 FileNotFoundError。
    """
    # 1) 环境变量优先
    env = os.getenv("MDCX_DATA_DIR") or os.getenv("SCRAPER_DATA_DIR")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if p.exists():
            return p.resolve()
        logger.warning("环境变量指定的数据目录不存在: %s，回退到自动检测", p)

    # 2) 项目根下的 data/
    default_data = (PROJECT_ROOT / "data").resolve()
    if default_data.exists():
        return default_data

    # 3) 遍历盘符查找
    import string

    logger.info(r"项目根下 %s/data 不存在，开始遍历盘符查找 \MDCX-Server\data ...", PROJECT_ROOT)
    scanned = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        candidate = Path(drive) / "MDCX-Server" / "data"
        scanned.append(drive)
        if candidate.exists():
            logger.info("盘符遍历命中: %s", candidate)
            # 同步更新全局 PROJECT_ROOT 至对应盘符
            # 注意：在此处通过 globals() 修改模块级 PROJECT_ROOT
            _new_root = Path(drive) / "MDCX-Server"
            globals()["PROJECT_ROOT"] = _new_root.resolve()
            return candidate.resolve()

    # 4) 全部未命中 → 抛出清晰异常
    scanned_str = ", ".join(scanned)
    err_msg = (
        "未在任何盘符下找到数据目录 \\MDCX-Server\\data！\n"
        f"已扫描盘符: {scanned_str}\n"
        f"项目根: {PROJECT_ROOT}\n"
        "请确认服务端已正确安装，或通过环境变量 MDCX_DATA_DIR 指定数据目录路径。"
    )
    logger.error(err_msg)
    raise FileNotFoundError(err_msg)


DATA_DIR = _resolve_data_dir()
CONFIG_FILE = DATA_DIR / "config" / "config.yaml"

# process-wide config.yaml 写入序列化锁(借鉴 OpenAver CD-66b-1)
# 必须用 threading.Lock(非 asyncio.Lock):FastAPI 的 def 路由跑在 threadpool,
# asyncio.Lock 保护不到;且必须用 plain Lock(非 RLock)——public locked /
# private unlocked 严格分层,锁内绝不二次 acquire(mutator 契约禁呼 public API)
_config_write_lock = threading.Lock()


class ConfigManager:
    """配置管理器 - 单例模式"""

    _instance: "ConfigManager | None" = None
    _config: Config | None = None
    _computed: ComputedConfig | None = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._config is None:
            self.load()

    @property
    def config(self) -> Config:
        """获取配置"""
        if self._config is None:
            self.load()
        return self._config  # type: ignore

    @property
    def computed(self) -> ComputedConfig:
        """获取计算配置"""
        if self._computed is None:
            self._computed = ComputedConfig(self.config)
        return self._computed

    def load(self) -> list[str]:
        """加载配置(process-wide 序列化,消除并发 RMW 竞态)

        Returns:
            验证错误列表
        """
        with _config_write_lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> list[str]:
        """加载配置(不加锁)——caller 须已持有 _config_write_lock

        借鉴 OpenAver _load_config_unlocked:迁移的写回必须走 _save_unlocked,
        否则在已持锁的 critical section 内再 acquire 同一 Lock → 自我死锁。
        """
        errors: list[str] = []

        # 1. 尝试从文件加载
        config_data: dict[str, Any] = {}

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    config_data = yaml.safe_load(f) or {}
            except Exception as e:
                errors.append(f"读取配置文件失败: {e}")
                logger.error(f"读取配置文件失败: {e}")

        # 2. 环境变量覆盖
        config_data = self._load_from_env(config_data)

        # 3. 验证并创建配置对象
        try:
            self._config = Config.model_validate(config_data)
            logger.info("配置加载成功")
        except ValidationError as e:
            errors.append(f"配置验证失败: {e}")
            logger.warning(f"配置验证失败，使用默认配置: {e}")
            self._config = Config()

        # 4. 创建计算配置
        self._computed = ComputedConfig(self._config)

        # 5. 确保目录存在
        self._ensure_directories()

        # 6. 相对路径解析到服务端根目录
        if self._config.scraper.output_dir and not Path(self._config.scraper.output_dir).is_absolute():
            self._config.scraper.output_dir = str(PROJECT_ROOT / self._config.scraper.output_dir)

        return errors

    def _load_from_env(self, config_data: dict[str, Any]) -> dict[str, Any]:
        """从环境变量加载配置"""
        env_mappings: dict[str, str] = {
            "SCRAPER_HOST": "server.host",
            "SCRAPER_PORT": "server.port",
            "SCRAPER_WORKERS": "server.workers",
            "SCRAPER_DEBUG": "server.debug",
            "SCRAPER_DATABASE_URL": "database.url",
            "SCRAPER_DATABASE_POOL_SIZE": "database.pool_size",
            "SCRAPER_DATABASE_ECHO": "database.echo",
            "SCRAPER_MEDIA_DIRS": "scraper.media_dirs",
            "SCRAPER_OUTPUT_DIR": "scraper.output_dir",
            "SCRAPER_CONCURRENT_LIMIT": "scraper.concurrent_limit",
            "SCRAPER_RETRY_COUNT": "scraper.retry_count",
            "SCRAPER_TIMEOUT": "scraper.timeout",
            "SCRAPER_LANG": "scraper.language",
            "SCRAPER_PROXY_ENABLED": "proxy.enabled",
            "SCRAPER_PROXY": "proxy.http",
            "SCRAPER_PROXY_SOCKS5": "proxy.socks5",
            "SCRAPER_EMBY_URL": "emby.url",
            "SCRAPER_EMBY_API_KEY": "emby.api_key",
            "SCRAPER_EMBY_ENABLED": "emby.enabled",
            "SCRAPER_JELLYFIN_URL": "jellyfin.url",
            "SCRAPER_JELLYFIN_API_KEY": "jellyfin.api_key",
            "SCRAPER_JELLYFIN_ENABLED": "jellyfin.enabled",
            "SCRAPER_TRANSLATE_ENGINE": "translate.engine",
            "SCRAPER_OPENAI_API_KEY": "translate.api_key",
            "SCRAPER_OPENAI_API_BASE": "translate.api_base",
            "SCRAPER_TRANSLATE_SOURCE_LANG": "translate.source_lang",
            "SCRAPER_TRANSLATE_TARGET_LANG": "translate.target_lang",
            "SCRAPER_LOG_LEVEL": "log.level",
            "SCRAPER_LOG_FORMAT": "log.format",
            "SCRAPER_LOG_FILE_ENABLED": "log.file_enabled",
            "SCRAPER_LOG_CONSOLE_ENABLED": "log.console_enabled",
            "WEBHOOK_TELEGRAM_TOKEN": "webhook.telegram_token",
            "WEBHOOK_TELEGRAM_CHAT_ID": "webhook.telegram_chat_id",
            "WEBHOOK_DISCORD_URL": "webhook.discord_url",
            "WEBHOOK_WECHAT_URL": "webhook.wechat_url",
            "WEBHOOK_ENABLED": "webhook.enabled",
        }

        for env_key, config_path in env_mappings.items():
            value = os.getenv(env_key)
            if value is not None:
                self._set_nested(config_data, config_path, value)

        return config_data

    def _set_nested(self, data: dict[str, Any], path: str, value: Any) -> None:
        """设置嵌套字典值"""
        keys = path.split(".")
        current = data

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # 类型转换
        final_key = keys[-1]
        if final_key in ("port", "workers", "concurrent_limit", "retry_count", "timeout", "pool_size"):
            value = int(value)
        elif final_key in ("debug", "enabled", "echo", "file_enabled", "console_enabled"):
            value = value.lower() in ("true", "1", "yes")

        current[final_key] = value

    def save(self) -> None:
        """保存配置到文件(原子写入 + process-wide 序列化)

        采用 atomic write 模式:
        1. 写入同目录临时文件(同目录保证 os.replace 是原子操作,跨文件系统则非原子)
        2. 调用 os.replace(target) 原子替换原文件
        3. 全程持 _config_write_lock,消除并发 RMW 竞态
        即使进程在写入中途崩溃,原 config.yaml 仍保持完整
        """
        with _config_write_lock:
            if self._config is None:
                return
            config_dict = self._config.model_dump(mode="json")
            self._save_unlocked(config_dict)

    def _save_unlocked(self, config_data: dict[str, Any]) -> None:
        """原子写 config.yaml(不加锁)——caller 须已持有 _config_write_lock

        借鉴 OpenAver _save_config_unlocked:mutate_config / 迁移 等已持锁场景
        必须调用此方法,否则在已持锁的 critical section 内再 acquire 同一 Lock
        → 自我死锁。
        """
        # 确保目录存在
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # 序列化 YAML
        yaml_text = yaml.dump(
            config_data,
            default_flow_style=False,
            allow_unicode=True,
            width=999999,           # fix23: 禁止 yaml 拆行（长字符串/cookie 不再被切成多行）
            sort_keys=False,        # 保留原顺序
        )

        # 原子写入:同目录临时文件 + os.replace
        try:
            # tempfile.mkstemp 在同目录创建,保证 os.replace 原子性
            fd, tmp_path = tempfile.mkstemp(
                prefix=".config_",
                suffix=".yaml.tmp",
                dir=str(CONFIG_FILE.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(yaml_text)
                    f.flush()
                    # 强制刷盘,确保异常断电也能落盘
                    os.fsync(f.fileno())
                # os.replace 是原子操作(Python 3.3+,POSIX rename(2) / Windows ReplaceFile)
                os.replace(tmp_path, CONFIG_FILE)
            except Exception:
                # 出错时清理临时文件
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.error(f"配置保存失败(原子写入异常): {e}")
            raise

        # 设置与原文件一致的权限(避免临时文件 0600 权限泄漏)
        try:
            mode = CONFIG_FILE.stat().st_mode & 0o777 if CONFIG_FILE.exists() else 0o644
            os.chmod(CONFIG_FILE, mode)
        except OSError:
            pass

        logger.info(f"配置已保存到 {CONFIG_FILE}(原子写入)")

    def mutate_config(self, mutator: Callable[[dict[str, Any]], None]) -> list[str]:
        """在单一 critical section 内 read-modify-write config.yaml(消除 RMW 竞态)

        借鉴 OpenAver mutate_config:load → mutator(cfg) → validate → save 全程持锁,
        两个并发 mutate_config 不再读到同一 v0 → 无 lost-update。

        mutator 契约:
        - 签名 mutator(cfg: dict) -> None,仅做纯内存 dict 操作
        - 不得调用任何 public locked API(load / save / mutate / reset)
          —— 会在已持锁时二次 acquire → 自我死锁

        Returns:
            验证错误列表(空列表表示成功)
        """
        with _config_write_lock:
            # 1. 从文件读取最新配置(避免基于内存 _config 的 stale 读)
            config_data: dict[str, Any] = {}
            if CONFIG_FILE.exists():
                try:
                    with open(CONFIG_FILE, encoding="utf-8") as f:
                        config_data = yaml.safe_load(f) or {}
                except Exception as e:
                    logger.error(f"mutate_config 读取配置失败: {e}")
                    config_data = {}
            # 环境变量覆盖(保持与 load() 一致)
            config_data = self._load_from_env(config_data)

            # 2. 调用 mutator 修改 dict
            mutator(config_data)

            # 3. 验证
            try:
                validated = Config.model_validate(config_data)
            except ValidationError as e:
                logger.warning(f"mutate_config 验证失败: {e}")
                return [f"配置验证失败: {e}"]

            # 4. 写回(已持锁,用 unlocked 版)
            self._save_unlocked(config_data)

            # 5. 更新内存中的 _config / _computed
            self._config = validated
            self._computed = ComputedConfig(validated)
            return []

    def reset(self) -> None:
        """重置为默认配置(在锁内完成,无 TOCTOU)"""
        with _config_write_lock:
            self._config = Config()
            self._computed = ComputedConfig(self._config)
            self._save_unlocked(self._config.model_dump(mode="json"))
            logger.info("配置已重置为默认值")

    def _ensure_directories(self) -> None:
        """确保必要的目录存在"""
        if self._computed is None:
            return

        dirs = [
            self._computed.data_dir,
            self._computed.config_dir,
            self._computed.database_dir,
            self._computed.logs_dir,
            self._computed.cache_dir,
            self._computed.backups_dir,
        ]

        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def update(self, **kwargs: Any) -> list[str]:
        """更新配置(线程安全 RMW,委托给 mutate_config)

        Args:
            **kwargs: 配置项(支持 dot-path 嵌套,如 "server.host")

        Returns:
            验证错误列表(空列表表示成功)
        """
        def _mutator(cfg: dict[str, Any]) -> None:
            for key, value in kwargs.items():
                if "." in key:
                    self._set_nested(cfg, key, value)
                else:
                    cfg[key] = value

        return self.mutate_config(_mutator)


# 全局配置管理器实例
_manager: ConfigManager | None = None


def get_config() -> Config:
    """获取配置实例"""
    global _manager
    if _manager is None:
        _manager = ConfigManager()
    return _manager.config


def get_config_manager() -> ConfigManager:
    """获取配置管理器实例"""
    global _manager
    if _manager is None:
        _manager = ConfigManager()
    return _manager
