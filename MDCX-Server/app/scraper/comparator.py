"""
本地与在线对比服务

参考 .参考/javdb 的 ChineseComparator，对比本地视频（文件 + 数据库）与在线 javdb 数据：
1. 找出未更新的影片（在线有、本地无）
2. 找出中字差异（在线中字、本地非中字 / 本地英文版）

本地番号识别复用 app.scraper.number 的 extract_number + parse_suffix，
中字判定规则：文件名/番号带 -C 后缀，或数据库 is_chinese=True。
"""
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, quote_plus

from parsel import Selector
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Movie
from app.scraper.number import extract_number, parse_suffix, normalize_number, strip_episode_suffix

logger = logging.getLogger(__name__)

# 本地视频扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
    ".iso", ".webm", ".rmvb", ".mpg", ".mpeg",
}

# 在线卡片中中字标记关键词
CHINESE_SUB_KEYWORDS = ("中文字幕", "中字", "chinese subtitle", "字幕")


@dataclass
class LocalCode:
    """本地番号条目"""
    code: str                              # 标准化基础番号（已去除 -C/-U 后缀）
    is_chinese: bool = False               # 是否中字版本（-C 后缀）
    is_uncensored: bool = False            # 是否破解/无码版本（-U 后缀）
    source: str = "file"                   # file / database
    file_path: Optional[str] = None
    title: Optional[str] = None


@dataclass
class OnlineVideo:
    """在线视频条目"""
    code: str                              # 番号（原始）
    base_code: str                         # 基础番号（去除后缀）
    title: str
    url: Optional[str] = None
    cover: Optional[str] = None
    date: Optional[str] = None
    has_chinese: bool = False              # 在线标记为中字（-C 后缀 / 中字标签）
    is_uncensored: bool = False            # 在线标记为破解/无码（-U 后缀）


@dataclass
class ChineseMismatch:
    """中字差异条目（在线中字、本地非中字）"""
    code: str
    online_title: str
    online_url: Optional[str]
    online_has_chinese: bool
    local_is_chinese: bool
    local_source: str
    local_file_path: Optional[str] = None


@dataclass
class CompareResult:
    """对比结果"""
    online_count: int = 0
    local_count: int = 0
    matched_count: int = 0
    missing_videos: list[OnlineVideo] = field(default_factory=list)        # 在线有、本地无（未更新）
    chinese_mismatch: list[ChineseMismatch] = field(default_factory=list)   # 在线中字、本地非中字
    local_only: list[LocalCode] = field(default_factory=list)              # 本地有、在线无
    local_summary: dict = field(default_factory=dict)                      # 本地汇总
    online_source: str = ""                                                # online 来源描述
    actress_name: str = ""

    def to_dict(self) -> dict:
        return {
            "online_count": self.online_count,
            "local_count": self.local_count,
            "matched_count": self.matched_count,
            "missing_count": len(self.missing_videos),
            "chinese_mismatch_count": len(self.chinese_mismatch),
            "local_only_count": len(self.local_only),
            "missing_videos": [asdict(v) for v in self.missing_videos],
            "chinese_mismatch": [asdict(m) for m in self.chinese_mismatch],
            "local_only": [asdict(c) for c in self.local_only],
            "local_summary": self.local_summary,
            "online_source": self.online_source,
            "actress_name": self.actress_name,
        }


