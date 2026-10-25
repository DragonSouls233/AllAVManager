"""媒体修复：对库内损坏/非 faststart 的影片文件做 ffmpeg 修复（学 peach mp4repair/mp4recover 的安全思路）

与 `media_health`（只读检测）配对：那个回答「哪些文件有问题」，本模块回答
「能不能修、怎么修、修坏了怎么退」。peach 的做法是 untrunc 参照恢复 + ctts 边车，
MDCX 不引入 untrunc 二进制，改用 ffmpeg remux 达到同一目的——**不重编码、
原文件先备份后替换、校验不过就原样退回**。

三种可修形态：
- moov_at_end   moov 在 mdat 之后（非 faststart，边下边播/网页播放体验差）。
                remux -movflags +faststart 重排，不损失画质。
- truncated     moov 还在（faststart 片被砍断/末尾损坏）但数据不完整。
                remux + discardcorrupt 能把所有完整帧捞回来。
- corrupt       moov 完好、文件能打开但中间有坏数据（磁盘/传输损坏）。
                remux 兜底尝试，救不回来就明说，绝不乱替换。

🔴 不可修的一种：no_moov（moov 整体缺失，非 faststart 片下载中断的典型形态）。
2026-10-25 实测：mdat 是长度前缀 NAL（无 Annex-B 起始码），ffmpeg 连输入都打不开
（moov atom not found）；把 mdat 线性转 Annex-B 的启发式扫描会因音视频样本交织
而错位（实测 8s/96 帧的片只解出 27 个 NAL，PPS 引用全乱），没有索引（stsz）
或同参数参照文件就是解不了——这是 untrunc 类工具的领域，如实标记不可修并
给指引，不假装修。

安全链（🔴 每一环失败都保证原文件一个字节不动）：
1. 输出写到同目录 `.mdcx-repair-tmp/`（同卷，替换才是原子 rename）
2. ffprobe 验证临时文件：有视频流、时长 > 0、时长不低于原文件的 30%
3. 可选全解码验证（-f null - 跑一遍，错误行数 ≤ DECODE_ERROR_LIMIT）
4. 原文件改名进同目录 `.mdcx-broken/`（不是删除，是留证）
5. os.replace 原子替换；任何一步失败 → 删临时文件，原文件原地不动

任务化：单文件修复动辄几分钟（大文件 -c copy 也受 IO 限制），全部走任务注册表
+ 轮询；并发 1（IO 密集，并行只会互相拖慢）；支持取消（杀 ffmpeg 子进程）。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import struct
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.utils.bin_tools import get_ffmpeg_path, get_ffprobe_path
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 单文件修复超时（秒）：大文件 -c copy 受 IO 限制，给足 1 小时
REPAIR_TIMEOUT = 3600
# 解码验证超时（秒）：全解码一遍比 remux 慢，单独给
DECODE_TIMEOUT = 5400
# 全解码允许的报错行数（截断处最后一帧常不完整，恰好 1 行是正常的）
DECODE_ERROR_LIMIT = 3
# 修复后时长不得低于原时长的这个比例（原时长可读时）
MIN_DURATION_RATIO = 0.3
# 同时进行的修复任务数（IO 密集，串行）
MAX_CONCURRENT_REPAIRS = 1
# 任务注册表容量（超出淘汰最旧的已完成任务）
JOB_HISTORY = 100
# 单任务日志行数上限（防内存膨胀）
JOB_LOG_LINES = 200
# MP4 box 扫描上限：超过这个数还没看到 moov 就不是认识的片源
BOX_SCAN_LIMIT = 512

REPAIR_TMP_DIR = ".mdcx-repair-tmp"
REPAIR_BACKUP_DIR = ".mdcx-broken"

MODES = ("remux", "reencode")


# ---------------------------------------------------------------- 诊断

@dataclass
class Diagnosis:
    """单文件诊断结果"""
    file_path: str
    category: str            # healthy / truncated / no_moov / moov_at_end / corrupt / zero_byte / missing / unreadable / not_video
    repairable: bool         # 能否修复
    detail: str = ""         # 人类可读说明
    size: int = 0
    duration: Optional[float] = None
    video_codec: Optional[str] = None
    resolution: Optional[str] = None
    has_audio: bool = False
    moov_before_mdat: Optional[bool] = None  # None = 没解析出（非 MP4 或没 moov）
    decode_errors: int = 0   # 全解码报错行数（仅 decode_check 时非 0）

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "category": self.category,
            "repairable": self.repairable,
            "detail": self.detail,
            "size": self.size,
            "duration": self.duration,
            "video_codec": self.video_codec,
            "resolution": self.resolution,
            "has_audio": self.has_audio,
            "moov_before_mdat": self.moov_before_mdat,
            "decode_errors": self.decode_errors,
        }


def _ffprobe_json(ffprobe: str, file_path: str, timeout: int = 60) -> tuple[Optional[dict], str]:
    """跑 ffprobe 拿 JSON。返回 (数据或 None, 错误文本)"""
    import subprocess
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams",
             "-print_format", "json", file_path],
            capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"ffprobe 超时（>{timeout}s）"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if proc.returncode == 0:
        import json
        try:
            return json.loads(proc.stdout.decode("utf-8", "replace")), ""
        except Exception as e:
            return None, f"ffprobe 输出解析失败: {e}"
    err = (proc.stderr or b"").decode("utf-8", "replace").strip()
    return None, err[:300] or f"ffprobe 返回码 {proc.returncode}"


def _extract_probe_summary(data: dict) -> dict:
    """从 ffprobe JSON 提关键字段"""
    out = {"duration": None, "video_codec": None, "resolution": None, "has_audio": False}
    fmt = data.get("format") or {}
    try:
        out["duration"] = float(fmt.get("duration"))
    except (TypeError, ValueError):
        out["duration"] = None
    for s in data.get("streams") or []:
        if s.get("codec_type") == "video" and out["video_codec"] is None:
            out["video_codec"] = s.get("codec_name")
            w, h = s.get("width"), s.get("height")
            if w and h:
                out["resolution"] = f"{w}x{h}"
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
    return out


def _scan_mp4_boxes(file_path: str) -> dict:
    """扫 MP4 顶层 box（只读 box 头 + seek 跳 payload，不读进内存）。

    Returns:
        {"moov": offset|None, "mdat": offset|None,
         "beyond_eof": bool,   # 有 box 声明范围超出文件实际长度（数据被砍断）
         "ok": bool}           # 解析是否顺利
    """
    result = {"moov": None, "mdat": None, "beyond_eof": False, "ok": False}
    try:
        file_size = os.path.getsize(file_path)
        seen: dict[bytes, int] = {}
        with open(file_path, "rb") as f:
            for _ in range(BOX_SCAN_LIMIT):
                header = f.read(8)
                if len(header) < 8:
                    break
                size = struct.unpack(">I", header[:4])[0]
                kind = header[4:8]
                if size == 1:  # 64 位扩展尺寸
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    size = struct.unpack(">Q", ext)[0]
                    header_len = 16
                elif size == 0:  # 延续到文件尾
                    size = file_size - (f.tell() - 8)
                    header_len = 8
                else:
                    header_len = 8
                if size < header_len:
                    break  # 尺寸非法，不是认识的片源
                box_start = f.tell() - header_len
                if kind not in seen:
                    seen[kind] = box_start
                if box_start + size > file_size:
                    # 盒子声明范围超出 EOF = 文件被砍断（典型：mdat 写到一半）
                    result["beyond_eof"] = True
                    break
                if kind == b"mdat" and b"moov" in seen:
                    break  # moov 在前，已结论
                f.seek(size - header_len, os.SEEK_CUR)
        result["moov"] = seen.get(b"moov")
        result["mdat"] = seen.get(b"mdat")
        result["ok"] = True
    except Exception as e:
        logger.debug(f"[media_repair] box 扫描失败 {file_path}: {e}")
    return result


def _scan_mp4_box_order(file_path: str) -> Optional[bool]:
    """moov 是否在 mdat 之前（True=faststart）。非 MP4/无 moov/解析失败返回 None。"""
    boxes = _scan_mp4_boxes(file_path)
    moov_off, mdat_off = boxes["moov"], boxes["mdat"]
    if moov_off is None or mdat_off is None:
        return None
    return moov_off < mdat_off


def _moov_before_mdat(boxes: dict) -> Optional[bool]:
    """从 box 扫描结果取 moov/mdat 先后；任一方缺失返回 None（不猜）。

    🔴 不能直接写 `boxes.get("moov", -1) < boxes.get("mdat", -1)`：
    dict.get 的默认值只在**键不存在**时生效，而 `_scan_mp4_boxes` 总会写入
    这两个键（缺席时值是 None），于是变成 `int < None` → TypeError，
    analyze 接口直接 500（砍断的片正好走这条分支）。
    """
    moov_off, mdat_off = boxes.get("moov"), boxes.get("mdat")
    if moov_off is None or mdat_off is None:
        return None
    return moov_off < mdat_off


async def _decode_check(file_path: str, ffmpeg: str) -> tuple[int, str]:
    """全解码一遍数报错行（-f null -）。返回 (错误行数, 摘要)。

    中段损坏只影响 mdat 里的码流，ffprobe 读元数据照样成功——只有真解码
    才能发现。耗时与完整播放一遍相当，仅按需（修复前诊断/替换前验证）调用。
    """
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-v", "error", "-i", file_path, "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=DECODE_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return -1, f"解码验证超时（>{DECODE_TIMEOUT}s）"
    except asyncio.CancelledError:
        # 任务被取消：wait_for 只取消等待，不会杀子进程。不 kill 的话 ffmpeg
        # 会以孤儿进程继续跑满一个 CPU 直到跑完（REPAIR_TIMEOUT 给的是 1 小时）。
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    lines = [l.strip() for l in (stderr or b"").decode("utf-8", "replace").splitlines() if l.strip()]
    return len(lines), " | ".join(lines[:3])[:200]


async def analyze_file(file_path: str, decode_check: bool = False) -> dict:
    """诊断单文件（只读，不改任何文件）。

    Args:
        file_path: 文件路径
        decode_check: 是否全解码一遍查中段损坏（耗时≈完整播放一遍，
            默认关；修复对话框打开时传 True 拿最准的结论）

    分类与可修性：
    - missing      文件不存在
    - zero_byte    0 字节
    - unreadable   读不了（权限/IO 错误/解码超时）
    - not_video    能探测但没有视频流（修不了）
    - no_moov      moov 索引整体缺失（修不了，需重新下载，详见模块 docstring 实测记录）
    - truncated    moov 还在但数据被砍断（box 声明范围超出 EOF）→ remux 可修
    - corrupt      moov 完好但中段码流损坏（仅 decode_check 能发现）→ remux 可修
    - moov_at_end  moov 在 mdat 后（非 faststart）→ remux 可修
    - healthy      正常

    🔴 ffprobe 只读元信息，砍断/中段损坏它都报正常（2026-10-25 实测），
    因此探测成功后再查 box 范围 +（按需）真解码，见下方注释。
    """
    file_path = str(file_path)
    if not os.path.isfile(file_path):
        return Diagnosis(file_path, "missing", False, "文件不存在（被移走/删除/改名）").to_dict()

    size = os.path.getsize(file_path)
    if size == 0:
        return Diagnosis(file_path, "zero_byte", False, "文件为 0 字节（下载未开始或写入失败）", size=size).to_dict()

    ffprobe = get_ffprobe_path()
    if not ffprobe or not os.path.isfile(ffprobe):
        return Diagnosis(file_path, "unreadable", False, "ffprobe 不可用（服务端未找到可执行文件）", size=size).to_dict()

    ffmpeg = get_ffmpeg_path()
    if decode_check and (not ffmpeg or not os.path.isfile(ffmpeg)):
        # 深检降级：ffmpeg 不可用时不阻塞基础诊断（元信息 + box 扫描仍有效）
        logger.warning("[media_repair] 深检降级：ffmpeg 不可用")
        decode_check = False

    data, err = await asyncio.to_thread(_ffprobe_json, ffprobe, file_path)
    if data is None:
        low = err.lower()
        if "permission" in low or "denied" in low or "being used" in low:
            return Diagnosis(file_path, "unreadable", False, f"文件读不了：{err}", size=size).to_dict()
        # moov 在不在，决定是「可 remux 的数据损坏」还是「不可修的索引缺失」
        boxes = await asyncio.to_thread(_scan_mp4_boxes, file_path)
        if boxes.get("moov") is None:
            return Diagnosis(
                file_path, "no_moov", False,
                "moov 索引缺失（非 faststart 的片子下载中断的典型形态）：ffmpeg 打不开，"
                "也没有索引可从数据流重建（需要 untrunc 类工具加同参数参照文件）。"
                "建议重新下载；库内有同番号完整副本的话可直接替换",
                size=size,
            ).to_dict()
        # moov 还在但探测失败 = 数据被砍断/中段损坏，remux 能捞回完整帧
        return Diagnosis(
            file_path, "truncated", True,
            f"文件数据不完整或中段损坏（索引还在）：{err[:120]}。remux 可尽量捞回完整帧",
            size=size,
        ).to_dict()

    summary = _extract_probe_summary(data)
    if summary["video_codec"] is None:
        return Diagnosis(
            file_path, "not_video", False,
            "能探测但没有视频流（音频文件或容器异常），remux 也修不出画面",
            size=size, **summary,
        ).to_dict()

    # 🔴 ffprobe 只读 moov 元信息：「moov 在但数据被砍断/中段砸烂」它照样报正常
    # （2026-10-25 实测：砍掉 40% 的 faststart 片、中间砸 4KB 0xFF，ffprobe 都
    # 说 healthy）。因此探测成功 ≠ 健康，还要查 box 声明范围 +（按需）真解码。
    boxes = await asyncio.to_thread(_scan_mp4_boxes, file_path)
    if boxes.get("beyond_eof"):
        return Diagnosis(
            file_path, "truncated", True,
            "文件数据被砍断（索引 moov 还在，常见于 faststart 片下载中断）："
            "remux 能救出已写入的全部完整帧",
            size=size, moov_before_mdat=_moov_before_mdat(boxes),
            **summary,
        ).to_dict()

    decode_errors = 0
    if decode_check:
        decode_errors, dec_summary = await _decode_check(file_path, ffmpeg)
        if decode_errors < 0:
            return Diagnosis(file_path, "unreadable", False, dec_summary, size=size, **summary).to_dict()
        if decode_errors > DECODE_ERROR_LIMIT:
            return Diagnosis(
                file_path, "corrupt", True,
                f"中段数据损坏（全解码报错 {decode_errors} 行）：{dec_summary}。"
                "remux 丢弃损坏包后可救回大部分内容",
                size=size, decode_errors=decode_errors,
                moov_before_mdat=_moov_before_mdat(boxes),
                **summary,
            ).to_dict()

    moov_first = None
    if boxes.get("moov") is not None and boxes.get("mdat") is not None:
        moov_first = boxes["moov"] < boxes["mdat"]
    if moov_first is False:
        return Diagnosis(
            file_path, "moov_at_end", True,
            "moov 在数据之后（非 faststart）：播放前要读完整个文件，remux 重排后边下边播/网页播放体验更好",
            size=size, moov_before_mdat=False, **summary,
        ).to_dict()
    detail = "文件正常，无需修复"
    if decode_check and decode_errors > 0:
        detail = f"文件基本正常（全解码有 {decode_errors} 行小报错，多为片尾帧不完整，可不管）"
    return Diagnosis(
        file_path, "healthy", False,
        detail, size=size, moov_before_mdat=moov_first, decode_errors=decode_errors, **summary,
    ).to_dict()


# ---------------------------------------------------------------- 修复

def _build_ffmpeg_cmd(ffmpeg: str, src: str, dst: str, mode: str) -> list[str]:
    """构建修复命令。remux = 不重编码重建索引 + faststart；reencode = 兜底重编码。"""
    suffix = Path(src).suffix.lower()
    # faststart 只对 mp4 系容器有意义
    faststart = suffix in (".mp4", ".mov", ".m4v")
    cmd = [
        ffmpeg, "-hide_banner", "-v", "warning", "-y",
        # 输入侧容错：忽略探测错误 + 丢弃损坏包（截断片能多捞回几帧）
        "-err_detect", "ignore_err",
        "-fflags", "+discardcorrupt",
        "-i", src,
    ]
    if mode == "reencode":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac"]
    else:
        cmd += ["-c", "copy"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd += ["-f", "mp4" if faststart else suffix.lstrip("."), dst]
    return cmd


def _mpv_holds(file_path: str) -> bool:
    """文件是否正被 mpv 播放（psutil 查 cmdline）。查不了就放行。"""
    try:
        import psutil
        target = os.path.normcase(os.path.abspath(file_path))
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "mpv" not in name:
                    continue
                cmdline = proc.info.get("cmdline") or []
                if any(os.path.normcase(str(a)) == target for a in cmdline):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logger.debug(f"[media_repair] mpv 占用检查跳过: {e}")
    return False


async def _run_ffmpeg(cmd: list[str], timeout: int, log: Callable[[str], None],
                      holder: dict) -> tuple[int, str]:
    """跑 ffmpeg 子进程，stderr 逐行进日志。返回 (返回码, 错误摘要)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    holder["proc"] = proc
    err_lines: list[str] = []
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return -1, f"ffmpeg 超时（>{timeout}s）"
    except asyncio.CancelledError:
        # 同上：取消只断等待，不断子进程，必须自己 kill，否则孤儿 ffmpeg 常驻。
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    finally:
        holder["proc"] = None
    text = (stderr or b"").decode("utf-8", "replace")
    for line in text.splitlines():
        line = line.strip()
        if line:
            log(f"ffmpeg: {line}")
            if len(err_lines) < 20:
                err_lines.append(line)
    return proc.returncode or 0, " | ".join(err_lines[:5])[:300]


