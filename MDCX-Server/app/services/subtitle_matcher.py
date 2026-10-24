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
    results = []
    seen: set[str] = set()

    def _add(candidate: Path, source: str) -> None:
        """去重后追加（同一文件可能被多条规则命中）"""
        key = str(candidate.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        results.append(_build_subtitle_info(candidate, source))

    # 🔴 2026-10-22：None/异常输入守卫必须**早于** Path()。
    #   Path(None) 直接抛 TypeError，而早先的空值判断写在 Path() 之后
    #   ⇒ 调用方传 None 时整个请求 500。
    #   （实测：find_local_subtitles(None) 崩在 Path(None)；空字符串/不存在路径
    #    则正常返回 []。）
    if file_path is None:
        return results
    try:
        video_path = Path(str(file_path).strip())
    except (TypeError, ValueError):
        return results
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

#: 常见中文字（高频字）——用于在多个候选编码都能"解码成功"时挑出正确的那个。
#: 场景：GB18030 是 Big5 的超集，cp949(韩文) 与 GB18030 的 CJK 区也大面积重叠，
#: 三者常常都能把同一段字节"成功"解码 ⇒ 单靠"能不能解码"无法区分，必须看解出来的
#: 是不是**像中文**。字幕文件以中文为主，用高频字命中数打分最直接。
_COMMON_CN_CHARS = frozenset(
    "的一是不了在人有我他这个们中来上大为和国地到以说时要就出会可也你对"
    "生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学"
    "如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想"
    "实日军者意无力它与长正把题问更手比又公很头见做才市老每各知何太世位"
    "文西口日水火山石田土木目儿女人大小中王父子马牛羊鱼鸟鸟虫风雨雪云电光影"
    "字幕听说说写写读读做做看看来来去去坐站立走跑跳飞开开关闭上下左右"
    "前后东西南北里外中间旁边高低长短深浅快慢早晚朝夕春夏秋冬"
)


def _cn_score(text: str) -> int:
    """解码文本里出现了多少常见中文字（越多越像中文）。"""
    if not text:
        return 0
    return sum(1 for c in text if c in _COMMON_CN_CHARS)


#: 编码名归一化（charset_normalizer 与 Python codecs 命名不一致）
_ENC_ALIASES = {
    "gb2312": "gb18030", "gbk": "gb18030", "gb18030": "gb18030",
    "big5": "big5", "big5hkscs": "big5", "cp950": "big5",
    "cp1252": "cp1252", "windows-1252": "cp1252",
    "ascii": "utf-8", "utf-8": "utf-8", "utf-8-sig": "utf-8-sig",
    "utf-16": "utf-16", "utf-16le": "utf-16", "utf-16be": "utf-16",
}


def detect_subtitle_encoding(raw: bytes) -> str:
    """
    嗅探字幕文件编码。

    真实样本里 UTF-8 / UTF-8-BOM / GBK / Big5 混杂，浏览器默认按 UTF-8 解码，
    非 UTF-8 的中文字幕会整片乱码，所以这里必须先定编码再返回。

    判定顺序（严格按可信度，先命中先返回）：
    1. UTF-8 BOM（EF BB BF）→ utf-8-sig
    2. UTF-16 BOM → utf-16
    3. 严格 UTF-8 解码成功 → utf-8
    4. 多候选打分：GB18030 / Big5 / cp949 / cp1252 等**都能**把中文字节
       "成功"解码（GB18030 是 Big5 超集；cp949 与 GB18030 的 CJK 区重叠），
       单看"能不能解码"必错。改为 charset_normalizer 给候选 + 常见中文字打分挑最优。
    5. 全失败 → latin-1 兜底，保证不抛异常

    🔴 2026-10-22 重构第 4 步，修两个实测 bug：
      a) Big5 繁体字幕被判成 GBK ⇒ 乱码（「繁體中文」→「羉砰いゅ」）。
         原因：旧实现顺序尝试 GB18030→Big5，而 GB18030 是 Big5 超集，
         Big5 永远排不上。
      b) 只换 charset_normalizer 后，短中文又被偏好判成 cp949（韩文）⇒ 同样乱码。
         故加「常见中文字打分」消歧：中文得分最高者胜出。
    """
    if not raw:
        return "utf-8"

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"

    # 严格 UTF-8（能解码就是 UTF-8，优先级最高）
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # ---- 收集候选编码（charset_normalizer 的建议优先，再补固定候选） ----
    candidates: list[str] = []
    try:
        from charset_normalizer import from_bytes
        for match in from_bytes(raw):
            enc = (match.encoding or "").lower().replace("_", "-")
            if enc and enc not in candidates:
                candidates.append(enc)
            if len(candidates) >= 5:
                break
    except Exception:
        pass
    for enc in ("gb18030", "big5", "cp949", "cp1252"):
        if enc not in candidates:
            candidates.append(enc)

    # ---- 逐个解码，用常见中文字打分挑最优 ----
    best_enc, best_score = None, -1
    for enc in candidates:
        norm = _ENC_ALIASES.get(enc, enc)
        try:
            text = raw.decode(norm)
        except (UnicodeDecodeError, LookupError):
            continue
        score = _cn_score(text)
        # 严格大于 ⇒ 平分时保留前面的候选（charset_normalizer 的建议优先）
        if score > best_score:
            best_enc, best_score = norm, score

    if best_enc:
        return best_enc

    # 兜底：顺序尝试（理论上走不到，charset_normalizer 异常时保底）
    for enc in ("gb18030", "big5", "cp949", "cp1252"):
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
