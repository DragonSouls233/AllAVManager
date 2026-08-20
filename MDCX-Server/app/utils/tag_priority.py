"""
NFO 标签优先级排序（移植自 ref42-Kesuy-mdcx mdcx/core/tag_priority.py，MIT）

核心思想：从 resources/mapping_table/mapping_info.xml 的内容类型标签区间
（"M女" -> "kira☆kira" / "S1 NO.1 STYLE"）构建优先级标签集合，NFO 写入前
把命中该集合的标签（如"女仆/护士/人妻"等内容类型）排在最前，让
Emby/Jellyfin/Kodi 的媒体库展示正确的首要类型标签。

依赖资源文件缺失/解析失败时优雅降级：返回空集合，NFO 按原顺序输出。
"""

import unicodedata
from pathlib import Path
from typing import Any

try:
    from lxml import etree
except ImportError:  # lxml 不可用时降级为不排序
    etree = None  # type: ignore

# 资源文件路径（随代码分发，PyInstaller 打包后 __file__ 在 _MEIPASS 下同样有效）
_RESOURCE_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "mapping_table" / "mapping_info.xml"
)

_PRIORITY_START = "M女"
_PRIORITY_STOPS = {
    "kira☆kira",
    "S1 NO.1 STYLE",
}
_INFO_LANGUAGE_ATTRS = ("zh_cn", "zh_tw", "jp")
_NON_CONTENT_TAGS = {
    "16小时+",
    "16小時+",
    "16時間以上作品",
    "3D",
    "3D卡通",
    "3Dエロアニメ",
    "4K",
    "VR",
    "8K VR",
    "4小时+",
    "4小時+",
    "4小時以上作品",
    "单体作品",
    "單體作品",
    "精选合集",
    "ベスト・総集編",
    "经典老片",
    "經典老片",
    "經典",
    "个人撮影",
    "個人撮影",
    "主观视角",
    "主觀視角",
    "纪录片",
    "紀錄片",
    "ドキュメンタリー",
    "故事集",
    "西洋片",
    "形象影片",
    "寫真偶像",
    "イメージビデオ",
    "男性形象影片",
    "男寫真偶像",
    "イメージビデオ（男性）",
    "出道作品",
    "首次亮相",
    "重制版",
    "重製版",
    "複刻版",
    "成人电影",
    "成人電影",
    "法国",
    "法國",
    "韓國",
    "韩国",
    "台湾模特",
    "臺灣模特",
    "台湾モデル",
    "薄马赛克",
    "薄馬賽克",
    "ギリモザ",
    "流出",
    "破解",
    "无码",
    "無碼",
    "無修正",
}
_priority_tag_names_cache: tuple[int, frozenset[str]] = (0, frozenset())


def _normalize_tag(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _get_mapping_nodes() -> tuple[int, list[Any]]:
    """加载 mapping_info.xml 并返回 (文件 mtime, 全部 <a> 节点)。

    文件不存在或解析失败时返回 (0, [])，调用方优雅降级。
    """
    if etree is None:
        return 0, []
    try:
        mtime = int(_RESOURCE_PATH.stat().st_mtime)
        parser = etree.HTMLParser(encoding="utf-8")
        with open(_RESOURCE_PATH, encoding="utf-8") as f:
            tree = etree.HTML(f.read().encode("utf-8"), parser=parser)
        return mtime, tree.xpath("//a")
    except (OSError, ValueError, SyntaxError):
        return 0, []


def get_priority_tag_names() -> frozenset[str]:
    """从 mapping_info.xml 内容类型标签区间构建优先级标签集合（带文件 mtime 缓存）。"""
    global _priority_tag_names_cache

    mapping_mtime, nodes = _get_mapping_nodes()
    cached_mtime, cached_names = _priority_tag_names_cache
    if mapping_mtime == cached_mtime:
        return cached_names

    names: set[str] = set()
    in_priority_section = False

    for node in nodes:
        zh_cn = (node.get("zh_cn") or "").strip()
        if zh_cn == _PRIORITY_START:
            in_priority_section = True
        if not in_priority_section:
            continue
        if zh_cn in _PRIORITY_STOPS:
            break

        for attr in _INFO_LANGUAGE_ATTRS:
            value = (node.get(attr) or "").strip().strip(",")
            if not value or value == "删除" or value in _NON_CONTENT_TAGS:
                continue
            names.add(_normalize_tag(value))

    _priority_tag_names_cache = (mapping_mtime, frozenset(names))
    return _priority_tag_names_cache[1]


def clear_priority_tag_cache() -> None:
    """清空缓存（资源文件被替换后调用）。"""
    global _priority_tag_names_cache
    _priority_tag_names_cache = (0, frozenset())


def _is_template_tag(tag: str, template: str, placeholder: str) -> bool:
    if placeholder not in template:
        return False

    prefix, suffix = template.split(placeholder, 1)
    prefix = _normalize_tag(prefix)
    suffix = _normalize_tag(suffix)
    normalized = _normalize_tag(tag)

    if not prefix and not suffix:
        return False
    if prefix and not normalized.startswith(prefix):
        return False
    if suffix and not normalized.endswith(suffix):
        return False

    value_start = len(prefix)
    value_end = len(normalized) - len(suffix) if suffix else len(normalized)
    return bool(normalized[value_start:value_end].strip())


def prioritize_nfo_tags(tags: list[str], series_tag: str = "", series_template: str = "") -> list[str]:
    """把优先级标签（内容类型）排在最前，随后是系列标签，其余保持原序。

    无优先级标签或标签不足 2 个时返回原列表（不改变既有输出）。
    """
    priority_names = get_priority_tag_names()
    if not priority_names or len(tags) < 2:
        return tags

    priority_tags: list[str] = []
    series_tags: list[str] = []
    other_tags: list[str] = []
    normalized_series_tag = _normalize_tag(series_tag) if series_tag else ""

    for tag in tags:
        normalized = _normalize_tag(tag)
        if normalized in priority_names:
            priority_tags.append(tag)
        elif (normalized_series_tag and normalized == normalized_series_tag) or _is_template_tag(
            tag, series_template, "series"
        ):
            series_tags.append(tag)
        else:
            other_tags.append(tag)

    if not priority_tags:
        return tags

    return priority_tags + series_tags + other_tags
