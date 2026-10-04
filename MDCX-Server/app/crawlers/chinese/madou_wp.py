"""国产模块爬虫 — 麻豆（madouqu.com）WordPress 站。

🔴 2026-10-04 实测依据（真实样本 G:\\TEST\\国产\\麻豆传媒）：
  ① **可用域名是 `www.madouqu.com`**（71KB 完整站，标题「麻豆区 - 麻豆传媒等国产
     传媒视频免费下载收藏区」）。旧代码 `base_url = "https://madouqu.sbs"` 与
     site_switchers 里的候选（lwabe.com / madou.com / madouqu.sbs / .net / .org）
     **全部实测不可达或 522** ⇒ chinese 模块长期 0 命中。
  ② 站点是标准 WordPress：搜索用 `?s=<关键词>`，结果在 `//article` 里，
     标题 `<h2 class="entry-title"><a>`，链接规律 `/video/<番号小写>/`。
  ③ 详情页 `meta description` 直接给出结构化字段（实测）：
     「麻豆番號：MD-0263 麻豆片名：美乳禦姐應援面試 麻豆女郎：梁佳芯 下載地址：」
     ⇒ 番号/片名/演员三项无需再猜 DOM，一次正则全拿到。
  ④ 封面走 `og:image`（原图，不是缩略图）。
  ⑤ 站内番号写法是 `MD0263`（**无连字符**），与文件名/番号标准 `MD-0263` 不同，
     搜索时必须两种写法都试。

实测抓取结果（G:\\TEST 真实样本）：
  MD-0263 → og:title=`MD0263 美乳禦姐應援面試`
           → desc 解析出 番号=MD-0263 / 片名=美乳禦姐應援面試 / 女郎=梁佳芯
"""
from __future__ import annotations

import re
from typing import Optional

from lxml import html as lxml_html

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

MADOU_BASE = "https://www.madouqu.com"

# 备用域名（2026-10-04 实测：只有 madouqu.com 完整可用，其余留作容灾）
# 🔴 实测 madouqu.com 存在**间歇性 ConnectTimeout**（同一天内 200 与超时交替），
#    所以必须做域名级回退 + 记忆上次成功域名，不能写死单域名。
MADOU_FALLBACKS = (
    "https://www.madouqu.com",
    "https://madou.club",
    "https://madouqu.cc",
    "https://madouqu.net",
)

# 详情页 meta description 的字段格式（实测原文）：
#   麻豆番號：MD-0263 麻豆片名：美乳禦姐應援面試 麻豆女郎：梁佳芯 下載地址：
_DESC_NUM_RE = re.compile(r"麻豆番號[：:]\s*([A-Za-z0-9\-]+)")
_DESC_TITLE_RE = re.compile(r"麻豆片名[：:]\s*(.+?)\s*(?=麻豆|下載|$)")
_DESC_ACTORS_RE = re.compile(r"麻豆女郎[：:]\s*(.+?)\s*(?=下載|$)")
_DESC_STUDIO_RE = re.compile(r"(麻豆傳媒|麻豆传媒)")

