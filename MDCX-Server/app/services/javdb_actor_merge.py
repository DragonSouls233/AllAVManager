# -*- coding: utf-8 -*-
"""
JavDB 改名演员自动合并扫描

利用 JavDB 演员目录页（/actors/censored 分页）中每个演员卡片的 title 属性
（格式: "主名, 曾用名1, 曾用名2, ..."，JavDB 内置维护的全部历史名称），
与本地演员库做匹配：若本地有 >=2 个演员的名字/别名命中同一个 JavDB 组，
则判定为改名同一人，生成合并候选（canonical + sources）。
"""
import logging
import re

from sqlalchemy import select

from app.utils.module_helper import get_module_model, get_module_session
from app.utils.actor_alias import merged_from_names

logger = logging.getLogger(__name__)

# JavDB 有码演员目录 URL 模板（每页 50 人，实际约 30 页）
_CENSORED_LIST_URL = "https://javdb.com/actors/censored?page={page}"


def _normalize(name: str) -> str:
    """名称规范化：去空白、统一大小写，用于匹配"""
    return re.sub(r"\s+", "", name or "").strip().lower()


def _parse_actor_card(html: str) -> dict[str, list[str]]:
    """解析演员目录页 HTML，返回 {actor_id: [全部名字]}"""
    result: dict[str, list[str]] = {}
    # 卡片结构: <a href="/actors/19yv" title="三浦歩美, 愛弓りょう">
    for m in re.finditer(
        r'<a href="/actors/([A-Za-z0-9]+)" title="([^"]*)"', html
    ):
        aid, title = m.group(1), m.group(2)
        names = [n.strip() for n in title.split(",") if n.strip()]
        if names:
            result[aid] = names
    return result


async def fetch_censored_actor_index(max_pages: int = 100, proxy: str | None = None) -> dict[str, list[str]]:
    """抓取 JavDB 有码演员目录，构建 actor_id -> [全部名字] 索引

    **主通道：匿名 App API**（/api/v1/actors?type=0）——免登录、不绑定 IP、
    绕 Cloudflare，不受 javdb.com 对出口 IP 封禁的影响（已被封时 HTML 目录
    页会 403，导致合并扫描完全失效）。
    **降级：HTML 目录页**（原逻辑，App API 签名失效等场景兜底）。

    Args:
        max_pages: 最多抓取页数（App API 每页 50 人；HTML 每页 50 人）
        proxy: 显式代理（本地测试用 10808；None 则走项目内置代理）

    Returns:
        {actor_id: [名字...]}
    """
    # ── 主通道：匿名 App API ──
    try:
        from app.services.javdb_app_client import JavDBAppClient, create_app_client_from_config
        if proxy:
            client = JavDBAppClient(proxy=proxy)
        else:
            client = await create_app_client_from_config()
        try:
            index = await client.fetch_actor_index(zone="censored", max_pages=max_pages)
        finally:
            await client.close()
        if index:
            logger.info(f"JavDB App API 演员目录抓取完成，共 {len(index)} 人")
            return index
        logger.warning("JavDB App API 演员目录为空，降级 HTML")
    except Exception as e:
        logger.warning(f"JavDB App API 演员目录抓取失败，降级 HTML: {e}")

    # ── 降级：HTML 目录页（原逻辑）──
    from app.utils.http_client import AsyncHttpClient
    from app.utils.cookie_manager import get_cookie_headers

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    # javdb 演员目录为公开数据，仅需 over18=1 年龄 cookie（登录 cookie 可选项）。
    # 带上 get_cookie_headers 统一输出，避免裸请求被 CF 拒。
    cookie_headers = get_cookie_headers("javdb")
    if cookie_headers and cookie_headers.get("cookie"):
        headers.setdefault("cookie", cookie_headers["cookie"])
    index: dict[str, list[str]] = {}
    async with AsyncHttpClient(proxy=proxy, timeout=20) as client:
        for page in range(1, max_pages + 1):
            try:
                html = await client.get_text(_CENSORED_LIST_URL.format(page=page), headers=headers)
                if not html:
                    logger.warning(f"JavDB 演员目录 page={page} 无响应，停止")
                    break
                if "Just a moment" in html or "cf-challenge" in html:
                    logger.warning(f"JavDB 演员目录 page={page} 被 CF 拦截，停止")
                    break
                page_index = _parse_actor_card(html)
                if not page_index:
                    logger.warning(f"JavDB 演员目录 page={page} 未解析到卡片，停止")
                    break
                index.update(page_index)
                if page % 5 == 0:
                    logger.info(f"JavDB 演员目录已抓取 {page} 页，累计 {len(index)} 人")
            except Exception as e:
                logger.warning(f"JavDB 演员目录 page={page} 抓取失败: {e}")
                break
    return index


