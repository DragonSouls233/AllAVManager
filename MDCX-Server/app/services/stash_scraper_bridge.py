"""Stash 刮削器桥接器 — 让 MDCX 能使用 Stash 社区的数百个刮削器。

Stash 刮削器是 YAML 格式的声明式爬虫。
这个桥接器将 Stash YAML 刮削器转换为 MDCX 可调用的爬虫。

支持：
1. 内置 Stash YAML 解析器
2. 通用的欧美/PORNHub刮削器桥接
3. 可通过 URL 或名称自动路由

参考：
- CommunityScrapers 仓库的数百个 YAML 刮削器
- Stash 官方 YAML 刮削器格式规范
"""

import logging
import re
from pathlib import Path
from typing import Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False
    logging.getLogger(__name__).warning("PyYAML not installed, stash YAML scrapers disabled. pip install pyyaml")

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.scraper.errors import ResourceUnavailable
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 内置的 5 个重点欧美站点 YAML 刮削器
_BUILTIN_SCRAPERS: dict[str, dict] = {}


def _register_builtin():
    """注册内置的 Stash 格式刮削器。"""
    scrapers = {
        "brazzers": {
            "name": "Brazzers",
            "url": "https://www.brazzers.com/video/{id}",
            "xpath": {
                "title": "//h1/text()",
                "date": '//meta[@property="article:published_time"]/@content',
                "cover": '//meta[@property="og:image"]/@content',
                "actors": '//a[contains(@href,"/pornstar/")]/text()',
                "tags": '//a[contains(@href,"/category/")]/text()',
                "studio": "//a[contains(@href,'/studio/')]/text()",
            },
        },
        "realitykings": {
            "name": "Reality Kings",
            "url": "https://www.realitykings.com/video/{id}",
            "xpath": {
                "title": "//h1/text()",
                "date": '//meta[@property="article:published_time"]/@content',
                "cover": '//meta[@property="og:image"]/@content',
                "actors": '//a[contains(@href,"/models/")]/text()',
            },
        },
    }
    _BUILTIN_SCRAPERS.update(scrapers)


_register_builtin()


