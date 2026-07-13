"""Emby 协议兼容路由

参考 MediaStationGo 的 Emby 兼容实现，让 MDCX 服务器被 Infuse/VidHub/SenPlayer/Fileball 等
Emby 客户端识别为标准 Emby 服务器。

实现的端点：
- GET  /emby/System/Info/Public          服务器公共信息（无认证）
- GET  /emby/System/Info                 服务器详细信息
- GET  /emby/Users/Public                公共用户列表
- POST /emby/Users/AuthenticateByName    用户名密码认证（返回 API Key）
- GET  /emby/Users/{userId}              用户详情
- GET  /emby/Users/{userId}/Items        用户媒体库
- GET  /emby/Users/{userId}/Items/{id}   单个媒体项
- GET  /emby/Items                       所有项（搜索）
- GET  /emby/Items/{id}                  单个项详情
- GET  /emby/Items/{id}/Images/Primary   主图（重定向到 cover URL）
- GET  /emby/Items/{id}/Images/Backdrop  背景图
- GET  /emby/Videos/{id}/stream          视频流（重定向到 play/external）
- GET  /emby/Videos/{id}/stream.m3u8     HLS 流（重定向）

挂在 /emby 路径下，不走 /api/v1 前缀，认证由 AuthMiddleware._check_emby_auth 处理。
"""

import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, get_config_manager
from app.db.database import get_session
from app.db.models import Movie, Actor, MovieActor, Studio, Series
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 固定的虚拟用户 ID（MDCX 是单用户系统，但 Emby 协议要求用户 ID）
VIRTUAL_USER_ID = "a00000000000000000000000000000000"
VIRTUAL_USER_NAME = "admin"


# ===== 数据模型 =====

class EmbyAuthRequest(BaseModel):
    """Emby 认证请求"""
    Username: str
    Pw: str = ""


class EmbyItem(BaseModel):
    """Emby 媒体项"""
    Id: str
    Name: str
    Type: str  # Movie / Series / Episode
    MediaType: str  # Video
    DateCreated: Optional[str] = None
    Overview: Optional[str] = None
    ProductionYear: Optional[int] = None
    PremiereDate: Optional[str] = None
    CommunityRating: Optional[float] = None
    RunTimeTicks: Optional[int] = None  # 100ns 单位
    Studios: list = []
    Genres: list = []
    Tags: list = []
    People: list = []  # 演员
    Path: Optional[str] = None
    ImageTags: dict = {}
    BackdropImageTags: list = []
    UserData: dict = {}


def _ticks_from_seconds(seconds: Optional[int]) -> Optional[int]:
    """秒 -> Emby Ticks（100ns 单位）"""
    if not seconds:
        return None
    return int(seconds) * 10_000_000