class LocalScanner:
    """本地扫描器：扫描文件目录 + 数据库"""

    def scan_directory(self, directory: str) -> list[LocalCode]:
        """递归扫描目录，从文件名提取番号并识别中字

        v3.0 增强：
        - extract_number 已支持全角归一化、CHS/CHT/CH 后缀、方括号中字标记
        - 在 normalize 后调用 strip_episode_suffix 剥离分集/版本后缀（ABC-123-A → ABC-123）
        """
        scan_dir = Path(directory)
        if not scan_dir.exists() or not scan_dir.is_dir():
            logger.warning(f"目录不存在: {directory}")
            return []

        result: dict[str, LocalCode] = {}
        for f in scan_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            number_result = extract_number(f.name)
            if not number_result.number:
                continue
            # v3.0: 先标准化，再剥离分集/版本后缀，确保与在线 base_code 对齐
            code = normalize_number(number_result.number)
            code = strip_episode_suffix(code)
            if not code:
                continue
            is_chinese = bool(number_result.is_chinese)
            is_uncensored = number_result.is_mosaic is False
            # 同一番号优先保留标记更多的记录（中字 + 破解）
            existing = result.get(code)
            if existing is None or self._is_better(existing, is_chinese, is_uncensored):
                result[code] = LocalCode(
                    code=code,
                    is_chinese=is_chinese,
                    is_uncensored=is_uncensored,
                    source="file",
                    file_path=str(f),
                )
        return list(result.values())

    @staticmethod
    def _is_better(existing: "LocalCode", new_chinese: bool, new_uncensored: bool) -> bool:
        """判断新记录是否比已有记录更优（标记更多 -> 更优）"""
        if new_chinese and not existing.is_chinese:
            return True
        if new_uncensored and not existing.is_uncensored:
            return True
        return False

    async def scan_database(self, session: AsyncSession) -> list[LocalCode]:
        """从数据库读取已有影片（含 is_chinese 标记）

        v3.0: 同步剥离分集/版本后缀
        """
        result = await session.execute(select(Movie))
        movies = result.scalars().all()

        codes: dict[str, LocalCode] = {}
        for m in movies:
            if not m.code:
                continue
            base, is_chinese, is_mosaic = parse_suffix(m.code)
            code = normalize_number(base)
            code = strip_episode_suffix(code)  # v3.0: 剥离分集后缀
            if not code:
                continue
            # 数据库 is_chinese / is_uncensored 优先，其次看番号后缀
            chinese_flag = bool(m.is_chinese) if m.is_chinese is not None else bool(is_chinese)
            uncensored_flag = bool(getattr(m, "is_uncensored", False)) or (is_mosaic is False)
            existing = codes.get(code)
            if existing is None or self._is_better(existing, chinese_flag, uncensored_flag):
                codes[code] = LocalCode(
                    code=code,
                    is_chinese=chinese_flag,
                    is_uncensored=uncensored_flag,
                    source="database",
                    file_path=m.file_path,
                    title=m.title,
                )
        return list(codes.values())

    def merge(self, file_codes: list[LocalCode], db_codes: list[LocalCode]) -> list[LocalCode]:
        """合并文件与数据库两套本地番号，同一番号标记更多优先"""
        merged: dict[str, LocalCode] = {}
        for lc in db_codes + file_codes:
            existing = merged.get(lc.code)
            if existing is None or self._is_better(existing, lc.is_chinese, lc.is_uncensored):
                merged[lc.code] = lc
        return list(merged.values())


