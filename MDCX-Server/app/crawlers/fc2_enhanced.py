"""
FC2 增强爬虫 — 多通道搜索 FC2 视频。

通道：
1. dmm.co.jp — 日本最大成人平台，FC2 官方通道
2. fc2ppvdb.com — 原已有，增加筛选
3. sukebei.nyaa.si — 磁力搜索增强
"""

import re
from typing import Optional
from urllib.parse import quote

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.scraper.number import extract_fc2_id
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@register_crawler
class FC2DMMCrawler(BaseCrawler):
    """FC2 + DMM 双通道搜索爬虫。"""

    name = "fc2_enhanced"
    display_name = "FC2 Enhanced"
    base_url = "https://www.fc2.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["fc2"]
    supported_prefixes = ["FC2"]
    description = "FC2 增强搜索（DMM + Sukebei 双通道）"
    language = "ja"
    requires_proxy = True

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        # 🔴 原实现是手写 replace 链且顺序错误：`FC2PPV-1234567` 会得到
        #    `"-1234567"`（孤立的前导横杠，因 `FC2PPV` 排在最后才删），
        #    拼进 `searchstr=-1234567` 必然零结果。改走真相源。
        clean_code = extract_fc2_id(code)
        if not clean_code:
            return None

        # 通道1: DMM 搜索
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                dmm_url = f"https://www.dmm.co.jp/search/=/searchstr={quote(clean_code)}/"
                r = await client.get_text(dmm_url, headers={"User-Agent": _USER_AGENT})
                if r and "FC2" in r:
                    result = self._parse_dmm(r, code, clean_code)
                    # 🔴 DMM 搜索页无精确匹配时 _parse_dmm 也会返回「title=番号」的空壳，
                    #    必须靠 has_content() 拦掉，否则不落到通道 2、还污染熔断器。
                    if result and result.has_content():
                        return result
            except Exception as e:
                logger.debug("fc2 dmm search failed: %s", e)

        # 通道2: Sukebei 磁力搜索
        result = await self._scrape_sukebei(clean_code)
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        results: list[ScrapeResult] = []
        r = await self.scrape(f"FC2-PPV-{keyword}")
        if r:
            results.append(r)
        return results

    async def _scrape_sukebei(self, clean_code: str) -> Optional[ScrapeResult]:
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as client:
            try:
                url = f"https://sukebei.nyaa.si/?q=FC2-PPV-{clean_code}&s=seeders&o=desc"
                r = await client.get_text(url, headers={"User-Agent": _USER_AGENT})
                if not r:
                    return None

                # 🔴 2026-10-04 修复：原实现在这里**无条件**构造并返回 ScrapeResult，
                #    即使搜索页是空的（nyaa 搜不到会渲染 "No results found"）。
                #    后果三重：① 绕过 strategy.py 的 NFO/目录名回退，用空值覆盖库里
                #    正确数据；② engine 记 record_success() + breaker.record_success()
                #    ⇒ 这个坏源**永远不会熔断**；③ 用户看到只有番号的空白条目。
                #    ⇒ 改为：抓不到任何实质内容就返 None（= 诚实的失败）。
                title_m = re.search(r'<a[^>]*href="[^"]*view[^"]*"[^>]*>(.*?)</a>', r, re.DOTALL)
                magnet_m = re.findall(r'href="(magnet:\?xt=urn:btih:[^"]+)"', r)
                if not title_m and not magnet_m:
                    logger.debug("fc2 sukebei 无匹配: %s", clean_code)
                    return None

                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
                # 标题就是番号的视同无内容（磁力命中时也只靠 magnets 算有效）
                if not title or title.upper() == f"FC2-PPV-{clean_code}":
                    title = f"FC2-PPV-{clean_code}"

                result = ScrapeResult(
                    code=f"FC2-PPV-{clean_code}",
                    title=title,
                    source="fc2_enhanced",
                    studio="FC2",
                )
                # 提取磁力链接（存入raw_data["magnets"]，NFO生成器从此读取）
                result.raw_data["magnets"] = magnet_m[:3]
                return result
            except Exception as e:
                logger.debug("fc2 sukebei search failed: %s", e)
        return None

    def _parse_dmm(self, html: str, code: str, clean_code: str) -> Optional[ScrapeResult]:
        result = ScrapeResult(code=code.upper(), title=code.upper(), source="fc2_enhanced")
        result.code = code.upper()
        result.source = "fc2_enhanced"
        result.studio = "FC2"

        title_m = re.search(r'<title>(.*?)</title>', html)
        result.title = title_m.group(1).strip() if title_m else code

        cover_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if cover_m:
            result.cover_url = cover_m.group(1)

        actors_m = re.findall(r'<a[^>]*href="[^"]*actor[^"]*"[^>]*>(.*?)</a>', html)
        result.actors = [ActorInfo(name=a.strip()) for a in actors_m if a.strip() and len(a.strip()) < 30]

        return result
