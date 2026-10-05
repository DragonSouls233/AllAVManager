"""
DMM/FANZA 爬虫（GraphQL 官方接口）

2026-10-05 实测重写历史
----------------------
旧实现（静态 xpath + 失效的 api.fanza.xyz GraphQL）**实测 0 命中**，根因三条：

1. `www.dmm.co.jp/digital/videoa/-/detail/=/cid=xxx` 已整体迁移到
   `video.dmm.co.jp`，静态 HTML 是纯客户端渲染的空壳（实测 len=28361，
   `__NEXT_DATA__`/`window.`/`出演者` 计数全为 0）。
2. 年龄认证是**路径形态且必须带绝对 URL**：
   `https://www.dmm.co.jp/age_check/=/declared=yes/?rurl=<绝对URL>`
   带绝对 URL 才会真正下发 `age_check_done=1` cookie 并落到目标页；
   拼站内相对路径（`.../rurl/digital/...`）会被甩到 `fanza.jp/top/` 首页。
3. `api.fanza.xyz` DNS 已失效；`api.dmm.com` 域名还在但**全站 404**
   （`/graphql` 也返回 `{"result":{"status":404,"message":"NOT FOUND"}}`）。

现行可用端点（实测确认）
------------------------
`https://api.video.dmm.co.jp/graphql` —— 官方现行 GraphQL，真实返回数据。

**番号 → id 规则（实测 6/6 真实番号命中）**::

    ABC-123  ->  abc00123      （前缀小写 + 数字零填充至 5 位）

对照组验证有效性：虚构番号 `ABC-123`/`ZZZ-999` 正确返回 ``ppvContent: null``，
说明命中不是假阳性，而是真的按此规则索引。

注意：id 前缀是**厂牌罗马字**，与番号前缀并非总是一致（如 ABP-128 实际落在
`abpn00012` 这类 id 上，因为 AV OPEN 厂的 DMM id 前缀是 abpn）。因此本爬虫
以番号规则拼 id 直取，取不到即视为该站未收录，**不再**做全文检索回退。

字段注意事项（都是实测踩出来的）
--------------------------------
* 评分在**顶层** `reviewSummary(contentId:)`，**不在** ppvContent 内
  （`ppvContent.review` / `reviewSummary` 字段均不存在，会 422）。
* 发行日字段是 `makerReleasedAt`（没有 `releaseDate` / `releasedAt`）。
* 导演是复数 `directors`（单数 `director` 不存在）。
* 厂牌是 `maker`（`studio` 不存在）。
* `duration` 是**秒**，需 /60 转分钟（契约=分钟）。
* `genres` 里有大量通用标签（独占配信/ハイビジョン），全量带走。
"""

import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

#: 官方现行 GraphQL 端点（旧的 api.fanza.xyz / api.dmm.com 均已失效）
GRAPHQL_URL = "https://api.video.dmm.co.jp/graphql"

#: 官方详情页查询（operationName 与官网 JS 中的 ContentPageData 一致）。
#: 评分走顶层 reviewSummary —— 这是唯一能取到评分的写法。
CONTENT_QUERY = """
query ContentPageData($id: ID!) {
  ppvContent(id: $id) {
    id
    title
    duration
    makerReleasedAt
    packageImage { largeUrl }
    actresses { id name }
    maker { id name }
    series { name }
    label { name }
    directors { name }
    genres { id name }
    sampleImages { number largeImageUrl }
    sample2DMovie { highestMovieUrl }
  }
  reviewSummary(contentId: $id) {
    average
    total
  }
}
"""

#: 官方检索查询：queryWord 是 legacySearchPPV 的**顶层参数**（不是 filter 字段）。
#: 实测能搜日文标题/厂牌，但**番号不被索引**（`ABP-128` 搜不到），
#: 故仅用于「按标题/厂牌补充检索」，不作为番号定位手段。
SEARCH_QUERY = """
query AvSearch($limit: Int!, $queryWord: String) {
  legacySearchPPV(limit: $limit, sort: RELEASE_DATE, queryWord: $queryWord) {
    result {
      contents { id title maker { name } }
    }
  }
}
"""

_GRAPHQL_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://video.dmm.co.jp",
    "Referer": "https://video.dmm.co.jp/",
}


def number_to_content_id(number: str) -> Optional[str]:
    """番号 → DMM content_id。

    规则（实测 6/6 真实番号命中，虚构番号正确返回 None 语义）：
    ``ABC-123`` -> ``abc00123``。

    🔴 这与旧实现的 ``_convert_to_cid`` 形似但**不是同一套东西**：旧函数把
    数字也当字符串处理且对 ``h-`` 前缀做 ``h_`` 替换，在现行 GraphQL 上
    因为 id 体系已变（厂牌罗马字前缀）而全部返回 null。
    """
    if not number:
        return None
    n = str(number).strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    m = re.match(r"^([A-Z]+)(\d+)$", n)
    if not m:
        return None
    return m.group(1).lower() + m.group(2).zfill(5)


def _parse_release_date(raw: Optional[str]) -> Optional[date]:
    """``makerReleasedAt`` → date。

    实测形如 ``2024-08-04T15:00:00Z``（UTC 午夜 JST 前一日），
    直接取日期部分即可，不要做时区换算。
    """
    if not raw:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(raw))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@register_crawler
