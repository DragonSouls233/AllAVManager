"""
扫描器基类
所有模块扫描器的公共基类
"""

import asyncio
import json
import os
import re
import shutil
from datetime import datetime
from typing import Optional
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

# 「番号 + 修饰词 + 限定词」后缀（_norm_key 已去掉 -/_，所以 rest 形如
# "cposter" / "ucposter" / "4kposter" / "leakposter"）。
# 🔴 2026-10-06 实测：片库里大量资源是 `JUFE-617-C-poster.jpg`、
# `PRED-886-U-thumb.jpg`、`JUR-689-UC-poster.jpg`、`DLDSS-558-4k-poster.jpg`、
# `STARS-071-Leak-poster.jpg` 这类命名，旧实现要求 rest **精确等于**
# map 键 ⇒ 全部返回 None 被丢弃。抽样 150 个「缺封面」的片子，视频目录里
# 其实 150/150 都有封面，只是被这条规则挡掉了 ⇒ 缺封面数长期不降。
# 修饰词只允许 1~4 个字母（c/u/uc/hd/leak…）或 2k/4k/8k 分辨率标记，
# **不容许以数字开头**，避免把「别的番号恰好以本番号开头」的文件
# （如 ABP-12 遇到 ABP-123-45-poster.jpg 的 rest="45poster"）错认。
_CODE_QUALIFIER_SUFFIX_RE = re.compile(
    r"^(?:[a-z]{1,4}|\d{1,2}k)"
    r"(landscape|background|backdrop|fanart|folder|poster|cover|thumb)$"
)


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
        if is_img:
            hit = _CODE_QUALIFIER_MAP.get(rest)
            if hit is not None:
                return hit
            # 兜底：「番号-修饰词-限定词」命名（见 _CODE_QUALIFIER_SUFFIX_RE 注释）
            m = _CODE_QUALIFIER_SUFFIX_RE.match(rest)
            if m:
                return _CODE_QUALIFIER_MAP[m.group(1)]
    return None


def detect_version_flags(file_name: str) -> dict:
    """从视频文件名识别版本标记，供各模块扫描器落库使用。

    支持两种模式：
    1) 全文扫描（优先）：文件名任意位置含 中文/中字/中文字幕/C/CH/CN/UC/U/破解/Leak/4K 等
    2) 尾部后缀（回退）：文件末尾 -C/-CH/-CN/-U/-UC 等

    与 nfo_parser._detect_version_suffix 口径保持一致。
    """
    stem = Path(file_name).stem
    low = stem.lower()

    flags = {
        "is_chinese": False,
        "is_uncensored": False,
        "is_leak": False,
        "is_4k": False,
    }

    # ---- 全文扫描（覆盖 [中字]、（中文）、中文字幕版 等常见命名习惯） ----
    if any(k in low for k in ("chinese", "中文字幕", "中文", "中字", "chs", "cht")):
        flags["is_chinese"] = True

    # 破解/无码（排除 UHD 误匹配）
    if "uhd" not in low and any(k in low for k in ("无码", "無碼", "uncensored", "破解", "leak", "流出", "rip")):
        flags["is_uncensored"] = True
        flags["is_leak"] = True

    # restored（无码修复版）识别为无码破解，但不视为流出(leak)  # 移植自 mdcx core/file.py acaf244
    if "restored" in low:
        flags["is_uncensored"] = True

    if "4k" in low or "uhd" in low:
        flags["is_4k"] = True

    # ---- 尾部后缀（兼容传统命名） ----
    # 尾部版本后缀（允许 - / _ / 空格 / 无分隔符）
    m = re.search(r"[-_.\s]?([A-Za-z0-9\u4e00-\u9fff]{1,12})$", stem)
    suffix = m.group(1) if m else ""
    sl = suffix.lower()

    if not sl:
        return flags

    # 复合后缀优先：UC = 无码 + 中字
    if sl == "uc":
        flags["is_chinese"] = True
        flags["is_uncensored"] = True
        return flags

    if "4k" in sl or "uhd" in sl:
        flags["is_4k"] = True
    if not flags["is_chinese"] and any(k in sl for k in ("c", "ch", "cn", "中字", "中文")):
        flags["is_chinese"] = True
    if not flags["is_uncensored"] and "uhd" not in sl and any(k in sl for k in ("u", "unc", "uncensored", "无码", "無碼")):
        flags["is_uncensored"] = True
    if not flags["is_leak"] and any(k in sl for k in ("leak", "流出", "破解", "rip")):
        flags["is_leak"] = True

    return flags


