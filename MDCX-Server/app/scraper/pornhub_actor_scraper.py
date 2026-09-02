"""
PORNHub 演员资料刮削器（增强版 v2）

增强内容：
  - curl_cffi + impersonate fallback（chrome136 → chrome120 → chrome119 → edge101）
  - selectolax 超快 HTML 解析
  - #getAvatar 双路径头像提取（ph-heatmap 方法）
  - 国籍 → 国家映射（ph-heatmap _NATIONALITY_TO_COUNTRY）
  - Video Views 精确提取（.videoViews data-title）
  - 出生地解析与标准化
  - 原有 regex 解析作为 fallback
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config.manager import DATA_DIR
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

AVATAR_DIR = DATA_DIR / "avatars" / "pornhub"
PH_PAGES_BASE = "https://www.pornhub.com/pornstars"

_IMPERSONATE_FALLBACKS = ["chrome136", "chrome120", "chrome119", "chrome116", "safari17_0", "edge101"]

_NATIONALITY_TO_COUNTRY = {
    "American": "United States", "British": "United Kingdom", "Russian": "Russia",
    "Italian": "Italy", "French": "France", "German": "Germany", "Spanish": "Spain",
    "Brazilian": "Brazil", "Mexican": "Mexico", "Japanese": "Japan",
    "Korean": "South Korea", "Chinese": "China", "Australian": "Australia",
    "Canadian": "Canada", "Czech": "Czech Republic", "Polish": "Poland",
    "Ukrainian": "Ukraine", "Hungarian": "Hungary", "Romanian": "Romania",
    "Argentine": "Argentina", "Argentinian": "Argentina", "Colombian": "Colombia",
    "Dutch": "Netherlands", "Swedish": "Sweden", "Norwegian": "Norway",
    "Finnish": "Finland", "Danish": "Denmark", "Turkish": "Turkey",
    "Greek": "Greece", "Portuguese": "Portugal", "Indian": "India",
    "Filipino": "Philippines", "Thai": "Thailand", "Vietnamese": "Vietnam",
    "Indonesian": "Indonesia", "Bulgarian": "Bulgaria", "Serbian": "Serbia",
    "Croatian": "Croatia", "Slovakian": "Slovakia", "Slovenian": "Slovenia",
    "English": "United Kingdom", "Irish": "Ireland", "Belgian": "Belgium",
    "Austrian": "Austria", "Cuban": "Cuba", "Dominican": "Dominican Republic",
    "Puerto Rican": "Puerto Rico", "Egyptian": "Egypt", "Nigerian": "Nigeria",
    "Armenian": "Armenia", "Peruvian": "Peru", "Venezuelan": "Venezuela",
    "Uruguayan": "Uruguay", "New Zealander": "New Zealand",
}

_COUNTRY_ALIASES = {
    "United States of America": "United States", "USA": "United States",
    "U.S.A.": "United States", "U.S.": "United States", "UK": "United Kingdom",
    "U.K.": "United Kingdom", "Great Britain": "United Kingdom", "England": "United Kingdom",
    "Scotland": "United Kingdom",
}


@dataclass
class EnhancedActorProfile:
    name: str
    alias: Optional[str] = None
    avatar_url: Optional[str] = None
    birth_date: Optional[str] = None
    debut_year: Optional[str] = None
    height: Optional[str] = None
    measurements: Optional[str] = None
    birthplace: Optional[str] = None
    country: Optional[str] = None
    ethnicity: Optional[str] = None
    movie_count: Optional[int] = None
    photo_count: Optional[int] = None
    video_count: Optional[int] = None
    profile_url: Optional[str] = None
    rank: Optional[int] = None
    rank_weekly: Optional[int] = None
    total_views: Optional[int] = None
    background: Optional[str] = None


def _canonicalize_country(name: str) -> str:
    name = name.strip()
    return _COUNTRY_ALIASES.get(name, name)


async def scrape_actor_profile(actor_name: str, nationality: Optional[str] = None) -> Optional[EnhancedActorProfile]:
    profile = await _scrape_from_pornhub_selectolax(actor_name)
    if profile:
        if nationality and not profile.country:
            profile.country = nationality
        return profile

    base_name = re.sub(r'\d+$', '', actor_name).strip()
    if base_name and base_name != actor_name:
        profile = await _scrape_from_pornhub_selectolax(base_name)
        if profile:
            if nationality and not profile.country:
                profile.country = nationality
            return profile

    profile = await _scrape_from_pornhub_regex(actor_name)
    if profile:
        if nationality and not profile.country:
            profile.country = nationality
        return profile

    avatar_url = await _scrape_avatar_from_javdb(actor_name)
    if avatar_url:
        return EnhancedActorProfile(name=actor_name, avatar_url=avatar_url, country=nationality)

    return None


async def download_actor_avatar(actor_name: str, avatar_url: str) -> Optional[str]:
    if not avatar_url or not avatar_url.startswith("http"):
        return None

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', actor_name).strip()
    local_path = AVATAR_DIR / f"{safe_name}.jpg"

    if local_path.exists():
        return str(local_path)

    try:
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()
        client = AsyncHttpClient(proxy=proxy_url)
        resp = await client.get(avatar_url, timeout=30)
        if resp and resp.status_code == 200:
            local_path.write_bytes(resp.content)
            logger.info("头像已下载: %s -> %s", actor_name, local_path)
            return str(local_path)
    except Exception as e:
        logger.warning("头像下载失败 [%s]: %s", actor_name, e)

    return None


def check_profile_completeness(profile: EnhancedActorProfile) -> dict:
    missing = []
    if not profile.avatar_url:
        missing.append("avatar_url")
    if not profile.birth_date:
        missing.append("birth_date")
    if not profile.country:
        missing.append("country")
    if not profile.debut_year:
        missing.append("debut_year")
    if profile.movie_count is None:
        missing.append("movie_count")
    completeness = max(0, 100 - len(missing) * 20)
    return {"completeness": completeness, "missing_fields": missing}


# ====== selectolax-based PH scraper ======


def _extract_photo_url(tree) -> Optional[str]:
    """双路径头像提取：#getAvatar → fallback .topProfileHeader img"""
    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        return None

    avatar = tree.css_first("#getAvatar")
    if avatar is not None:
        src = avatar.attributes.get("src") or avatar.attributes.get("data-src")
        if src:
            return src

    header = tree.css_first(".topProfileHeader")
    if header is not None:
        for img in header.css("img"):
            src = img.attributes.get("src") or img.attributes.get("data-src")
            if src and "/avatar" in src:
                return src
    return None


