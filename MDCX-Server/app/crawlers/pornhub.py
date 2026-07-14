"""
PORNHub 爬虫

参考来源：
- P0: PornHubDL-main/content.js + inject.js (MIT)
- P0: phdownloader-master/downloader.py (MIT)
- P0: fc2.py (MDCX 现有爬虫架构)

整合说明：
- 元数据提取: 参考 PornHubDL-main flashvars 提取方案 (P0)
- 反爬策略: 参考 phdownloader-master yt-dlp impersonate (P0)
- 爬虫框架: 沿用 MDCX BaseCrawler + ScrapeResult (现有)
"""

import json
import re
from datetime import date
from typing import Optional

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# PORNHub 视频页面 URL 格式
VIEW_PAGE_URL = "https://www.pornhub.com/view_video.php?viewkey={viewkey}"

# 用于从页面提取 flashvars 的正则
FLASHVARS_RE = re.compile(r'flashvars_\w+\s*=\s*({.*?});', re.DOTALL)
MEDIA_DEF_RE = re.compile(r'mediaDefinitions\s*:\s*(\[.*?\]),?\s*(?:\n|\r)', re.DOTALL)


def extract_flashvars_from_html(html_text: str) -> Optional[dict]:
    """从 PornHub 页面 HTML 提取 flashvars 数据（等效于 PornHubDL inject.js 的逻辑）"""
    # 策略1: 直接匹配 flashvars_xxx = {...}
    m = FLASHVARS_RE.search(html_text)
    if m:
        try:
            data = json.loads(m.group(1))
            logger.debug(f"flashvars 提取成功，key 数: {len(data)}")
            return data
        except json.JSONDecodeError:
            logger.warning("flashvars JSON 解析失败，尝试 mediaDefinitions 提取")

    # 策略2: 从 script 标签中提取 mediaDefinitions
    m = MEDIA_DEF_RE.search(html_text)
    if m:
        try:
            data = json.loads(m.group(1))
            logger.debug(f"mediaDefinitions 提取成功，{len(data)} 条")
            return {"mediaDefinitions": data}
        except json.JSONDecodeError:
            logger.warning("mediaDefinitions JSON 解析失败")

    return None


def parse_flashvars_to_metadata(flashvars: dict, viewkey: str) -> Optional[ScrapeResult]:
    """将 flashvars 解析为 ScrapeResult"""
    if not flashvars:
        return None

    # 标题提取
    title = (
        flashvars.get("video_title")
        or flashvars.get("title")
        or ""
    )
    # 清理非法字符
    title = re.sub(r'[\\/:*?"<>|]', '', title).strip()

    # 演员提取
    actors = []
    actors_raw = flashvars.get("actors")
    if isinstance(actors_raw, list):
        for a in actors_raw:
            if isinstance(a, dict):
                name = a.get("name") or a.get("actor", "")
                if name:
                    actors.append(ActorInfo(name=name))
            elif isinstance(a, str):
                actors.append(ActorInfo(name=a))

    # 标签/分类
    tags = flashvars.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    categories = flashvars.get("categories", [])
    if isinstance(categories, list):
        cats = [c.get("category", str(c)) if isinstance(c, dict) else str(c) for c in categories]
    elif isinstance(categories, str):
        cats = [c.strip() for c in categories.split(",") if c.strip()]
    else:
        cats = []

    # 评分
    rating = None
    try:
        rating = float(flashvars.get("rating", 0) or 0)
    except (ValueError, TypeError):
        pass

    # 播放量
    views = None
    try:
        views = int(flashvars.get("views", 0) or 0)
    except (ValueError, TypeError):
        pass

    # 时长
    duration = None
    try:
        duration = int(flashvars.get("video_duration", 0) or 0)
        if duration > 3600:  # 可能以毫秒为单位
            duration = duration // 1000
    except (ValueError, TypeError):
        pass

    # 上传者
    uploader = flashvars.get("uploader") or flashvars.get("username", "")

    # 缩略图
    cover_url = flashvars.get("image_url") or flashvars.get("thumb", "")

    # 构建 ScrapeResult
    result = ScrapeResult(
        code=viewkey,
        title=title,
        source="pornhub",
        original_title=title,
        studio=uploader,
        release_date=None,
        duration=duration if duration and duration > 0 else None,
        rating=rating,
        genres=cats,
        tags=tags,
        actors=actors,
        cover_url=cover_url,
    )

    # 存入原始数据和附加元数据
    result.raw_data = flashvars
    return result


