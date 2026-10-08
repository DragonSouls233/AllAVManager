"""Heyzo 爬虫（英文站 en.heyzo.com）

来源：ref155-crawlerx（Adapters/Heyzo）。2026-10-07 实测验证：
  - 详情页可达（经代理），title / 封面 / 演员 / 系列(作 genres) 可解析。
  - 演员选择器为字段级，已排除相关影片区误抓（全局 `a.actor` 会误抓分类/相关影片）。
  - 封面不在静态 HTML（JS 拼出）：`dir_gallery = /contents/{分组}/{id}/gallery/`，
    实测 `gallery/001.jpg` 返回 image/jpeg；`images/player_cover.jpg` 404（不存在）。
  - 详情页无 th/td 信息表、无 JSON-LD、og:description 为通用文案 ⇒
    duration / release_date / studio / plot 拿不到，**不伪造**（has_content 靠 title+cover+actor+genres 撑起）。

URL 规律：
  - 详情页：https://en.heyzo.com/moviepages/{id}/index.html  （id 为纯数字）
  - 封面  ：https://en.heyzo.com/contents/{分组}/{id}/gallery/001.jpg
            （分组 = (id // 1000) * 1000，如 3954 → 3000）

番号路由：纯数字或 HEYZO- 前缀才处理；其它番号（如 ABC-123）直接返回 None，
避免对无关番号空发请求污染源序。
"""

import logging
import re
from datetime import date
from typing import Optional

from lxml import etree

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

_BASE = "https://en.heyzo.com"
# 详情页字段级演员选择器：排除相关影片区（relateive-movies）误抓
_ACTOR_XPATH = (
    "//a[contains(@href,'listpages/actor_') and "
    "not(ancestor::div[contains(concat(' ',normalize-space(@class),' '),'relateive-movies')])]"
)
# 系列/分类链接（Heyzo 详情页无 genre_ 链接，series_ 是最接近的“分类/标签”数据）
_SERIES_XPATH = "//a[contains(@href,'listpages/series_')]"

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _extract_id(code: str) -> Optional[str]:
    """从用户输入的番号提取 Heyzo 数字 id；非 Heyzo 番号返回 None。"""
    if not code:
        return None
    c = code.strip()
    if c.upper().startswith("HEYZO"):
        c = re.sub(r"^HEYZO[-_ ]?", "", c, flags=re.IGNORECASE)
    # 仅接受纯数字 id（Heyzo 影片 id 为纯整数）
    m = re.match(r"^(\d{2,7})$", c)
    return m.group(1) if m else None


