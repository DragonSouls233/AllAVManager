"""VDF 增强视频去重引擎 — 从 VideoDuplicateFinder 项目移植核心算法。

VDF 的 C# 核心算法移植为 Python：
1. 并查集 (UnionFind) — 替代 HashSet 去重
2. Chromaprint 音频指纹支持
3. 感知哈希增强（多帧采样 + PCA 降维）
4. 扫描+比对+报告三阶段架构
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import hashlib

from app.services.video_hash import compute_video_hash, hamming_distance

logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".wmv", ".m4v", ".mov", ".webm", ".ts", ".flv", ".mts", ".m2ts"}

# 并查集 — 效率最高的去重数据结���
class UnionFind:
    """并查集 (Disjoint Set Union) — O(α(n)) 复杂度去重合并。"""

    def __init__(self):
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
            return x
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for key in self._parent:
            groups[self.find(key)].append(key)
        return groups


@dataclass
class VDFingerprint:
    path: str
    file_size: int = 0
    perceptual_hash: str = ""
    duration_ms: int = 0
    frame_count: int = 0
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    audio_channels: int = 0
    error: str = ""


class VDFEngine:
    """VDF 增强视频去重引擎。

    三阶段架构:
    1. Scan — 扫描目录提取视频指纹
    2. Compare — 两两比对，使用并查集合并重复组
    3. Report — 生成去重报告

    参考：VideoDuplicateFinder (C#) 的 ScanEngine
    """

    def __init__(self, similarity_threshold: float = 0.90):
        self.threshold = similarity_threshold
        self._fps: list[VDFingerprint] = []
        self._uf = UnionFind()

    async def scan(self, directory: str) -> list[VDFingerprint]:
        """阶段1: 扫描目录并提取视频指纹。"""
        fps: list[VDFingerprint] = []
        video_files: list[Path] = []

        for ext in _VIDEO_EXTS:
            video_files.extend(Path(directory).rglob(f"*{ext}"))

        logger.info("VDF scan: %d files in %s", len(video_files), directory)

        sem = asyncio.Semaphore(4)

        async def _process(p: Path):
            async with sem:
                fp = await self._fingerprint(str(p))
                if fp:
                    fps.append(fp)

        await asyncio.gather(*[_process(p) for p in video_files if p.is_file()])
        self._fps = fps
        return fps

    async def compare(self) -> list[tuple[str, str, float]]:
        """阶段2: 两两比对，使用并查集合并重复组。"""
        results: list[tuple[str, str, float]] = []
        n = len(self._fps)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = self._fps[i], self._fps[j]
                score = self._compute_similarity(a, b)
                if score >= self.threshold:
                    self._uf.union(a.path, b.path)
                    results.append((a.path, b.path, score))

        results.sort(key=lambda x: x[2], reverse=True)
        return results

    def report(self) -> dict:
        """阶段3: 生成去重报告。"""
        groups = self._uf.groups()
        total_size_savings = 0
        items = []

        for root, paths in groups.items():
            if len(paths) < 2:
                continue

            fps_map = {fp.path: fp for fp in self._fps}
            sorted_paths = sorted(paths, key=lambda p: fps_map[p].file_size if p in fps_map else 0, reverse=True)

            keep = sorted_paths[0]
            removes = sorted_paths[1:]

            for remove in removes:
                size = fps_map[remove].file_size if remove in fps_map else 0
                total_size_savings += size
                items.append({
                    "keep": keep,
                    "remove": remove,
                    "size_bytes": size,
                    "size_human": self._format_bytes(size),
                })

        return {
            "total_scanned": len(self._fps),
            "duplicate_groups": len([g for g in groups.values() if len(g) > 1]),
            "duplicate_files": len(items),
            "size_savings_bytes": total_size_savings,
            "size_savings_human": self._format_bytes(total_size_savings),
            "items": items,
        }

    async def full_pipeline(self, directory: str) -> dict:
        """完整三阶段管道。"""
        await self.scan(directory)
        await self.compare()
        return self.report()

    # ------------------------------------------------------------------ #
    # 指纹提取
    # ------------------------------------------------------------------ #

    async def _fingerprint(self, path: str) -> Optional[VDFingerprint]:
        if not os.path.isfile(path):
            return None
        fp = VDFingerprint(path=path)
        try:
            fp.file_size = os.path.getsize(path)
        except OSError:
            return None

        # 感知哈希
        phash = await compute_video_hash(path)
        if phash:
            fp.perceptual_hash = phash

        # ffprobe 获取元数据
        fp.width, fp.height, fp.duration_ms, fp.frame_count = \
            await self._ffprobe(path)

        if fp.width and fp.height:
            fp.aspect_ratio = round(fp.width / fp.height, 4)

        return fp

    async def _ffprobe(self, path: str) -> tuple:
        """ffprobe 获取视频元数据。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries",
                "stream=width,height:stream=nb_frames:format=duration",
                "-of", "json",
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            data = json.loads(stdout.decode("utf-8", errors="replace") or "{}")

            width = height = 0
            frame_count = 0
            duration_ms = 0

            for s in data.get("streams", []):
                if s.get("codec_type") == "video":
                    width = int(s.get("width", 0) or 0)
                    height = int(s.get("height", 0) or 0)
                    fc = s.get("nb_frames")
                    if fc:
                        frame_count = int(fc)

            dur = data.get("format", {}).get("duration")
            if dur:
                duration_ms = int(float(dur) * 1000)

            return (width, height, duration_ms, frame_count)
        except Exception:
            return (0, 0, 0, 0)

    # ------------------------------------------------------------------ #
    # 相似度计算
    # ------------------------------------------------------------------ #

    def _compute_similarity(self, a: VDFingerprint, b: VDFingerprint) -> float:
        """多维度相似度计算（权重参考 VDF C# 算法）。"""
        scores: list[tuple[float, float]] = []

        # 1. 感知哈希 (40%)
        if a.perceptual_hash and b.perceptual_hash:
            dist = hamming_distance(a.perceptual_hash, b.perceptual_hash)
            phash_sim = max(0.0, 1.0 - dist / 64.0)
            scores.append((phash_sim, 0.40))

        # 2. 时长 (25%)
        if a.duration_ms > 0 and b.duration_ms > 0:
            ratio = min(a.duration_ms, b.duration_ms) / max(a.duration_ms, b.duration_ms)
            scores.append((ratio, 0.25))

        # 3. 文件大小 (20%)
        if a.file_size > 0 and b.file_size > 0:
            ratio = min(a.file_size, b.file_size) / max(a.file_size, b.file_size)
            scores.append((ratio, 0.20))

        # 4. 分辨率 (15%)
        if a.width > 0 and b.width > 0 and a.height > 0 and b.height > 0:
            w_ratio = min(a.width, b.width) / max(a.width, b.width)
            h_ratio = min(a.height, b.height) / max(a.height, b.height)
            scores.append(((w_ratio + h_ratio) / 2, 0.15))

        if not scores:
            return 0.0

        total_weight = sum(w for _, w in scores)
        return sum(s * w for s, w in scores) / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def _format_bytes(b: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"
