"""
网页播放兼容层（avm v1.13.1 移植）。

背景
----
浏览器 ``<video>`` 只认 H.264 + AAC 这类通用封装。HEVC / 10bit / MKV+FLAC 等
在网页里直接挂会触发 ``<video>`` 的 error 事件、黑屏或只有声音没有画面。

avm 的做法是：**播放失败时才自动 ffmpeg 转封装**为 MP4
（视频流 ``-c:v copy`` 不重编码，仅音轨转 AAC），缓存到 ``data/remux``，
LRU 按体积上限清理；HEVC / 10bit 仍判定为「需系统播放器」，不转封装。

本模块只负责「判定 + 转封装 + 缓存」，不负责播放；播放端（Play.vue）在
检测到 ``<video>`` error 时来这里取一个可网页播放的 URL。

ffmpeg / ffprobe 路径统一走 ``app.utils.bin_tools``（bin/ 优先，回退 PATH）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 浏览器原生可直接解码的视频编码（保守集合；HEVC/H.265 与 mpeg2video 排除，
# 后者虽可塞进 MP4 但浏览器基本不放）
_NATIVE_VIDEO_CODECS = {"h264", "avc", "avc1", "mpeg4", "vp9", "av1"}
# 浏览器原生可直接解码的音频编码（avm 只把其它音轨转 AAC）
_NATIVE_AUDIO_CODECS = {"aac", "mp3", "mp2", "opus", "vorbis"}
# 明确需要系统播放器的视频编码
_SYSTEM_ONLY_VIDEO_CODECS = {"hevc", "h265", "h266", "av1_10", "vp8"}

# data/remux 默认体积上限：4 GiB
DEFAULT_REMUX_MAX_BYTES = 4 * 1024 * 1024 * 1024

_lock = threading.Lock()


def _ffmpeg_base(ffmpeg_path: Optional[object] = None) -> list[str]:
    """把『ffmpeg 路径』规范成命令前缀（支持传入 [python, fake.py] 用于测试）。"""
    if ffmpeg_path is None:
        from app.utils.bin_tools import get_ffmpeg_path

        return [get_ffmpeg_path()]
    if isinstance(ffmpeg_path, (list, tuple)):
        return [str(x) for x in ffmpeg_path]
    return [str(ffmpeg_path)]


def _ffprobe_base(ffprobe_path: Optional[object] = None) -> list[str]:
    if ffprobe_path is None:
        from app.utils.bin_tools import get_ffprobe_path

        return [get_ffprobe_path()]
    if isinstance(ffprobe_path, (list, tuple)):
        return [str(x) for x in ffprobe_path]
    return [str(ffprobe_path)]


def find_ffmpeg() -> Optional[str]:
    """返回可用的 ffmpeg 路径；不存在返回 None。"""
    from app.utils.bin_tools import get_ffmpeg_path

    p = get_ffmpeg_path()
    return p if p and os.path.isfile(p) else None


def find_ffprobe() -> Optional[str]:
    from app.utils.bin_tools import get_ffprobe_path

    p = get_ffprobe_path()
    return p if p and os.path.isfile(p) else None


def probe_streams(
    path: str,
    *,
    ffprobe_path: Optional[object] = None,
    timeout: float = 30.0,
) -> Optional[dict]:
    """用 ffprobe 取流信息。

    Returns:
        含 ``video`` / ``audio`` / ``format`` 的 dict；失败返回 None。
    """
    base = _ffprobe_base(ffprobe_path)
    if not base or not os.path.isfile(str(base[0])):
        return None
    cmd = base + [
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
        logger.warning("ffprobe 执行失败: %s", e)
        return None
    if proc.returncode != 0:
        return None
    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None

    video, audio = [], []
    for s in info.get("streams", []):
        codec_type = (s.get("codec_type") or "").lower()
        if codec_type == "video":
            video.append(s)
        elif codec_type == "audio":
            audio.append(s)
    return {"video": video, "audio": audio, "format": info.get("format", {})}


def _codec_name(stream: dict) -> str:
    return (stream.get("codec_name") or "").lower().split(".")[0]


def _bit_depth(stream: dict) -> int:
    for key in ("bits_per_raw_sample", "bit_depth"):
        v = stream.get(key)
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    # 从 pix_fmt 推断（yuv420p10le 等）
    pix = (stream.get("pix_fmt") or "").lower()
    if "10" in pix:
        return 10
    if "12" in pix:
        return 12
    return 8


def analyze_playability(streams: Optional[dict]) -> dict:
    """分析一次 probe 结果，给出浏览器播放结论。

    Returns:
        {
          "playable": bool,             # 浏览器能否直接播放
          "mode": "native"|"remux"|"system",
          "reason": None|"hevc"|"10bit"|"video_codec"|"no_video"|"probe_failed",
          "video_codec": str,
          "audio_codec": str|None,
          "bit_depth": int,
        }
    """
    if not streams or not streams.get("video"):
        return {
            "playable": False,
            "mode": "system",
            "reason": "no_video" if streams else "probe_failed",
            "video_codec": "",
            "audio_codec": None,
            "bit_depth": 0,
        }

    v = streams["video"][0]
    vcodec = _codec_name(v)
    depth = _bit_depth(v)

    # HEVC / H.265 / H.266 / 10bit 及以上 → 系统播放器
    if vcodec in _SYSTEM_ONLY_VIDEO_CODECS or depth >= 10:
        reason = "hevc" if vcodec in ("hevc", "h265", "h266") else "10bit"
        return {
            "playable": False,
            "mode": "system",
            "reason": reason,
            "video_codec": vcodec,
            "audio_codec": _codec_name(streams["audio"][0]) if streams.get("audio") else None,
            "bit_depth": depth,
        }

    # 视频编码浏览器不支持 → 需要 remux（转封装时视频流仍 copy，但容器变 MP4 后常被接受；
    # 对真正不支持的视频编码，copy 也放不进 MP4，这里仍给 remux 由 ffmpeg 决定，
    # 调用方重试一次失败则降级系统播放器）
    if vcodec not in _NATIVE_VIDEO_CODECS:
        return {
            "playable": False,
            "mode": "remux",
            "reason": "video_codec",
            "video_codec": vcodec,
            "audio_codec": _codec_name(streams["audio"][0]) if streams.get("audio") else None,
            "bit_depth": depth,
        }

    # 视频原生可播。若音轨非原生（如 FLAC/DTS），浏览器会静音但视频能放；
    # 为体验统一转封装（音轨转 AAC）。判定为 remux。
    audio_codec = None
    if streams.get("audio"):
        audio_codec = _codec_name(streams["audio"][0])
        if audio_codec not in _NATIVE_AUDIO_CODECS:
            return {
                "playable": True,  # 视频本身可播
                "mode": "remux",  # 但音轨需转 AAC 才有声
                "reason": "audio_codec",
                "video_codec": vcodec,
                "audio_codec": audio_codec,
                "bit_depth": depth,
            }

    return {
        "playable": True,
        "mode": "native",
        "reason": None,
        "video_codec": vcodec,
        "audio_codec": audio_codec,
        "bit_depth": depth,
    }


def remux_file(
    src: str,
    dst: str,
    *,
    ffmpeg_path: Optional[object] = None,
    timeout: float = 600.0,
) -> subprocess.CompletedProcess:
    """ffmpeg 转封装：视频流 copy，音轨转 AAC，输出带 faststart 的 MP4。"""
    base = _ffmpeg_base(ffmpeg_path)
    if not base or not os.path.isfile(str(base[0])):
        raise FileNotFoundError("ffmpeg 不可用")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    cmd = base + [
        "-y",
        "-i", src,
        "-c:v", "copy",
        "-c:a", "aac",
        "-movflags", "+faststart",
        dst,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _remux_cache_dir() -> Path:
    from app.config.manager import DATA_DIR

    d = Path(DATA_DIR) / "remux"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(src: str, size: int, mtime: float) -> str:
    h = hashlib.sha1(f"{src}|{size}|{mtime:.3f}".encode("utf-8")).hexdigest()[:24]
    return h


def _lru_cleanup(max_bytes: int = DEFAULT_REMUX_MAX_BYTES) -> int:
    """按 mtime 从旧到新删除，直到缓存总体积 < max_bytes。返回删除字节数。"""
    d = _remux_cache_dir()
    try:
        entries = [p for p in d.iterdir() if p.is_file() and p.suffix == ".mp4"]
    except OSError:
        return 0
    entries.sort(key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in entries)
    freed = 0
    for p in entries:
        if total <= max_bytes:
            break
        try:
            sz = p.stat().st_size
            p.unlink()
            total -= sz
            freed += sz
        except OSError:
            continue
    return freed


def request_remux(
    src_path: str,
    *,
    force: bool = False,
    ffmpeg_path: Optional[object] = None,
    ffprobe_path: Optional[object] = None,
    max_bytes: int = DEFAULT_REMUX_MAX_BYTES,
) -> dict:
    """给一个视频文件，返回浏览器可播放的版本。

    Args:
        src_path: 原始视频绝对路径。
        force: True 时即使原生可播也强制转封装（用于播放失败后的重试）。
        ffmpeg_path / ffprobe_path: 注入用（测试 / 自定义路径）。

    Returns:
        {
          "mode": "native"|"remux"|"system",
          "path": 浏览器应使用的文件路径,
          "playable": bool,
          "reason": ...,
          "video_codec"/"audio_codec"/"bit_depth": ...
        }
    """
    src = Path(src_path)
    if not src.is_file():
        raise FileNotFoundError(f"源文件不存在: {src_path}")

    streams = probe_streams(str(src), ffprobe_path=ffprobe_path)
    analysis = analyze_playability(streams)

    # 系统播放器场景：HEVC/10bit 即使强制也无法在网页播放，始终不转封装
    if analysis["mode"] == "system":
        return {
            "mode": "system",
            "path": str(src),
            "playable": False,
            "reason": analysis["reason"],
            "video_codec": analysis["video_codec"],
            "audio_codec": analysis["audio_codec"],
            "bit_depth": analysis["bit_depth"],
        }

    # 原生可播且未强制 → 直接给原文件
    if analysis["mode"] == "native" and not force:
        return {
            "mode": "native",
            "path": str(src),
            "playable": True,
            "reason": None,
            "video_codec": analysis["video_codec"],
            "audio_codec": analysis["audio_codec"],
            "bit_depth": analysis["bit_depth"],
        }

    # 需要转封装：缓存命中优先
    st = src.stat()
    key = _cache_key(str(src.resolve()), st.st_size, st.st_mtime)
    cache_dir = _remux_cache_dir()
    cached = cache_dir / f"{key}.mp4"
    with _lock:
        if not cached.is_file():
            remux_file(str(src), str(cached), ffmpeg_path=ffmpeg_path)
        if not cached.is_file():
            # 转封装失败（如编码确实放不进 MP4）→ 降级系统播放器
            return {
                "mode": "system",
                "path": str(src),
                "playable": False,
                "reason": "remux_failed",
                "video_codec": analysis["video_codec"],
                "audio_codec": analysis["audio_codec"],
                "bit_depth": analysis["bit_depth"],
            }
        _lru_cleanup(max_bytes)

    return {
        "mode": "remux",
        "path": str(cached),
        "playable": True,
        "reason": analysis["reason"],
        "video_codec": analysis["video_codec"],
        "audio_codec": analysis["audio_codec"],
        "bit_depth": analysis["bit_depth"],
    }


def clear_remux_cache() -> int:
    """清空整个 remux 缓存目录。返回删除文件数。"""
    d = _remux_cache_dir()
    n = 0
    try:
        for p in d.iterdir():
            if p.is_file():
                p.unlink()
                n += 1
    except OSError:
        pass
    return n


__all__ = [
    "find_ffmpeg",
    "find_ffprobe",
    "probe_streams",
    "analyze_playability",
    "remux_file",
    "request_remux",
    "clear_remux_cache",
    "DEFAULT_REMUX_MAX_BYTES",
]