class JavBusListCrawler:
    """javbus 列表爬虫：按演员页或关键词爬取视频列表

    javbus 演员页 URL 格式：https://www.javbus.com/star/{id}
    翻页格式：https://www.javbus.com/star/{id}/{page}
    """

    def __init__(self, max_pages: int = 10, request_delay: float = 1.0):
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.base_url = "https://www.javbus.com"

    async def _fetch(self, url: str, cookie_headers: Optional[dict] = None) -> Optional[str]:
        """使用 AsyncHttpClient 抓取 javbus 页面"""
        import asyncio
        try:
            from app.utils.http_client import AsyncHttpClient
        except ImportError:
            logger.error("AsyncHttpClient 不可用")
            return None

        if cookie_headers is None:
            from app.utils.cookie_manager import get_cookie_headers
            cookie_headers = get_cookie_headers("javbus")

        try:
            async with AsyncHttpClient() as client:
                html = await asyncio.wait_for(
                    client.get_text(url, headers=cookie_headers),
                    timeout=30,
                )
                if not html:
                    return None
                low = html.lower()
                if "just a moment" in low or "attention required" in low:
                    logger.debug(f"JavBus 列表页被 Cloudflare 拦截: {url}")
                    return None
                if "captcha-form" in low or "captcha?" in low:
                    logger.debug(f"JavBus 列表页需要验证码: {url}")
                    return None
                if "lostpasswd" in low:
                    logger.debug(f"JavBus 列表页需要密码/JavBus Cookie 无效: {url}")
                    return None
                return html
        except asyncio.TimeoutError:
            logger.warning(f"JavBus 列表页超时: {url}")
            return None
        except Exception as e:
            logger.warning(f"JavBus 列表页请求失败 {url}: {e}")
            return None

    async def crawl_actress(self, actress_url: str) -> list[OnlineVideo]:
        """爬取演员页所有视频（自动翻页）

        javbus 演员页 URL 示例：
        - https://www.javbus.com/star/abc
        - https://www.javbus.com/star/abc/2  (第2页)
        """
        import asyncio
        from lxml import etree

        actress_url = actress_url.rstrip("/")
        # 提取 star ID（去掉可能的页码）
        # 格式: https://www.javbus.com/star/xxx 或 https://www.javbus.com/star/xxx/2
        star_base = actress_url
        page_match = re.search(r"^(https?://[^/]+/star/[^/]+)", actress_url)
        if page_match:
            star_base = page_match.group(1)

        all_videos: list[OnlineVideo] = []
        page = 1

        while page <= self.max_pages:
            url = star_base if page == 1 else f"{star_base}/{page}"
            logger.info(f"javbus 爬取第 {page} 页: {url}")
            html = await self._fetch(url)
            if not html:
                break

            try:
                tree = etree.fromstring(html, etree.HTMLParser())
                videos = self._parse_star_page(tree)
                if not videos:
                    break
                all_videos.extend(videos)

                # 检查是否有下一页
                if not self._has_next_page(tree, page):
                    break
            except Exception as e:
                logger.warning(f"JavBus 解析演员页失败: {e}")
                break

            page += 1
            await asyncio.sleep(self.request_delay)

        return all_videos

    async def search_keyword(self, keyword: str) -> list[OnlineVideo]:
        """按关键词搜索 javbus"""
        import asyncio
        from urllib.parse import quote_plus
        from lxml import etree

        search_url = f"{self.base_url}/search/{quote_plus(keyword)}"
        all_videos: list[OnlineVideo] = []
        page = 1

        while page <= self.max_pages:
            url = search_url if page == 1 else f"{search_url}/{page}"
            logger.info(f"javbus 搜索第 {page} 页: {url}")
            html = await self._fetch(url)
            if not html:
                break

            try:
                tree = etree.fromstring(html, etree.HTMLParser())
                videos = self._parse_star_page(tree)
                if not videos:
                    break
                all_videos.extend(videos)

                if not self._has_next_page(tree, page):
                    break
            except Exception as e:
                logger.warning(f"JavBus 搜索解析失败: {e}")
                break

            page += 1
            await asyncio.sleep(self.request_delay)

        return all_videos

    def _parse_star_page(self, tree) -> list[OnlineVideo]:
        """解析 javbus 演员/搜索结果页，提取视频卡片

        javbus 视频卡片结构（.movie-box）：
        <a class="movie-box" href="https://www.javbus.com/VND-164">
            <div class="photo-frame">
                <img src="/pics/thumb/xxx.jpg" title="影片标题" />
            </div>
            <div class="photo-info">
                <date>VND-164</date>       第一个 date = 番号
                <date>2017-07-12</date>     第二个 date = 日期
                <span>影片标题</span>
            </div>
        </a>
        """
        videos: list[OnlineVideo] = []

        # 主选择器：a.movie-box（精确匹配 + contains 兼容多 class）
        movie_boxes = tree.xpath('//a[contains(@class,"movie-box")]')
        if not movie_boxes:
            movie_boxes = tree.xpath('//div[contains(@class,"movie-box")]/a')
        if not movie_boxes:
            movie_boxes = tree.xpath('//a[contains(@href,"/v/")][img]')

        if not movie_boxes:
            logger.warning("JavBus 列表解析：未找到任何 .movie-box 卡片")

        for box in movie_boxes:
            video = self._parse_movie_box(box)
            if video:
                videos.append(video)

        return videos

    def _parse_movie_box(self, box) -> Optional[OnlineVideo]:
        """解析单个 javbus .movie-box 卡片

        番号后缀识别：
        - -C / -CHS / -CHT  -> 中文字幕
        - -U                -> 无码破解
        - -UC / -CU         -> 中文字幕 + 无码破解
        后缀来源：<date> 番号、href、标题文本、卡片标签
        """
        # href
        href = box.xpath("@href")
        href = href[0] if href else None

        # 影片标题：img/@title 或 span 文本
        img_title = box.xpath('.//img/@title')
        title_text = img_title[0].strip() if img_title else ""
        if not title_text:
            span_texts = box.xpath('.//span/text()')
            title_text = span_texts[0].strip() if span_texts else ""

        # 卡片全部文本（用于后缀扫描）
        card_text = box.xpath('string(.)') or ""
        card_text = card_text.strip()

        # 番号提取：优先从 <date> 元素取（第一个 date 是番号，第二个是日期）
        date_texts = [t.strip() for t in box.xpath('.//date/text()') if t.strip()]
        code = None
        release_date = None
        if date_texts:
            first = date_texts[0]
            # 支持 -C/-U/-UC/-CHS 等后缀
            if self._looks_like_code(first):
                code = first.upper().replace("_", "-")
                if len(date_texts) > 1:
                    release_date = date_texts[1]
            else:
                release_date = first

        # 如果 date 里没有番号，从 href 提取
        if not code and href:
            code = self._extract_code_from_href(href)

        # 如果还没有番号，尝试从标题/卡片文本提取带后缀的番号
        if not code:
            code = self._extract_code_with_suffix(title_text) or self._extract_code_with_suffix(card_text)

        if not code:
            return None

        # 封面 URL
        img_src = box.xpath('.//img/@src') or box.xpath('.//img/@data-src')
        cover = img_src[0] if img_src else None
        if cover and cover.startswith("/"):
            cover = self.base_url.rstrip("/") + cover

        # 解析后缀
        base, is_chinese, is_mosaic = parse_suffix(code)
        base_code = normalize_number(base) if base else code
        base_code = strip_episode_suffix(base_code)

        url = None
        if href:
            url = urljoin(self.base_url, href)

        # 中字检测：1) 番号后缀 2) 标题关键词 3) 从标题/卡片文本扫描带后缀番号
        has_chinese = bool(is_chinese)
        if not has_chinese:
            has_chinese = self._detect_chinese_in_text(title_text, card_text)

        # 破解/无码检测：1) 番号后缀 2) 标题关键词 3) 从标题/卡片文本扫描带后缀番号
        is_uncensored = is_mosaic is False
        if not is_uncensored:
            is_uncensored = self._detect_uncensored_in_text(title_text, card_text)

        return OnlineVideo(
            code=code,
            base_code=base_code,
            title=title_text[:200] if title_text else code,
            url=url,
            cover=cover,
            date=release_date,
            has_chinese=has_chinese,
            is_uncensored=is_uncensored,
        )

    @staticmethod
    def _looks_like_code(text: str) -> bool:
        """判断文本是否像番号（含可能的后缀）"""
        text = text.strip()
        # 标准 ABC-123 / ABC-123C / ABC-123-UC / ABC-123-CHS
        if re.match(r'^[A-Za-z]{2,6}[-_]?\d{2,5}([-_]?[UCuc]{1,2}|[-_]?CHS|[-_]?CHT|[-_]?CH)?$', text):
            return True
        # FC2 纯数字
        if re.match(r'^\d{6,7}([UCuc]{1,2})?$', text):
            return True
        return False

    def _extract_code_with_suffix(self, text: str) -> Optional[str]:
        """从文本中提取带后缀的番号（-C/-U/-UC/-CHS/-CHT）

        示例: "ABC-123-C 中文字幕" -> "ABC-123-C"
              "ABC-123UC 高清破解版" -> "ABC-123UC"
        """
        if not text:
            return None
        # 匹配番号 + 可选后缀（-C/-U/-UC/-CU/-CHS/-CHT/-CH）
        match = re.search(r'([A-Za-z]{2,6}[-_]?\d{2,5}(?:[-_]?(?:UC|CU|CHS|CHT|CH|U|C))?)', text)
        if match:
            return match.group(1).upper().replace("_", "-")
        # FC2 纯数字 + 可选后缀
        match = re.search(r'(\d{6,7}(?:[UC]{1,2})?)', text)
        if match:
            return match.group(1).upper()
        return None

    @staticmethod
    def _detect_chinese_in_text(title: str, card_text: str) -> bool:
        """从标题和卡片文本检测中字标记"""
        keywords = ("中字", "中文字幕", "中文", "chinese subtitle", "chs", "cht")
        combined = f"{title} {card_text}".lower()
        return any(kw in combined for kw in keywords)

    @staticmethod
    def _detect_uncensored_in_text(title: str, card_text: str) -> bool:
        """从标题和卡片文本检测破解/无码标记"""
        keywords = ("破解", "无码", "uncensored", "无修正", "裏", "裏码", "uc", "-u")
        combined = f"{title} {card_text}".lower()
        # -U / -UC 后缀在番号中
        if re.search(r'[A-Za-z]{2,6}[-_]?\d{2,5}[-_]?U\b', combined, re.IGNORECASE):
            return True
        if re.search(r'[A-Za-z]{2,6}[-_]?\d{2,5}[-_]?UC\b', combined, re.IGNORECASE):
            return True
        return any(kw in combined for kw in keywords)

    def _extract_code_from_href(self, href: str) -> Optional[str]:
        """从 javbus href URL 提取番号

        JavBus URL 格式: https://www.javbus.com/ABC-123
        """
        if not href:
            return None
        path = href.split("?")[0].split("#")[0].rstrip("/")
        last_segment = path.rsplit("/", 1)[-1] if "/" in path else path
        if re.match(r'^[A-Za-z]{2,6}[-_]?\d{2,5}$', last_segment):
            return last_segment.upper().replace("_", "-")
        if re.match(r'^\d{6,7}$', last_segment):
            return last_segment
        return None

    def _extract_code_from_title(self, title: str) -> Optional[str]:
        """从 javbus img title 中提取番号

        javbus 的 title 格式通常是 "ABC-123 作品标题"
        """
        if not title:
            return None
        # 常见番号格式
        match = re.search(r"([A-Za-z]{2,6}[-_]\d{2,5})", title)
        if match:
            return match.group(1).upper().replace("_", "-")
        # FC2 等格式
        match = re.search(r"(\d{6,7})", title)
        if match:
            return match.group(1)
        return None

    def _has_next_page(self, tree, current_page: int) -> bool:
        """检测 javbus 是否有下一页

        javbus 翻页典型结构：
        <ul class="pagination">
            <li><a id="next" href="...">...</a></li>
        </ul>
        或隐藏的下一页链接
        """
        # 标准翻页
        next_links = tree.xpath('//a[@id="next"]')
        if next_links:
            return True
        # li.next
        next_links = tree.xpath('//li[contains(@class,"next")]/a')
        if next_links:
            return True
        # 检查是否有下一页码的链接
        page_links = tree.xpath(f'//ul[contains(@class,"pagination")]//a[contains(@href,"/{current_page + 1}")]')
        if page_links:
            return True
        return False


