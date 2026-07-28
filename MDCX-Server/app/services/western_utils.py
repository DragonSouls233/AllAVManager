"""欧美站点专用工具集。

功能：
1. Aylo 品牌 URL 标准化 — 20+ 品牌短名称 ↔ 场景 URL 互转
2. 站点域名 → 品牌映射
3. 标题模糊去重（相似度 > CommunityScrapers 的 0.75 阈值）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Aylo 品牌站点注册表
# 参考: CommunityScrapers AyloAPI/domains.py
# ---------------------------------------------------------------------------

@dataclass
class AyloBrand:
    name: str
    domain: str
    tags: list[str] = field(default_factory=list)


# 完整的 Aylo 品牌列表（20+ 品牌）
AYLO_BRANDS: list[AyloBrand] = [
    AyloBrand("Brazzers", "brazzers.com", ["Big Tits", "Brazzers"]),
    AyloBrand("Reality Kings", "realitykings.com", ["Reality Kings"]),
    AyloBrand("Mofos", "mofos.com", ["Mofos"]),
    AyloBrand("Digital Playground", "digitalplayground.com", ["Digital Playground"]),
    AyloBrand("Twistys", "twistys.com", ["Twistys"]),
    AyloBrand("Babes", "babes.com", ["Babes"]),
    AyloBrand("Vixen", "vixen.com", ["Vixen"]),
    AyloBrand("Blacked", "blacked.com", ["Blacked", "Black Male"]),
    AyloBrand("Blacked Raw", "blackedraw.com", ["Blacked Raw", "Black Male"]),
    AyloBrand("Tushy", "tushy.com", ["Tushy", "Anal Sex"]),
    AyloBrand("Tushy Raw", "tushyraw.com", ["Tushy Raw", "Anal Sex"]),
    AyloBrand("Deeper", "deeper.com", ["Deeper"]),
    AyloBrand("Milfy", "milfy.com", ["Milfy", "MILF"]),
    AyloBrand("Slayed", "slayed.com", ["Slayed", "Lesbian Sex"]),
    AyloBrand("Wifey", "wifey.com", ["Wifey"]),
    AyloBrand("Naughty America", "naughtyamerica.com", ["Naughty America"]),
    AyloBrand("MYLF", "mylf.com", ["MYLF", "MILF"]),
    AyloBrand("TeamSkeet", "teamskeet.com", ["TeamSkeet"]),
    AyloBrand("Evil Angel", "evilangel.com", ["Evil Angel"]),
    AyloBrand("BangBros", "bangbros.com", ["BangBros"]),
    AyloBrand("PornPros", "pornpros.com", ["PornPros"]),
    AyloBrand("Girlsway", "girlsway.com", ["Girlsway", "Lesbian"]),
    AyloBrand("SexyHub", "sexyhub.com", ["SexyHub"]),
]

# 域名 → 品牌查找
_DOMAIN_TO_BRAND: dict[str, str] = {
    b.domain: b.name for b in AYLO_BRANDS
}
_DOMAIN_TO_TAGS: dict[str, list[str]] = {
    b.domain: b.tags for b in AYLO_BRANDS
}


# ---------------------------------------------------------------------------
# Vixen 网络站点
# ---------------------------------------------------------------------------

VIXEN_SITES: dict[str, str] = {
    "vixen.com": "Vixen",
    "blacked.com": "Blacked",
    "blackedraw.com": "Blacked Raw",
    "tushy.com": "Tushy",
    "tushyraw.com": "Tushy Raw",
    "deeper.com": "Deeper",
    "milfy.com": "Milfy",
    "slayed.com": "Slayed",
    "wifey.com": "Wifey",
}


# ---------------------------------------------------------------------------
# URL 标准化
# ---------------------------------------------------------------------------

def normalize_scene_url(url: str) -> str:
    """标准化欧美场景 URL 为统一格式。

    处理常见变异：
    - 去掉末尾的 /
    - 统一 https
    - 去掉 www.
    - 去掉 URL 中的追踪参数
    - 从短名称还原完整域名

    Examples:
        "brazzers.com/video/123" → "https://www.brazzers.com/video/123"
        "https://vixen.com/trailers/abc" → "https://www.vixen.com/trailers/abc"
    """
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    url = url.rstrip("/")

    # 去掉追踪参数
    url = re.sub(r"\?.*$", "", url)

    # 标准化域名
    url = re.sub(r"^https?://(www\.)?", "https://www.", url)

    return url


def extract_brand_from_url(url: str) -> Optional[str]:
    """从 URL 中提取品牌名称。

    Examples:
        "https://www.brazzers.com/video/123" → "Brazzers"
        "https://vixen.com/trailers/abc" → "Vixen"
    """
    normalized = normalize_scene_url(url)
    m = re.search(r"https://www\.([^/]+)", normalized)
    if not m:
        return None
    domain = m.group(1).lower()
    return _DOMAIN_TO_BRAND.get(domain)


def get_brand_tags(domain_or_name: str) -> list[str]:
    """获取品牌的默认标签。"""
    for brand in AYLO_BRANDS:
        if brand.name.lower() == domain_or_name.lower() or brand.domain == domain_or_name:
            return brand.tags
    return []


# ---------------------------------------------------------------------------
# 标题相似度匹配（移植自 CommunityScrapers）
# ---------------------------------------------------------------------------

def title_similarity(title1: str, title2: str) -> float:
    """计算两个标题的相似度 (0.0 ~ 1.0)。

    使用 difflib.SequenceMatcher（与 CommunityScrapers 一致）。
    """
    import difflib
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()
    return difflib.SequenceMatcher(None, t1, t2).ratio()


def is_scene_match(title1: str, title2: str, threshold: float = 0.75) -> bool:
    """判断两个场景标题是否匹配（相似度 ≥ threshold）。

    CommunityScrapers 默认使用 0.75。
    """
    return title_similarity(title1, title2) >= threshold
