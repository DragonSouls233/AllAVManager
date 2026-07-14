"""
下载对比追踪引擎

参考来源：
- P1: PornSimilarityPlatform/modules/javdb/core/comparator.py (254行)
- P1: PornSimilarityPlatform/modules/javdb/core/models.py (175行)

整合说明：
- 核心对比逻辑: 复用 P1 ChineseComparator (直接移植)
- 数据模型: 复用 P1 VideoInfo/CompareResult dataclass
- 数据存储: 升级为 MDCX SQLite (替代 P1 的 JSON)
- 代理集成: 通过 MDCX 内置代理 (强制)
- 新增: 多目录扫描、模块适配、报告生成
"""

import os
import re
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, List, Set, Tuple, Dict

logger = logging.getLogger(__name__)


# ============================================================================
# 数据模型（复用 P1 models.py 的 dataclass 设计）
# ============================================================================

@dataclass
class VideoInfo:
    """视频信息

    番号格式说明：
    - 普通版本: ABC-123
    - 中文版本: ABC-123C 或 ABC-123-C
    """
    code: str
    title: str
    actress_name: str
    url: Optional[str] = None
    cover: Optional[str] = None
    date: Optional[str] = None
    duration: Optional[str] = None
    has_chinese: bool = False
    chinese_code: Optional[str] = None
    source: str = "javdb"
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.code and not self.has_chinese:
            self.has_chinese = self._detect_chinese(self.code)
        if self.has_chinese and not self.chinese_code:
            self.chinese_code = self._generate_chinese_code(self.code)

    @staticmethod
    def _detect_chinese(code: str) -> bool:
        if not code:
            return False
        patterns = [r'-C$', r'-c$', r'C$', r'c$', r'-C\d*$']
        for pattern in patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _generate_chinese_code(code: str) -> str:
        if not code:
            return code
        if VideoInfo._detect_chinese(code):
            return code
        return f"{code}-C"

    def get_base_code(self) -> str:
        if not self.code:
            return ""
        return re.sub(r'[-]?[Cc]$', '', self.code)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CompareResult:
    """对比结果"""
    actress_name: str
    online_count: int
    local_count: int
    matched_count: int
    missing_count: int
    missing_videos: List[VideoInfo]
    chinese_missing: List[VideoInfo]
    local_chinese: List[str]
    local_non_chinese: List[str]

    def to_dict(self) -> dict:
        data = asdict(self)
        data['missing_videos'] = [v.to_dict() for v in self.missing_videos]
        data['chinese_missing'] = [v.to_dict() for v in self.chinese_missing]
        return data


# ============================================================================
# 对比追踪引擎（复用 P1 ChineseComparator 核心逻辑）
# ============================================================================

