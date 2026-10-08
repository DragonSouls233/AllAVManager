"""P1-4 · crawlerx 选择器摘取（首批 5 站，来自 ref155-crawlerx）。

⚠️ 本模块只是**数据抽取**，不是可用爬虫。P1-4 的路线图口径是「把 ref155 的
manifest.json / Selectors.php 翻译为 Python 字典（base_url / 分页 / soft404 /
浏览器头 / 节流区间）」。这些字典是后续「实测能否拿到数据」的输入，**未接入任何
源序**。

🔴 启用硬约束（对齐用户规则：拿不到数据就如实排除，绝不留 0 命中源污染源序）：
- 每个站点默认 `enabled=False`。
- `needs_browser=True` 的站点（Jable / Missav）依赖 Playwright 浏览器抓取，
  MDCX 当前抓取栈（http_client + 代理）无此路径，启用前必须先把浏览器抓取补齐，
  否则必为 0 命中。
- 真正启用须先跑真实抓取样本验证（见 `tmp_scancheck/test_crawlerx_sites.py` 的
  smoke 钩子说明），通过后才把站点写进 `canon.py` 的源序。

抽取字段对齐 manifest.json  operational 段；字段级 CSS（Selectors.php）是下一步，
本批只保留「就绪标记 / soft404 标记」用于后续实测判定页面是否真抓到。

实测结论（2026-10-07 探针，经 socks5://127.0.0.1:10808 代理）：
- caribbeancom / heyzo：✅ 纯 HTTP 可达，listing + 详情页 HTML 正常，title/cover 可解析。
- 字段级演员解析（2026-10-07 实测验证）：
  - **Heyzo ✅ 验证有效**：字段级选择器 `//a[contains(@href,'listpages/actor_') and not(ancestor::div[contains(@class,'relateive-movies')])]` 精确拿本片演员（例 3954→Ayane Nakai），排除相关影片区误抓（全局 a.actor 误抓 6 个含分类 PORN STAR）。
  - **CaribbeanCom ❌ 演员字段缺失**：英文站详情页无 actress 链接（仅导航 AV Idols）、无 dl 信息表 → actor 拿不到；不能凭可达接源序（否则演员空白污染）。actor 源待解决（日文站/actress 搜索）。
- onepondo：❌ 纯 HTTP 返回 13KB 反爬 challenge 壳（<script> 同源 POST 长 base64url 检测），无 /movies/{id} 列表
  → 需浏览器渲染，按硬规则 blocked，不接入源序（与 jable/missav 同类）。
- jable / missav：manifest 标 playwrightFetchEnabled=true，MDCX 无浏览器抓取路径，暂挂。

源数据：`ref155-crawlerx/src/Adapters/{Jable,Missav,CaribbeanCom,Heyzo,OnePondo}/manifest.json`
"""

from __future__ import annotations

from typing import Dict, List