_VIEWS_DATA_TITLE_RE = re.compile(r"Video views?\s*:\s*([\d,]+)", re.IGNORECASE)


def _extract_video_views(tree) -> Optional[int]:
    for node in tree.css(".videoViews[data-title]"):
        title = node.attributes.get("data-title", "") or ""
        match = _VIEWS_DATA_TITLE_RE.search(title)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _extract_country_from_tree(tree) -> Optional[str]:
    birth_place = None
    background = None
    for piece in tree.css(".infoPiece"):
        text = piece.text(strip=True)
        if text.startswith("Birth Place:"):
            birth_place = text[len("Birth Place:"):].strip()
        elif text.startswith("Background:"):
            background = text[len("Background:"):].strip()

    if birth_place:
        country = birth_place.split(",")[-1].strip()
        if country:
            return _canonicalize_country(country)

    if background:
        mapped = _NATIONALITY_TO_COUNTRY.get(background)
        if mapped:
            return mapped
    return None


async def _fetch_with_impersonate_fallback(url: str, cookies: dict, timeout: int = 30) -> Optional[str]:
    from app.services.proxy_manager import get_effective_proxy_url
    proxy_url = get_effective_proxy_url()
    client = AsyncHttpClient(proxy=proxy_url, timeout=timeout, max_retries=1)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    for impersonate in _IMPERSONATE_FALLBACKS:
        try:
            resp = await client.get(
                url,
                cookies=cookies,
                headers=headers,
                fingerprint={"impersonate": impersonate},
                timeout=timeout,
            )
            if resp and resp.status_code == 200 and len(resp.text) > 1000:
                logger.debug("impersonate=%s 成功 [%s]", impersonate, url[:60])
                return resp.text
        except Exception as e:
            logger.debug("impersonate=%s 失败: %s", impersonate, e)

    return None


async def _scrape_from_pornhub_selectolax(actor_name: str) -> Optional[EnhancedActorProfile]:
    try:
        from app.crawlers.pornhub import _PH_BASE_COOKIES
        from selectolax.parser import HTMLParser
    except ImportError:
        return None

    ph_name = actor_name.replace(" ", "_")
    url = f"https://www.pornhub.com/pornstar/{ph_name}"

    html = await _fetch_with_impersonate_fallback(url, _PH_BASE_COOKIES)
    if not html:
        logger.debug("selectolax 抓取失败 [%s]", actor_name)
        return None

    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    profile = EnhancedActorProfile(name=actor_name)

    h1 = tree.css_first("h1")
    if h1 is not None:
        profile.name = h1.text(strip=True)

    profile.avatar_url = _extract_photo_url(tree)
    profile.total_views = _extract_video_views(tree)
    profile.country = _extract_country_from_tree(tree)

    info_fields = {}
    for piece in tree.css(".infoPiece"):
        text = piece.text(strip=True)
        if ":" in text:
            key, _, val = text.partition(":")
            info_fields[key.strip().lower()] = val.strip()

    for key, val in info_fields.items():
        if key == "birthday":
            profile.birth_date = val
        elif key == "height":
            profile.height = val
        elif key == "measurements":
            profile.measurements = val
        elif key == "birth place":
            profile.birthplace = val
        elif key == "ethnicity":
            profile.ethnicity = val
        elif key == "background":
            profile.background = val
            if not profile.country:
                mapped = _NATIONALITY_TO_COUNTRY.get(val)
                if mapped:
                    profile.country = mapped

    profile.profile_url = url
    if profile.avatar_url or profile.birth_date or profile.country:
        return profile

    return None


