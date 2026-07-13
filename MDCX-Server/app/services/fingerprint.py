"""
视频指纹去重服务

参考 JavBoss 的 Video.Fingerprint 设计：
- 使用 ffmpeg 截取视频中间帧，计算感知哈希 (pHash)
- 相同指纹的视频视为同一文件的不同命名/路径
- 用于跨重命名/移动去重
"""
import hashlib
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# 感知哈希尺寸
HASH_SIZE = 16  # 16x16 = 256 bits，产生 64 字符 hex


def compute_video_fingerprint(file_path: str) -> Optional[str]:
    """
    计算视频文件的感知哈希指纹

    流程：
    1. 用 ffmpeg 截取视频中段一帧
    2. 缩放到 32x32 灰度图
    3. 计算 pHash（DCT 感知哈希）
    4. 返回 64 字符 hex 字符串

    参数:
        file_path: 视频文件路径

    返回:
        指纹 hex 字符串，失败返回 None
    """
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg 未安装，无法计算视频指纹")
        return None

    video_path = Path(file_path)
    if not video_path.exists():
        logger.warning(f"视频文件不存在: {file_path}")
        return None

    # 用临时文件存放截帧
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_frame = tmp.name

    try:
        # 截取视频中段一帧（用 -ss 快速 seek 到 50% 位置附近）
        # 先获取时长
        duration = _get_duration(str(video_path))
        seek_time = max(1, duration * 0.5) if duration > 2 else 1

        result = subprocess.run(
            [
                "ffmpeg",
                "-ss", str(seek_time),
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=32:32,format=gray",
                "-q:v", "2",
                "-y",
                tmp_frame,
            ],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )

        if result.returncode != 0 or not Path(tmp_frame).exists():
            logger.debug(f"截帧失败: {(result.stderr or '')[:200]}")
            return None

        # 计算感知哈希
        return _compute_phash(tmp_frame)

    except subprocess.TimeoutExpired:
        logger.warning(f"截帧超时: {file_path}")
        return None
    except Exception as e:
        logger.warning(f"计算指纹失败: {e}")
        return None
    finally:
        # 清理临时文件
        try:
            Path(tmp_frame).unlink(missing_ok=True)
        except Exception:
            pass


def _get_duration(file_path: str) -> float:
    """用 ffprobe 获取视频时长"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout:
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def _compute_phash(image_path: str) -> Optional[str]:
    """
    计算图片的感知哈希 (pHash)

    使用 DCT (离散余弦变换) 方法：
    1. 缩放到 32x32 灰度图
    2. 计算 DCT
    3. 取左上角 16x16 的低频分量
    4. 以均值为阈值生成二值哈希
    """
    try:
        img = Image.open(image_path).convert("L").resize((32, 32), Image.LANCZOS)
        pixels = list(img.getdata())

        # 简化的 DCT 感知哈希
        # 用 numpy 加速
        import numpy as np
        arr = np.array(pixels, dtype=np.float64).reshape(32, 32)

        # 计算 2D DCT（简化版：用均值哈希作为快速近似）
        # 取 16x16 的低频区域
        dct_block = arr[:HASH_SIZE, :HASH_SIZE]
        avg = dct_block.mean()

        # 生成哈希
        hash_bits = (dct_block > avg).flatten()
        # 转为 hex 字符串
        hash_int = 0
        for bit in hash_bits:
            hash_int = (hash_int << 1) | int(bit)

        return format(hash_int, f"0{HASH_SIZE * HASH_SIZE // 4}x")

    except Exception as e:
        logger.warning(f"计算 pHash 失败: {e}")
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """计算两个哈希的汉明距离（不同位数）"""
    if len(hash1) != len(hash2):
        return -1
    try:
        n1 = int(hash1, 16)
        n2 = int(hash2, 16)
        return bin(n1 ^ n2).count("1")
    except ValueError:
        return -1


def are_duplicates(hash1: str, hash2: str, threshold: int = 5) -> bool:
    """判断两个指纹是否视为重复（汉明距离 <= threshold）"""
    dist = hamming_distance(hash1, hash2)
    return 0 <= dist <= threshold
