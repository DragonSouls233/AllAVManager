"""
TheJavDB 开放 API 爬虫（https://api.thejavdb.net/v1）

第三方开放 JSON API，无需 Cookie / 登录 Token，天然绕过 javdb.com 的 Cloudflare。
作为 javdb / javdb_new（App API 通道）之外的补充通道：同一番号多通道冗余，
某条通道失效时仍能刮削到元数据。

来源: Kesuy/mdcx ref42 mdcx/crawlers/javdbapi.py
- 字段映射对齐 JavdbApiMovie（extra="ignore" 容忍服务端新增字段）
- 详情页链接 source_url 作为 external_id 使用

================================================================================
⚠️ TheJavDB API 来源与版本追踪（更新前必读）=====================================
在线参考:   https://api.thejavdb.net/v1/movies?q={番号}
本地参考:   G:/MDCX/.references/MDCX-Project-Reference/ref42-Kesuy-mdcx/mdcx/crawlers/javdbapi.py
依赖:       无（走 AsyncHttpClient 内置指纹，无需额外 Cookie）
失效信号:   HTTP 非 200 / 响应 JSON 缺 title 且缺 fullcover_url / 请求持续超时
替代方案:   javdb.py（App API 匿名通道）或 javdb_new.py（同 App API）
================================================================================
"""
from __future__ import annotations

import html as html_utils
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import urlencode

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

API_BASE = "https://api.thejavdb.net/v1"

# 维护元数据：给后续更新/排障用的集中入口（单点修改）
JAVDBAPI_META = {
    "source_repo": "Kesuy/mdcx (ref42)",
    "source_file": "mdcx/crawlers/javdbapi.py",
    "api_base": API_BASE,
    "auth": "无（开放 API，免 Cookie）",
    "deprecated_after": None,
    "check_command_hint":
        "python -c \"import asyncio; from app.crawlers.javdbapi import JavdbApiCrawler;"
        "c=JavdbApiCrawler(); r=asyncio.run(c.scrape('SSIS-344')); print(r.title if r else None)\"",
}


def _clean_text(value) -> str:
    """HTML 反转义 + <br>/<p> 转换行 + 去标签 + 压缩连续换行。"""
    text = html_utils.unescape(str(value or "").strip())
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_list(values) -> list[str]:
    """去重清理列表。"""
    return list(dict.fromkeys(item for value in (values or []) if (item := _clean_text(value))))


def _parse_date(s: str) -> Optional[date]:
    """解析发行日期（YYYY-MM-DD / YYYY/MM/DD 等）。"""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return date(*map(int, s.replace("/", "-").replace(".", "-").split("-")[:3]))
        except (ValueError, TypeError):
            continue
    return None


@register_crawler
class JavdbApiCrawler(BaseCrawler):
    """TheJavDB 开放 API 爬虫（免登录、绕过 Cloudflare）。"""

    name = "javdbapi"
    display_name = "TheJavDB (API)"
    base_url = API_BASE

    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "TheJavDB 第三方开放 JSON API（免 Cookie 绕 CF）"
    language = "zh"

    def _api_url(self, number: str) -> str:
        return f"{self.base_url}/movies?{urlencode({'q': number})}"

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        """刮削指定番号（通过 thejavdb.net 开放 API）。"""
        code = (code or "").strip()
        if not code:
            return None

        try:
            async with AsyncHttpClient() as client:
                api_url = self._api_url(code)
                logger.debug(f"TheJavDB API URL: {api_url}")
                data = await client.get_json(
                    api_url, headers={"Accept": "application/json"}, purpose="api"
                )
        except Exception as e:
            logger.warning(f"TheJavDB API 请求失败 {code}: {e}")
            self.mark_error()
            return None

        if not isinstance(data, dict):
            self.mark_error()
            return None

        result = self._to_scrape_result(data, fallback_number=code)
        if result is None or (not result.title and not result.cover_url):
            logger.debug(f"TheJavDB API {code}: 未找到或无内容")
            self.mark_error()
            return None

        self.mark_success()
        return result

    def _to_scrape_result(self, data: dict, *, fallback_number: str) -> Optional[ScrapeResult]:
        """将 API 响应映射为 ScrapeResult（对齐 JavdbApiMovie 字段）。"""
        title = _clean_text(data.get("title"))
        if not title and not data.get("fullcover_url"):
            return None

        source_url = _clean_text(data.get("source_url"))
        number = _clean_text(data.get("universal_id")) or fallback_number

        actors = []
        for name in _clean_list(data.get("actresses")):
            actors.append(ActorInfo(name=name))

        runtime_raw = data.get("duration")
        duration = None
        if isinstance(runtime_raw, int):
            duration = runtime_raw if runtime_raw > 0 else None
        elif isinstance(runtime_raw, str):
            if matched := re.search(r"\d+", runtime_raw):
                duration = int(matched.group())

        return ScrapeResult(
            code=number,
            title=title,
            original_title=title,
            source=self.name,
            source_url=source_url or None,
            plot=_clean_text(data.get("description")),
            studio=_clean_text(data.get("maker")),
            maker=_clean_text(data.get("label")),
            label=_clean_text(data.get("label")),
            series=_clean_text(data.get("series")),
            release_date=_parse_date(data.get("release_date")),
            duration=duration,
            genres=_clean_list(data.get("genres")),
            tags=_clean_list(data.get("genres")),
            actors=actors,
            all_actors=_clean_list(data.get("actresses")),
            directors=_clean_list(data.get("directors")),
            is_mosaic=True,
            cover_url=_with_https(data.get("fullcover_url")) or None,
            poster_url=_with_https(data.get("frontcover_url")) or None,
            trailer_url=_with_https(data.get("sample_movie_url")) or None,
            extrafanart=[_with_https(u) for u in (data.get("samples") or []) if u],
            raw_data=dict(data),
            confidence=0.9,
            is_exact_match=True,
        )

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """TheJavDB API 不支持列表搜索，返回空。"""
        return []


def _with_https(url) -> str:
    """补全 https:// 前缀（保留原始值，否则返回空串）。"""
    if not url:
        return ""
    text = str(url).strip()
    if text.startswith("//"):
        return "https:" + text
    return text
