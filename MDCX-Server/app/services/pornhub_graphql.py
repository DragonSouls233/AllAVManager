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
    # 以下为 2026-10-03 按实测返回补充的字段
    sample_images: list[str] = field(default_factory=list)  # 实测 thumbs 列表（样图/剧照）
    segment: dict = field(default_factory=dict)             # 实测 segment 分段信息
    video_id: str = ""                                      # 实测 video_id
    url: str = ""                                            # 实测 url
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

        # ⚠️ 修复(2026-10-03)：以下字段名全部按**实测返回**对齐，旧代码用的是
        # 臆测名（thumbnail/likes/dislikes/is_premium/performers…），实测一个都对不上：
        #   实测 video 对象键 = categories, default_thumb, duration, pornstars,
        #   publish_date, rating, ratings, segment, tags, thumb, thumbs, title, url, video_id, views
        #   另 duration 是 "10:44" 字符串（见 _to_int），rating 是 0-100 浮点（不是 0-5）。
        meta.title = _to_text(data.get("title"))
        meta.description = _to_text(data.get("description"))
        meta.duration = _to_int(data.get("duration"))
        meta.thumbnail = _to_text(data.get("thumb") or data.get("default_thumb"))
        meta.views = _to_int(data.get("views"))
        meta.publish_date = _to_text(data.get("publish_date"))
        meta.date_updated = _to_text(data.get("date_updated"))
        meta.likes = _to_int(data.get("likes"))
        meta.dislikes = _to_int(data.get("dislikes"))
        # 实测 rating = 89.204（0-100 制），转成 0-5 需要 /20
        raw_rating = _to_float(data.get("rating"))
        meta.rating = round(raw_rating / 20.0, 2) if raw_rating > 5 else raw_rating
        meta.video_status = _to_text(data.get("video_status"))
        meta.is_premium = bool(data.get("is_premium") or data.get("premium"))
        meta.is_live = bool(data.get("is_live"))
        meta.is_hd = bool(data.get("is_hd"))
        meta.video_id = _to_text(data.get("video_id"))
        meta.url = _to_text(data.get("url"))

        # tags 实测是 [{'tag_name': 'xxx'}, …]（旧代码按 list[str] 处理 → 拿到 dict 列表）
        tags = data.get("tags") or []
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, dict):
                    name = t.get("tag_name") or t.get("name")
                    if name:
                        meta.tags.append(str(name).strip())
                elif isinstance(t, str):
                    meta.tags.append(t.strip())

        # categories 实测是 [{'category': 'asian'}, …]
        cats = data.get("categories") or []
        if isinstance(cats, list):
            for c_ in cats:
                if isinstance(c_, dict):
                    name = c_.get("category") or c_.get("name")
                    if name:
                        meta.categories.append({"category": str(name).strip()})
                elif isinstance(c_, str):
                    meta.categories.append({"category": c_.strip()})

        # performers 实测键是 pornstars（不是 performers），元素含 name/id
        performers = data.get("pornstars") or data.get("performers") or []
        if isinstance(performers, list):
            for p in performers:
                if isinstance(p, dict):
                    if p.get("name"):
                        meta.performer_names.append(str(p["name"]).strip())
                    pid = p.get("id") or p.get("pornstar_id")
                    if pid:
                        meta.performer_ids.append(str(pid))

        # thumbs 实测是 16 条 dict：{'size':'320x240','width','height','src':...}
        # （旧代码完全没处理）——取 src，按 width*height 降序优先大图
        thumbs = data.get("thumbs") or []
        if isinstance(thumbs, list):
            sized: list[tuple[int, str]] = []
            for t in thumbs:
                if isinstance(t, str) and t:
                    sized.append((0, t))
                elif isinstance(t, dict):
                    src = t.get("src") or t.get("url")
                    if not src:
                        continue
                    try:
                        w = int(t.get("width") or 0)
                        h = int(t.get("height") or 0)
                    except (TypeError, ValueError):
                        w = h = 0
                    sized.append((w * h, str(src)))
            sized.sort(key=lambda x: x[0], reverse=True)
            meta.sample_images = [u for _, u in sized]

        # segment 是分段信息，与 mediaDefinitions 互补
        segment = data.get("segment")
        if isinstance(segment, dict):
            meta.segment = segment

        media_defs = data.get("mediaDefinitions") or data.get("media_definitions") or []
        if isinstance(media_defs, list):
            meta.media_definitions = media_defs
            _build_hls_master(meta)

        return meta

    except Exception as e:
        logger.warning("GraphQL 元数据获取失败 [%s]: %s", viewkey, e)
        return None


def _to_int(value, default: int = 0) -> int:
    """宽松转 int。

    修复(2026-10-03)：实测 ``webmasters/video_by_id`` 返回的 duration 是
    ``"10:44"`` 这种 mm:ss 字符串，原代码直接 ``int(data.get("duration", 0))``
    会抛 ValueError → 被外层 except 吞掉 → **兜底源 100% 静默失效**
    （日志只有一行"invalid literal for int() with base 10"）。
    同理 likes/dislikes 可能缺失或为 None。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return default
    # mm:ss 或 hh:mm:ss → 秒
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return default
        total = 0
        for n in nums:
            total = total * 60 + n
        return total
    try:
        return int(float(s))
    except ValueError:
        return default


def _to_float(value, default: float = 0.0) -> float:
    """宽松转 float（rating 可能是 str）。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


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