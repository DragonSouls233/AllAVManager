"""高清版目标服务 /quality-goals

给某部片子设定「想要更高清的版本」，替换文件后由本服务重新探测，
实测分辨率达到目标即自动标记 fulfilled。

设计要点
--------
- 分辨率现场探测用 ffprobe 子进程，必须 ``asyncio.to_thread`` 包一层：
  同步 subprocess 会阻塞整个事件循环，卡住所有 HTTP 请求。
- 探测结果写回 goal 表做快照，前端列表直接读快照，不必每次 ffprobe。
- 目标垂直像素：2160(4K) / 1080 / 720 / 480。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime

from sqlalchemy import select

from app.utils.module_helper import MODULE_MODELS, get_module_model

logger = logging.getLogger(__name__)

# 常见目标档位（垂直像素 -> 标签）
TARGET_PRESETS: list[tuple[int, str]] = [
    (2160, "4K"),
    (1440, "1440p"),
    (1080, "1080p"),
    (720, "720p"),
    (480, "480p"),
]

PROBE_TIMEOUT = 15

_RESOLUTION_CACHE: dict[str, tuple[int, int] | None] = {}


def height_label(h: int | None) -> str:
    """垂直像素 → 可读标签。

    🔴 容差匹配（±5%），不要把 900p 这种非标准值硬降级成 480p —— 那会让用户误判
    手里的文件比实际更差。落不进任何标准档位时如实显示 ``{h}p``。
    """
    if not h:
        return "未知"
    for px, lb in TARGET_PRESETS:
        if abs(h - px) <= px * 0.05:
            return lb
    return f"{h}p"


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()


# ------------------------------------------------------------------
# ffprobe 探测
# ------------------------------------------------------------------

def _probe_sync(file_path: str) -> tuple[int, int] | None:
    """同步探测视频分辨率（在线程里跑，勿直接在协程调用）"""
    from app.utils.bin_tools import get_ffprobe_path

    ffprobe = get_ffprobe_path()
    if not ffprobe or not os.path.isfile(ffprobe):
        logger.warning("[quality_goals] ffprobe 不可用，分辨率探测降级为未知")
        return None
    if not file_path or not os.path.isfile(file_path):
        return None

    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                file_path,
            ],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        out = proc.stdout.strip().splitlines()[0].strip()
        if "x" not in out:
            return None
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except subprocess.TimeoutExpired:
        logger.warning(f"[quality_goals] ffprobe 超时: {file_path}")
        return None
    except Exception as e:
        logger.warning(f"[quality_goals] ffprobe 失败: {type(e).__name__}: {e}")
        return None


async def probe_resolution(file_path: str | None) -> tuple[int, int] | None:
    """异步探测分辨率（子进程丢到线程池，避免阻塞事件循环）"""
    if not file_path:
        return None
    if file_path in _RESOLUTION_CACHE:
        return _RESOLUTION_CACHE[file_path]
    wh = await asyncio.to_thread(_probe_sync, file_path)
    _RESOLUTION_CACHE[file_path] = wh
    return wh


async def find_movie_file(module: str, normalized_code: str) -> tuple[str | None, str | None, int | None]:
    """按番号在模块库里找影片，返回 (file_path, title, movie_id)"""
    Movie = get_module_model(module, "movie")
    from app.utils.module_helper import get_module_session

    session = await get_module_session(module)
    try:
        stmt = select(Movie).where(Movie.code.ilike(normalized_code)).limit(1)
        row = (await session.execute(stmt)).scalars().first()
        if not row:
            # SQLite ILIKE 对非 ASCII 不可靠，回退一次严格相等
            stmt = select(Movie).where(Movie.code == normalized_code).limit(1)
            row = (await session.execute(stmt)).scalars().first()
        if not row:
            return None, None, None
        return row.file_path, row.title, row.id
    except Exception as e:
        logger.warning(f"[quality_goals] 查库失败 {module}/{normalized_code}: {type(e).__name__}: {e}")
        return None, None, None


async def evaluate_goal(goal, session, probe: bool = True) -> dict:
    """评估单个目标是否达成（必要时现场 ffprobe）

    返回 dict 描述当前状态；达成时写回 goal 并 commit。
    """
    file_path = goal.file_path
    title = goal.title

    if probe or not file_path:
        fp, db_title, _mid = await find_movie_file(goal.module, goal.normalized_code)
        if fp:
            file_path = fp
        if db_title:
            title = db_title

    width = height = None
    if probe:
        wh = await probe_resolution(file_path)
        if wh:
            width, height = wh

    if height is None:
        # 探测失败时沿用上次快照，且**不改状态**（避免把 fulfilled 误打回去）
        height = goal.current_height
        width = goal.current_width

    reached = bool(height and height >= goal.target_height)
    now = datetime.utcnow()

    goal.file_path = file_path
    goal.title = title
    goal.current_height = height
    goal.current_width = width
    goal.detected_at = now
    goal.updated_at = now
    if reached and goal.status == "open":
        goal.status = "fulfilled"
        goal.fulfilled_at = now

    return {
        "id": goal.id,
        "module": goal.module,
        "code": goal.code,
        "title": title,
        "target_height": goal.target_height,
        "target_label": height_label(goal.target_height),
        "current_height": height,
        "current_width": width,
        "current_label": height_label(height),
        "file_path": file_path,
        "file_exists": bool(file_path and os.path.isfile(file_path)),
        "status": goal.status,
        "reached": reached,
        "detected_at": now.isoformat(),
        "fulfilled_at": goal.fulfilled_at.isoformat() if goal.fulfilled_at else None,
        "note": goal.note,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
    }


def valid_target(h: int) -> bool:
    return isinstance(h, int) and 0 < h <= 4320