# ─── 外挂字幕识别（移植自 ref114-amane，2026-10-13） ──────────────────────
# amane 的口径：中字标识 = 文件名特征 ∪ 同目录字幕文件。
# 文件名特征 detect_version_flags 早已覆盖；这里补「同目录字幕文件」一半。
# 扩展名表与 amane library/rules.py::DEFAULT_SUBTITLE_EXTENSIONS 一致。
_SUBTITLE_EXTS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub"})


def dir_subtitle_stems(files: list[str]) -> set[str]:
    """从目录文件清单提取外挂字幕 stem 集合。

    ``files`` 直接来自 ``iter_media_entries`` 的 ``(root, dirs, files)``——
    它含目录下**全部**文件（不只视频），因此这里是**零额外磁盘 IO**：
    整盘/网络盘扫描不会多一次 listdir。
    """
    stems: set[str] = set()
    for name in files:
        if Path(name).suffix.lower() in _SUBTITLE_EXTS:
            stems.add(Path(name).stem)
    return stems


def has_external_subtitle(
    video_stem: str, subtitle_stems: set[str], code: str | None = None
) -> bool:
    """视频是否有外挂字幕。

    口径移植自 amane ``cleanup/footprint.py::_add_subtitles``：
    ``stem == video.stem`` 或 ``stem.startswith(video.stem + ".")``
    （即「同名」与「视频名.语言」两种形式，如 ``ABC-123.chs.srt``）。
    额外接受番号命名：``ABC-123-C.mp4`` 配 ``ABC-123.srt`` 也算
    （同目录同番号，字幕大概率属于该片；JAV 社区的外挂字幕基本即中字）。

    注意：这里**不区分字幕语言**——目录里出现 .srt 即视为中字证据，
    与 amane 的口径一致（英文外挂字幕极罕见；若以后要区分，可按
    chs/cht/sc/tc/简/繁 关键字收紧）。
    """
    if not subtitle_stems:
        return False
    keys = [video_stem]
    if code:
        keys.append(code)
    for k in keys:
        if not k:
            continue
        if k in subtitle_stems:
            return True
        prefix = k + "."
        if any(s.startswith(prefix) for s in subtitle_stems):
            return True
    return False


def find_external_subtitle(video_path: str | Path, code: str | None = None) -> bool:
    """按完整路径判定外挂字幕（给补刮/修补 route 用，会真列一次目录）。

    扫描器热路径请用 :func:`dir_subtitle_stems` + :func:`has_external_subtitle`
    （复用遍历已得到的 files，零 IO）；本函数用于单部影片的事后判定。
    """
    try:
        video_dir = Path(video_path).parent
        children = list(video_dir.iterdir())
    except OSError:
        return False
    stems = {c.stem for c in children if c.suffix.lower() in _SUBTITLE_EXTS}
    return has_external_subtitle(Path(video_path).stem, stems, code)


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


# 🔴 孤儿清理宽限期（天）——移植 avm（片匣）的「缺失宽限期」设计：
# 影片文件消失后不立即删记录，先标记；连续缺失满 30 天才真正删除。
# 背景：媒体库在网络盘（Z:/Y:/X:/W: 映射盘）上，盘临时掉线/重连时
# os.path.exists 全部返回 False，旧逻辑会把这些记录当孤儿一次性删光。
ORPHAN_GRACE_DAYS = 30


def _load_grace_state(path: Path) -> dict:
    """读取孤儿宽限状态 {记录id: 首次发现缺失的 ISO 时间}。损坏时返回空。"""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        logger.warning(f"孤儿宽限状态读取失败（按空处理）: {e}")
    return {}


def _save_grace_state(path: Path, state: dict) -> None:
    """持久化孤儿宽限状态（失败只警告，不影响清理主流程）。"""
    try:
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"孤儿宽限状态写入失败: {e}")