def _parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def _parse_genres(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    import json
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [raw]
    except Exception:
        return [g.strip() for g in str(raw).split(",") if g.strip()]


async def _movie_to_emby_item(
    movie: Movie,
    session: AsyncSession,
    base_url: str,
    nsfw_hidden: bool = False,
) -> dict:
    """将 Movie 对象转换为 Emby Item"""
    # 查询演员
    actors_result = await session.execute(
        select(Actor.name)
        .join(MovieActor, MovieActor.actor_id == Actor.id)
        .where(MovieActor.movie_id == movie.id)
        .limit(20)
    )
    actors = [r[0] for r in actors_result.fetchall()]

    # 查询片商
    studio_name = None
    if movie.studio_id:
        studio_obj = await session.get(Studio, movie.studio_id)
        studio_name = studio_obj.name if studio_obj else None

    # 查询系列
    series_name = None
    if movie.series_id:
        series_obj = await session.get(Series, movie.series_id)
        series_name = series_obj.name if series_obj else None

    # 处理 NSFW 模式（隐藏标题）
    name = movie.code
    if not nsfw_hidden and movie.title:
        name = f"[{movie.code}] {movie.title}"

    # 类型
    genres = _parse_genres(movie.genre)
    tags = _parse_genres(movie.tag)

    return {
        "Id": str(movie.id),
        "Name": name,
        "OriginalTitle": movie.original_title or movie.title or movie.code,
        "SortName": movie.code,
        "ForcedSortName": movie.code,
        "Type": "Movie",
        "MediaType": "Video",
        "DateCreated": movie.created_at.isoformat() if movie.created_at else None,
        "Overview": movie.plot or "",
        "ProductionYear": _parse_year(movie.release_date),
        "PremiereDate": movie.release_date,
        "CommunityRating": float(movie.rating) if movie.rating else None,
        "RunTimeTicks": _ticks_from_seconds(movie.duration),
        "Studios": [{"Name": studio_name}] if studio_name else [],
        "Genres": genres,
        "Tags": tags,
        "People": [
            {"Name": name, "Type": "Actor", "Role": "Actor"}
            for name in actors
        ],
        "Path": movie.file_path or f"/movies/{movie.id}",
        "ImageTags": {"Primary": "primary"} if movie.cover_url or movie.poster_url else {},
        "BackdropImageTags": ["backdrop"] if movie.cover_url else [],
        "UserData": {
            "Played": movie.play_count > 0,
            "PlayCount": movie.play_count,
            "IsFavorite": False,
            "Key": str(movie.id),
        },
        "ProviderIds": {"Imdb": movie.code},
        "Taglines": [series_name] if series_name else [],
    }


# ===== 系统信息端点 =====

@router.get("/System/Info/Public")
async def system_info_public():
    """服务器公共信息（无认证）"""
    cfg = get_config().emby_compat
    return {
        "ServerName": cfg.server_name,
        "Version": cfg.version,
        "Id": "mdcx-emby-server",
        "OperatingSystem": "Linux",
        "OperatingSystemDisplayName": "Linux",
        "CanSelfRestart": False,
        "CanLaunchWebBrowser": False,
        "HasPendingRestart": False,
        "IsShuttingDown": False,
        "SupportsLibraryMonitor": False,
        "WebSocketPortNumber": get_config().server.port,
        "InstallCompleted": True,
        "Extensions": [],
    }


@router.get("/System/Info")
async def system_info():
    """服务器详细信息"""
    cfg = get_config().emby_compat
    public = await system_info_public()
    public.update({
        "LocalAddress": f"http://localhost:{get_config().server.port}",
        "HttpServerPortNumber": get_config().server.port,
        "WanAddress": "0.0.0.0",
        "OperatingSystem": "Linux",
    })
    return public


# ===== 用户端点 =====

@router.get("/Users/Public")
async def users_public():
    """公共用户列表"""
    return [
        {
            "Name": VIRTUAL_USER_NAME,
            "Id": VIRTUAL_USER_ID,
            "HasPassword": False,
            "HasConfiguredPassword": False,
            "EnableAutoLogin": True,
            "PrimaryImageTag": None,
        }
    ]


@router.post("/Users/AuthenticateByName")
async def authenticate_by_name(req: EmbyAuthRequest):
    """用户名密码认证，返回 API Key"""
    cfg = get_config().emby_compat
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="Emby 协议兼容未启用")

    # 简单校验：MDCX 是单用户系统，username=admin 即放行（密码可空）
    # 严格场景下可校验 MDCX 的 Bearer Token
    if not req.Username:
        raise HTTPException(status_code=400, detail="Username 不能为空")

    # 生成或返回 API Key
    if not cfg.api_key:
        # 自动生成
        cm = get_config_manager()
        cm.config.emby_compat.api_key = secrets.token_hex(16)
        cm.save()
        cfg = get_config().emby_compat

    return {
        "User": {
            "Name": req.Username,
            "Id": VIRTUAL_USER_ID,
            "HasPassword": False,
            "Configuration": {
                "EnableLocalPassword": False,
                "HidePlayedInLatest": True,
                "EnableNextEpisodeAutoPlay": True,
            },
            "Policy": {
                "IsAdministrator": True,
                "IsHidden": False,
                "IsDisabled": False,
                "EnabledFolders": [],
                "EnableUserPreferenceAccess": True,
                "EnableMediaPlayback": True,
                "EnableAudioPlaybackTranscoding": True,
                "EnableVideoPlaybackTranscoding": True,
                "EnableSubtitleManagement": False,
                "EnableContentDeletion": False,
                "EnableContentDownloading": True,
            },
        },
        "SessionInfo": {
            "UserId": VIRTUAL_USER_ID,
            "UserName": req.Username,
            "DeviceId": "mdcx-emby-client",
            "DeviceName": "MDCX Emby Client",
            "Client": "MDCX",
            "ApplicationVersion": cfg.version,
            "IsActive": True,
        },
        "AccessToken": cfg.api_key,
        "ServerId": "mdcx-emby-server",
    }


@router.get("/Users/{user_id}")
async def get_user(user_id: str):
    """获取用户详情"""
    return {
        "Name": VIRTUAL_USER_NAME,
        "Id": VIRTUAL_USER_ID,
        "HasPassword": False,
        "Configuration": {
            "HidePlayedInLatest": True,
            "EnableNextEpisodeAutoPlay": True,
        },
        "Policy": {
            "IsAdministrator": True,
            "IsHidden": False,
            "IsDisabled": False,
            "EnableMediaPlayback": True,
        },
        "PrimaryImageTag": None,
    }


