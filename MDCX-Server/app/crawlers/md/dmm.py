"""
DMM/FANZA 爬虫 - 从 MDCX 迁移

使用 DMM GraphQL API 获取数据。
支持：FANZA TV、DMM TV、DIGITAL（PPV）等多种内容类型。

原始文件: dmm_new/__init__.py, dmm_new/tv.py, dmm_new/parsers.py
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

# DMM GraphQL API 端点
FANZA_API_URL = "https://api.fanza.xyz/graphql"
DMM_API_URL = "https://api.dmm.com/graphql"


def _extract_cid(number: str) -> str:
    """从番号中提取 DMM content_id"""
    # 番号格式: SSIS-001 -> ssis001
    clean = number.replace("-", "").replace(" ", "").lower()
    return clean


def _build_fanza_payload(cid: str) -> dict:
    """构建 FANZA TV GraphQL 查询"""
    return {
        "operationName": "FetchFanzaTvPlusContent",
        "variables": {
            "id": cid,
            "device": "BROWSER",
            "isLoggedIn": False,
            "isForeign": False,
            "playDevice": "BROWSER",
            "withResume": False,
        },
        "query": """
query FetchFanzaTvPlusContent($id: ID!, $device: Device!, $isLoggedIn: Boolean!, $playDevice: PlayDevice!, $withResume: Boolean!, $isForeign: Boolean) {
  fanzaTvPlus(device: $device) {
    content(id: $id, isForeign: $isForeign) {
      title
      description(format: HTML)
      packageImage
      packageLargeImage
      sampleMovie { url thumbnail }
      samplePictures { imageLarge }
      actresses { name }
      directors { name }
      series { name }
      maker { name }
      label { name }
      genres { name }
      reviewSummary { averagePoint }
      playInfo { duration }
    }
  }
}
""",
    }


def _build_digital_payload(content_id: str) -> dict:
    """构建 DIGITAL (PPV) GraphQL 查询"""
    return {
        "operationName": "MDCxDigitalContent",
        "variables": {"id": content_id},
        "query": """