class StashScraperBridge:
    """Stash YAML 刮削器到 MDCX 爬虫的桥接器。"""

    def __init__(self, scrapers_dir: str | None = None):
        self._scrapers: dict[str, dict] = dict(_BUILTIN_SCRAPERS)
        if scrapers_dir:
            self._load_from_dir(scrapers_dir)

    def _load_from_dir(self, directory: str):
        """从目录加载 YAML 刮削器文件。"""
        d = Path(directory)
        if not d.is_dir():
            return
        for f in d.glob("*.yml"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                    if isinstance(data, dict) and data.get("name"):
                        self._scrapers[data["name"].lower()] = data
            except Exception as e:
                logger.debug("failed to load scraper %s: %s", f.name, e)

    def list_scrapers(self) -> list[str]:
        return list(self._scrapers.keys())

    def get_scraper(self, name: str) -> Optional[dict]:
        return self._scrapers.get(name.lower())

    def search(self, code: str) -> Optional[str]:
        """根据番号/URL匹配刮削器。"""
        for name, scraper in self._scrapers.items():
            url_pattern = scraper.get("url", "")
            if url_pattern and code.lower() in url_pattern.lower():
                return name
        return None


# 全局桥接器
_bridge: Optional[StashScraperBridge] = None


def get_bridge() -> StashScraperBridge:
    global _bridge
    if _bridge is None:
        _bridge = StashScraperBridge()
    return _bridge


# ---------------------------------------------------------------------------
# 通用 Stash 兼容爬虫
# ---------------------------------------------------------------------------


@register_crawler
class StashGenericCrawler(BaseCrawler):
    """通用 Stash 兼容刮削器 — 仅服务欧美站点（theporndb / Stash 实例）。

    🔴 2026-10-15 修正：曾误把 "pornhub" 写进 supported_types。
       本爬虫按 Stash scraper 名 / URL 匹配，对 PORNHUB viewkey（形如
       ``ph69a4d19084d2f``）永远走 ``else`` 分支抛 ``ResourceUnavailable(not_listed)``，
       根本拿不到数据。一旦真正的 ``pornhub_api`` 被熔断禁用，pornhub 模块就只剩它
       ⇒ 每部都 not_listed ⇒ 补刮/批量刮削 0 成功。PORNHUB 只走 ``pornhub_api`` /
       ``pornhub`` 专属爬虫，这里坚决不能掺和（用户 2026-10-14 明确要求
       "PORNHUB 只有 PORNHUB 的"）。
    """

    name = "stash_generic"
    display_name = "Stash Generic"
    base_url = ""

    priority = CrawlerPriority.LOW
    # 🔴 仅 western：stash 按 URL/scraper 名匹配，爬不了 PORNHUB viewkey。
    supported_types = ["western"]
    description = "通用 Stash 格式刮削器（欧美）"
    language = "en"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        # 1. 匹配刮削器
        bridge = get_bridge()
        scraper_name = bridge.search(code)

        # 2. 按 URL 模式猜测
        if not scraper_name:
            if "brazzers" in code.lower():
                scraper_name = "brazzers"
            elif "realitykings" in code.lower():
                scraper_name = "realitykings"
            else:
                # 🔴 2026-10-14：这个源根本不收录该番号 ⇒ **必须抛
                #    ResourceUnavailable，不能 return None**。
                #    本爬虫 supported_types 含 pornhub，所以每一道 PH 番号都会走到这里；
                #    旧实现 return None ⇒ engine 记一次「源失败」并喂给熔断器 ⇒
                #    每刮一部就跳闸一次，45s 冷却被指数放大到 **6 小时上限**
                #    （实测 stash_generic 熔断 20,503s、触发 300 次），
                #    期间整条无码/欧美源序被白白短路。
                #    语义上这属于「源站确认没有这个资源」，不是「源坏了」。
                raise ResourceUnavailable(
                    f"stash 未收录该番号/URL: {code}", kind="not_listed"
                )

        scraper = bridge.get_scraper(scraper_name)
        if not scraper:
            raise ResourceUnavailable(
                f"stash 刮削器不存在: {scraper_name}", kind="not_listed"
            )

        return await self._scrape_with_stash(code, scraper)

    async def search(self, keyword: str) -> list[ScrapeResult]:
        results: list[ScrapeResult] = []
        r = await self.scrape(keyword)
        if r:
            results.append(r)
        return results

    async def _scrape_with_stash(self, code: str, scraper: dict) -> Optional[ScrapeResult]:
        xpath = scraper.get("xpath", {})
        if not xpath:
            raise ResourceUnavailable(
                f"stash 刮削器缺 xpath: {scraper.get('name')}", kind="bad_config"
            )

        url = code  # code 就是 URL
        # 🔴 2026-10-14：code 必须是 URL 才会被当地址请求。
        #   PORNHUB 番号形如 `ph69a4d19084d2f`，直接丢给 httpx 会得到
        #   "unsupported/invalid URL" 类异常，旧实现 except Exception → return None
        #   ⇒ 又一次「源失败」。这里提前判定并抛 ResourceUnavailable（语义正确、不熔断）。
        if not re.match(r"^https?://", url.strip(), re.I):
            raise ResourceUnavailable(
                f"stash 需要 URL 而非番号: {code}", kind="not_a_url"
            )

        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                html = await client.get_text(url, headers={"User-Agent": _USER_AGENT})
                if not html:
                    raise ResourceUnavailable(
                        f"stash 抓取到空页面: {url}", kind="empty"
                    )

                from lxml import html as lxml_html
                doc = lxml_html.fromstring(html)

                result = ScrapeResult()
                result.code = scraper.get("name", "stash")
                result.source = "stash_generic"
                result.studio = scraper.get("name", "")

                # 标题
                title_els = doc.xpath(xpath.get("title", "//h1/text()"))
                result.title = title_els[0].strip() if title_els else code

                # 封面
                cover_els = doc.xpath(xpath.get("cover", '//meta[@property="og:image"]/@content'))
                result.cover_url = cover_els[0] if cover_els else ""

                # 发行日期
                date_els = doc.xpath(xpath.get("date", ""))
                if date_els:
                    result.release_date = date_els[0][:10] if len(date_els[0]) > 10 else date_els[0]

                # 演员
                actor_xpath = xpath.get("actors", "")
                if actor_xpath:
                    actor_els = doc.xpath(actor_xpath)
                    result.actors = [
                        ActorInfo(name=a.strip()) for a in actor_els
                        if a.strip()
                    ]

                # 标签
                tag_xpath = xpath.get("tags", "")
                if tag_xpath:
                    tag_els = doc.xpath(tag_xpath)
                    result.genres = [t.strip() for t in tag_els if t.strip()]

                return result

            except ResourceUnavailable:
                # 🔴 必须放行：否则会被下面的 `except Exception` 吞掉并退化成
                #   return None ⇒ 又被 engine 记成「源失败」⇒ 无谓触发熔断。
                raise
            except Exception as e:
                # 真正的网络/解析异常仍走这里：此时该源确实可能有问题，
                # 让它 return None（记录源失败）是合理的。
                logger.debug("stash scrape failed for %s: %s", code, e)
        return None


# ---------------------------------------------------------------------------
# 社区刮削器管理器
# ---------------------------------------------------------------------------


class CommunityScraperManager:
    """CommunityScrapers 社区刮削器管理器。

    扫描 CommunityScrapers 目录，加载所有 YAML 刮削器。
    提供搜索和调用接口。
    """

    def __init__(self, scrapers_path: str | None = None):
        self.path = scrapers_path or str(Path(__file__).parent.parent.parent / ".references" / "GitHub" / "CommunityScrapers-master" / "scrapers")
        self._scrapers: dict[str, dict] = {}
        self._load()

    def _load(self):
        d = Path(self.path)
        if not d.is_dir():
            logger.info("CommunityScrapers not found at: %s", self.path)
            return
        count = 0
        for f in d.rglob("*.yml"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, dict) and data.get("name"):
                    self._scrapers[data["name"].lower()] = data
                    count += 1
            except Exception:
                pass
        logger.info("Loaded %d CommunityScrapers from %s", count, self.path)

    def list_all(self) -> list[dict]:
        return [{"name": k, "url": v.get("url", "")} for k, v in self._scrapers.items()]

    def find(self, keyword: str) -> list[dict]:
        kw = keyword.lower()
        results = []
        for name, data in self._scrapers.items():
            if kw in name or kw in data.get("url", "").lower():
                results.append({"name": data.get("name", name), "url": data.get("url", "")})
        return results

    @property
    def count(self) -> int:
        return len(self._scrapers)


# 全局社区管理器
_scraper_manager: Optional[CommunityScraperManager] = None


def get_community_scrapers() -> CommunityScraperManager:
    global _scraper_manager
    if _scraper_manager is None:
        _scraper_manager = CommunityScraperManager()
    return _scraper_manager
