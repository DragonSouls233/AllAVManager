"""PORNHub 视频页 HTML 解析器 — 从 pornhub.py 拆分。

提供 4 种降级策略提取视频信息：
1. flashvars JSON（最高优先级，直接可取 1080p 直链）
2. __NEXT_DATA__ 初始状态（SSR 数据，完整元数据）
3. mediaDefinitions JSON（视频流定义）
4. HTML 解析（最慢但最兼容）
"""

import json
import logging
import re
from typing import Optional

from app.crawlers.base import ActorInfo, ScrapeResult
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# flashvars 解析 — 最快的视频信息提取
# 格式: var flashvars_123 = { ... };
# ---------------------------------------------------------------------------

_REGEX_FLASHVARS = re.compile(r"var\s+flashvars_\d+\s*=\s*(\{.+?\});", re.DOTALL)


def parse_flashvars(html: str, viewkey: str) -> Optional[dict]:
    """从 HTML 中提取 flashvars JSON。"""
    m = _REGEX_FLASHVARS.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        if data.get("video_id") == viewkey or data.get("image") == viewkey:
            return data
        return data
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# __NEXT_DATA__ 解析 — SSR 数据（完整元数据）
# ---------------------------------------------------------------------------

_REGEX_NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def parse_next_data(html: str) -> Optional[tuple[dict, str]]:
    """从 HTML 中提取 __NEXT_DATA__ JSON。

    Returns:
        (data, viewkey) or None
    """
    m = _REGEX_NEXT_DATA.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        # SSR 页面，找视频数据
        video_data = data.get("props", {}).get("pageProps", {}).get("videoData", {})
        if video_data:
            vk = video_data.get("viewkey", "")
            return (video_data, vk)
    except json.JSONDecodeError:
        pass
    return None


# ---------------------------------------------------------------------------
# mediaDefinitions 解析 — 视频流 URL 列表
# ---------------------------------------------------------------------------

_REGEX_MEDIA_DEF = re.compile(r"mediaDefinitions\s*:\s*(\[.+?\]),\s*", re.DOTALL)


def parse_media_definitions(html: str) -> list[dict]:
    """从 HTML 中提取 mediaDefinitions 视频流定义。"""
    m = _REGEX_MEDIA_DEF.search(html)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, AttributeError):
        return []


# ---------------------------------------------------------------------------
# HTML 字段提取 — 最兼容方式
# ---------------------------------------------------------------------------

def extract_title(html: str) -> str:
    """从 HTML 提取视频标题。"""
    m = re.search(r'<title>(.*?)</title>', html)
    if m:
        title = m.group(1).strip()
        # 去除站点后缀 " - Pornhub.com" 等
        title = re.sub(r"\s*[-–|]\s*(Pornhub|PH).*$", "", title, flags=re.I)
        return title.strip()
    return ""


def extract_cover(html: str) -> Optional[str]:
    """从 HTML 提取封面 URL。"""
    # og:image
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if m:
        return m.group(1)
    # twitter:image
    m = re.search(r'<meta\s+name="twitter:image"\s+content="([^"]+)"', html)
    if m:
        return m.group(1)
    # 常规封面
    m = re.search(r'<img[^>]+class="[^"]*cover[^"]*"[^>]+src="([^"]+)"', html)
    if m:
        return m.group(1)
    return None


def extract_actors(html: str) -> list[ActorInfo]:
    """从 HTML 提取演员列表。"""
    actors: list[ActorInfo] = []
    # PornHub 演员列表: <a class="pornstar-label" ...>
    pattern = re.compile(
        r'<a[^>]+class="[^"]*(?:pornstar-label|actor-name)[^"]*"[^>]*>'
        r'\s*<span[^>]*>\s*(.*?)\s*</span>'
    )
    for m in pattern.finditer(html):
        name = m.group(1).strip()
        if name and name.lower() not in ("pornhub", "ph"):
            actors.append(ActorInfo(name=name))

    if not actors:
        # 备选: 从标签中提取演员
        pattern2 = re.compile(
            r'<a[^>]+href="[^"]*pornstar[^"]*"[^>]*>(.*?)</a>'
        )
        for m in pattern2.finditer(html):
            name = m.group(1).strip()
            if name and len(name) < 50:
                actors.append(ActorInfo(name=name))

    return actors