# 浏览器 UA（ref155 统一用 Chrome 131 macOS；各站 browserHeaders 一致，这里归一一份）
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 首批 5 站（纯新站；MDCX 现有源不含这些英文站）
CRAWLERX_FIRST_BATCH: Dict[str, dict] = {
    "jable": {
        "slug": "jable",
        "name": "Jable",
        "base_url": "https://en.jable.tv",
        "pagination": {"strategy": "segment", "param": "page"},
        "listing_url": "https://en.jable.tv/new-release/",
        "detail_url_example": "https://en.jable.tv/videos/fjin-091/",
        "soft404_markers": [
            "page not found", "404 not found",
            "the page you requested was not found",
        ],
        "ready_markers": {
            "listing": [".video-img-box"],
            "detail": ["section.video-info h4"],
        },
        "throttle": {"default": 8, "min": 3, "max": 60},
        "browser_headers": {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8,"
                      "application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "fetch_profile": "browser_likely",
        "needs_browser": True,      # playwrightFetchEnabled=true → MDCX 当前无此路径
        "enabled": False,           # 🔴 默认禁用，实测通过后才翻 True
    },
    "missav": {
        "slug": "missav",
        "name": "MissAV",
        "base_url": "https://missav.ws/en",
        "pagination": {"strategy": "query", "param": "page"},
        "listing_url": "https://missav.ws/en/new",
        "detail_url_example": "https://missav.ws/en/fns-247",
        "soft404_markers": [
            "page not found", "404 not found",
            "the page you requested was not found",
        ],
        "ready_markers": {
            "listing": ["a[href]"],
            "detail": ["h1, h2, meta[property='og:title'], meta[name='title']"],
        },
        "throttle": {"default": 5, "min": 2, "max": 30},
        "browser_headers": {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8,"
                      "application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "fetch_profile": "browser_likely",
        "needs_browser": True,      # playwrightFetchEnabled=true
        "enabled": False,
    },
    "caribbeancom": {
        "slug": "caribbeancom",
        "name": "Caribbeancom",
        "base_url": "https://en.caribbeancom.com",
        "pagination": {"strategy": "path", "param": "page"},
        "listing_url": "https://en.caribbeancom.com/eng/index2.htm",
        "detail_url_example": "https://en.caribbeancom.com/eng/moviepages/080826-001/index.html",
        "soft404_markers": [
            "page not found", "404 not found",
            "the page you requested was not found",
        ],
        "ready_markers": {
            "listing": [".entry, .swiper-slide"],
            "detail": ["#moviepages"],
        },
        "throttle": {"default": 10, "min": 5, "max": 60},
        "browser_headers": None,    # manifest 未给 browserHeaders，用默认 UA 即可
        "fetch_profile": "adaptive",
        "needs_browser": False,     # playwrightFetchEnabled=false → 可纯 HTTP
                "verified_reachable": True,
        "field_parse_pending": True,
        "performer_selectors": [],  # 2026-10-07 实测：英文站详情页无演员字段（无 a[href*=actress] 链接/无 dl 信息表）；actor 源待解决
        "actor_field_missing": True,  # 英文站详情页 actor 字段缺失；不能凭可达接源序（否则演员空白污染元数据）
        "enabled": False,
    },
    "heyzo": {
        "slug": "heyzo",
        "name": "HEYZO",
        "base_url": "https://en.heyzo.com",
        "pagination": {"strategy": "path", "param": "page"},
        "listing_url": "https://en.heyzo.com/listpages/all_1.html",
        "detail_url_example": "https://en.heyzo.com/moviepages/3927/index.html",
        "soft404_markers": [
            "page not found", "404 not found",
            "the page you requested was not found",
        ],
        "ready_markers": {
            "listing": [".movie"],
            "detail": ["a[href*='/moviepages/']"],
        },
        "throttle": {"default": 10, "min": 5, "max": 60},
        "browser_headers": None,
        "fetch_profile": "adaptive",
        "needs_browser": False,
                "verified_reachable": True,
        "field_parse_pending": False,
        "performer_selectors": ["//a[contains(@href,'listpages/actor_') and not(ancestor::div[contains(concat(' ',normalize-space(@class),' '),'relateive-movies')])]"],  # 2026-10-07 实测验证：精确拿本片演员，排除 relateive-movies 相关影片区误抓
        "enabled": True,               # 2026-10-07 crawler 已建（app/crawlers/heyzo.py）并接源序（AUX_SOURCE_ORDER）；字段级解析已验证不污染
    },
    "onepondo": {
        "slug": "onepondo",
        "name": "1Pondo",
        "base_url": "https://en.1pondo.tv",
        "pagination": {"strategy": "query", "param": "page"},
        "listing_url": "https://en.1pondo.tv/list/?o=n",
        # 详情走 JSON API（非 HTML）：dyn/phpauto/movie_details/movie_id/060426_001.json
        "detail_url_example": "https://en.1pondo.tv/dyn/phpauto/movie_details/movie_id/060426_001.json",
        "soft404_markers": [
            "page not found", "404 not found",
            "the page you requested was not found",
        ],
        "ready_markers": {
            "listing": ["body"],
            "detail": ["body"],
        },
        "throttle": {"default": 6, "min": 2, "max": 30},
        "browser_headers": {
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
        },
        "fetch_profile": "adaptive",
        "needs_browser": False,
                "blocked": True,              # 2026-10-07 探针：纯 HTTP 返回反爬 challenge 壳，需浏览器
        "enabled": False,
    },
}


def first_batch_list() -> List[dict]:
    """返回首批 5 站定义列表（按固定顺序）。"""
    order = ["jable", "missav", "caribbeancom", "heyzo", "onepondo"]
    return [CRAWLERX_FIRST_BATCH[s] for s in order]
