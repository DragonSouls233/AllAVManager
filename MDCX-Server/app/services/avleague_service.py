"""
AVリーグ（AV联盟）数据服务

实时抓取 AV联盟 的榜单与演员作品数据，并与本地 jav 库比对发现新作。

提供：
- 实时榜单（新人 / 全女优，24小时 / 3日 / 30日 / 年度 / 新着）
- 演员搜索（站内搜索，仅支持演员名）
- 演员作品列表（2D 作品，含封面 / 发售日 / 标题）
- 番号提取（作品详情页内嵌 DMM 样本 cid 或 og:image 封面 URL）
- 本地库比对（按番号标记作品是否已收录，实现"新作发现"）
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from sqlalchemy import select

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.av-league.com"

# 榜单周期 -> URL 片段（数字对应 24小时/3日/30日/年度，newest=新着，all=全时期）
PERIOD_MAP = {
    "24h": "1",
    "3d": "3",
    "30d": "30",
    "year": "2025",
    "newest": "newest",
    "all": "all",
}

# 榜单类型（新人榜 / 全女优榜）
KIND_MAP = {
    "new": "new",
    "all": "all",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
}


# ==========================================
# 榜单
# ==========================================

async def fetch_leaderboard(
    kind: str = "all", period: str = "3d", page: int = 1, tag: Optional[int] = None
) -> dict:
    """实时抓取 AV联盟 演员人气榜单

    Args:
        kind: 榜单类型，new=新人榜，all=全女优榜
        period: 统计周期，24h / 3d / 30d / year / newest / all
        page: 页码（每页 60 人）
        tag: 标签 ID（如巨乳/美少女等），指定后按标签榜单抓取

    Returns:
        {"total": 总人数, "page": 当前页, "items": [{
            "rank": 排名, "name": 名字, "score": 票数,
            "avatar_url": 头像, "actress_id": 站内ID, "actress_url": 详情链接,
        }]}
    """
    if tag:
        # 标签榜单: /actress-list/ctag/{tag}_all_default_{page}.html
        url = f"{BASE_URL}/actress-list/ctag/{tag}_all_default_{page}.html"
    else:
        kind_key = KIND_MAP.get(kind, "all")
        period_key = PERIOD_MAP.get(period, "3")
        if period_key == "all":
            url = f"{BASE_URL}/actress-list/{kind_key}-/all_all_default_{page}.html"
        else:
            url = f"{BASE_URL}/actress-list/{kind_key}-{period_key}/all_all_default_{page}.html"

    async with AsyncHttpClient(timeout=20) as client:
        html_text = await client.get_text(url, headers=_HEADERS)
        if not html_text:
            return {"total": 0, "page": page, "items": []}

    items = []
    # 榜单条目以 <div class="l-box"> 为分隔符切块（块间无第三层 </div>）
    for block in html_text.split('<div class="l-box">')[1:]:
        rank_m = re.search(r'class="l-rank">\s*(\d+)', block)
        name_m = re.search(r'class="l-name">\s*<a href="([^"]+)"[^>]*>([^<]*)</a>', block)
        score_m = re.search(r'class="l-vote">[^0-9]*([\d,]+)', block)
        avatar_m = re.search(r'data-layzr="([^"]+)"', block)
        if not name_m:
            continue
        href, name = name_m.group(1), name_m.group(2).strip()
        items.append({
            "rank": int(rank_m.group(1)) if rank_m else len(items) + 1,
            "name": name,
            "score": int(score_m.group(1).replace(",", "")) if score_m else 0,
            "avatar_url": avatar_m.group(1) if avatar_m else None,
            "actress_id": int(href.split("/")[-1].replace(".html", "")),
            "actress_url": href if href.startswith("http") else f"{BASE_URL}{href}",
        })
        # 碰到下一个 l-box 前的尾部多余内容不影响（各字段只取第一个匹配）
        if len(items) >= 100:
            break

    total_m = re.search(r"（(\d+)人）", html_text)
    return {
        "total": int(total_m.group(1)) if total_m else 0,
        "page": page,
        "items": items,
    }


# ==========================================
# 演员搜索 / 作品
# ==========================================

async def search_actress(name: str) -> Optional[dict]:
    """站内搜索演员（仅支持演员名），返回第一个匹配结果"""
    from urllib.parse import quote

    search_url = f"{BASE_URL}/search/search.php?k={quote(name)}"
    async with AsyncHttpClient(timeout=20) as client:
        html_text = await client.get_text(search_url, headers=_HEADERS)
        if not html_text:
            return None

    for block in html_text.split('<div class="l-box">')[1:]:
        name_m = re.search(r'class="l-name">\s*<a href="([^"]+)"[^>]*>([^<]*)</a>', block)
        avatar_m = re.search(r'data-layzr="([^"]+)"', block)
        if not name_m:
            continue
        href, hit_name = name_m.group(1), name_m.group(2).strip()
        if name.lower() in hit_name.lower() or hit_name.lower() in name.lower():
            actress_id = int(href.split("/")[-1].replace(".html", ""))
            return {
                "actress_id": actress_id,
                "name": hit_name,
                "avatar_url": avatar_m.group(1) if avatar_m else None,
                "actress_url": href if href.startswith("http") else f"{BASE_URL}{href}",
            }
    return None


async def fetch_actor_works(actress_id: int, limit: int = 30) -> list[dict]:
    """抓取演员的 2D 作品列表（第 1 页，按发售日倒序）"""
    url = f"{BASE_URL}/works-list/actress/{actress_id}_2d_all_1.html"
    async with AsyncHttpClient(timeout=20) as client:
        html_text = await client.get_text(url, headers=_HEADERS)
        if not html_text:
            return []

    works = []
    # 作品条目以 <div class="w-box"> 为分隔符切块
    for block in html_text.split('<div class="w-box">')[1:]:
        link_m = re.search(r'href="/works/(\d+)\.html"', block)
        cover_m = re.search(r'data-layzr="([^"]+)"', block)
        date_m = re.search(r'class="w-date[^"]*">\s*([^<]+)', block)
        title_m = re.search(r'class="w-title">\s*<a[^>]*>([^<]*)', block)
        if not link_m:
            continue
        works.append({
            "work_id": int(link_m.group(1)),
            "title": title_m.group(1).strip() if title_m else "",
            "cover_url": cover_m.group(1) if cover_m else None,
            "release_date": date_m.group(1).strip() if date_m else None,
        })
        if len(works) >= limit:
            break
    return works


# ==========================================
# 番号提取
# ==========================================

async def fetch_work_code(work_id: int) -> Optional[str]:
    """抓取作品详情页，从 DMM 样本 cid / og:image 封面 URL 提取番号"""
    url = f"{BASE_URL}/works/{work_id}.html"
    async with AsyncHttpClient(timeout=20) as client:
        html_text = await client.get_text(url, headers=_HEADERS)
        if not html_text:
            return None

    # DMM 样本 iframe: src=...?cid=ipzz00853
    m = re.search(r"cid=([a-zA-Z0-9]+)", html_text)
    if m:
        return _cid_to_code(m.group(1))

    # og:image: pics.dmm.co.jp/digital/video/{cid}/{cid}ps.jpg
    m = re.search(r"pics\.dmm\.co\.jp/digital/video/([a-zA-Z0-9]+)/", html_text)
    if m:
        return _cid_to_code(m.group(1))

    return None


def _cid_to_code(cid: str) -> str:
    """DMM cid -> 番号：ipzz00853 -> IPZZ-00853（字母大写 + 数字前加横线）"""
    m = re.fullmatch(r"([a-zA-Z]+)(\d+)", cid)
    if not m:
        return cid.upper()
    return f"{m.group(1).upper()}-{m.group(2)}"


# ==========================================
# 本地比对（新作发现）
# ==========================================

async def get_actor_new_works(name: str, limit: int = 15, module: str = "jav") -> dict:
    """演员新作发现：搜索演员 -> 拉作品列表 -> 并发提取番号 -> 与本地库比对

    Returns:
        {"actor": {...}, "total": 作品数, "new_count": 本地未收录数, "works": [{
            "work_id", "title", "cover_url", "release_date",
            "code": 番号, "has_local": 是否已收录,
        }]}
    """
    actor = await search_actress(name)
    if not actor:
        return {"actor": None, "total": 0, "new_count": 0, "works": []}

    works = await fetch_actor_works(actor["actress_id"], limit=limit)
    if not works:
        return {"actor": actor, "total": 0, "new_count": 0, "works": []}

    # 并发提取番号
    codes = await asyncio.gather(
        *[fetch_work_code(w["work_id"]) for w in works],
        return_exceptions=True,
    )
    for work, code in zip(works, codes):
        work["code"] = code if isinstance(code, str) else None

    # 与本地 jav 库比对
    known_codes = set()
    try:
        from app.utils.module_helper import get_module_model, get_module_session
        MovieModel = get_module_model(module, "movie")
        session = await get_module_session(module)
        try:
            result = await session.execute(
                select(MovieModel.code).where(
                    MovieModel.code.in_([w["code"] for w in works if w["code"]])
                )
            )
            known_codes = {row[0] for row in result.all()}
        finally:
            await session.close()
    except Exception as e:
        logger.warning(f"本地库比对失败（module={module}）: {e}")

    new_count = 0
    for work in works:
        work["has_local"] = work["code"] in known_codes if work["code"] else False
        if work["code"] and not work["has_local"]:
            new_count += 1

    return {"actor": actor, "total": len(works), "new_count": new_count, "works": works}