# 站内番号常见写法 → 统一大写带连字符
def _norm_madou_code(raw: str) -> str:
    """把站内写法（MD0263 / md-0263 / MDCM0006）统一成 `MDCM-0006`。"""
    s = (raw or "").strip().upper().replace("_", "-")
    if not s:
        return ""
    m = re.match(r"^([A-Z]{2,6})-?(\d{2,6})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return s


def _search_variants(code: str) -> list[str]:
    """站内搜索词变体：MD-0263 / MD0263 两种写法都要试（实测站内是无连字符的）。"""
    base = (code or "").strip()
    out = [base]
    m = re.match(r"^([A-Za-z]{2,6})-?(\d{2,6})$", base)
    if m:
        no_dash = f"{m.group(1)}{m.group(2)}"
        dashed = f"{m.group(1)}-{m.group(2)}"
        for v in (no_dash, dashed):
            if v not in out:
                out.append(v)
    return out


@register_crawler
class MadouWordPressCrawler(BaseCrawler):
    """麻豆（madouqu.com）国产刮削器 — WordPress 搜索 + meta description 解析。

    ⚠️ 与 `app/crawlers/chinese/madou.py`（磁力搜索爬虫）**并存不冲突**：
       那个抓磁力链接，本类抓元数据（番号/片名/演员/封面）。
    """

    name = "madou_wp"
    display_name = "麻豆 madouqu.com"
    base_url = MADOU_BASE

    priority = CrawlerPriority.VERY_HIGH
    supported_types = ["chinese"]
    description = "麻豆传媒国产元数据（madouqu.com WordPress 站，实测可用）"
    language = "zh"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        from app.services.proxy_manager import get_effective_proxy_url
        self._proxy = get_effective_proxy_url()
        self._base = MADOU_BASE   # 当前可用域名（可被回退逻辑改写）

    def _headers(self) -> dict:
        return {
            "User-Agent": _USER_AGENT,
            "Referer": self._base + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    # ── 域名回退 ───────────────────────────────────────────────────────
    def _bases(self) -> list[str]:
        """把上次成功的域名排到最前（进程级记忆，避免每次都从死域开始试）。"""
        seen, out = {self._base}, [self._base]
        for b in MADOU_FALLBACKS:
            if b not in seen:
                seen.add(b)
                out.append(b)
        return out

    def _remember_base(self, base: str) -> None:
        if base != self._base:
            logger.info("madou_wp 切换可用域名: %s -> %s", self._base, base)
            self._base = base

    # ── 搜索页 ───────────────────────────────────────────────────────────
    async def _search_page(self, client: AsyncHttpClient, query: str) -> list[tuple[str, str]]:
        """返回 [(标题, 详情页URL)]。跨候选域名回退。"""
        from urllib.parse import quote

        q = quote(query)
        for base in self._bases():
            try:
                text = await client.get_text(f"{base}/?s={q}", headers=self._headers())
            except Exception as e:
                logger.debug("madou_wp 搜索失败 [%s|%s]: %s", base, query, e)
                continue
            if not text:
                continue
            self._remember_base(base)
            try:
                doc = lxml_html.fromstring(text)
            except Exception:
                return []

            out: list[tuple[str, str]] = []
            for art in doc.xpath("//article"):
                links = art.xpath('.//h2[contains(@class,"entry-title")]//a[@href]')
                if not links:
                    links = art.xpath(".//h2//a[@href]")
                if not links:
                    continue
                title = links[0].text_content().strip()
                href = links[0].get("href", "")
                if href:
                    out.append((title, href))
            return out
        return []

    # ── 详情页 ───────────────────────────────────────────────────────────
    async def _fetch_detail(
        self, client: AsyncHttpClient, url: str
    ) -> Optional[ScrapeResult]:
        try:
            text = await client.get_text(url, headers=self._headers())
        except Exception as e:
            logger.debug("madou_wp 详情失败 %s: %s", url, e)
            return None
        if not text:
            return None

        try:
            doc = lxml_html.fromstring(text)
        except Exception:
            return None

        result = ScrapeResult(source="madou_wp", source_url=url)

        # ① meta description —— 番号/片名/演员一次拿全（实测最可靠）
        desc = ""
        for m in doc.xpath('//meta[@name="description"]/@content | //meta[@property="og:description"]/@content'):
            if m:
                desc = m
                break

        num = ""
        if m := _DESC_NUM_RE.search(desc):
            num = _norm_madou_code(m.group(1))
        # ② 兜底：从 og:title 的「MD0263 片名」取番号
        title_text = ""
        for m in doc.xpath('//meta[@property="og:title"]/@content | //h1//text()'):
            if m:
                title_text = m.strip()
                break
        if not num:
            m = re.match(r"^([A-Za-z]{2,6})-?(\d{2,6})\s*(.*)$", title_text)
            if m:
                num = f"{m.group(1).upper()}-{m.group(2)}"
                if not result.title and m.group(3):
                    result.title = m.group(3).strip()
        if not num and not result.title:
            return None

        # 片名
        if not result.title:
            if m := _DESC_TITLE_RE.search(desc):
                result.title = m.group(1).strip()
        if not result.title:
            result.title = re.sub(r"^[A-Za-z]{2,6}-?\d{2,6}\s*", "", title_text).strip()
        if not result.title:
            result.title = num

        # 演员（麻豆女郎，可多人顿号/逗号分隔）
        actors: list[ActorInfo] = []
        if m := _DESC_ACTORS_RE.search(desc):
            raw = re.split(r"[、,，/／\s]+", m.group(1).strip())
            for n in raw:
                n = n.strip()
                # 过滤「未知」这类占位与超长噪声
                if n and n not in ("未知", "不详", "无") and len(n) <= 20:
                    actors.append(ActorInfo(name=n))
        result.actors = actors

        result.original_title = result.title
        result.studio = "麻豆传媒"
        result.code = num or result.title
        result.cover_url = (
            doc.xpath('//meta[@property="og:image"]/@content') or [None]
        )[0]
        result.plot = desc[:2000] or None
        result.genres = ["麻豆传媒", "国产"]
        return result

    # ── BaseCrawler 接口 ────────────────────────────────────────────────
    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        if not code or not code.strip():
            return None

        for query in _search_variants(code):
            # ⚠️ 每次搜索用独立 client：curl_cffi 在同一 client 连续请求多个
            #    站点时会静默杀掉整个进程（不是抛异常，拦不住）。
            async with AsyncHttpClient(timeout=25, proxy=self._proxy) as client:
                items = await self._search_page(client, query)
            if not items:
                continue

            target = _norm_madou_code(code)
            for title, href in items[:8]:
                cand = ""
                # 标题里含番号（忽略连字符差异）才算命中，避免拿到"相邻番号"
                head = re.match(r"^([A-Za-z]{2,6})-?(\d{2,6})", title.strip())
                if head:
                    cand = f"{head.group(1).upper()}-{head.group(2)}"
                    if target and cand != target:
                        continue
                async with AsyncHttpClient(timeout=25, proxy=self._proxy) as client:
                    r = await self._fetch_detail(client, href)
                if r and r.title:
                    if not r.code:
                        r.code = target or cand or title[:40]
                    self.mark_success()
                    logger.info("madou_wp 命中 [%s] -> %s (%s)", code, r.title, href)
                    return r
        self.mark_error()
        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """按番号或关键词搜索，返回候选列表。"""
        results: list[ScrapeResult] = []
        async with AsyncHttpClient(timeout=25, proxy=self._proxy) as client:
            items = await self._search_page(client, keyword)
        for title, href in items[:10]:
            async with AsyncHttpClient(timeout=25, proxy=self._proxy) as client:
                r = await self._fetch_detail(client, href)
            if r and r.title:
                if not r.code:
                    r.code = title[:40]
                results.append(r)
        return results