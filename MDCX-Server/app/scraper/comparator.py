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

from app.utils.module_helper import get_module_model, get_module_session
from app.scraper.number import extract_number, parse_suffix, normalize_number, strip_episode_suffix

logger = logging.getLogger(__name__)

# 本地视频扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
    ".iso", ".webm", ".rmvb", ".mpg", ".mpeg",
}

# 在线卡片中中字标记关键词
CHINESE_SUB_KEYWORDS = ("中文字幕", "中字", "chinese subtitle", "字幕")


def _norm_name(n: str) -> str:
    """归一化姓名用于匹配：NFKC 归一 + 去空格/连字符 + 小写"""
    import unicodedata
    n = unicodedata.normalize("NFKC", n or "")
    return n.lower().replace(" ", "").replace("　", "").replace("-", "").replace("_", "")


# 女优页显示名常见后缀/修饰：有碼/無碼/中字/破解/（别名）等
_ROLE_TAG_RE = re.compile(r"[（(].*?[)）]|有碼|無碼|无码|中字|中文字幕|破解|uncensored|chinese", re.IGNORECASE)


def _strip_role_tags(n: str) -> str:
    """剥离女优显示名里的角色修饰（有碼/無碼/别名括号），仅留纯名用于匹配。"""
    return _ROLE_TAG_RE.sub("", n or "")


def _best_star_match(target: str, candidates: list[tuple[str, str]]):
    """从候选 (star_id, 显示名) 中选与 target 最匹配的女优页

    匹配优先级（基于对「纯名」的判定，已剥离 有碼/無碼/别名括号）：
      1. 精确相等（纯名 == target 纯名）
      2. 互相包含
      3. difflib 相似度 >= 0.6
    在同档（精确/包含）内，优先选「纯名最短」的候选 —— 避免选中
    「森沢かな（飯岡かなこ）有碼」而漏掉更干净的「森沢かな有碼」主名页。
    """
    import difflib
    t = _norm_name(_strip_role_tags(target))
    if not t:
        return None
    exact: list[tuple[str, str]] = []
    contains: list[tuple[str, str]] = []
    best_score = 0.0
    best = None
    for sid, name in candidates:
        clean = _norm_name(_strip_role_tags(name))
        if not clean:
            continue
        if clean == t:
            exact.append((sid, name))
        elif t in clean or clean in t:
            contains.append((sid, name))
        score = difflib.SequenceMatcher(None, t, clean).ratio()
        if score > best_score:
            best_score = score
            best = (sid, name)
    # 同档内选「原始显示名最短」的候选 —— 主名页（森沢かな有碼）会比
    # 别名页（森沢かな（飯岡かなこ）有碼）更短，优先选主名页。
    if exact:
        return min(exact, key=lambda x: len(x[1]))
    if contains:
        return min(contains, key=lambda x: len(x[1]))
    if best and best_score >= 0.6:
        return best
    return None


# ===== 磁力链接中文判定 =====

# JavDB 匿名 App API 演员目录缓存（detect_actress 反查用，避免每次全量抓目录）
_JAVDB_ACTOR_INDEX_CACHE: dict[str, tuple[float, dict[str, list[str]]]] = {}
_JAVDB_ACTOR_INDEX_TTL = 24 * 3600

def _magnet_is_chinese(link: str, name: str) -> bool:
    """判定磁力链接是否中文字幕版

    规则（用户约定）：
    1. 名称/链接含 中文/中文字幕/chinese/chs/cht → 中文
    2. 番号带后缀 -C / -UC / -CU / -CHS / -CHT（如 ABC-123-C、ABC-123-UC）→ 中文
    """
    text = f"{link} {name}".lower()
    if re.search(r"中文字幕|中文|chinese|chs|cht", text):
        return True
    # 番号后缀：ABC-123-C / ABC-123-UC / ABC-123CHS 等（-CH 单独匹配太宽泛，要求 -CH 后跟边界）
    if re.search(r"[a-z]{2,6}[-_]?\d{2,5}[-_]?(?:uc|cu|chs|cht|ch)\b", text):
        return True
    return False


def pick_best_magnet(magnets: list[dict]) -> Optional[dict]:
    """从磁力列表挑最佳：优先中文版，其次第一个"""
    if not magnets:
        return None
    for m in magnets:
        if m.get("chinese"):
            return m
    return magnets[0]


async def attach_magnets(crawler, items, concurrency: int = 4, limit: int = 30) -> None:
    """并发抓取影片详情页磁力链接，写入 item.magnets（带中文标记）

    - items 可以是 OnlineVideo（字段 .url）或 ChineseMismatch（字段 .online_url）
    - 只处理前 limit 个（前端/路由已按优先级排序）
    - 单部失败不影响整体
    """
    import asyncio
    target = [
        it for it in items
        if (getattr(it, "url", None) or getattr(it, "online_url", None))
    ][:limit]
    if not target:
        return
    sem = asyncio.Semaphore(concurrency)

    async def one(it):
        async with sem:
            url = getattr(it, "url", None) or getattr(it, "online_url", None)
            try:
                it.magnets = await crawler._fetch_magnets(url)
            except Exception as e:
                logger.warning(f"抓取磁力失败 {url}: {e}")

    await asyncio.gather(*(one(it) for it in target))


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
    magnets: list[dict] = field(default_factory=list)  # [{"link","name","size","chinese"}] 详情页磁力


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
    magnets: list[dict] = field(default_factory=list)  # 中字版磁力（供下载替换本地非中字）