async def cleanup_orphans_with_grace(
    module_name: str,
    media_dirs: list,
    db,
    log_tag: str = "",
) -> int:
    """带缺失宽限期的孤儿清理（BaseScanner / anime_resumable 共用）。

    与旧实现的差异（2026-10-14，修网络盘掉线误删）：
    1. **盘可达性预检**：清理前对每个 media_dir 根做带超时探测，不可达的盘
       整体跳过——扫描中途掉线的盘不会再让它的记录被误判为"文件已删除"；
    2. **宽限期**：文件确实消失（且盘可达）时不立即删，先在状态文件
       `<模块db>.orphan_grace.json` 登记"首次缺失时间"，满 ORPHAN_GRACE_DAYS
       天才删除；文件重新出现则自动清除标记（盘重新挂上即自愈）；
    3. 状态文件里已不存在记录的残留 key 会顺手剪除。

    返回：本次实际删除的记录数。
    """
    from sqlalchemy import text

    from app.utils.media_helpers import path_reachable

    session = await db.get_session()
    removed = 0
    try:
        result = await session.execute(text("SELECT id, file_path FROM movies"))
        rows = result.fetchall()
        if not rows:
            return 0

        # 1) 媒体盘可达性预检（不可达的盘整体跳过，防掉线误删）
        reachable_prefixes: list[str] = []
        skipped_drives: list[str] = []
        for d in media_dirs:
            if path_reachable(str(d), timeout=2.0):
                reachable_prefixes.append(os.path.normcase(os.path.normpath(str(d))))
            else:
                skipped_drives.append(str(d))
        if skipped_drives:
            logger.warning(
                f"{log_tag}孤儿清理: 媒体盘不可达，跳过其下记录: {skipped_drives}"
            )
        if not reachable_prefixes:
            logger.warning(f"{log_tag}孤儿清理: 无可达媒体盘，本次跳过")
            return 0

        # 2) 宽限状态文件（与模块 DB 同目录，重启不丢）
        state_path = Path(str(db.db_path) + ".orphan_grace.json")
        grace_state = _load_grace_state(state_path)
        now = datetime.now()

        to_delete: list = []
        newly_marked: list = []
        in_grace: list = []
        recovered: list = []
        seen_ids: set[str] = set()
        for row in rows:
            fp = row[1]
            if not fp:
                continue
            norm_fp = os.path.normcase(os.path.normpath(str(fp)))
            if not any(norm_fp.startswith(p) for p in reachable_prefixes):
                continue
            rid = row[0]
            seen_ids.add(str(rid))
            if os.path.exists(norm_fp):
                # 文件在（或盘重连后回来了）：清除宽限标记
                if grace_state.pop(str(rid), None):
                    recovered.append(rid)
                continue
            first_seen = grace_state.get(str(rid))
            if not first_seen:
                grace_state[str(rid)] = now.isoformat()
                newly_marked.append(rid)
                continue
            try:
                age_days = (now - datetime.fromisoformat(first_seen)).days
            except ValueError:
                age_days = ORPHAN_GRACE_DAYS  # 状态损坏按到期处理，避免永远卡着
            if age_days >= ORPHAN_GRACE_DAYS:
                to_delete.append(rid)
            else:
                in_grace.append(rid)

        # 3) 剪除已不存在记录的状态残留 + 本轮已删记录的宽限标记
        for stale_key in [k for k in grace_state if k not in seen_ids]:
            grace_state.pop(stale_key, None)
        for rid in to_delete:
            grace_state.pop(str(rid), None)  # 已删除，标记随之清除

        for rid in to_delete:
            await session.execute(text("DELETE FROM movies WHERE id = :id"), {"id": rid})
            removed += 1
        if to_delete:
            await session.commit()
        _save_grace_state(state_path, grace_state)

        if to_delete or newly_marked or in_grace or recovered or skipped_drives:
            logger.info(
                f"{log_tag}孤儿清理: 删除 {removed} 条（宽限 {ORPHAN_GRACE_DAYS} 天到期）；"
                f"新标记缺失 {len(newly_marked)} 条；宽限期内 {len(in_grace)} 条；"
                f"恢复清除标记 {len(recovered)} 条"
            )
    except Exception as e:
        logger.warning(f"{log_tag}孤儿清理失败: {e}")
    finally:
        await session.close()
    return removed


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


