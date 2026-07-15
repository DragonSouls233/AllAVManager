"""
章节标记服务

为视频添加章节标记（chapter markers），让播放器显示精彩瞬间跳转点。

支持两种来源：
1. **手动标记**：用户在播放时点击"标记此刻"，自动记录当前时间为章节
2. **自动检测**：基于场景变化检测（ffmpeg select filter）自动识别精彩瞬间

数据存储：
    data/chapters/{movie_id}/chapters.json

章节格式参考 MKV/WebM 章节标准，前端兼容 Artplayer 的 chapters 插件。
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


def _get_chapter_dir(movie_id: int) -> Path:
    """获取影片章节目录"""
    manager = get_config_manager()
    data_dir = getattr(manager.computed, 'data_dir', Path("data"))
    chapter_dir = data_dir / "chapters" / str(movie_id)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    return chapter_dir


def _get_chapters_file(movie_id: int) -> Path:
    return _get_chapter_dir(movie_id) / "chapters.json"


def _get_video_duration(file_path: str) -> float:
    """获取视频时长"""
    from app.utils.bin_tools import get_ffprobe_path
    ffprobe = get_ffprobe_path()
    if not os.path.isfile(ffprobe):
        return 0.0
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet",
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


def _default_chapter_title(seconds: float) -> str:
    """根据时间生成默认章节标题"""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"章节 {m:02d}:{s:02d}"


def load_chapters(movie_id: int) -> list[dict]:
    """
    加载影片章节列表

    返回:
        [
            {
                "id": str,           # 章节 ID
                "start": float,      # 起始时间（秒）
                "end": float,        # 结束时间（秒），最后一个为视频时长
                "title": str,        # 章节标题
                "thumbnail": str,    # 章节缩略图 URL（可选）
                "created_at": str,   # 创建时间
                "source": str,       # 来源：manual/auto
            }
        ]
    """
    path = _get_chapters_file(movie_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "chapters" in data:
            return data["chapters"]
    except Exception as e:
        logger.warning(f"加载章节失败 {movie_id}: {e}")
    return []


def save_chapters(movie_id: int, chapters: list[dict]) -> None:
    """保存章节列表"""
    path = _get_chapters_file(movie_id)
    try:
        path.write_text(json.dumps({
            "movie_id": movie_id,
            "chapters": chapters,
            "updated_at": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"保存章节失败 {movie_id}: {e}")


def add_chapter(
    movie_id: int,
    start: float,
    title: Optional[str] = None,
    source: str = "manual",
    duration: Optional[float] = None,
) -> dict:
    """
    添加章节标记

    参数:
        movie_id: 影片 ID
        start: 起始时间（秒）
        title: 章节标题（留空自动生成）
        source: 来源 - manual（手动）/ auto（自动检测）
        duration: 视频时长（用于计算 end 字段）

    返回:
        新章节 dict
    """
    chapters = load_chapters(movie_id)

    # 防止重复：相近的章节（< 2 秒）合并
    for ch in chapters:
        if abs(ch["start"] - start) < 2.0:
            # 已存在相近章节，更新它
            if title:
                ch["title"] = title
            ch["updated_at"] = datetime.now().isoformat()
            save_chapters(movie_id, chapters)
            return ch

    chapter = {
        "id": f"ch_{int(start * 1000)}",
        "start": round(start, 3),
        "end": round(start + 30, 3),  # 默认 30 秒，最后会被 normalize 调整
        "title": title or _default_chapter_title(start),
        "source": source,
        "created_at": datetime.now().isoformat(),
    }

    chapters.append(chapter)
    chapters.sort(key=lambda c: c["start"])

    # 调整 end 时间为下一个章节的 start
    if duration:
        normalize_chapter_ends(chapters, duration)
    else:
        # 没有时长信息，用相邻章节推断
        for i, ch in enumerate(chapters):
            if i + 1 < len(chapters):
                ch["end"] = chapters[i + 1]["start"]
            else:
                ch["end"] = ch["start"] + 30  # 默认 30 秒

    save_chapters(movie_id, chapters)
    logger.info(f"影片 {movie_id} 添加章节: {chapter['title']} @ {start:.1f}s")
    return chapter


def update_chapter(movie_id: int, chapter_id: str, updates: dict) -> Optional[dict]:
    """更新章节"""
    chapters = load_chapters(movie_id)
    for ch in chapters:
        if ch["id"] == chapter_id:
            if "start" in updates:
                ch["start"] = round(float(updates["start"]), 3)
            if "title" in updates:
                ch["title"] = updates["title"]
            ch["updated_at"] = datetime.now().isoformat()
            chapters.sort(key=lambda c: c["start"])
            save_chapters(movie_id, chapters)
            return ch
    return None


def delete_chapter(movie_id: int, chapter_id: str) -> bool:
    """删除章节"""
    chapters = load_chapters(movie_id)
    new_chapters = [c for c in chapters if c["id"] != chapter_id]
    if len(new_chapters) == len(chapters):
        return False
    save_chapters(movie_id, new_chapters)
    return True


def normalize_chapter_ends(chapters: list[dict], duration: float) -> None:
    """规范化章节 end 时间"""
    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            ch["end"] = chapters[i + 1]["start"]
        else:
            ch["end"] = duration


def auto_detect_chapters(
    movie_id: int,
    file_path: str,
    threshold: float = 0.4,
    min_duration: float = 10.0,
) -> dict:
    """
    使用 ffmpeg 场景检测自动识别章节边界

    参数:
        movie_id: 影片 ID
        file_path: 视频文件路径
        threshold: 场景变化阈值 (0-1)，越大越敏感
        min_duration: 最小章节间隔（秒）

    返回:
        {
            "added": int,        # 新增章节数
            "total": int,        # 总章节数
            "chapters": list,    # 所有章节
        }
    """
    from app.utils.bin_tools import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    if not os.path.isfile(ffmpeg):
        return {"error": "ffmpeg 未安装"}

    video_path = Path(file_path)
    if not video_path.exists():
        return {"error": f"视频文件不存在: {file_path}"}

    duration = _get_video_duration(str(video_path))
    if duration <= 0:
        return {"error": "无法获取视频时长"}

    try:
        # ffmpeg 场景检测：showframes + scene score
        cmd = [
            ffmpeg, "-i", str(video_path),
            "-filter:v", f"select='gt(scene,{threshold})'",
            "-show_frames",
            "-show_entries", "frame=pkt_pts_time",
            "-of", "csv=p=0",
            "-print_format", "csv",
            "-",
        ]
        # 注意：上面参数有误，正确做法用 ffprobe
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_frames",
            "-select_streams", "v:0",
            "-show_entries", "frame=pkt_pts_time,pkt_duration_time",
            "-of", "csv=p=0",
            "-read_intervals", "%+#1",
            str(video_path),
        ]
        # 实际场景检测需要逐帧分析，这里用简化的 ffmpeg filter
        # 用 ffmpeg 输出场景变化时间戳
        cmd = [
            ffmpeg, "-i", str(video_path),
            "-filter:v", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                encoding="utf-8", errors="replace")

        # 解析 stderr 中的 showinfo 行
        # 格式：[Parsed_showinfo...] n: 123 pts: 4567 pts_time:89.01 ...
        scene_timestamps = []
        for line in result.stderr.split("\n"):
            if "showinfo" in line and "pts_time:" in line:
                try:
                    pts_part = line.split("pts_time:")[1].split()[0]
                    ts = float(pts_part)
                    scene_timestamps.append(ts)
                except (ValueError, IndexError):
                    continue

        if not scene_timestamps:
            return {"added": 0, "total": len(load_chapters(movie_id)),
                    "chapters": load_chapters(movie_id), "message": "未检测到场景变化"}

        existing = load_chapters(movie_id)
        existing_starts = {round(c["start"], 1) for c in existing}

        added = 0
        for ts in scene_timestamps:
            # 过滤掉过近的章节
            too_close = any(abs(ts - s) < min_duration for s in existing_starts)
            if too_close:
                continue
            add_chapter(movie_id, ts, source="auto", duration=duration)
            existing_starts.add(round(ts, 1))
            added += 1

        chapters = load_chapters(movie_id)
        return {
            "added": added,
            "total": len(chapters),
            "chapters": chapters,
            "duration": duration,
        }

    except subprocess.TimeoutExpired:
        return {"error": "场景检测超时"}
    except Exception as e:
        return {"error": f"场景检测失败: {e}"}


def generate_chapter_thumbnails(movie_id: int, file_path: str, thumb_width: int = 320) -> dict:
    """为所有章节生成缩略图"""
    from app.utils.bin_tools import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    if not os.path.isfile(ffmpeg):
        return {"error": "ffmpeg 未安装"}

    chapters = load_chapters(movie_id)
    if not chapters:
        return {"error": "无章节"}

    chapter_dir = _get_chapter_dir(movie_id)
    thumb_dir = chapter_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    video_path = Path(file_path)
    if not video_path.exists():
        return {"error": "视频文件不存在"}

    updated = 0
    for ch in chapters:
        thumb_filename = f"{ch['id']}.jpg"
        thumb_path = thumb_dir / thumb_filename
        if thumb_path.exists():
            ch["thumbnail"] = f"/api/v1/player/{movie_id}/chapters/thumbnails/{thumb_filename}"
            continue

        try:
            result = subprocess.run(
                [ffmpeg, "-y",
                 "-ss", f"{ch['start']:.3f}",
                 "-i", str(video_path),
                 "-frames:v", "1",
                 "-vf", f"scale={thumb_width}:-2",
                 "-q:v", "3",
                 str(thumb_path)],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and thumb_path.exists():
                ch["thumbnail"] = f"/api/v1/player/{movie_id}/chapters/thumbnails/{thumb_filename}"
                updated += 1
        except Exception:
            continue

    save_chapters(movie_id, chapters)
    return {"updated": updated, "chapters": chapters}


def get_chapter_thumbnail_path(movie_id: int, filename: str) -> Optional[Path]:
    """获取章节缩略图路径"""
    chapter_dir = _get_chapter_dir(movie_id)
    target = chapter_dir / "thumbnails" / filename
    try:
        target.resolve().relative_to(chapter_dir.resolve())
    except ValueError:
        return None
    if target.exists() and target.is_file():
        return target
    return None
