"""欧美场景聚合刮削器 — 一站覆盖所有欧美站点。

数据源（优先级链）：
1. Aylo API（site-api.project1service.com）— Brazzers/Mofos/Twistys 等 20+ 品牌，
   **实测可用且支持跨品牌全局搜索**（?q= 一次请求 total=25210）
2. IAFD 场景搜索 — 最全的欧美元数据库
3. ThePornDB API — 通用欧美元数据 API（需用户自备 Key）
4. NaughtyAmerica API — 仅能按 scene_id 取，不支持关键词搜索

⚠️ 2026-10-04 实测纠错（务必先读，与旧注释相反）：
  ① IAFD 搜索页**没有改成 AJAX**。实测 `results.asp?searchtype=comprehensive`
     直接返回含 `<table id="titleresult">` 的完整 HTML（37KB，Top 50 行）。
     真正的问题是旧解析器找 `//table[@class="maintableresults"]` ——
     该 class 已不存在，现为 `table display table-responsive` + `id="titleresult"`。
     另外 `searchtype=scenes` 搜 "Cum Inside Me" 只返回 4KB 空页 ⇒ 必须用 comprehensive。
  ② IAFD 结果里的链接是**绝对 URL**（`https://www.iafd.com/title.rme/id=<uuid>`），
     旧代码 `_IAFD_BASE + "/" + href.lstrip("/")` 会拼成
     `https://www.iafd.com/https://www.iafd.com/title.rme/...` ⇒ 100% 失败。
  ③ IAFD 详情页字段名已变：时长是 `Minutes`（**分钟**，旧代码读 `Running Time`
     并乘 60）；演员在 `div.castbox`（旧代码读 bioheading 的 Performer —— 不存在）；
     **详情页完全没有封面图**（`<img class="headshot">` 是演员头像，不是封面）。
     ⇒ IAFD 只能提供 title/studio/date/actors/duration，封面必须由其它源补。
  ④ IAFD 详情页 403 —— 必须带 `Referer: https://www.iafd.com/` + 浏览器 UA，
     否则 Cloudflare 直接拒（不带 Referer 时首页能 200、搜索页 403）。
  ⑤ naughtyapi（NaughtyAmerica）**忽略全部查询参数**：`?search=` / `?title=` / `?q=`
     三种参数返回的都是同一份「最新 100 条」。所以它只能按 scene_id 取详情，
     不能当搜索源用。
"""
import asyncio
import json
import re
from typing import Optional
from urllib.parse import quote_plus, urljoin

from lxml import html as lxml_html

from app.crawlers.base import ActorInfo, BaseCrawler, CrawlerPriority, ScrapeResult
from app.crawlers.provider import register_crawler
from app.services.western_utils import (
    AYLO_BRANDS,
    is_scene_match,
    extract_brand_from_url,
)
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# IAFD 需要 Referer 才放行（见模块 docstring ④）
_IAFD_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://www.iafd.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# IAFD 场景搜索（2026-10-04 重写）
# ---------------------------------------------------------------------------

_IAFD_BASE = "https://www.iafd.com"
# 🔴 searchtype 必须是 comprehensive（见模块 docstring ①）
_IAFD_SEARCH = f"{_IAFD_BASE}/results.asp?searchtype=comprehensive&searchstring={{query}}"

# 降级序列上限 / 重试间隔（见 _search_iafd_scene docstring 补坑 3：IAFD 间歇限流）
_MAX_VARIANTS = 3
_RETRY_DELAY = 2.0


def _title_score(query: str, candidate: str) -> float:
    """候选标题与查询词的匹配打分（0~1）。

    🔴 为什么不用 is_scene_match()：它用 difflib 全串相似度，对
    "Cum Inside Me" vs "BBC Cum Inside Me" 这类前缀差异过于敏感
    （相似度仅 ~0.6），会把正确结果判掉。改用词级覆盖率：
    查询里每个词都在候选里出现即算命中，再按长度差做轻微惩罚。
    """
    q = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1]
    if not q:
        return 0.0
    c = candidate.lower()
    hit = sum(1 for w in q if w in c)
    if hit == 0:
        return 0.0
    coverage = hit / len(q)
    len_ratio = min(1.0, (len(c) / max(len(query), 1)) ** 0.15)
    return coverage * 0.85 + len_ratio * 0.15


