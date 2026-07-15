"""
视频缩略图/截图生成服务

参考 JavBoss 的 screenshot_manager 策略：
- 8 档秒数 [128, 63, 32, 16, 8, 4, 2, 1]，选取不超过时长的最大值
- 基于 ModifiedAt + Size 做变更检测，文件未变则跳过
- 截图存到 data/thumbnails/{movie_id}/

使用 ffmpeg -ss 快速截帧，无需全片解码。
"""
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.config.manager import get_config_manager

logger = logging.getLogger(__name__)

# JavBoss 策略：8 档秒数，从大到小
SCREENSHOT_SECONDS = [128, 63, 32, 16, 8, 4, 2, 1]


def _get_thumbnail_dir(movie_id: int) -> Path:
    """获取影片缩略图目录"""
    manager = get_config_manager()
    data_dir = manager.computed.data_dir if hasattr(manager.computed, 'data_dir') else Path("data")
    thumb_dir = data_dir / "thumbnails" / str(movie_id)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir


def _get_video_duration(file_path: str) -> float:
    """用 ffprobe 获取视频时长（秒）"""
    from app.utils.bin_tools import get_ffprobe_path
    ffprobe = get_ffprobe_path()
    if not os.path.isfile(ffprobe):
        return 0.0
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"ffprobe 获取时长失败 {file_path}: {e}")
    return 0.0


def pick_screenshot_second(duration: float) -> list[int]:
    """选取适合时长的截帧秒数列表（不超过时长）"""
    if duration <= 0:
        return [1]
    return [s for s in SCREENSHOT_SECONDS if s < duration] or [1]


def generate_thumbnails(
    movie_id: int,
    file_path: str,
    file_size: Optional[int] = None,
    force: bool = False,
) -> list[str]:
    """
    为影片生成缩略图截图

    参数:
        movie_id: 影片 ID
        file_path: 视频文件路径
        file_size: 文件大小（用于变更检测）
        force: 是否强制重新生成

    返回:
        生成的截图文件路径列表
    """
    from app.utils.bin_tools import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    if not os.path.isfile(ffmpeg):
        logger.warning("ffmpeg 未安装，无法生成缩略图")
        return []

    video_path = Path(file_path)
    if not video_path.exists():
        logger.warning(f"视频文件不存在: {file_path}")
        return []

    thumb_dir = _get_thumbnail_dir(movie_id)

    # 变更检测：检查 marker 文件
    marker = thumb_dir / ".meta"
    current_sig = f"{video_path.stat().st_mtime}:{video_path.stat().st_size}"
    if not force and marker.exists():
        try:
            if marker.read_text() == current_sig:
                # 文件未变更，返回已有截图
                existing = sorted(thumb_dir.glob("*.jpg"))
                if existing:
                    return [str(p) for p in existing]
        except Exception:
            pass

    # 清理旧截图
    for old in thumb_dir.glob("*.jpg"):
        old.unlink()

    # 获取时长，选取截帧秒数
    duration = _get_video_duration(str(video_path))
    seconds = pick_screenshot_second(duration)

    generated = []
    for sec in seconds:
        out_path = thumb_dir / f"{sec}.jpg"
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-ss", str(sec),       # 快速 seek
                    "-i", str(video_path),
                    "-frames:v", "1",       # 只取 1 帧
                    "-q:v", "3",            # 质量 (2-5 较好)
                    "-vf", "scale=640:-2",  # 缩放到 640 宽
                    "-y",
                    str(out_path),
                ],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and out_path.exists():
                generated.append(str(out_path))
            else:
                logger.debug(f"截帧失败 {sec}s: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.warning(f"截帧超时 {sec}s: {file_path}")
        except Exception as e:
            logger.warning(f"截帧异常 {sec}s: {e}")

    # 写入 marker
    try:
        marker.write_text(current_sig)
    except Exception:
        pass

    logger.info(f"影片 {movie_id} 生成 {len(generated)} 张缩略图")
    return generated


def get_thumbnails(movie_id: int) -> list[str]:
    """获取影片已有的缩略图路径列表"""
    thumb_dir = _get_thumbnail_dir(movie_id)
    return sorted([str(p) for p in thumb_dir.glob("*.jpg")])
