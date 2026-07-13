"""
302 反代播放路由

将网盘视频(CloudDrive2 / 115)通过 302 重定向到直链,
不消耗服务器带宽;本地文件回退到本地流媒体端点。

挂载在 /api/v1/proxy-play。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Movie
from app.services.proxy_player import proxy_player_service

router = APIRouter()


@router.get("/{movie_id}")
async def proxy_play(
    movie_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """302 重定向到影片直链(网盘视频不消耗服务器带宽)"""
    url = await proxy_player_service.get_play_url(movie_id, session)

    if not url:
        # 本地文件:回退到本地流媒体端点
        movie = await session.get(Movie, movie_id)
        if movie and movie.file_path:
            base = str(request.base_url).rstrip("/")
            url = f"{base}/api/v1/movies/{movie_id}/play/file"
        else:
            raise HTTPException(status_code=404, detail="影片不存在或无可播放文件")

    return RedirectResponse(url=url, status_code=302)


@router.get("/{movie_id}/info")
async def proxy_play_info(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取播放信息(不重定向,返回 JSON)

    前端可先调用此接口判断是否需要走 302 重定向,
    避免直接请求 /proxy-play/{id} 时被浏览器视为下载。
    """
    url = await proxy_player_service.get_play_url(movie_id, session)
    return {
        "movie_id": movie_id,
        "play_url": url,
        "is_redirect": url is not None,
    }
