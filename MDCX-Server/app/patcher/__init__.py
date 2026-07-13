"""
智能补刮引擎

检测已有刮削内容的缺失字段，自动补全
"""

from app.patcher.detector import MissingDetector, MissingInfo
from app.patcher.engine import PatchEngine, PatchResult
from app.patcher.reporter import PatchReporter
from app.patcher.skipper import Skipper, SkipReason

__all__ = [
    "MissingDetector",
    "MissingInfo",
    "PatchEngine",
    "PatchResult",
    "PatchReporter",
    "Skipper",
    "SkipReason",
]