@register_crawler
class PornhubCrawler(BaseCrawler):
    """PORNHub 爬虫

    使用 flashvars 页面注入方案提取元数据（参考 PornHubDL-main），
    配合 yt-dlp impersonate 方案绕过 Cloudflare 反爬（参考 phdownloader-master）。
    """

    name = "pornhub"
    display_name = "PORNHub"
    base_url = "https://www.pornhub.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["pornhub"]
    supported_prefixes = ["ph"]
    description = "PORNHub 视频元数据刮削"
    language = "en"
    requires_proxy = True  # CF 反爬严，推荐走代理

    def _extract_viewkey(self, code: str) -> Optional[str]:
        """从番号提取 viewkey

        支持格式: phabcdef123456 / abcdef123456
        """
        code = code.strip().lower()
        m = re.search(r'(?:ph)?([a-f0-9]{10,20})', code)
        if m:
            return m.group(1)
        return None

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定 viewkey

        流程（参考 PornHubDL-main）：
        1. 获取视频页面 HTML
        2. 从页面提取 flashvars 数据
        3. 解析 flashvars 为结构化元数据
        4. 如 flashvars 缺失，尝试从 mediaDefinitions 提取视频信息
        """
        viewkey = self._extract_viewkey(code)
        if not viewkey:
            logger.warning(f"无效的 viewkey: {code}")
            return None

        async with AsyncHttpClient() as client:
            try:
                url = VIEW_PAGE_URL.format(viewkey=viewkey)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Referer": "https://www.pornhub.com/",
                }

                html_text = await client.get_text(url, headers=headers)

                # 检查是否被 CF 拦截
                if "Just a moment" in html_text or "cf-browser-verification" in html_text:
                    logger.warning(f"PornHub CF 反爬拦截: {url}")
                    self.mark_error()
                    return None

                # 检查页面是否存在
                if "The page you requested cannot be found" in html_text or "404" in html_text[:500]:
                    logger.info(f"视频不存在 (404): {viewkey}")
                    return None

                # 提取 flashvars（参考 PornHubDL inject.js 逻辑）
                flashvars = extract_flashvars_from_html(html_text)

                if not flashvars:
                    # 兜底: 从页面基础 meta 信息提取
                    logger.warning(f"flashvars 提取失败，尝试兜底解析: {viewkey}")
                    result = self._fallback_parse(html_text, viewkey)
                    if result:
                        self.mark_success()
                    else:
                        self.mark_error()
                    return result

                # 解析 flashvars 为 ScrapeResult
                result = parse_flashvars_to_metadata(flashvars, viewkey)
                if not result:
                    logger.warning(f"flashvars 解析后无数据: {viewkey}")
                    self.mark_error()
                    return None

                self.mark_success()
                return result

            except Exception as e:
                logger.error(f"PornHub 刮削失败 [{viewkey}]: {e}")
                self.mark_error()
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 PornHub 视频（通过 PornHub 搜索页）"""
        results = []
        async with AsyncHttpClient() as client:
            try:
                search_url = f"{self.base_url}/video/search?search={keyword}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.pornhub.com/",
                }
                html_text = await client.get_text(search_url, headers=headers)
                if "Just a moment" in html_text:
                    return results

                # 从搜索结果页提取 viewkey 和标题
                pattern = re.compile(
                    r'viewkey=([a-f0-9]+)[^"]*".*?data-movie-title="([^"]+)"',
                    re.DOTALL
                )
                for m in pattern.finditer(html_text):
                    vk = m.group(1)
                    title = m.group(2)
                    if vk and title:
                        results.append(ScrapeResult(
                            code="ph" + vk,
                            title=title.strip(),
                            source="pornhub",
                            cover_url="",
                        ))
                        if len(results) >= 20:
                            break
            except Exception as e:
                logger.error(f"PornHub 搜索失败 [{keyword}]: {e}")

        return results

    def _fallback_parse(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """兜底解析：当 flashvars 不可用时从页面 meta 提取"""
        # 标题: 从 <title> 或 <h1> 提取
        title = ""
        m = re.search(r'<title>(.*?)</title>', html_text, re.DOTALL)
        if m:
            title = m.group(1).replace(" - Pornhub.com", "").replace(" - PornHub", "").strip()

        if not title:
            m = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.DOTALL)
            if m:
                title = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        if not title:
            return None

        # 封面
        cover = ""
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html_text)
        if m:
            cover = m.group(1)

        return ScrapeResult(
            code=viewkey,
            title=title,
            source="pornhub",
            cover_url=cover,
        )
