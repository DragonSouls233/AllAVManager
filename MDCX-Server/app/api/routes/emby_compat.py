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

import importlib
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func, or_

from app.config.manager import get_config, get_config_manager
from app.utils.logger import get_logger
from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS as MODULE_MODEL_REGISTRY

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


# ===== 工具函数 =====

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


async def _find_movie_anywhere(movie_id: int):
    """跨模块查找影片：遍历所有模块数据库

    Returns:
        (movie_obj, module_session, module_name) 元组。
        - module_name 为具体字符串表示模块数据库的对象（如 "jav"）
        - 调用方必须在使用后关闭 module_session
        如果所有库都查不到，返回 (None, None, None)
    """
    from app.db.module_db import ModuleDatabase

    for module_name, (mod_path, movie_cls_name, _) in MODULE_MODEL_REGISTRY.items():
        try:
            mod_db = ModuleDatabase.get_instance(module_name)
            mod_session = await mod_db.get_session()
            mod = importlib.import_module(mod_path)
            movie_cls = getattr(mod, movie_cls_name)

            movie = await mod_session.get(movie_cls, movie_id)
            if movie:
                return movie, mod_session, module_name
            await mod_session.close()
        except Exception as e:
            logger.warning(f"查询模块数据库 [{module_name}] 失败: {e}")
            continue

    return None, None, None


async def _find_actor_anywhere(actor_id: int):
    """跨模块查找演员：遍历所有模块数据库

    Returns:
        (actor_obj, module_session, module_name) 元组
    """
    from app.db.module_db import ModuleDatabase

    for module_name, (mod_path, _, actor_cls_name) in MODULE_MODEL_REGISTRY.items():
        try:
            mod_db = ModuleDatabase.get_instance(module_name)
            mod_session = await mod_db.get_session()
            mod = importlib.import_module(mod_path)
            actor_cls = getattr(mod, actor_cls_name)

            actor = await mod_session.get(actor_cls, actor_id)
            if actor:
                return actor, mod_session, module_name
            await mod_session.close()
        except Exception as e:
            logger.warning(f"查询模块数据库 [{module_name}] 演员失败: {e}")
            continue

    return None, None, None