class JavDBListCrawler:
    """javdb 列表爬虫：按演员页或关键词爬取视频列表"""

    def __init__(self, max_pages: int = 10, request_delay: float = 1.5):
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.base_url = "https://javdb.com"
        self._fetcher = None

    def _get_fetcher(self):
        """复用 JavDBCrawler 的 cloudscraper/stealth 抓取能力"""
        if self._fetcher is None:
            from app.crawlers.javdb import JavDBCrawler
            self._fetcher = JavDBCrawler()
            # 已经初始化时设置了代理，不需要额外处理
        return self._fetcher

    async def _fetch(self, url: str) -> Optional[str]:
        html = await self._get_fetcher()._fetch_with_cloudscraper(url)
        if not html:
            return None
        # 检测登录页重定向（Cookie 失效）
        low = html.lower()
        if "return_to_url" in low or "<title>登入" in low or "<title>login" in low:
            logger.warning(f"JavDB Cookie 已失效，被重定向到登录页: {url}")
            logger.warning("-> 请用 Cookie 管理器重新登录获取 Cookie")
            return None
        return html

    async def crawl_actress(self, actress_url: str) -> list[OnlineVideo]:
        """爬取演员页所有视频（自动翻页）"""
        actress_url = actress_url.rstrip("/")
        # 确保 locale=zh
        if "locale=" not in actress_url:
            actress_url += ("&" if "?" in actress_url else "?") + "locale=zh"

        import asyncio
        all_videos: list[OnlineVideo] = []
        page = 1
        actress_name = self._extract_actress_name(actress_url)

        while page <= self.max_pages:
            url = actress_url if page == 1 else f"{actress_url}&page={page}"
            logger.info(f"javdb 爬取第 {page} 页: {url}")
            html = await self._fetch(url)
            if not html:
                break
            videos = self._parse_list_html(html)
            if not videos:
                break
            all_videos.extend(videos)
            if not self._has_next_page(Selector(html)):
                break
            page += 1
            await asyncio.sleep(self.request_delay)

        # 填充演员名
        for v in all_videos:
            if not v.title:
                v.title = actress_name
        return all_videos

    async def search_keyword(self, keyword: str) -> list[OnlineVideo]:
        """按关键词搜索 javdb（爬取搜索结果列表，自动翻页）"""
        import asyncio
        search_url = f"{self.base_url}/search?q={quote_plus(keyword)}&f=all&locale=zh"

        all_videos: list[OnlineVideo] = []
        page = 1
        while page <= self.max_pages:
            url = search_url if page == 1 else f"{search_url}&page={page}"
            logger.info(f"javdb 搜索第 {page} 页: {url}")
            html = await self._fetch(url)
            if not html:
                break
            videos = self._parse_list_html(html)
            if not videos:
                break
            all_videos.extend(videos)
            if not self._has_next_page(Selector(html)):
                break
            page += 1
            await asyncio.sleep(self.request_delay)
        return all_videos

    def _parse_list_html(self, html_text: str) -> list[OnlineVideo]:
        """解析列表页 HTML，提取视频卡片

        javdb 列表页可能有多套布局，使用多级选择器回退：
        1. 演员页 / 搜索结果主要卡片：<a class="box"> 或 <div class="movie-list"> 下的 <a>
        2. 备用：<div class="item"> 下的 <a>（某些 javdb 主题）
        3. 最后兜底：任意包含 href 的 <a> 中提取番号
        """
        sel = Selector(html_text)
        # 使用 contains(@class, ...) 而非 @class= 精确匹配，兼容多 class 写法
        items = (
            sel.xpath("//a[contains(@class,'box')]")
            or sel.xpath("//div[contains(@class,'movie-list')]//a")
            or sel.xpath("//div[contains(@class,'item')]//a[contains(@href,'/v/')]")
            or sel.xpath("//a[contains(@href,'/v/')]")
        )
        if not items:
            logger.warning("javdb 列表解析：未找到任何视频卡片，HTML 前 500 字符: %s", html_text[:500])
        videos: list[OnlineVideo] = []

        for item in items:
            video = self._parse_card(item)
            if video:
                videos.append(video)
        return videos

    def _parse_card(self, item) -> Optional[OnlineVideo]:
        """解析单个视频卡片（兼容 javdb 多套布局）"""
        href = item.xpath("@href").get()

        # 标题：多级回退
        title = (
            item.xpath('.//div[contains(@class,"video-title")]//strong/text()').get()
            or item.xpath('.//strong/text()').get()
            or item.xpath('.//span[contains(@class,"title")]/text()').get()
            or item.xpath("string(.)").get()  # 最后兜底：整个元素的文本
        )

        # 番号：多级回退
        code_text = (
            item.xpath('.//div[contains(@class,"video-title")]//span/text()').get()
            or item.xpath('.//span[contains(@class,"uid")]/text()').get()
            or item.xpath('.//span[contains(@class,"code")]/text()').get()
        )

        cover = item.xpath(".//img/@src").get() or item.xpath(".//img/@data-src").get()
        date = (
            item.xpath('.//div[contains(@class,"meta")]/text()').get()
            or item.xpath('.//span[contains(@class,"date")]/text()').get()
        )

        if not code_text and title:
            # 退化：从标题提取番号
            code_text = self._extract_code_from_text(title)
        if not code_text:
            return None

        code = code_text.strip().upper()
        base, is_chinese_suffix, is_mosaic = parse_suffix(code)
        # v3.0: 剥离分集/版本后缀，确保在线 base_code 与本地 code 对齐
        base_code = normalize_number(base) if base else code
        base_code = strip_episode_suffix(base_code)

        # 完整链接
        url = None
        if href:
            url = urljoin(self.base_url, href)

        # 中字 + 破解检测：卡片标签、番号后缀、卡片文本
        has_chinese, is_uncensored = self._detect_card_flags(item, code, is_chinese_suffix, is_mosaic)

        return OnlineVideo(
            code=code,
            base_code=base_code,
            title=(title or "").strip()[:200],  # 限制标题长度，避免整页文本
            url=url,
            cover=cover,
            date=date.strip() if date else None,
            has_chinese=has_chinese,
            is_uncensored=is_uncensored,
        )

    def _detect_card_flags(
        self, item, code: str, suffix_chinese: Optional[bool], suffix_mosaic: Optional[bool]
    ) -> tuple[bool, bool]:
        """检测在线卡片的中字和破解/无码标记

        Returns:
            (has_chinese, is_uncensored)
        """
        # 卡片标签文本
        tag_texts = item.xpath('.//span[contains(@class,"tag")]/text()').getall()
        tag_text = " ".join(t.strip() for t in tag_texts).lower()
        # 卡片整体文本
        full_text = (item.get() or "").lower()

        # 中字检测
        has_chinese = bool(suffix_chinese)
        if not has_chinese:
            if any(kw in tag_text for kw in CHINESE_SUB_KEYWORDS):
                has_chinese = True
            elif "中文字幕" in full_text or "中字" in full_text or "chs" in full_text or "cht" in full_text:
                has_chinese = True

        # 破解/无码检测
        is_uncensored = suffix_mosaic is False
        if not is_uncensored:
            uncensored_keywords = ("破解", "无码", "uncensored", "无修正", "裏", "裏码")
            if any(kw in tag_text for kw in uncensored_keywords):
                is_uncensored = True
            elif any(kw in full_text for kw in uncensored_keywords):
                is_uncensored = True

        return has_chinese, is_uncensored

    def _has_next_page(self, sel: Selector) -> bool:
        """是否存在下一页（兼容 javdb 多套翻页组件）"""
        next_selectors = [
            '//a[@rel="next"]',
            '//a[contains(@class,"next")]',
            '//a[contains(@class,"pagination-next")]',
            '//li[contains(@class,"next")]/a',
            '//span[contains(@class,"next")]/a',
            '//nav[contains(@class,"pagination")]//a[contains(@class,"next")]',
        ]
        for s in next_selectors:
            if sel.xpath(s):
                return True
        return False

    def _extract_actress_name(self, url: str) -> str:
        match = re.search(r"/actors?/([^/?]+)", url)
        if match:
            return match.group(1)
        return ""

    def _extract_code_from_text(self, text: str) -> str:
        match = re.search(r"([A-Za-z]{2,}-\d{2,})", text)
        if match:
            return match.group(1).upper()
        return ""


