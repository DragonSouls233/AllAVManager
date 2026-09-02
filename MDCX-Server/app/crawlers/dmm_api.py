"""DMM API 爬取器

来源: https://api.thejavdb.net/v1/movies?q={code}
基于 mdcx-diy 的 DmmApiCrawler 移植到 MDCX 架构。
稳定可靠的第三方 DMM 聚合 API，支持有码番号查询。

================================================================================
参考来源: G:/MDCX/.references/MDCX-Project-Reference/ref22-mdcx-diy/mdcx/crawlers/dmm_api.py
依赖:     无（走 AsyncHttpClient）
================================================================================
"""
import re
import logging
from datetime import date
from typing import Optional

from urllib.parse import quote

from app.crawlers.base import BaseCrawler, ScrapeResult, ActorInfo, CrawlerPriority
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

_JAV_CODE_RE = re.compile(r"^[A-Z]{1,6}-?\d{2,5}", re.IGNORECASE)

_JAV_STUDIO_RE = re.compile(
    r"^(SC-|ABW-|SSIS-|STARS-|HEYZO-|KTR-|IPX-|MUDE-|SIRO|ABP-|ABWP-|EYD-|EXD-|EXLA-|"
    r"GANA-|GEK-|GMKD-|GNM-|HERO-|HIBIT-|HRD-|HSMTL-|IDP-|IDSD-|IPX-|KID-|KS-|KSR-|"
    r"KURA-|LUX-|LUXU-|MCY-|MEYD-|MIDE-|NAC-|NAG-|NICE-|NMKD-|NUM-|NURI-|ONED-|"
    r"PARAD-|PERF-|PK-|PRED-|PR-|PRTL-|QT-|RCR-|SBL-|SC-|SCD-|SD-|SGO-|SHKD-|"
    r"SMBR-|SMSD-|SOH-|SOY-|STAR-|STR-|STARS-|SU-|SWITCH-|TCR-|TDC-|TEK-|TES-|"
    r"TI-|TK-|TKY-|TN-|TOKYO-|TSTR-|TTD-|UMR-|V-|VID-|VR-|VRD-|VRH-|VRK-|VRS-|"
    r"VS-|WAAA-|WAR-|WBD-|WFS-|WOO-|WVR-|XG-|XR-|XXX-)",
    re.IGNORECASE,
)


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return date(*map(int, s.replace("/", "-").replace(".", "-").split("-")[:3]))
        except (ValueError, TypeError):
            continue
    return None


def _with_https(url) -> Optional[str]:
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    elif url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("https://"):
        url = "https://" + url
    return url


def _extract_code_from_title(title: str) -> str:
    title = title.strip().upper()
    for prefix in re.findall(_JAV_STUDIO_RE, title):
        idx = title.upper().index(prefix.upper())
        rest = title[idx + len(prefix):]
        m = re.match(r"(\d{2,5})", rest)
        if m:
            return prefix.upper() + m.group(1)
    m = _JAV_CODE_RE.match(title)
    if m:
        return m.group(0).upper()
    return ""


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


