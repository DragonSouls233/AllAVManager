"""命名引擎（VaultX 风格高级封装）

参考 VaultX 的命名引擎设计，在现有 Jinja2 沙箱命名模板系统之上提供：
- 三级模板系统（文件夹/文件名/媒体库标题）
- 20+ 模板变量解析器
- 三种文件整理模式（复制/移动/软链接）
- 批量整理与预览功能

底层依赖 `app.services.naming` 的 Jinja2 沙箱引擎。
"""

import enum
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config.manager import get_config
from app.services.naming import (
    render_filename as _render_filename,
    render_dirpath as _render_dirpath,
    build_template_context,
    get_available_variables,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OrganizeMode(str, enum.Enum):
    """文件整理模式"""
    COPY = "copy"
    MOVE = "move"
    SYMLINK = "symlink"
    HARDLINK = "hardlink"


class MergeStrategy(str, enum.Enum):
    """同名文件冲突策略"""
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"


@dataclass
class OrganizeResult:
    """单个文件的整理结果"""
    source: str
    destination: str
    success: bool = False
    skipped: bool = False
    error: Optional[str] = None
    mode: str = ""


@dataclass
class BatchOrganizeResult:
    """批量整理结果"""
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[OrganizeResult] = field(default_factory=list)


class NamingEngine:
    """高级命名引擎

    在 app.services.naming 的 Jinja2 模板系统之上提供：
    - 三级模板系统（文件夹模板/文件名模板/媒体库标题模板）
    - 20+ 变量解析器注册
    - 预览功能
    """

    def __init__(self):
        self._custom_variables: dict[str, str] = {}
        self._load_config()

    def _load_config(self) -> None:
        """从配置加载模板"""
        cfg = get_config().naming if hasattr(get_config(), "naming") else None
        if cfg:
            self.dir_template = getattr(cfg, "dir_template", "{studio}/{code}")
            self.file_template = getattr(cfg, "file_template", "{code} {title}")
            self.library_title_template = getattr(cfg, "library_title_template", "{code} {title}")
        else:
            self.dir_template = "{studio}/{code}"
            self.file_template = "{code} {title}"
            self.library_title_template = "{code} {title}"

    def render_filename(
        self,
        movie_dict: dict,
        actors: Optional[list[str]] = None,
        extension: str = "",
        template: Optional[str] = None,
    ) -> str:
        """渲染文件名

        Args:
            movie_dict: 影片数据字典
            actors: 演员名列表
            extension: 文件扩展名（不含点）
            template: 自定义模板，None 使用配置模板

        Returns:
            渲染后的文件名
        """
        tpl = template or self.file_template
        return _render_filename(tpl, movie_dict, actors, extension)

    def render_dirpath(
        self,
        movie_dict: dict,
        actors: Optional[list[str]] = None,
        template: Optional[str] = None,
    ) -> str:
        """渲染目录路径

        Args:
            movie_dict: 影片数据字典
            actors: 演员名列表
            template: 自定义模板，None 使用配置模板

        Returns:
            相对路径（如 "studio/2024/ABC-123"）
        """
        tpl = template or self.dir_template
        return _render_dirpath(tpl, movie_dict, actors)

    def render_library_title(
        self,
        movie_dict: dict,
        actors: Optional[list[str]] = None,
    ) -> str:
        """渲染媒体库标题"""
        return _render_filename(
            self.library_title_template,
            movie_dict,
            actors,
            extension="",
        )

    def preview(
        self,
        movie_dict: Optional[dict] = None,
        template_type: str = "file",
    ) -> str:
        """预览渲染效果"""
        if movie_dict is None:
            movie_dict = {
                "code": "ABC-123",
                "title": "示例标题",
                "actor": "示例演员",
                "actors": ["示例演员"],
                "studio": "示例工作室",
                "release_date": "2024-05-01",
            }

        template_map = {
            "file": self.file_template,
            "dir": self.dir_template,
            "library": self.library_title_template,
        }
        tpl = template_map.get(template_type, self.file_template)
        return _render_filename(tpl, movie_dict, extension="")

    def get_variables(self) -> list[dict]:
        """获取所有可用变量"""
        return get_available_variables()

    def register_custom_variable(self, name: str, value: str) -> None:
        """注册自定义模板变量"""
        self._custom_variables[name] = value

    def build_context(self, movie_dict: dict, actors: Optional[list[str]] = None) -> dict:
        """构建模板上下文（含自定义变量）"""
        ctx = build_template_context(movie_dict, actors)
        ctx.update(self._custom_variables)
        return ctx


class FileOrganizer:
    """文件整理器

    支持三种模式：
    - COPY: 复制文件到目标位置（保留源文件）
    - MOVE: 移动文件到目标位置（源文件将被删除）
    - SYMLINK: 创建软链接（保全做种，适用于 BT 下载）
    """

    def __init__(
        self,
        base_dir: str = "",
        mode: OrganizeMode = OrganizeMode.COPY,
        merge_strategy: MergeStrategy = MergeStrategy.SKIP,
        naming_engine: Optional[NamingEngine] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else Path()
        self.mode = mode
        self.merge_strategy = merge_strategy
        self.naming_engine = naming_engine or NamingEngine()

    def organize(
        self,
        source_path: str,
        movie_dict: dict,
        actors: Optional[list[str]] = None,
    ) -> OrganizeResult:
        """整理单个文件

        Args:
            source_path: 源文件路径
            movie_dict: 影片数据
            actors: 演员名列表

        Returns:
            整理结果
        """
        src = Path(source_path)
        if not src.exists():
            return OrganizeResult(
                source=source_path,
                destination="",
                success=False,
                error="源文件不存在",
                mode=self.mode.value,
            )

        ext = src.suffix.lstrip(".")
        dir_rel = self.naming_engine.render_dirpath(movie_dict, actors)
        filename = self.naming_engine.render_filename(movie_dict, actors, extension=ext)

        dest_dir = self.base_dir / dir_rel if self.base_dir else Path(dir_rel)
        dest_path = dest_dir / filename

        # 处理冲突
        if dest_path.exists():
            if self.merge_strategy == MergeStrategy.SKIP:
                return OrganizeResult(
                    source=source_path,
                    destination=str(dest_path),
                    skipped=True,
                    mode=self.mode.value,
                )
            elif self.merge_strategy == MergeStrategy.RENAME:
                dest_path = self._resolve_rename(dest_path)

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)

            if self.mode == OrganizeMode.COPY:
                shutil.copy2(str(src), str(dest_path))
            elif self.mode == OrganizeMode.MOVE:
                shutil.move(str(src), str(dest_path))
            elif self.mode == OrganizeMode.SYMLINK:
                abs_src = src.resolve()
                dest_path.symlink_to(abs_src)
            elif self.mode == OrganizeMode.HARDLINK:
                abs_src = src.resolve()
                dest_path.hardlink_to(abs_src)

            logger.info(
                f"文件整理 [{self.mode.value}]: {source_path} -> {dest_path}"
            )
            return OrganizeResult(
                source=source_path,
                destination=str(dest_path),
                success=True,
                mode=self.mode.value,
            )

        except (OSError, shutil.Error) as e:
            logger.error(f"文件整理失败: {source_path} -> {dest_path}: {e}")
            return OrganizeResult(
                source=source_path,
                destination=str(dest_path),
                success=False,
                error=str(e),
                mode=self.mode.value,
            )

    def organize_batch(
        self,
        items: list[dict],
    ) -> BatchOrganizeResult:
        """批量整理文件

        Args:
            items: 每项包含 source_path, movie_dict, 可选的 actors

        Returns:
            批量整理结果
        """
        batch_result = BatchOrganizeResult(total=len(items))

        for item in items:
            result = self.organize(
                source_path=item["source_path"],
                movie_dict=item["movie_dict"],
                actors=item.get("actors"),
            )
            batch_result.results.append(result)

            if result.success:
                batch_result.success += 1
            elif result.skipped:
                batch_result.skipped += 1
            else:
                batch_result.failed += 1

        return batch_result

    def _resolve_rename(self, path: Path) -> Path:
        """解决命名冲突：添加数字后缀"""
        stem = path.stem
        ext = path.suffix
        parent = path.parent

        counter = 1
        while True:
            new_path = parent / f"{stem}_{counter}{ext}"
            if not new_path.exists():
                return new_path
            counter += 1


# 便捷函数

def organize_file(
    source_path: str,
    movie_dict: dict,
    base_dir: str = "",
    mode: str = "copy",
    actors: Optional[list[str]] = None,
) -> OrganizeResult:
    """便捷函数：整理单个文件"""
    organizer = FileOrganizer(
        base_dir=base_dir,
        mode=OrganizeMode(mode),
    )
    return organizer.organize(source_path, movie_dict, actors)


__all__ = [
    "NamingEngine",
    "FileOrganizer",
    "OrganizeMode",
    "MergeStrategy",
    "OrganizeResult",
    "BatchOrganizeResult",
    "organize_file",
]