def _copy_file_resilient(src: Path, dst: Path) -> bool:
    """跨网络盘复制单个文件，带 SameFileError / 元数据失败降级。

    服务器的媒体目录常是 SMB 映射盘（`L:` = `\\\\host\\share`），同一个物理文件可能
    通过不同路径可达（如 `L:\\data` 与服务器本地 `E:\\MDCX-Server\\data`）。此时
    `shutil.copy2` 会抛 SameFileError；另外 SMB 上 copystat（写 mtime/权限）经常
    被拒绝，导致明明内容可复制却整体失败。

    降级链：samefile 短路 → copy2（保留元数据）→ 纯字节流 copyfileobj（只要内容）。
    """
    try:
        if dst.exists() and src.samefile(dst):
            logger.debug(f"源与目标为同一文件，跳过: {src}")
            return False
    except OSError:
        pass  # 网络盘不支持 samefile，交给后续实际复制去兜底

    try:
        shutil.copy2(src, dst)
        return True
    except shutil.SameFileError:
        logger.debug(f"源与目标为同一文件，跳过: {src}")
        return False
    except OSError as e:
        # SMB / 只读属性 / copystat 被拒：退化为只要内容的字节流复制
        logger.debug(f"copy2 失败，改用字节流复制 {src}: {e}")
        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
            return True
        except Exception as e2:
            raise RuntimeError(f"字节流复制也失败: {e2}") from e2


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
            # 用 _copy_file_resilient 兜住 SMB 映射盘的 SameFileError / copystat 失败
            ok = await asyncio.to_thread(_copy_file_resilient, src, dst)
            if not ok:
                continue
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
        """并发受限地执行复制任务（保留给旧的 ensure_future 调用方）"""
        if BaseScanner._COPY_SEM is None:
            BaseScanner._COPY_SEM = asyncio.Semaphore(5)
        try:
            async with BaseScanner._COPY_SEM:
                await asyncio.wait_for(coro, timeout=60)
        except Exception:
            pass  # 复制失败不影响扫描主流程

    # ------------------------------------------------------------------ #
    # 🔴 2026-10-13：非阻塞拷贝投递（PORNHUB 实测教训）
    #
    # `_copy_limited` 的 Semaphore(5) **只限"同时执行数"、不限"创建的 task 数"**。
    # 扫描器在文件循环里逐个 `ensure_future`，PORNHUB 单盘 3 万+ 文件就会创建
    # 3 万+ 个 task：事件循环被调度压垮 + task 对象内存膨胀（实测内存占用 83%、
    # 日志完全静止、连一条分批提交都没有）。
    #
    # 正确做法：**有界队列 + 固定 worker + 非阻塞投递**。
    #   - 队列满 → `put_nowait` 抛 QueueFull → 直接跳过这次拷贝
    #   - 跳过只丢"本地 NFO/封面拷贝"这个可选副作用，**绝不影响入库主流程**
    #   - worker 执行的网络盘 listdir 还有单项超时兜底，防止 worker 全被占死
    # ------------------------------------------------------------------ #
    def _init_copy_pool(self, worker_n: int = 3, queue_size: int = 200) -> None:
        self._copy_q: Optional[asyncio.Queue] = None
        self._copy_workers: list = []
        self._copy_worker_n = worker_n
        self._copy_queue_size = queue_size
        self._copy_dropped = 0

    def _ensure_copy_pool(self) -> "asyncio.Queue":
        if getattr(self, "_copy_q", None) is None:
            self._copy_q = asyncio.Queue(maxsize=self._copy_queue_size)
            self._copy_workers = [
                asyncio.create_task(self._copy_worker())
                for _ in range(self._copy_worker_n)
            ]
        return self._copy_q

    async def _copy_worker(self) -> None:
        q = self._copy_q
        while True:
            try:
                item = await q.get()
            except asyncio.CancelledError:
                raise
            path, code, module_name = item
            try:
                from app.tasks.base_scanner import (
                    copy_video_assets_to_data_dir as _copy_assets,
                )
                await asyncio.wait_for(
                    _copy_assets(path, code, module_name), timeout=30
                )
            except Exception:
                pass
            finally:
                q.task_done()

    def _submit_copy(self, file_path: str, code: str,
                     module_name: str = "") -> None:
        """非阻塞投递拷贝任务；队列满直接跳过，绝不阻塞扫描主循环。

        ⚠️ `module_name` 必须有默认值：各扫描器只服务一个模块，调用方漏传时
        应当退化到 `self.module_name`，而不是抛 TypeError 把整个扫描打断
        （2026-10-13 实测：续扫器漏传 → 第一个文件就抛"missing ... module_name"，
          339 个目录只扫了 1 个文件就结束）。
        """
        if not code:
            return
        try:
            q = self._ensure_copy_pool()
        except RuntimeError:
            return          # 没在事件循环里（同步上下文），直接跳过
        try:
            q.put_nowait((file_path, code, module_name or self.module_name))
        except asyncio.QueueFull:
            self._copy_dropped += 1

    async def _shutdown_copy_pool(self, drain_timeout: int = 60) -> None:
        """停止拷贝 worker；已入队项最多再等 drain_timeout。"""
        q, self._copy_q = getattr(self, "_copy_q", None), None
        workers, self._copy_workers = getattr(self, "_copy_workers", []), []
        if q is not None:
            try:
                await asyncio.wait_for(q.join(), timeout=drain_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"拷贝队列未在 {drain_timeout}s 内排空，放弃剩余 {q.qsize()} 项"
                )
        for w in workers:
            w.cancel()
        for w in workers:
            try:
                await w
            except asyncio.CancelledError:
                pass      # 正常取消路径（py3.11+ CancelledError 不继承 Exception）
            except Exception:
                pass
        if self._copy_dropped:
            logger.info(
                f"因队列积压跳过 {self._copy_dropped} 部影片的本地资源拷贝"
                f"（不影响入库，封面可事后批量补）"
            )

    @abstractmethod
    async def scan(self) -> dict:
        """扫描媒体目录，返回扫描结果"""
        ...

    # ------------------------------------------------------------------
    # 演员关联表维护（2026-10-04 新增，供各扫描器统一调用）
    # ------------------------------------------------------------------

    async def _sync_actor_links(self) -> dict:
        """把本模块 ``movies`` 演员文本列回填成 ``movie_actors`` 关联行。

        放在基类而不是各扫描器里，是因为 4 个扫描器（jav / uncensored /
        pornhub / chinese）原本各写一份 ``_update_actor_counts``，全部用
        文本 ``LIKE '%name%'`` 统计 movie_count，而 SQLite 的 ``LIKE``
        **默认大小写不敏感** ⇒ ``Ruth lee`` 与 ``Ruth Lee`` 互相虚增，
        子串匹配还会把 ``Anna Cherry`` 算进 ``Anna Cherry7`` 的影片。

        实测 7 个模块里 6 个的 ``movie_actors`` 为 0 行 ⇒
        ``actors.movie_count`` 与"按演员查影片"都只能靠文本 LIKE 兜底
        （``api/routes/actors.py`` 的注释里也写明了这一点）。

        失败绝不中断扫描：演员关联是辅助数据。
        """
        try:
            from app.db.module_db import ModuleDatabase
            from app.db.movie_actor_sync import (
                backfill_links_from_text,
                recount_actor_movie_counts,
            )

            db = ModuleDatabase.get_instance(self.module_name)
            async with db.session_scope() as session:
                r = await backfill_links_from_text(
                    session, self.module_name, recount=False,
                )
                await session.commit()
                rc = await recount_actor_movie_counts(session, self.module_name)
            logger.info(
                f"[{self.module_name}] 演员关联回填: 扫描 {r['scanned']} 部，"
                f"写入 {r['linked']} 条关联，{r['no_valid_name']} 部无有效演员名；"
                f"重算 movie_count {rc['changed']}/{rc['actors']}"
            )
            return {"backfill": r, "recount": rc}
        except Exception as e:
            logger.warning(f"[{self.module_name}] 演员关联回填失败（不影响扫描）: {e}")
            return {}

    async def _count_actor_movies(self) -> int:
        """按关联表精确统计 movie_count 已重算的演员数（供子类日志用）。"""
        return 0

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

        🔴 2026-10-14 起带缺失宽限期（见 cleanup_orphans_with_grace）：
        媒体盘在网络盘上，掉线时 os.path.exists 全 False，旧逻辑会误删整批记录。
        """
        from app.db.module_db import ModuleDatabase

        return await cleanup_orphans_with_grace(
            self.module_name, self.media_dirs, ModuleDatabase.get_instance(self.module_name),
            log_tag=f"模块 [{self.module_name}] ",
        )