@register_crawler
class DmmApiCrawler(BaseCrawler):
    name = "dmm_api"
    display_name = "DMM API (TheJavDB)"
    base_url = "https://api.thejavdb.net/v1/movies"
    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    description = "DMM 第三方聚合 API（通过 TheJavDB）"
    language = "zh"

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        cleaned = re.sub(r"\s+", "", code).upper()
        safe = quote(cleaned)
        api_url = f"{self.base_url}?q={safe}"
        logger.info("[%s] scraping %s via %s", self.name, cleaned, api_url)

        try:
            async with AsyncHttpClient() as client:
                data = await client.get_json(
                    api_url,
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                    purpose=f"scrape:{cleaned}",
                )
        except Exception as e:
            logger.warning("[%s] request failed for %s: %s", self.name, cleaned, e)
            self.mark_error()
            return None

        if not isinstance(data, dict):
            self.mark_error()
            return None

        movies = data.get("movies") or []
        if not movies:
            self.mark_error()
            return None

        best: Optional[ScrapeResult] = None
        for item in movies:
            result = self._parse_item(item, cleaned)
            if result is not None:
                if best is None or self._is_better(result, best):
                    best = result

        if best is None:
            self.mark_error()
            return None

        self.mark_success()
        return best

    async def search(self, keyword: str) -> list[ScrapeResult]:
        safe = quote(keyword.strip())
        api_url = f"{self.base_url}?q={safe}"
        try:
            async with AsyncHttpClient() as client:
                data = await client.get_json(
                    api_url,
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                    purpose=f"search:{keyword}",
                )
        except Exception as e:
            logger.warning("[%s] search failed: %s", self.name, e)
            return []

        if not isinstance(data, dict):
            return []

        movies = data.get("movies") or []
        results = []
        for item in movies[:10]:
            parsed = self._parse_item(item, "")
            if parsed is not None:
                results.append(parsed)
        return results

    async def health_check(self) -> bool:
        try:
            result = await self.scrape("ABP-617")
            return result is not None and bool(result.title)
        except Exception as e:
            logger.warning("[%s] health check failed: %s", self.name, e)
            return False

    def _parse_item(self, item: dict, fallback_code: str) -> Optional[ScrapeResult]:
        if not isinstance(item, dict):
            return None

        movie_id = item.get("universal_id") or item.get("id")
        if not movie_id:
            return None

        title = item.get("title") or item.get("title_zh") or ""
        title = str(title).strip()

        code = (item.get("series") or "").strip()
        if not code and title:
            code = _extract_code_from_title(title)
        code = code or fallback_code or str(movie_id)

        description = str(item.get("description") or "").strip()
        release_date = _parse_date(item.get("release_date") or "")
        duration_text = item.get("duration")
        duration = None
        if duration_text is not None:
            try:
                duration = int(float(str(duration_text)))
            except (ValueError, TypeError):
                m = re.search(r"\d+", str(duration_text))
                if m:
                    duration = int(m.group())

        full_cover = _with_https(item.get("fullcover_url"))
        front_cover = _with_https(item.get("frontcover_url"))
        cover_url = full_cover or front_cover

        samples = item.get("samples") or []
        sample_urls = [_with_https(str(s)) for s in samples if s]

        genre_names = _clean_list(item.get("genres"))
        actress_names = _clean_list(item.get("actresses"))

        actors = [ActorInfo(name=n) for n in actress_names]

        maker = str(item.get("maker") or "").strip()
        label = str(item.get("label") or "").strip()
        series = str(item.get("series") or "").strip()
        directors = str(item.get("directors") or "").strip()

        studio = maker or label or ""

        result = ScrapeResult(
            code=code,
            title=title,
            source=self.name,
            release_date=release_date,
            duration=duration,
            genres=genre_names,
            tags=genre_names,
            actors=actors,
            cover_url=cover_url,
            poster_url=cover_url,
            studio=studio,
            plot=description,
            sample_images=sample_urls,
        )
        result.raw_data = {
            "directors": directors,
            "label": label,
            "series": series,
            "samples": sample_urls,
            "fullcover_url": full_cover,
            "frontcover_url": front_cover,
        }
        return result

    @staticmethod
    def _is_better(a: ScrapeResult, b: ScrapeResult) -> bool:
        a_samples = len(a.sample_images or [])
        b_samples = len(b.sample_images or [])
        if a_samples != b_samples:
            return a_samples > b_samples
        a_genres = len(a.genres or [])
        b_genres = len(b.genres or [])
        if a_genres != b_genres:
            return a_genres > b_genres
        a_actors = len(a.actors or [])
        b_actors = len(b.actors or [])
        if a_actors != b_actors:
            return a_actors > b_actors
        return len(a.title or "") > len(b.title or "")