def _actor_match_keys(actor) -> set[str]:
    """取演员的全部匹配键（name + alias 拆分），返回规范化集合"""
    keys = set()
    for raw in (getattr(actor, "name", "") or "",):
        n = _normalize(raw)
        if n:
            keys.add(n)
    alias = getattr(actor, "alias", "") or ""
    for al in alias.split(","):
        n = _normalize(al)
        if n:
            keys.add(n)
    return keys


async def scan_merge_candidates(module: str = "jav", max_pages: int = 100, proxy: str | None = None) -> dict:
    """扫描改名演员合并候选

    流程：
    1. 抓 JavDB 有码演员目录 → {actor_id: [全部名字]}
    2. 建 JavDB 名字 -> actor_id 反查索引
    3. 遍历本地演员，记录每个演员命中的 JavDB 组
    4. 命中同一 JavDB 组且 >=2 个本地演员 → 合并候选

    Returns:
        {"candidates": [...], "total": N, "scanned": 本地扫描数, "javdb_groups": JavDB组数}
    """
    index = await fetch_censored_actor_index(max_pages=max_pages, proxy=proxy)
    if not index:
        return {"error": "JavDB 演员目录抓取失败（网络/被拦截），请检查代理与 Cookie", "candidates": [], "total": 0}

    # JavDB 名字 -> set(actor_id)
    name_to_groups: dict[str, set[str]] = {}
    for aid, names in index.items():
        for n in names:
            k = _normalize(n)
            if k:
                name_to_groups.setdefault(k, set()).add(aid)

    session = await get_module_session(module)
    ActorModel = get_module_model(module, "actor")
    try:
        result = await session.execute(select(ActorModel))
        local_actors = result.scalars().all()
    finally:
        await session.close()

    # 本地演员 -> 命中的 JavDB 组集合
    actor_groups: dict[int, tuple] = {}  # actor_id -> (actor, set(gid))
    for actor in local_actors:
        # 已合并过的演员（alias 含来源旧名）不再参与候选，
        # 避免「合并完成后重新扫描又显示同一组」
        if merged_from_names(actor):
            continue
        keys = _actor_match_keys(actor)
        groups: set[str] = set()
        for k in keys:
            gs = name_to_groups.get(k)
            if gs:
                groups |= gs
        if groups:
            actor_groups[actor.id] = (actor, groups)

    # 组 -> 命中的本地演员
    group_actors: dict[str, list] = {}
    for actor, groups in actor_groups.values():
        for gid in groups:
            group_actors.setdefault(gid, []).append(actor)

    candidates: list[dict] = []
    for gid, actors in group_actors.items():
        if len(actors) < 2:
            continue
        javdb_names = index.get(gid, [])
        main_name = _normalize(javdb_names[0]) if javdb_names else ""
        # canonical 选择：主名命中的本地演员优先；否则作品数最多的
        canonical = None
        for a in actors:
            if _normalize(getattr(a, "name", "")) == main_name:
                canonical = a
                break
        if canonical is None:
            canonical = max(actors, key=lambda a: getattr(a, "movie_count", 0) or 0)
        sources = [a for a in actors if a.id != canonical.id]
        if not sources:
            continue
        candidates.append({
            "javdb_group": gid,
            "javdb_names": javdb_names,
            "canonical": {
                "id": canonical.id,
                "name": getattr(canonical, "name", ""),
                "alias": getattr(canonical, "alias", "") or "",
                "movie_count": getattr(canonical, "movie_count", 0) or 0,
            },
            "sources": [
                {
                    "id": a.id,
                    "name": getattr(a, "name", ""),
                    "alias": getattr(a, "alias", "") or "",
                    "movie_count": getattr(a, "movie_count", 0) or 0,
                }
                for a in sources
            ],
        })

    # 按来源数量降序（合并价值大的在前）
    candidates.sort(key=lambda c: -len(c["sources"]))
    return {
        "candidates": candidates,
        "total": len(candidates),
        "scanned": len(local_actors),
        "javdb_groups": len(index),
        "matched_actors": len(actor_groups),
    }
