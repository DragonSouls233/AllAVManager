"""MissAV API 爬取器（Recombee HMAC 签名）

来源: MissAV 官方推荐的 Recombee API，绕过 Cloudflare。
基于 mdcx-diy 的 MissAvApiCrawler 移植到 MDCX 架构。

================================================================================
参考来源: G:/MDCX/.references/MDCX-Project-Reference/ref22-mdcx-diy/mdcx/crawlers/missav_api.py
依赖:     MissAV Recombee 官方 API key + secret（免费申请）
================================================================================
"""
import re
import hmac
import hashlib
import logging
import time
import os
import base64
from datetime import date
from typing import Optional

from app.crawlers.base import BaseCrawler, ScrapeResult, ActorInfo, CrawlerPriority
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

_API_BASE = "https://client-rapi-missav.recombee.com/webapi"
_API_KEY = os.getenv("MISSAV_RECOMBEE_API_KEY", "58283469-5d23-4ec4-af46-2a922f7c2381")
_API_SECRET = os.getenv("MISSAV_RECOMBEE_API_SECRET", "1f7c59f3-6304-4c76-94e1-d0164748654b")

_NUM_RE = re.compile(r"\d+")


def _sign(method: str, path: str, body: str, api_key: str, api_secret: str) -> str:
    canonical = f"{method.upper()}\n{path}\n{body}"
    signature = hmac.new(
        base64.b64decode(api_secret),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"RDK1 {api_key}:{signature}"


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    try:
        return date(*map(int, s[:10].replace("/", "-").replace(".", "-").split("-")[:3]))
    except (ValueError, TypeError):
        return None


def _clean_list(values) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        return [v.strip() for v in values.split(",") if v.strip()]
    if isinstance(values, list):
        cleaned = []
        for v in values:
            if isinstance(v, str):
                v = v.strip()
                if v:
                    cleaned.append(v)
            else:
                s = str(v).strip()
                if s:
                    cleaned.append(s)
        return cleaned
    return [str(values).strip()]


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


@register_crawler
class MissAvApiCrawler(BaseCrawler):
    name = "missav_api"
    display_name = "MissAV (Recombee API)"
    base_url = "https://missav.ws"
    priority = CrawlerPriority.HIGH
    supported_types = ["jav_uncensored", "jav"]
    description = "MissAV 无码影片 Recombee API（官方绕过 CF 方案）"
    language = "zh"

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        cleaned = re.sub(r"\s+", "", code).upper()
        logger.info("[%s] scraping %s via Recombee API", self.name, cleaned)

        payload = self._build_get_payload(cleaned)
        try:
            async with AsyncHttpClient() as client:
                path = "/predict/item-to-item?returnFields=full_title,title_cn,title_zh,actresses,directors,genres,series,labels,markers,released_at,duration,is_uncensored_leak,cover_id"
                headers = {
                    "Authorization": payload["auth"],
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Request-Timestamp": str(payload["ts"]),
                }
                body = f'{{"itemId":"{cleaned}","algorithm":"recommended-for-movie","numResults":1}}'
                data = await client.post_json(
                    f"{_API_BASE}{path}",
                    data=body,
                    headers=headers,
                    purpose=f"scrape:{cleaned}",
                )
        except Exception as e:
            logger.warning("[%s] request failed for %s: %s", self.name, cleaned, e)
            self.mark_error()
            return None

        if not data:
            self.mark_error()
            return None

        predictions = data.get("predictions") if isinstance(data, dict) else None
        if not predictions or not isinstance(predictions, list):
            self.mark_error()
            return None

        result = self._parse_item(predictions[0], cleaned)
        if result is None:
            self.mark_error()
            return None

        self.mark_success()
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        payload = self._build_get_payload(keyword)
        try:
            async with AsyncHttpClient() as client:
                path = "/predict/item-to-item?returnFields=full_title,title_cn,title_zh,actresses,directors,genres,series,labels,markers,released_at,duration,is_uncensored_leak,cover_id"
                headers = {
                    "Authorization": payload["auth"],
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Request-Timestamp": str(payload["ts"]),
                }
                body = f'{{"itemId":"{keyword}","algorithm":"recommended-for-movie","numResults":10}}'
                data = await client.post_json(
                    f"{_API_BASE}{path}",
                    data=body,
                    headers=headers,
                    purpose=f"search:{keyword}",
                )
        except Exception as e:
            logger.warning("[%s] search failed: %s", self.name, e)
            return []

        if not isinstance(data, dict):
            return []

        predictions = data.get("predictions") or []
        results = []
        for item in predictions:
            parsed = self._parse_item(item, "")
            if parsed is not None:
                results.append(parsed)
        return results

    async def health_check(self) -> bool:
        try:
            test_code = "184-F-0036"
            result = await self.scrape(test_code)
            return result is not None and bool(result.title)
        except Exception as e:
            logger.warning("[%s] health check failed: %s", self.name, e)
            return False

    def _build_get_payload(self, number: str) -> dict:
        ts = int(time.time() * 1000)
        path = "/predict/item-to-item"
        body = f'{{"itemId":"{number}","algorithm":"recommended-for-movie","numResults":1}}'
        auth = _sign("POST", path, body, _API_KEY, _API_SECRET)
        return {"auth": auth, "ts": ts}

    def _parse_item(self, item: dict, fallback_code: str) -> Optional[ScrapeResult]:
        if not isinstance(item, dict):
            return None

        props = item.get("properties") or {}
        if not isinstance(props, dict):
            return None

        full_title = _clean_text(props.get("full_title"))
        title_cn = _clean_text(props.get("title_cn"))
        title_zh = _clean_text(props.get("title_zh"))
        title = full_title or title_cn or title_zh or ""
        if not title and not props.get("cover_id"):
            return None

        code = item.get("itemId") or fallback_code
        if not code:
            code = title.split("  ")[0] if "  " in title else ""
        code = code or fallback_code

        description = _clean_text(props.get("description"))
        release_date = _parse_date(props.get("released_at") or "")
        duration_text = props.get("duration")
        duration = None
        if duration_text is not None:
            try:
                duration = int(float(str(duration_text)))
            except (ValueError, TypeError):
                m = re.search(r"\d+", str(duration_text))
                if m:
                    duration = int(m.group())

        cover_id = props.get("cover_id") or ""
        cover_url = None
        if cover_id:
            for suffix in ("cover-n.jpg", "cover.jpg", "cover-l.jpg"):
                url = f"https://fourhoi.com/{cover_id}/{suffix}"
                if url:
                    cover_url = url
                    break

        genres = _clean_list(props.get("genres"))
        labels = _clean_list(props.get("labels"))
        markers = _clean_list(props.get("markers"))
        all_genres = genres + labels + markers

        actress_names = _clean_list(props.get("actresses"))
        directors_text = _clean_text(props.get("directors"))
        directors = _clean_list(directors_text) if directors_text else []

        actors = [ActorInfo(name=n) for n in actress_names]

        series_text = _clean_text(props.get("series"))
        label_text = _clean_text(props.get("labels"))
        is_uncensored_leak = props.get("is_uncensored_leak")

        uncensored = bool(is_uncensored_leak) if is_uncensored_leak is not None else True

        result = ScrapeResult(
            code=code,
            title=title,
            source=self.name,
            release_date=release_date,
            duration=duration,
            genres=all_genres,
            tags=labels + markers,
            actors=actors,
            directors=directors,
            cover_url=cover_url,
            poster_url=cover_url,
            plot=description,
            is_uncensored=uncensored,
        )
        result.raw_data = {
            "full_title": full_title,
            "title_cn": title_cn,
            "title_zh": title_zh,
            "series": series_text,
            "labels": label_text,
            "cover_id": str(cover_id) if cover_id else "",
            "is_uncensored_leak": is_uncensored_leak,
            "directors": directors_text,
        }
        return result
