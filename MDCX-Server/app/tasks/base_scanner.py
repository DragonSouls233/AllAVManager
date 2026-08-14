"""
扫描器基类
所有模块扫描器的公共基类
"""

import asyncio
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


# 视频目录中常见的资源文件名 → 数据中心标准名
_VIDEO_DIR_ASSETS = {
    # (源文件名, 目标相对名)
    "movie.nfo":      "movie.nfo",
    "poster.jpg":     "poster.jpg",
    "poster.png":     "poster.jpg",
    "fanart.jpg":     "fanart.jpg",
    "fanart.png":     "fanart.jpg",
    "cover.jpg":      "cover.jpg",
    "cover.png":      "cover.jpg",
    "thumb.jpg":      "thumb.jpg",
    "thumb.png":      "thumb.jpg",
    "landscape.jpg":  "cover.jpg",
    "backdrop.jpg":   "fanart.jpg",
    "background.jpg": "fanart.jpg",
    "folder.jpg":     "poster.jpg",
}

_MIN_ASSET_BYTES = 1024  # 小于 1KB 的视为无效文件

# 以番号命名的资源后缀 → 数据中心标准名
# 例：012213_831-poster.jpg → poster.jpg；HEYZO-0407-fanart.png → fanart.jpg
_CODE_QUALIFIER_MAP = {
    "poster": "poster.jpg",
    "cover": "cover.jpg",
    "thumb": "thumb.jpg",
    "fanart": "fanart.jpg",
    "landscape": "cover.jpg",
    "backdrop": "fanart.jpg",
    "background": "fanart.jpg",
    "folder": "poster.jpg",
}


def _norm_key(s: str) -> str:
    """归一化用于比对的键：每段数字去前导零，再去掉 -/_。

    先在各数字段内去前导零（保留 -/_ 以便分段），再去除分隔符，
    兼容番号中 - 与 _ 的差异，以及数字前导零差异
    （如 012213-831 与 012213_831、HEYDOUGA-4169-24 与 HEYDOUGA-4169-024）。
    """
    s = re.sub(r"(\d+)", lambda m: m.group(1).lstrip("0") or "0", s.lower())
    return re.sub(r"[-_]", "", s)


def _resolve_asset_target(src_name: str, code: str) -> str | None:
    """将视频目录中的资源文件名映射到数据中心标准名。

    兼容两类命名：
    1) 通用名：movie.nfo / poster.jpg / fanart.png / cover.jpg ...
    2) 以番号命名的资源：{code}.nfo / {code}-poster.jpg / {code}_fanart.png ...
       忽略番号中 - 与 _ 的差异（如 012213-831 与 012213_831 视为同一番号）。
    """
    src_name = (src_name or "").strip()
    if not src_name:
        return None
    stem = Path(src_name).stem
    suffix = Path(src_name).suffix.lower()
    is_nfo = suffix == ".nfo"
    is_img = suffix in (".jpg", ".jpeg", ".png", ".webp")

    # 1) 通用名（保持原行为）
    generic = _VIDEO_DIR_ASSETS.get(src_name.lower())
    if generic is not None:
        if is_nfo and not generic.endswith(".nfo"):
            return None
        if is_img and not generic.endswith((".jpg", ".png")):
            return None
        return generic

    # 2) 以番号命名的资源（忽略 -/_ 与数字前导零差异）
    code_key = _norm_key(code or "")
    s_key = _norm_key(stem)
    if not code_key:
        return None
    if s_key == code_key:
        # 仅有番号：NFO → movie.nfo；图片 → 兜底为 poster.jpg
        return "movie.nfo" if is_nfo else ("poster.jpg" if is_img else None)
    if s_key.startswith(code_key):
        rest = s_key[len(code_key):]
        if is_nfo:
            return "movie.nfo"
        if is_img and rest in _CODE_QUALIFIER_MAP:
            return _CODE_QUALIFIER_MAP[rest]
    return None


def detect_version_flags(file_name: str) -> dict:
    """从视频文件名统一识别版本后缀，供各模块扫描器落库使用。

    与 nfo_parser._detect_version_suffix 口径保持一致，映射规则：
      -C / -CH / -CN / -中字   → is_chinese=True
      -U / -Uncensored / -无码  → is_uncensored=True
      -UC（复合，无码+中字）    → is_chinese=True 且 is_uncensored=True
      -Leak / -流出 / -破解     → is_leak=True
      -4K / -UHD                → is_4k=True

    返回 {"is_chinese", "is_uncensored", "is_leak", "is_4k"} 四个布尔标记。
    """
    stem = Path(file_name).stem
    # 尾部版本后缀（允许 - / _ / 空格 / 无分隔符，兼容 JAV 常见命名）
    m = re.search(r"[-_.\s]?([A-Za-z0-9\u4e00-\u9fff]{1,12})$", stem)
    suffix = m.group(1) if m else ""
    low = suffix.lower()

    flags = {
        "is_chinese": False,
        "is_uncensored": False,
        "is_leak": False,
        "is_4k": False,
    }
    if not low:
        return flags

    # 复合后缀优先：UC = 无码 + 中字
    if low == "uc":
        flags["is_chinese"] = True
        flags["is_uncensored"] = True
        return flags

    # 4K 判定前置：UHD 含 "u"，必须先判 4K 再判无码，否则 -UHD 会被误判为无码
    if "4k" in low or "uhd" in low:
        flags["is_4k"] = True
    if any(k in low for k in ("c", "ch", "cn", "中字", "中文")):
        flags["is_chinese"] = True
    if "uhd" not in low and any(k in low for k in ("u", "unc", "uncensored", "无码", "無碼")):
        flags["is_uncensored"] = True
    if any(k in low for k in ("leak", "流出", "破解", "rip")):
        flags["is_leak"] = True
    return flags