class LocalOnlineComparator:
    """本地与在线对比器"""

    def __init__(self):
        self.scanner = LocalScanner()

    def compare(
        self,
        online_videos: list[OnlineVideo],
        local_codes: list[LocalCode],
        online_source: str = "",
        actress_name: str = "",
    ) -> CompareResult:
        """对比在线视频与本地番号集合"""
        local_map: dict[str, LocalCode] = {lc.code: lc for lc in local_codes}

        matched_count = 0
        missing_videos: list[OnlineVideo] = []
        chinese_mismatch: list[ChineseMismatch] = []
        online_codes_seen: set[str] = set()

        for video in online_videos:
            key = video.base_code or video.code
            online_codes_seen.add(key)
            local = local_map.get(key)

            if local:
                matched_count += 1
                # 中字差异：在线中字、本地非中字
                if video.has_chinese and not local.is_chinese:
                    chinese_mismatch.append(ChineseMismatch(
                        code=key,
                        online_title=video.title,
                        online_url=video.url,
                        online_has_chinese=True,
                        local_is_chinese=False,
                        local_source=local.source,
                        local_file_path=local.file_path,
                    ))
            else:
                missing_videos.append(video)

        # 本地有、在线无
        local_only = [lc for code, lc in local_map.items() if code not in online_codes_seen]

        # 本地汇总
        local_chinese_count = sum(1 for lc in local_codes if lc.is_chinese)
        local_uncensored_count = sum(1 for lc in local_codes if lc.is_uncensored)
        local_summary = {
            "total": len(local_codes),
            "chinese": local_chinese_count,
            "non_chinese": len(local_codes) - local_chinese_count,
            "uncensored": local_uncensored_count,
            "from_file": sum(1 for lc in local_codes if lc.source == "file"),
            "from_database": sum(1 for lc in local_codes if lc.source == "database"),
        }

        return CompareResult(
            online_count=len(online_videos),
            local_count=len(local_codes),
            matched_count=matched_count,
            missing_videos=missing_videos,
            chinese_mismatch=chinese_mismatch,
            local_only=local_only,
            local_summary=local_summary,
            online_source=online_source,
            actress_name=actress_name,
        )