async def repair_file(
    file_path: str,
    mode: str = "remux",
    verify_decode: bool = True,
    decode_check: bool = False,
    log: Optional[Callable[[str], None]] = None,
    holder: Optional[dict] = None,
) -> dict:
    """修复单文件（安全链见模块 docstring）。原文件先备份后替换。

    Args:
        decode_check: 内部复查是否也全解码（corrupt 形态只有解码能发现，
            🔴 必须由调用方透传，否则复查会把 corrupt 误判成 healthy 而拒绝修复）

    Returns:
        {"status": "ok"|"error", ..., "backup_path": 原文件备份位置}
    """
    log = log or (lambda _msg: None)
    holder = holder if holder is not None else {}
    file_path = str(file_path)
    t0 = time.monotonic()

    if mode not in MODES:
        return {"status": "error", "message": f"未知修复模式 {mode}（可选：{'/'.join(MODES)}）"}

    src = Path(file_path)
    if not src.is_file():
        return {"status": "error", "message": "文件不存在"}
    if _mpv_holds(file_path):
        return {"status": "error", "message": "文件正在 mpv 中播放，请先退出播放再修复"}

    diag = await analyze_file(file_path, decode_check=decode_check)
    if not diag.get("repairable"):
        return {"status": "error", "message": f"无需修复或修不了：{diag.get('detail')}",
                "category": diag.get("category")}

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return {"status": "error", "message": "ffmpeg 不可用（服务端未找到可执行文件）"}

    tmp_dir = src.parent / REPAIR_TMP_DIR
    backup_dir = src.parent / REPAIR_BACKUP_DIR
    tmp_out = tmp_dir / f".{src.name}.repair{src.suffix}"
    backup_path: Optional[Path] = None
    try:
        tmp_dir.mkdir(exist_ok=True)
        log(f"开始修复（{mode}）：{file_path}（{diag.get('size', 0) / 1048576:.1f} MB，形态：{diag.get('category')}）")

        # 1) ffmpeg 修复到临时文件
        cmd = _build_ffmpeg_cmd(ffmpeg, str(src), str(tmp_out), mode)
        log("执行：" + " ".join(cmd))
        rc, err = await _run_ffmpeg(cmd, REPAIR_TIMEOUT, log, holder)
        if rc != 0:
            return {"status": "error", "message": f"ffmpeg 修复失败：{err or f'返回码 {rc}'}"}
        if not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            return {"status": "error", "message": "ffmpeg 没有产出有效文件"}

        # 2) ffprobe 验证临时文件
        data, perr = await asyncio.to_thread(_ffprobe_json, get_ffprobe_path(), str(tmp_out))
        if data is None:
            return {"status": "error", "message": f"修复产物验证失败（ffprobe 打不开）：{perr}"}
        fixed = _extract_probe_summary(data)
        if fixed["video_codec"] is None:
            return {"status": "error", "message": "修复产物没有视频流，已放弃替换"}
        if not fixed["duration"] or fixed["duration"] <= 0:
            return {"status": "error", "message": "修复产物时长为 0，已放弃替换"}
        orig_dur = diag.get("duration")
        if orig_dur and fixed["duration"] < orig_dur * MIN_DURATION_RATIO:
            return {"status": "error",
                    "message": f"恢复内容过少（原 {orig_dur:.0f}s → 修复后 {fixed['duration']:.0f}s），已放弃替换"}

        # 3) 可选全解码验证
        decode_errors = 0
        if verify_decode:
            log("全解码验证中（-f null -）...")
            dec_cmd = [ffmpeg, "-hide_banner", "-v", "error", "-i", str(tmp_out), "-f", "null", "-"]
            dec_proc = await asyncio.create_subprocess_exec(
                *dec_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            holder["proc"] = dec_proc
            try:
                _, dec_err = await asyncio.wait_for(dec_proc.communicate(), timeout=DECODE_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    dec_proc.kill()
                except ProcessLookupError:
                    pass
                return {"status": "error", "message": f"解码验证超时（>{DECODE_TIMEOUT}s）"}
            except asyncio.CancelledError:
                try:
                    dec_proc.kill()
                except ProcessLookupError:
                    pass
                raise
            finally:
                holder["proc"] = None
            decode_errors = len([l for l in (dec_err or b"").decode("utf-8", "replace").splitlines() if l.strip()])
            if decode_errors > DECODE_ERROR_LIMIT:
                return {"status": "error",
                        "message": f"解码验证报错 {decode_errors} 行（>{DECODE_ERROR_LIMIT}），已放弃替换"}

        # 4) 备份原文件 → 同目录 .mdcx-broken/（同卷 rename，不留副本占双倍空间）
        backup_dir.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"{src.stem}.broken-{stamp}{src.suffix}"
        os.rename(str(src), str(backup_path))
        log(f"原文件已备份到：{backup_path}")

        # 5) 原子替换；替换失败要把备份改回原位，绝不让原文件「消失」
        try:
            os.replace(str(tmp_out), str(src))
        except Exception:
            try:
                os.rename(str(backup_path), str(src))
            except Exception:
                pass
            raise
        ms = int((time.monotonic() - t0) * 1000)
        log(f"修复完成：{file_path}（{fixed['duration']:.0f}s，{fixed['resolution'] or '?'}，耗时 {ms / 1000:.0f}s）")
        return {
            "status": "ok",
            "message": "修复成功",
            "mode": mode,
            "category": diag.get("category"),
            "backup_path": str(backup_path),
            "old_size": diag.get("size"),
            "new_size": src.stat().st_size,
            "duration_before": orig_dur,
            "duration_after": fixed["duration"],
            "decode_errors": decode_errors,
            "duration_ms": ms,
        }
    except Exception as e:
        logger.error(f"[media_repair] 修复异常 {file_path}: {e}", exc_info=True)
        return {"status": "error", "message": f"修复异常：{type(e).__name__}: {e}"}
    finally:
        # 临时文件清理（替换成功后 tmp_out 已不在）
        try:
            if tmp_out.is_file():
                tmp_out.unlink()
            if tmp_dir.is_dir() and not any(tmp_dir.iterdir()):
                tmp_dir.rmdir()
        except Exception:
            pass


# ---------------------------------------------------------------- 任务注册表

@dataclass
class RepairJob:
    id: str
    file_path: str
    mode: str
    verify_decode: bool
    decode_check: bool = False   # 内部复查是否全解码（corrupt 形态需要）
    status: str = "queued"          # queued / running / success / failed / cancelled
    stage: str = "排队中"
    log_lines: deque = field(default_factory=lambda: deque(maxlen=JOB_LOG_LINES))
    result: Optional[dict] = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel_requested: bool = False  # 用户点了取消（杀进程后任务以 cancelled 收尾）
    holder: dict = field(default_factory=dict)  # 持 ffmpeg 子进程/task 引用（取消用）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "mode": self.mode,
            "verify_decode": self.verify_decode,
            "decode_check": self.decode_check,
            "status": self.status,
            "stage": self.stage,
            "log": list(self.log_lines),
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


_JOBS: "OrderedDict[str, RepairJob]" = OrderedDict()
_SEM = asyncio.Semaphore(MAX_CONCURRENT_REPAIRS)
_job_seq = 0


def _new_job_id() -> str:
    global _job_seq
    _job_seq += 1
    return f"rp{int(time.time() * 1000):x}{_job_seq:03d}"


def _evict_jobs() -> None:
    """淘汰最旧的已完成任务，防内存无限增长"""
    finished = [k for k, j in _JOBS.items() if j.status in ("success", "failed", "cancelled")]
    while len(finished) > JOB_HISTORY:
        _JOBS.pop(finished.pop(0), None)


async def _run_job(job: RepairJob) -> None:
    async with _SEM:
        if job.status == "cancelled":
            return
        job.status = "running"
        job.stage = "诊断/修复中"
        job.log_lines.append(f"[{time.strftime('%H:%M:%S')}] 任务开始")

        def _log(msg: str) -> None:
            job.log_lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

        try:
            result = await repair_file(
                job.file_path, mode=job.mode, verify_decode=job.verify_decode,
                decode_check=job.decode_check,
                log=_log, holder=job.holder,
            )
            job.result = result
            if job.cancel_requested:
                # 取消进程会让 ffmpeg 非零退出；以取消收尾而不是报失败
                job.status = "cancelled"
                job.stage = "已取消"
            elif result.get("status") == "ok":
                job.status = "success"
                job.stage = "修复成功"
            else:
                job.status = "failed"
                job.stage = "修复失败"
                job.error = result.get("message", "")
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "已取消"
            raise
        except Exception as e:
            job.status = "failed"
            job.stage = "修复异常"
            job.error = f"{type(e).__name__}: {e}"
        finally:
            job.finished_at = time.time()
            _evict_jobs()


async def start_repair_job(
    file_path: str, mode: str = "remux", verify_decode: bool = True, decode_check: bool = False,
) -> dict:
    """创建修复任务（后台执行，立即返回）。并发 1，其余排队。"""
    global _job_seq
    job = RepairJob(
        id=_new_job_id(), file_path=str(file_path), mode=mode,
        verify_decode=verify_decode, decode_check=decode_check,
    )
    _JOBS[job.id] = job
    _evict_jobs()
    task = asyncio.create_task(_run_job(job))
    job.holder["task"] = task
    logger.info(f"[media_repair] 任务入队 {job.id}: {file_path} mode={mode}")
    return job.to_dict()


def get_job(job_id: str) -> Optional[dict]:
    job = _JOBS.get(job_id)
    return job.to_dict() if job else None


def list_jobs(limit: int = 20) -> list[dict]:
    """最近的任务（新的在前）"""
    items = list(_JOBS.values())[-limit:]
    return [j.to_dict() for j in reversed(items)]


def cancel_job(job_id: str) -> dict:
    """取消任务：queued 直接标记；running 杀 ffmpeg 子进程 + cancel task。"""
    job = _JOBS.get(job_id)
    if not job:
        return {"status": "error", "message": "任务不存在"}
    if job.status in ("success", "failed", "cancelled"):
        return {"status": "error", "message": f"任务已结束（{job.status}）"}
    job.cancel_requested = True
    proc = job.holder.get("proc")
    if proc is not None:
        try:
            proc.kill()
        except Exception:
            pass
    task = job.holder.get("task")
    if task is not None and not task.done():
        task.cancel()
    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "已取消（未开始）"
        job.finished_at = time.time()
    job.log_lines.append(f"[{time.strftime('%H:%M:%S')}] 用户取消任务")
    return {"status": "ok", "message": "已取消"}


__all__ = [
    "analyze_file", "repair_file", "start_repair_job", "get_job", "list_jobs",
    "cancel_job", "MODES", "Diagnosis",
]
