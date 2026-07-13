"""
GIF 动图生成服务

从视频片段生成 GIF 动图，支持：
- 指定起始时间和时长
- 指定分辨率（自动保持宽高比）
- 指定帧率
- 调色板优化（避免颜色失真）

参考 JvedioNew 的 FFmpeg GIF 生成方案。

输出位置：
    data/gifs/{movie_id}/
        {timestamp}_{duration}s_{width}w.gif
        .meta.json  # 元数据
"""

import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config.manager import get_config_manager

logger = logging.getLogger(__name__)

DEFAULT_FPS = 12                # GIF 帧率
DEFAULT_WIDTH = 480             # GIF 宽度（自动按比例缩放）
DEFAULT_DURATION = 3.0          # 默认时长（秒）
MAX_DURATION = 30.0             # 最大时长限制
MAX_WIDTH = 800                 # 最大宽度


def _get_gif_dir(movie_id: int) -> Path:
    """获取影片 GIF 目录"""
    manager = get_config_manager()
    data_dir = getattr(manager.computed, 'data_dir', Path("data"))
    gif_dir = data_dir / "gifs" / str(movie_id)
    gif_dir.mkdir(parents=True, exist_ok=True)
    return gif_dir


def _get_video_duration(file_path: str) -> float:
    """获取视频时长"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             file_path],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def generate_gif(
    movie_id: int,
    file_path: str,
    start: float = 0.0,
    duration: float = DEFAULT_DURATION,
    width: int = DEFAULT_WIDTH,
    fps: int = DEFAULT_FPS,
) -> dict:
    """
    从视频生成 GIF 动图

    参数:
        movie_id: 影片 ID
        file_path: 视频文件路径
        start: 起始时间（秒）
        duration: GIF 时长（秒）
        width: 输出宽度（自动按比例缩放）
        fps: 帧率

    返回:
        {
            "gif_url": str,
            "file_size": int,
            "width": int,
            "height": int,
            "duration": float,
            "start": float,
        }
    """
    if not shutil.which("ffmpeg"):
        return {"error": "ffmpeg 未安装"}

    video_path = Path(file_path)
    if not video_path.exists():
        return {"error": f"视频文件不存在: {file_path}"}

    # 参数校验
    duration = max(0.5, min(duration, MAX_DURATION))
    width = max(120, min(width, MAX_WIDTH))
    fps = max(2, min(fps, 30))
    start = max(0.0, start)

    # 检查视频时长，避免越界
    total_duration = _get_video_duration(str(video_path))
    if total_duration > 0 and start + duration > total_duration:
        duration = max(0.5, total_duration - start)
        if duration <= 0:
            return {"error": "起始时间超过视频时长"}

    gif_dir = _get_gif_dir(movie_id)

    # 生成文件名：起始时间_时长_宽度
    filename = f"{int(start)}s_{duration:.1f}s_{width}w.gif"
    output_path = gif_dir / filename

    # 使用两遍法：先生成调色板，再用调色板生成 GIF（颜色更丰富）
    palette_path = gif_dir / f".palette_{int(start)}.png"

    try:
        # 1. 生成调色板
        cmd_palette = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(video_path),
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen=stats_mode=diff",
            "-y", str(palette_path),
        ]
        result = subprocess.run(cmd_palette, capture_output=True, text=True, timeout=60,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0 or not palette_path.exists():
            logger.warning(f"调色板生成失败，回退到直接生成: {(result.stderr or '')[:200]}")
            # 回退方案：直接生成 GIF（无调色板）
            cmd_direct = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}",
                "-t", f"{duration:.3f}",
                "-i", str(video_path),
                "-vf", f"fps={fps},scale={width}:-1:flags=lanczos",
                "-loop", "0",
                str(output_path),
            ]
            result = subprocess.run(cmd_direct, capture_output=True, text=True, timeout=120,
                                    encoding="utf-8", errors="replace")
            if result.returncode != 0:
                return {"error": f"GIF 生成失败: {(result.stderr or '')[:300]}"}
        else:
            # 2. 用调色板生成 GIF
            cmd_gif = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}",
                "-t", f"{duration:.3f}",
                "-i", str(video_path),
                "-i", str(palette_path),
                "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
                str(output_path),
            ]
            result = subprocess.run(cmd_gif, capture_output=True, text=True, timeout=120,
                                    encoding="utf-8", errors="replace")
            if result.returncode != 0:
                return {"error": f"GIF 生成失败: {(result.stderr or '')[:300]}"}

        # 清理调色板
        palette_path.unlink(missing_ok=True)

        if not output_path.exists():
            return {"error": "GIF 文件未生成"}

        # 获取实际尺寸
        actual_width, actual_height = _get_image_size(str(output_path))
        file_size = output_path.stat().st_size

        result_meta = {
            "gif_url": f"/api/v1/player/{movie_id}/gifs/{filename}",
            "file_path": str(output_path),
            "file_size": file_size,
            "width": actual_width or width,
            "height": actual_height or 0,
            "duration": duration,
            "start": start,
            "fps": fps,
            "created_at": datetime.now().isoformat(),
        }

        logger.info(f"影片 {movie_id} 生成 GIF: {filename} ({file_size} bytes)")
        return result_meta

    except subprocess.TimeoutExpired:
        return {"error": "GIF 生成超时（视频可能过长或过大）"}
    except Exception as e:
        return {"error": f"GIF 生成异常: {e}"}


def _get_image_size(image_path: str) -> tuple[Optional[int], Optional[int]]:
    """获取图片尺寸"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0",
             image_path],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("x")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None, None


def list_gifs(movie_id: int) -> list[dict]:
    """列出影片的所有 GIF"""
    gif_dir = _get_gif_dir(movie_id)
    gifs = []
    for p in sorted(gif_dir.glob("*.gif")):
        try:
            stat = p.stat()
            width, height = _get_image_size(str(p))
            gifs.append({
                "gif_url": f"/api/v1/player/{movie_id}/gifs/{p.name}",
                "file_name": p.name,
                "file_size": stat.st_size,
                "width": width,
                "height": height,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            continue
    return gifs


def get_gif_file_path(movie_id: int, filename: str) -> Optional[Path]:
    """获取 GIF 文件路径"""
    gif_dir = _get_gif_dir(movie_id)
    target = gif_dir / filename
    try:
        target.resolve().relative_to(gif_dir.resolve())
    except ValueError:
        return None
    if target.exists() and target.is_file() and target.suffix.lower() == ".gif":
        return target
    return None


def delete_gif(movie_id: int, filename: str) -> bool:
    """删除指定 GIF"""
    path = get_gif_file_path(movie_id, filename)
    if path:
        try:
            path.unlink()
            return True
        except Exception:
            return False
    return False
