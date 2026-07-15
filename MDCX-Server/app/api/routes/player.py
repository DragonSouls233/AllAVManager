"""
统一播放器 API 路由

整合：
- 缩略图进度条（精灵图 + VTT）
- GIF 动图生成
- 章节标记管理
- 字幕匹配

挂载在 /api/v1/player，所有端点都需要影片 ID。
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Movie
from app.services import ffmpeg_thumbnail, gif_generator, chapter_marker, subtitle_matcher

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== 共用工具 =====

async def _get_movie(session: AsyncSession, movie_id: int) -> Movie:
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")
    return movie


# ===== 缩略图进度条 =====

@router.get("/{movie_id}/thumbnail-sprite")
async def get_thumbnail_sprite_meta(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取缩略图进度条元数据"""
    movie = await _get_movie(session, movie_id)
    meta = ffmpeg_thumbnail.get_thumbnail_sprite(movie_id)
    if not meta:
        raise HTTPException(status_code=404, detail="未生成缩略图进度条")
    return meta


@router.post("/{movie_id}/thumbnail-sprite/generate")
async def generate_thumbnail_sprite(
    movie_id: int,
    interval: int = Query(30, ge=5, le=300),
    thumb_width: int = Query(160, ge=80, le=400),
    thumb_height: int = Query(90, ge=45, le=300),
    cols: int = Query(10, ge=2, le=20),
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """生成或刷新缩略图进度条"""
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")
    result = ffmpeg_thumbnail.generate_thumbnail_sprite(
        movie_id, movie.file_path,
        interval=interval, thumb_width=thumb_width, thumb_height=thumb_height,
        cols=cols, force=force,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/{movie_id}/thumbnail-sprite/{filename}")
async def serve_thumbnail_sprite_file(
    movie_id: int,
    filename: str,
):
    """提供精灵图 / VTT 文件"""
    if filename not in ("sprite.jpg", "sprite.vtt"):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = ffmpeg_thumbnail.get_sprite_file_path(movie_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "image/jpeg" if filename.endswith(".jpg") else "text/vtt"
    return FileResponse(str(path), media_type=media_type)


# ===== GIF 生成 =====

class GifRequest(BaseModel):
    start: float = Field(0.0, ge=0, description="起始时间（秒）")
    duration: float = Field(3.0, ge=0.5, le=30, description="GIF 时长（秒）")
    width: int = Field(480, ge=120, le=800, description="输出宽度")
    fps: int = Field(12, ge=2, le=30, description="帧率")


@router.get("/{movie_id}/gifs")
async def list_gifs(movie_id: int):
    """列出影片所有 GIF"""
    return {"items": gif_generator.list_gifs(movie_id)}


@router.post("/{movie_id}/gifs/generate")
async def generate_gif(
    movie_id: int,
    req: GifRequest,
    session: AsyncSession = Depends(get_session),
):
    """生成 GIF"""
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")
    result = gif_generator.generate_gif(
        movie_id, movie.file_path,
        start=req.start, duration=req.duration,
        width=req.width, fps=req.fps,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/{movie_id}/gifs/{filename}")
async def serve_gif_file(movie_id: int, filename: str):
    """提供 GIF 文件"""
    path = gif_generator.get_gif_file_path(movie_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="GIF 不存在")
    return FileResponse(str(path), media_type="image/gif")


@router.delete("/{movie_id}/gifs/{filename}")
async def delete_gif(movie_id: int, filename: str):
    """删除 GIF"""
    if gif_generator.delete_gif(movie_id, filename):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="GIF 不存在")


# ===== 章节标记 =====

class ChapterCreate(BaseModel):
    start: float = Field(..., ge=0, description="起始时间（秒）")
    title: Optional[str] = Field(None, description="章节标题")


class ChapterUpdate(BaseModel):
    start: Optional[float] = Field(None, ge=0)
    title: Optional[str] = None


@router.get("/{movie_id}/chapters")
async def list_chapters(movie_id: int):
    """列出所有章节"""
    return {"items": chapter_marker.load_chapters(movie_id)}


@router.post("/{movie_id}/chapters")
async def add_chapter(
    movie_id: int,
    req: ChapterCreate,
    session: AsyncSession = Depends(get_session),
):
    """添加章节"""
    movie = await _get_movie(session, movie_id)
    duration = None
    if movie.duration:
        duration = float(movie.duration)
    chapter = chapter_marker.add_chapter(
        movie_id, req.start, title=req.title, source="manual", duration=duration
    )
    return chapter


@router.put("/{movie_id}/chapters/{chapter_id}")
async def update_chapter(
    movie_id: int,
    chapter_id: str,
    req: ChapterUpdate,
):
    """更新章节"""
    updates = req.model_dump(exclude_none=True)
    result = chapter_marker.update_chapter(movie_id, chapter_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="章节不存在")
    return result


@router.delete("/{movie_id}/chapters/{chapter_id}")
async def delete_chapter(movie_id: int, chapter_id: str):
    """删除章节"""
    if chapter_marker.delete_chapter(movie_id, chapter_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="章节不存在")


@router.post("/{movie_id}/chapters/auto-detect")
async def auto_detect_chapters(
    movie_id: int,
    threshold: float = Query(0.4, ge=0.05, le=1.0),
    min_duration: float = Query(10.0, ge=2.0, le=120.0),
    session: AsyncSession = Depends(get_session),
):
    """自动检测章节（基于场景变化）"""
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")
    result = chapter_marker.auto_detect_chapters(
        movie_id, movie.file_path,
        threshold=threshold, min_duration=min_duration,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/{movie_id}/chapters/generate-thumbnails")
async def generate_chapter_thumbnails(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """为所有章节生成缩略图"""
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")
    result = chapter_marker.generate_chapter_thumbnails(movie_id, movie.file_path)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/{movie_id}/chapters/thumbnails/{filename}")
async def serve_chapter_thumbnail(movie_id: int, filename: str):
    """提供章节缩略图"""
    path = chapter_marker.get_chapter_thumbnail_path(movie_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="缩略图不存在")
    return FileResponse(str(path), media_type="image/jpeg")


# ===== 字幕 =====

@router.get("/{movie_id}/subtitles")
async def list_subtitles(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """列出所有可用字幕（内嵌 + 外挂）"""
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")
    result = subtitle_matcher.list_all_subtitles(movie_id, movie.file_path)
    return result


@router.get("/{movie_id}/subtitles/file")
async def serve_subtitle_file(
    movie_id: int,
    path: str = Query(..., description="字幕文件绝对路径"),
    session: AsyncSession = Depends(get_session),
):
    """提供字幕文件内容"""
    movie = await _get_movie(session, movie_id)
    # 安全检查：字幕必须在该影片的可用列表中
    available = subtitle_matcher.find_local_subtitles(movie.file_path or "")
    target_path = Path(path).resolve()
    for sub in available:
        if Path(sub["path"]).resolve() == target_path:
            if not target_path.exists():
                raise HTTPException(status_code=404, detail="字幕文件不存在")
            ext = target_path.suffix.lower()
            media_type_map = {
                ".srt": "application/x-subrip",
                ".ass": "text/plain",
                ".ssa": "text/plain",
                ".vtt": "text/vtt",
                ".sub": "text/plain",
            }
            media_type = media_type_map.get(ext, "application/octet-stream")
            return FileResponse(str(target_path), media_type=media_type)
    raise HTTPException(status_code=404, detail="字幕文件不在可用列表中")


# ===== 播放器配置 =====

@router.get("/{movie_id}/config")
async def get_player_config(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取影片的播放器配置（一次性返回所有元数据，减少前端请求次数）"""
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")

    # 缩略图进度条
    sprite = ffmpeg_thumbnail.get_thumbnail_sprite(movie_id)

    # 章节
    chapters = chapter_marker.load_chapters(movie_id)

    # 字幕
    subtitles = subtitle_matcher.list_all_subtitles(movie_id, movie.file_path)

    # GIF 列表
    gifs = gif_generator.list_gifs(movie_id)

    # 视频流 URL
    play_url = f"/api/v1/movies/{movie_id}/play/file"

    # 音轨列表（v3.5 新增，支持音轨切换）
    audio_tracks = get_audio_tracks_info(movie.file_path)

    return {
        "movie_id": movie_id,
        "play_url": play_url,
        "play_url_external": f"/api/v1/movies/{movie_id}/play/external",
        "hls_master_url": f"/api/v1/movies/{movie_id}/hls/master.m3u8",
        "thumbnail_sprite": sprite,
        "chapters": chapters,
        "subtitles": subtitles,
        "gifs": gifs,
        "audio_tracks": audio_tracks,
        "duration": movie.duration,
        "file_path": movie.file_path,
    }


# ===== 音轨切换（v3.5 新增） =====

def get_audio_tracks_info(file_path: str) -> list[dict]:
    """
    使用 ffprobe 获取视频文件的所有音轨信息

    返回:
        [
            {
                "index": 1,              # 流索引（ffprobe 中的 stream.index）
                "codec": "aac",          # 音频编码
                "channels": 2,           # 声道数
                "channel_layout": "stereo",  # 声道布局
                "language": "jpn",       # 语言标签（如 jpn/chi/eng，可能为 und）
                "title": "日语",          # 轨道标题（部分文件有）
                "default": True,         # 是否默认轨道
                "bitrate": 128000,       # 比特率（bps，可能为 None）
                "sample_rate": 48000,    # 采样率
                "label": "音轨 1 (日语)",  # 显示用标签
            },
            ...
        ]
    """
    import json
    import subprocess
    from app.utils.bin_tools import get_ffprobe_path

    ffprobe = get_ffprobe_path()
    if not os.path.isfile(ffprobe):
        return []

    try:
        cmd = [
            ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "a",  # 仅音频流
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            return []
        info = json.loads(result.stdout)
    except Exception:
        return []

    tracks = []
    for idx, stream in enumerate(info.get("streams", [])):
        tags = stream.get("tags", {}) or {}
        language = tags.get("language", "und") or "und"
        title = tags.get("title", "") or ""
        codec = stream.get("codec_name", "unknown")
        channels = stream.get("channels", 0)
        channel_layout = stream.get("channel_layout", "")
        sample_rate = int(stream.get("sample_rate", 0) or 0)
        bitrate = int(stream.get("bit_rate", 0) or 0) or None
        is_default = stream.get("disposition", {}).get("default", 0) == 1

        # 构建显示标签
        lang_map = {
            "jpn": "日语", "chi": "中文", "eng": "英语",
            "kor": "韩语", "fra": "法语", "deu": "德语",
            "spa": "西班牙语", "ita": "意大利语", "und": "未知",
        }
        lang_label = lang_map.get(language, language)
        title_part = f" - {title}" if title else ""
        label = f"音轨 {idx + 1} ({lang_label}{title_part})"

        tracks.append({
            "index": idx,  # 前端使用的序号（0-based）
            "stream_index": stream.get("index", idx),
            "codec": codec,
            "channels": channels,
            "channel_layout": channel_layout,
            "language": language,
            "title": title,
            "default": is_default,
            "bitrate": bitrate,
            "sample_rate": sample_rate,
            "label": label,
        })

    return tracks


@router.get("/{movie_id}/audio-tracks")
async def list_audio_tracks(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    列出影片所有音轨（v3.5 新增）

    返回音轨列表，前端通过 HLS audioTrack 或 video.audioTracks API 切换。
    - 直接播放（MP4）：浏览器需支持 HTMLAudioTrack API（Chrome/Edge 支持，Firefox 有限）
    - HLS 播放：通过 hls.js 的 audioTrack 切换（推荐）
    """
    movie = await _get_movie(session, movie_id)
    if not movie.file_path:
        raise HTTPException(status_code=400, detail="影片无关联文件")
    tracks = get_audio_tracks_info(movie.file_path)
    return {"movie_id": movie_id, "items": tracks, "count": len(tracks)}


@router.post("/{movie_id}/audio-tracks/{track_index}/switch")
async def switch_audio_track(
    movie_id: int,
    track_index: int,
    session: AsyncSession = Depends(get_session),
):
    """
    记录音轨切换偏好（v3.5 新增）

    实际切换由前端完成：
    - HLS：hls.audioTrack = track_index
    - 直接播放：video.audioTracks[track_index].enabled = true

    后端仅记录用户偏好（可选，持久化到 Movie 元数据）。
    """
    movie = await _get_movie(session, movie_id)
    tracks = get_audio_tracks_info(movie.file_path) if movie.file_path else []
    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(status_code=400, detail=f"音轨索引越界（0-{len(tracks) - 1}）")
    track = tracks[track_index]
    return {
        "movie_id": movie_id,
        "track_index": track_index,
        "track": track,
        "hint": "前端请通过 hls.audioTrack 或 video.audioTracks[track_index].enabled 切换",
    }
