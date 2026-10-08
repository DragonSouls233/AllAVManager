"""MP4 原子级校验 + faststart 修复 + 改完复验（P1-3，思路来自 ref177-javcover_insert）。

MDCX 现状：仅 `app/api/routes/movies.py:1853` 在 HLS 转码时顺带 `-movflags faststart`，
**没有 atom 级校验**。本模块补齐：

1. 解析 MP4 box 结构（直接读字节，不依赖 ffmpeg/ffprobe，零网络、零子进程）。
2. 判定 faststart 是否已应用（``moov`` 是否在首个 ``mdat`` 之前）。
3. 检测 ``moov`` 之前的异常 ``dat`` atom（PSP 标记，常见于部分工具不认的视频）。
4. ``verify_and_fix``：用 ffmpeg 重封装 + ``+faststart`` 修复 → 重新解析复验
   （确认 moov 在前、无损坏 atom）后才算成功。

🔴 设计约束：解析器只读字节、绝不修改文件；修复走 ffmpeg 临时文件 → 原子替换，
失败保留原文件（与项目 atomic_write 约定一致）。
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.utils.bin_tools import get_ffmpeg_path

_ATOM_HDR = 8  # 4 字节 size + 4 字节 type
# 顶层常见标准 atom（未知类型单独告警，但不阻断解析）
_STANDARD_TOP = {
    "ftyp", "moov", "mdat", "free", "wide", "meta", "udta",
    "mvhd", "trak", "mdia", "minf", "stbl", "stsd", "edts", "dinf",
}


@dataclass
class Atom:
    """一个 MP4 box。``offset`` 是 box 起始（含 8 字节头），``size`` 含头。"""
    type: str
    offset: int
    size: int
    parent: Optional[str] = None


def iter_top_atoms(path: str | os.PathLike) -> list[Atom]:
    """遍历 MP4 顶层 box，返回 Atom 列表。

    处理三种 size 约定：普通 32 位、``size==1``（64 位扩展，头后跟 8 字节）、
    ``size==0``（直到文件尾）。遇到 ``size<8`` 视为损坏，停止遍历避免死循环。
    """
    total = os.path.getsize(path)
    out: list[Atom] = []
    off = 0
    with open(path, "rb") as f:
        while off + _ATOM_HDR <= total:
            f.seek(off)
            hdr = f.read(_ATOM_HDR)
            if len(hdr) < _ATOM_HDR:
                break
            size = struct.unpack(">I", hdr[:4])[0]
            typ = hdr[4:8].decode("latin1")
            if size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    break
                size = struct.unpack(">Q", ext)[0]
            elif size == 0:
                size = total - off
            if size < _ATOM_HDR:
                # 损坏的 box：停止（避免 off 不前进死循环）
                break
            out.append(Atom(typ, off, size))
            off += size
    return out


def moov_children(path: str | os.PathLike, top: list[Atom]) -> list[Atom]:
    """返回 ``moov`` 内的子 atom（用于更细的损坏判定）。"""
    moov = next((a for a in top if a.type == "moov"), None)
    if moov is None:
        return []
    children: list[Atom] = []
    off = moov.offset + _ATOM_HDR
    end = moov.offset + moov.size
    total = os.path.getsize(path)
    end = min(end, total)
    with open(path, "rb") as f:
        while off + _ATOM_HDR <= end:
            f.seek(off)
            hdr = f.read(_ATOM_HDR)
            if len(hdr) < _ATOM_HDR:
                break
            size = struct.unpack(">I", hdr[:4])[0]
            typ = hdr[4:8].decode("latin1")
            if size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    break
                size = struct.unpack(">Q", ext)[0]
            elif size == 0:
                size = end - off
            if size < _ATOM_HDR:
                break
            children.append(Atom(typ, off, size, parent="moov"))
            off += size
    return children


def is_faststart_applied(top: list[Atom]) -> bool:
    """``moov`` 是否在首个 ``mdat`` 之前（即 faststart 已应用）。

    没有 ``mdat``（纯音频/碎片）或没有 ``moov`` 时返回 True（无需前置）。
    """
    moov = next((a for a in top if a.type == "moov"), None)
    if moov is None:
        return True
    mdat = next((a for a in top if a.type == "mdat"), None)
    if mdat is None:
        return True
    return moov.offset < mdat.offset


def find_dat_issues(top: list[Atom]) -> list[str]:
    """检测 ``moov`` 之前的 ``dat`` atom（PSP 标记，部分播放器/工具不认）。

    返回问题列表；空列表表示无异常。``dat`` 出现在 ``moov`` 之前即视为可疑
    （正常 MP4 不应在 moov 前携带 dat；size 异常也追加说明）。
    """
    issues: list[str] = []
    moov = next((a for a in top if a.type == "moov"), None)
    moov_off = moov.offset if moov else 1 << 60
    for a in top:
        # MP4 atom type 为 4 字节；常见写法 "dat "/"dat\x00"，统一按前缀匹配
        # （顶层无 "data" atom，不会误判）。
        if not a.type.startswith("dat"):
            continue
        if a.offset < moov_off:
            issues.append(f"dat_atom_before_moov@offset={a.offset}")
        if a.size < _ATOM_HDR:
            issues.append(f"dat_atom_invalid_size@offset={a.offset}")
    return issues


def scan(path: str | os.PathLike) -> dict:
    """扫描单个 MP4，返回结构化报告（不修改文件）。"""
    p = Path(path)
    top = iter_top_atoms(p)
    return {
        "path": str(p),
        "size": p.stat().st_size,
        "top_atoms": [{"type": a.type, "offset": a.offset, "size": a.size} for a in top],
        "faststart_applied": is_faststart_applied(top),
        "dat_issues": find_dat_issues(top),
        "has_moov": any(a.type == "moov" for a in top),
        "has_mdat": any(a.type == "mdat" for a in top),
    }


def _apply_faststart(path: str) -> bool:
    """用 ffmpeg 重封装 + faststart 到临时文件，成功后原子替换原文件。

    返回 True 表示修复成功；False 表示 ffmpeg 缺失/失败（原文件保持不变）。
    """
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return False
    src = Path(path)
    fd, tmp_name = tempfile.mkstemp(suffix=".tmp.mp4", dir=str(src.parent))
    os.close(fd)
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(src), "-c", "copy", "-movflags", "+faststart", tmp_name],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
        if proc.returncode != 0 or not os.path.exists(tmp_name) or os.path.getsize(tmp_name) == 0:
            return False
        # 原子替换：先校验临时文件可被重新解析（防止写了半截文件覆盖原片）
        try:
            tmp_top = iter_top_atoms(tmp_name)
            if not any(a.type == "moov" for a in tmp_top):
                return False
        except Exception:
            return False
        os.replace(tmp_name, str(src))
        return True
    except Exception:
        return False
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def verify_and_fix(path: str | os.PathLike, fix: bool = False) -> dict:
    """校验 MP4 结构；``fix=True`` 时自动修复（faststart + 清除异常 dat）并复验。

    返回：``{"ok", "issues", "fixed", "before"(fix 时), "after"(fix 时)}``。
    """
    top = iter_top_atoms(path)
    issues = []
    if not is_faststart_applied(top):
        issues.append("moov_not_front")
    issues.extend(find_dat_issues(top))

    if not issues:
        return {"ok": True, "issues": [], "fixed": False}

    if not fix:
        return {"ok": False, "issues": issues, "fixed": False}

    fixed = _apply_faststart(str(path))
    if not fixed:
        return {"ok": False, "issues": issues, "fixed": False, "error": "ffmpeg_faststart_failed"}

    # 复验：重新解析确认 moov 在前、无 dat 异常
    top2 = iter_top_atoms(path)
    after = []
    if not is_faststart_applied(top2):
        after.append("moov_not_front")
    after.extend(find_dat_issues(top2))
    return {
        "ok": len(after) == 0,
        "issues": after,
        "fixed": True,
        "before": issues,
    }
