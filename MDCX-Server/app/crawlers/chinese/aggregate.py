"""
国产模块聚合爬虫 — 一站覆盖所有国产站点。

数据源：
1. ModelMediaAsia 官方 API — 麻豆传媒官方 JSON API (最高优先级)
2. HDouban API — 通用国产番号元数据 API
3. CNMDB — 国产片数据库

使用方式：
  crawler = ChineseAggregateCrawler()
  result = await crawler.search(keyword, studio=None)
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.services.proxy_manager import get_effective_proxy_url
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 国产工作室数据
STUDIO_KEYWORDS: dict[str, list[str]] = {
    "麻豆传媒": ["madou", "麻豆", "mds", "mdx", "md"],
    "天美传媒": ["tianmei", "天美", "tm"],
    "果冻传媒": ["guodong", "果冻", "gd"],
    "精东影业": ["jingdong", "精东", "jd"],
    "糖心VLOG": ["tangxin", "糖心", "tx"],
    "蜜桃传媒": ["mitao", "蜜桃", "mt"],
    "星空无限": ["xingkong", "星空", "xk"],
    "SWAG": ["swag"],
    "大象传媒": ["daxiang", "大象", "dx"],
    "爱豆传媒": ["aidou", "爱豆", "ad"],
}

# 已知国产演员完整列表
KNOWN_ACTORS: list[str] = [
    "沈娜娜", "夏晴子", "苏语棠", "张芸熙", "杜冰若", "叶一涵",
    "唐芯", "王茜", "董小宛", "秦可欣", "叶紫彤", "赵颖",
    "王雨蝶", "李慕儿", "林予曦", "乔伊", "杨依", "陈雪儿",
    "周若云", "刘雅", "林思妤", "吴欣", "蔡萝莉", "白鹿",
    "王子欣", "韩雪儿", "黄可欣", "林果果", "林依诺", "王梓晗",
    "张岚", "沈芯语", "安琪", "林可欣", "陈曦", "杨柳",
    "宋雪儿", "李佳欣", "林婉仪", "王艺", "慕容可可", "赵一曼",
    "苏苏", "糖糖", "李瑶", "安娜", "王小雅", "张若琳",
    "陈雨奇", "周思琪", "唐雅", "蓝若曦", "赵欣", "杨雪",
    "李小小", "夏小薇", "刘一诺", "王嘉欣", "林诗琪", "陈梓欣",
    "杨幂璐", "张思琪", "周佳怡", "宋怡", "赵佳美", "王晨曦",
    "周雅欣", "林苗", "杨芬", "徐丽", "张婷婷", "刘梦瑶",
    "林婉儿", "叶心", "唐静", "王颖", "李思琪", "刘思瑶",
    "赵雅欣", "方雅", "林怡", "王怡然", "赵若萱", "陈思艺",
    "杨子嫣", "周雨彤", "唐艺", "夏洛依", "孙晓萌",
    "王艺绒", "赵初然", "李瑶瑶", "刘亦希", "吴梦雅", "唐悠悠",
    "陈雨涵", "林若曦", "周子怡", "张子欣", "王思妍",
    "夏雪", "林婉清", "赵灵儿", "王诗涵", "李芷晴",
    "雪碧", "草莓", "尤娜", "允希", "可凡", "冰冰", "可欣",
    "小只", "兔兔", "芋圆", "奶茶", "维维", "蔓蔓", "若溪",
    "西西", "晴晴", "念念", "芷柔", "宇希", "朵朵",
    "HongKongDoll", "玩偶姐姐", "梁佳芯", "雪霏", "穆雪",
    "璇元", "寻小小", "楚梦舒", "袁子仪", "蜜苏", "宁娜",
    "苏文文", "莉娜乔安", "美雪樱", "沈樵", "吴梦梦",
    "孟若羽", "王小妮", "郭童童",
]


@dataclass
class ChineseVideoInfo:
    code: str
    title: str
    actors: list[str] = field(default_factory=list)
    studio: str = ""
    release_date: str = ""
    duration: int = 0
    cover_url: str = ""
    poster_url: str = ""
    plot: str = ""
    genres: list[str] = field(default_factory=list)
    sample_images: list[str] = field(default_factory=list)
    source: str = ""


def _guess_studio(code: str) -> str:
    """从番号猜测工作室。"""
    code_upper = code.upper()
    for studio, keywords in STUDIO_KEYWORDS.items():
        for kw in keywords:
            if code_upper.startswith(kw.upper()):
                return studio
    return ""


def _extract_actors(text: str) -> list[str]:
    """从文本中提取已知演员名。"""
    found: list[str] = []
    for actor in KNOWN_ACTORS:
        if actor in text:
            found.append(actor)
    return found


# ---------------------------------------------------------------------------
# 数据源 1: HDouban API (通用国产番号搜索)
# ---------------------------------------------------------------------------

_HD_API_SEARCH = "https://api.6dccbca.com/api/search"
_HD_API_DETAIL = "https://api.6dccbca.com/api/movie/detail"


async def _search_hdouban(code: str, client: httpx.AsyncClient) -> Optional[ChineseVideoInfo]:
    """通过 HDouban API 搜索国产番号。"""
    try:
        r = await client.get(
            _HD_API_SEARCH,
            params={"ty": "movie", "search": code, "page": 1, "pageSize": 5},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("data", {}).get("list", []) if isinstance(data, dict) else []
        if not items:
            return None

        # 精确匹配
        best = None
        for item in items:
            item_code = (item.get("number") or "").upper().replace("-", "").replace(" ", "")
            search_code = code.upper().replace("-", "").replace(" ", "")
            if item_code == search_code:
                best = item
                break
        if not best:
            best = items[0]

        vid = best.get("id", "")
        if vid:
            rd = await client.post(
                _HD_API_DETAIL,
                data={"id": vid},
                timeout=10.0,
            )
            if rd.status_code == 200:
                detail = rd.json().get("data", {})
                return ChineseVideoInfo(
                    code=best.get("number", code),
                    title=detail.get("title") or best.get("title", ""),
                    actors=[a.get("name", "") for a in (detail.get("actors") or [])],
                    studio=detail.get("studio") or _guess_studio(code),
                    release_date=detail.get("publishDate", ""),
                    duration=detail.get("duration", 0),
                    cover_url=detail.get("cover", ""),
                    poster_url=best.get("cover", ""),
                    plot=detail.get("description", ""),
                    genres=[g.get("name", "") for g in (detail.get("genres") or [])],
                    source="hdouban",
                )

        return ChineseVideoInfo(
            code=best.get("number", code),
            title=best.get("title", ""),
            actors=_extract_actors(best.get("title", "") + best.get("number", "")),
            studio=_guess_studio(code),
            cover_url=best.get("cover", ""),
            source="hdouban",
        )
    except Exception as e:
        logger.debug("hdouban search failed for %s: %s", code, e)
    return None


# ---------------------------------------------------------------------------
# 数据源 2: ModelMediaAsia 官方 API (麻豆官方)
# ---------------------------------------------------------------------------

_MODEL_API_BASE = "https://model-api.bvncmsldo.com/api/v2"
_MODEL_API_SEARCH = f"{_MODEL_API_BASE}/videos"
_MODEL_STUDIO = "麻豆傳媒映畫"


async def _search_model_media(code: str, client: httpx.AsyncClient) -> Optional[ChineseVideoInfo]:
    """通过 ModelMediaAsia 官方 API 搜索麻豆视频。"""
    try:
        clean_code = re.sub(r"[^A-Za-z0-9]", "", code.upper())
        r = await client.get(
            _MODEL_API_SEARCH,
            params={"code": clean_code, "limit": 1},
            headers={
                "Accept": "application/json",
                "Referer": "https://modelmediaasia.com/",
            },
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        if not items:
            return None

        item = items[0] if isinstance(items, list) else items
        actors_raw = item.get("models") or item.get("actors") or []
        actors = [a.get("name", "") if isinstance(a, dict) else str(a) for a in actors_raw]

        return ChineseVideoInfo(
            code=item.get("code", code).upper(),
            title=item.get("title", {}).get("zh") or item.get("title", ""),
            actors=actors,
            studio=_MODEL_STUDIO,
            release_date=item.get("release_date", ""),
            duration=item.get("duration", 0),
            cover_url=item.get("cover_url", "") or item.get("image", ""),
            poster_url=item.get("poster_url", "") or item.get("poster", ""),
            plot=item.get("description", {}).get("zh", ""),
            genres=[g.get("name", "") for g in (item.get("tags", []) or [])],
            sample_images=[s.get("url", "") for s in (item.get("screenshots", []) or [])],
            source="modelmediaasia",
        )
    except Exception as e:
        logger.debug("modelmedia search failed for %s: %s", code, e)
    return None


# ---------------------------------------------------------------------------
# 数据源 3: CNMDB (国产片数据库兜底)
# ---------------------------------------------------------------------------

_CNMDB_BASE = "https://cnmdb.net"


async def _search_cnmdb(code: str, client: httpx.AsyncClient) -> Optional[ChineseVideoInfo]:
    """通过 CNMDB 搜索国产片。"""
    try:
        r = await client.get(
            f"{_CNMDB_BASE}/{code}",
            headers={"Referer": _CNMDB_BASE},
            timeout=10.0,
        )
        if r.status_code != 200:
            # 尝试搜索
            rs = await client.get(
                f"{_CNMDB_BASE}/s0",
                params={"q": code},
                timeout=10.0,
            )
            if rs.status_code != 200:
                return None
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(rs.text, "html.parser")
            link = soup.select_one("a[href*='/']")
            if not link or not link.get("href"):
                return None
            detail_url = link["href"]
            if not detail_url.startswith("http"):
                detail_url = _CNMDB_BASE + detail_url
            r = await client.get(detail_url, timeout=10.0)
            if r.status_code != 200:
                return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        title_el = soup.select_one("h1, .title")
        title = title_el.text.strip() if title_el else ""

        cover_el = soup.select_one("img.cover, .poster img, img[src*='cover']")
        cover = ""
        if cover_el:
            src = cover_el.get("src") or cover_el.get("data-src", "")
            if src and not src.startswith("http"):
                cover = _CNMDB_BASE + src
            else:
                cover = src

        actors = _extract_actors(title + code)
        studio = _guess_studio(code)

        return ChineseVideoInfo(
            code=code.upper(),
            title=title,
            actors=actors,
            studio=studio,
            cover_url=cover,
            source="cnmdb",
        )
    except Exception as e:
        logger.debug("cnmdb search failed for %s: %s", code, e)
    return None


# ---------------------------------------------------------------------------
# 聚合爬虫类
# ---------------------------------------------------------------------------


class ChineseAggregateScraper:
    """国产聚合搜索器 — 按优先级链搜索多个数据源。"""

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy

    async def search(self, code: str) -> Optional[ChineseVideoInfo]:
        """搜索国产视频信息。

        优先级: ModelMediaAsia API → HDouban API → CNMDB → 纯番号推测
        """
        async with httpx.AsyncClient(
            timeout=15.0,
            proxy=self.proxy,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/html",
            },
            follow_redirects=True,
        ) as client:
            # 1. ModelMediaAsia 官方 API
            result = await _search_model_media(code, client)
            if result and result.title:
                logger.info("chinese search %s: found via modelmediaasia", code)
                return result

            # 2. HDouban API
            result = await _search_hdouban(code, client)
            if result and result.title:
                logger.info("chinese search %s: found via hdouban", code)
                return result

            # 3. CNMDB
            result = await _search_cnmdb(code, client)
            if result and result.title:
                logger.info("chinese search %s: found via cnmdb", code)
                return result

        # 4. 纯番号猜测
        studio = _guess_studio(code)
        actors = _extract_actors(code)
        logger.info("chinese search %s: no data source found, using guess only", code)
        return ChineseVideoInfo(
            code=code,
            title=code,
            actors=actors,
            studio=studio,
            source="guess",
        )

    async def search_actor(self, actor_name: str) -> list[ChineseVideoInfo]:
        """搜索某个演员的全部作品（从 HDouban 搜索）。"""
        results: list[ChineseVideoInfo] = []
        async with httpx.AsyncClient(
            timeout=15.0,
            proxy=self.proxy,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            try:
                for page in range(1, 4):
                    r = await client.get(
                        _HD_API_SEARCH,
                        params={"ty": "movie", "search": actor_name, "page": page, "pageSize": 20},
                        timeout=10.0,
                    )
                    if r.status_code != 200:
                        break
                    data = r.json()
                    items = data.get("data", {}).get("list", []) if isinstance(data, dict) else []
                    if not items:
                        break
                    for item in items:
                        results.append(ChineseVideoInfo(
                            code=item.get("number", ""),
                            title=item.get("title", ""),
                            studio=_guess_studio(item.get("number", "")),
                            cover_url=item.get("cover", ""),
                            release_date=item.get("publishDate", ""),
                            source="hdouban",
                        ))
            except Exception as e:
                logger.debug("search_actor failed for %s: %s", actor_name, e)
        return results


async def scrape_chinese(code: str) -> Optional[ScrapeResult]:
    """国产刮削入口 — 供 scraper/engine.py 调用。"""
    from app.services.proxy_manager import get_effective_proxy_url

    proxy = get_effective_proxy_url()

    scraper = ChineseAggregateScraper(proxy=proxy)
    info = await scraper.search(code)
    if not info:
        return None

    result = ScrapeResult()
    result.title = info.title
    result.code = info.code
    result.studio = info.studio
    result.cover_url = info.cover_url
    result.poster_url = info.poster_url
    result.release_date = info.release_date
    result.duration = info.duration
    result.plot = info.plot
    result.genres = info.genres
    result.actors = [ActorInfo(name=a) for a in info.actors]
    result.source = info.source
    result.source_url = info.code
    return result