def _gallery_group(movie_id: str) -> str:
    """封面路径的分组目录：(id // 1000) * 1000。"""
    return str((int(movie_id) // 1000) * 1000)


def _clean_title(raw_title: str) -> str:
    """从 <title> 或 <h1> 提取纯影片标题，去掉站点后缀与演员名。"""
    if not raw_title:
        return ""
    # 先去首尾空白（h1 文本常以前导 \n\t 开头，否则会在开头换行处误切）
    s = raw_title.strip()
    # <h1> 形如 "Beauty Collection Vol.141\n...- Ayane Nakai"；
    # <title> 形如 "Ayane Nakai  Beauty Collection Vol.141 - HEYZO"
    # 取第一个 '-' / 换行前的部分作为标题。
    head = re.split(r"[\n\-]", s, maxsplit=1)[0]
    return head.strip()


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        t = it.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


@register_crawler
class HeyzoCrawler(BaseCrawler):
    name = "heyzo"
    display_name = "Heyzo"
    base_url = _BASE

    priority = CrawlerPriority.LOW  # 辅助源，低优先级（与 thejavdb 同级）
    supported_types = ["jav"]
    supported_prefixes = []  # 纯数字 id 无前缀；靠源序 + 类型匹配路由
    description = "Heyzo 英文站（en.heyzo.com）影片元数据"
    language = "en"
    requires_proxy = True

    # ------------------------------------------------------------------
    # 公开调用入口
    # ------------------------------------------------------------------
    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        movie_id = _extract_id(code)
        if not movie_id:
            # 非 Heyzo 番号：不打网络，直接返回 None（避免污染源序）
            return None
        if ctx is not None and getattr(ctx, "http_client", None) is not None:
            return await self._scrape_with_client(movie_id, ctx.http_client)
        async with AsyncHttpClient() as client:
            return await self._scrape_with_client(movie_id, client)

    async def _scrape_with_client(self, movie_id: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
        detail_url = f"{_BASE}/moviepages/{movie_id}/index.html"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            html_text = await client.get_text(detail_url, headers=headers)
        except Exception as e:
            self.mark_error()
            logger.debug(f"Heyzo {movie_id} 请求失败: {e}")
            return None

        if not html_text:
            self.mark_error()
            return None

        result = self._parse(html_text, movie_id, detail_url)
        if result is None:
            self.mark_error()
            logger.debug(f"Heyzo {movie_id}: 页面未解析出有效内容（可能 404/非影片页）")
            return None
        self.mark_success()
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """Heyzo 英文站无稳定公开搜索端点；按 id 抓取是唯一可靠路径，故返回空。

        返回空列表不会造成误判（engine 走 scrape-by-code 主路径）。
        """
        return []

    # ------------------------------------------------------------------
    # 解析（离线可测：接收 HTML 文本，不依赖网络）
    # ------------------------------------------------------------------
    def _parse(
        self, html_text: str, movie_id: str, detail_url: str
    ) -> Optional[ScrapeResult]:
        try:
            tree = etree.fromstring(
                html_text.encode("utf-8") if isinstance(html_text, str) else html_text,
                etree.HTMLParser(),
            )
        except Exception as e:
            logger.debug(f"Heyzo {movie_id} HTML 解析失败: {e}")
            return None

        # 软 404 / 非影片页判定：真实影片页有 html5_player video 节点
        if tree.xpath("//video[@id='html5_player']") is None:
            return None
        low = (html_text or "").lower()
        if "page not found" in low or "404 - " in low:
            return None

        # 标题：优先 <h1> 首节点，回退 <title>
        title = ""
        h1 = tree.xpath("//h1")
        if h1:
            title = _clean_title(" ".join(h1[0].xpath(".//text()")))
        if not title:
            title = _clean_title(" ".join(tree.xpath("//title/text()")).strip())
        if not title:
            return None

        # 封面：JS 拼出的 gallery 首图（实测 image/jpeg；player_cover.jpg 不存在）
        group = _gallery_group(movie_id)
        cover_url = f"{_BASE}/contents/{group}/{movie_id}/gallery/001.jpg"

        # 演员（字段级，排除相关影片区误抓）
        actors: list[ActorInfo] = []
        for a in tree.xpath(_ACTOR_XPATH):
            name = " ".join(a.xpath(".//text()")).strip()
            if name:
                actors.append(ActorInfo(name=name))

        # 系列/分类 → genres（Heyzo 详情页无 genre_ 链接，series_ 是最接近的标签）
        genres = _dedup([ " ".join(a.xpath(".//text()")).strip()
                          for a in tree.xpath(_SERIES_XPATH) ])

        # 样图（前 3 张 gallery 图，可选）
        sample_images = [
            f"{_BASE}/contents/{group}/{movie_id}/gallery/{i:03d}.jpg"
            for i in range(1, 4)
        ]

        result = ScrapeResult(
            code=movie_id,
            title=title,
            source=self.name,
            source_url=detail_url,
            cover_url=cover_url,
            poster_url=cover_url,
            thumb_url=cover_url,
            actors=actors,
            all_actors=[a.name for a in actors],
            genres=genres,
            tags=genres,
            sample_images=sample_images,
        )
        return result
