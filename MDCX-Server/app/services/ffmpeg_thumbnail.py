"""
视频缩略图进度条服务

为 Artplayer / Video.js 等播放器生成进度条悬停预览缩略图。

输出两种格式：
1. **精灵图 (sprite)**：N 张小图拼接成一张大图，配合 VTT 文件描述每张小图的时间区间
2. **VTT 文件**：WebVTT 格式元数据，前端用 <track kind="metadata"> 加载

参考 YouTube / B 站的进度条预览效果。

文件输出位置：
    data/thumbnails/{movie_id}/sprite/
        sprite.jpg          # 精灵图（多张缩略图拼接）
        sprite.vtt          # VTT 元数据
        preview_{n}.jpg     # 单独的预览图（可选，供其他用途）

独立模块，不依赖 thumbnail.py 的现有截图功能。
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.config.manager import get_config_manager

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_INTERVAL = 30          # 每 30 秒一张缩略图
DEFAULT_THUMB_WIDTH = 160      # 缩略图宽度
DEFAULT_THUMB_HEIGHT = 90      # 缩略图高度（16:9）
DEFAULT_COLS = 10              # 精灵图每行小图数
DEFAULT_QUALITY = 85           # JPEG 质量
DEFAULT_INTERVALS_MIN = 20     # 最少生成的缩略图数
DEFAULT_INTERVALS_MAX = 200    # 最多生成的缩略图数


def _get_sprite_dir(movie_id: int) -> Path:
    """获取影片缩略图进度条目录"""
    manager = get_config_manager()
    data_dir = getattr(manager.computed, 'data_dir', Path("data"))
    sprite_dir = data_dir / "thumbnails" / str(movie_id) / "sprite"
    sprite_dir.mkdir(parents=True, exist_ok=True)
    return sprite_dir


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


def _build_sprite_with_imagemagick(images: list[Path], output: Path, cols: int) -> bool:
    """用 ImageMagick montage 拼接精灵图"""
    if not shutil.which("magick") and not shutil.which("montage"):
        return False
    try:
        cmd = ["montage"]
        if shutil.which("magick"):
            cmd = ["magick", "montage"]
        cmd.extend([
            "-tile", f"{cols}x",
            "-geometry", "+0+0",
            "-background", "none",
            *[str(p) for p in images],
            str(output),
        ])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                encoding="utf-8", errors="replace")
        return result.returncode == 0 and output.exists()
    except Exception as e:
        logger.warning(f"montage 拼接失败: {e}")
        return False


def _build_sprite_with_ffmpeg(images: list[Path], output: Path, cols: int, rows: int,
                              thumb_w: int, thumb_h: int) -> bool:
    """用 ffmpeg 拼接精灵图（无 ImageMagick 时的回退方案）"""
    from app.utils.bin_tools import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    if not os.path.isfile(ffmpeg) or not images:
        return False
    try:
        # ffmpeg 拼接：先按行拼接，再按列拼接
        # 简化版：使用 filter_complex 把 N 个输入拼成 cols x rows 网格
        n = len(images)
        inputs = []
        for p in images:
            inputs.extend(["-i", str(p)])

        # 构建 filter：缩放 + 拼接
        # 用 xstack filter（ffmpeg 4.3+）或 hstack/vstack 组合
        filter_parts = []
        for i in range(n):
            filter_parts.append(f"[{i}:v]scale={thumb_w}:{thumb_h}:force_original_aspect_ratio=decrease,pad={thumb_w}:{thumb_h}:(ow-iw)/2:(oh-ih)/2[v{i}]")

        # 用 xstack 拼接
        xstack_inputs = "".join(f"[v{i}]" for i in range(n))
        layout = "|".join(f"{(i % cols) * thumb_w}_{(i // cols) * thumb_h}" for i in range(n))
        filter_complex = ";".join(filter_parts) + f";{xstack_inputs}xstack=inputs={n}:layout={layout}[v]"

        cmd = [ffmpeg, "-y", *inputs, "-filter_complex", filter_complex,
               "-frames:v", "1", "-q:v", str(DEFAULT_QUALITY), str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                encoding="utf-8", errors="replace")
        return result.returncode == 0 and output.exists()
    except Exception as e:
        logger.warning(f"ffmpeg 拼接精灵图失败: {e}")
        return False


def _format_vtt_timestamp(seconds: float) -> str:
    """格式化为 WebVTT 时间戳 (HH:MM:SS.mmm)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _write_vtt(sprites: list[dict], vtt_path: Path, sprite_filename: str,
               thumb_w: int, thumb_h: int, cols: int) -> None:
    """写入 WebVTT 元数据文件"""
    lines = ["WEBVTT", ""]
    for i, sp in enumerate(sprites):
        start = sp["start"]
        end = sp["end"]
        row = i // cols
        col = i % cols
        x = col * thumb_w
        y = row * thumb_h
        lines.append(f"{_format_vtt_timestamp(start)} --> {_format_vtt_timestamp(end)}")
        lines.append(f"{sprite_filename}#xywh={x},{y},{thumb_w},{thumb_h}")
        lines.append("")
    vtt_path.write_text("\n".join(lines), encoding="utf-8")