async def _search_iafd_scene(title: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    """通过 IAFD 搜索欧美元数据。2026-10-04 重写要点见模块 docstring ①②。

    🔴 实测补坑 1：欧美文件名普遍是「演员名 - 场景名 - [站点] - [年份]」，
    而 **IAFD 只索引场景标题、不含演员名**，实测
    `searchstring=Anna Ralphs Cum Inside Me` 返回 **0 行**，
    同一站点搜 `Cum Inside Me` 返回 50 行。
    ⇒ 搜索失败时逐级剥离「前缀演员名」「方括号站点/年份」后重试。

    ⚠️ 实测补坑 2（curl_cffi 原生层）：**同一 client 连续发多次请求会被静默
    杀掉整个进程** —— 不是抛异常，是进程直接消失，`except BaseException`
    都拦不住。所以每次尝试都**新建一个 client**，不复用传进来的那个。

    ⚠️ 实测补坑 3（IAFD 限流）：同一关键词连续 3 次请求，实测有 1 次返回空
    （间歇性限流，不是稳定失败）。故每个关键词最多重试 2 次，且尝试次数
    封顶（`_MAX_VARIANTS`）—— 否则降级序列会把请求数放大到十几倍，
    既触发限流又拖慢批量刮削。
    """
    for query in _iafd_query_variants(title)[:_MAX_VARIANTS]:
        for attempt in range(3):
            async with AsyncHttpClient(timeout=30) as c:
                r = await _iafd_search_once(query, c)
            if r:
                return r
            if attempt == 0:
                await asyncio.sleep(_RETRY_DELAY)
    return None


def _tidy_query(s: str) -> str:
    """把欧美文件名清洗成「场景标题」形态，供 IAFD/Aylo 搜索。

    实测需要处理的形态（G:\\TEST\\欧美 真实样本）：
      `Anna Ralphs - [Hegre.com] - [2023] - Cum Inside Me - 4K`
        → 去方括号、去年份、去画质、去**分隔符残留** → `Anna Ralphs Cum Inside Me`
      `Blacked.19.10.12.Lana.Sharapova.4k-C`
        → 去年份/画质/后缀 → `Blacked.Lana.Sharapova`（仍搜不到，属站点号，走 Aylo ID）
      `PublicAgent.16.05.27.Jimena.Lago.XXX.1080p.MP4-KTR[rarbg]`
        → `PublicAgent.Jimena.Lago.XXX.MP4-KTR`
    """
    s = re.sub(r"\[[^\]]*\]", " ", s)                 # 方括号（站点/画质/发布组）
    s = re.sub(r"[（(][^）)]*[）)]", " ", s)            # 圆括号
    s = re.sub(r"\.(?=\d{4}\.)", " ", s)               # Blacked.19.10.12 → Blacked 19.10.12
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)             # 年份
    s = re.sub(r"\b(4k|8k|1080p|2160p|720p|480p|hd|uhd|fhd|x264|x265|hevc)\b",
               " ", s, flags=re.IGNORECASE)
    s = re.sub(r"-(?:c|u|uc|cu)$", " ", s, flags=re.IGNORECASE)   # 中字/无码后缀
    s = re.sub(r"\s+", " ", s)
    # 🔴 分隔符归一：`A - B - C` 里的孤立连字符要清掉，否则切词后得到
    #    "Ralphs - - - Cum Inside Me" 这种垃圾查询（实测）。
    s = re.sub(r"\s*[-–—]\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .·|")
    return s