async def _movie_to_emby_item(
    movie,
    module_name: str,
    base_url: str,
    nsfw_hidden: bool = False,
) -> dict:
    """将模块数据库的 Movie 对象转换为 Emby Item

    模块数据库的影片将 act_info 存储在 movie.actor 字段（逗号分隔），
    片商存储在 movie.studio 字段，系列存储在 movie.series 字段。
    同时支持关联表查询（MovieActor/Actor/Studio/Series）。
    """
    # 从 actor 字段解析演员列表
    actors = []
    if hasattr(movie, 'actor') and movie.actor:
        actors = [a.strip() for a in str(movie.actor).split(",") if a.strip()]

    # 处理 NSFW 模式（隐藏标题）
    name = movie.code
    if not nsfw_hidden and movie.title:
        name = f"[{movie.code}] {movie.title}"

    # 类型
    genres = _parse_genres(getattr(movie, 'genre', None))
    tags = _parse_genres(getattr(movie, 'tag', None))

    # 使用 module_name 作为 Id 前缀避免跨库 ID 冲突
    item_id = f"{module_name}_{movie.id}"

    # 片商名（模块数据库直接存字符串，如 studio 字段）
    studio_name = getattr(movie, 'studio', None)

    # 系列名
    series_name = getattr(movie, 'series', None)

    return {
        "Id": item_id,
        "Name": name,
        "OriginalTitle": getattr(movie, 'original_title', None) or movie.title or movie.code,
        "SortName": movie.code,
        "ForcedSortName": movie.code,
        "Type": "Movie",
        "MediaType": "Video",
        "DateCreated": movie.created_at.isoformat() if getattr(movie, 'created_at', None) else None,
        "Overview": getattr(movie, 'plot', None) or "",
        "ProductionYear": _parse_year(movie.release_date),
        "PremiereDate": movie.release_date,
        "CommunityRating": float(movie.rating) if movie.rating else None,
        "RunTimeTicks": _ticks_from_seconds(getattr(movie, 'duration', None)),
        "Studios": [{"Name": studio_name}] if studio_name else [],
        "Genres": genres,
        "Tags": tags,
        "People": [
            {"Name": name, "Type": "Actor", "Role": "Actor"}
            for name in actors
        ],
        "Path": getattr(movie, 'file_path', None) or f"/movies/{item_id}",
        "ImageTags": {"Primary": "primary"} if (getattr(movie, 'cover_url', None) or getattr(movie, 'poster_url', None)) else {},
        "BackdropImageTags": ["backdrop"] if getattr(movie, 'cover_url', None) else [],
        "UserData": {
            "Played": movie.play_count > 0 if hasattr(movie, 'play_count') else False,
            "PlayCount": getattr(movie, 'play_count', 0),
            "IsFavorite": False,
            "Key": item_id,
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

    if not req.Username:
        raise HTTPException(status_code=400, detail="Username 不能为空")

    if not cfg.api_key:
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
    StartIndex: int = Query(0, ge=0),
    Limit: int = Query(100, ge=1, le=500),
    ParentId: Optional[str] = None,
    IncludeItemTypes: Optional[str] = None,
    SearchTerm: Optional[str] = None,
    SortBy: Optional[str] = None,
    SortOrder: Optional[str] = "Ascending",
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """用户媒体库列表（单模块查询）"""
    cfg = get_config().emby_compat
    base_url = str(request.base_url).rstrip("/")

    movie_cls = get_module_model(module, "movie")

    sess = await get_module_session(module)
    async with sess:
        query = select(movie_cls)

        if SearchTerm:
            kw = f"%{SearchTerm}%"
            query = query.where(
                or_(
                    movie_cls.code.like(kw),
                    movie_cls.title.like(kw),
                    movie_cls.original_title.like(kw),
                )
            )

        query = query.where(movie_cls.file_path.isnot(None))

        if SortBy:
            sort_map = {
                "SortName": movie_cls.code,
                "Name": movie_cls.code,
                "DateCreated": movie_cls.created_at,
                "PremiereDate": movie_cls.release_date,
                "CommunityRating": movie_cls.rating,
            }
            sort_col = sort_map.get(SortBy, movie_cls.id)
            if SortOrder == "Descending":
                query = query.order_by(sort_col.desc())
            else:
                query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(movie_cls.id.desc())

        count_query = select(func.count(movie_cls.id)).where(movie_cls.file_path.isnot(None))
        if SearchTerm:
            kw = f"%{SearchTerm}%"
            count_query = count_query.where(
                or_(
                    movie_cls.code.like(kw),
                    movie_cls.title.like(kw),
                    movie_cls.original_title.like(kw),
                )
            )
        total_result = await sess.execute(count_query)
        total = total_result.scalar() or 0

        query = query.offset(StartIndex).limit(Limit)
        result = await sess.execute(query)
        movies = result.scalars().all()

    items = [
        await _movie_to_emby_item(m, module, base_url, cfg.nsfw_hidden)
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
):
    """单个媒体项详情（支持跨模块查询）"""
    base_url = str(request.base_url).rstrip("/")
    cfg = get_config().emby_compat

    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的 Item ID")

    movie, mod_session, module_name = await _find_movie_anywhere(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    try:
        return await _movie_to_emby_item(movie, module_name, base_url, cfg.nsfw_hidden)
    finally:
        await mod_session.close()


# ===== Items 通用端点 =====

@router.get("/Items")
async def list_items(
    request: Request,
    StartIndex: int = Query(0, ge=0),
    Limit: int = Query(100, ge=1, le=500),
    SearchTerm: Optional[str] = None,
    IncludeItemTypes: Optional[str] = None,
    module: str = Query("jav", description="模块名：jav/fc2/uncensored/chinese/western/pornhub"),
):
    """通用 Items 查询"""
    return await get_user_items(VIRTUAL_USER_ID, request, StartIndex, Limit, None, IncludeItemTypes, SearchTerm, module=module)


@router.get("/Items/{item_id}")
async def get_item(
    item_id: str,
    request: Request,
):
    """单个 Item 详情"""
    return await get_user_item(VIRTUAL_USER_ID, item_id, request)


@router.get("/Items/{item_id}/Images/{image_type}")
async def get_item_image(
    item_id: str,
    image_type: str,
    max_width: Optional[int] = None,
):
    """获取媒体图片（重定向到 MDCX 的 cover/poster URL，支持跨模块查询）"""
    try:
        movie_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的 Item ID")

    movie, mod_session, module_name = await _find_movie_anywhere(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    cover_url = getattr(movie, 'cover_url', None)
    poster_url = getattr(movie, 'poster_url', None)
    thumb_url = getattr(movie, 'thumb_url', None)

    if image_type == "Backdrop":
        url = cover_url
    elif image_type == "Thumb":
        url = thumb_url or cover_url
    else:
        url = poster_url or cover_url

    if module_name is not None:
        await mod_session.close()

    if not url:
        transparent_png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63000100000005000100c0e9080a0000000049454e44ae426082"
        )
        return Response(content=transparent_png, media_type="image/png")

    if not url.startswith("http"):
        cfg = get_config()
        local_path = os.path.join(cfg.scraper.output_dir, url) if not os.path.isabs(url) else url
        if os.path.exists(local_path):
            return FileResponse(local_path)

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
    silent_wav = (
        b"RIFF"
        + struct.pack("<I", 36)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)
        + struct.pack("<H", 1)
        + struct.pack("<I", 8000)
        + struct.pack("<I", 8000)
        + struct.pack("<H", 1)
        + struct.pack("<H", 8)
        + b"data"
        + struct.pack("<I", 0)
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
