"""
文件浏览路由

提供目录浏览功能，用于前端选择目录路径。
完整兼容 Windows（盘符）和 Linux（挂载点）。
"""

import os
import sys
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


def _get_windows_drives() -> list[str]:
    """获取 Windows 所有可用盘符"""
    drives = []
    # 方法1：使用 ctypes 调用 Windows API
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        logger.info(f"[Windows] GetLogicalDrives 位掩码: {bitmask:#x}")
        for letter in range(65, 91):  # A-Z
            if bitmask & (1 << (letter - 65)):
                drive = f"{chr(letter)}:\\"
                if os.path.isdir(drive):
                    drives.append(drive)
                    logger.info(f"[Windows] 发现盘符: {drive}")
    except Exception as e:
        logger.warning(f"[Windows] ctypes 获取盘符失败: {e}")

    # 方法2：如果方法1失败，用 os.listdir 扫描
    if not drives:
        logger.info("[Windows] ctypes 失败，尝试 os.listdir 扫描")
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            try:
                if os.path.isdir(drive):
                    drives.append(drive)
            except Exception:
                pass

    logger.info(f"[Windows] 最终盘符列表: {drives}")
    return sorted(drives)


def _get_windows_drive_label(drive: str) -> str:
    """获取 Windows 盘符的卷标"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        volume_name = ctypes.create_unicode_buffer(256)
        fs_name = ctypes.create_unicode_buffer(256)
        if kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive),
            volume_name, ctypes.sizeof(volume_name),
            None, None, None,
            fs_name, ctypes.sizeof(fs_name),
        ):
            label = volume_name.value.strip()
            if label:
                return label
    except Exception:
        pass
    return ""


def _get_parent_path(path_str: str) -> str | None:
    """
    获取父目录路径，兼容 Windows 和 Linux

    Windows 特殊处理：
    - C:\\Users 的父目录是 C:\\
    - C:\\ 的父目录是 "此电脑"（返回特殊标记）
    """
    p = Path(path_str)

    if IS_WINDOWS:
        # Windows: 盘符根目录的父目录返回特殊标记
        drive_root = p.drive + "\\" if p.drive else None
        if drive_root and os.path.normpath(path_str) == os.path.normpath(drive_root):
            # 已经是盘符根目录，返回 "此电脑" 标记
            return "THIS_PC"
        # 普通目录的父目录
        parent = p.parent
        if parent.exists() and parent.is_dir():
            return str(parent)
        return None
    else:
        # Linux: 根目录的父目录是 None
        if p.parent == p:
            return None
        if p.parent.exists() and p.parent.is_dir():
            return str(p.parent)
        return None


@router.get("/browse")
async def browse_directory(
    path: str = Query("", description="要浏览的目录路径"),
    show_files: bool = Query(False, description="是否显示文件"),
):
    """
    浏览指定目录的内容

    - path: 目录路径，Windows 下传入 "THIS_PC" 可返回所有盘符
    - show_files: 是否同时显示文件（默认只显示目录）
    """
    # Windows 默认路径处理
    if not path or path == "/":
        if IS_WINDOWS:
            path = "THIS_PC"
        else:
            path = "/"

    logger.info(f"[browse] 请求路径: path='{path}', repr={repr(path)}, 系统: {'Windows' if IS_WINDOWS else 'Linux'}")

    # Windows 特殊处理：浏览 "此电脑"（显示所有盘符）
    if IS_WINDOWS and (path == "THIS_PC" or path.upper() == "THIS_PC"):
        logger.info("[browse] Windows 此电脑模式，返回所有盘符")
        drives = _get_windows_drives()
        entries = []
        for drive in drives:
            try:
                # 获取卷标
                vol_label = _get_windows_drive_label(drive)
                # 获取驱动器类型
                drive_type = "本地磁盘"
                try:
                    import ctypes
                    dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
                    type_map = {2: "可移动磁盘", 3: "本地磁盘", 4: "网络驱动器", 5: "CD-ROM", 6: "RAM 磁盘"}
                    drive_type = type_map.get(dtype, "未知")
                except Exception:
                    pass

                # 显示名称
                display = f"{drive}"
                if vol_label:
                    display = f"{drive} ({vol_label})"
                else:
                    display = f"{drive} {drive_type}"

                entries.append({
                    "name": display,
                    "path": drive,
                    "type": "directory",
                    "is_drive": True,
                    "drive_type": drive_type,
                })
            except (PermissionError, OSError):
                continue

        return {
            "current_path": "THIS_PC",
            "current_name": "此电脑",
            "parent_path": None,
            "entries": entries,
            "total": len(entries),
        }

    # 普通目录浏览
    try:
        dir_path = Path(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"路径格式错误: {e}")

    if not dir_path.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")

    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {path}")

    try:
        entries = []
        for entry in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                if entry.is_dir():
                    entries.append({
                        "name": entry.name,
                        "path": str(entry.absolute()),
                        "type": "directory",
                    })
                elif show_files and entry.is_file():
                    entries.append({
                        "name": entry.name,
                        "path": str(entry.absolute()),
                        "type": "file",
                        "size": entry.stat().st_size,
                    })
            except (PermissionError, OSError):
                continue

        # 获取父目录
        parent = _get_parent_path(str(dir_path.absolute()))

        return {
            "current_path": str(dir_path.absolute()),
            "current_name": dir_path.name or str(dir_path.absolute()),
            "parent_path": parent,
            "entries": entries,
            "total": len(entries),
        }

    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权限访问: {path}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取目录失败: {e}")


@router.get("/roots")
async def get_system_roots():
    """
    获取系统根目录/盘符列表

    Windows: 返回所有可用的盘符 (C:\\, D:\\, E:\\ 等)
    Linux: 通过 /proc/mounts 检测所有挂载点
    """
    logger.info(f"[roots] 系统平台: {sys.platform}, IS_WINDOWS={IS_WINDOWS}")
    roots = []

    # ===== Windows 系统 =====
    if IS_WINDOWS:
        logger.info("[roots] Windows 系统，获取盘符列表")
        drives = _get_windows_drives()

        for drive in drives:
            try:
                # 获取卷标
                vol_label = _get_windows_drive_label(drive)

                # 获取驱动器类型
                drive_type = "本地磁盘"
                is_mount = True
                try:
                    import ctypes
                    dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
                    type_map = {2: "可移动磁盘", 3: "本地磁盘", 4: "网络驱动器", 5: "CD-ROM", 6: "RAM 磁盘"}
                    drive_type = type_map.get(dtype, "未知")
                    is_mount = dtype in (2, 3, 4, 5, 6)
                except Exception:
                    pass

                # 获取子目录数量和视频检测
                subdir_count = 0
                has_video = False
                try:
                    for f in os.listdir(drive):
                        full_path = os.path.join(drive, f)
                        if os.path.isdir(full_path):
                            subdir_count += 1
                        elif f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".iso", ".wmv", ".flv")):
                            has_video = True
                except (PermissionError, OSError):
                    pass

                # 显示名称
                if vol_label:
                    label = f"💾 {drive} ({vol_label})"
                else:
                    label = f"💾 {drive} {drive_type}"
                if has_video:
                    label += " 🎬"
                if subdir_count > 0:
                    label += f" ({subdir_count}个文件夹)"

                roots.append({
                    "name": label,
                    "path": drive,
                    "type": "directory",
                    "is_mount": is_mount,
                    "is_drive": True,
                    "has_video": has_video,
                    "drive_type": drive_type,
                })
            except (PermissionError, OSError):
                continue

        logger.info(f"[roots] Windows 盘符数量: {len(roots)}")
        return {"roots": roots}

    # ===== Linux 系统 =====
    logger.info("[roots] Linux 系统，获取挂载点列表")
    mount_points_found = set()

    # 1. 从 /proc/mounts 读取所有挂载点
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mount_path = parts[1]
                    if mount_path.startswith(("/sys", "/proc", "/dev", "/run", "/etc")):
                        continue
                    if mount_path in ("/", "/dev", "/proc", "/sys"):
                        continue
                    mount_points_found.add(mount_path)
    except Exception:
        pass

    # 2. 补充常见挂载点
    common_mounts = ["/media", "/mnt", "/output", "/data", "/volume1", "/volume2",
                     "/share", "/shared", "/nfs", "/cifs", "/smb"]
    for m in common_mounts:
        if os.path.exists(m):
            mount_points_found.add(m)

    # 3. 扫描 / 下所有一级目录
    try:
        for entry in sorted(os.listdir("/")):
            entry_path = f"/{entry}"
            if os.path.isdir(entry_path) and not entry.startswith("."):
                mount_points_found.add(entry_path)
    except PermissionError:
        pass

    # 4. 排序并生成结果
    priority_roots = []
    other_roots = []

    for mount_path in sorted(mount_points_found):
        if not os.path.exists(mount_path):
            continue
        try:
            is_mount = False
            try:
                st = os.stat(mount_path)
                parent_st = os.stat(os.path.dirname(mount_path))
                is_mount = st.st_dev != parent_st.st_dev
            except Exception:
                pass

            subdir_count = 0
            has_video = False
            try:
                for f in os.listdir(mount_path):
                    if os.path.isdir(os.path.join(mount_path, f)):
                        subdir_count += 1
                    elif f.endswith((".mp4", ".mkv", ".avi", ".mov", ".iso", ".wmv", ".flv")):
                        has_video = True
            except PermissionError:
                continue

            display = os.path.basename(mount_path) or mount_path
            icon = "💾" if is_mount else "📁"
            label = f"{icon} {display}"

            if is_mount:
                label += " (硬盘)"
            if has_video:
                label += " 🎬"
            if subdir_count > 0:
                label += f" ({subdir_count}个文件夹)"

            item = {
                "name": label,
                "path": mount_path,
                "type": "directory",
                "is_mount": is_mount,
                "is_drive": False,
                "has_video": has_video,
            }

            if is_mount or has_video or mount_path in ("/media", "/mnt", "/output", "/data"):
                priority_roots.append(item)
            else:
                other_roots.append(item)

        except (PermissionError, OSError):
            continue

    return {"roots": priority_roots + other_roots}


# ============== 文件代理 ==============

# 允许代理的文件扩展名白名单(主要用于图片/视频缩略图/NFO 预览)
_PROXY_ALLOWED_EXTS = {
    # 图片
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".ico",
    # 视频
    ".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v", ".ts", ".mpg", ".mpeg",
    # 音频
    ".mp3", ".flac", ".aac", ".ogg", ".wav", ".m4a",
    # 字幕
    ".srt", ".vtt", ".ass", ".ssa", ".sub",
    # 文本/NFO
    ".nfo", ".txt", ".xml", ".json",
    # 海报/封面缓存
    ".avif", ".tiff",
}


@router.get("/proxy")
async def proxy_file(
    path: str = Query(..., description="本地文件绝对路径"),
):
    """代理本地文件(用于前端 <img>/<video> 标签加载本地文件)

    安全策略:
    1. 路径必须是绝对路径
    2. 文件扩展名必须在白名单内(防止读取敏感文件如 .env/.py)
    3. 文件必须存在且可读
    """
    from fastapi.responses import FileResponse

    # 安全校验:必须是绝对路径
    if not os.path.isabs(path):
        raise HTTPException(status_code=400, detail="路径必须是绝对路径")

    # 安全校验:扩展名白名单
    ext = os.path.splitext(path)[1].lower()
    if ext not in _PROXY_ALLOWED_EXTS:
        raise HTTPException(status_code=403, detail=f"不支持的文件类型: {ext}")

    # 文件存在性检查
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail="路径不是文件")

    try:
        return FileResponse(path)
    except PermissionError:
        raise HTTPException(status_code=403, detail="无权限读取文件")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")
