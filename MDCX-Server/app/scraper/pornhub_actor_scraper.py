"""
PORNHub 演员资料刮削器（增强版）

从 PornHub 官方页面和辅助数据源拉取演员核心资料：
- 全名、别名
- 出生日期、出道年份
- 作品统计量（影片数、视频数）
- 官方头像下载与本地存储
- 去重与完整性校验
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.http_client import AsyncHttpClient
from app.config.manager import DATA_DIR

logger = logging.getLogger(__name__)

# 头像本地存储目录
AVATAR_DIR = DATA_DIR / "avatars" / "pornhub"

# 综合数据源
PH_PAGES_BASE = "https://www.pornhub.com/pornstars"  # /{name}


@dataclass
class EnhancedActorProfile:
    """演员增强资料"""
    name: str
    alias: Optional[str] = None
    avatar_url: Optional[str] = None
    birth_date: Optional[str] = None
    debut_year: Optional[str] = None          # 出道年份
    height: Optional[str] = None
    measurements: Optional[str] = None
    birthplace: Optional[str] = None
    country: Optional[str] = None
    ethnicity: Optional[str] = None
    movie_count: Optional[int] = None          # PornHub 作品数
    photo_count: Optional[int] = None          # 相片数
    video_count: Optional[int] = None          # 视频数
    profile_url: Optional[str] = None          # PornHub 个人主页
    rank: Optional[int] = None                 # 排名
    rank_weekly: Optional[int] = None          # 周排名


async def scrape_actor_profile(actor_name: str, nationality: Optional[str] = None) -> Optional[EnhancedActorProfile]:
    """从 PornHub 和辅助数据源刮削演员资料

    Args:
        actor_name: 演员名称
        nationality: 国籍（可选，用于辅助匹配校验）

    Returns:
        EnhancedActorProfile 或 None（刮削失败）
    """
    # 1. 先从 PornHub 页面爬取
    profile = await _scrape_from_pornhub(actor_name)
    if profile:
        # 校正国籍：路径提取的优先级高于网页爬取
        if nationality and not profile.country:
            profile.country = nationality
        return profile

    # 2. 如果 PH 没有，尝试名称变体搜索
    # 去掉尾随数字
    base_name = re.sub(r'\d+$', '', actor_name).strip()
    if base_name and base_name != actor_name:
        profile = await _scrape_from_pornhub(base_name)
        if profile:
            if nationality and not profile.country:
                profile.country = nationality
            return profile

    # 3. 尝试 JavDB 搜索获取基本信息
    avatar_url = await _scrape_avatar_from_javdb(actor_name)
    if avatar_url:
        return EnhancedActorProfile(
            name=actor_name,
            avatar_url=avatar_url,
            country=nationality,
        )

    return None


async def download_actor_avatar(actor_name: str, avatar_url: str) -> Optional[str]:
    """下载演员头像到本地存储

    Args:
        actor_name: 演员名称
        avatar_url: 头像 URL

    Returns:
        本地文件路径字符串，或 None
    """
    if not avatar_url or not avatar_url.startswith("http"):
        return None

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)

    # 文件名用演员名，去掉不合法字符
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', actor_name).strip()
    local_path = AVATAR_DIR / f"{safe_name}.jpg"

    if local_path.exists():
        return str(local_path)

    try:
        # 获取代理 URL（PornHub 需要翻墙）
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
    """检查资料完整性，返回缺失字段列表"""
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

    completeness = max(0, 100 - len(missing) * 20)  # 每个字段 20%
    return {"completeness": completeness, "missing_fields": missing}


# ==================== 内部实现 ====================


async def _scrape_from_pornhub(actor_name: str) -> Optional[EnhancedActorProfile]:
    """从 PornHub 官方页面爬取演员资料"""
    try:
        from app.crawlers.pornhub import _PH_BASE_COOKIES
        import json

        # PornHub 演员页面 URL
        # 将空格转成下划线，特殊字符处理
        ph_name = actor_name.replace(" ", "_")
        url = f"https://www.pornhub.com/pornstar/{ph_name}"

        # 获取代理 URL（PornHub 需要翻墙）
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()

        client = AsyncHttpClient(proxy=proxy_url)
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
            logger.debug("PH 演员页访问失败 [%s]: HTTP %s", actor_name, resp.status_code if resp else "None")
            return None

        html = resp.text

        # 提取 JSON-LD / script 数据
        profile = EnhancedActorProfile(name=actor_name)

        # 提取名字
        name_match = re.search(r'<h1[^>]*class="[^"]*name[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if name_match:
            profile.name = name_match.group(1).strip()

        # 提取头像URL
        avatar_match = re.search(r'<img[^>]*class="[^"]*avatar[^"]*"[^>]*src="([^"]+)"', html, re.DOTALL)
        if avatar_match:
            profile.avatar_url = avatar_match.group(1).strip()

        # 提取国家/地区
        country_match = re.search(r'<span[^>]*class="[^"]*country[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
        if country_match:
            profile.country = country_match.group(1).strip()

        # 提取粉丝数、排名等统计信息
        stats_section = re.search(r'class="[^"]*statsWrapper[^"]*"', html, re.DOTALL)

        # 从个人资料栏提取详细信息
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

        # 提取视频数量、照片数量
        count_pattern = re.compile(
            r'<span[^>]*class="[^"]*count[^"]*"[^>]*>\s*([\d,.KMB]+)\s*</span>',
            re.DOTALL
        )
        count_labels = re.findall(
            r'<span[^>]*class="[^"]*label[^"]*"[^>]*>\s*(Videos|Photos)\s*</span>',
            html, re.DOTALL
        )
        counts = count_pattern.findall(html)
        for i, label in enumerate(count_labels):
            if i < len(counts):
                val = _parse_number(counts[i])
                if label.lower() == "videos":
                    profile.video_count = val
                elif label.lower() == "photos":
                    profile.photo_count = val

        # 提取排名
        rank_match = re.search(r'#(\d+)\s*Rank', html, re.DOTALL)
        if rank_match:
            profile.rank = int(rank_match.group(1))

        profile.profile_url = url

        # 检查是否提取到基本信息
        if not profile.avatar_url and not profile.birth_date and not profile.country:
            return None

        return profile

    except Exception as e:
        logger.debug("PH 演员页面解析失败 [%s]: %s", actor_name, e)
        return None


async def _scrape_avatar_from_javdb(actor_name: str) -> Optional[str]:
    """从 JavDB 搜索演员头像（降级方案）"""
    try:
        from app.utils.http_client import AsyncHttpClient
        from urllib.parse import quote

        search_url = f"https://javdb.com/search?q={quote(actor_name)}&f=actor"
        client = AsyncHttpClient()
        resp = await client.get(
            search_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            timeout=15,
        )

        if not resp or resp.status_code != 200:
            return None

        html = resp.text
        # 提取第一个演员头像
        avatar_match = re.search(
            r'<img[^>]*class="[^"]*avatar[^"]*"[^>]*src="(https://[^"]+\.(?:jpg|jpeg|png))"',
            html, re.DOTALL
        )
        if avatar_match:
            return avatar_match.group(1)

        # 备选：提取演员卡片中的头像
        avatar_match2 = re.search(
            r'class="[^"]*actor-avatar[^"]*"[^>]*>\s*<img[^>]*src="([^"]+\.(?:jpg|jpeg|png))"',
            html, re.DOTALL
        )
        if avatar_match2:
            return avatar_match2.group(1)

        return None
    except Exception as e:
        logger.debug("JavDB 头像搜索失败 [%s]: %s", actor_name, e)
        return None


def _parse_number(text: str) -> int:
    """解析带 K/M/B 后缀的数字"""
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
