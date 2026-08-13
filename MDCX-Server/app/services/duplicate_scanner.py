"""番号重复文件扫描器

跨磁盘目录 walk 所有视频文件，按基础番号（去除 -C/-UC/-U 后缀）分组，
找出同一番号存在多份视频文件的重复组，帮助用户清理冗余副本节约硬盘空间。

与 `dedup.py`（内容指纹去重）不同：本模块基于**文件名中的番号**做去重，
专用于发现同一番号的多个变体文件（如 ABC-123.mp4 + ABC-123-C.mp4 + ABC-123-UC.mp4）。
"""

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.tasks.base_scanner import iter_media_entries
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 支持的视频扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m2ts", ".ts", ".mts", ".rmvb", ".iso", ".mpg", ".mpeg",
}

# 标准 JAV 番号正则（与 jav_scanner._extract_code 保持一致）
_CODE_PATTERNS = [
    re.compile(r"([A-Za-z]{2,6}-\d{2,5})(?:[-_.\s]?[CUc]?[UCuc]?)?$"),
    re.compile(r"\[([A-Za-z]{2,6}-\d{2,5})\]"),
]

# -C / -UC / -U 后缀检测（与 jav_scanner._detect_suffix 保持一致）
_SUFFIX_UC = re.compile(r"[-_.\s]?(UC|uc)$")
_SUFFIX_C = re.compile(r"[-_.\s]?C$")
_SUFFIX_U = re.compile(r"[-_.\s]?U$")


def _format_size(size_bytes: int) -> str:
    """人类可读的文件大小"""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


@dataclass
class DuplicateFile:
    """单个重复候选文件"""
    path: str             # 文件绝对路径
    size: int             # 字节数
    suffix: str           # "-C" / "-UC" / "-U" / ""(无后缀)
    is_chinese: bool      # 含中字标记
    is_uncensored: bool   # 含无码标记


@dataclass
class DuplicateGroup:
    """一组同番号重复文件"""
    base_code: str                       # 基础番号（去除后缀）
    files: list[DuplicateFile] = field(default_factory=list)
    # 推荐保留的文件（排序后第一个：优先中字 → 其次大文件）
    keep_index: int = 0
    category: str = ""                   # 分类/演员名（从路径提取）

    @property
    def wasted_bytes(self) -> int:
        """可释放的空间（除了 keep_index 外的所有文件大小之和）"""
        return sum(f.size for i, f in enumerate(self.files) if i != self.keep_index)

    def to_dict(self) -> dict:
        """转为 API 响应格式"""
        return {
            "base_code": self.base_code,
            "category": self.category,
            "file_count": len(self.files),
            "keep_index": self.keep_index,
            "wasted_bytes": self.wasted_bytes,
            "wasted_display": _format_size(self.wasted_bytes),
            "files": [
                {
                    "path": f.path,
                    "size": f.size,
                    "size_display": _format_size(f.size),
                    "suffix": f.suffix or "(无后缀)",
                    "is_chinese": f.is_chinese,
                    "is_uncensored": f.is_uncensored,
                }
                for f in self.files
            ],
        }


def extract_base_code(file_name: str, file_dir: Path) -> Optional[str]:
    """从文件名提取基础番号（去除 -C/-UC/-U 后缀）

    逻辑与 jav_scanner._extract_code 一致。
    """
    stem = Path(file_name).stem

    for pattern in _CODE_PATTERNS:
        match = pattern.search(stem)
        if match:
            code = match.group(1).upper().rstrip("-_. ")
            return code

    # 文件名无匹配时尝试父目录名
    parent_name = file_dir.name
    for pattern in _CODE_PATTERNS:
        match = pattern.search(parent_name)
        if match:
            code = match.group(1).upper().rstrip("-_. ")
            return code

    return None


def detect_suffix(file_name: str) -> tuple[bool, bool]:
    """检测文件名中的 -C/-UC/-U 后缀

    Returns:
        (is_chinese, is_uncensored)
    """
    stem = Path(file_name).stem

    # 优先匹配复合后缀 -UC
    if _SUFFIX_UC.search(stem):
        return True, True  # UC = 中字 + 无码
    if _SUFFIX_C.search(stem):
        return True, False  # C = 中字
    if _SUFFIX_U.search(stem):
        return False, True  # U = 无码

    return False, False


def _build_suffix_label(is_chinese: bool, is_uncensored: bool) -> str:
    """根据后缀标志生成可读标签"""
    if is_chinese and is_uncensored:
        return "-UC"
    if is_chinese:
        return "-C"
    if is_uncensored:
        return "-U"
    return ""