class DmmWebCrawler(BaseCrawler):
    """DMM/FANZA 爬虫（官方 GraphQL）"""

    name = "dmm_web"
    display_name = "DMM/FANZA"
    # 必须是 dmm.co.jp 域：http_client 靠它判断是否走日本出口分流
    base_url = "https://www.dmm.co.jp"
    graph_url = GRAPHQL_URL

    priority = CrawlerPriority.LOW
    supported_types = ["jav"]
    supported_prefixes = []
    description = "DMM/FANZA 官方 GraphQL 数据源（需日本出口）"
    language = "ja"
    requires_proxy = False

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """按番号刮削。"""
        cid = number_to_content_id(code)
        if not cid:
            logger.debug("DMM: 番号 %r 无法转换为 content_id", code)
            return None

        # 🔴 必须传 base_url：命中 dmm.co.jp ⇒ http_client 改走日本链式代理。
        # 不传则永远走原代理（实测出口在美国）⇒ 拿不到数据。
        async with AsyncHttpClient(base_url=self.base_url) as client:
            try:
                data = await self._gql(
                    client, CONTENT_QUERY, "ContentPageData", {"id": cid})
            except Exception as e:  # noqa: BLE001
                logger.debug("DMM %s 请求失败: %s", code, e)
                return None

        content = (data or {}).get("ppvContent")
        if not content or not content.get("title"):
            # 正确行为：DMM 未收录此番号（旧实现会误判为成功并落空数据）
            logger.debug("DMM: %s (%s) 未收录", code, cid)
            return None

        result = self._build_result(code, cid, content,
                                    (data or {}).get("reviewSummary"))
        self.mark_success()
        return result

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """按标题/厂牌检索（**番号搜不到**，见模块 docstring）。"""
        if not keyword:
            return []
        async with AsyncHttpClient(base_url=self.base_url) as client:
            try:
                data = await self._gql(
                    client, SEARCH_QUERY, "AvSearch",
                    {"limit": 20, "queryWord": keyword})
            except Exception as e:  # noqa: BLE001
                logger.debug("DMM 检索 %r 失败: %s", keyword, e)
                return []

        out: list[ScrapeResult] = []
        contents = (((data or {}).get("legacySearchPPV") or {})
                    .get("result") or {}).get("contents") or []
        for item in contents:
            cid = item.get("id")
            title = item.get("title")
            if not cid or not title:
                continue
            out.append(ScrapeResult(
                code=cid,
                title=title,
                source=self.name,
                source_url="https://video.dmm.co.jp/av/content/?id=%s" % cid,
                studio=(item.get("maker") or {}).get("name"),
                raw_data={"content_id": cid},
            ))
        return out

    # ---------- 内部 ----------

    async def _gql(self, client: AsyncHttpClient, query: str,
                   operation: str, variables: dict) -> dict:
        """执行一次 GraphQL 查询，返回 data 段。"""
        resp = await client.post(
            self.graph_url,
            json={"operationName": operation, "variables": variables, "query": query},
            headers=_GRAPHQL_HEADERS,
        )
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            return {}
        if payload.get("errors"):
            logger.debug("DMM GraphQL %s 报错: %s", operation,
                         str(payload["errors"])[:200])
        return payload.get("data") or {}

    def _build_result(self, code: str, cid: str, content: dict,
                      review: Optional[dict]) -> ScrapeResult:
        """把 GraphQL 返回映射成 ScrapeResult。"""
        # 演员：源站 actresses 即女性演员名（无 gender 字段混杂）
        actors = [
            ActorInfo(name=a["name"])
            for a in (content.get("actresses") or [])
            if a and a.get("name")
        ]

        # 时长：源站是秒 ⇒ /60 转分钟（契约=分钟）
        duration = None
        raw_dur = content.get("duration")
        if isinstance(raw_dur, (int, float)) and raw_dur > 0:
            duration = int(raw_dur // 60)

        # 评分：reviewSummary 是 0~5 量纲，契约是 0~10 ⇒ *2
        rating = None
        if review and review.get("average") is not None:
            try:
                rating = round(float(review["average"]) * 2, 2)
            except (TypeError, ValueError):
                rating = None

        genres = [
            g["name"] for g in (content.get("genres") or [])
            if g and g.get("name")
        ]
        samples = [
            s["largeImageUrl"] for s in (content.get("sampleImages") or [])
            if s and s.get("largeImageUrl")
        ]
        directors = [
            d["name"] for d in (content.get("directors") or [])
            if d and d.get("name")
        ]

        return ScrapeResult(
            code=code,
            title=(content.get("title") or "").strip(),
            source=self.name,
            source_url="https://video.dmm.co.jp/av/content/?id=%s" % cid,
            studio=(content.get("maker") or {}).get("name"),
            maker=(content.get("label") or {}).get("name"),
            label=(content.get("label") or {}).get("name"),
            series=(content.get("series") or {}).get("name"),
            release_date=_parse_release_date(content.get("makerReleasedAt")),
            duration=duration,
            genres=genres,
            actors=actors,
            directors=directors,
            cover_url=(content.get("packageImage") or {}).get("largeUrl"),
            poster_url=(content.get("packageImage") or {}).get("largeUrl"),
            sample_images=samples,
            trailer_url=(content.get("sample2DMovie") or {}).get("highestMovieUrl"),
            rating=rating,
            raw_data={
                "content_id": cid,
                "dmm_review_total": (review or {}).get("total"),
            },
        )
