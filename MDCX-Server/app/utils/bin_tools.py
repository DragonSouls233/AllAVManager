"""
工具二进制路径管理

集中管理所有外部工具（yt-dlp、ffmpeg、ffprobe、ffplay）的二进制路径。
优先使用项目 `bin/` 目录下的版本，其次回退到系统 PATH。
"""

import os
import shutil
from pathlib import Path

# 项目根目录
APP_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = APP_ROOT / "bin"

# 工具名称到 bin/ 目录下文件名的映射
_TOOL_MAP = {
    "yt-dlp": "yt-dlp.exe",
    "ffmpeg": "ffmpeg.exe",
    "ffprobe": "ffprobe.exe",
    "ffplay": "ffplay.exe",
}


def get_tool_path(name: str) -> str:
    """获取工具二进制文件的完整路径。

    优先返回项目 `bin/` 目录下的版本，如果不存在则返回系统 PATH 中的版本。
    如果都不存在则返回原始名称（让调用方自行处理错误）。

    Args:
        name: 工具名称，如 'yt-dlp', 'ffmpeg', 'ffprobe', 'ffplay'

    Returns:
        工具二进制文件的完整路径或原始名称
    """
    # 检查 bin/ 目录
    if name in _TOOL_MAP:
        local_path = BIN_DIR / _TOOL_MAP[name]
        if local_path.exists():
            return str(local_path.resolve())

    # 回退到系统 PATH
    sys_path = shutil.which(name)
    if sys_path:
        return sys_path

    return name


def get_ffprobe_path() -> str:
    """获取 ffprobe 二进制路径的快捷方式"""
    return get_tool_path("ffprobe")


def get_ffmpeg_path() -> str:
    """获取 ffmpeg 二进制路径的快捷方式"""
    return get_tool_path("ffmpeg")


def ensure_tool(name: str) -> bool:
    """��查工具是否可用（在 bin/ 或 PATH 中存在）"""
    result = get_tool_path(name)
    return result != name and os.path.isfile(result)
