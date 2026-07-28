"""视频感知哈希去重 — 移植自 videohash + PSP。

用于 PornHub / 欧美等非番号视频的去重：
1. 通过 ffmpeg 提取视频帧
2. 生成拼贴图 → 计算 DWT 小波哈希 (imagehash.whash)
3. 汉明距离比较 → 判断是否重复

轻量版：不依赖 videohash 的完整框架，只保留核心哈希计算 + 比较逻辑。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


try:
    import imagehash
    from PIL import Image
    _HASH_OK = True
except ImportError:
    _HASH_OK = False
    logger.warning("imagehash/Pillow not installed; video hash disabled")


def _ffmpeg_path() -> Optional[str]:
    """找到 ffmpeg 路径。"""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    if shutil.which("ffmpeg.exe"):
        return "ffmpeg.exe"
    for candidate in (
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


async def extract_frames(
    video_path: str,
    output_dir: str,
    frame_interval: float = 1.0,
    max_frames: int = 60,
) -> list[str]:
    """用 ffmpeg 从视频中提取帧。

    Args:
        video_path: 视频文件路径
        output_dir: 帧图片输出目录
        frame_interval: 每秒提取帧数 (1=每秒1帧, 0.2=每5秒1帧)
        max_frames: 最多提取帧数

    Returns:
        frame_paths: 帧图片路径列表
    """
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        logger.warning("ffmpeg not found; cannot extract frames")
        return []

    os.makedirs(output_dir, exist_ok=True)
    output_pattern = os.path.join(output_dir, "frame_%06d.jpg")

    cmd = [
        ffmpeg,
        "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"fps={frame_interval}",
        "-frames:v", str(max_frames),
        "-q:v", "5",
        "-y",
        output_pattern,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
    except (asyncio.TimeoutError, FileNotFoundError, PermissionError) as e:
        logger.warning("ffmpeg frame extraction failed: %s", e)
        return []

    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]


async def _make_collage(frame_paths: list[str], output_path: str) -> Optional[str]:
    """将多帧图片拼接为拼贴图 (用于哈希计算)。"""
    if not frame_paths or not _HASH_OK:
        return None

    images = []
    for fp in frame_paths:
        try:
            im = Image.open(fp)
            im.thumbnail((256, 256))
            images.append(im)
        except Exception:
            continue

    if not images:
        return None

    # 拼接成网格
    cols = min(8, len(images))
    rows = (len(images) + cols - 1) // cols
    thumb_w, thumb_h = images[0].size
    collage = Image.new("RGB", (cols * thumb_w, rows * thumb_h))

    for idx, im in enumerate(images):
        x = (idx % cols) * thumb_w
        y = (idx // cols) * thumb_h
        collage.paste(im, (x, y))

    collage.save(output_path, "JPEG", quality=85)
    return output_path


async def compute_video_hash(video_path: str) -> Optional[str]:
    """计算视频的感知哈希值。

    流程：
    1. ffmpeg 提取关键帧
    2. 拼接为拼贴图
    3. imagehash.whash (DWT 小波哈希) → 64-bit 哈希字符串

    Returns:
        hash_str: 如 "0b101010..." 的哈希字符串，或 None
    """
    if not _HASH_OK:
        logger.warning("imagehash not available")
        return None

    tmp_dir = tempfile.mkdtemp(prefix="videohash_")
    try:
        frames = await extract_frames(video_path, tmp_dir, frame_interval=0.5, max_frames=40)
        if not frames:
            return None

        collage_path = os.path.join(tmp_dir, "collage.jpg")
        result = await _make_collage(frames, collage_path)
        if not result:
            return None

        img = Image.open(collage_path)
        h = imagehash.whash(img)
        return str(h)
    except Exception as e:
        logger.warning("compute_video_hash failed for %s: %s", video_path, e)
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def hamming_distance(hash1: str, hash2: str) -> int:
    """计算两个哈希字符串的汉明距离。"""
    try:
        h1 = imagehash.hex_to_hash(hash1) if isinstance(hash1, str) else hash1
        h2 = imagehash.hex_to_hash(hash2) if isinstance(hash2, str) else hash2
        return h1 - h2
    except Exception:
        return 999


def is_similar(hash1: str, hash2: str, threshold: int = 10) -> bool:
    """判断两个视频哈希是否相似（汉明距离 ≤ threshold）。"""
    return hamming_distance(hash1, hash2) <= threshold


class VideoHashDB:
    """视频哈希数据库 — 管理已处理视频的哈希值。

    用于 PornHub/欧美的增量去重：新下载的视频先比对哈希库，
    避免重复下载相同内容。
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), "..", "data", "video_hashes.txt"
        )
        self._hashes: dict[str, str] = {}  # video_path -> hash
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "|" in line:
                        path, h = line.split("|", 1)
                        self._hashes[path] = h

    def _save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            for path, h in self._hashes.items():
                f.write(f"{path}|{h}\n")

    def add(self, video_path: str, hash_value: str):
        self._hashes[video_path] = hash_value
        self._save()

    def find_similar(self, hash_value: str, threshold: int = 10) -> list[str]:
        """在库中查找相似的视频。"""
        results = []
        for path, h in self._hashes.items():
            if is_similar(hash_value, h, threshold):
                results.append(path)
        return results

    @property
    def count(self) -> int:
        return len(self._hashes)
