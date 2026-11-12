"""字幕源适配器注册表。

新增站点只需在此登记；编排层只认 ``SOURCES``，不认具体类。
javzimu 因 Turnstile 无法纯 HTTP 通过，本期不实现（见 DESIGN.md R11）。
"""
from __future__ import annotations

from app.services.subtitle_sources.aiyi1 import Aiyi1Source
from app.services.subtitle_sources.base import (
    BASE_HEADERS,
    LANG_LABEL,
    LANG_RANK,
    MAX_BYTES,
    MAX_CANDIDATES_TRY,
    POLICIES,
    SOURCE_LABEL,
    VIDEO_BUDGET_S,
    Budget,
    DownloadFailed,
    RateGate,
    SourceBlocked,
    SourceTimeout,
    SubtitleCandidate,
    SubtitleError,
    SubtitleSource,
    gate,
    merge_and_rank,
    normalize_code,
    normalize_srt,
    registry_record,
    srt_target_path,
    title_matches_code,
)
from app.services.subtitle_sources.subtitlecat import SubtitleCatSource

SOURCES: dict[str, SubtitleSource] = {
    "subtitlecat": SubtitleCatSource(),
    "aiyi1": Aiyi1Source(),
}

__all__ = [
    "SOURCES",
    "Aiyi1Source",
    "BASE_HEADERS",
    "Budget",
    "DownloadFailed",
    "LANG_LABEL",
    "LANG_RANK",
    "MAX_BYTES",
    "MAX_CANDIDATES_TRY",
    "POLICIES",
    "RateGate",
    "SOURCE_LABEL",
    "SourceBlocked",
    "SourceTimeout",
    "SubtitleCandidate",
    "SubtitleCatSource",
    "SubtitleError",
    "SubtitleSource",
    "VIDEO_BUDGET_S",
    "gate",
    "merge_and_rank",
    "normalize_code",
    "normalize_srt",
    "registry_record",
    "srt_target_path",
    "title_matches_code",
]