@router.get("/Users/{user_id}/Views")
async def get_user_views(user_id: str):
    """用户媒体库视图"""
    return {
        "Items": [
            {
                "Id": "movies",
                "Name": "电影",
                "Type": "CollectionFolder",
                "MediaType": "Video",
                "CollectionType": "movies",
                "ImageTags": {},
            }
        ],
        "TotalRecordCount": 1,
    }


@router.get("/Users/{user_id}/Items")
async def get_user_items(
    user_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    StartIndex: int = Query(0, ge=0),
    Limit: int = Query(100, ge=1, le=500),
    ParentId: Optional[str] = None,
    IncludeItemTypes: Optional[str] = None,
    SearchTerm: Optional[str] = None,
    SortBy: Optional[str] = None,
    SortOrder: Optional[str] = "Ascending",
):
    """用户媒体库列表"""
    cfg = get_config().emby_compat
    base_url = str(request.base_url).rstrip("/")

    query = select(Movie)

    # NSFW 模式：仅显示已收藏的影片（这里简化为不筛选）
    # 实际可结合 FavoriteItem 表

    # 搜索
    if SearchTerm:
        kw = f"%{SearchTerm}%"
        query = query.where(
            or_(
                Movie.code.like(kw),
                Movie.title.like(kw),
                Movie.original_title.like(kw),
            )
        )

    # 仅展示有文件的影片
    query = query.where(Movie.file_path.isnot(None))

    # 排序
    if SortBy:
        sort_map = {
            "SortName": Movie.code,
            "Name": Movie.code,
            "DateCreated": Movie.created_at,
            "PremiereDate": Movie.release_date,
            "CommunityRating": Movie.rating,
        }
        sort_col = sort_map.get(SortBy, Movie.id)
        if SortOrder == "Descending":
            query = query.order_by(sort_col.desc())
        else:
            query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(Movie.id.desc())

    # 总数
    count_query = select(func.count(Movie.id)).where(Movie.file_path.isnot(None))
    if SearchTerm:
        kw = f"%{SearchTerm}%"
        count_query = count_query.where(
            or_(
                Movie.code.like(kw),
                Movie.title.like(kw),
                Movie.original_title.like(kw),
            )
        )
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # 分页
    query = query.offset(StartIndex).limit(Limit)
    result = await session.execute(query)
    movies = result.scalars().all()

    items = [
        await _movie_to_emby_item(m, session, base_url, cfg.nsfw_hidden)
        for m in movies
    ]

    return {
        "Items": items,
        "TotalRecordCount": total,
        "StartIndex": StartIndex,
    }


