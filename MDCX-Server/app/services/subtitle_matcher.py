"""
字幕匹配服务

为视频文件匹配本地字幕文件，并支持在线字幕搜索（预留接口）。

匹配规则（按优先级）：
1. 同目录同名 .srt/.ass/.vtt（标准做法）
2. 同目录含番号的字幕文件（如 ABC-123.zh.srt）
3. 影片同目录下的子目录 subtitles/
4. 全局字幕库（data/subtitles/）按番号匹配

支持的字幕格式：.srt / .ass / .ssa / .vtt / .sub
"""

import logging
import re
from pathlib import Path
from typing import Optional

from app.config.manager import get_config_manager

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".smi", ".lrc"}


def _get_subtitle_library_dir() -> Path:
    """全局字幕库目录"""
    manager = get_config_manager()
    data_dir = getattr(manager.computed, 'data_dir', Path("data"))
    sub_dir = data_dir / "subtitles"
    sub_dir.mkdir(parents=True, exist_ok=True)
    return sub_dir


def _extract_code_from_filename(filename: str) -> Optional[str]:
    """从文件名提取番号（ABC-123 / ABC123 / abc-123456）"""
    # 常见番号格式
    patterns = [
        r"([A-Za-z]{2,5})[-_]?(\d{2,6})",  # ABC-123 / ABC123
        r"([a-z]{2,5})[-_]?(\d{3,6})",     # 小写
    ]
    for p in patterns:
        m = re.search(p, filename, re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}-{m.group(2)}"
    return None


def find_local_subtitles(file_path: str, code: Optional[str] = None) -> list[dict]:
    """
    查找本地字幕文件

    返回:
        [
            {
                "path": str,
                "filename": str,
                "language": str,        # zh / ja / en / unknown
                "ext": str,             # .srt / .ass ...
                "source": str,          # same_dir / sibling / library
                "size": int,
            }
        ]
    """
    video_path = Path(file_path)
    results = []

    if not video_path.exists():
        return results

    video_dir = video_path.parent
    video_stem = video_path.stem
    detected_code = code or _extract_code_from_filename(video_path.name)

    # 1. 同目录同名
    for ext in SUPPORTED_EXTS:
        candidate = video_dir / f"{video_stem}{ext}"
        if candidate.exists():
            results.append(_build_subtitle_info(candidate, "same_dir"))

    # 2. 同目录含番号
    if detected_code:
        for candidate in video_dir.glob(f"*{detected_code}*"):
            if candidate.suffix.lower() in SUPPORTED_EXTS and candidate not in [r["path"] for r in results if isinstance(r["path"], Path)]:
                results.append(_build_subtitle_info(candidate, "sibling"))

    # 3. 同目录的 subtitles 子目录
    sub_dir = video_dir / "subtitles"
    if sub_dir.exists() and sub_dir.is_dir():
        for candidate in sub_dir.glob("*"):
            if candidate.suffix.lower() in SUPPORTED_EXTS:
                results.append(_build_subtitle_info(candidate, "subdir"))

    # 4. 全局字幕库
    library_dir = _get_subtitle_library_dir()
    if library_dir.exists():
        # 按番号匹配
        if detected_code:
            for candidate in library_dir.glob(f"*{detected_code}*"):
                if candidate.suffix.lower() in SUPPORTED_EXTS:
                    results.append(_build_subtitle_info(candidate, "library"))
        # 按文件名匹配
        for ext in SUPPORTED_EXTS:
            candidate = library_dir / f"{video_stem}{ext}"
            if candidate.exists() and candidate not in [r["path"] for r in results if isinstance(r["path"], Path)]:
                results.append(_build_subtitle_info(candidate, "library"))

    return results


def _build_subtitle_info(path: Path, source: str) -> dict:
    """构建字幕信息 dict"""
    return {
        "path": str(path),
        "filename": path.name,
        "language": _detect_language(path.name),
        "ext": path.suffix.lower(),
        "source": source,
        "size": path.stat().st_size if path.exists() else 0,
    }


def _detect_language(filename: str) -> str:
    """从文件名推断语言"""
    name_lower = filename.lower()
    if any(k in name_lower for k in [".zh.", ".chs.", ".cht.", ".zh-cn.", ".zh-tw.", "_zh_", "chinese", "中文"]):
        return "zh"
    if any(k in name_lower for k in [".ja.", ".jpn.", "_ja_", "japanese"]):
        return "ja"
    if any(k in name_lower for k in [".en.", ".eng.", "_en_", "english"]):
        return "en"
    return "unknown"


def get_subtitle_file(movie_id: int, file_path: str, language: Optional[str] = None) -> Optional[dict]:
    """
    获取指定影片的字幕文件信息

    参数:
        movie_id: 影片 ID
        file_path: 视频文件路径
        language: 首选语言（zh/ja/en），留空返回首个匹配

    返回:
        字幕信息 dict 或 None
    """
    subs = find_local_subtitles(file_path)
    if not subs:
        return None

    if language:
        # 按语言优先级筛选
        for sub in subs:
            if sub["language"] == language:
                return sub
    return subs[0]


def list_subtitle_tracks(movie_id: int, file_path: str) -> list[dict]:
    """
    列出视频内嵌的字幕轨道（用 ffprobe）

    返回:
        [
            {
                "index": int,
                "language": str,
                "title": str,
                "codec": str,
                "default": bool,
                "external": False,  # 内嵌
            }
        ]
    """
    import subprocess
    from app.utils.bin_tools import get_tool_path

    ffprobe = get_tool_path("ffprobe")
    if not os.path.isfile(ffprobe):
        return []

    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet",
             "-print_format", "json",
             "-show_streams",
             "-select_streams", "s",
             file_path],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return []

        import json
        data = json.loads(result.stdout)
        tracks = []
        for stream in data.get("streams", []):
            tracks.append({
                "index": stream.get("index", 0),
                "language": stream.get("tags", {}).get("language", "unknown"),
                "title": stream.get("tags", {}).get("title", ""),
                "codec": stream.get("codec_name", "unknown"),
                "default": stream.get("disposition", {}).get("default", 0) == 1,
                "external": False,
            })
        return tracks
    except Exception as e:
        logger.warning(f"ffprobe 字幕轨道分析失败: {e}")
        return []


def list_all_subtitles(movie_id: int, file_path: str) -> dict:
    """
    列出所有可用字幕（内嵌 + 外挂）

    返回:
        {
            "embedded": [...],   # 内嵌字幕轨道
            "external": [...],   # 外挂字幕文件
        }
    """
    return {
        "embedded": list_subtitle_tracks(movie_id, file_path),
        "external": find_local_subtitles(file_path),
    }