def _iafd_query_variants(title: str) -> list[str]:
    """生成 IAFD 搜索关键词的降级序列（从最精确到最宽松）。

    实测依据：
    - `Cum Inside Me` → 50 行（IAFD 索引的是纯场景标题）
    - `Anna Ralphs Cum Inside Me` → **0 行**（演员名不在索引里）
    - 方括号内容（站点名/年份/画质）IAFD 不索引，同样要去掉

    ⚠️ 顺序：先剥离演员名再搜整串 —— 含演员名的整串必然 0 行，
    先发它纯属白耗请求 + 吃限流配额。
    """
    base = _tidy_query(title) or title.strip()

    variants: list[str] = []

    # ① 剥离前缀演员名（"Anna Ralphs Cum Inside Me" → "Cum Inside Me"）
    #    🔴 剥离后必须仍 ≥3 词：实测 "Cum Inside Me"（3 词）若按 cut=1
    #    剥成 "Inside Me"（2 词）会先白发一次请求、还吃一次限流配额。
    #
    #    🔴 另一个坑：**只剥掉「名字」不剥「姓氏」** 会产出
    #    "Ralphs Cum Inside Me" 这种垃圾查询（实测），白白消耗一次请求。
    #    判定：欧美演员名 = 「名 + 姓」两个大写开头的词。所以按**词数对**
    #    整段剥离（cut=2 起步），而不是逐词砍。
    words = base.split()
    for cut in (2, 3, 4):
        if len(words) - cut >= 3:
            cand = " ".join(words[cut:])
            if cand not in variants:
                variants.append(cand)
    # 单词前缀站（如 "Cum Inside Me"）切不动就整串搜，不必凑变体

    # ② 清洗后的整串（去掉年份/画质/括号/分隔符）
    if base and base not in variants:
        variants.append(base)

    # ③ 原始串兜底
    if title.strip() and title.strip() not in variants:
        variants.append(title.strip())

    return variants


