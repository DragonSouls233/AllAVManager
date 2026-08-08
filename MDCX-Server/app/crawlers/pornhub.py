"""
PORNHub 爬虫

参考来源（已整合）：
- VaultX/pornhub_adapter.py: HTML 解析选择器（userInfo, usernameWrap, count, percent)
- PornSimilarityPlatform/pornhub_scraper.py: 演员信息/视频列表提取
- Hitomi-Downloader/pornhub_downloader.py: age_verified cookie, Premium 降级, fix_soup, get_videos AJAX 分页
- yt-dlp/extractor/pornhub.py: flashvars/script 提取, login, mediaDefinitions
- PornHubDL-main: flashvars 注入方案 (P0)
"""

import json
import re
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

VIEW_PAGE_URL = "https://www.pornhub.com/view_video.php?viewkey={viewkey}"
CN_BASE_URL = "https://cn.pornhub.com"

# PornHub 需要的 cookies（对标 Hitomi-Downloader 第241-245行）
_PH_BASE_COOKIES = {
    "age_verified": "1",
    "accessAgeDisclaimerPH": "1",
    "accessPH": "1",
}

# 从 script 标签中提取 flashvars 的正则
FLASHVARS_RE = re.compile(r'flashvars_(\w+)\s*=\s*({.*?});', re.DOTALL)
MEDIA_DEF_RE = re.compile(r'mediaDefinitions\s*:\s*(\[.*?\])\s*[,;]', re.DOTALL)
SCRIPT_JSON_RE = re.compile(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', re.DOTALL)


def _parse_number(text: str) -> int:
    """解析带 K/M/B 后缀的数字（参考 PornSimilarityPlatform）"""
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


def _parse_duration_to_seconds(duration_str: str) -> Optional[int]:
    """解析时长字符串（参考 PornSimilarityPlatform）
    支持格式: "12:34" / "1:12:34" / "45 min"
    """
    if not duration_str:
        return None
    duration_str = duration_str.strip()
    # mm:ss 或 hh:mm:ss
    parts = duration_str.split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    elif len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            pass
    return None


@register_crawler
class PornhubCrawler(BaseCrawler):
    """PORNHub 爬虫（v2 - 参考 VaultX / Hitomi-Downloader / PornSimilarityPlatform 重构）

    多级提取策略：
    1. flashvars 脚本变量提取（最快，完整元数据）
    2. __INITIAL_STATE__ JSON 提取（React SSR 数据）
    3. HTML (BeautifulSoup) 页面解析（兜底）
    """

    name = "pornhub"
    display_name = "PORNHub"
    base_url = "https://www.pornhub.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["pornhub"]
    supported_prefixes = ["ph"]
    description = "PORNHub 视频元数据刮削"
    language = "en"
    requires_proxy = True

    def _extract_viewkey(self, code: str) -> Optional[str]:
        code = code.strip().lower()
        m = re.search(r'(?:ph)?([a-f0-9]{10,20})', code)
        return m.group(1) if m else None

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        viewkey = self._extract_viewkey(code)
        if not viewkey:
            logger.warning(f"无效的 viewkey: {code}")
            return None

        url = VIEW_PAGE_URL.format(viewkey=viewkey)

        # 优先使用上下文中的 http_client（复用指纹池和代理）
        if ctx and hasattr(ctx, "http_client") and ctx.http_client:
            client = ctx.http_client
            need_close = False
        else:
            client = AsyncHttpClient()
            await client.init_session()
            need_close = True

        try:
            html_text = await client.get_text(
                url,
                cookies=_PH_BASE_COOKIES,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.pornhub.com/",
                },
                timeout=30,
            )

            # 检查 Cloudflare 拦截
            if not html_text or len(html_text) < 500:
                logger.warning(f"PornHub 返回空页面: {url}")
                self.mark_error()
                return None

            if "Just a moment" in html_text or "cf-browser-verification" in html_text:
                logger.warning(f"PornHub CF 反爬拦截: {url}")
                self.mark_error()
                return None

            # 检查页面是否存在
            if "The page you requested cannot be found" in html_text or "Page not found" in html_text:
                logger.info(f"视频不存在: {viewkey}")
                return None

            # === 策略1: flashvars 提取（参考 PornHubDL inject.js + yt-dlp） ===
            result = self._try_flashvars(html_text, viewkey)
            if result:
                self.mark_success()
                return result

            # === 策略2: __INITIAL_STATE__ 提取 ===
            result = self._try_initial_state(html_text, viewkey)
            if result:
                self.mark_success()
                return result

            # === 策略3: HTML 页面解析兜底（参考 Hitomi-Downloader 第135-141行 + VaultX） ===
            result = self._parse_html(html_text, viewkey)
            if result:
                self.mark_success()
                return result

            logger.warning(f"所有提取策略均失败: {viewkey}")
            self.mark_error()
            return None

        except Exception as e:
            logger.error(f"PornHub 刮削失败 [{viewkey}]: {e}")
            self.mark_error()
            return None
        finally:
            if need_close:
                await client.close_session()

    # ===== 提取策略 =====

    def _try_flashvars(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """策略1: 从 flashvars 脚本变量中提取（参考 PornHubDL inject.js）"""
        # 匹配 flashvars_xxx = {...};
        m = FLASHVARS_RE.search(html_text)
        if not m:
            return None

        try:
            flashvars = json.loads(m.group(2))
        except json.JSONDecodeError:
            return None
        if not flashvars:
            return None

        return self._build_result_from_dict(flashvars, viewkey, source="flashvars")

    def _try_initial_state(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """策略2: 从 __INITIAL_STATE__ JSON 中提取（React SSR 数据）"""
        m = SCRIPT_JSON_RE.search(html_text)
        if not m:
            return None

        try:
            state = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

        # 尝试从 mediaDefinitions 获取
        video_data = state.get("video", {})
        if not video_data:
            return None

        # 合并 mediaDefinitions 到数据结构中
        data = {
            "video_title": video_data.get("title"),
            "title": video_data.get("title"),
            "duration": video_data.get("duration"),
            "views": video_data.get("views"),
            "rating": video_data.get("rating"),
            "is_hd": video_data.get("is_hd"),
        }

        # 从 videoData 或 mediaDefinitions 中提取演员
        actors = []
        for ps in video_data.get("pornstars", []):
            if isinstance(ps, dict):
                name = ps.get("star", {}).get("name") if isinstance(ps.get("star"), dict) else ps.get("name")
                if name:
                    actors.append(ActorInfo(name=name))
            elif isinstance(ps, str):
                actors.append(ActorInfo(name=ps))

        # 标签
        tags = [t.get("tag_name", str(t)) if isinstance(t, dict) else str(t) for t in video_data.get("tags", [])]
        categories = [c.get("category", str(c)) if isinstance(c, dict) else str(c) for c in video_data.get("categories", [])]

        # 缩略图
        cover = video_data.get("poster_url") or video_data.get("thumb") or video_data.get("image_url", "")

        result = ScrapeResult(
            code=viewkey,
            title=data.get("video_title") or data.get("title") or "",
            source="pornhub",
            original_title=data.get("title", ""),
            cover_url=cover,
        )
        if actors:
            result.actors = actors
        if tags:
            result.tags = tags
        if categories:
            result.genres = categories

        duration = self._parse_duration_value(data.get("duration"))
        if duration:
            result.duration = duration

        try:
            if data.get("rating"):
                result.rating = float(data["rating"])
        except (ValueError, TypeError):
            pass

        result.raw_data = video_data
        return result

    def _try_media_definitions(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """从 mediaDefinitions JSON 中提取（yt-dlp 兜底方案）"""
        # 查找 mediaDefinitions: [...]
        m = MEDIA_DEF_RE.search(html_text)
        if not m:
            return None
        try:
            medias = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        if not medias:
            return None

        data = {"mediaDefinitions": medias}

        # 尝试搜索 title 等关联数据
        title_m = re.search(r'<title>(.*?)</title>', html_text, re.DOTALL)
        title = ""
        if title_m:
            title = title_m.group(1).replace(" - Pornhub.com", "").replace(" - PornHub", "").strip()

        if not title:
            title_h1 = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html_text, re.DOTALL)
            if title_h1:
                title = re.sub(r'<[^>]+>', '', title_h1.group(1)).strip()

        result = ScrapeResult(
            code=viewkey,
            title=title,
            source="pornhub",
        )

        # 尝试从页面中提取更多信息
        # 演员
        actors = []
        for m_a in re.finditer(r'/pornstar/([^"&?]+)', html_text):
            name = m_a.group(1).replace("-", " ").title().strip()
            if name and name not in actors:
                actors.append(ActorInfo(name=name))

        if not actors:
            for m_a in re.finditer(r'"pornstarName"[^>]*>\s*([^<]+)\s*<', html_text):
                name = m_a.group(1).strip()
                if name:
                    actors.append(ActorInfo(name=name))

        if actors:
            result.actors = actors

        # 封面
        cover_m = re.search(r'<meta property="og:image" content="([^"]+)"', html_text)
        if cover_m:
            result.cover_url = cover_m.group(1)

        # 评分
        rating_m = re.search(r'<span[^>]*class="percent"[^>]*>([^<]+)%', html_text)
        if rating_m:
            try:
                result.rating = float(rating_m.group(1))
            except ValueError:
                pass

        result.raw_data = data
        return result

    # ===== HTML 解析兜底 =====

    def _parse_html(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """策略3: HTML 页面解析（参考 Hitomi-Downloader 第135-141行 + VaultX 第96-132行）

        使用正则提取关键字段，不依赖 BeautifulSoup 减少依赖。
        """
        title = self._extract_title_html(html_text)
        if not title:
            return None

        result = ScrapeResult(
            code=viewkey,
            title=title,
            source="pornhub",
        )

        # 封面
        cover = self._extract_cover_html(html_text)
        if cover:
            result.cover_url = cover

        # 演员（参考 Hitomi-Downloader 第141行: soup.find('div', class_='userInfo')...）
        actors = self._extract_actors_html(html_text)
        if actors:
            result.actors = actors

        # 时长（参考 VaultX: var class_='duration'）
        duration = self._extract_duration_html(html_text)
        if duration:
            result.duration = duration

        # 评分（参考 VaultX: span class_='percent'）
        rating = self._extract_rating_html(html_text)
        if rating is not None:
            result.rating = rating

        # 播放量（参考 VaultX: span class_='count'）
        views = self._extract_views_html(html_text)
        if views is not None:
            result.votes = views

        # 标签/分类（参考 VaultX: div class_='categoriesWrapper'）
        tags, categories = self._extract_tags_html(html_text)
        if tags:
            result.tags = tags
        if categories:
            result.genres = categories

        # 上传者（作为 studio）
        uploader = self._extract_uploader_html(html_text)
        if uploader:
            result.studio = uploader

        # 原始数据尝试
        fv = self._try_flashvars(html_text, viewkey)
        if fv and fv.raw_data:
            result.raw_data = fv.raw_data
        else:
            md = self._try_media_definitions(html_text, viewkey)
            if md:
                result.raw_data = md.raw_data if hasattr(md, "raw_data") else {}

        return result

    def _extract_title_html(self, html: str) -> str:
        """从 HTML 提取标题（参考 Hitomi-Downloader 第135行）"""
        # 首选 og:title
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.I)
        if m:
            title = m.group(1)
            title = re.sub(r'\s*-\s*(?:Pornhub\.com|PornHub)\s*$', '', title).strip()
            if title:
                return title

        # h1.title（参考 Hitomi-Downloader 第135行）
        m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if m:
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if title:
                return title

        # data-video-title（yt-dlp 参考）
        m = re.search(r'data-video-title\s*=\s*"([^"]+)"', html)
        if m:
            return m.group(1)

        # <title> 兜底
        m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
        if m:
            title = m.group(1).replace(" - Pornhub.com", "").replace(" - PornHub", "").strip()
            return title
        return ""

    def _extract_cover_html(self, html: str) -> Optional[str]:
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.I)
        if m:
            return m.group(1)
        m = re.search(r'<link\s+rel="image_src"\s+href="([^"]+)"', html, re.I)
        if m:
            return m.group(1)
        # data-image / poster 属性
        m = re.search(r'(?:data-image|poster)\s*=\s*"([^"]*phncdn[^"]+)"', html)
        if m:
            return m.group(1)
        return None

    def _extract_actors_html(self, html: str) -> list[ActorInfo]:
        """从 HTML 提取演员列表（参考 VaultX/Hitomi-Downloader 第141行）"""
        actors = []
        seen = set()

        # 方案1: pornstarsWrapper（参考 VaultX 第113行）
        # 查找 pornstarsWrapper 区块内的所有 a 标签
        pw_match = re.search(r'class="[^"]*pornstarsWrapper[^"]*"(.*?)(?=class="|</div>\s*</div>)', html, re.DOTALL)
        if pw_match:
            for m_a in re.finditer(r'<a[^>]*href="[^"]*(?:pornstar|model)/([^"/&?]+)[^"]*"[^>]*>\s*([^<]+)', pw_match.group(1), re.DOTALL):
                name = (m_a.group(2) or m_a.group(1)).strip()
                if name and name not in seen:
                    seen.add(name)
                    actors.append(ActorInfo(name=name))

        # 方案2: userInfo > usernameWrap（参考 Hitomi-Downloader 第141行 + VaultX 第105-109行）
        if not actors:
            ui_match = re.search(r'class="[^"]*userInfo[^"]*"(.*?)(?=class="|</div>\s*</div>)', html, re.DOTALL)
            if ui_match:
                uw_match = re.search(r'class="[^"]*usernameWrap[^"]*"[^>]*>\s*<a[^>]*>\s*([^<]+)', ui_match.group(1))
                if uw_match:
                    name = uw_match.group(1).strip()
                    if name:
                        actors.append(ActorInfo(name=name))

        # 方案3: 从 data-video-pornstars 属性提取
        if not actors:
            m_p = re.search(r'data-video-pornstars\s*=\s*"([^"]+)"', html)
            if m_p:
                for part in m_p.group(1).split(","):
                    name = part.strip()
                    if name and name not in seen:
                        seen.add(name)
                        actors.append(ActorInfo(name=name))

        # 方案4: /pornstar/ 链接中的名字
        if not actors:
            for m_a in re.finditer(r'<a[^>]*href="[^"]*(?:pornstar|model)/([^"/&?]+)"[^>]*>', html):
                name = m_a.group(1).replace("-", " ").title().strip()
                if name and name not in seen and len(name) < 50:
                    seen.add(name)
                    actors.append(ActorInfo(name=name))

        return actors

    def _extract_duration_html(self, html: str) -> Optional[int]:
        """提取时长（参考 VaultX: var class='duration'）"""
        # duration 元素
        m = re.search(r'<var[^>]*class="[^"]*duration[^"]*"[^>]*>\s*([^<]+)', html)
        if m:
            dur = _parse_duration_to_seconds(m.group(1).strip())
            if dur:
                return dur

        # meta duration
        m = re.search(r'<meta\s+property="video:duration"\s+content="(\d+)"', html, re.I)
        if m:
            return int(m.group(1))

        # data-duration
        m = re.search(r'data-duration\s*=\s*["\'](\d+)["\']', html)
        if m:
            return int(m.group(1))

        return None

    def _extract_rating_html(self, html: str) -> Optional[float]:
        """提取评分（参考 VaultX 第126-132行: span class='percent'）"""
        m = re.search(r'<span[^>]*class="[^"]*percent[^"]*"[^>]*>\s*(\d+(?:\.\d+)?)\s*%', html)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        # votesUp / votesDown
        up = 0
        down = 0
        m_up = re.search(r'data-rating\s*=\s*["\'](\d+)["\'][^>]*votesUp', html)
        if m_up:
            up = int(m_up.group(1))
        m_down = re.search(r'data-rating\s*=\s*["\'](\d+)["\'][^>]*votesDown', html)
        if m_down:
            down = int(m_down.group(1))
        if up + down > 0:
            return round(up / (up + down) * 10, 1)
        return None

    def _extract_views_html(self, html: str) -> Optional[int]:
        """提取播放量（参考 VaultX 第121-123行: span class='count'）"""
        m = re.search(r'<span[^>]*class="[^"]*count[^"]*"[^>]*>\s*([^<]+)', html)
        if m:
            return _parse_number(m.group(1))
        return None

    def _extract_tags_html(self, html: str) -> tuple[list[str], list[str]]:
        """提取标签和分类（参考 VaultX 第114-119行: div class='categoriesWrapper')"""
        tags = []
        categories = []

        # 分类（categoriesWrapper 区块，参考 VaultX 第114行）
        cat_match = re.search(r'class="[^"]*categoriesWrapper[^"]*"(.*?)(?=class="|</div>\s*</div>)', html, re.DOTALL)
        if cat_match:
            for m_a in re.finditer(r'<a[^>]*>\s*([^<]+)\s*</a>', cat_match.group(1)):
                text = m_a.group(1).strip()
                if text and text not in ("All", "Categories"):
                    categories.append(text)

        # 标签（tagsWrapper 区块）
        tag_match = re.search(r'class="[^"]*tagsWrapper[^"]*"(.*?)(?=class="|</div>\s*</div>)', html, re.DOTALL)
        if tag_match:
            for m_a in re.finditer(r'<a[^>]*>\s*([^<]+)\s*</a>', tag_match.group(1)):
                text = m_a.group(1).strip()
                if text:
                    tags.append(text)

        # 通用标签提取
        if not tags and not categories:
            for m_a in re.finditer(r'<a[^>]*href="/video\?c=\d+[^"]*"[^>]*>\s*([^<]+)\s*</a>', html):
                text = m_a.group(1).strip()
                if text:
                    categories.append(text)
            for m_a in re.finditer(r'<a[^>]*href="/tags/[^"]*"[^>]*>\s*([^<]+)\s*</a>', html):
                text = m_a.group(1).strip()
                if text:
                    tags.append(text)

        return tags, categories

    def _extract_uploader_html(self, html: str) -> Optional[str]:
        """提取上传者"""
        m = re.search(r'class="[^"]*usernameWrap[^"]*"[^>]*>\s*<a[^>]*>\s*([^<]+)', html)
        if m:
            return m.group(1).strip()
        m = re.search(r'"uploader"\s*:\s*"([^"]+)"', html)
        if m:
            return m.group(1)
        return None

    # ===== 工具方法 =====

    def _build_result_from_dict(self, data: dict, viewkey: str, source: str = "flashvars") -> ScrapeResult:
        """从字典构建 ScrapeResult"""
        title = (
            data.get("video_title")
            or data.get("title")
            or ""
        )
        title = re.sub(r'[\\/:*?"<>|]', '', title).strip()

        result = ScrapeResult(
            code=viewkey,
            title=title,
            source="pornhub",
            original_title=title,
        )

        # 演员
        actors_raw = data.get("actors") or data.get("pornstars") or []
        if isinstance(actors_raw, list):
            actors = []
            for a in actors_raw:
                if isinstance(a, dict):
                    name = a.get("name") or a.get("actor") or a.get("star_name", "")
                    if name:
                        actors.append(ActorInfo(name=name))
                elif isinstance(a, str):
                    actors.append(ActorInfo(name=a))
            if actors:
                result.actors = actors

        # 标签/分类
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if tags:
            result.tags = tags if isinstance(tags, list) else []

        categories = data.get("categories", [])
        if isinstance(categories, list):
            cats = []
            for c in categories:
                if isinstance(c, dict):
                    cats.append(c.get("category", str(c)))
                else:
                    cats.append(str(c))
            if cats:
                result.genres = cats

        # 评分
        try:
            rating = float(data.get("rating", 0) or 0)
            if rating > 0:
                result.rating = rating
        except (ValueError, TypeError):
            pass

        # 播放量
        try:
            views = int(data.get("views", 0) or 0)
            if views > 0:
                result.votes = views
        except (ValueError, TypeError):
            pass

        # 时长
        result.duration = self._parse_duration_value(data.get("video_duration") or data.get("duration"))

        # 上传者（作为 studio）
        uploader = data.get("uploader") or data.get("username", "")
        if uploader:
            result.studio = uploader

        # 缩略图
        result.cover_url = data.get("image_url") or data.get("thumb") or data.get("poster_url", "")

        # 原始数据
        result.raw_data = data
        return result

    @staticmethod
    def _parse_duration_value(value) -> Optional[int]:
        """解析时长值"""
        if value is None:
            return None
        try:
            duration = int(value)
            if duration <= 0:
                return None
            if duration > 3600:
                duration = duration // 1000
            return duration
        except (ValueError, TypeError):
            pass
        return None

    # ===== 搜索 =====

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 PornHub 视频"""
        results = []
        client = AsyncHttpClient()
        await client.init_session()
        try:
            search_url = f"{self.base_url}/video/search?search={keyword}"
            html_text = await client.get_text(
                search_url,
                cookies=_PH_BASE_COOKIES,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.pornhub.com/",
                },
            )

            if not html_text or "Just a moment" in html_text:
                return results

            # 从搜索结果中提取视频
            seen = set()

            # 方案1: viewkey 提取 - 多种属性
            for m in re.finditer(r'viewkey=([a-f0-9]+)', html_text):
                vk = m.group(1)
                if vk not in seen:
                    seen.add(vk)

            # 方案2: data-video-title + viewkey 匹配
            for m in re.finditer(
                r'viewkey=([a-f0-9]+)[^"]*".*?data-movie-title="([^"]+)"',
                html_text,
                re.DOTALL,
            ):
                vk = m.group(1)
                title = m.group(2)
                if vk and title:
                    result = ScrapeResult(
                        code="ph" + vk,
                        title=title.strip(),
                        source="pornhub",
                    )
                    # 提取缩略图
                    thumb_m = re.search(
                        rf'viewkey={vk}[^"]*".*?(?:data-src|src)="([^"]*phncdn[^"]+\.jpg)"',
                        html_text[:html_text.find(f"viewkey={vk}") + 2000],
                        re.DOTALL,
                    )
                    if thumb_m:
                        result.cover_url = thumb_m.group(1)
                    results.append(result)
                    if len(results) >= 20:
                        break

        except Exception as e:
            logger.error(f"PornHub 搜索失败 [{keyword}]: {e}")
        finally:
            await client.close_session()

        return results

    # ===== 演员视频列表（对比查重用） =====

    async def fetch_actress_videos(self, actress_url: str, max_pages: int = 5) -> list[dict]:
        """获取演员主页下的视频列表（供对比查重使用）。

        兼容 model / pornstar / channels 等演员主页 URL，逐页提取
        viewkey + 标题 + 缩略图，返回与 compare 消费格式一致的 dict 列表。
        """
        results: list[dict] = []
        if not actress_url:
            return results

        base = actress_url.strip()
        if base.startswith("//"):
            base = "https:" + base
        elif base.startswith("/"):
            base = self.base_url + base

        client = AsyncHttpClient()
        await client.init_session()
        try:
            pages = max(1, min(int(max_pages), 20))
            for page in range(1, pages + 1):
                url = f"{base}?page={page}" if page > 1 else base
                html_text = await client.get_text(
                    url,
                    cookies=_PH_BASE_COOKIES,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://www.pornhub.com/",
                    },
                    timeout=30,
                )
                if not html_text or "Just a moment" in html_text or "cf-browser-verification" in html_text:
                    break
                cards = self._extract_actress_video_cards(html_text)
                if not cards:
                    break
                results.extend(cards)
                if len(results) >= 200:
                    break
        except Exception as e:
            logger.error(f"PornHub 演员视频列表获取失败 [{actress_url}]: {e}")
        finally:
            await client.close_session()
        return results

    def _extract_actress_video_cards(self, html_text: str) -> list[dict]:
        """从演员主页 HTML 提取视频卡片（viewkey + 标题 + 缩略图）。"""
        cards: list[dict] = []
        seen: set[str] = set()
        for m in re.finditer(
            r'viewkey=([a-f0-9]+)[^"]*".*?data-movie-title="([^"]+)"',
            html_text,
            re.DOTALL,
        ):
            vk = m.group(1)
            if vk in seen:
                continue
            seen.add(vk)
            title = m.group(2).strip()
            seg_end = html_text.find(f"viewkey={vk}") + 3000
            thumb_m = re.search(
                rf'viewkey={vk}[^"]*".*?(?:data-src|src)="([^"]*phncdn[^"]+\.jpg)"',
                html_text[:seg_end],
                re.DOTALL,
            )
            cards.append({
                "code": "ph" + vk,
                "title": title,
                "url": f"{self.base_url}/view_video.php?viewkey={vk}",
                "cover_url": thumb_m.group(1) if thumb_m else "",
                "source": "pornhub",
            })
            if len(cards) >= 60:
                break

        # 兜底：无 data-movie-title 时，从 viewkey 链接提取
        if not cards:
            for m in re.finditer(r'/view_video\.php\?viewkey=([a-f0-9]+)', html_text):
                vk = m.group(1)
                if vk in seen:
                    continue
                seen.add(vk)
                cards.append({
                    "code": "ph" + vk,
                    "title": "",
                    "url": f"{self.base_url}/view_video.php?viewkey={vk}",
                    "cover_url": "",
                    "source": "pornhub",
                })
                if len(cards) >= 60:
                    break
        return cards
