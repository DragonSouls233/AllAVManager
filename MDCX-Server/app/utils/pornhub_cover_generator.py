"""
PORNHub 视频封面生成器（增强版）

从视频正片时长的 20%-80% 区间内选取 3 帧高清画面，
通过清晰度、亮度、色彩综合评分筛选最优帧生成统一封面。

命名规则: {原视频名}_cover.jpg
"""

import asyncio
import logging
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from app.utils.bin_tools import get_ffmpeg_path, get_ffprobe_path

logger = logging.getLogger(__name__)

# 默认封面配置
DEFAULT_COVER_WIDTH = 480
DEFAULT_COVER_QUALITY = 85      # JPEG 质量 1-100
DEFAULT_SAMPLE_POINTS = 3       # 采样帧数
DEFAULT_SAMPLE_RANGE = (0.2, 0.8)  # 采样区间（视频时长的百分比）
DEFAULT_TEMP_DIR = None         # None 自动使用系统临时目录


async def generate_cover(
    video_path: str,
    output_dir: str,
    cover_name: Optional[str] = None,
    width: int = DEFAULT_COVER_WIDTH,
    quality: int = DEFAULT_COVER_QUALITY,
    sample_points: int = DEFAULT_SAMPLE_POINTS,
    sample_range: tuple[float, float] = DEFAULT_SAMPLE_RANGE,
    force: bool = False,
) -> dict:
    """从视频文件生成封面图

    流程：
      1. 获取视频总时长
      2. 在 sample_range 区间内均匀取 sample_points 个时间点
      3. 对每个时间点截取一帧
      4. 通过清晰度、亮度评分选择最优帧
      5. 输出为统一分辨率的封面图

    Args:
        video_path: 视频文件路径
        output_dir: 封面输出目录
        cover_name: 封面文件名（不含扩展名），默认使用视频文件名
        width: 封面宽度（保持宽高比）
        quality: JPEG 质量 (1-100)
        sample_points: 采样帧数（默认 3）
        sample_range: 采样区间 (start_pct, end_pct)，0.0-1.0 范围
        force: 是否覆盖已存在的封面

    Returns:
        {"status": "ok", "cover_path": str, "frames": [...]}
        {"status": "error", "message": str}
    """
    # 检查 ffmpeg
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg or not Path(ffmpeg).exists():
        return {"status": "error", "message": "ffmpeg 未找到"}

    inp = Path(video_path)
    if not inp.exists():
        return {"status": "error", "message": f"视频文件不存在: {video_path}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not cover_name:
        cover_name = inp.stem
    # 移除不合法文件名字符
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', cover_name)
    final_cover = out_dir / f"{safe_name}_cover.jpg"

    if final_cover.exists() and not force:
        return {
            "status": "ok",
            "message": "封面已存在",
            "cover_path": str(final_cover),
            "frames": [],
        }

    # 1. 获取视频时长（秒）
    duration = _get_video_duration(str(inp))
    if duration is None or duration <= 0:
        return {"status": "error", "message": "无法获取视频时长"}

    # 不截取前 20% 和后 20% 的视频范围
    start_time = duration * sample_range[0]
    end_time = duration * sample_range[1]
    if end_time <= start_time:
        start_time = duration * 0.1
        end_time = duration * 0.9

    # 2. 均匀取 sample_points 个时间点
    if sample_points < 1:
        sample_points = 1
    interval = (end_time - start_time) / (sample_points + 1)
    timestamps = [start_time + interval * (i + 1) for i in range(sample_points)]

    # 3. 截取每一帧
    frames = []
    for ts in timestamps:
        frame = _extract_frame(ffmpeg, str(inp), ts, width)
        if frame:
            frames.append(frame)

    if not frames:
        return {"status": "error", "message": "所有帧截取失败"}

    # 4. 评分选取最优帧
    scored = [_score_frame(f) for f in frames]
    best_frame = max(scored, key=lambda x: x["score"])

    # 5. 将最优帧作为最终封面
    _copy_as_cover(ffmpeg, best_frame["path"], str(final_cover), quality)

    # 清理临时帧文件
    for f in frames:
        try:
            Path(f).unlink(missing_ok=True)
        except Exception:
            pass

    return {
        "status": "ok",
        "cover_path": str(final_cover),
        "frames": [
            {"timestamp": round(ts, 1), "score": round(s["score"], 2)}
            for ts, s in zip(timestamps, scored)
        ],
    }


# ==================== 内部辅助函数 ====================


def _get_video_duration(video_path: str) -> Optional[float]:
    """通过 ffprobe 获取视频时长（秒）"""
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        # 降级使用 ffmpeg
        ffprobe = get_ffmpeg_path()

    try:
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning("获取视频时长失败: %s", e)
    return None


def _extract_frame(ffmpeg: str, video_path: str, timestamp: float, width: int) -> Optional[str]:
    """从视频指定时间点截取一帧"""
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        cmd = [
            ffmpeg, "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={width}:-1",
            "-q:v", "2",  # 高质量 JPEG
            tmp_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and Path(tmp_path).exists() and Path(tmp_path).stat().st_size > 0:
            return tmp_path
    except Exception as e:
        logger.warning("截帧失败 [ts=%.1f]: %s", timestamp, e)

    # 清理失败的文件
    try:
        Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        pass
    return None


def _score_frame(frame_path: str) -> dict:
    """对一帧图片进行质量评分

    评分依据：
      - 清晰度（Laplacian 方差近似）
      - 亮度（平均像素值）
      - 色彩丰富度（标准差）

    Returns:
        {"path": str, "score": float, "sharpness": float, "brightness": float, "colorfulness": float}
    """
    score = {"path": frame_path, "score": 0.0, "sharpness": 0.0, "brightness": 0.0, "colorfulness": 0.0}

    try:
        from PIL import Image
        import numpy as np

        img = Image.open(frame_path).convert("RGB")
        arr = np.array(img, dtype=np.float32)

        # 清晰度：Laplacian 方差（近似用相邻像素差的标准差）
        if arr.ndim == 3:
            gray = np.mean(arr, axis=2)
        else:
            gray = arr
        # 计算水平方向和垂直方向的梯度
        dx = np.diff(gray, axis=1)
        dy = np.diff(gray, axis=0)
        sharpness = np.std(dx) + np.std(dy)

        # 亮度：平均像素值（0-255）
        brightness = np.mean(arr)

        # 色彩丰富度：RGB 三个通道的标准差均值
        if arr.ndim == 3:
            colorfulness = np.mean([np.std(arr[:, :, c]) for c in range(3)])
        else:
            colorfulness = 0.0

        # 综合评分：清晰度权重 0.5，亮度权重 0.2，色彩权重 0.3
        # 归一化处理
        norm_sharpness = min(sharpness / 50.0, 1.0) if sharpness > 0 else 0
        norm_brightness = 1.0 - abs(brightness - 128) / 128.0  # 接近 128 为最佳
        norm_colorfulness = min(colorfulness / 80.0, 1.0) if colorfulness > 0 else 0

        total = norm_sharpness * 0.5 + norm_brightness * 0.2 + norm_colorfulness * 0.3

        score["score"] = total * 100
        score["sharpness"] = float(sharpness)
        score["brightness"] = float(brightness)
        score["colorfulness"] = float(colorfulness)

    except ImportError:
        # 没有 PIL/numpy 时，用文件大小作为粗略评分
        try:
            size = Path(frame_path).stat().st_size
            score["score"] = min(size / 10000, 100) if size > 0 else 0
        except Exception:
            score["score"] = 50.0
    except Exception as e:
        logger.warning("帧评分失败: %s", e)
        score["score"] = 50.0

    return score


def _copy_as_cover(ffmpeg: str, src_path: str, dst_path: str, quality: int) -> None:
    """将最优帧复制为最终封面，并调整质量"""
    try:
        cmd = [
            ffmpeg, "-y",
            "-i", src_path,
            "-q:v", str(max(1, min(quality // 10, 31))),  # ffmpeg q:v 范围 2-31（值越小质量越高）
            dst_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        logger.warning("封面复制失败: %s，回退直接复制文件", e)
        import shutil
        shutil.copy2(src_path, dst_path)