async def _iafd_search_once(query: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    """按单个关键词搜 IAFD（真正的 HTTP + 解析）。"""
    try:
        url = _IAFD_SEARCH.format(query=quote_plus(query))
        html_text = await client.get_text(url, headers=_IAFD_HEADERS)
        if not html_text:
            return None

        doc = lxml_html.fromstring(html_text)

        # ① 表格定位：旧 class "maintableresults" 已不存在
        rows = doc.xpath('//table[@id="titleresult"]//tbody/tr')
        if not rows:
            rows = doc.xpath('//table[@id="titleresult"]//tr[td]')
        if not rows:
            return None

        best_href: Optional[str] = None
        best_score = 0.0
        for row in rows:
            links = row.xpath(".//a[contains(@href, 'title.rme')]")
            if not links:
                links = row.xpath(".//a[@href]")
            if not links:
                continue
            score = _title_score(query, links[0].text_content().strip())
            if score > best_score:
                best_score = score
                best_href = links[0].get("href", "")

        # 阈值 0.5：至少一半查询词命中，且候选标题不比查询短太多
        if not best_href or best_score < 0.5:
            logger.debug("iafd: [%s] 无匹配（best=%.2f）", query, best_score)
            return None

        # ② 链接是绝对 URL（实测），必须 urljoin 而不是字符串拼接
        detail_url = urljoin(_IAFD_BASE + "/", best_href)
        if detail_url.startswith(_IAFD_BASE):
            return await _parse_iafd_detail(detail_url, client)

    except Exception as e:
        logger.debug("iafd search failed [%s]: %s", query, e)
    return None


async def _parse_iafd_detail(url: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    """解析 IAFD 详情页（2026-10-04 按实测结构重写）。"""
    try:
        html_text = await client.get_text(url, headers=_IAFD_HEADERS)
        if not html_text:
            return None

        doc = lxml_html.fromstring(html_text)
        result = ScrapeResult()
        result.source = "iafd"
        result.source_url = url

        # 标题：h1 带年份，如 "B.R.I. [Brazzers Research Institute] (2024)"
        h1 = " ".join(t.strip() for t in doc.xpath("//h1//text()") if t.strip())
        h1 = re.sub(r"\s+", " ", h1).strip()
        if h1:
            h1 = re.sub(r"\s*\(\d{4}\)\s*$", "", h1).strip()
        result.title = h1

        # 字段对：bioheading 文本 → biodata 文本（实测 10 对，成对出现）
        headings = ["".join(p.itertext()).strip() for p in doc.xpath('//p[@class="bioheading"]')]
        datas = ["".join(p.itertext()).strip() for p in doc.xpath('//p[@class="biodata"]')]
        field: dict[str, str] = {}
        for k, v in zip(headings, datas):
            if k:
                field[k.lower()] = v

        # 时长：实测字段名 "Minutes"（已是分钟）
        # 🔴 ScrapeResult.duration 契约是**分钟**（见 javbus._get_duration /
        #    javdb._get_duration，两者都直接返回整数分钟，NFO <runtime> 也是分钟）。
        #    旧代码读 `Running Time` 且乘 60 —— 字段名已不存在，且乘 60 会造成
        #    60 倍偏差（与 PH 的历史 bug 同类）。这里原样返回分钟数。
        m = re.search(r"(\d+)", field.get("minutes", ""))
        if m:
            result.duration = int(m.group(1))

        result.release_date = field.get("release date") or None
        if result.release_date:
            try:
                from datetime import datetime
                result.release_date = datetime.strptime(
                    result.release_date, "%b %d, %Y"
                ).strftime("%Y-%m-%d")
            except Exception:
                result.release_date = None

        result.studio = field.get("distributor") or field.get("studio") or ""

        # 演员：实测在 div.castbox 里（旧代码读 bioheading 的 Performer —— 不存在）
        result.actors = []
        seen: set[str] = set()
        for box in doc.xpath('//div[contains(@class,"castbox")]'):
            a = box.xpath(".//a[contains(@href, 'person.rme')]")
            if not a:
                continue
            name = a[0].text_content().strip()
            if name and name.lower() not in ("n/a", "unknown", "") and name not in seen:
                seen.add(name)
                ai = ActorInfo(name=name)
                img = box.xpath(".//img[@src]")
                if img:
                    ai.avatar_url = img[0].get("src")
                result.actors.append(ai)

        # ③ 详情页无封面图（headshot 是演员头像）
        og = doc.xpath('//meta[@property="og:image"]/@content')
        if og and "iafd_square_logo" not in og[0]:
            result.cover_url = og[0]
        elif result.actors and result.actors[0].avatar_url:
            result.cover_url = result.actors[0].avatar_url

        if result.title:
            return result
    except Exception as e:
        logger.debug("iafd detail parse failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# ThePornDB API 搜索
# ---------------------------------------------------------------------------

_TPDB_API = "https://api.theporndb.net"
_TPDB_SEARCH = f"{_TPDB_API}/scenes?q={{query}}"
_TPDB_DETAIL = f"{_TPDB_API}/scenes/{{slug}}"


async def _search_theporndb(
    title: str, client: AsyncHttpClient, api_key: str = ""
) -> Optional[ScrapeResult]:
    """通过 ThePornDB API 搜索欧美场景。

    🔴 2026-10-04 两个实测结论：
    ① 该 API **必须**带有效 Bearer Token，无 Key 时 401（实测裸 GET 与带假 Key
       都是 401）。没 Key 就直接返回 None，不要白耗一次代理连接。
    ② 模糊搜索直接取 `scenes[0]` 会返回**假数据**（实测无关关键词返回一条
       完全不相关的热门场景）。必须逐条用 is_scene_match() 校验标题。
    """
    if not api_key:
        return None
    headers = {
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        "Authorization": f"Bearer {api_key}",
    }
    try:
        url = _TPDB_SEARCH.format(query=quote_plus(title))
        r = await client.get(url, headers=headers)
        if r is None or r.status_code != 200:
            return None
        try:
            data = r.json()
        except (json.JSONDecodeError, TypeError):
            return None

        scenes = data.get("data", []) if isinstance(data, dict) else []
        if not scenes:
            return None

        # 🔴 逐条校验，绝不取 scenes[0]
        for scene in scenes[:20]:
            stitle = (scene.get("title") or "").strip()
            if not stitle or not is_scene_match(title, stitle):
                continue
            site = scene.get("site") or {}
            result = ScrapeResult()
            result.source = "theporndb"
            result.source_url = _TPDB_DETAIL.format(slug=scene.get("slug", ""))
            result.title = stitle
            result.studio = (site.get("network") or {}).get("name") or site.get("name") or ""
            result.release_date = scene.get("date") or ""
            # 🔴 ThePornDB 返回秒，契约是分钟（同 NA）
            try:
                result.duration = (int(scene.get("duration") or 0) // 60) or None
            except (ValueError, TypeError):
                result.duration = None
            result.cover_url = (
                (scene.get("background") or {}).get("large") or scene.get("image") or ""
            )
            result.poster_url = (scene.get("posters") or {}).get("large") or ""
            result.actors = [
                ActorInfo(name=a.get("name", ""))
                for a in scene.get("performers", []) or []
                if a.get("name")
            ]
            result.genres = [
                t.get("name", "") for t in scene.get("tags", []) or [] if t.get("name")
            ]
            return result
    except Exception as e:
        logger.debug("theporndb search failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# Aylo API（2026-10-04 实测可用：?q= 是跨品牌全局搜索）
# ---------------------------------------------------------------------------

AYLO_API_BASE = "https://site-api.project1service.com/v2"
_AYLO_TOKEN_CACHE: dict[str, str] = {}


async def _get_aylo_instance_token(domain: str, client: AsyncHttpClient) -> str:
    """从品牌站根域取 instance_token（cookie）。进程内缓存。"""
    cached = _AYLO_TOKEN_CACHE.get(domain)
    if cached:
        return cached
    try:
        r = await client.get(
            f"https://www.{domain}.com", headers={"User-Agent": _USER_AGENT}
        )
        if r is not None:
            tok = (r.cookies or {}).get("instance_token")
            if tok:
                _AYLO_TOKEN_CACHE[domain] = tok
                return tok
    except Exception as e:
        logger.debug("aylo token 失败 %s: %s", domain, e)
    return ""


def _aylo_headers(domain: str, token: str) -> dict:
    return {
        "Instance": token,
        "User-Agent": _USER_AGENT,
        "Origin": f"https://www.{domain}",
        "Referer": f"https://www.{domain}",
        "Accept": "application/json",
    }


def _aylo_to_result(item: dict, domain: str) -> Optional[ScrapeResult]:
    """Aylo API 单条记录 → ScrapeResult。

    实测字段：brand / brandMeta{shortName,displayName} / id / type / title /
    dateReleased / description / performers[].images / images[].poster
    """
    title = (item.get("title") or "").strip()
    if not title:
        return None

    brand = item.get("brand") or domain
    brand_meta = item.get("brandMeta") or {}
    short = brand_meta.get("shortName") or ""
    studio = brand_meta.get("displayName") or brand

    release = (item.get("dateReleased") or "")[:10]

    cover = ""
    images = item.get("images") or []
    if isinstance(images, list) and images:
        poster = images[0].get("poster") or {}
        if isinstance(poster, dict):
            for size in ("xx", "xl", "lg", "md", "sm", "xs"):
                cell = poster.get(size)
                if isinstance(cell, dict) and cell.get("url"):
                    cover = re.sub(r"/m=[^/]+", "", cell["url"])
                    break

    actors = []
    for p in item.get("performers") or []:
        name = p.get("name") or ""
        if not name:
            continue
        ai = ActorInfo(name=name)
        pimgs = p.get("images") or {}
        if isinstance(pimgs, dict):
            for size in ("md", "lg", "sm"):
                cell = pimgs.get(size)
                if isinstance(cell, dict) and cell.get("url"):
                    ai.avatar_url = re.sub(r"/m=[^/]+", "", cell["url"])
                    break
        actors.append(ai)

    scene_id = item.get("id")
    code = f"{short}-{scene_id}" if short else str(scene_id or title)
    return ScrapeResult(
        code=code,
        title=title,
        source="aylo",
        source_url=f"https://www.{brand}.com/scene/{scene_id}" if scene_id else None,
        original_title=title,
        studio=studio,
        release_date=release or None,
        plot=(item.get("description") or "")[:2000] or None,
        actors=actors,
        cover_url=cover or None,
    )


async def _aylo_search(
    query: str, client: AsyncHttpClient, domain: str = "brazzers"
) -> Optional[ScrapeResult]:
    """Aylo API 搜索。

    🔴 2026-10-04 实测：`site-api.project1service.com/v2/releases?q=milf`
    带任意一个品牌的 instance_token 就能返回**跨品牌全局结果**（meta.total=25210）。
    旧实现遍历 20+ 品牌各发一次请求（慢 20 倍，且多数品牌取不到 token）。

    与 IAFD 同理，Aylo 也只索引场景标题 ⇒ 沿用同一套关键词降级序列。

    ⚠️ token 必须复用（`_AYLO_TOKEN_CACHE` 进程内缓存），但**每次搜索请求
    新建 client** —— 同一 client 连续请求会被 curl_cffi 原生层静默杀进程
    （见 _search_iafd_scene 的 docstring 补坑 2）。
    """
    # 复用传入 client 只为拿 token（一次请求），随后搜索用独立 client
    token = await _get_aylo_instance_token(domain, client)
    if not token:
        return None

    for q in _iafd_query_variants(query)[:_MAX_VARIANTS]:
        headers = _aylo_headers(domain, token)
        got = False
        for attempt in range(3):
            try:
                async with AsyncHttpClient(timeout=30) as c:
                    r = await c.get(
                        f"{AYLO_API_BASE}/releases?q={quote_plus(q)}", headers=headers
                    )
            except Exception as e:
                logger.debug("aylo search failed [%s]: %s", q, e)
                continue
            if r is not None and r.status_code == 200:
                got = True
                break
            if attempt == 0:
                await asyncio.sleep(_RETRY_DELAY)

        if not got:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        items = (data.get("result") or []) if isinstance(data, dict) else []
        if not items:
            continue

        best, best_score = None, 0.0
        for it in items:
            t = (it.get("title") or "").strip()
            if not t:
                continue
            s = _title_score(q, t)
            if s > best_score:
                best, best_score = it, s
        if best and best_score >= 0.5:
            return _aylo_to_result(best, domain)
    return None


async def _aylo_release_by_id(
    scene_id: str, domain: str, client: AsyncHttpClient
) -> Optional[ScrapeResult]:
    """按 scene_id 取 Aylo release（品牌未知时逐个回退）。"""
    candidates = [domain] + [b.domain.split(".")[0] for b in AYLO_BRANDS]
    seen: set[str] = set()
    for dom in candidates:
        if dom in seen:
            continue
        seen.add(dom)
        token = await _get_aylo_instance_token(dom, client)
        if not token:
            continue
        try:
            r = await client.get(
                f"{AYLO_API_BASE}/releases/{scene_id}",
                headers=_aylo_headers(dom, token),
            )
            if r is None or r.status_code != 200:
                continue
            data = r.json()
            item = data.get("result") if isinstance(data, dict) else None
            if isinstance(item, list):
                item = item[0] if item else None
            if not item:
                continue
            # gallery/compilation 类型往上找父 scene
            if item.get("type") not in (None, "scene"):
                parent = item.get("parent")
                if isinstance(parent, dict) and parent.get("type") == "scene":
                    item = parent
            res = _aylo_to_result(item, dom)
            if res:
                return res
        except Exception as e:
            logger.debug("aylo by id 失败 %s/%s: %s", dom, scene_id, e)
    return None


# ---------------------------------------------------------------------------
# NaughtyAmerica（仅按 scene_id，不支持关键词搜索 —— 见 docstring ⑤）
# ---------------------------------------------------------------------------


async def _naughty_by_id(scene_id: str, client: AsyncHttpClient) -> Optional[ScrapeResult]:
    try:
        r = await client.get(
            f"https://api.naughtyapi.com/tools/scenes/scenes?id={scene_id}",
            headers={"User-Agent": _USER_AGENT},
        )
        if r is None or r.status_code != 200:
            return None
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else None
        scene = (
            items[0] if isinstance(items, list) and items
            else items if isinstance(items, dict)
            else None
        )
        if not scene:
            return None
        title = (scene.get("title") or "").strip()
        return ScrapeResult(
            code=str(scene.get("id") or scene_id),
            title=title,
            source="naughtyamerica",
            source_url=scene.get("scene_url"),
            original_title=title,
            release_date=(scene.get("published_date") or "")[:10] or None,
            plot=(scene.get("synopsis") or "")[:2000] or None,
            cover_url=scene.get("image") or scene.get("trailer") or None,
            # 🔴 naughtyapi 的 length 是**秒**（实测 2036），但 ScrapeResult.duration
            #    契约是**分钟**（javbus/javdb 都直接返回整数分钟，NFO <runtime> 同）。
            #    不转换会造成 60 倍偏差（与 PH 历史 bug 同类）。
            duration=(int(scene.get("length") or 0) // 60) or None,
        )
    except Exception as e:
        logger.debug("naughtyamerica failed: %s", e)
    return None


def _extract_scene_id(code: str) -> Optional[str]:
    """从任意输入提取 scene 数字 ID。"""
    if code.isdigit():
        return code
    m = re.search(r"(\d{3,})(?:$|[/?#.\-_ ])", code)
    return m.group(1) if m else None


def _tpdb_api_key() -> str:
    try:
        from app.config.manager import get_config
        return getattr(get_config().modules.western, "theporndb_api_key", "") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 爬虫注册
# ---------------------------------------------------------------------------


@register_crawler
class WesternAggregateCrawler(BaseCrawler):
    """欧美聚合爬虫 — Aylo + IAFD + ThePornDB + NaughtyAmerica。"""

    name = "western_aggregate"
    display_name = "欧美聚合"
    base_url = ""

    priority = CrawlerPriority.NORMAL
    supported_types = ["western"]
    description = "欧美聚合爬虫（Aylo + IAFD + ThePornDB + NA）"
    language = "en"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        from app.services.proxy_manager import get_effective_proxy_url
        self._proxy = get_effective_proxy_url()

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        """按标题/URL/ID 刮削欧美场景。

        支持三种输入：
        - URL   : https://www.brazzers.com/scene/12345
        - 纯 ID : 12345
        - 标题  : Busty Mom Seduces Son
        """
        brand = extract_brand_from_url(code) if code.startswith("http") else None
        brand_key = (brand or "brazzers").lower()
        is_id_input = code.startswith("http") or code.isdigit()
        scene_id = _extract_scene_id(code) if is_id_input else None

        # ⚠️ 每一步都用**独立 client**：同一 client 连续请求多个站点会被
        # curl_cffi 原生层静默杀掉整个进程（不是异常，拦不住）。
        # 0) URL / 纯 ID → 按 ID 直取（Aylo 品牌站最准）
        if scene_id:
            async with AsyncHttpClient(timeout=30, proxy=self._proxy) as c:
                r = await _aylo_release_by_id(scene_id, brand_key, c)
            if r:
                logger.info("western scrape %s: found via aylo id", code)
                return r
            async with AsyncHttpClient(timeout=20, proxy=self._proxy) as c:
                r = await _naughty_by_id(scene_id, c)
            if r:
                logger.info("western scrape %s: found via naughtyamerica", code)
                return r

        # 1) Aylo 全局搜索（实测最快最全）
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as c:
            r = await _aylo_search(code, c, brand_key)
        if r:
            logger.info("western scrape %s: found via aylo search", code)
            return r

        # 2) IAFD 搜索
        async with AsyncHttpClient(timeout=30, proxy=self._proxy) as c:
            r = await _search_iafd_scene(code, c)
        if r:
            logger.info("western scrape %s: found via iafd", code)
            return r

        # 3) ThePornDB（需用户 Key）
        async with AsyncHttpClient(timeout=20, proxy=self._proxy) as c:
            r = await _search_theporndb(code, c, _tpdb_api_key())
        if r:
            logger.info("western scrape %s: found via theporndb", code)
            return r

        return None

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索欧美内容（多源并发，返回全部有效命中）。

        ⚠️ 每个源用**各自的 client** —— 同一 client 跨源连续请求会被
        curl_cffi 原生层静默杀进程（见 _search_iafd_scene docstring 补坑 2）。
        """
        proxy = self._proxy

        async def _aylo() -> Optional[ScrapeResult]:
            async with AsyncHttpClient(timeout=30, proxy=proxy) as c:
                return await _aylo_search(keyword, c, "brazzers")

        async def _iafd() -> Optional[ScrapeResult]:
            async with AsyncHttpClient(timeout=30, proxy=proxy) as c:
                return await _search_iafd_scene(keyword, c)

        async def _tpdb() -> Optional[ScrapeResult]:
            async with AsyncHttpClient(timeout=20, proxy=proxy) as c:
                return await _search_theporndb(keyword, c, _tpdb_api_key())

        out: list[ScrapeResult] = []
        for name, res in zip(
            ("aylo", "iafd", "tpdb"),
            await asyncio.gather(_aylo(), _iafd(), _tpdb(), return_exceptions=True),
        ):
            if isinstance(res, BaseException):
                logger.debug("western %s 搜索异常: %s", name, res)
                continue
            if res and res.is_valid():
                out.append(res)
        return out


@register_crawler
class WesternBulkSearcher(BaseCrawler):
    """欧美批量搜索 — 与 WesternAggregateCrawler 同链路（并发三源）。"""

    name = "western_bulk"
    display_name = "欧美批量"
    base_url = ""

    priority = CrawlerPriority.LOW
    supported_types = ["western"]
    description = "欧美批量搜索（Aylo + IAFD + ThePornDB 并行）"
    language = "en"
    requires_proxy = True

    def __init__(self):
        super().__init__()
        from app.services.proxy_manager import get_effective_proxy_url
        self._proxy = get_effective_proxy_url()

    async def scrape(self, code: str) -> Optional[ScrapeResult]:
        return await WesternAggregateCrawler.scrape(self, code)

    async def search(self, keyword: str) -> list[ScrapeResult]:
        return await WesternAggregateCrawler.search(self, keyword)