@dataclass
class CompareResult:
    """对比结果"""
    online_count: int = 0
    local_count: int = 0
    matched_count: int = 0
    missing_videos: list[OnlineVideo] = field(default_factory=list)
    local_only: list[LocalCode] = field(default_factory=list)
    local_summary: dict = field(default_factory=dict)
    online_source: str = ""
    actress_name: str = ""

    def to_dict(self) -> dict:
        return {
            "online_count": self.online_count,
            "local_count": self.local_count,
            "matched_count": self.matched_count,
            "missing_count": len(self.missing_videos),
            "local_only_count": len(self.local_only),
            "missing_videos": [asdict(v) for v in self.missing_videos],
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

    async def scan_database(self, session: AsyncSession, module: str = "jav") -> list[LocalCode]:
        """从数据库读取已有影片（含 is_chinese 标记）

        v3.0: 同步剥离分集/版本后缀
        """
        Movie = get_module_model(module, "movie")
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
    无码分区（uncensored=True）：https://www.javbus.com/uncensored/star/{id}
    """

    def __init__(self, max_pages: int = 10, request_delay: float = 1.0, uncensored: bool = False):
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.uncensored = uncensored
        self.base_url = "https://www.javbus.com/uncensored" if uncensored else "https://www.javbus.com"

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

        # 空 cookie 头反而可能触发 javbus 反爬（带 cookie: "" 的请求会被拒）→ 空则不带 cookie
        headers = {}
        if cookie_headers and cookie_headers.get("cookie"):
            headers["cookie"] = cookie_headers["cookie"]
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
        headers["Accept-Language"] = "zh-CN,zh;q=0.9"

        try:
            async with AsyncHttpClient() as client:
                html = await asyncio.wait_for(
                    client.get_text(url, headers=headers),
                    timeout=15,
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

    async def crawl_actress(self, actress_url: str, actor_name: str = "") -> list[OnlineVideo]:
        """爬取演员页所有视频（自动翻页）

        javbus 演员页 URL 示例：
        - https://www.javbus.com/star/abc
        - https://www.javbus.com/star/abc/2  (第2页)
        """
        import asyncio
        from lxml import etree

        actress_url = actress_url.rstrip("/")
        # 提取 star ID（去掉可能的页码）
        # 格式: https://www.javbus.com/star/xxx 或 https://www.javbus.com/uncensored/star/xxx 或 .../xxx/2
        star_base = actress_url
        page_match = re.search(r"^(https?://[^/]+/(?:uncensored/)?star/[^/]+)", actress_url)
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

    async def _fetch_magnets(self, video_url: str) -> list[dict]:
        """抓取 javbus 影片详情页的磁力链接

        详情页磁力表结构（<table> 行）：
        <tr>
          <td class="magnet-name"><a href="magnet:?xt=urn:btih:...">中文字幕 1080P</a></td>
          <td class="magnet-size">2.5GB</td>
          ...
        </tr>
        """
        if not video_url:
            return []
        html = await self._fetch(video_url)
        if not html:
            return []
        from lxml import etree
        try:
            tree = etree.fromstring(html, etree.HTMLParser())
        except Exception:
            return []

        magnets: list[dict] = []
        seen: set[str] = set()
        for a in tree.xpath('//a[contains(@href,"magnet:")]'):
            link = (a.get("href") or "").strip()
            if not link.startswith("magnet:") or link in seen:
                continue
            seen.add(link)
            name = (a.xpath("string(.)") or "").strip()
            size = ""
            # 向上找所在 <tr>，取 magnet-size 单元格
            tr = a.getparent()
            while tr is not None and tr.tag != "tr":
                tr = tr.getparent()
            if tr is not None:
                size_tds = tr.xpath('.//td[contains(@class,"size")]/text()')
                if size_tds:
                    size = size_tds[0].strip()
            magnets.append({
                "link": link,
                "name": name[:120],
                "size": size,
                "chinese": _magnet_is_chinese(link, name),
            })
        return magnets

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

    @staticmethod
    def _parse_star_links(html: str) -> list[tuple[str, str]]:
        """从页面 HTML 提取所有 /star/{id} 锚点及其显示文本（女优名）

        兼容：搜索结果页的女优专区、影片卡片上的女优名链接、女优索引页等
        """
        from lxml import etree
        try:
            tree = etree.fromstring(html, etree.HTMLParser())
        except Exception:
            return []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for a in tree.xpath('//a[contains(@href,"/star/")]'):
            href = a.get("href") or ""
            m = re.search(r"/star/([^/?#]+)", href)
            if not m:
                continue
            sid = m.group(1)
            if sid in seen:
                continue
            text = (a.xpath("string(.)") or "").strip()
            seen.add(sid)
            out.append((sid, text))
        return out

    @staticmethod
    def _parse_movie_links(html: str) -> list[str]:
        """从页面 HTML 提取影片详情链接（形如 /ABC-123 或 /uncensored/ABC-123），用于回退探测女优页

        保留路径前缀（/uncensored/...），无码分区详情页才能正确拼接。
        """
        from lxml import etree
        try:
            tree = etree.fromstring(html, etree.HTMLParser())
        except Exception:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for a in tree.xpath("//a"):
            href = a.get("href") or ""
            path = href.split("?")[0].split("#")[0].rstrip("/")
            seg = path.rsplit("/", 1)[-1]
            if re.match(r"^[A-Za-z]{2,6}[-_]?\d{2,5}$", seg):
                if path not in seen:
                    seen.add(path)
                    out.append(path or "/" + seg)
        return out

    async def detect_actress_star(self, actor_name: str) -> Optional[tuple[str, str]]:
        """在 javbus 定位该演员的 /star/{id} 女优页

        两级策略（基于实测 javbus 页面结构）：
        1) 主路径：javbus 专门的女优搜索端点 /searchstar/{name}
           该页直接列出匹配女优的 /star/{id} 链接与显示名，最干净。
        2) 回退：普通 /search/{name}（返回影片卡，无 /star/ 链接）→
           取首个影片详情页，从其女优链接中匹配。

        Returns:
            (star_url, star_id) 或 None（未探测到/被拦截）
        """
        import asyncio
        from urllib.parse import quote_plus, urljoin

        # 1) 主路径：女优搜索端点
        star_search_url = f"{self.base_url}/searchstar/{quote_plus(actor_name)}"
        logger.info(f"javbus 探测女优页(searchstar): {star_search_url}")
        html = await self._fetch(star_search_url)
        if html:
            candidates = self._parse_star_links(html)
            if candidates:
                match = _best_star_match(actor_name, candidates)
                if match:
                    sid, _ = match
                    return (f"{self.base_url}/star/{sid}", sid)

        # 2) 回退：普通影片搜索 -> 首个影片详情页 -> 女优链接
        search_url = f"{self.base_url}/search/{quote_plus(actor_name)}"
        logger.info(f"javbus 探测女优页(回退 search): {search_url}")
        html = await self._fetch(search_url)
        if not html:
            logger.warning(f"javbus 探测失败/被拦截: {actor_name}")
            return None
        for ml in self._parse_movie_links(html)[:3]:
            mhtml = await self._fetch(urljoin(self.base_url, ml))
            if not mhtml:
                continue
            mcands = self._parse_star_links(mhtml)
            match = _best_star_match(actor_name, mcands)
            if match:
                sid, _ = match
                return (f"{self.base_url}/star/{sid}", sid)
            await asyncio.sleep(self.request_delay)

        logger.info(f"javbus 未找到匹配女优页: {actor_name}")
        return None


class JavDBListCrawler:
    """javdb 列表爬虫：按演员页或关键词爬取视频列表

    有码：https://javdb.com/actors/{id}
    无码分区（uncensored=True）：https://javdb.com/uncensored/actors/{id}

    默认走**匿名 App API**（api.javdb.com 签名方案，免登录、绕 Cloudflare、不封 IP，
    与刮削模块同一通道）；API 失败时自动降级 HTML 爬虫。
    """

    def __init__(self, max_pages: int = 10, request_delay: float = 1.5,
                 uncensored: bool = False, api_mode: bool = True, solo_only: bool = False):
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.uncensored = uncensored
        self.api_mode = api_mode
        self.solo_only = solo_only
        self.base_url = "https://javdb.com/uncensored" if uncensored else "https://javdb.com"
        self._fetcher = None
        self._app_client = None

    def _zone(self) -> str:
        """App API 分区名：censored / uncensored"""
        return "uncensored" if self.uncensored else "censored"

    @staticmethod
    def _is_compilation(title: str) -> bool:
        """判断影片是否为合集/精选/总集编/BEST（按标题关键词粗筛）"""
        if not title:
            return False
        t = title.lower()
        COMPILE_KEYWORDS = [
            "best", "総集編", "总集编", "まとめ", "总合", "精选", "best", "best ", " BEST ",
            "complete", "完全版", "comprehensive", "selection", "アンソロジー", "anthology",
            "anthology", "anthology ", "コンプ", "complete edition", "best of", "bestver",
            "bestver", "bestver", "special", "deluxe", "mega", "super", "ultra", "grand",
        ]
        return any(k in t for k in COMPILE_KEYWORDS)

    def _filter_solo(self, videos: list[OnlineVideo]) -> list[OnlineVideo]:
        """solo_only=True 时排除合集/BEST/总集编"""
        if not self.solo_only:
            return videos
        return [v for v in videos if not self._is_compilation(v.title)]

    async def _get_app_client(self):
        """懒加载匿名 App API 客户端（与刮削同通道，免登录不封 IP）"""
        if self._app_client is None:
            from app.services.javdb_app_client import create_app_client_from_config
            self._app_client = await create_app_client_from_config()
        return self._app_client

    async def _actor_index(self) -> dict[str, list[str]]:
        """获取演员目录 {actor_id: [全部名字]}（App API，24h 缓存）

        用于 detect_actress 按名反查，避免每次探测都全量翻页抓目录。
        """
        import time
        key = self._zone()
        now = time.time()
        cached = _JAVDB_ACTOR_INDEX_CACHE.get(key)
        if cached and now - cached[0] < _JAVDB_ACTOR_INDEX_TTL:
            return cached[1]
        client = await self._get_app_client()
        try:
            index = await client.fetch_actor_index(zone=key, max_pages=100)
        except Exception:
            index = {}
        if index:
            _JAVDB_ACTOR_INDEX_CACHE[key] = (now, index)
        return index

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

    async def crawl_actress(self, actress_url: str, actor_name: str = "") -> list[OnlineVideo]:
        """爬取演员页所有视频（自动翻页）

        API 模式：优先按 actor_id 全量抓取（filter_by，标题不含演员名的合集/精选也收录）；
        失败时降级按演员名搜索（q=演员名），再失败降级 HTML 演员页。
        """
        actress_url = actress_url.rstrip("/")
        if self.api_mode:
            videos = await self.scrape_actor_movies(actress_url, max_pages=self.max_pages)
            if videos:
                return self._filter_solo(videos)
            logger.warning("javdb App API 按演员ID抓取失败/为空，降级按演员名搜索: %s", actress_url)
            videos = await self._api_crawl_actress(actress_url)
            if videos:
                return self._filter_solo(videos)
            logger.warning("javdb App API 按演员抓取失败/为空，降级 HTML: %s", actress_url)

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

        for v in all_videos:
            if not v.title:
                v.title = actress_name
        return self._filter_solo(all_videos)

    async def _api_crawl_actress(self, actress_url: str) -> list[OnlineVideo]:
        """App API 按演员抓取：actor_id -> 演员名 -> 按名搜索翻页取全部作品"""
        # 兼容新版 /actors/{id} 与旧版 /actresses/{id}
        m = re.search(r"/(?:actresses|actors)/([A-Za-z0-9]+)", actress_url)
        if not m:
            return []
        actor_id = m.group(1)
        client = await self._get_app_client()
        from app.services.javdb_app_client import ZONES
        zone_num = ZONES.get(self._zone(), 0)

        # 1. 取演员主名（优先 actor 详情，回退目录索引）
        name = ""
        try:
            detail = await client._request("GET", f"/api/v1/actors/{actor_id}")
            if detail and isinstance(detail, dict):
                actor = detail.get("actor") or {}
                name = str(actor.get("name") or "")
        except Exception:
            pass
        if not name:
            index = await self._actor_index()
            names = index.get(actor_id) or []
            name = names[0] if names else ""
        if not name:
            logger.warning("javdb API 未取到演员名: %s", actor_id)
            return []

        # 2. 按演员名搜索（q 匹配标题含演员名的影片），翻页收集
        all_videos: list[OnlineVideo] = []
        seen_codes: set[str] = set()
        for page in range(1, self.max_pages + 1):
            data = await client._request("GET", "/api/v2/search", {
                "q": name, "page": page, "movie_type": zone_num,
            })
            movies = []
            if isinstance(data, dict):
                movies = data.get("movies") or []
            if not movies:
                break
            for mv in movies:
                if not isinstance(mv, dict):
                    continue
                code = (mv.get("number") or "").strip().upper()
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                base, is_chinese_suffix, is_mosaic = parse_suffix(code)
                base_code = normalize_number(base) if base else code
                base_code = strip_episode_suffix(base_code)
                all_videos.append(OnlineVideo(
                    code=code,
                    base_code=base_code,
                    title=(mv.get("title") or mv.get("origin_title") or "").strip()[:200],
                    url=f"https://javdb.com/v/{mv.get('id') or ''}",
                    cover=mv.get("cover_url") or mv.get("thumb_url") or "",
                    date=mv.get("release_date") or "",
                    has_chinese=bool(mv.get("has_cnsub")),
                    is_uncensored=self.uncensored,
                ))
        return all_videos

    async def scrape_actor_movies(self, actress_url: str, max_pages: int = 10) -> list[OnlineVideo]:
        """按演员页精确抓取影片列表（基于 actor_id 的完整片单）。

        与 _api_crawl_actress 的区别：
        - _api_crawl_actress 按「演员名搜索」，标题不含演员名的合集/精选片会被漏掉；
        - 本方法用 /api/v1/movies/tags + filter_by={zone}:a:{actor_id} 直接按演员 ID
          抓完整片单（移植自 ref15-javdb-cli EntityMovies），不依赖标题命中。

        支持翻页（每页 limit=50），按上映时间倒序。
        """
        m = re.search(r"/(?:actresses|actors)/([A-Za-z0-9]+)", actress_url)
        if not m:
            return []
        actor_id = m.group(1)
        if not self.api_mode:
            return []
        import asyncio
        client = await self._get_app_client()
        all_videos: list[OnlineVideo] = []
        seen_codes: set[str] = set()
        page = 1
        while page <= max_pages:
            data = await client.fetch_actor_movies(actor_id, zone=self._zone(), page=page, limit=50)
            movies = data.get("movies") or []
            if not movies:
                break
            for mv in movies:
                if not isinstance(mv, dict):
                    continue
                code = (mv.get("number") or "").strip().upper()
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                base, is_chinese_suffix, is_mosaic = parse_suffix(code)
                base_code = normalize_number(base) if base else code
                base_code = strip_episode_suffix(base_code)
                all_videos.append(OnlineVideo(
                    code=code,
                    base_code=base_code,
                    title=(mv.get("title") or mv.get("origin_title") or "").strip()[:200],
                    url=f"https://javdb.com/v/{mv.get('id') or ''}",
                    cover=mv.get("cover_url") or mv.get("thumb_url") or "",
                    date=mv.get("release_date") or "",
                    has_chinese=bool(mv.get("has_cnsub")),
                    is_uncensored=self.uncensored,
                ))
            # current_page 为空表示无翻页信息，保守多抓一页后结束
            if data.get("current_page") is None:
                break
            page += 1
            await asyncio.sleep(self.request_delay)
        return all_videos

    async def search_keyword(self, keyword: str) -> list[OnlineVideo]:
        """按关键词搜索 javdb（API 模式优先，降级 HTML 搜索结果页）"""
        import asyncio
        if self.api_mode:
            videos = await self._api_search_keyword(keyword)
            if videos:
                return videos
            logger.warning("javdb App API 关键词搜索失败/为空，降级 HTML: %s", keyword)

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

    async def _api_search_keyword(self, keyword: str) -> list[OnlineVideo]:
        """App API 按关键词搜索影片（q + movie_type 分区），翻页收集"""
        client = await self._get_app_client()
        from app.services.javdb_app_client import ZONES
        zone_num = ZONES.get(self._zone(), 0)
        all_videos: list[OnlineVideo] = []
        seen_codes: set[str] = set()
        for page in range(1, self.max_pages + 1):
            data = await client._request("GET", "/api/v2/search", {
                "q": keyword, "page": page, "movie_type": zone_num,
            })
            movies = []
            if isinstance(data, dict):
                movies = data.get("movies") or []
            if not movies:
                break
            for mv in movies:
                if not isinstance(mv, dict):
                    continue
                code = (mv.get("number") or "").strip().upper()
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                base, is_chinese_suffix, is_mosaic = parse_suffix(code)
                base_code = normalize_number(base) if base else code
                base_code = strip_episode_suffix(base_code)
                all_videos.append(OnlineVideo(
                    code=code,
                    base_code=base_code,
                    title=(mv.get("title") or mv.get("origin_title") or "").strip()[:200],
                    url=f"https://javdb.com/v/{mv.get('id') or ''}",
                    cover=mv.get("cover_url") or mv.get("thumb_url") or "",
                    date=mv.get("release_date") or "",
                    has_chinese=bool(mv.get("has_cnsub")),
                    is_uncensored=self.uncensored,
                ))
        return all_videos

    async def _fetch_magnets(self, video_url: str) -> list[dict]:
        """抓取 javdb 影片磁力链接

        API 模式：App API /api/v1/movies/{id}/magnets（cnsub 字段直接判定中字）。
        - App API 成功返回 0 条（magnets_count=0）＝javdb 上确实无磁力，跳过 HTML 降级
          （HTML 被 Cloudflare 403 拦截，降级只会空转产生噪音日志）；
        - App API 请求异常（返回 None）才降级 HTML 解析。
        """
        if not video_url:
            return []
        if self.api_mode:
            magnets = await self._api_fetch_magnets(video_url)
            if magnets:
                return magnets
            # 区分"无磁力"（API 正常返回空）与"抓取失败"（API 异常）
            api_failed = await self._api_magnets_failed(video_url)
            if not api_failed:
                return []
            logger.warning("javdb App API 磁力抓取失败，降级 HTML: %s", video_url)

        html = await self._fetch(video_url)
        if not html:
            return []
        sel = Selector(html)
        magnets: list[dict] = []
        seen: set[str] = set()

        blocks = (
            sel.xpath('//div[contains(@class,"magnet-item")]')
            or sel.xpath('//div[contains(@class,"magnet")]')
        )
        for b in blocks:
            link = (b.xpath('.//a[contains(@href,"magnet:")]/@href').get() or "").strip()
            if not link.startswith("magnet:") or link in seen:
                continue
            seen.add(link)
            name = (
                b.xpath('.//span[contains(@class,"name")]/text()').get()
                or b.xpath('.//a[contains(@href,"magnet:")]/text()').get()
                or ""
            ).strip()
            size = (b.xpath('.//span[contains(@class,"meta")]/text()').get() or "").strip()
            magnets.append({
                "link": link,
                "name": name[:120],
                "size": size,
                "chinese": _magnet_is_chinese(link, name),
            })

        # 兜底：页面任意 magnet 链接（结构变化时仍可用）
        if not magnets:
            for a in sel.xpath('//a[contains(@href,"magnet:")]'):
                link = (a.xpath('@href').get() or "").strip()
                if not link.startswith("magnet:") or link in seen:
                    continue
                seen.add(link)
                name = (a.xpath("string(.)").get() or "").strip()
                magnets.append({
                    "link": link,
                    "name": name[:120],
                    "size": "",
                    "chinese": _magnet_is_chinese(link, name),
                })
        return magnets

    async def _api_fetch_magnets(self, video_url: str) -> Optional[list[dict]]:
        """App API 取磁力：/api/v1/movies/{id}/magnets

        cnsub 字段为 JavDB 官方中字标记，比名称/后缀正则更可靠。
        返回三态：
        - 非空列表：磁力抓取成功；
        - []：App API 正常响应但该影片无磁力（magnets_count=0，属正常）；
        - None：App API 请求异常/失败（调用方应降级 HTML）。
        """
        m = re.search(r"/v/([A-Za-z0-9]+)", video_url)
        if not m:
            return []
        client = await self._get_app_client()
        try:
            magnets = await client.get_magnets(m.group(1))
        except Exception:
            return None
        out: list[dict] = []
        seen: set[str] = set()
        for mg in magnets:
            link = (mg.magnet_uri or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            out.append({
                "link": link,
                "name": (mg.name or "")[:120],
                "size": f"{mg.size} MB" if mg.size else "",
                "chinese": bool(mg.cnsub),
            })
        return out

    async def _api_magnets_failed(self, video_url: str) -> bool:
        """判断 javdb App API 磁力抓取是否属于"请求失败"（而非"无磁力"）。

        通过电影详情 /api/v4/movies/{id} 的 magnets_count 字段判定：
        - magnets_count>0 但 get_magnets 返回空 → 请求失败（应降级 HTML 兜底）；
        - magnets_count=0 → javdb 上确实无磁力（跳过 HTML 降级，避免 403 空转）。
        """
        m = re.search(r"/v/([A-Za-z0-9]+)", video_url)
        if not m:
            return False
        try:
            client = await self._get_app_client()
            detail = await client.get_movie_detail(m.group(1))
        except Exception:
            return True
        if not detail:
            return True
        movie = detail.get("movie") or {}
        count = int(movie.get("magnets_count") or 0)
        return count > 0

    async def detect_actress(self, actor_name: str) -> Optional[tuple[str, str]]:
        """在 javdb 定位该演员的 /actors/{id} 页 URL

        API 模式（默认）：
        1. 先按 App API 演员目录索引（前 100 页约 5000 人）按名反查；
        2. 索引未命中时降级「电影搜索反查」：/api/v2/search?q=演员名 → 前几部电影
           详情（/api/v4/movies/{id}）的 actors 列表匹配演员名 —— 可覆盖索引之外的演员；
        3. 以上都失败再降级 HTML 搜索页 → 电影详情页反查。

        Returns:
            (actress_url, actress_id) 或 None
        """
        from urllib.parse import quote_plus
        if not actor_name:
            return None
        if self.api_mode:
            result = await self._api_detect_actress(actor_name)
            if result:
                return result
            result = await self._api_detect_actress_via_movies(actor_name)
            if result:
                return result
            logger.warning("javdb App API 演员探测失败，降级 HTML 搜索: %s", actor_name)

        # HTML 兜底：电影搜索页 → 电影详情页 → 演员链接
        search_url = f"{self.base_url}/search?q={quote_plus(actor_name)}&locale=zh"
        logger.info(f"javdb 探测女优页: {search_url}")
        html = await self._fetch(search_url)
        if not html:
            logger.warning(f"javdb 探测失败/被拦截/Cookie 失效: {actor_name}")
            return None
        sel = Selector(html)
        movie_links = list(dict.fromkeys(
            a for a in sel.xpath('//a[contains(@href, "/v/")]/@href').getall() if a.strip()
        ))
        import asyncio
        for link in movie_links[:5]:
            if not link.startswith("http"):
                link = self.base_url + link
            detail_html = await self._fetch(link)
            await asyncio.sleep(self.request_delay)
            if not detail_html:
                continue
            dsel = Selector(detail_html)
            candidates: list[tuple[str, str]] = []
            # 兼容新版 /actors/ 与旧版 /actresses/ 链接，统一存 /actors/{id}
            for a in dsel.xpath('//a[contains(@href, "/actresses/") or contains(@href, "/actors/")]'):
                href = a.xpath("@href").get() or ""
                m = re.search(r"/(?:actresses|actors)/([^/?]+)", href)
                if not m:
                    continue
                text = (a.xpath("string(.)").get() or "").strip()
                candidates.append((f"{self.base_url}/actors/{m.group(1)}", text or m.group(1)))
            if not candidates:
                continue
            match = _best_star_match(actor_name, candidates)
            if match:
                url, _ = match
                return url, url.rsplit("/", 1)[-1]
        logger.info(f"javdb 未找到匹配女优页: {actor_name}")
        return None

    async def _api_detect_actress_via_movies(self, actor_name: str) -> Optional[tuple[str, str]]:
        """电影搜索反查演员：/api/v2/search?q={演员名} → 前几部电影详情 → actors 列表匹配

        App API 演员目录索引只翻前 100 页（约 5000 人），索引外的演员用本方法兜底：
        标题含演员名的影片详情必带该演员，能拿到准确 /actors/{id} URL。
        """
        if not actor_name:
            return None
        client = await self._get_app_client()
        data = await client._request("GET", "/api/v2/search", {"q": actor_name, "page": 1})
        if not data:
            return None
        movies = data.get("movies") or []
        import asyncio
        seen: set[str] = set()
        for movie in movies[:5]:
            mid = (movie.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            detail = await client.get_movie_detail(mid)
            if not detail:
                continue
            actors = (detail.get("movie") or {}).get("actors") or []
            candidates: list[tuple[str, str]] = []
            for actor in actors:
                if not isinstance(actor, dict):
                    continue
                aid = (actor.get("id") or "").strip()
                nm = (actor.get("name") or "").strip()
                if aid and nm:
                    candidates.append((f"{self.base_url}/actors/{aid}", nm))
            match = _best_star_match(actor_name, candidates)
            if match:
                url, _ = match
                return url, url.rsplit("/", 1)[-1]
            await asyncio.sleep(self.request_delay)
        return None

    async def _api_detect_actress(self, actor_name: str) -> Optional[tuple[str, str]]:
        """App API 按名反查演员：从演员目录索引（主名/繁体名/曾用名）匹配 actor_id"""
        index = await self._actor_index()
        if not index:
            return None
        # 名 -> actor_id 反查索引（精确优先）
        name_to_ids: dict[str, list[str]] = {}
        for aid, names in index.items():
            for n in names:
                k = _norm_name(n)
                if k:
                    name_to_ids.setdefault(k, []).append(aid)
        target = _norm_name(actor_name)
        if not target:
            return None

        aid = None
        hits = name_to_ids.get(target)
        if hits:
            aid = hits[0]
        if not aid:
            # 模糊：双向包含匹配（取名字最短的候选，优先主名页）
            best = None
            best_len = 10 ** 9
            for k, ids in name_to_ids.items():
                if target in k or k in target:
                    cand = ids[0]
                    if len(k) < best_len:
                        best_len = len(k)
                        best = cand
            aid = best
        if not aid:
            return None
        url = f"{self.base_url}/actors/{aid}"
        return url, aid

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
        """对比在线视频与本地番号集合（纯番号对比，不看标题）"""
        local_map: dict[str, LocalCode] = {lc.code: lc for lc in local_codes}

        matched_count = 0
        missing_videos: list[OnlineVideo] = []
        online_codes_seen: set[str] = set()

        for video in online_videos:
            key = video.base_code or video.code
            online_codes_seen.add(key)
            local = local_map.get(key)

            if local:
                matched_count += 1
            else:
                missing_videos.append(video)

        local_only = [lc for code, lc in local_map.items() if code not in online_codes_seen]

        local_summary = {
            "total": len(local_codes),
            "from_file": sum(1 for lc in local_codes if lc.source == "file"),
            "from_database": sum(1 for lc in local_codes if lc.source == "database"),
        }

        return CompareResult(
            online_count=len(online_videos),
            local_count=len(local_codes),
            matched_count=matched_count,
            missing_videos=missing_videos,
            local_only=local_only,
            local_summary=local_summary,
            online_source=online_source,
            actress_name=actress_name,
        )


# ===== JavBooks 列表爬虫（对比源 3） =====
# 女优页 URL: https://javbooks.com/serchinfo_censored/{performer_id}/performerbt_{page}.htm
# 大陆直连超时，需走代理（AsyncHttpClient 默认取有效代理）。


class JavBooksListCrawler:
    """javbooks 列表爬虫：按演员页(performerbt)或关键词爬取视频列表

    基于 JavBooksCrawler（刮削模块）复用其搜索/解析能力。
    """

    def __init__(self, max_pages: int = 10, request_delay: float = 1.0, uncensored: bool = False):
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.uncensored = uncensored
        self.base_url = "https://javbooks.com"
        self._crawler = None

    def _get_crawler(self):
        """懒加载刮削模块的 JavBooksCrawler（含代理配置）"""
        if self._crawler is None:
            from app.crawlers.javbooks import JavBooksCrawler
            self._crawler = JavBooksCrawler()
        return self._crawler

    async def _fetch(self, url: str) -> Optional[str]:
        """抓取 javbooks 页面"""
        crawler = self._get_crawler()
        try:
            from app.utils.http_client import AsyncHttpClient
            async with AsyncHttpClient(timeout=30, proxy=crawler._proxy) as client:
                return await client.get_text(url, headers=crawler._headers())
        except Exception as e:
            logger.warning(f"JavBooks 抓取失败 {url}: {e}")
            return None

    # javbooks 无独立女优页入口（performer 链接藏在作品详情页里），
    # 探测时统一返回搜索页 URL：POST serch_censored.htm + skey={演员名} 即可列出该演员作品。
    _SEARCH_PAGE_URL = "https://javbooks.com/serch_censored.htm"

    def _performer_id(self, actress_url: str) -> Optional[str]:
        """从女优页 URL 提取 performer_id（数字）"""
        m = re.search(r"/serchinfo_censored/(\d+)", actress_url)
        return m.group(1) if m else None

    def _is_search_page(self, actress_url: str) -> bool:
        """是否搜索页 URL（探测保存的通用搜索页）"""
        return "serch_censored" in (actress_url or "")

    async def crawl_actress(self, actress_url: str, actor_name: str = "") -> list[OnlineVideo]:
        """爬取该演员的作品列表

        支持两种 URL：
        1. 女优页 /serchinfo_censored/{performer_id}/performerbt_*.htm —— 按 performer_id 抓全量作品
        2. 搜索页 /serch_censored.htm —— 探测保存的通用搜索页，需 actor_name 配合 POST skey 搜索
        """
        if self._is_search_page(actress_url):
            if not actor_name:
                logger.warning(f"JavBooks 搜索页需要 actor_name: {actress_url}")
                return []
            movies = await self._search_actor_movies(actor_name, max_pages=self.max_pages)
        else:
            performer_id = self._performer_id(actress_url)
            if not performer_id:
                logger.warning(f"JavBooks 无法从 URL 提取 performer_id: {actress_url}")
                return []
            crawler = self._get_crawler()
            movies = await crawler.fetch_actress_movies(performer_id, max_pages=self.max_pages)
        videos: list[OnlineVideo] = []
        seen: set[str] = set()
        for m in movies:
            code = (m.get("code") or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            base, is_chinese_suffix, is_mosaic = parse_suffix(code)
            base_code = normalize_number(base) if base else code
            base_code = strip_episode_suffix(base_code)
            url = m.get("url") or ""
            if url and not url.startswith("http"):
                url = self.base_url + url
            videos.append(OnlineVideo(
                code=code,
                base_code=base_code,
                title=(m.get("title") or "").strip()[:200],
                url=url,
                date=m.get("date") or "",
                has_chinese=bool(is_chinese_suffix),
            ))
        return videos

    async def _search_actor_movies(self, actor_name: str, max_pages: int = 1) -> list[dict]:
        """POST javbooks 搜索页 skey={演员名}，解析作品卡片列表

        javbooks 搜索为表单提交（GET 查询参数均无效），响应页含 div.Po_topic 卡片，
        每张卡片可提取 番号/标题/日期/详情页链接。

        Returns:
            [{"title": str, "code": str, "date": str, "url": str}, ...]
        """
        movies: list[dict] = []
        crawler = self._get_crawler()
        import asyncio
        from app.utils.http_client import AsyncHttpClient
        for page in range(1, max_pages + 1):
            url = f"{self.base_url}/serch_censored_{page}.htm" if page > 1 else self._SEARCH_PAGE_URL
            try:
                async with AsyncHttpClient(timeout=30, proxy=crawler._proxy) as client:
                    resp = await client.post(url, data={"skey": actor_name}, headers=crawler._headers())
                    html_text = resp.text if resp else ""
            except Exception as e:
                logger.warning(f"JavBooks 搜索失败 {actor_name}: {e}")
                break
            if not html_text:
                break
            sel = Selector(html_text)
            found = 0
            for topic in sel.css("div.Po_topic"):
                title = (topic.css("div.Po_topic_title b ::text").get() or "").strip()
                href = (topic.css("div.Po_topic_title a::attr(href)").get()
                        or topic.css("div.Po_topicCG a::attr(href)").get() or "")
                date_serial = (topic.css("div.Po_topic_Date_Serial font ::text").get() or "")
                parts = [p.strip() for p in date_serial.split("/")]
                code = parts[0] if parts else ""
                movie_date = parts[1] if len(parts) > 1 else ""
                if not title and not code:
                    continue
                if href and not href.startswith("http"):
                    href = self.base_url + href
                movies.append({"title": title, "code": code, "date": movie_date, "url": href})
                found += 1
            if found == 0:
                break
            await asyncio.sleep(self.request_delay)
        return movies

    async def search_keyword(self, keyword: str) -> list[OnlineVideo]:
        """按关键词搜索：复用刮削模块 search（前缀搜索页精确匹配）"""
        crawler = self._get_crawler()
        results = await crawler.search(keyword)
        videos: list[OnlineVideo] = []
        seen: set[str] = set()
        for r in results:
            code = (r.code or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            base, is_chinese_suffix, is_mosaic = parse_suffix(code)
            base_code = normalize_number(base) if base else code
            base_code = strip_episode_suffix(base_code)
            videos.append(OnlineVideo(
                code=code,
                base_code=base_code,
                title=(r.title or "").strip()[:200],
                url=r.source_url or "",
                date=r.release_date.isoformat() if r.release_date else "",
                has_chinese=bool(is_chinese_suffix or r.is_chinese),
            ))
        return videos

    async def detect_actress(self, actor_name: str) -> Optional[tuple[str, str]]:
        """在 javbooks 定位该演员的搜索页 URL

        javbooks 无按女优名的独立演员页，演员页链接只能从某部作品的详情页里找到，
        无法从演员名直接确定 performer_id。因此改为**必须使用搜索**：
        POST serch_censored.htm + skey={演员名}，若搜到作品卡片则确认演员存在，
        返回统一搜索页 URL（对比时 crawl_actress 配合 actor_name 再执行搜索）。

        Returns:
            (search_page_url, actor_name) 或 None
        """
        if not actor_name:
            return None
        movies = await self._search_actor_movies(actor_name, max_pages=1)
        if not movies:
            logger.info(f"JavBooks 搜索无结果: {actor_name}")
            return None
        logger.info(f"JavBooks 探测成功: {actor_name} -> {self._SEARCH_PAGE_URL}（{len(movies)} 部作品）")
        return self._SEARCH_PAGE_URL, actor_name

    async def _fetch_magnets(self, video_url: str) -> list[dict]:
        """javbooks 磁力链接为 reurl 混淆编码，无法直接解码，返回空"""
        return []


# ===== Avmoo 列表爬虫（对比源 4） =====
# 演员页 URL: https://avmoo.shop/tw/actresses/{starId}（存储用；数据经私有 JSON API 获取）


class AvmooListCrawler:
    """avmoo 列表爬虫：按演员页或关键词爬取视频列表（新私有 JSON API）"""

    def __init__(self, max_pages: int = 10, request_delay: float = 1.0, uncensored: bool = False):
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.uncensored = uncensored
        self.base_url = "https://avmoo.shop"
        self._crawler = None

    def _get_crawler(self):
        """懒加载刮削模块的 AvmooCrawler（含 CSRF 会话 + 代理）"""
        if self._crawler is None:
            from app.crawlers.avmoo import AvmooCrawler
            self._crawler = AvmooCrawler()
        return self._crawler

    def _star_id(self, actress_url: str) -> Optional[str]:
        """从演员页 URL 提取 starId（兼容新版 /tw/actresses/{id} 与旧版 /star/{id}）"""
        m = re.search(r"/(?:tw/actresses|star)/([A-Za-z0-9]+)", actress_url or "")
        return m.group(1) if m else None

    async def crawl_actress(self, actress_url: str, actor_name: str = "") -> list[OnlineVideo]:
        """按 starId 抓取演员全部作品（getMovies 过滤）"""
        star_id = self._star_id(actress_url)
        if not star_id:
            logger.warning(f"Avmoo 无法从 URL 提取 starId: {actress_url}")
            return []
        crawler = self._get_crawler()
        movies = await crawler.fetch_actress_movies(star_id, max_pages=self.max_pages)
        videos: list[OnlineVideo] = []
        seen: set[str] = set()
        for m in movies:
            code = (m.get("code") or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            base, is_chinese_suffix, is_mosaic = parse_suffix(code)
            base_code = normalize_number(base) if base else code
            base_code = strip_episode_suffix(base_code)
            videos.append(OnlineVideo(
                code=code,
                base_code=base_code,
                title=(m.get("title") or "").strip()[:200],
                url=m.get("url") or "",
                date=m.get("date") or "",
                has_chinese=bool(is_chinese_suffix),
            ))
        return videos

    async def search_keyword(self, keyword: str) -> list[OnlineVideo]:
        """按关键词搜索"""
        crawler = self._get_crawler()
        results = await crawler.search(keyword)
        videos: list[OnlineVideo] = []
        seen: set[str] = set()
        for r in results:
            code = (r.code or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            base, is_chinese_suffix, is_mosaic = parse_suffix(code)
            base_code = normalize_number(base) if base else code
            base_code = strip_episode_suffix(base_code)
            videos.append(OnlineVideo(
                code=code,
                base_code=base_code,
                title=(r.title or "").strip()[:200],
                url=r.source_url or "",
                date=r.release_date.isoformat() if r.release_date else "",
                has_chinese=bool(is_chinese_suffix or r.is_chinese),
            ))
        return videos

    async def detect_actress(self, actor_name: str) -> Optional[tuple[str, str]]:
        """按演员名搜索 → starId → 演员页 URL

        Returns:
            (star_url, star_id) 或 None
        """
        if not actor_name:
            return None
        crawler = self._get_crawler()
        star_id = await crawler.search_star_id(actor_name)
        if not star_id:
            logger.info(f"Avmoo 未找到匹配女优页: {actor_name}")
            return None
        return f"{self.base_url}/tw/actresses/{star_id}", star_id

    async def _fetch_magnets(self, video_url: str) -> list[dict]:
        """avmoo 详情无磁力链接，返回空"""
        return []


# 对比源注册表：source 名 -> 列表爬虫工厂（供 compare.py 统一路由）
LIST_CRAWLER_SOURCES = {
    "javbus": lambda max_pages, uncensored, solo_only=False: JavBusListCrawler(max_pages=max_pages, uncensored=uncensored),
    "javdb": lambda max_pages, uncensored, solo_only=False: JavDBListCrawler(max_pages=max_pages, uncensored=uncensored, solo_only=solo_only),
    "javbooks": lambda max_pages, uncensored, solo_only=False: JavBooksListCrawler(max_pages=max_pages, uncensored=uncensored),
    "avmoo": lambda max_pages, uncensored, solo_only=False: AvmooListCrawler(max_pages=max_pages, uncensored=uncensored),
}

LIST_CRAWLER_LABELS = {
    "javbus": "JavBus",
    "javdb": "JavDB",
    "javbooks": "JavBooks",
    "avmoo": "Avmoo",
}