async def _scrape_from_pornhub_regex(actor_name: str) -> Optional[EnhancedActorProfile]:
    try:
        from app.crawlers.pornhub import _PH_BASE_COOKIES
        from app.services.proxy_manager import get_effective_proxy_url

        ph_name = actor_name.replace(" ", "_")
        url = f"https://www.pornhub.com/pornstar/{ph_name}"
        proxy_url = get_effective_proxy_url()

        client = AsyncHttpClient(proxy=proxy_url, timeout=30)
        resp = await client.get(
            url,
            cookies=_PH_BASE_COOKIES,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
        )

        if not resp or resp.status_code != 200:
            return None

        html = resp.text
        profile = EnhancedActorProfile(name=actor_name)

        name_match = re.search(r'<h1[^>]*class="[^"]*name[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if name_match:
            profile.name = name_match.group(1).strip()

        avatar_match = re.search(r'<img[^>]*id="getAvatar"[^>]*src="([^"]+)"', html, re.DOTALL)
        if avatar_match:
            profile.avatar_url = avatar_match.group(1).strip()
        else:
            avatar_match = re.search(r'<img[^>]*class="[^"]*avatar[^"]*"[^>]*src="([^"]+)"', html, re.DOTALL)
            if avatar_match:
                profile.avatar_url = avatar_match.group(1).strip()

        country_match = re.search(r'<span[^>]*class="[^"]*country[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
        if country_match:
            profile.country = country_match.group(1).strip()

        info_items = re.findall(
            r'<div[^>]*class="[^"]*infoPiece[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>',
            html, re.DOTALL
        )
        for label, value in info_items:
            label_clean = label.strip().lower()
            value_clean = value.strip()
            if "birthday" in label_clean or "born" in label_clean:
                profile.birth_date = value_clean
            elif "height" in label_clean:
                profile.height = value_clean
            elif "measurements" in label_clean:
                profile.measurements = value_clean
            elif "birthplace" in label_clean:
                profile.birthplace = value_clean
            elif "ethnicity" in label_clean:
                profile.ethnicity = value_clean
            elif "country" in label_clean:
                if not profile.country:
                    profile.country = value_clean

        count_pattern = re.compile(r'<span[^>]*class="[^"]*count[^"]*"[^>]*>\s*([\d,.KMB]+)\s*</span>', re.DOTALL)
        count_labels = re.findall(r'<span[^>]*class="[^"]*label[^"]*"[^>]*>\s*(Videos|Photos)\s*</span>', html, re.DOTALL)
        counts = count_pattern.findall(html)
        for i, label in enumerate(count_labels):
            if i < len(counts):
                val = _parse_number(counts[i])
                if label.lower() == "videos":
                    profile.video_count = val
                elif label.lower() == "photos":
                    profile.photo_count = val

        rank_match = re.search(r'#(\d+)\s*Rank', html, re.DOTALL)
        if rank_match:
            profile.rank = int(rank_match.group(1))

        profile.profile_url = url

        if not profile.avatar_url and not profile.birth_date and not profile.country:
            return None

        return profile
    except Exception as e:
        logger.debug("PH regex 解析失败 [%s]: %s", actor_name, e)
        return None


async def _scrape_avatar_from_javdb(actor_name: str) -> Optional[str]:
    try:
        from urllib.parse import quote
        search_url = f"https://javdb.com/search?q={quote(actor_name)}&f=actor"
        client = AsyncHttpClient()
        resp = await client.get(search_url, timeout=15)
        if not resp or resp.status_code != 200:
            return None
        html = resp.text
        avatar_match = re.search(r'<img[^>]*class="[^"]*avatar[^"]*"[^>]*src="(https://[^"]+\.(?:jpg|jpeg|png))"', html, re.DOTALL)
        if avatar_match:
            return avatar_match.group(1)
        return None
    except Exception as e:
        logger.debug("JavDB 头像搜索失败 [%s]: %s", actor_name, e)
        return None


def _parse_number(text: str) -> int:
    if not text:
        return 0
    text = text.strip().replace(",", "").replace(" ", "")
    multipliers = {"K": 1000, "M": 1000000, "B": 1000000000}
    suffix = text[-1].upper() if text else ""
    if suffix in multipliers:
        try:
            return int(float(text[:-1]) * multipliers[suffix])
        except ValueError:
            pass
    try:
        return int(float(text))
    except ValueError:
        return 0