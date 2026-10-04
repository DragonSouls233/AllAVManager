"""PORNHUB 兜底刮削源（官方 webmasters JSON 接口）

## 为什么需要这个源

PORNHUB 模块原先只有 `pornhub` 一个爬虫（HTML 解析路线），且：
- 模块隔离（`provider.py:25`）下无任何 fallback 池
- 一旦被 Cloudflare / JS Challenge 拦住，整批补刮全灭

本源走官方 `webmasters/video_by_id` JSON 端点，**不解析 HTML、不碰 JS Challenge**，
作为 HTML 主源失败后的兜底。它同时是 PH 模块唯一一个能提供 **样图（thumbs，16 张）**
和 **评分（rating，0-100 制）** 的来源。

## 2026-10-03 修复记录（该服务此前一直静默失效）

`app/services/pornhub_graphql.py` 的 `fetch_video_metadata()` 存在三处致命错误，
使它 100% 抛异常后被 `except` 吞掉，只在日志留一行 `invalid literal for int()`：

1. **`int(duration)` 崩溃** —— 实测 duration 返回 `"10:44"` 的 mm:ss 字符串，
   不是整数。直接 `int()` 抛 ValueError。
2. **字段名全是臆测的** —— 旧代码读 `thumbnail` / `likes` / `dislikes` /
   `is_premium` / `performers` / `mediaDefinitions`，而实测 `video` 对象的键是：
   `categories, default_thumb, duration, pornstars, publish_date, rating,
   ratings, segment, tags, thumb, thumbs, title, url, video_id, views`
   → 逐个字段都取不到值（全都 None）。
3. **tags/categories 结构判断错** —— 实测是 `[{'tag_name': 'x'}]` /
   `[{'category': 'x'}]`，旧代码按 `list[str]` 处理，拿到 dict 后 `str()` 成
   `"{'tag_name': 'colombia'}"` 这种脏值。

修完实测 3/3 可用，duration/rating/tags/categories/sample_images 全部正确。
"""

from typing import Optional

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.logger import get_logger


def _as_int(val) -> Optional[int]:
    """宽松转 int（PH 返回的评分人数等可能是 str/None/float）。"""
    try:
        n = int(float(val))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None

logger = get_logger(__name__)


@register_crawler
class PornhubApiCrawler(BaseCrawler):
    """PORNHUB 官方 JSON 接口兜底源"""

    name = "pornhub_api"
    display_name = "PORNHub API"
    base_url = "https://www.pornhub.com"
    priority = CrawlerPriority.LOW  # 兜底源，HTML 主源优先
    supported_types = ["pornhub"]
    supported_prefixes = ["ph"]
    requires_proxy = False

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        from app.scraper.number import normalize_ph_viewkey
        from app.services.pornhub_graphql import fetch_video_metadata

        viewkey = normalize_ph_viewkey(code)
        if not viewkey:
            logger.warning(f"[pornhub_api] 无效的 viewkey: {str(code)[:60]}")
            return None

        meta = await fetch_video_metadata(viewkey)
        if not meta or not meta.title:
            logger.debug(f"[pornhub_api] 元数据为空: {viewkey}")
            return None

        # 实测 pornstars 常为空列表（PH 的 webmasters 接口不返回演员明细），
        # 演员仍留空交给 HTML 主源补，不臆造。
        actors = [ActorInfo(name=n) for n in meta.performer_names if n]

        result = ScrapeResult(
            code=viewkey,
            title=meta.title,
            source=self.name,
            source_url=f"{self.base_url}/view_video.php?viewkey={viewkey}",
            plot=meta.description or None,
            duration=(meta.duration // 60) if meta.duration else None,  # 秒 → 分钟
            cover_url=meta.thumbnail or None,
            sample_images=list(meta.sample_images),
            extrafanart=[],  # 与 sample_images 同源，避免重复下载
            genres=list(meta.categories and [c["category"] for c in meta.categories if c.get("category")]),
            tags=list(meta.tags),
            actors=actors,
            rating=(meta.rating * 2) if meta.rating else None,  # 0-5 → ScrapeResult 期望 0-10
            votes=_as_int(meta.raw_response.get("ratings")),  # 实测 ratings=评分人数
            raw_data={
                "viewkey": viewkey,
                "ph_views": meta.views,
                "ph_publish_date": meta.publish_date,
                "ph_is_premium": meta.is_premium,
                "ph_is_hd": meta.is_hd,
                "ph_categories": meta.categories,
                "ph_segment": meta.segment,
                "ph_video_id": meta.video_id,
                # ---- 供 _scrape_missing 提取、写入 pornhub 表专属列 ----
                # 实测 3/3 样本：rating=89.183（0-100 制）、ratings=2191（人数）、
                # likes=None、uploader=None ⇒ 这两个字段该端点根本不返回，
                # PHVideoMeta.likes 会退化成默认 0（伪数据），故**不放入 raw_data**。
                "ph_rating": meta.rating,
            },
        )
        logger.info(
            f"[pornhub_api] 刮削成功 [{viewkey}] dur={result.duration}min "
            f"tags={len(meta.tags)} samples={len(meta.sample_images)}"
        )
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """按关键字搜索。

        ⚠️ 与 HTML 主源不同，这里**不做全站关键词搜索**：
        PH 的 `video/search` 是 HTML 页面且有 JS 挑战，抓 HTML 就等于放弃本源的
        "纯 JSON、不受 CF 拦截" 的设计初衷（那正是它作为兜底源存在的意义）。

        实测的合理用法是：调用方（`pornhub.search`）已经能拿到 viewkey
        （例如从演员页 / 视频列表页解析），此时只需要换 JSON 端点补齐元数据。
        所以这里只支持"输入即 viewkey"的直查模式。
        """
        from app.scraper.number import normalize_ph_viewkey

        viewkey = normalize_ph_viewkey(keyword)
        if not viewkey:
            logger.debug(f"[pornhub_api] search 关键词非 viewkey，跳过: {str(keyword)[:60]}")
            return []
        result = await self.scrape(viewkey)
        return [result] if result else []
