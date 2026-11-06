# -*- coding: utf-8 -*-
"""外挂字幕质检：质量打分 + 版本错配判定 + 落盘登记。

动机
----
线上字幕最常见的两种「静默错误」：

1. **配错版本**：字幕是同番号的另一版本（通常版 / 完全版 / 剪辑版），
   播放器照样能加载、中文也正常，但看到后半段完全对不上。
   最可靠的结构化信号是**末条字幕时间 vs 视频真实时长**：一部 120 分钟
   的片子，字幕末条在 45 分钟，基本可以断定不是同一个版本。
2. **乱码 / 空壳**：编码嗅探选错、文件只有几条、时间轴倒退或整片重叠。
   现有 ``subtitle_matcher`` 只负责编码识别，不评价内容质量。

本模块只做**离线只读分析**，不改字幕文件、不自动替换、不拦截播放：
调用方（播放器页面的「字幕质检」按钮）拿到报告自行决定。
结果按字幕路径写入 ``<data>/subtitle_quality.json``（原子写），便于长期留痕。

思路借鉴 avm 的字幕质检，独立实现，未复制任何源码。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.utils.atomic_write import atomic_read_json, atomic_write_json

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "subtitle_quality.json"
_registry_lock = threading.Lock()

#: SRT / VTT 时间轴（允许省略小时、允许逗号或点做毫秒分隔）。
_SRT_VTT_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
)
_ASS_RE = re.compile(
    r"Dialogue:\s*\d+,\s*(\d+):(\d{2}):(\d{2})[.](\d{1,2})\s*,\s*"
    r"(\d+):(\d{2}):(\d{2})[.](\d{1,2})\s*,"
)
_LRC_RE = re.compile(r"\[(\d{1,3}):(\d{2})[.](\d{1,2})\]\s*(.*)")

#: 明显的乱码特征（解码替换符 + 经典的 GBK/UTF-8 互转垃圾串）
_MOJIBAKE_MARKERS = ("\ufffd", "锟斤拷", "烫烫烫", "□□", "锘匡豢")


def _hms(h: Optional[str], m: str, s: str, frac: str) -> float:
    """把时间字段转秒。frac 按位数归一（,500 → 0.5；,50 → 0.50）。"""
    hours = int(h) if h else 0
    minutes = int(m)
    seconds = int(s)
    ms = int(frac) / (10 ** len(frac))
    return hours * 3600 + minutes * 60 + seconds + ms


# ----------------------------------------------------------------------
# 时间轴解析
# ----------------------------------------------------------------------

def parse_cues(text: str, ext: str = ".srt") -> list[dict]:
    """解析字幕为 ``[{start, end, text}, ...]``（秒）。

    支持 .srt / .vtt / .ass / .ssa / .lrc；无法可靠解析的格式返回空列表，
    由调用方标记 ``unparseable``（**不猜**，避免用错误时间轴误判版本）。
    """
    if not text:
        return []
    ext = (ext or "").lower()
    if ext in (".ass", ".ssa"):
        return _parse_ass(text)
    if ext == ".lrc":
        return _parse_lrc(text)
    if ext in (".srt", ".vtt", ".sub"):
        return _parse_srt_vtt(text)
    return []


def _parse_srt_vtt(text: str) -> list[dict]:
    cues: list[dict] = []
    # 空行分块；VTT 的 NOTE / STYLE 块没有时间轴，自然被跳过
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        m = _SRT_VTT_RE.search(block)
        if not m:
            continue
        sh, sm, ss, sf, eh, em, es, ef = m.groups()
        start = _hms(sh, sm, ss, sf)
        end = _hms(eh, em, es, ef)
        # 时间轴行之后的全部行都是正文（可能多行）
        body = block[m.end():].strip("\n")
        # 去掉 VTT 的位置/对齐等设置尾巴不影响文本统计
        cues.append({"start": start, "end": end, "text": body.strip()})
    return cues


def _parse_ass(text: str) -> list[dict]:
    cues: list[dict] = []
    for line in text.splitlines():
        m = _ASS_RE.match(line.strip())
        if not m:
            continue
        sh, sm, ss, sf, eh, em, es, ef = m.groups()
        parts = line.split(",", 9)
        body = parts[9] if len(parts) > 9 else ""
        cues.append({
            "start": _hms(sh, sm, ss, sf),
            "end": _hms(eh, em, es, ef),
            "text": body.strip(),
        })
    return cues


def _parse_lrc(text: str) -> list[dict]:
    """LRC 只有起点：end 取下一条起点，末条补 4 秒（歌词行典型时长）。"""
    marks: list[tuple[float, str]] = []
    for line in text.splitlines():
        m = _LRC_RE.match(line.strip())
        if m:
            marks.append((int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / (10 ** len(m.group(3))),
                          m.group(4).strip()))
    cues = []
    for i, (start, body) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else start + 4.0
        cues.append({"start": start, "end": end, "text": body})
    return cues


# ----------------------------------------------------------------------
# 质检
# ----------------------------------------------------------------------

def inspect_text(
    text: str,
    ext: str = ".srt",
    video_duration_s: Optional[float] = None,
) -> dict:
    """对字幕文本做质检，返回报告（纯函数，不读文件、不落盘）。

    ``video_duration_s`` 为视频真实秒数；传 None 时跳过时长贴合判定，
    报告里以 ``unknown`` 标注，绝不拿猜测值硬判「配错版本」。
    """
    cues = parse_cues(text, ext)
    report: dict[str, Any] = {
        "cue_count": len(cues),
        "first_start_s": None,
        "last_end_s": None,
        "video_duration_s": video_duration_s,
        "duration_fit": None,          # 末条 / 视频时长
        "duration_deviation": None,    # |末条-时长| / 时长
        "score": 0,
        "verdict": "unparseable",
        "issues": [],
        "encoding": None,
    }
    if not cues:
        report["issues"].append("未能解析出时间轴，无法判定质量（格式可能不受支持）")
        return report

    starts = [c["start"] for c in cues]
    ends = [c["end"] for c in cues]
    report["first_start_s"] = round(min(starts), 2)
    report["last_end_s"] = round(max(ends), 2)

    backwards = sum(1 for i in range(1, len(cues)) if starts[i] < starts[i - 1])
    overlaps = sum(
        1 for i in range(1, len(cues))
        if cues[i]["start"] < cues[i - 1]["end"] - 0.05
    )
    empty_text = sum(1 for c in cues if not c["text"].strip())
    invalid_len = sum(1 for c in cues if c["end"] <= c["start"])

    body_text = "\n".join(c["text"] for c in cues)
    bad_chars = sum(body_text.count(mk) for mk in _MOJIBAKE_MARKERS)
    mojibake_ratio = bad_chars / max(len(body_text), 1)

    score = 25  # 有时间轴
    if len(cues) >= 100:
        score += 15
    elif len(cues) >= 20:
        score += 12
    elif len(cues) >= 5:
        score += 6
    else:
        report["issues"].append(f"字幕条数过少（{len(cues)} 条），可能是残缺文件")

    if backwards == 0 and invalid_len == 0:
        score += 15
    else:
        report["issues"].append(f"时间轴异常：{backwards} 条倒退、{invalid_len} 条结束早于开始")

    if overlaps / len(cues) < 0.05:
        score += 10
    else:
        report["issues"].append(f"相邻字幕重叠过多（{overlaps} 条）")

    if empty_text / len(cues) < 0.05:
        score += 10
    else:
        report["issues"].append(f"空文本条目 {empty_text} 条")

    if mojibake_ratio < 0.002:
        score += 10
    else:
        report["issues"].append("检测到替换字符/乱码特征，编码可能识别错误")

    mismatch = False
    if video_duration_s and video_duration_s > 0:
        fit = max(ends) / video_duration_s
        deviation = abs(1.0 - fit)
        report["duration_fit"] = round(fit, 4)
        report["duration_deviation"] = round(deviation, 4)
        if deviation <= 0.03:
            score += 15
        elif deviation <= 0.10:
            score += 10
        elif deviation <= 0.20:
            score += 5
            report["issues"].append(
                "末条字幕与视频时长偏差 %.0f%%，可能是删减/加长版" % (deviation * 100)
            )
        else:
            mismatch = True
            report["issues"].append(
                "末条字幕 %s，视频 %s，偏差 %.0f%% —— 疑似配错版本"
                % (_fmt_time(max(ends)), _fmt_time(video_duration_s), deviation * 100)
            )
    else:
        report["issues"].append("未取得视频时长，跳过时长贴合校验")

    # 严重内容问题封顶：否则「一半条目是空行」仍可能靠其它项凑到 90 分，
    # 分数与 verdict(suspect) 自相矛盾，用户会误以为字幕没问题。
    if empty_text / len(cues) >= 0.2:
        score = min(score, 55)
    if mojibake_ratio >= 0.01:
        score = min(score, 55)
    # 「配错版本」是最严重的问题：其它维度全满分也不能让它看起来像 80 分的好字幕。
    if mismatch:
        score = min(score, 45)

    report["score"] = int(score)
    report["backwards"] = backwards
    report["overlaps"] = overlaps
    report["empty_text"] = empty_text
    report["mojibake_ratio"] = round(mojibake_ratio, 5)

    if mismatch:
        report["verdict"] = "mismatch"
    elif score < 60 or mojibake_ratio >= 0.01 or empty_text / len(cues) >= 0.2:
        report["verdict"] = "suspect"
    elif video_duration_s is None:
        report["verdict"] = "unknown"
    else:
        report["verdict"] = "good"
    return report


def _fmt_time(seconds: float) -> str:
    s = int(max(seconds, 0))
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


# ----------------------------------------------------------------------
# 落盘登记
# ----------------------------------------------------------------------

def _registry_path() -> Path:
    from app.config.manager import get_config_manager
    manager = get_config_manager()
    data_dir = getattr(manager.computed, "data_dir", Path("data"))
    return Path(data_dir) / _REGISTRY_FILENAME


def registry_path() -> Path:
    """质检登记文件位置（对外只读查询用）。"""
    return _registry_path()


def load_registry() -> dict:
    """读取质检登记（文件损坏时返回空登记，不让播放页崩掉）。"""
    data = atomic_read_json(_registry_path(), default=None)
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"version": 1, "items": {}}
    return data


def record_to_registry(path: str | Path, report: dict) -> None:
    """把一次质检结果写入登记（原子写 + 进程内锁）。"""
    key = str(Path(path).resolve())
    with _registry_lock:
        reg = load_registry()
        reg["items"][key] = {
            "score": report.get("score"),
            "verdict": report.get("verdict"),
            "cue_count": report.get("cue_count"),
            "last_end_s": report.get("last_end_s"),
            "video_duration_s": report.get("video_duration_s"),
            "duration_deviation": report.get("duration_deviation"),
            "issues": report.get("issues", [])[:8],
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            atomic_write_json(_registry_path(), reg)
        except OSError as e:
            # 登记失败不应影响本次质检结果返回
            logger.warning("[subtitle-quality] 登记写入失败: %s", e)


def registry_entries(paths: list[str | Path]) -> dict[str, dict]:
    """按路径批量取历史登记（供前端「上次质检」展示）。"""
    reg = load_registry()
    items = reg["items"]
    # key 统一用 resolve 后的规范化路径，与 record_to_registry 写入口径一致，
    # 否则 Windows 上大小写/短路径差异会让「明明登记过却查不到」。
    out: dict[str, dict] = {}
    for p in paths:
        key = str(Path(p).resolve())
        if key in items:
            out[key] = items[key]
    return out


def check_subtitle_file(
    path: str | Path,
    video_duration_s: Optional[float] = None,
    *,
    record: bool = True,
) -> dict:
    """读取字幕文件 → 质检 → 登记。返回报告（含 path/filename/size）。"""
    from app.services.subtitle_matcher import read_subtitle_text

    p = Path(path)
    report: dict[str, Any] = {
        "path": str(p),
        "filename": p.name,
        "size": p.stat().st_size if p.is_file() else 0,
    }
    try:
        text, enc = read_subtitle_text(p)
        report.update(inspect_text(text, p.suffix.lower(), video_duration_s))
        report["encoding"] = enc
    except OSError as e:
        report.update({
            "score": 0, "verdict": "unreadable", "cue_count": 0,
            "issues": ["字幕文件读取失败: %s" % e],
        })
    if record:
        record_to_registry(p, report)
    return report


def probe_video_duration(file_path: str, fallback_minutes: Optional[float] = None) -> tuple[Optional[float], str]:
    """取视频真实时长（秒）。优先 ffprobe，失败时用库里的分钟数换算。

    返回 ``(秒数 或 None, 来源字符串)``。库里的 ``duration`` 是**分钟**
    （NFO ``<duration>`` 口径），故需要 ×60；ffprobe 的 ``format=duration`` 是秒。
    """
    try:
        from app.services.chapter_marker import _get_video_duration
        sec = _get_video_duration(file_path)
        if sec and sec > 0:
            return float(sec), "ffprobe"
    except Exception as e:
        logger.debug("[subtitle-quality] ffprobe 取时长失败: %s", e)
    if fallback_minutes and float(fallback_minutes) > 0:
        return float(fallback_minutes) * 60.0, "movie.duration(分钟)×60"
    return None, "unavailable"
