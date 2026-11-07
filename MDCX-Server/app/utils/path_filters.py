"""系统 / 厂商元数据目录与文件的统一判据。

背景（2026-11-07，参考 peach `src/peach/discovery_rules.py`）：
媒体库放在群晖 / 飞牛 / QNAP / Windows 共享盘上时，这些系统会到处撒自己的元数据目录
和文件。旧实现有三套名单、四处遍历完全不过滤，导致：

1. `@Recently-Snapshot`（群晖快照）、`@tmp`、`@sharebin`、`#snapshot`、`~snapshot`、
   `__MACOSX` 这些**不以点开头**的目录会被当真实媒体目录扫进去——
   快照目录里是整份历史副本，扫进去就是成倍的重复记录；
2. `ad_residue`（推广残留）、`junk_files`（垃圾扫描）、`uncensored_routes`（补漏扫描）、
   `download_tracker`（下载登记）四处 `os.walk` / `os.scandir` 压根没剪枝，
   会钻进 `@eaDir`、`.@__thumb`（群晖为每个影片目录生成的缩略图，动辄上万个小 jpg）、
   `$RECYCLE.BIN`：既把扫描预算（`_MAX_FILES` / `SCAN_MAX_ENTRIES`）吃光，
   也容易把缩略图当"推广图/垃圾图"误报。

因此统一到本模块：**任何**遍历媒体目录的入口都走 :func:`skip_dir` 剪枝。
名单以 peach 的实现为基线（它按各厂商官方文档整理过边界），并按我们实际遇到的
群晖 / 飞牛 / Windows 目录补齐。
"""
from __future__ import annotations

import os
import re

# 目录名（casefold 后精确匹配）
SYSTEM_DIR_NAMES = frozenset({
    # 群晖 Synology
    "@eadir", "@tmp", "@sharebin", "@recycle", "#recycle", "#snapshot",
    "@snapshot", "@recently-snapshot", "@upload_cache", "@synologydrive",
    ".@__thumb", ".@__qini", ".@__qsync", ".@#local", ".synoppsdb",
    # 飞牛 fnOS
    ".wfm_upload", ".wfm_upload_cache",
    # QNAP
    ".@__thumb", ".streams", ".@upload_cache",
    # ZFS / 快照
    ".zfs", ".snapshot", ".snapshots", "~snapshot", ".recycle",
    # 回收站
    "$recycle.bin", "system volume information", "recycler", "$sysreset",
    "found.000", "network trash folder",
    # macOS / Windows
    ".trash", ".trashes", ".temporaryitems", ".fseventsd", ".spotlight-v100",
    "__macosx", ".appledouble", ".appledesktop", ".appledb",
    # 开发/构建产物（误放在媒体目录时不必扫）
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
})

# 文件名（casefold 后精确匹配或以指定前缀开头）
SYSTEM_FILE_NAMES = frozenset({
    "desktop.ini", "thumbs.db", ".ds_store", ".localized", "icon\r",
    ".volumeicon.icns", "ehthumbs.db",
})
_SYSTEM_FILE_PREFIXES = ("._", ".synoppsdb", ".wfm_upload")

# `.trash-1000` 这类按用户 ID 后缀的回收站
_TRASH_UID_RE = re.compile(r"^\.trash-\d+$")


def is_system_dir(name: str) -> bool:
    """目录名是否属于系统 / 厂商元数据（应整体跳过，不下钻）。"""
    if not name:
        return False
    low = name.casefold()
    return (
        low in SYSTEM_DIR_NAMES
        or low.startswith(".wfm_upload")
        or _TRASH_UID_RE.match(low) is not None
    )


def is_system_file(name: str) -> bool:
    """文件名是否属于系统元数据（不是媒体、也不是有意义的附属文件）。"""
    if not name:
        return False
    low = name.casefold()
    return (
        low in SYSTEM_FILE_NAMES
        or low.startswith(_SYSTEM_FILE_PREFIXES)
        or low.endswith("@synoeastream")
    )


def skip_dir(name: str) -> bool:
    """遍历时的目录剪枝判据：系统目录，或以点开头的隐藏目录一律不进。

    以点开头直接跳过是历史行为（`base_scanner` 一直是这么做的），这里保留，
    并额外覆盖上表里那些**不以点开头**的系统目录（`@Recently-Snapshot` 等）。
    """
    if not name:
        return False
    return name.startswith(".") or is_system_dir(name)


def is_system_path(path: str | os.PathLike) -> bool:
    """路径中任一组件是系统目录，或末段是系统文件，即视为系统路径。"""
    parts = [p for p in re.split(r"[\\/]+", str(path)) if p]
    if not parts:
        return False
    return any(is_system_dir(p) for p in parts) or is_system_file(parts[-1])


def prune(dirnames: list) -> None:
    """就地剪枝 `os.walk` 的 dirs 列表（topdown=True 时必须原地改）。"""
    dirnames[:] = [d for d in dirnames if not skip_dir(d)]
