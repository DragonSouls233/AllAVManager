"""
维基百科 日本AV女优 分类服务

通过 MediaWiki API 抓取中文维基百科「Category:日本AV女優」分类下的女优条目，
作为演员发现/补充来源。

数据流：
1. list=categorymembers 按分类分页拉取成员页面（cmcontinue 游标，稳定可靠）
2. 分批用 prop=pageimages 查询条目缩略图
3. 返回女优列表（名称 / 页面ID / 缩略图 / 维基链接）

注：
- 分类页为繁体「Category:日本AV女優」（简体标题自动重定向）
- 分类共约 777 个条目，其中含少量概念页（AV事務所/AV女優 等）已过滤
- 避免使用 generator+prop 组合查询（其分页返回 picontinue，行为不一致）
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

# 中文维基百科 API 端点
WIKIPEDIA_API = "https://zh.wikipedia.org/w/api.php"

# 日本AV女优 分类（繁体，简体自动重定向）
CATEGORY_TITLE = "Category:日本AV女優"

# Wikipedia 要求标识 UA
USER_AGENT = "MDCX/3.0 (https://github.com/mdcx)"

# 单次缩略图查询的最大标题数（MediaWiki titles 参数限制）
_THUMB_BATCH = 50

# 分类中的非个人条目（概念页/合集页），排除避免混淆
_EXCLUDE_TITLES = {
    "AV女優",
    "AV女优",
    "日本AV女優",
    "AV女優列表",
    "AV女優出身人物",
    "SOD女優",
    "ケータイ専用女優",
    "AV事務所",
    "AV事務所一覧",
}


async def _fetch_members(client: AsyncHttpClient, limit: int, continue_token: Optional[str]) -> tuple:
    """拉取分类成员标题列表（一页），返回 (标题列表, 下一页游标)"""
    params = [
        "action=query",
        "list=categorymembers",
        "cmtitle=" + quote(CATEGORY_TITLE),
        f"cmlimit={limit}",
        "cmtype=page",
        "format=json",
    ]
    if continue_token:
        params.append("cmcontinue=" + quote(continue_token))
    url = f"{WIKIPEDIA_API}?{'&'.join(params)}"
    data = await client.get_json(url, headers={"User-Agent": USER_AGENT})

    members = data.get("query", {}).get("categorymembers", [])
    next_token = data.get("continue", {}).get("cmcontinue")
    return [m["title"] for m in members if m.get("title") and m["title"] not in _EXCLUDE_TITLES], next_token


async def _fetch_thumbnails(client: AsyncHttpClient, titles: list) -> dict:
    """批量查询条目缩略图，返回 {标题: 缩略图URL}"""
    result = {}
    for i in range(0, len(titles), _THUMB_BATCH):
        batch = titles[i:i + _THUMB_BATCH]
        params = [
            "action=query",
            "titles=" + quote("|".join(batch)),
            "prop=pageimages",
            "piprop=thumbnail",
            "pithumbsize=150",
            "format=json",
        ]
        url = f"{WIKIPEDIA_API}?{'&'.join(params)}"
        data = await client.get_json(url, headers={"User-Agent": USER_AGENT})
        pages = data.get("query", {}).get("pages", {})
        for pid, pg in pages.items():
            try:
                if int(pid) < 0:
                    continue
            except (ValueError, TypeError):
                continue
            title = pg.get("title", "")
            if title:
                result[title] = (pg.get("thumbnail") or {}).get("source")
    return result


async def fetch_actress_category(
    limit: int = 500,
    continue_token: Optional[str] = None,
    with_thumbnail: bool = True,
) -> dict:
    """抓取维基百科「日本AV女優」分类成员列表

    Args:
        limit: 单次拉取条数（1-500）
        continue_token: 分页游标（MediaWiki cmcontinue），空则从第一页开始
        with_thumbnail: 是否附带条目缩略图

    Returns:
        {"items": [{
            "title": 条目名, "pageid": 页面ID,
            "thumbnail": 缩略图URL(可能为空), "url": 维基页面链接,
        }], "continue": 下一页游标(空表示无更多), "has_more": 是否还有下一页}
    """
    limit = max(1, min(limit, 500))

    async with AsyncHttpClient(timeout=25) as client:
        try:
            titles, next_token = await _fetch_members(client, limit, continue_token)
            thumbnails = await _fetch_thumbnails(client, titles) if with_thumbnail and titles else {}
        except Exception as e:
            logger.warning(f"维基分类抓取失败: {e}")
            return {"items": [], "continue": None, "has_more": False}

    items = [
        {
            "title": t,
            "thumbnail": thumbnails.get(t),
            "url": f"https://zh.wikipedia.org/wiki/{quote(t)}",
        }
        for t in titles
    ]

    return {
        "items": items,
        "continue": next_token,
        "has_more": bool(next_token),
    }