query MDCxDigitalContent($id: ID!) {
  ppvContent(id: $id) {
    title
    description
    packageImage { largeUrl mediumUrl }
    sampleImages { largeImageUrl }
    sample2DMovie { highestMovieUrl }
    deliveryStartDate
    makerReleasedAt
    duration
    actresses { name }
    directors { name }
    series { name }
    maker { name }
    label { name }
    genres { name }
  }
  reviewSummary(contentId: $id) { average }
}
""",
    }


def _parse_fanza_response(data: dict) -> Optional[dict]:
    """解析 FANZA TV API 响应"""
    try:
        content = data.get("fanzaTvPlus", {}).get("content")
        if not content or not content.get("title"):
            return None

        title = content.get("title", "")
        actors = [a["name"] for a in (content.get("actresses") or []) if a and a.get("name")]
        genres = [g["name"] for g in (content.get("genres") or []) if g and g.get("name")]
        directors = [d["name"] for d in (content.get("directors") or []) if d and d.get("name")]

        # 封面
        cover = content.get("packageLargeImage") or content.get("packageImage")

        # 样图
        samples = []
        for sp in (content.get("samplePictures") or []):
            if sp and sp.get("imageLarge"):
                samples.append(sp["imageLarge"])

        # 预告片
        trailer = ""
        sample_movie = content.get("sampleMovie")
        if sample_movie and sample_movie.get("url"):
            trailer = sample_movie["url"]
            # 转换 hls 到 mp4
            cid_match = re.search(r"/([^/]+)/playlist\.m3u8", trailer)
            if cid_match:
                cid = cid_match.group(1)
                trailer = trailer.replace("playlist.m3u8", cid + "_sm_w.mp4")

        # 时长
        duration = None
        play_info = content.get("playInfo")
        if play_info and play_info.get("duration"):
            duration = play_info["duration"] // 60

        # 评分
        rating = None
        review = content.get("reviewSummary")
        if review and review.get("averagePoint"):
            rating = float(review["averagePoint"])

        return {
            "title": title,
            "outline": content.get("description", ""),
            "actor": ",".join(actors),
            "tag": ",".join(genres),
            "cover": cover,
            "thumb": content.get("packageImage"),
            "extrafanart": samples,
            "trailer": trailer,
            "runtime": str(duration) if duration else "",
            "score": str(rating) if rating else "",
            "series": (content.get("series") or {}).get("name", ""),
            "studio": (content.get("maker") or {}).get("name", ""),
            "publisher": (content.get("label") or {}).get("name", ""),
            "director": ",".join(directors),
        }
    except Exception as e:
        logger.error(f"Parse FANZA response error: {e}")
        return None


def _parse_digital_response(data: dict) -> Optional[dict]:
    """解析 DIGITAL (PPV) API 响应"""
    try:
        content = data.get("ppvContent")
        if not content or not content.get("title"):
            return None

        title = content.get("title", "")
        actors = [a["name"] for a in (content.get("actresses") or []) if a and a.get("name")]
        genres = [g["name"] for g in (content.get("genres") or []) if g and g.get("name")]
        directors = [d["name"] for d in (content.get("directors") or []) if d and d.get("name")]

        # 封面
        pkg_image = content.get("packageImage") or {}
        cover = pkg_image.get("largeUrl") or pkg_image.get("mediumUrl")

        # 样图
        samples = []
        for si in (content.get("sampleImages") or []):
            if si and si.get("largeImageUrl"):
                samples.append(si["largeImageUrl"])

        # 预告片
        trailer = ""
        movie = content.get("sample2DMovie")
        if movie:
            trailer = movie.get("highestMovieUrl") or ""

        # 时长
        duration = content.get("duration")

        # 评分
        rating = None
        review = data.get("reviewSummary")
        if review and review.get("average"):
            rating = float(review["average"])

        return {
            "title": title,
            "outline": content.get("description", ""),
            "actor": ",".join(actors),
            "tag": ",".join(genres),
            "cover": cover,
            "extrafanart": samples,
            "trailer": trailer,
            "runtime": str(duration) if duration else "",
            "score": str(rating) if rating else "",
            "series": (content.get("series") or {}).get("name", ""),
            "studio": (content.get("maker") or {}).get("name", ""),
            "publisher": (content.get("label") or {}).get("name", ""),
            "director": ",".join(directors),
            "release": content.get("deliveryStartDate") or content.get("makerReleasedAt", ""),
        }
    except Exception as e:
        logger.error(f"Parse digital response error: {e}")
        return None


@register_crawler
class DmmCrawler(BaseCrawler):
    """DMM/FANZA 爬虫"""

    name = "dmm"
    display_name = "DMM/FANZA"
    base_url = "https://www.dmm.co.jp"
    priority = CrawlerPriority.HIGH
    supported_types = ["jav"]
    supported_prefixes = []
    description = "DMM/FANZA 官方数据源，支持多种内容类型"
    language = "ja"
    requires_proxy = False

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """刮削指定番号"""
        cid = _extract_cid(code)

        async with AsyncHttpClient() as client:
            try:
                # 1. 尝试 FANZA TV API
                result = await self._try_fanza_api(client, cid)
                if result:
                    return self._build_result(result, code)

                # 2. 尝试 DIGITAL (PPV) API
                result = await self._try_digital_api(client, cid)
                if result:
                    return self._build_result(result, code)

                logger.info(f"DMM no result for {code}")
                return None

            except Exception as e:
                logger.error(f"DMM scrape error for {code}: {e}")
                return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return []

    async def _try_fanza_api(self, client: AsyncHttpClient, cid: str) -> Optional[dict]:
        """尝试 FANZA TV API"""
        payload = _build_fanza_payload(cid)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as hclient:
                resp = await hclient.post(
                    FANZA_API_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    result = _parse_fanza_response(data)
                    if result and result.get("title"):
                        return result
        except Exception as e:
            logger.debug(f"FANZA API failed: {e}")
        return None

    async def _try_digital_api(self, client: AsyncHttpClient, cid: str) -> Optional[dict]:
        """尝试 DIGITAL (PPV) API"""
        payload = _build_digital_payload(cid)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as hclient:
                resp = await hclient.post(
                    DMM_API_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    result = _parse_digital_response(data)
                    if result and result.get("title"):
                        return result
        except Exception as e:
            logger.debug(f"DIGITAL API failed: {e}")
        return None

    def _build_result(self, data: dict, code: str) -> ScrapeResult:
        """构建 ScrapeResult"""
        # 解析演员
        actors = []
        actor_str = data.get("actor", "")
        if actor_str:
            for name in actor_str.split(","):
                name = name.strip()
                if name:
                    actors.append(ActorInfo(name=name))

        # 解析标签
        genres = []
        tag_str = data.get("tag", "")
        if tag_str:
            genres = [t.strip() for t in tag_str.split(",") if t.strip()]

        # 解析发行日期
        release_date = None
        release = data.get("release", "")
        if release:
            if m := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", release):
                try:
                    release_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pass

        # 解析时长
        duration = None
        runtime = data.get("runtime", "")
        if runtime:
            try:
                duration = int(runtime)
            except (ValueError, TypeError):
                pass

        # 解析评分
        rating = None
        score = data.get("score", "")
        if score:
            try:
                rating = float(score)
            except (ValueError, TypeError):
                pass

        return ScrapeResult(
            code=code,
            title=data.get("title", code),
            source=self.name,
            studio=data.get("studio"),
            maker=data.get("publisher"),
            series=data.get("series"),
            release_date=release_date,
            duration=duration,
            plot=data.get("outline", ""),
            genres=genres,
            actors=actors,
            cover_url=data.get("cover") or data.get("thumb"),
            poster_url=data.get("thumb"),
            trailer_url=data.get("trailer"),
            sample_images=data.get("extrafanart", []),
            rating=rating,
        )