def _extract_category(file_paths: list[str]) -> str:
    """从一组重复文件的路径中提取分类名。

    取倒数第二级目录名作为分类，例如路径 "H:/AI/SSIS-001/file.mp4"
    → 分类 = "SSIS-001" 的上级目录 = "AI"

    若多个文件在不同番号子目录则尝试更高一级。
    """
    if not file_paths:
        return "其他"

    # 提取每个路径的倒数第二级目录（去掉文件名和番号目录）
    parents = set()
    for p in file_paths:
        parts = Path(p).parts
        # parts like: ("H:", "\\", "AI", "SSIS-001", "file.mp4")
        # 倒数第二级是番号目录，倒数第三级是分类
        if len(parts) >= 3:
            # 跳过盘符，取实际目录名
            category = parts[-2] if len(parts) >= 2 else ""
            parents.add(category)

    if len(parents) == 1:
        return parents.pop()

    # 如果每个文件在不同的番号子目录，尝试更高一级
    higher_parents = set()
    for p in file_paths:
        parts = Path(p).parts
        if len(parts) >= 4:
            higher_parents.add(parts[-3])

    if len(higher_parents) == 1 and higher_parents != parents:
        return higher_parents.pop()

    # 回退：取第一个文件中一个有意义的目录名
    first_parts = Path(file_paths[0]).parts
    for i in range(len(first_parts) - 2, 0, -1):
        part = first_parts[i]
        if part and part != "\\" and "." not in part and not part.endswith(":"):
            return part

    return "其他"


async def scan_duplicates(
    module_name: str,
    media_dirs: list[str],
) -> dict:
    """扫描指定模块的 media_dirs，找出同番号重复的视频文件。

    Args:
        module_name: 模块名（如 "jav", "chinese", "western"）
        media_dirs: 媒体目录列表（绝对路径）

    Returns:
        {
            "module": str,
            "total_files": int,          # 共扫描的视频文件数
            "total_groups": int,         # 存在重复的番号组数
            "duplicate_files": int,      # 多余的重复文件数（各组 len-1 之和）
            "space_wasted_bytes": int,    # 可释放空间（字节）
            "space_wasted_display": str,  # 可读格式
            "groups": [ DuplicateGroup.to_dict(), ... ],
        }
    """
    if not media_dirs:
        return {
            "module": module_name,
            "total_files": 0,
            "total_groups": 0,
            "duplicate_files": 0,
            "space_wasted_bytes": 0,
            "space_wasted_display": "0 B",
            "groups": [],
        }

    code_to_files: dict[str, list[DuplicateFile]] = {}
    total_files = 0
    matched_files = 0

    for media_dir in media_dirs:
        media_path = Path(media_dir)
        if not media_path.exists():
            logger.warning(f"[duplicate_scanner] 目录不存在，跳过: {media_dir}")
            continue

        logger.info(f"[duplicate_scanner] 正在扫描: {media_dir}")
        walk_entries = await asyncio.to_thread(iter_media_entries, media_path)

        for root, _dirs, files in walk_entries:
            dir_path = Path(root)
            for file_name in files:
                ext = Path(file_name).suffix.lower()
                if ext not in VIDEO_EXTENSIONS:
                    continue

                file_path = dir_path / file_name
                total_files += 1

                code = extract_base_code(file_name, dir_path)
                if not code:
                    continue
                matched_files += 1

                is_chinese, is_uncensored = detect_suffix(file_name)
                suffix = _build_suffix_label(is_chinese, is_uncensored)

                try:
                    size = file_path.stat().st_size
                except OSError:
                    logger.debug(f"[duplicate_scanner] 无法获取文件大小: {file_path}")
                    size = 0

                dup_file = DuplicateFile(
                    path=str(file_path),
                    size=size,
                    suffix=suffix,
                    is_chinese=is_chinese,
                    is_uncensored=is_uncensored,
                )

                code_to_files.setdefault(code, []).append(dup_file)

    logger.info(
        f"[duplicate_scanner] 扫描完成: {total_files} 个视频文件, "
        f"{matched_files} 个成功提取番号, "
        f"{len(code_to_files)} 个唯一番号"
    )

    # 构建重复组：只保留 >1 个文件的番号
    groups: list[DuplicateGroup] = []
    duplicate_files = 0
    total_wasted = 0

    for code in sorted(code_to_files):
        files = code_to_files[code]
        if len(files) <= 1:
            continue

        # 排序策略：优先保留中字版（-C / -UC），其次保留较大体积的文件
        # -C 后缀权重最高（有字幕优先保留），-UC 其次
        # 然后按文件大小降序（大文件通常是更高画质版本）
        def _sort_key(f: DuplicateFile) -> tuple:
            chinese_score = 0
            if f.is_chinese and f.is_uncensored:
                chinese_score = 2  # -UC: 中字+无码
            elif f.is_chinese:
                chinese_score = 3  # -C: 纯中字（最高权重，通常画质更好）
            elif f.is_uncensored:
                chinese_score = 1  # -U: 无码（无中字）
            return (-chinese_score, -f.size)

        files.sort(key=_sort_key)
        group = DuplicateGroup(
            base_code=code,
            files=files,
            keep_index=0,
            category=_extract_category([f.path for f in files]),
        )
        groups.append(group)
        duplicate_files += len(files) - 1
        total_wasted += group.wasted_bytes

    logger.info(
        f"[duplicate_scanner] 发现 {len(groups)} 组重复, "
        f"共 {duplicate_files} 个重复文件, "
        f"可释放 {_format_size(total_wasted)}"
    )

    return {
        "module": module_name,
        "total_files": total_files,
        "matched_files": matched_files,
        "total_groups": len(groups),
        "duplicate_files": duplicate_files,
        "space_wasted_bytes": total_wasted,
        "space_wasted_display": _format_size(total_wasted),
        "groups": [g.to_dict() for g in groups],
    }