def generate_thumbnail_sprite(
    movie_id: int,
    file_path: str,
    interval: int = DEFAULT_INTERVAL,
    thumb_width: int = DEFAULT_THUMB_WIDTH,
    thumb_height: int = DEFAULT_THUMB_HEIGHT,
    cols: int = DEFAULT_COLS,
    force: bool = False,
) -> dict:
    """
    为影片生成进度条预览精灵图 + VTT 文件

    参数:
        movie_id: 影片 ID
        file_path: 视频文件路径
        interval: 截图间隔（秒）
        thumb_width: 单张缩略图宽度
        thumb_height: 单张缩略图高度
        cols: 精灵图每行小图数
        force: 是否强制重新生成

    返回:
        {
            "sprite_url": str,      # 精灵图 URL（相对路径）
            "vtt_url": str,         # VTT 文件 URL
            "count": int,           # 缩略图总数
            "interval": int,        # 截图间隔
            "duration": float,      # 视频时长
        }
    """
    from app.utils.bin_tools import get_ffmpeg_path
    if not os.path.isfile(get_ffmpeg_path()):
        logger.warning("ffmpeg 未安装，无法生成进度条缩略图")
        return {"error": "ffmpeg 未安装"}

    video_path = Path(file_path)
    if not video_path.exists():
        return {"error": f"视频文件不存在: {file_path}"}

    sprite_dir = _get_sprite_dir(movie_id)
    sprite_path = sprite_dir / "sprite.jpg"
    vtt_path = sprite_dir / "sprite.vtt"
    meta_path = sprite_dir / ".meta"

    # 变更检测
    current_sig = f"{video_path.stat().st_mtime}:{video_path.stat().st_size}:{interval}:{thumb_width}x{thumb_height}"
    if not force and meta_path.exists() and sprite_path.exists() and vtt_path.exists():
        try:
            if meta_path.read_text(encoding="utf-8") == current_sig:
                # 已存在，读取元数据返回
                meta_json = json.loads((sprite_dir / ".meta.json").read_text(encoding="utf-8"))
                return meta_json
        except Exception:
            pass

    # 获取时长
    duration = _get_video_duration(str(video_path))
    if duration <= 0:
        return {"error": "无法获取视频时长"}

    # 计算截帧点
    # 根据时长动态调整间隔，保证缩略图数量在合理范围
    raw_count = int(duration / interval)
    if raw_count < DEFAULT_INTERVALS_MIN:
        # 时长短，缩小间隔保证至少 N 张
        interval = max(2, int(duration / DEFAULT_INTERVALS_MIN))
        raw_count = int(duration / interval)
    elif raw_count > DEFAULT_INTERVALS_MAX:
        # 时长长，放大间隔避免过多
        interval = max(interval, int(duration / DEFAULT_INTERVALS_MAX))
        raw_count = int(duration / DEFAULT_INTERVALS_MAX)

    timestamps = []
    t = interval / 2  # 从区间中点开始，避免黑屏
    while t < duration:
        timestamps.append(t)
        t += interval

    if not timestamps:
        timestamps = [duration / 2]

    rows = (len(timestamps) + cols - 1) // cols

    # 生成单张缩略图
    single_images = []
    for i, ts in enumerate(timestamps):
        out_path = sprite_dir / f"frame_{i:04d}.jpg"
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", f"{ts:.3f}",
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-vf", f"scale={thumb_width}:{thumb_height}:force_original_aspect_ratio=decrease,pad={thumb_width}:{thumb_height}:(ow-iw)/2:(oh-ih)/2",
                    "-q:v", str(DEFAULT_QUALITY),
                    str(out_path),
                ],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and out_path.exists():
                single_images.append(out_path)
            else:
                logger.debug(f"截帧失败 {ts}s: {(result.stderr or '')[:200]}")
        except Exception as e:
            logger.warning(f"截帧异常 {ts}s: {e}")

    if not single_images:
        return {"error": "未能生成任何缩略图"}

    # 拼接精灵图
    sprite_ok = _build_sprite_with_imagemagick(single_images, sprite_path, cols)
    if not sprite_ok:
        sprite_ok = _build_sprite_with_ffmpeg(single_images, sprite_path, cols, rows, thumb_width, thumb_height)

    if not sprite_ok:
        # 最后回退：直接用第一张作为精灵图
        logger.warning(f"影片 {movie_id} 精灵图拼接失败，回退到首张缩略图")
        shutil.copy(single_images[0], sprite_path)

    # 写 VTT
    sprites_meta = []
    for i, ts in enumerate(timestamps[:len(single_images)]):
        end_ts = timestamps[i + 1] if i + 1 < len(timestamps) else duration
        sprites_meta.append({"start": ts, "end": end_ts})

    _write_vtt(sprites_meta, vtt_path, "sprite.jpg", thumb_width, thumb_height, cols)

    # 写元数据
    try:
        meta_path.write_text(current_sig, encoding="utf-8")
        meta_json = {
            "sprite_url": f"/api/v1/player/{movie_id}/thumbnail-sprite/sprite.jpg",
            "vtt_url": f"/api/v1/player/{movie_id}/thumbnail-sprite/sprite.vtt",
            "count": len(single_images),
            "interval": interval,
            "duration": duration,
            "thumb_width": thumb_width,
            "thumb_height": thumb_height,
            "cols": cols,
        }
        (sprite_dir / ".meta.json").write_text(json.dumps(meta_json, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # 清理单张图（保留以备 GIF 等其他用途，可选）
    # for img in single_images:
    #     img.unlink(missing_ok=True)

    logger.info(f"影片 {movie_id} 生成进度条缩略图 {len(single_images)} 张")
    return meta_json


def get_thumbnail_sprite(movie_id: int) -> Optional[dict]:
    """获取已生成的缩略图进度条元数据"""
    sprite_dir = _get_sprite_dir(movie_id)
    meta_json = sprite_dir / ".meta.json"
    if not meta_json.exists():
        return None
    try:
        return json.loads(meta_json.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_sprite_file_path(movie_id: int, filename: str) -> Optional[Path]:
    """获取精灵图/VTT 文件路径"""
    sprite_dir = _get_sprite_dir(movie_id)
    target = sprite_dir / filename
    # 安全检查：防止目录穿越
    try:
        target.resolve().relative_to(sprite_dir.resolve())
    except ValueError:
        return None
    if target.exists() and target.is_file():
        return target
    return None


# ============================================
# v4.1 B5：智能裁剪缩略图
# ============================================

def _capture_frame_at(video_path: str, ts: float, out_path: Path,
                      width: int = 480, quality: int = 90) -> bool:
    """在指定时间点截取单帧

    Args:
        video_path: 视频文件路径
        ts: 时间点（秒）
        out_path: 输出图像路径
        width: 输出宽度（保持原比例缩放）
        quality: JPEG 质量

    Returns:
        是否成功
    """
    from app.utils.bin_tools import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    if not os.path.isfile(ffmpeg):
        return False
    try:
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-ss", f"{ts:.3f}",
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", f"scale={width}:-2",
                "-q:v", str(quality),
                str(out_path),
            ],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0 and out_path.exists()
    except Exception as e:
        logger.warning(f"截帧失败 {ts}s: {e}")
        return False


def _image_variance(image_path: Path) -> float:
    """计算图像灰度方差（用于过滤空白画面）

    方差越低，画面越接近纯色（黑屏/白屏）。

    Args:
        image_path: 图像路径

    Returns:
        灰度方差；失败返回 0
    """
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        return float(np.var(img))
    except ImportError:
        # 无 cv2 时用 PIL 计算近似方差
        try:
            from PIL import Image
            gray = Image.open(image_path).convert("L")
            hist = gray.histogram()
            total = sum(hist)
            if total == 0:
                return 0.0
            mean = sum(i * c for i, c in enumerate(hist)) / total
            var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
            return float(var)
        except Exception:
            return 0.0
    except Exception:
        return 0.0


def _detect_faces_in_image(image_path: Path) -> list[dict]:
    """检测图像中的人脸位置与数量

    优先使用 face_crop 模块的标志点检测（v4.1 B4），失败时回退到
    FaceCropper.detect_faces。

    Args:
        image_path: 图像路径

    Returns:
        人脸信息列表，每项含 cx / cy（人脸中心，归一化 0-1）与 score
    """
    try:
        # 延迟导入避免循环依赖
        from app.services.face_crop import detect_landmarks
        lms_list = detect_landmarks(str(image_path))
        if lms_list:
            from PIL import Image
            with Image.open(image_path) as im:
                w, h = im.size
            faces = []
            for lm in lms_list:
                # 用双眼 + 鼻尖 + 嘴角的中点作为人脸中心
                pts = [lm["right_eye"], lm["left_eye"], lm["nose_tip"],
                       lm["mouth_right"], lm["mouth_left"]]
                cx = sum(p[0] for p in pts) / len(pts) / max(w, 1)
                cy = sum(p[1] for p in pts) / len(pts) / max(h, 1)
                faces.append({"cx": cx, "cy": cy, "score": lm.get("score", 1.0)})
            return faces
    except Exception as e:
        logger.debug(f"face_crop.detect_landmarks 失败: {e}")

    # 回退：FaceCropper.detect_faces（同步调用，但需初始化）
    try:
        import asyncio
        from app.services.face_crop import get_face_cropper

        # 在无事件循环上下文中安全调用
        try:
            asyncio.get_running_loop()
            # 已在事件循环中：不能直接 await，跳过
            return []
        except RuntimeError:
            cropper = asyncio.run(get_face_cropper())
            if cropper is None:
                return []
            faces_raw = cropper.detect_faces(str(image_path))
            from PIL import Image
            with Image.open(image_path) as im:
                w, h = im.size
            faces = []
            for f in faces_raw:
                cx = (f["x"] + f["w"] / 2) / max(w, 1)
                cy = (f["y"] + f["h"] / 2) / max(h, 1)
                faces.append({"cx": cx, "cy": cy, "score": f.get("score", 1.0)})
            return faces
    except Exception as e:
        logger.debug(f"FaceCropper 回退检测失败: {e}")
        return []


def _score_thumbnail(faces: list[dict], variance: float, img_w: int, img_h: int) -> float:
    """为一张候选缩略图打分

    评分维度：
        - 人脸数量：1~3 张最佳，0 张次之，过多扣分
        - 人脸居中度：人脸中心越接近图像中心，得分越高
        - 画面信息量：方差过低（空白画面）扣分

    Args:
        faces: 人脸列表
        variance: 灰度方差
        img_w: 图像宽度
        img_h: 图像高度

    Returns:
        综合评分（越高越好）
    """
    score = 0.0

    # 画面信息量（方差）：方差 > 阈值才有意义
    # 经验值：自然画面方差通常 > 1000，纯黑/白 < 100
    if variance < 100:
        score -= 50.0  # 空白画面重罚
    else:
        # 用 log 压缩，避免方差过高主导
        import math
        score += min(20.0, math.log10(max(variance, 1.0)) * 5.0)

    # 人脸评分
    n_faces = len(faces)
    if n_faces == 0:
        # 无人脸：仍可用，但低于有脸
        score += 10.0
    elif n_faces <= 3:
        # 1~3 张脸：最佳
        score += 30.0 + (3 - n_faces) * 5.0  # 数量适中加分
    else:
        # 过多：递减
        score += max(0.0, 30.0 - (n_faces - 3) * 5.0)

    # 人脸居中度（每张脸都加分）
    for f in faces:
        # 与图像中心 (0.5, 0.5) 的距离，0~0.707
        dist = ((f["cx"] - 0.5) ** 2 + (f["cy"] - 0.5) ** 2) ** 0.5
        # 居中加分（越近中心越高）
        score += max(0.0, (0.5 - dist) * 20.0)

    return score


def generate_smart_thumbnails(
    video_path: str,
    count: int = 4,
    output_dir: str = "",
    width: int = 480,
) -> list[str]:
    """智能裁剪缩略图（v4.1 B5）

    流程：
        1. 在视频多个时间点（默认 20%/40%/60%/80%）截图，
           候选数量 = max(count, 4)
        2. 用 face_crop 检测每张截图中的人脸数量和位置
        3. 选择含人脸的最佳缩略图（优先人脸居中、数量适中）
        4. 避免截出空白画面（检查图像方差）

    Args:
        video_path: 视频文件路径
        count: 期望生成的缩略图数量
        output_dir: 输出目录；为空时使用视频同目录下的 .thumbs 子目录
        width: 截图宽度（保持原比例）

    Returns:
        生成的缩略图绝对路径列表（按评分从高到低排序）。
        若 ffmpeg 缺失或视频时长无法获取，返回空列表。
    """
    from app.utils.bin_tools import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    if not os.path.isfile(ffmpeg):
        logger.warning("ffmpeg 未安装，无法生成智能缩略图")
        return []

    video = Path(video_path)
    if not video.exists():
        logger.warning(f"视频文件不存在: {video_path}")
        return []

    # 输出目录
    if output_dir:
        out_root = Path(output_dir)
    else:
        out_root = video.parent / ".thumbs"
    out_root.mkdir(parents=True, exist_ok=True)

    # 获取时长
    duration = _get_video_duration(str(video))
    if duration <= 0:
        logger.warning(f"无法获取视频时长: {video_path}")
        return []

    # 候选时间点：取 max(count, 4) 个，均匀分布在 10%~90%
    n_candidates = max(count, 4)
    if n_candidates == 4:
        ratios = [0.2, 0.4, 0.6, 0.8]
    else:
        # 均匀分布，避开首尾 10%
        step = 0.8 / (n_candidates - 1) if n_candidates > 1 else 0.5
        ratios = [0.1 + step * i for i in range(n_candidates)]

    timestamps = [duration * r for r in ratios]

    # 截图并打分
    candidates: list[dict] = []  # {"path": Path, "score": float, "ts": float}
    for i, ts in enumerate(timestamps):
        out_path = out_root / f"smart_{i:02d}.jpg"
        ok = _capture_frame_at(str(video), ts, out_path, width=width)
        if not ok:
            continue

        variance = _image_variance(out_path)
        faces = _detect_faces_in_image(out_path)

        from PIL import Image
        try:
            with Image.open(out_path) as im:
                img_w, img_h = im.size
        except Exception:
            img_w, img_h = width, int(width * 9 / 16)

        score = _score_thumbnail(faces, variance, img_w, img_h)
        candidates.append({
            "path": out_path,
            "score": score,
            "ts": ts,
            "n_faces": len(faces),
            "variance": variance,
        })
        logger.debug(
            f"候选 {i}: ts={ts:.1f}s score={score:.2f} "
            f"faces={len(faces)} var={variance:.0f}"
        )

    if not candidates:
        return []

    # 按评分降序，取前 count 张
    candidates.sort(key=lambda c: c["score"], reverse=True)
    selected = candidates[:count]

    # 重命名为 thumb_0.jpg, thumb_1.jpg, ...（按评分排序）
    result_paths: list[str] = []
    for i, cand in enumerate(selected):
        new_path = out_root / f"thumb_{i:02d}.jpg"
        try:
            if new_path.exists():
                new_path.unlink()
            cand["path"].rename(new_path)
            result_paths.append(str(new_path.resolve()))
        except Exception as e:
            logger.warning(f"重命名缩略图失败: {e}")
            result_paths.append(str(cand["path"].resolve()))

    logger.info(
        f"智能缩略图生成完成：{len(result_paths)}/{count} 张，"
        f"视频时长 {duration:.1f}s"
    )
    return result_paths
