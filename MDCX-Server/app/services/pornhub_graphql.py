"""
PORNHub GraphQL API 客户端

调用 Pornhub 公开 GraphQL 端点获取视频元数据：
  https://www.pornhub.com/webmasters/video_by_id?id={viewkey}

返回结构化 JSON：duration, thumbnail, title, views, publish_date,
categories, tags, mediaDefinitions 等。

不依赖 unofficial-api-for-pornhub（AGPLv3），直接调用公开端点。
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

PH_GRAPHQL_URL = "https://www.pornhub.com/webmasters/video_by_id"


@dataclass
class PHVideoMeta:
    viewkey: str
    title: str = ""
    description: str = ""
    duration: int = 0
    thumbnail: str = ""
    views: int = 0
    publish_date: str = ""
    date_updated: str = ""
    likes: int = 0
    dislikes: int = 0
    rating: float = 0.0
    video_status: str = ""
    is_premium: bool = False
    tags: list[str] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    performer_names: list[str] = field(default_factory=list)
    performer_ids: list[str] = field(default_factory=list)
    media_definitions: list[dict] = field(default_factory=list)
    hls_master: Optional[str] = None
    is_live: bool = False
    is_hd: bool = False
    raw_response: dict = field(default_factory=dict)


async def fetch_video_metadata(viewkey: str) -> Optional[PHVideoMeta]:
    try:
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()
        client = AsyncHttpClient(proxy=proxy_url, timeout=30, max_retries=2)

        url = f"{PH_GRAPHQL_URL}?id={viewkey}"
        resp = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"https://www.pornhub.com/view_video.php?viewkey={viewkey}",
            },
            timeout=30,
        )

        if not resp or resp.status_code != 200:
            logger.debug("GraphQL 请求失败 [%s]: HTTP %s", viewkey, resp.status_code if resp else "None")
            return None

        data = _parse_graphql_response(resp.text)
        if not data:
            return None

        meta = PHVideoMeta(viewkey=viewkey, raw_response=data)

        meta.title = str(data.get("title", ""))
        meta.description = str(data.get("description", ""))
        meta.duration = int(data.get("duration", 0))
        meta.thumbnail = str(data.get("thumbnail", ""))
        meta.views = int(data.get("views", 0))
        meta.publish_date = str(data.get("publish_date", ""))
        meta.date_updated = str(data.get("date_updated", ""))
        meta.likes = int(data.get("likes", 0))
        meta.dislikes = int(data.get("dislikes", 0))
        meta.rating = float(data.get("rating", 0.0))
        meta.video_status = str(data.get("video_status", ""))
        meta.is_premium = bool(data.get("is_premium", False))
        meta.is_live = bool(data.get("is_live", False))
        meta.is_hd = bool(data.get("is_hd", False))

        tags = data.get("tags") or []
        if isinstance(tags, list):
            meta.tags = [str(t) for t in tags]

        cats = data.get("categories") or []
        if isinstance(cats, list):
            meta.categories = cats

        performers = data.get("performers") or data.get("pornstars") or []
        if isinstance(performers, list):
            for p in performers:
                if isinstance(p, dict):
                    if p.get("name"):
                        meta.performer_names.append(str(p["name"]))
                    if p.get("id") or p.get("pornstar_id"):
                        meta.performer_ids.append(str(p.get("id") or p.get("pornstar_id", "")))

        media_defs = data.get("mediaDefinitions") or data.get("media_definitions") or []
        if isinstance(media_defs, list):
            meta.media_definitions = media_defs
            _build_hls_master(meta)

        return meta

    except Exception as e:
        logger.warning("GraphQL 元数据获取失败 [%s]: %s", viewkey, e)
        return None


def _parse_graphql_response(text: str) -> Optional[dict]:
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "video" in data:
            return data["video"]
        if isinstance(data, dict) and "data" in data:
            inner = data["data"]
            if isinstance(inner, dict):
                if "video" in inner:
                    return inner["video"]
                return inner
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def _build_hls_master(meta: PHVideoMeta) -> None:
    hls_urls: list[dict] = []
    for md in meta.media_definitions:
        if not isinstance(md, dict):
            continue
        url = md.get("url", "")
        if not url or not isinstance(url, str):
            continue
        url_lower = url.lower()
        if not url_lower.startswith(("http://", "https://")):
            continue
        if ".m3u8" in url_lower or ".mpd" in url_lower or "hls" in url_lower or "dash" in url_lower:
            entry = {
                "url": url,
                "height": md.get("height") or md.get("filesize"),
                "type": md.get("has_video") or md.get("ext") or md.get("type"),
                "quality": md.get("quality") or md.get("quality_label"),
            }
            if ".m3u8" in url_lower or "hls" in url_lower:
                entry["format"] = "hls"
            elif ".mpd" in url_lower or "dash" in url_lower:
                entry["format"] = "dash"
            else:
                entry["format"] = "hls"
            hls_urls.append(entry)

    if hls_urls:
        meta.hls_master = hls_urls
    else:
        meta.hls_master = None


async def fetch_video_search(query: str, page: int = 1) -> Optional[dict]:
    try:
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()
        client = AsyncHttpClient(proxy=proxy_url, timeout=30, max_retries=2)

        search_url = f"https://www.pornhub.com/video/search?search={query}&page={page}"
        resp = await client.get(
            search_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30,
        )

        if not resp or resp.status_code != 200:
            return None

        html = resp.text
        try:
            import re
            flash_match = re.search(
                r'flashvars\s*=\s*JSON\.parse\(["\'](.*?)["\']\)',
                html, re.DOTALL
            )
            if flash_match:
                parsed = json.loads(flash_match.group(1).replace('\\"', '"'))
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass

        return {"html": html}
    except Exception as e:
        logger.warning("视频搜索失败 [%s]: %s", query, e)
        return None


async def download_video(viewkey: str, quality: str = "auto", output_path: str = "") -> Optional[str]:
    meta = await fetch_video_metadata(viewkey)
    if not meta or not meta.hls_master:
        logger.warning("下载失败: 无可用 m3u8 链接 [%s]", viewkey)
        return None

    urls = meta.hls_master
    target = None
    if quality != "auto":
        for u in urls:
            h = str(u.get("height", ""))
            if h == quality:
                target = u
                break

    if not target:
        target = urls[0]

    m3u8_url = target["url"]
    logger.info("开始下载 [%s] m3u8: %s", viewkey, m3u8_url[:80])

    if not output_path:
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', meta.title)[:100]
        output_path = f"{safe_title} [{viewkey}].mp4"

    try:
        from app.services.proxy_manager import get_effective_proxy_url
        proxy_url = get_effective_proxy_url()
        client = AsyncHttpClient(proxy=proxy_url, timeout=120, max_retries=1)

        resp = await client.get(m3u8_url, timeout=120)
        if resp and resp.status_code == 200:
            if m3u8_url.endswith(".ts"):
                import pathlib
                pathlib.Path(output_path).write_bytes(resp.content)
            else:
                import pathlib
                ts_ext = m3u8_url.rsplit(".", 1)[-1] if "." in m3u8_url else "txt"
                safe_name = f"{viewkey}.playlist.{ts_ext}"
                pathlib.Path(output_path).write_text(resp.text, encoding="utf-8")
                return output_path
            return output_path
    except Exception as e:
        logger.warning("视频下载失败 [%s]: %s", viewkey, e)

    return None