class DownloadTracker:
    """下载对比追踪引擎

    参考: P1 PornSimilarityPlatform/modules/javdb/core/comparator.py

    功能：
    1. 扫描本地视频目录，提取番号，识别中文版本
    2. 对比在线视频列表与本地文件
    3. 标记已匹配/缺失/中文缺失
    4. 生成对比报告
    """

    # 视频扩展名
    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts'}

    # 中文标识模式（直接复用 P1）
    CHINESE_PATTERNS = [
        r'-c$',           # 结尾是 -c
        r'-C$',           # 结尾是 -C
        r'c$',            # 结尾是 c（无横杠）
        r'C$',            # 结尾是 C
        r'[\-_]c[\-_]',   # 中间有 _c_ 或 -c-
        r'[\-_]chinese',  # 包含 -chinese 或 _chinese
        r'中文',           # 包含中文二字
    ]

    # 番号提取正则（复用 P1，扩展支持更多格式）
    CODE_PATTERNS = [
        r'([A-Z]{2,6}-\d{3,5}(?:-[Cc])?)',   # ABC-123, ABC-123-C
        r'([A-Z]{2,6}\d{3,5}[Cc]?)',          # ABC123, ABC123C
        r'([A-Z]{2,6}-\d{3,5}[Cc])',          # ABC-123C
        r'([A-Z]{2,6}\d{2,6})',               # ABC12345 (短番号)
    ]

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def scan_local_videos(self, directory: str) -> Tuple[Set[str], Set[str]]:
        """扫描本地视频目录

        Args:
            directory: 本地目录路径

        Returns:
            (普通番号集合, 中文番号集合)
        """
        if not os.path.exists(directory):
            logger.warning(f"目录不存在: {directory}")
            return set(), set()

        normal_codes: Set[str] = set()
        chinese_codes: Set[str] = set()

        for root, dirs, files in os.walk(directory):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in self.VIDEO_EXTENSIONS:
                    continue

                code = self._extract_code_from_filename(filename)
                if not code:
                    continue

                if self._is_chinese_version(filename, code):
                    base_code = self._get_base_code(code)
                    chinese_codes.add(base_code)
                    logger.debug(f"中文版本: {filename} -> {base_code}")
                else:
                    normal_codes.add(code)
                    logger.debug(f"普通版本: {filename} -> {code}")

        logger.info(f"扫描完成: 普通版本 {len(normal_codes)} 个, 中文版本 {len(chinese_codes)} 个")
        return normal_codes, chinese_codes

    def scan_multiple_directories(self, directories: List[str]) -> Tuple[Set[str], Set[str]]:
        """扫描多个本地视频目录

        Args:
            directories: 目录路径列表

        Returns:
            (普通番号集合, 中文番号集合) - 合并后的结果
        """
        all_normal: Set[str] = set()
        all_chinese: Set[str] = set()

        for directory in directories:
            if not directory:
                continue
            normal, chinese = self.scan_local_videos(directory)
            all_normal.update(normal)
            all_chinese.update(chinese)

        logger.info(f"多目录扫描完成: 普通版本 {len(all_normal)} 个, 中文版本 {len(all_chinese)} 个")
        return all_normal, all_chinese

    def _extract_code_from_filename(self, filename: str) -> str:
        """从文件名提取番号"""
        name = os.path.splitext(filename)[0]

        for pattern in self.CODE_PATTERNS:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        return ""

    def _is_chinese_version(self, filename: str, code: str) -> bool:
        """检测是否为中文版本"""
        for pattern in self.CHINESE_PATTERNS:
            if re.search(pattern, filename, re.IGNORECASE):
                return True
        return VideoInfo._detect_chinese(code)

    def _get_base_code(self, code: str) -> str:
        """获取基础番号（去除中文标识）"""
        return re.sub(r'[-]?[Cc]$', '', code).upper()

    def compare(
        self,
        online_videos: List[VideoInfo],
        local_directory: str
    ) -> CompareResult:
        """对比在线视频和本地视频

        Args:
            online_videos: 在线视频列表
            local_directory: 本地目录

        Returns:
            对比结果
        """
        return self.compare_with_directories(online_videos, [local_directory])

    def compare_with_directories(
        self,
        online_videos: List[VideoInfo],
        local_directories: List[str]
    ) -> CompareResult:
        """对比在线视频和多个本地目录

        Args:
            online_videos: 在线视频列表
            local_directories: 本地目录列表

        Returns:
            对比结果
        """
        logger.info(f"开始对比: 在线 {len(online_videos)} 个视频, 本地目录 {len(local_directories)} 个")

        local_normal, local_chinese = self.scan_multiple_directories(local_directories)

        matched_count = 0
        missing_videos: List[VideoInfo] = []
        chinese_missing: List[VideoInfo] = []

        for video in online_videos:
            base_code = video.get_base_code()

            has_normal = base_code in local_normal
            has_chinese = base_code in local_chinese

            if has_normal or has_chinese:
                matched_count += 1
            else:
                missing_videos.append(video)

            if video.has_chinese and not has_chinese:
                chinese_missing.append(video)

        actress_name = online_videos[0].actress_name if online_videos else ""

        return CompareResult(
            actress_name=actress_name,
            online_count=len(online_videos),
            local_count=len(local_normal) + len(local_chinese),
            matched_count=matched_count,
            missing_count=len(missing_videos),
            missing_videos=missing_videos,
            chinese_missing=chinese_missing,
            local_chinese=list(local_chinese),
            local_non_chinese=list(local_normal),
        )

    def generate_report(self, result: CompareResult) -> str:
        """生成对比报告"""
        lines = [
            "=" * 60,
            f"下载对比报告 - {result.actress_name}",
            "=" * 60,
            f"在线视频: {result.online_count} 个",
            f"本地视频: {result.local_count} 个",
            f"  - 普通版本: {len(result.local_non_chinese)} 个",
            f"  - 中文版本: {len(result.local_chinese)} 个",
            f"已匹配:   {result.matched_count} 个",
            f"缺失:     {result.missing_count} 个",
            "",
            "缺失视频列表:",
            "-" * 60,
        ]

        for i, video in enumerate(result.missing_videos[:20], 1):
            chinese_mark = " [中文]" if video.has_chinese else ""
            title = video.title[:50] if video.title else ""
            lines.append(f"{i}. {video.code}{chinese_mark}")
            if title:
                lines.append(f"   {title}...")

        if len(result.missing_videos) > 20:
            lines.append(f"... 还有 {len(result.missing_videos) - 20} 个")

        if result.chinese_missing:
            lines.append("")
            lines.append("缺失的中文版本:")
            for video in result.chinese_missing[:10]:
                lines.append(f"  - {video.code}")

        return "\n".join(lines)

    def compare_from_db(
        self,
        online_videos: List[VideoInfo],
        local_codes_normal: Set[str],
        local_codes_chinese: Set[str]
    ) -> CompareResult:
        """从数据库已扫描的番号集合进行对比（无需重新扫描目录）

        Args:
            online_videos: 在线视频列表
            local_codes_normal: 本地普通番号集合
            local_codes_chinese: 本地中文番号集合

        Returns:
            对比结果
        """
        logger.info(f"从数据库对比: 在线 {len(online_videos)} 个, 本地普通 {len(local_codes_normal)} 个, 中文 {len(local_codes_chinese)} 个")

        matched_count = 0
        missing_videos: List[VideoInfo] = []
        chinese_missing: List[VideoInfo] = []

        for video in online_videos:
            base_code = video.get_base_code()

            has_normal = base_code in local_codes_normal
            has_chinese = base_code in local_codes_chinese

            if has_normal or has_chinese:
                matched_count += 1
            else:
                missing_videos.append(video)

            if video.has_chinese and not has_chinese:
                chinese_missing.append(video)

        actress_name = online_videos[0].actress_name if online_videos else ""

        return CompareResult(
            actress_name=actress_name,
            online_count=len(online_videos),
            local_count=len(local_codes_normal) + len(local_codes_chinese),
            matched_count=matched_count,
            missing_count=len(missing_videos),
            missing_videos=missing_videos,
            chinese_missing=chinese_missing,
            local_chinese=list(local_codes_chinese),
            local_non_chinese=list(local_codes_normal),
        )


# ============================================================================
# 全局单例
# ============================================================================

_tracker_instance: Optional[DownloadTracker] = None


def get_download_tracker() -> DownloadTracker:
    """获取全局 DownloadTracker 实例"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = DownloadTracker()
    return _tracker_instance