def find_local_cover(video_file_path: str | Path, code: str) -> str | None:
    """在视频目录中查找本地封面，返回绝对路径（用于回填 cover_url）。

    优先 poster.jpg，其次 cover.jpg / fanart.jpg；
    同时兼容通用名与 {code}-poster.jpg 这类以番号命名的资源。
    """
    video_dir = Path(video_file_path).parent
    if not video_dir.exists():
        return None
    priority = ["poster.jpg", "cover.jpg", "fanart.jpg"]
    found: dict[str, str] = {}
    for src in video_dir.iterdir():
        if not src.is_file():
            continue
        dst_name = _resolve_asset_target(src.name, code)
        if dst_name in priority and src.stat().st_size >= _MIN_ASSET_BYTES:
            found.setdefault(dst_name, str(src))
    for name in priority:
        if name in found:
            return found[name]
    return None


# 遍历时剪枝跳过的系统/垃圾目录名（整盘扫描时避免陷入回收站、系统卷信息等）
_SKIP_WALK_DIRS = {
    "$recycle.bin", "system volume information", "@eadir", "#recycle",
    "found.000", "recycler", "$sysreset", "node_modules", "__pycache__",
    ".git", ".svn", ".hg",
}


def _list_dir_entries(path: Path) -> list:
    """列目录条目（容错）。用于线程池中执行，避免同步磁盘 IO 阻塞事件循环。"""
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def _file_size(path: Path) -> int:
    """取文件大小（容错）。网络盘上一次 stat 即可，避免 exists()+stat() 两次 IO。"""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def iter_media_entries(
    media_dir: str | Path,
    max_depth: int = 8,
) -> list[tuple[str, list[str], list[str]]]:
    """受控遍历媒体目录：限制深度 + 剪枝系统/隐藏目录（os.scandir 快速实现）。

    替代 `list(os.walk(media_dir))`——当 media_dirs 是整盘符（M:\\、H:\\）或超大
    网络目录时，无限制的 os.walk 会遍历出数百万条目并长期占满线程池，导致整个
    服务假死（日志/API 全部停止）。此函数：
    - 限制下探深度（max_depth），整盘目录下只读有效媒体层级；
    - 剪枝回收站、系统卷信息、隐藏目录等无效目录；
    - 返回值与 os.walk 相同：(root, dirs, files) 列表。
    """
    media_dir = Path(media_dir)
    entries: list[tuple[str, list[str], list[str]]] = []
    # 显式栈做受限深度遍历（等价 os.walk topdown + dirs 剪枝，但只列目录名与文件名，
    # 不 stat 文件内容；scandir 目录项复用系统缓存，整盘遍历明显更快）
    stack: list[tuple[Path, int]] = [(media_dir, 0)]
    while stack:
        root, depth = stack.pop()
        try:
            with os.scandir(root) as it:
                dirs: list[str] = []
                files: list[str] = []
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if (
                                depth < max_depth
                                and entry.name.lower() not in _SKIP_WALK_DIRS
                                and not entry.name.startswith(".")
                            ):
                                dirs.append(entry.name)
                        else:
                            files.append(entry.name)
                    except OSError:
                        continue
        except OSError:
            continue
        entries.append((str(root), dirs, files))
        # 逆序压栈，保持与 os.walk 一致的目录访问顺序
        for d in reversed(dirs):
            stack.append((root / d, depth + 1))
    return entries


