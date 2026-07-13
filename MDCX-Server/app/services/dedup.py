"""三层视频去重引擎

参考 ReelSorter (dedup.py) + Stash (fingerprint) + fdupves 的设计：
- 第一层：文件哈希（SHA256，精确匹配，最快）
- 第二层：感知哈希（pHash，相似匹配，跨格式/分辨率）
- 第三层：音频指纹（Chromaprint，检测剪辑版/重编码版）

使用场景：
1. 扫描新文件时自动去重
2. 手动触发全库扫描
3. 批量导入时的预去重检查
"""

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 支持的视频扩展名
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m2ts", ".ts", ".mts"}


@dataclass
class DuplicateGroup:
    """一组重复的视频"""
    videos: list[dict] = field(default_factory=list)
    method: str = ""          # file_hash / phash / audio
    similarity: float = 0.0   # 0-1
    keep_index: int = 0       # 保留的视频索引


@dataclass
class DedupResult:
    """去重结果"""
    total: int = 0
    groups: list[DuplicateGroup] = field(default_factory=list)
    total_duplicates: int = 0
    space_wasted_gb: float = 0.0


class DedupEngine:
    """三层视频去重引擎"""

    def __init__(self, phash_threshold: float = 0.85, audio_threshold: float = 0.9):
        self.phash_threshold = phash_threshold
        self.audio_threshold = audio_threshold

    # ============ 第一层：文件哈希 ============

    def compute_file_hash(self, file_path: str, chunk_size: int = 64 * 1024) -> Optional[str]:
        """计算文件 SHA256 哈希"""
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            logger.warning(f"文件哈希计算失败 [{file_path}]: {e}")
            return None

    def find_by_file_hash(self, videos: list[dict]) -> list[DuplicateGroup]:
        """通过文件哈希查找精确重复"""
        hash_map: dict[str, list[dict]] = {}
        for v in videos:
            fp = v.get("file_path", "")
            fh = v.get("file_hash")
            if not fh:
                fh = self.compute_file_hash(fp)
                v["file_hash"] = fh
            if fh:
                if fh not in hash_map:
                    hash_map[fh] = []
                hash_map[fh].append(v)

        groups = []
        for fh, group in hash_map.items():
            if len(group) > 1:
                total_size = sum(os.path.getsize(v["file_path"]) for v in group if os.path.isfile(v["file_path"]))
                dup_size = total_size - (os.path.getsize(group[0]["file_path"]) if os.path.isfile(group[0]["file_path"]) else 0)
                groups.append(DuplicateGroup(
                    videos=group,
                    method="file_hash",
                    similarity=1.0,
                    keep_index=0,
                ))
        return groups

    # ============ 第二层：感知哈希 ============

    def compute_phash(self, file_path: str) -> Optional[str]:
        """计算视频文件的感知哈希

        使用 ffmpeg 提取关键帧，然后用 imagehash 计算 pHash。
        """
        try:
            import imagehash
            from PIL import Image
        except ImportError:
            logger.warning("缺少 imagehash/Pillow 依赖，无法计算 pHash")
            return None

        if not os.path.isfile(file_path):
            return None

        try:
            tmp_dir = tempfile.mkdtemp()
            tmp_pattern = os.path.join(tmp_dir, "frame_%03d.jpg")

            cmd = [
                "ffmpeg", "-i", file_path,
                "-vf", "select=gt(scene,0.4),scale=320:-1",
                "-frames:v", "3",
                "-vsync", "vfr",
                "-q:v", "2",
                "-y", tmp_pattern,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.debug(f"ffmpeg 提取帧失败 [{file_path}]: {result.stderr[:100]}")
                return None

            frames = sorted(Path(tmp_dir).glob("frame_*.jpg"))
            if not frames:
                return None

            hashes = []
            for frame_path in frames:
                try:
                    img = Image.open(frame_path)
                    phash = str(imagehash.phash(img))
                    hashes.append(phash)
                except Exception:
                    continue

            # 清理临时文件
            for p in Path(tmp_dir).iterdir():
                p.unlink()
            Path(tmp_dir).rmdir()

            if not hashes:
                return None

            combined = hashlib.sha256("".join(hashes).encode()).hexdigest()[:16]
            return combined

        except subprocess.TimeoutExpired:
            logger.warning(f"pHash 计算超时 [{file_path}]")
            return None
        except Exception as e:
            logger.debug(f"pHash 计算失败 [{file_path}]: {e}")
            return None

    def _compare_phash(self, hash1: str, hash2: str) -> float:
        """比较两个 pHash 字符串，返回相似度 0-1"""
        try:
            import imagehash
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            distance = h1 - h2
            max_distance = len(hash1) * 4  # 16 hex chars × 4 bits = 64 bits
            return max(0.0, 1.0 - (distance / max_distance))
        except Exception:
            return 0.0

    def find_by_phash(self, videos: list[dict]) -> list[DuplicateGroup]:
        """通过感知哈希查找相似重复"""
        try:
            import imagehash
        except ImportError:
            logger.warning("缺少 imagehash 依赖，跳过 pHash 去重")
            return []

        # 计算缺失的 pHash
        for v in videos:
            if not v.get("phash"):
                fp = v.get("file_path", "")
                v["phash"] = self.compute_phash(fp)

        candidates = [v for v in videos if v.get("phash")]
        if len(candidates) < 2:
            return []

        groups = []
        processed: set[str] = set()

        for i, v1 in enumerate(candidates):
            vid1 = v1.get("file_path", "")
            if vid1 in processed:
                continue

            group = [v1]
            processed.add(vid1)

            for j in range(i + 1, len(candidates)):
                v2 = candidates[j]
                vid2 = v2.get("file_path", "")
                if vid2 in processed:
                    continue

                sim = self._compare_phash(v1["phash"], v2["phash"])
                if sim >= self.phash_threshold:
                    group.append(v2)
                    processed.add(vid2)

            if len(group) > 1:
                groups.append(DuplicateGroup(
                    videos=group,
                    method="phash",
                    similarity=self.phash_threshold,
                ))

        return groups

    # ============ 第三层：音频指纹 ============

    def compute_audio_fingerprint(self, file_path: str) -> Optional[str]:
        """计算音频指纹（Chromaprint）

        需要 ffmpeg 编译有 chromaprint 支持，或安装 fpcalc 工具。
        """
        if not os.path.isfile(file_path):
            return None

        # 方案1: 使用 fpcalc（推荐）
        try:
            result = subprocess.run(
                ["fpcalc", "-json", "-length", "120", file_path],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                fingerprint = data.get("fingerprint", "")
                if fingerprint:
                    return fingerprint
        except FileNotFoundError:
            pass
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.debug(f"fpcalc 失败 [{file_path}]: {e}")

        # 方案2: 使用 ffmpeg + chromaprint
        try:
            cmd = [
                "ffmpeg", "-i", file_path,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "11025", "-ac", "1",
                "-f", "chromaprint", "-fp_format", "json",
                "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                fingerprint = data.get("fingerprint", "")
                if fingerprint:
                    return fingerprint
        except FileNotFoundError:
            logger.debug("ffmpeg 未找到 chromaprint 支持")
        except Exception as e:
            logger.debug(f"音频指纹计算失败 [{file_path}]: {e}")

        return None

    def _compare_audio_fingerprints(self, fp1: str, fp2: str) -> float:
        """比较两个音频指纹的相似度"""
        if not fp1 or not fp2:
            return 0.0
        min_len = min(len(fp1), len(fp2))
        if min_len == 0:
            return 0.0
        matches = sum(1 for a, b in zip(fp1, fp2) if a == b)
        return matches / min_len

    def find_by_audio(self, videos: list[dict]) -> list[DuplicateGroup]:
        """通过音频指纹查找重复（检测剪辑版/重编码版）"""
        for v in videos:
            if not v.get("audio_fingerprint"):
                fp = v.get("file_path", "")
                v["audio_fingerprint"] = self.compute_audio_fingerprint(fp)

        candidates = [v for v in videos if v.get("audio_fingerprint")]
        if len(candidates) < 2:
            return []

        groups = []
        processed: set[str] = set()

        for i, v1 in enumerate(candidates):
            vid1 = v1.get("file_path", "")
            if vid1 in processed:
                continue

            group = [v1]
            processed.add(vid1)

            for j in range(i + 1, len(candidates)):
                v2 = candidates[j]
                vid2 = v2.get("file_path", "")
                if vid2 in processed:
                    continue

                sim = self._compare_audio_fingerprints(v1["audio_fingerprint"], v2["audio_fingerprint"])
                if sim >= self.audio_threshold:
                    group.append(v2)
                    processed.add(vid2)

            if len(group) > 1:
                groups.append(DuplicateGroup(
                    videos=group,
                    method="audio",
                    similarity=self.audio_threshold,
                ))

        return groups

    # ============ 全流程 ============

    def find_all_duplicates(
        self,
        videos: list[dict],
        methods: Optional[list[str]] = None,
    ) -> DedupResult:
        """执行全三层去重

        Args:
            videos: 视频信息列表，每项含 file_path，可选 file_hash/phash/audio_fingerprint
            methods: 去重方法列表，默认全部 ['file_hash', 'phash', 'audio']

        Returns:
            DedupResult 汇总结果
        """
        if methods is None:
            methods = ["file_hash", "phash", "audio"]

        all_groups: list[DuplicateGroup] = []
        seen_paths: set[str] = set()

        # 第一层：文件哈希
        if "file_hash" in methods:
            groups = self.find_by_file_hash(videos)
            all_groups.extend(groups)
            for g in groups:
                for v in g.videos:
                    seen_paths.add(v.get("file_path", ""))

        # 第二层：感知哈希（排除已匹配的文件）
        if "phash" in methods:
            remaining = [v for v in videos if v.get("file_path", "") not in seen_paths]
            groups = self.find_by_phash(remaining)
            all_groups.extend(groups)
            for g in groups:
                for v in g.videos:
                    seen_paths.add(v.get("file_path", ""))

        # 第三层：音频指纹
        if "audio" in methods:
            remaining = [v for v in videos if v.get("file_path", "") not in seen_paths]
            groups = self.find_by_audio(remaining)
            all_groups.extend(groups)

        # 计算统计
        total_duplicates = sum(len(g.videos) - 1 for g in all_groups)
        space_wasted = 0.0
        for g in all_groups:
            keep = g.videos[0]
            for v in g.videos[1:]:
                fp = v.get("file_path", "")
                if os.path.isfile(fp):
                    space_wasted += os.path.getsize(fp)

        result = DedupResult(
            total=len(videos),
            groups=all_groups,
            total_duplicates=total_duplicates,
            space_wasted_gb=round(space_wasted / (1024 ** 3), 2),
        )

        logger.info(
            f"去重完成: {result.total} 个文件中发现 {result.total_duplicates} 个重复, "
            f"可释放 {result.space_wasted_gb}GB"
        )

        return result


# ============ 便捷函数 ============

def find_videos_in_directory(directory: str, recursive: bool = True) -> list[dict]:
    """扫描目录获取视频文件列表"""
    videos = []
    base = Path(directory)
    if not base.exists():
        return videos

    pattern = "**/*" if recursive else "*"
    for p in base.glob(pattern):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append({
                "file_path": str(p),
                "file_size": p.stat().st_size,
            })
    return videos


async def dedup_directory(
    directory: str,
    methods: Optional[list[str]] = None,
) -> DedupResult:
    """便捷函数：对整个目录执行去重"""
    engine = DedupEngine()
    videos = find_videos_in_directory(directory)
    if not videos:
        return DedupResult()
    return engine.find_all_duplicates(videos, methods)


__all__ = [
    "DedupEngine",
    "DedupResult",
    "DuplicateGroup",
    "find_videos_in_directory",
    "dedup_directory",
]
