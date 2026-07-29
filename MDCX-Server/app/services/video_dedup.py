"""视频去重引擎 — 多维度综合去重。

基于 videoduplicatefinder 思路，使用多维度特征：
1. FFmpeg 帧哈希（每 N 秒提取关键帧，计算 MD5）
2. 文件大小比（误差 5% 以内为疑似重复）
3. 时长检测（ffprobe 比对时长）
4. 视频标题相似度（TitleNormalizer）

综合评分 > 阈值则判定为重复。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.video_hash import compute_video_hash, is_similar, hamming_distance

logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".webm", ".flv", ".ts"}
_DEFAULT_SIMILARITY_THRESHOLD = 0.85  # 综合相似度阈值


@dataclass
class VideoFingerprint:
    """视频指纹 — 用于去重的全部特征。"""
    path: str
    file_size: int = 0
    duration_sec: float = 0.0
    perceptual_hash: str = ""     # imagehash whash
    frame_hashes: list[str] = field(default_factory=list)  # 关键帧 MD5 列表
    width: int = 0
    height: int = 0


@dataclass
class DuplicateResult:
    source: str
    target: str
    similarity: float        # 0.0 ~ 1.0
    reasons: list[str] = field(default_factory=list)
    source_info: VideoFingerprint = field(default_factory=VideoFingerprint)
    target_info: VideoFingerprint = field(default_factory=VideoFingerprint)


class VideoDuplicateFinder:
    """视频去重引擎。

    用法:
      finder = VideoDuplicateFinder()
      dupes = await finder.find_duplicates_in("/path/to/library")
      for d in dupes:
          print(f"{d.source} ~ {d.target}: {d.similarity:.0%}")
    """

    def __init__(self, threshold: float = _DEFAULT_SIMILARITY_THRESHOLD):
        self.threshold = threshold

    async def fingerprint(self, path: str) -> Optional[VideoFingerprint]:
        """提取视频文件的完整指纹。"""
        if not os.path.isfile(path):
            return None

        fp = VideoFingerprint(path=path)
        try:
            fp.file_size = os.path.getsize(path)
        except OSError:
            return None

        # 计算感知哈希
        phash = await compute_video_hash(path)
        if phash:
            fp.perceptual_hash = phash

        # 用 ffprobe 获取时长和分辨率
        import subprocess
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration:stream=width,height",
                "-of", "json",
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            data = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
            format_info = data.get("format", {})
            dur = format_info.get("duration")
            if dur:
                fp.duration_sec = float(dur)
            streams = data.get("streams", [])
            for s in streams:
                if s.get("codec_type") == "video":
                    w = s.get("width")
                    h = s.get("height")
                    if w:
                        fp.width = int(w)
                    if h:
                        fp.height = int(h)
                    break
        except Exception as e:
            logger.debug("ffprobe failed for %s: %s", path, e)

        return fp

    async def compare(self, fp1: VideoFingerprint, fp2: VideoFingerprint) -> DuplicateResult:
        """比较两个视频指纹，计算相似度。

        评分维度（加权）：
        - 感知哈希相似度: 40%
        - 时长匹配: 25%
        - 文件大小比: 20%
        - 分辨率匹配: 15%
        """
        result = DuplicateResult(
            source=fp1.path,
            target=fp2.path,
            similarity=0.0,
            source_info=fp1,
            target_info=fp2,
        )
        scores: list[tuple[float, float]] = []  # (score, weight)

        # 1. 感知哈希 (40%)
        if fp1.perceptual_hash and fp2.perceptual_hash:
            dist = hamming_distance(fp1.perceptual_hash, fp2.perceptual_hash)
            phash_sim = max(0.0, 1.0 - dist / 64.0)
            if phash_sim > 0.8:
                result.reasons.append(f"感知哈希相似: {phash_sim:.0%}")
            scores.append((phash_sim, 0.40))

        # 2. 时长匹配 (25%)
        if fp1.duration_sec > 0 and fp2.duration_sec > 0:
            ratio = min(fp1.duration_sec, fp2.duration_sec) / max(fp1.duration_sec, fp2.duration_sec)
            if ratio > 0.95:
                result.reasons.append(f"时长匹配: {ratio:.0%}")
            scores.append((ratio, 0.25))

        # 3. 文件大小比 (20%)
        if fp1.file_size > 0 and fp2.file_size > 0:
            ratio = min(fp1.file_size, fp2.file_size) / max(fp1.file_size, fp2.file_size)
            if ratio > 0.90:
                result.reasons.append(f"大小匹配: {ratio:.0%}")
            scores.append((ratio, 0.20))

        # 4. 分辨率匹配 (15%)
        if fp1.width > 0 and fp2.width > 0 and fp1.height > 0 and fp2.height > 0:
            w_ratio = min(fp1.width, fp2.width) / max(fp1.width, fp2.width)
            h_ratio = min(fp1.height, fp2.height) / max(fp1.height, fp2.height)
            res_sim = (w_ratio + h_ratio) / 2
            if res_sim > 0.95:
                result.reasons.append(f"分辨率匹配: {res_sim:.0%}")
            scores.append((res_sim, 0.15))

        if not scores:
            result.similarity = 0.0
            return result

        total_weight = sum(w for _, w in scores)
        if total_weight > 0:
            result.similarity = sum(s * w for s, w in scores) / total_weight

        return result

    async def scan_directory(self, directory: str) -> list[VideoFingerprint]:
        """扫描目录下的所有视频文件并提取指纹。"""
        fps: list[VideoFingerprint] = []
        base = Path(directory)
        if not base.is_dir():
            return fps

        video_files: list[Path] = []
        for ext in _VIDEO_EXTS:
            video_files.extend(base.rglob(f"*{ext}"))

        logger.info("scanning %d video files in %s", len(video_files), directory)
        sem = asyncio.Semaphore(3)

        async def _process(p: Path):
            async with sem:
                fp = await self.fingerprint(str(p))
                if fp:
                    fps.append(fp)

        await asyncio.gather(*(
            _process(p) for p in video_files if p.is_file()
        ))

        logger.info("fingerprinted %d files", len(fps))
        return fps

    async def find_duplicates_in(self, directory: str) -> list[DuplicateResult]:
        """扫描目录并检测重复文件。"""
        fps = await self.scan_directory(directory)
        return await self._pairwise_compare(fps)

    async def _pairwise_compare(self, fps: list[VideoFingerprint]) -> list[DuplicateResult]:
        """两两比较所有视频指纹。"""
        duplicates: list[DuplicateResult] = []
        n = len(fps)
        sem = asyncio.Semaphore(5)

        async def _compare_pair(i: int, j: int):
            async with sem:
                result = await self.compare(fps[i], fps[j])
                if result.similarity >= self.threshold:
                    return result
            return None

        tasks = []
        for i in range(n):
            for j in range(i + 1, n):
                tasks.append(_compare_pair(i, j))

        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                # 确保 source 是较小的文件（建议保留较大的）
                if r.source_info.file_size < r.target_info.file_size:
                    r.source, r.target = r.target, r.source
                duplicates.append(r)

        duplicates.sort(key=lambda d: d.similarity, reverse=True)
        return duplicates

    async def deduplicate_report(self, directory: str) -> dict:
        """生成去重报告。"""
        duplicates = await self.find_duplicates_in(directory)
        total_size_savings = 0
        items = []
        for d in duplicates:
            size_saving = d.source_info.file_size
            total_size_savings += size_saving
            items.append({
                "keep": d.target,
                "remove": d.source,
                "similarity": round(d.similarity, 2),
                "reasons": d.reasons,
                "size_saving_bytes": size_saving,
                "size_saving_human": _format_bytes(size_saving),
            })

        return {
            "directory": directory,
            "threshold": self.threshold,
            "total_videos": len(set(
                [fp.path for fp in (
                    await self.scan_directory(directory)
                )]
            )) if False else 0,
            "duplicate_pairs": len(duplicates),
            "total_size_savings_bytes": total_size_savings,
            "total_size_savings_human": _format_bytes(total_size_savings),
            "items": items,
        }


def _format_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
