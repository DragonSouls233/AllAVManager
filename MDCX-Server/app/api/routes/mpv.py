"""
mpv 播放器路由

API 端点：
- POST /api/v1/mpv/play/{movie_id}  - 启动 mpv 播放
- GET  /api/v1/mpv/config            - 获取 mpv 配置
- PUT  /api/v1/mpv/config            - 保存 mpv 配置
- GET  /api/v1/mpv/hotkeys           - 获取默认热键列表
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services.mpv_player import (
    DEFAULT_HOTKEYS,
    play_video,
    get_mpv_config,
    save_mpv_config,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class PlayRequest(BaseModel):
    start_time: float = 0
    volume: Optional[int] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None
    on_top: Optional[bool] = None


class SaveConfigRequest(BaseModel):
    hotkeys: Optional[list[dict]] = None
    volume: Optional[int] = None
    on_top: Optional[bool] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None


@router.post("/play/{movie_id}")
async def play_with_mpv(
    movie_id: int,
    req: PlayRequest = Body(default_factory=PlayRequest),
):
    """启动 mpv 播放指定影片"""
    # 合并配置：请求参数 > 数据库配置 > 默认值
    config = await get_mpv_config()

    result = await play_video(
        movie_id=movie_id,
        start_time=req.start_time,
        volume=req.volume if req.volume is not None else config["volume"],
        window_width=req.window_width or config["window_width"],
        window_height=req.window_height or config["window_height"],
        on_top=req.on_top if req.on_top is not None else config["on_top"],
        hotkeys=config["hotkeys"],
    )

    if result["status"] == "error":
        # mpv 未安装 / 文件不存在属于服务不可用,不是服务器内部错误
        code = 503 if "未找到" in result["message"] or "不存在" in result["message"] else 500
        raise HTTPException(status_code=code, detail=result["message"])

    # 更新播放次数
    from app.db.database import get_database
    from app.db.models import Movie
    from datetime import datetime
    db = get_database()
    async with db.session() as session:
        movie = await session.get(Movie, movie_id)
        if movie:
            movie.play_count = (movie.play_count or 0) + 1
            movie.last_played_at = datetime.now()
            await session.commit()

    return result


@router.get("/config")
async def get_config():
    """获取 mpv 配置"""
    config = await get_mpv_config()
    # 检查 mpv 是否安装
    from app.services.mpv_player import _find_mpv
    mpv_path = _find_mpv()
    config["mpv_installed"] = mpv_path is not None
    config["mpv_path"] = mpv_path
    return config


@router.put("/config")
async def update_config(req: SaveConfigRequest):
    """保存 mpv 配置"""
    result = await save_mpv_config(
        hotkeys=req.hotkeys,
        volume=req.volume,
        on_top=req.on_top,
        window_width=req.window_width,
        window_height=req.window_height,
    )
    return result


@router.get("/hotkeys")
async def get_default_hotkeys():
    """获取默认热键列表"""
    return {"hotkeys": DEFAULT_HOTKEYS}
