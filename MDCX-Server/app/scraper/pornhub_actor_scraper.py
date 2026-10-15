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
import os
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


def _slugify(name: str) -> str:
    """演员名 → pornhub URL slug。

    2026-10-14 修：原代码用 `actor_name.replace(" ", "_")` 生成下划线 slug，
    实测 `/pornstar/lexi_luna` 返回 200 但抓到的是 **Pornstars 列表页**
    （title="Top Pornstars and Models..."），压根不是详情页 ⇒ `#getAvatar`
    永远取不到 ⇒ 头像功能从未成功。真实 slug 是**连字符**形式
    （`/pornstar/alexis-fawx`），且部分模特只有 `/model/` 路由有页面。
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[''`\.]", "", s)        # 去撇号/点（St. Mary → st-mary）
    s = re.sub(r"[^a-z0-9]+", "-", s)    # 非字母数字一律转连字符
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _url_variants(known_url: Optional[str], actor_name: str) -> list[str]:
    """由"已知 profile_url" + 演员名，推导按优先级排列的候选 URL 列表。

    🔴 2026-10-15：以前刮削完全靠 `slugify(演员名)` 猜 URL，而库里的
    profile_url（来自 PornSimilarityPlatform models.db 的权威映射）压根没被读，
    导致「资料页能点开、但点进去刮削不走这个地址」。现在把已知 URL 放到最前面。

    对已知 URL 做两件事：
      1. 空格等非法字符转义（外部库 49 条是 `/model/Abby Lovee7/videos` 形态）；
      2. 去掉 `/videos` 后缀并派生 `pornstar` / `model` 双路由 —— 与
         _slugify 的既有结论一致（连字符 slug，部分模特只在其中一条路由有页面）。
    去重保序，最终再接上按名字猜的 URL 作为兜底。
    """
    out: list[str] = []

    def add(u: str) -> None:
        u = (u or "").strip()
        if u and u not in out:
            out.append(u)

    if known_url and "pornhub.com" in known_url.lower():
        try:
            from urllib.parse import urlsplit, urlunsplit, quote
            p = urlsplit(known_url.strip())
            path = quote(p.path, safe="/%-_.")
            base = urlunsplit((p.scheme, p.netloc, path, "", ""))
            add(base)
            # 派生去 /videos 的裸主页
            m = re.match(r"^(https?://[^/]+/(?:model|pornstar|channels|users)/[^/]+)/?$",
                         path)
            if m:
                root = urlunsplit((p.scheme, p.netloc, m.group(1), "", ""))
                add(root)
        except Exception as e:
            logger.debug("已知 profile_url 规范化失败 [%s]: %s", known_url, e)

    # 兜底：按名字猜（保持既有行为，连字符 slug）
    slug = _slugify(actor_name)
    # 🔴 守卫：slug 信息量不足时不猜。实测踩坑 `短V` → _slugify 丢掉全部中文只剩
    # "v" → /model/v/videos 是真实路由(200)，会把"短V"错认成名叫 v 的模特。
    if slug and len(slug) >= 3 and not re.search(
            r"onlyfans|chaturbate|fansly|myfans|twitter|tiktok|instagram|patreon",
            actor_name or "", re.I):
        add(f"https://www.pornhub.com/pornstar/{slug}")
        add(f"https://www.pornhub.com/model/{slug}")
        add(f"https://cn.pornhub.com/model/{slug}/videos")
    return out


async def scrape_actor_profile(actor_name: str,
                               nationality: Optional[str] = None,
                               profile_url: Optional[str] = None) -> Optional[EnhancedActorProfile]:
    # 🔴 2026-10-15：先用库里已知的 profile_url 直连，再退回按名字猜。
    if profile_url and "pornhub.com" in profile_url.lower():
        for u in _url_variants(profile_url, actor_name):
            direct = await _scrape_from_known_url(actor_name, u)
            if direct:
                if nationality and not direct.country:
                    direct.country = nationality
                return direct

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

    # 2026-10-05 新增：cn.pornhub.com/model 页面含 #getAvatar（ei.phncdn 头像可下）
    profile = await _scrape_from_cn_model(actor_name)
    if profile:
        if nationality and not profile.country:
            profile.country = nationality
        return profile

    # 🔴 2026-10-14 按用户要求移除 JavDB 头像回退："PORNHUB 只有 PORNHUB 的，
    # 没有其他 JAV 的任何事情"。原实现（2026-10-05 加）在 pornhub 四条路径
    # （selectolax / 去尾数字重试 / regex / cn.model）全失败后，去 javdb.com
    # 搜同名演员借头像，实测两个硬伤：
    #   ① 跨源张冠李戴——javdb 是 JAV 站，搜到的"同名演员"多半不是同一个人；
    #      实测借回来的 URL 是 ei.phncdn.com/pics/users/default/ 占位图，
    #      直接落盘成 actor_{id}.jpg 污染 PORNHUB 演员数据（Wow Girls 案例）。
    #   ② routes 版正则不校验域名/扩展名，实测把 mc.yandex.ru 统计像素
    #      （43 字节）当头像 URL 拉回来（Met Art X 案例）。
    # 现在拿不到就返回 None，按"留空不猜"处理，由自愈任务下轮自然重试。
    return None


# ── 头像内容校验（防把 1x1 占位 GIF / 截断文件当头像写盘）──
# 2026-10-05 修：原 download_actor_avatar 直接 write_bytes(resp.content)，不校验内容，
# PH 返回的 1x1 透明 GIF（43 字节）被当成有效头像落盘；且 `if local_path.exists(): return`
# 导致损坏文件永不再下。现加魔数 + 尺寸双重校验，并删损坏文件后重下。
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM")
_AVATAR_MIN_SIZE = 24  # 像素：小于此视为占位/追踪像素


def _avatar_looks_like_image(content: bytes) -> bool:
    if not content or len(content) < 128:
        return False
    if content.startswith(_IMAGE_MAGIC):
        return True
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    return False


def _avatar_size_ok(content: bytes) -> bool:
    """用 PIL 校验尺寸，挡住 1x1 占位图。"""
    try:
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(content)) as im:
            w, h = im.size
        return w >= _AVATAR_MIN_SIZE and h >= _AVATAR_MIN_SIZE
    except Exception:
        return False


def _valid_avatar_file(path) -> bool:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    return _avatar_looks_like_image(data) and _avatar_size_ok(data)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()
    os.replace(tmp, path)


async def download_actor_avatar(actor_name: str, avatar_url: str) -> Optional[str]:
    if not avatar_url or not avatar_url.startswith("http"):
        return None

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', actor_name).strip()
    local_path = AVATAR_DIR / f"{safe_name}.jpg"

    # 已有文件：仅当内容有效才复用；损坏（1x1/截断）则删掉重下
    if local_path.exists():
        if _valid_avatar_file(local_path):
            return str(local_path)
        try:
            local_path.unlink()
        except OSError:
            pass

    try:
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()
        client = AsyncHttpClient(proxy=proxy_url)
        resp = await client.get(avatar_url, timeout=30, purpose="download")
        if resp and resp.status_code == 200:
            content = resp.content
            if not _avatar_looks_like_image(content) or not _avatar_size_ok(content):
                logger.warning(
                    "头像内容无效（占位图/截断）：%s -> %d bytes，跳过落盘",
                    avatar_url, len(content),
                )
                return None
            _atomic_write_bytes(local_path, content)
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
                impersonate=impersonate,
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

    # 2026-10-14：连字符 slug + 双路由（pornstar/model）。下划线 slug 会抓到
    # 列表页而非详情页；部分模特（uploader/amateur）只有 /model/ 有页面。
    slug = _slugify(actor_name)
    best: Optional[EnhancedActorProfile] = None
    for route in ("pornstar", "model"):
        url = f"https://www.pornhub.com/{route}/{slug}"

        html = await _fetch_with_impersonate_fallback(url, _PH_BASE_COOKIES)
        if not html:
            continue

        try:
            tree = HTMLParser(html)
        except Exception:
            continue

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
        # 头像优先：本路由有头像就直接返回；否则留作兜底继续试下一个路由
        if profile.avatar_url:
            return profile
        if (profile.birth_date or profile.country) and best is None:
            best = profile

    return best


async def _scrape_from_pornhub_regex(actor_name: str) -> Optional[EnhancedActorProfile]:
    try:
        from app.crawlers.pornhub import _PH_BASE_COOKIES
        from app.services.proxy_manager import get_effective_proxy_url

        # 2026-10-14：连字符 slug + 双路由。下划线 slug 抓到的是列表页（无头像）。
        slug = _slugify(actor_name)
        proxy_url = get_effective_proxy_url()

        client = AsyncHttpClient(proxy=proxy_url, timeout=30)
        best: Optional[EnhancedActorProfile] = None

        for route in ("pornstar", "model"):
            url = f"https://www.pornhub.com/{route}/{slug}"
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
                continue

            html = resp.text
            profile = EnhancedActorProfile(name=actor_name)

            name_match = re.search(r'<h1[^>]*class="[^"]*name[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
            if name_match:
                profile.name = name_match.group(1).strip()

            avatar_match = re.search(r'<img[^>]*id="getAvatar"[^>]*src="([^"]+)"', html, re.DOTALL)
            if avatar_match:
                profile.avatar_url = avatar_match.group(1).strip()
            else:
                avatar_match = re.search(r'<img[^>]*id="getAvatar"[^>]*data-src="([^"]+)"', html, re.DOTALL)
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

            # 头像优先：本路由有头像直接返回；否则留作兜底继续试下一个路由
            if profile.avatar_url:
                return profile
            if (profile.birth_date or profile.country) and best is None:
                best = profile

        return best
    except Exception as e:
        logger.debug("PH regex 解析失败 [%s]: %s", actor_name, e)
        return None


async def _scrape_from_cn_model(actor_name: str) -> Optional[EnhancedActorProfile]:
    """从 cn.pornhub.com/model/{name}/videos 提取头像。

    2026-10-05 新增：本机 venv 未安装 selectolax，导致 _scrape_from_pornhub_selectolax
    直接 ImportError 返回 None；而 www.pornhub.com/pornstar/{name} 页面（regex 路径）
    不含 #getAvatar 元素，头像 URL 取不到。实测 cn.pornhub.com/model/{name}/videos
    页面含 #getAvatar 且 ei.phncdn.com 头像可正常下载（200/有效 JPEG）。
    故在此补充一条 regex 提取路径，覆盖 uploader/amateurs 类演员。
    """
    from app.services.proxy_manager import get_effective_proxy_url

    # 2026-10-14：必须用连字符 slug。原代码直接拼原始名（带空格），
    # URL 里的空格会被编码成 %20， pornhub 无此路由 ⇒ 永远 404。
    slug = _slugify(actor_name)
    url = f"https://cn.pornhub.com/model/{slug}/videos"
    proxy_url = get_effective_proxy_url()
    try:
        client = AsyncHttpClient(proxy=proxy_url, timeout=30)
        resp = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
        )
        if not resp or resp.status_code != 200:
            return None
        html = resp.text
        avatar_url = None
        m = re.search(r'<img[^>]*id="getAvatar"[^>]*src="([^"]+)"', html, re.DOTALL)
        if m:
            avatar_url = m.group(1).strip()
        else:
            m2 = re.search(
                r'<img[^>]*id="getAvatar"[^>]*data-src="([^"]+)"', html, re.DOTALL
            )
            if m2:
                avatar_url = m2.group(1).strip()
        if not avatar_url:
            return None
        return EnhancedActorProfile(
            name=actor_name, avatar_url=avatar_url, profile_url=url
        )
    except Exception as e:
        logger.debug("cn.model 抓取失败 [%s]: %s", actor_name, e)
        return None


async def _scrape_from_known_url(actor_name: str, url: str) -> Optional[EnhancedActorProfile]:
    """直接抓取给定的 PornHub 模特 URL 并解析资料（2026-10-15 新增）。

    与 _scrape_from_cn_model 的区别：URL 由外部库权威给定（不是按名字猜），
    且除头像外一并解析资料页上的姓名/国家/生日/三围等字段。

    列表页防呆：`/pornstars`、`/models` 这类聚合页会返回 200，用 _is_list_page() 判定，
    命中即视为无效。

    🔴 2026-10-15 实测（服务器代理直抓 cn.pornhub.com）：
      对 10 个"PornHub 上确实存在但 PSP 未收录"的演员（Rich Jay / Meg Vicious /
      Abella Olsen / Bratty Sis / carrots / DeNata …）：
        `cn.pornhub.com/model/{slug}/videos` → **10/10 是真实资料页**（title="XXX的全新色情片2026"）
        `cn.pornhub.com/pornstar/{slug}`     → 多数退化为聚合列表页（title="完整版免费色情片中的顶流色情明星及模特"）
      且聚合页 title 是中文，`startswith("Top Pornstars")` 那套英文判据根本拦不住，
      必须在内容层（<h1> + profile 区块）判定。
    """
    try:
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()
        client = AsyncHttpClient(proxy=proxy_url, timeout=30)
        resp = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
        )
        if not resp or resp.status_code != 200:
            return None
        html = resp.text or ""
        if not html:
            return None

        if _is_list_page(html):
            logger.debug("已知 URL 命中聚合/列表页，丢弃 [%s]: %s", actor_name, url)
            return None

        profile = EnhancedActorProfile(name=actor_name, profile_url=url)

        # 头像：优先 #getAvatar，其次 og:image
        m = re.search(r'<img[^>]*id="getAvatar"[^>]*(?:data-src|src)="([^"]+)"',
                      html, re.DOTALL)
        if not m:
            m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"',
                          html, re.DOTALL | re.IGNORECASE)
        if m:
            profile.avatar_url = m.group(1).strip()

        # 姓名：og:title / h1
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        if m:
            nm = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if nm:
                profile.name = nm
        else:
            m = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
                          html, re.DOTALL | re.IGNORECASE)
            if m:
                profile.name = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        profile.country = _extract_country_from_html(html)

        for label, value in re.findall(r'<span class="meta[^"]*"[^>]*>\s*([^:]{1,20}):?\s*</span>'
                                       r'\s*<span[^>]*>\s*([^<]{1,60}?)\s*</span>',
                                       html, re.DOTALL | re.IGNORECASE):
            key = label.strip().lower()
            val = value.strip()
            if not val:
                continue
            if key in ("birthday", "birth date", "born"):
                profile.birth_date = val
            elif key == "height":
                profile.height = val
            elif key in ("measurements", "measurements "):
                profile.measurements = val
            elif key in ("birth place", "birthplace"):
                profile.birthplace = val
            elif key == "ethnicity":
                profile.ethnicity = val
            elif key == "background":
                profile.background = val
                if not profile.country:
                    mapped = _NATIONALITY_TO_COUNTRY.get(val)
                    if mapped:
                        profile.country = mapped

        # 🔴 严格校验：必须命中资料页强特征才算数。
        # 只判"有没有解析到字段"会误收——任何 PornHub 页面（乃至别的模特的页面）
        # 都可能带 og:image / birthday，导致把 A 的资料当成 B 的。
        # 实测可靠特征：id="profileImages" / class="profileHeader" / id="profile"。
        has_profile_marker = any(re.search(p, html, re.IGNORECASE)
                                 for p in ('id="profileImages"', 'id="profile"',
                                           r'class="profileHeader"', r'id="profileVideos"'))
        if not has_profile_marker:
            logger.debug("页面无资料页特征，丢弃 [%s]: %s", actor_name, url)
            return None

        # 什么都没有拿到 → 视为失败，走下一个候选 URL
        if not (profile.avatar_url or profile.birth_date or profile.country
                or profile.birthplace or profile.measurements):
            logger.debug("已知 URL 未解析到有效字段 [%s]: %s", actor_name, url)
            return None
        return profile
    except Exception as e:
        logger.debug("已知 URL 抓取失败 [%s] %s: %s", actor_name, url, e)
        return None


_LIST_TITLE_MARKERS = (
    # 英文
    "top pornstars", "pornstars and models", "all pornstars", "browse models",
    # 🔴 中文聚合页（实测 cn.pornhub.com/pornstar/{不存在slug} 会返回这个）
    "顶流色情明星", "色情明星和模特", "全部色情明星",
)

# 资料页的强特征（任一命中即认为是"个人资料页"）
_PROFILE_MARKERS = (
    r'id="profileImages"', r'id="profile"', r'class="profileHeader"',
    r'id="getAvatar"', r'id="profileVideos"', r'class="profileWrapper"',
)


def _is_list_page(html: str) -> bool:
    """判定 HTML 是否为 PornHub 聚合/列表页而非某演员的资料页。

    🔴 2026-10-15 实测依据：`/pornstar/{不存在的slug}` 与 `/pornstar/{存在但仅
    有model页的slug}` 都返回 200，title 是中文「完整版免费色情片中的顶流色情明星
    及模特 | Pornhub」，英文 `startswith("Top Pornstars")` 判据拦不住。
    正确做法：看**内容特征**——列表页没有个人资料区块(profileImages/profileHeader/
    getAvatar)，而真资料页一定有。
    """
    if not html:
        return True
    # 先看强特征：有 ⇒ 是资料页，直接否掉列表页判定
    for pat in _PROFILE_MARKERS:
        if re.search(pat, html, re.IGNORECASE):
            return False
    # 无任何资料区块 ⇒ 视为列表/404 兜底页
    tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.IGNORECASE)
    title = re.sub(r"\s+", " ", tm.group(1)).strip().lower() if tm else ""
    for m in _LIST_TITLE_MARKERS:
        if m in title:
            return True
    # 无 profile 区块且标题含"明星/模特/列表"字样，也算列表页
    if any(k in title for k in ("明星", "模特", "列表")):
        return True
    return False


def _extract_country_from_html(html: str) -> Optional[str]:
    """从资料页 HTML 粗提国家/地区。取不到返回 None（留空不猜）。"""
    for pat in (r'<span[^>]*class="[^"]*meta[^"]*"[^>]*>\s*Country\s*:\s*</span>\s*'
                r'<span[^>]*>\s*([^<]{2,40}?)\s*</span>',
                r'<span[^>]*>\s*Country\s*:\s*</span>\s*<span[^>]*>\s*([^<]{2,40}?)\s*</span>'):
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            if val and val.lower() not in ("n/a", "-"):
                return val
    return None


# 🔴 2026-10-14 移除 _scrape_avatar_from_javdb（原 548-563 行）：
# 用户明确要求"PORNHUB 只有 PORNHUB 的，没有其他 JAV 的任何事情"。
# 该函数在 pornhub 路径全失败时去 javdb.com/search?q=<演员名>&f=actor
# 借头像，实测污染数据（占位图/统计像素/跨源错配），详见
# scrape_actor_profile 末尾的禁用注释。PORNHUB 演员拿不到头像就留空。


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