def extract_duration(html: str) -> Optional[int]:
    """从 HTML 提取时长（秒）。"""
    # 格式: "12:34" 或 "1:12:34"
    patterns = [
        r'"duration"\s*:\s*"(\d+:\d+(?::\d+)?)"',
        r'"duration"\s*:\s*(\d+)',
        r'<span[^>]*class="[^"]*duration[^"]*"[^>]*>(\d+:\d+(?::\d+)?)',
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            val = m.group(1)
            if ":" in str(val):
                parts = str(val).split(":")
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            try:
                return int(val)
            except ValueError:
                continue
    return None


def extract_rating(html: str) -> Optional[float]:
    """从 HTML 提取评分。"""
    m = re.search(r'"rating"\s*:\s*"?([\d.]+)"?', html)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = re.search(r'<span[^>]*class="[^"]*rating[^"]*"[^>]*>([\d.]+)', html)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def extract_views(html: str) -> Optional[int]:
    """从 HTML 提取播放量。"""
    m = re.search(r'(\d[\d,.]*)\s*(?:views|次观看)', html)
    if m:
        raw = m.group(1).replace(",", "")
        if "." in raw:
            num = float(raw)
        else:
            num = int(raw)
        return int(num)
    return None


def extract_tags(html: str) -> tuple[list[str], list[str]]:
    """从 HTML 提取标签。

    Returns:
        (categories, tags) 分类和标签列表
    """
    categories: list[str] = []
    tags: list[str] = []

    # 分类（PornHub 的分类标签）: <a class="category" ...>
    cat_pattern = re.compile(
        r'<a[^>]+class="[^"]*category[^"]*"[^>]+href="[^"]*/categories/[^"]*"[^>]*>(.*?)</a>'
    )
    for m in cat_pattern.finditer(html):
        cat = m.group(1).strip()
        if cat and "porn" not in cat.lower():
            categories.append(cat)

    # 普通标签（production tags）:
    tag_pattern = re.compile(
        r'<a[^>]+class="[^"]*tag[^"]*"[^>]+href="[^"]*/video[^"]*"[^>]*>(.*?)</a>'
    )
    for m in tag_pattern.finditer(html):
        tag = m.group(1).strip()
        if tag and len(tag) < 50:
            tags.append(tag)

    return (categories, tags)


def extract_uploader(html: str) -> Optional[str]:
    """从 HTML 提取上传者。"""
    m = re.search(r'/users/([^"\'<]+)', html)
    if m:
        name = m.group(1).replace("-", " ").title()
        return name
    return None


def extract_viewkey(html: str) -> Optional[str]:
    """从 HTML 提取 viewkey。"""
    m = re.search(r'viewkey=([a-z0-9]+)', html)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# 构建 ScrapeResult 的工具函数
# ---------------------------------------------------------------------------

def build_result_from_data(data: dict, viewkey: str, title: str = "") -> ScrapeResult:
    """从 flashvars / next_data 字典构建 ScrapeResult。"""
    result = ScrapeResult()
    result.code = viewkey
    result.source = "pornhub"
    result.title = title or data.get("video_title", data.get("title", ""))
    result.cover_url = data.get("image_url") or data.get("image", data.get("cover", ""))
    result.duration = _parse_duration_value(data.get("video_duration") or data.get("duration", 0))
    result.rating = _float_or_none(data.get("rating"))

    # 演员
    actors_raw = data.get("pornstars", [])
    if isinstance(actors_raw, list):
        result.actors = [ActorInfo(name=a.get("pornstar_name", "") if isinstance(a, dict) else str(a)) for a in actors_raw if a]
    elif isinstance(actors_raw, str):
        result.actors = [ActorInfo(name=a.strip()) for a in actors_raw.split(",") if a.strip()]

    # 标签
    tags_raw = data.get("tags", data.get("categories", []))
    if isinstance(tags_raw, list):
        result.genres = [t.get("tag_name", "") if isinstance(t, dict) else str(t) for t in tags_raw if t]

    # 质量列表（视频流）
    quality = data.get("quality", {})
    if isinstance(quality, dict):
        result.metadata["qualities"] = {k: v for k, v in quality.items() if isinstance(v, str)}

    return result


def _parse_duration_value(value) -> Optional[int]:
    """解析各种格式的时长为秒数。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if ":" in str(value):
        parts = str(value).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return None


def _float_or_none(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(" rating", "").strip())
    except (ValueError, TypeError):
        return None