@router.get("/Users/{user_id}/Items/{item_id}")
async def get_user_item(
    user_id: str,
    item_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """单个媒体项详情"""
    base_url = str(request.base_url).rstrip("/")
    cfg = get_config().emby_compat

    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的 Item ID")

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    return await _movie_to_emby_item(movie, session, base_url, cfg.nsfw_hidden)


# ===== Items 通用端点 =====

@router.get("/Items")
async def list_items(
    request: Request,
    session: AsyncSession = Depends(get_session),
    StartIndex: int = Query(0, ge=0),
    Limit: int = Query(100, ge=1, le=500),
    SearchTerm: Optional[str] = None,
    IncludeItemTypes: Optional[str] = None,
):
    """通用 Items 查询"""
    return await get_user_items(VIRTUAL_USER_ID, request, session, StartIndex, Limit, None, IncludeItemTypes, SearchTerm)


@router.get("/Items/{item_id}")
async def get_item(
    item_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """单个 Item 详情"""
    return await get_user_item(VIRTUAL_USER_ID, item_id, request, session)


@router.get("/Items/{item_id}/Images/{image_type}")
async def get_item_image(
    item_id: str,
    image_type: str,  # Primary / Backdrop / Thumb / Logo
    session: AsyncSession = Depends(get_session),
    max_width: Optional[int] = None,
):
    """获取媒体图片（重定向到 MDCX 的 cover/poster URL）"""
    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的 Item ID")

    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    # Primary 用海报，Backdrop 用封面
    if image_type == "Backdrop":
        url = movie.cover_url
    elif image_type == "Thumb":
        url = movie.thumb_url or movie.cover_url
    else:
        url = movie.poster_url or movie.cover_url

    if not url:
        # 返回 1x1 透明 PNG
        transparent_png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63000100000005000100c0e9080a0000000049454e44ae426082"
        )
        return Response(content=transparent_png, media_type="image/png")

    # 如果是本地路径
    if not url.startswith("http"):
        cfg = get_config()
        local_path = os.path.join(cfg.scraper.output_dir, url) if not os.path.isabs(url) else url
        if os.path.exists(local_path):
            return FileResponse(local_path)

    # 远程 URL 重定向
    return RedirectResponse(url=url)


# ===== 视频流端点 =====

@router.get("/Videos/{item_id}/stream")
async def stream_video(item_id: str, request: Request):
    """视频流（重定向到 MDCX 的播放端点）"""
    base_url = str(request.base_url).rstrip("/")
    target = f"{base_url}/api/v1/movies/{item_id}/play/external"
    return RedirectResponse(url=target)


@router.get("/Videos/{item_id}/stream.{ext}")
async def stream_video_with_ext(item_id: str, ext: str, request: Request):
    """带扩展名的视频流（HLS/MP4 等）"""
    base_url = str(request.base_url).rstrip("/")
    target = f"{base_url}/api/v1/movies/{item_id}/play/external"
    return RedirectResponse(url=target)


@router.get("/Videos/{item_id}/original.{ext}")
async def original_video(item_id: str, ext: str, request: Request):
    """原始视频流"""
    return await stream_video(item_id, request)


@router.get("/Audio/{item_id}/stream")
async def stream_audio(item_id: str, request: Request):
    """音频流（v3.8 改进：返回静音 WAV 提升兼容性）

    MDCX 无独立音频库,但部分 Emby 客户端在扫描/播放时会请求音频流。
    旧版直接返回 404 会导致客户端报错。v3.8 改为返回 44 字节的静音 WAV
    (8kHz 单声道 8-bit PCM,时长 0 秒),客户端可正常打开但无声音。
    """
    import struct
    # 构造 44 字节的静音 WAV 头(PCM 8kHz mono 8-bit,数据长度 0)
    silent_wav = (
        b"RIFF"
        + struct.pack("<I", 36)  # chunk size = 36 (file size - 8)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)  # fmt chunk size
        + struct.pack("<H", 1)   # audio format = PCM
        + struct.pack("<H", 1)   # num channels = 1
        + struct.pack("<I", 8000)  # sample rate = 8000
        + struct.pack("<I", 8000)  # byte rate = 8000
        + struct.pack("<H", 1)   # block align = 1
        + struct.pack("<H", 8)   # bits per sample = 8
        + b"data"
        + struct.pack("<I", 0)   # data size = 0
    )
    return Response(
        content=silent_wav,
        media_type="audio/wav",
        headers={"Content-Length": str(len(silent_wav)), "Accept-Ranges": "none"},
    )


# ===== 配置端点 =====

@router.get("/System/Configuration")
async def get_system_configuration():
    """系统配置（Emby 客户端会请求）"""
    return {
        "EnableCaseSensitiveItemIds": False,
        "EnableLibraryMonitor": False,
        "EnableDateLastRefresh": False,
        "MetadataPath": "",
        "PreferredMetadataLanguage": "zh",
        "MetadataCountryCode": "cn",
        "SortReplaceCharacters": [],
        "SortRemoveCharacters": [],
        "SortRemoveWords": [],
        "MinResumePct": 5,
        "MaxResumePct": 90,
        "MinResumeDurationSeconds": 300,
        "EnableAutomaticRestart": False,
        "EnableLiveTvAccess": False,
        "EnableChannelContentDeletion": False,
        "EnableContentDeletion": False,
        "EnableContentDownloading": True,
        "EnableSubtitleManagement": False,
        "PathSubstitutions": [],
    }


@router.get("/web/System/Info/Public")
async def web_system_info_public():
    """Web 端点（Emby Web UI 的兼容路径）"""
    return await system_info_public()


@router.get("/DisplayPreferences/usersettings")
async def display_preferences():
    """显示偏好设置"""
    return {
        "Id": "usersettings",
        "UserId": VIRTUAL_USER_ID,
        "Client": "emby",
        "ShowSidebar": True,
        "ShowBackdrop": True,
        "ScrollDirection": "Horizontal",
        "DashboardLayout": "",
        "HomeLayout": "",
        "TvGuideLayout": "",
        "SkipForwardLength": 30000,
        "SkipBackwardLength": 15000,
        "EnableNextVideoInfoOverlay": True,
        "EnableThemeSongs": False,
        "EnableThemeVideos": False,
        "EnableBlurHash": True,
        "EnableBackdrops": True,
        "DetailViewType": "Detailed",
    }


@router.get("/Sessions/Capabilities/Full")
async def sessions_capabilities():
    """客户端能力查询"""
    return {
        "SupportsMediaControl": False,
        "SupportsPersistentIdentifier": False,
        "SupportsSync": False,
        "PlayableMediaTypes": ["Video"],
        "SupportedCommands": [],
    }


@router.get("/Branding/Configuration")
async def branding_configuration():
    """品牌配置"""
    cfg = get_config().emby_compat
    return {
        "LoginDisclaimer": "MDCX Emby Protocol Compat",
        "CustomCss": "",
        "SplashscreenEnabled": False,
        "LoginDisclaimer2": "",
    }