async def copy_video_assets_to_data_dir(
    video_file_path: str | Path,
    code: str,
    module_name: str = "jav",
) -> int:
    """将视频文件所在目录的 NFO + 封面资源复制到数据中心目录。

    触发时机：扫描器发现新视频并写入 DB 后立即调用（无需等网络刮削）。

    Args:
        video_file_path: 视频文件完整路径
        code: 番号（如 CJOD-507）
        module_name: 模块名（jav/fc2/...）

    Returns:
        成功复制的文件数
    """
    video_dir = Path(video_file_path).parent
    if not video_dir.exists():
        logger.debug(f"视频目录不存在: {video_dir}")
        return 0

    try:
        from app.config.manager import get_config_manager
        data_dir = get_config_manager().computed.data_dir
    except Exception:
        logger.warning("无法获取 data_dir，跳过视频资源复制")
        return 0

    target_dir = Path(data_dir) / "movies" / module_name / code
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    # 遍历视频目录中的真实文件，兼容通用名与 {code}-前缀命名
    # iterdir 是同步磁盘 IO，在慢盘/网络盘上会阻塞事件循环（数千并发复制时秒级假死），
    # 丢到线程池执行
    for src in await asyncio.to_thread(_list_dir_entries, video_dir):
        if not src.is_file():
            continue
        dst_name = _resolve_asset_target(src.name, code)
        if not dst_name:
            continue
        size = src.stat().st_size
        if src.suffix.lower() == ".nfo":
            # NFO 是文本元数据，通常很小（几百字节~数 KB），只看是否有内容，
            # 不能用图片的最小体积阈值，否则会被误判为「残缺文件」跳过
            if size == 0:
                logger.debug(f"跳过空 NFO: {src}")
                continue
        else:
            # 图片要求最小体积，避免复制残缺/无效文件
            if size < _MIN_ASSET_BYTES:
                logger.debug(f"跳过无效文件 (<1KB): {src}")
                continue
        dst = target_dir / dst_name
        # 已存在且完整则跳过，避免重复复制
        if dst.exists() and dst.stat().st_size >= size:
            continue
        try:
            # 丢到线程池执行，避免同步复制阻塞事件循环（扫描期间大量小文件复制
            # 会拖慢整个服务端，APScheduler 曾因此报 "missed by 1:08"）。
            await asyncio.to_thread(shutil.copy2, src, dst)
            copied += 1
            logger.info(f"[{module_name}] 复制视频资源: {src.name} → {dst}")
        except Exception as e:
            logger.debug(f"复制失败 {src} → {dst}: {e}")

    return copied


class BaseScanner(ABC):
    """扫描器基类"""

    def __init__(self, module_name: str, media_dirs: list[str]):
        self.module_name = module_name
        self.media_dirs = [Path(d) for d in media_dirs if Path(d).exists()]
        self.video_extensions = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"}

    # 复制任务并发限制：整盘/超大目录扫描时，无限制 ensure_future 会同时派发数千个
    # 资源复制协程，线程池被占满 + 同步磁盘 IO 风暴会拖死事件循环（表现为日志/API 全部
    # 停止的"假死"，连 600s 扫描超时也无法触发）。anime 模块 2026-08-08 已修复，此处分发复用。
    _COPY_SEM: asyncio.Semaphore | None = None

    async def _copy_limited(self, coro) -> None:
        """并发受限地执行复制任务"""
        if BaseScanner._COPY_SEM is None:
            BaseScanner._COPY_SEM = asyncio.Semaphore(5)
        try:
            async with BaseScanner._COPY_SEM:
                await asyncio.wait_for(coro, timeout=60)
        except Exception:
            pass  # 复制失败不影响扫描主流程

    @abstractmethod
    async def scan(self) -> dict:
        """扫描媒体目录，返回扫描结果"""
        ...

    def find_video_files(self, directory: Path) -> list[Path]:
        """递归查找目录下的所有视频文件"""
        videos = []
        try:
            for f in directory.rglob("*"):
                if f.is_file() and f.suffix.lower() in self.video_extensions:
                    videos.append(f)
        except PermissionError:
            pass
        return videos

    def get_relative_path(self, file_path: Path) -> str:
        """获取相对于媒体目录的路径"""
        for media_dir in self.media_dirs:
            try:
                return str(file_path.relative_to(media_dir))
            except ValueError:
                continue
        return str(file_path)

    async def cleanup_orphans(self) -> int:
        """删除磁盘上已不存在影片的数据库记录，返回删除数量。

        扫描只做增量新增，这里用于同步"文件删除"事件：磁盘文件已消失但 DB 记录仍在，
        应将其删除并计入 removed，使统计反映真实净变化（新增 - 删除）。
        仅处理本模块 media_dirs 前缀下的记录，避免误删其它来源数据。
        """
        from app.db.module_db import ModuleDatabase
        from sqlalchemy import text

        db = ModuleDatabase.get_instance(self.module_name)
        session = await db.get_session()
        removed = 0
        try:
            result = await session.execute(text("SELECT id, file_path FROM movies"))
            rows = result.fetchall()
            if not rows:
                return 0
            dir_prefixes = [
                os.path.normcase(os.path.normpath(str(d))) for d in self.media_dirs
            ]
            to_delete = []
            for row in rows:
                fp = row[1]
                if not fp:
                    continue
                norm_fp = os.path.normcase(os.path.normpath(str(fp)))
                if not any(norm_fp.startswith(p) for p in dir_prefixes):
                    continue
                if not os.path.exists(norm_fp):
                    to_delete.append(row[0])
            for rid in to_delete:
                await session.execute(text("DELETE FROM movies WHERE id = :id"), {"id": rid})
                removed += 1
            if to_delete:
                await session.commit()
                logger.info(
                    f"模块 [{self.module_name}] 孤儿清理: 删除 {removed} 条已移除文件的记录"
                )
        except Exception as e:
            logger.warning(f"模块 [{self.module_name}] 孤儿清理失败: {e}")
        finally:
            await session.close()
        return removed
