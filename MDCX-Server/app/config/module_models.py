"""
模块配置模型
包含各模块的独有配置项
"""

from pydantic import BaseModel, Field


class ModuleConfig(BaseModel):
    """模块基础配置"""
    enabled: bool = Field(default=False, title="是否启用")
    media_dirs: list[str] = Field(default_factory=list, title="媒体目录列表")


class ChineseModuleConfig(ModuleConfig):
    """国产模块配置（有文件夹演员独有功能）"""

    actor_from_folder: bool = Field(
        default=True,
        title="从文件夹名识别演员"
    )
    folder_depth: int = Field(
        default=1,
        ge=1, le=5,
        title="文件夹演员识别深度（1=直接父文件夹）"
    )
    folder_pattern: list[str] = Field(
        default_factory=list,
        title="自定义正则过滤（空=不过滤）"
    )
    actor_blacklist: list[str] = Field(
        default_factory=lambda: [
            "新建文件夹", "合集", "精选", "unknown",
            "未分类", "tmp", "temp", "downloads",
        ],
        title="过滤文件夹名黑名单"
    )
    auto_create_actor: bool = Field(
        default=True,
        title="自动创建演员记录"
    )
    studio_names_as_folder: bool = Field(
        default=False,
        title="工作室名是否作为演员文件夹名"
    )


class ScannerConfig(BaseModel):
    """扫描器配置"""
    concurrent_limit: int = Field(default=5, ge=1, le=20, title="并发数")
    retry_count: int = Field(default=3, ge=0, le=10, title="重试次数")


class ModulesConfig(BaseModel):
    """5 模块统一配置"""
    jav: ModuleConfig = ModuleConfig()
    uncensored: ModuleConfig = ModuleConfig()
    fc2: ModuleConfig = ModuleConfig()
    chinese: ChineseModuleConfig = ChineseModuleConfig()
    pornhub: ModuleConfig = ModuleConfig()
    scanner: ScannerConfig = ScannerConfig()
