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

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from app.config.manager import get_config_manager
from app.utils.bin_tools import get_ffprobe_path

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
    seen: set[str] = set()

    def _add(candidate: Path, source: str) -> None:
        """去重后追加（同一文件可能被多条规则命中）"""
        key = str(candidate.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        results.append(_build_subtitle_info(candidate, source))

    if not str(file_path).strip() or not video_path.exists():
        return results

    video_dir = video_path.parent
    video_stem = video_path.stem
    detected_code = code or _extract_code_from_filename(video_path.name)

    # 1. 同目录同名
    for ext in SUPPORTED_EXTS:
        candidate = video_dir / f"{video_stem}{ext}"
        if candidate.is_file():
            _add(candidate, "same_dir")

    # 2. 同目录含番号
    if detected_code:
        for candidate in video_dir.glob(f"*{detected_code}*"):
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTS:
                _add(candidate, "sibling")

    # 3. 同目录的 subtitles 子目录
    sub_dir = video_dir / "subtitles"
    if sub_dir.is_dir():
        for candidate in sub_dir.iterdir():
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTS:
                _add(candidate, "subdir")

    # 4. 全局字幕库
    library_dir = _get_subtitle_library_dir()
    if library_dir.is_dir():
        # 按番号匹配
        if detected_code:
            for candidate in library_dir.glob(f"*{detected_code}*"):
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTS:
                    _add(candidate, "library")
        # 按文件名匹配
        for ext in SUPPORTED_EXTS:
            candidate = library_dir / f"{video_stem}{ext}"
            if candidate.is_file():
                _add(candidate, "library")

    return results


def _build_subtitle_info(path: Path, source: str) -> dict:
    """构建字幕信息 dict"""
    info = {
        "path": str(path),
        "filename": path.name,
        "language": _detect_language(path.name),
        "ext": path.suffix.lower(),
        "source": source,
        "size": path.stat().st_size if path.exists() else 0,
    }
    # 附带嗅探到的源编码，前端加载时可据此设置 Artplayer 的 encoding，
    # 避免非 UTF-8 字幕（GBK/Big5）中文字幕整片乱码。
    try:
        raw = path.read_bytes()
        info["encoding"] = detect_subtitle_encoding(raw)
    except OSError:
        info["encoding"] = "utf-8"
    return info


# ===== 字幕编码嗅探 =====

def detect_subtitle_encoding(raw: bytes) -> str:
    """
    嗅探字幕文件编码。

    真实样本里 UTF-8 / UTF-8-BOM / GBK / Big5 混杂，浏览器默认按 UTF-8 解码，
    非 UTF-8 的中文字幕会整片乱码，所以这里必须先定编码再返回。

    判定顺序（严格按可信度，先命中先返回）：
    1. UTF-8 BOM（EF BB BF）→ utf-8-sig
    2. UTF-16 BOM → utf-16
    3. 严格 UTF-8 解码成功 → utf-8
    4. GB18030 / Big5 / cp1252 依次尝试，取第一个严格解码成功的
    5. 全失败 → latin-1 兜底，保证不抛异常
    """
    if not raw:
        return "utf-8"

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"

    for enc in ("utf-8", "gb18030", "big5", "cp1252"):
        try:
            raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        return enc

    return "latin-1"


def read_subtitle_text(path) -> tuple[str, str]:
    """
    读取字幕文本内容。

    返回:
        (文本, 编码名)。文本已统一为 str，调用方负责按需转码输出。
    """
    raw = Path(path).read_bytes()
    enc = detect_subtitle_encoding(raw)
    text = raw.decode(enc, errors="replace")
    # 统一剥掉 BOM，避免第一行时间轴前混入 U+FEFF
    return text.lstrip("\ufeff"), enc


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
    ffprobe = get_ffprobe_path()
    if not ffprobe or not os.path.isfile(ffprobe):
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
