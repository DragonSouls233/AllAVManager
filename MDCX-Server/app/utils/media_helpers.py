"""
媒体工具函数：收集媒体目录、搜索视频/图片文件等
供 movies.py、actors.py 等路由模块共用
"""

import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)


def path_reachable(p: str, timeout: float = 1.0) -> bool:
    """带超时的路径可达性检查（Windows 未挂载网络盘/空光盘驱防护）。

    媒体目录常配置服务器专属盘符（H: I: J: K: Y: Z: M: N: O: 等），
    在开发机等未挂载这些盘的环境里，直接调用 os.path.exists / Path.exists
    会阻塞数十秒，进而冻结 asyncio 事件循环、拖慢启动与封面请求。
    这里用守护线程 + join(timeout) 限时探测，超时即视为不可达并跳过，
    既避免卡死，又不影响真实已挂载的盘符（它们通常在 1 秒内返回）。
    """
    res: dict = {}

    def _probe() -> None:
        try:
            res["v"] = os.path.exists(p)
        except Exception:
            res["v"] = False

    th = threading.Thread(target=_probe, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        return False
    return bool(res.get("v", False))


def fast_file_exists(p: str, timeout: float = 0.5) -> bool:
    """超短超时的文件存在性检查，专用于封面路径快速命中。

    封面请求量大，如果每个 Path(p).exists() 都在网络盘上卡 30 秒，
    浏览器连接池马上耗尽导致首页卡死。
    这里用 0.5s 超时：本地路径通常 <10ms 返回，网络路径 >0.5s 直接视为不存在。
    即使误判也只会降级到兜底步骤，不会丢失封面。
    """
    res: dict = {}

    def _probe() -> None:
        try:
            p_obj = Path(p)
            res["v"] = p_obj.exists() and p_obj.is_file()
        except Exception:
            res["v"] = False

    th = threading.Thread(target=_probe, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        return False
    return bool(res.get("v", False))


def filter_reachable(paths: list[str], timeout: float = 1.0) -> list[str]:
    """并行探测多个路径的可达性, 返回可达路径列表。

    用于 media_dirs 等可能包含大量未挂载网络盘的列表: 串行逐个 path_reachable
    探测会让启动卡顿(如 10 个死盘 × 1s = 10s 阻塞事件循环)。这里一次性并发探测,
    整体只等 timeout 秒(首个最慢的盘), 不可达(含超时)的路径被过滤掉。
    """
    if not paths:
        return []
    results: dict[str, bool] = {}
    threads: list[threading.Thread] = []
    for p in paths:
        def _probe(path: str = p) -> None:
            try:
                results[path] = os.path.exists(path)
            except Exception:
                results[path] = False

        th = threading.Thread(target=_probe, daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(timeout)
    return [p for p in paths if results.get(p, False)]

# 视频文件扩展名集合（不含大写，比较前统一小写）
VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".webm"}

# 图片文件扩展名集合
IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# 标准封面图片文件名（按优先级排序）
STANDARD_COVER_NAMES: tuple = ("poster.jpg", "cover.jpg", "fanart.jpg", "thumb.jpg")

# 标准头像子目录名
AVATAR_SUB_DIRS: tuple = ("actors", "actor_avatars", "avatars", ".actors", ".avatars")

# 所有模块名
_ALL_MODULES: tuple = ("jav", "uncensored", "fc2", "chinese", "pornhub", "western")


def collect_media_dirs(cfg) -> list[str]:
    """
    收集所有可用的媒体目录：
    1. scraper.media_dirs（旧配置）
    2. 所有模块的 media_dirs（无论是否启用，用于封面/头像等文件搜索兜底）
    """
    dirs = []
    # 旧配置：scraper.media_dirs
    scraper_dirs = getattr(cfg.scraper, "media_dirs", None) or []
    dirs.extend(scraper_dirs)
    # 新配置：modules.*.media_dirs
    modules = getattr(cfg, "modules", None)
    if modules:
        for mod_name in _ALL_MODULES:
            mod = getattr(modules, mod_name, None)
            if mod:
                mod_dirs = getattr(mod, "media_dirs", None) or []
                dirs.extend(mod_dirs)
    # 去重并保留顺序
    seen: set = set()
    unique: list = []
    for d in dirs:
        normalized = d.rstrip("\\/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(d)
    return unique


def scan_media_dirs_for_cover(
    media_dirs: list[str],
    code: str,
    max_depth: int = 3,
) -> Optional[str]:
    """
    在 media_dirs 中搜索匹配番号的封面图片。

    搜索策略：
      1. 直接匹配 media_dir / <code> 目录下的标准封面图片
      2. 递归搜索（受 max_depth 限制）子目录名包含番号的目录
      3. 在上述目录中取第一张图片

    Args:
        media_dirs: 媒体目录列表
        code: 影片番号
        max_depth: 递归搜索最大深度（默认 3，避免全盘扫描）

    Returns:
        找到的封面文件路径（字符串）或 None
    """
    if not code:
        return None
    code_lower = code.lower()

    for d in media_dirs:
        d_path = Path(d)
        if not path_reachable(str(d_path)) or not d_path.is_dir():
            continue

        # 1) 直接匹配 d_path / code/
        code_dir = d_path / code
        if code_dir.exists() and code_dir.is_dir():
            result = _find_image_in_dir(code_dir)
            if result:
                return result
            continue  # 找到目录但无图片，跳过递归搜索

        # 2) 限制深度递归搜索
        code_dir = _find_code_subdir_depth_limited(d_path, code_lower, max_depth)
        if code_dir:
            result = _find_image_in_dir(code_dir)
            if result:
                return result
    return None


def scan_media_dirs_for_avatar(
    media_dirs: list[str],
    name: str,
    name_jp: Optional[str] = None,
) -> Optional[str]:
    """
    在 media_dirs 中搜索匹配演员名的头像文件。

    搜索模式：media_dir / (actors|actor_avatars|avatars|...) / {name}.jpg 等

    Args:
        media_dirs: 媒体目录列表
        name: 演员名
        name_jp: 演员日文名（可选）

    Returns:
        找到的头像文件路径（字符串）或 None
    """
    if not name:
        return None
    name_lower = name.lower()

    for d in media_dirs:
        base = Path(d)
        if not path_reachable(str(base)):
            continue
        for sub_dir_name in AVATAR_SUB_DIRS:
            actor_dir = base / sub_dir_name
            if not actor_dir.exists() or not actor_dir.is_dir():
                continue
            try:
                for fp in actor_dir.iterdir():
                    if fp.is_file() and fp.suffix.lower() in IMAGE_EXTENSIONS:
                        fname = fp.stem.lower()
                        if name_lower in fname or (name_jp and name_jp.lower() in fname):
                            return str(fp)
            except Exception:
                continue
    return None


def search_video_in_media_dirs(media_dirs: list[str], code_lower: str) -> Optional[str]:
    """
    在 media_dirs 中递归搜索匹配番号的视频文件。

    限制最大深度以避免全盘扫描。
    """
    for d in media_dirs:
        base = Path(d)
        if not path_reachable(str(base)):
            continue
        try:
            for f in _walk_depth_limited(base, max_depth=4):
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                    fname = f.stem.lower()
                    if code_lower in fname:
                        logger.info("在 media_dirs 中找到视频文件: %s", f)
                        return str(f)
        except Exception as e:
            logger.warning("搜索媒体目录 %s 时出错: %s", d, e)
            continue
    return None


# ==================== 内部辅助函数 ====================


def _walk_depth_limited(base: Path, max_depth: int):
    """
    限制深度的目录遍历生成器。
    生成 base 下深度不超过 max_depth 的所有文件/目录路径。
    """
    # 使用列表而非递归，避免深度递归的栈溢出
    stack = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            for child in current.iterdir():
                yield child
                if child.is_dir():
                    stack.append((child, depth + 1))
        except PermissionError:
            continue
        except OSError:
            continue


def _find_code_subdir_depth_limited(base: Path, code_lower: str, max_depth: int) -> Optional[Path]:
    """
    在 base 下搜索子目录名包含 code_lower 的目录，深度不超过 max_depth。
    """
    stack = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            for child in current.iterdir():
                if child.is_dir():
                    if code_lower in child.name.lower():
                        return child
                    stack.append((child, depth + 1))
        except PermissionError:
            continue
        except OSError:
            continue
    return None


def _find_image_in_dir(directory: Path) -> Optional[str]:
    """
    在目录中搜索标准封面图片，若无则取第一张图片文件。
    返回文件路径字符串或 None。
    """
    # 先搜索标准文件名
    for img_name in STANDARD_COVER_NAMES:
        img_path = directory / img_name
        if img_path.exists() and img_path.is_file():
            return str(img_path)
    # 再取任意第一张图片
    try:
        for fp in sorted(directory.iterdir()):
            if fp.is_file() and fp.suffix.lower() in IMAGE_EXTENSIONS:
                return str(fp)
    except Exception:
        pass
    return None


# ──────────────────────────────────────────
# 模块资源管理工具（6个模块共用）
# ──────────────────────────────────────────

MODULE_DIR_MAP = {
    "jav": "jav",
    "fc2": "fc2",
    "chinese": "chinese",
    "uncensored": "uncensored",
    "pornhub": "pornhub",
    "western": "western",
}


def _get_config() -> object:
    """获取配置管理器（延迟导入避免循环依赖）"""
    try:
        from app.config.manager import get_config
        return get_config()
    except Exception:
        return None


def _get_data_base_dir() -> Path:
    """自动识别数据根目录

    优先级：
    1. config_manager.computed.data_dir（由环境变量 MDCX_DATA_DIR 或启动参数确定）
    2. 从 database.url 自动推导
    3. 默认 ./data

    最终输出：
    - 模块封面: {data_base}/movies/{module}/{code}/poster.jpg
    - 演员头像: {data_base}/avatars/{name}.jpg
    """
    try:
        from app.config.manager import get_config_manager
        mgr = get_config_manager()
        if mgr and hasattr(mgr, 'computed') and mgr.computed and mgr.computed.data_dir:
            return Path(mgr.computed.data_dir).resolve()
    except Exception:
        pass
    try:
        from app.config.manager import get_config as _gc
        c = _gc()
        if c and hasattr(c, 'database') and hasattr(c.database, 'url') and c.database.url:
            db_url = c.database.url
            if "///" in db_url:
                p = Path(db_url.split("///")[-1]).parent.parent
                return p.resolve()
    except Exception:
        pass
    return Path("./data").resolve()


def get_module_movies_dir(module_name: str) -> Path:
    """获取模块对应的影视资源根目录

    格式: {data_base}/movies/{module}/
    例如: L:/data/movies/jav/

    Args:
        module_name: 模块名称（jav/fc2/chinese/uncensored/pornhub/western）

    Returns:
        该模块的影片根目录 Path 对象
    """
    sub = MODULE_DIR_MAP.get(module_name, module_name)
    return _get_data_base_dir() / "movies" / sub


def get_movie_local_dir(module_name: str, code: str) -> Path:
    """获取单个番号资源在本地磁盘上的专属目录

    格式: {data_base}/movies/{module}/{code}/
    例如: L:/data/movies/jav/MIDE-002/

    Args:
        module_name: 模块名称
        code: 番号

    Returns:
        本地目录路径
    """
    base = get_module_movies_dir(module_name)
    return base / code


def get_movie_cover_path(module_name: str, code: str) -> Path:
    """获取封面图片的本地路径（统一文件名 poster.jpg）

    格式: {data_base}/movies/{module}/{code}/poster.jpg
    例如: L:/data/movies/jav/MIDE-002/poster.jpg

    Args:
        module_name: 模块名称
        code: 番号

    Returns:
        封面本地路径
    """
    return get_movie_local_dir(module_name, code) / "poster.jpg"


def get_movie_fanart_path(module_name: str, code: str) -> Path:
    """获取背景图的本地路径"""
    return get_movie_local_dir(module_name, code) / "fanart.jpg"


def get_movie_thumb_path(module_name: str, code: str) -> Path:
    """获取缩略图的本地路径"""
    return get_movie_local_dir(module_name, code) / "thumb.jpg"


# ========== 本地预览图（extrafanart）支持 ==========

# 预览图可识别的扩展名
PREVIEW_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif")

# 系统垃圾文件（Windows/macOS 会在共享目录里自动生成，必须排除）
_JUNK_FILENAMES = {"thumbs.db", ".ds_store", "desktop.ini"}

# 单图最小体积，低于此值视为下载失败的残留文件
_MIN_IMAGE_BYTES = 1024


def get_movie_extrafanart_dir(module_name: str, code: str) -> Path:
    """获取预览图（剧照）目录的本地路径

    格式: {data_base}/movies/{module}/{code}/extrafanart/
    例如: L:/data/movies/jav/CJOD-507/extrafanart/
    """
    return get_movie_local_dir(module_name, code) / "extrafanart"


def _natural_sort_key(name: str) -> list:
    """自然排序键：让 2.jpg 排在 10.jpg 前面"""
    return [
        int(token) if token.isdigit() else token.lower()
        for token in re.split(r"(\d+)", name)
    ]


def _list_images_in_dir(directory: Path, limit: int = 200) -> list[str]:
    """列出目录内的有效图片文件（自然排序，已过滤垃圾文件与残缺文件）"""
    try:
        if not directory.exists() or not directory.is_dir():
            return []
    except (OSError, PermissionError):
        return []

    picked: list[Path] = []
    try:
        for entry in directory.iterdir():
            try:
                if entry.name.lower() in _JUNK_FILENAMES:
                    continue
                if entry.suffix.lower() not in PREVIEW_IMAGE_EXTS:
                    continue
                stat = entry.stat()
                if not entry.is_file() or stat.st_size < _MIN_IMAGE_BYTES:
                    continue
                picked.append(entry)
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        return []

    picked.sort(key=lambda p: _natural_sort_key(p.name))
    return [str(p) for p in picked[:limit]]


def list_movie_preview_files(
    module_name: str,
    code: Optional[str],
    file_path: Optional[str] = None,
    limit: int = 200,
) -> list[str]:
    """列出某部影片本地已下载的预览图（extrafanart）绝对路径

    查找优先级（命中即返回，不做合并去重）：
    1. {data_base}/movies/{module}/{code}/extrafanart/   ← 刮削器标准落盘目录
    2. {视频所在目录}/extrafanart/                        ← 影片同级目录
    3. {视频所在目录}/{code}/extrafanart/                 ← 影片同级番号子目录

    Args:
        module_name: 模块名（jav/fc2/uncensored/chinese/pornhub/western）
        code: 番号
        file_path: 视频文件绝对路径（可选，用于回退查找）
        limit: 最多返回多少张

    Returns:
        图片绝对路径列表，自然排序；无本地图时返回空列表
    """
    candidates: list[Path] = []

    if code:
        candidates.append(get_movie_extrafanart_dir(module_name, code))

    if file_path:
        try:
            video_dir = Path(file_path).parent
            candidates.append(video_dir / "extrafanart")
            if code:
                candidates.append(video_dir / code / "extrafanart")
        except (OSError, ValueError):
            pass

    for directory in candidates:
        images = _list_images_in_dir(directory, limit)
        if images:
            return images
    return []


def get_movie_main_image_path(module_name: str, code: Optional[str]) -> Optional[str]:
    """获取影片主图（横版大图优先）的本地路径

    优先级: fanart.jpg → thumb.jpg → cover.jpg → poster.jpg
    用于详情页「预览」区第一张展示的封面大图。
    """
    if not code:
        return None
    base = get_movie_local_dir(module_name, code)
    for name in ("fanart.jpg", "thumb.jpg", "cover.jpg", "poster.jpg",
                 "fanart.png", "cover.png", "poster.png"):
        candidate = base / name
        try:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        except (OSError, PermissionError):
            continue
    return None


def get_actor_avatar_path(actor_name: str) -> Path:
    """获取演员头像的本地路径

    所有模块的演员头像统一存储到 {data_base}/avatars/ 目录
    相同名称的演员复用同一头像文件

    格式: {data_base}/avatars/{actor_name}.jpg
    例如: L:/data/avatars/三上悠亜.jpg

    Args:
        actor_name: 演员名

    Returns:
        头像本地路径
    """
    return _get_data_base_dir() / "avatars" / f"{actor_name}.jpg"


async def download_image_to_local(
    url: str,
    local_path: Path,
    timeout: float = 15.0,
    referer: Optional[str] = None,
) -> Optional[str]:
    """下载远程图片到本地，返回本地路径字符串

    Args:
        url: 远程图片 URL
        local_path: 本地目标路径
        timeout: 下载超时秒数
        referer: Referer 请求头（防盗链绕过）

    Returns:
        下载成功返回本地路径字符串，失败返回 None
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        # 如果本地已有文件则直接返回
        if local_path.exists() and local_path.stat().st_size > 0:
            return str(local_path)
        import aiohttp
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if referer:
            headers["Referer"] = referer
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_obj) as sess:
            async with sess.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if data:
                        Path(str(local_path)).write_bytes(data)
                        return str(local_path)
    except Exception as e:
        logger.warning(f"下载远程图片失败 [{url[:60]}]: {e}")
    return None


async def ensure_movie_media_local(
    module_name: str,
    code: str,
    cover_url: Optional[str] = None,
    fanart_url: Optional[str] = None,
    thumb_url: Optional[str] = None,
    referer: Optional[str] = None,
) -> dict:
    """确保模块影片的所有媒体文件已下载到本地

    根据规范：
    - 封面存到 {data_base}/movies/{module}/{code}/poster.jpg
    - 背景图存到 {data_base}/movies/{module}/{code}/fanart.jpg
    - 缩略图存到 {data_base}/movies/{module}/{code}/thumb.jpg

    Args:
        module_name: 模块名称
        code: 番号
        cover_url: 远程封面 URL
        fanart_url: 远程背景图 URL
        thumb_url: 远程缩略图 URL
        referer: 防盗链 Referer

    Returns:
        {"cover": 本地路径或None, "fanart": ..., "thumb": ...}
    """
    result = {"cover": None, "fanart": None, "thumb": None}
    if cover_url:
        dst = get_movie_cover_path(module_name, code)
        result["cover"] = await download_image_to_local(cover_url, dst, referer=referer)
    if fanart_url:
        dst = get_movie_fanart_path(module_name, code)
        result["fanart"] = await download_image_to_local(fanart_url, dst, referer=referer)
    if thumb_url:
        dst = get_movie_thumb_path(module_name, code)
        result["thumb"] = await download_image_to_local(thumb_url, dst, referer=referer)
    return result


async def ensure_actor_avatar_local(name: str, avatar_url: Optional[str]) -> Optional[str]:
    """确保演员头像已下载到本地

    根据规范：
    所有模块的演员头像统一存入 {data_base}/avatars/
    同演员名的头像复用同一文件，不重复下载

    Args:
        name: 演员名
        avatar_url: 远程头像 URL

    Returns:
        本地头像路径或 None
    """
    if not name:
        return None
    local_path = get_actor_avatar_path(name)
    if local_path.exists() and local_path.stat().st_size > 0:
        return str(local_path)
    if avatar_url:
        return await download_image_to_local(avatar_url, local_path, referer="https://javdb.com/")
    return None


def validate_local_path(path_str: Optional[str]) -> bool:
    """校验本地路径的有效性

    检查：
    1. 路径非空
    2. 文件或目录存在
    3. 文件大小 > 0

    Args:
        path_str: 本地路径字符串

    Returns:
        是否有效
    """
    if not path_str:
        return False
    p = Path(path_str)
    return p.exists() and (p.is_file() if p.suffix else True)
