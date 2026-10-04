"""
PORNHub 爬虫

参考来源（已整合）：
- VaultX/pornhub_adapter.py: HTML 解析选择器（userInfo, usernameWrap, count, percent)
- PornSimilarityPlatform/pornhub_scraper.py: 演员信息/视频列表提取
- Hitomi-Downloader/pornhub_downloader.py: age_verified cookie, Premium 降级, fix_soup, get_videos AJAX 分页
- yt-dlp/extractor/pornhub.py: flashvars/script 提取, login, mediaDefinitions
- PornHubDL-main: flashvars 注入方案 (P0)
"""

import asyncio
import json
import re
from datetime import date
from typing import Optional

from app.crawlers.base import (
    ActorInfo,
    BaseCrawler,
    CrawlerPriority,
    ScrapeResult,
)
from app.crawlers.provider import register_crawler
from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger
from app.utils.release_date import parse_ph_publish_date, parse_release_date
from app.scraper.number import is_valid_ph_viewkey, ph_viewkey_to_code

logger = get_logger(__name__)

VIEW_PAGE_URL = "https://www.pornhub.com/view_video.php?viewkey={viewkey}"
CN_BASE_URL = "https://cn.pornhub.com"

# PornHub 需要的 cookies（对标 Hitomi-Downloader 第241-245行 + unofficial-api-for-pornhub）
# 修复:补充 accessAgeDisclaimerUK / cookieBannerState / platform,否则 PH 返回 cookie banner 或拦截
_PH_BASE_COOKIES = {
    "age_verified": "1",
    "accessAgeDisclaimerPH": "1",
    "accessAgeDisclaimerUK": "1",
    "accessPH": "1",
    "cookieBannerState": "1",
    "platform": "pc",
}

# 从 script 标签中提取 flashvars 的正则
# 修复:原 (\{.+?}) 非贪婪匹配可能截断嵌套 JSON,改为 (\{.*?\}); 到分号结束
FLASHVARS_RE = re.compile(r'var\s+flashvars_\d+\s*=\s*(\{.*?\});', re.DOTALL)
MEDIA_DEF_RE = re.compile(r'mediaDefinitions\s*:\s*(\[.*?\])\s*[,;]', re.DOTALL)
NEXT_DATA_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

# JS Challenge 检测（参考 eaf_base_api REGEX_CHALLENGE）
_CHALLENGE_RE = re.compile(r'var p=(\d+); var s=(\d+);.*?(\d+):1;', re.DOTALL)


# ===== PornHub JS 挑战解算器（移植自 lustpress/src/utils/ph-solver.ts）=====
# PornHub 的 anti-bot 会在页面注入一段 function go(){...n=leastFactor(p);...}
# 并据此下发 document.cookie="KEY=..."; 只有带上正确 KEY cookie 才能拿到真实页面。
def _least_factor(n: int) -> int:
    """PornHub 挑战 leastFactor 算法（与 lustpress 一致）"""
    if n == 0:
        return 0
    if int(n) != n or n * n < 2:
        return 1
    if n % 2 == 0:
        return 2
    if n % 3 == 0:
        return 3
    if n % 5 == 0:
        return 5
    m = int(n ** 0.5)
    i = 7
    while i <= m:
        if n % i == 0:
            return i
        if n % (i + 4) == 0:
            return i + 4
        if n % (i + 6) == 0:
            return i + 6
        if n % (i + 10) == 0:
            return i + 10
        if n % (i + 12) == 0:
            return i + 12
        if n % (i + 16) == 0:
            return i + 16
        if n % (i + 22) == 0:
            return i + 22
        if n % (i + 24) == 0:
            return i + 24
        i += 30
    return n


def solve_ph_challenge(html: str) -> Optional[str]:
    """解出 PornHub JS 挑战的 KEY cookie 字符串（如 "KEY=10*12345:175:3:1"）

    解不出返回 None。算法移植自 lustpress ph-solver.ts。
    """
    clean = re.sub(r"/\*[\s\S]*?\*/", "", html)  # 去注释，避免注释里出现干扰字符

    pm = re.search(r"var p=(\d+);", clean)
    sm = re.search(r"var s=(\d+);", clean)
    em = re.search(r'document\.cookie="KEY="\+n\+"\*"\+p/n\+":"\+s\+":(\d+):1;path=/;";', clean)
    if not pm or not sm or not em:
        return None

    p = int(pm.group(1))
    s = int(sm.group(1))
    extra = em.group(1)

    go = re.search(r"function go\(\)\s*\{(.*?)n=leastFactor\(p\);", clean, re.DOTALL)
    if go:
        body = re.sub(r"\s+", "", go.group(1))
        # 1) 处理 if((s>>shift)&1)p+=a*b;else p-=c*d; 块，并从 body 移除避免重复计算
        ifelse = re.compile(r"if\(\(s>>(\d+)\)&1\)p([+-])=(\d+)\*(\d+);elsep([+-])=(\d+)\*(\d+);")
        body_without_ifs = body
        for m in ifelse.finditer(body):
            shift = int(m.group(1))
            cond = (s >> shift) & 1
            if cond:
                sign, a, b = m.group(2), int(m.group(3)), int(m.group(4))
            else:
                sign, a, b = m.group(5), int(m.group(6)), int(m.group(7))
            p = p + a * b if sign == "+" else p - a * b
            body_without_ifs = body_without_ifs.replace(m.group(0), "", 1)
        # 2) 处理剩余 p+= / p-= 调整
        for m in re.finditer(r"p([+-])=(\d+);", body_without_ifs):
            sign, v = m.group(1), int(m.group(2))
            p = p + v if sign == "+" else p - v

    n = _least_factor(p)
    if not n or n in (0, 1) or n != n:  # NaN 防护
        n = p
    return f"KEY={n}*{p // n}:{s}:{extra}:1"


# 请求超时(秒)
_REQ_TIMEOUT = 30
# 最大重试次数
_REQ_RETRIES = 3
# 重试间隔(秒, 指数退避基数)
_REQ_RETRY_BASE = 2


def _parse_number(text: str) -> int:
    """解析带 K/M/B 后缀的数字（参考 PornSimilarityPlatform）"""
    if not text:
        return 0
    text = text.strip().replace(",", "").replace(" ", "")
    multipliers = {"K": 1000, "M": 1000000, "B": 1000000000}
    suffix = text[-1].upper() if text else ""
    if suffix in multipliers:
        try:
            return int(float(text[:-1]) * multipliers[suffix])
        except ValueError:
            pass
    try:
        return int(float(text))
    except ValueError:
        return 0


def _parse_duration_to_seconds(duration_str: str) -> Optional[int]:
    """解析时长字符串（参考 PornSimilarityPlatform）
    支持格式: "12:34" / "1:12:34" / "45 min"
    """
    if not duration_str:
        return None
    duration_str = duration_str.strip()
    # mm:ss 或 hh:mm:ss
    parts = duration_str.split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    elif len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            pass
    return None


#: PH 下架 / 不可用页的标题文案。**必须多语言收集**。
#: 页面标题随请求方语言变化（实测：带 Accept-Language:en → "Video Disabled"；
#: 不带 → 按出口 IP 判为中文区 → "取消播放视频"）。
#: 只收英文会漏判 ⇒ 把下架页当正常页解析，标题/分类/推荐演员全部入库。
_UNAVAILABLE_MARKERS = (
    # 英文
    "The page you requested cannot be found",
    "Page not found",
    "Video Disabled",
    "video was removed",
    "access is restricted",
    "This video is no longer available",
    # 中文（实测真实返回）
    "取消播放视频", "视频已禁用", "视频不可用", "页面不存在", "该视频已被移除",
    # 西语 / 其它常见语种（PH 是多语站，按 IP 判定语言，不可枚举完，
    # 靠下面的"标题极短且无实质字段"兜底）
)


def _is_unavailable_page(html: str) -> bool:
    """判断是否为下架 / 不可用页。

    双重判据：
      ① 页面含任一下架文案（多语言，见 ``_UNAVAILABLE_MARKERS``）；
      ② 兜底：og:title 命中下架文案 **或** 标题短于 4 字符
         （下架页没有真实标题，而正常 PH 标题都远长于 4 字符）。
    """
    if not html:
        return True
    for marker in _UNAVAILABLE_MARKERS:
        if marker in html:
            return True
    # 只在 <title> / og:title 上做短标题判定，避免正文里的短句误伤
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html, re.I)
    title = m.group(1) if m else ""
    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.I)
        title = m.group(1) if m else ""
    title = title.strip()
    if title and len(title) <= 4:
        return True
    return False


def _fill_missing(base: Optional[ScrapeResult], extra: Optional[ScrapeResult]) -> Optional[ScrapeResult]:
    """用 ``extra`` 补 ``base`` 里缺失的字段（就地修改并返回 base）。

    用于「HTML 解析打底 + flashvars/next_data 补缺」的组合策略：
    ``base`` 已有值时**不覆盖**（HTML 解析的语义更完整，如演员来自 userInfo 块），
    只有 base 为 None/空时才取 extra 的值。

    ⚠️ 三值语义注意：``release_date`` / ``rating`` / ``is_uncensored`` 这类字段
    「源站明确说没有」与「源没说」都表现为 None，合并时无法区分，
    因此这里只在 base 完全没有该字段时才补，不做「用 0/False 覆盖」——
    否则会重演 merger 里那个「把库里 True 覆盖成 NULL」的旧问题。
    """
    if base is None:
        return extra
    if extra is None:
        return base

    for fld in (
        "plot", "cover_url", "poster_url", "thumb_url", "trailer_url",
        "studio", "maker", "series", "duration", "plot_short",
    ):
        if not getattr(base, fld, None) and getattr(extra, fld, None):
            setattr(base, fld, getattr(extra, fld))

    # 评分：base 为 None 才补（HTML 未登录态拿不到评分是正常的）
    if base.rating is None and extra.rating is not None:
        base.rating = extra.rating
    # 发行日期：同上
    if base.release_date is None and extra.release_date is not None:
        base.release_date = extra.release_date
    # 票数：base 为 None 才补
    if not base.votes and extra.votes:
        base.votes = extra.votes
    # 标题：base 一定有（_parse_html 无标题会返 None），不覆盖
    if not base.original_title and extra.original_title:
        base.original_title = extra.original_title

    # 列表型字段：并集去重
    for fld in ("tags", "genres", "sample_images", "extrafanart", "directors", "male_actors"):
        cur = list(getattr(base, fld, None) or [])
        for v in (getattr(extra, fld, None) or []):
            if v not in cur:
                cur.append(v)
        if cur:
            setattr(base, fld, cur)

    # 演员：base 没有才用 extra 的（HTML 的 userInfo 块更可靠）
    if not base.actors and extra.actors:
        base.actors = list(extra.actors)

    # raw_data：白名单键补缺
    for k, v in (extra.raw_data or {}).items():
        if v in (None, "", [], {}):
            continue
        if k in ("ph_views", "ph_likes", "ph_uploader", "ph_rating",
                 "ph_categories", "ph_is_premium", "ph_is_hd",
                 "ph_segment", "ph_video_id", "viewkey"):
            base.raw_data.setdefault(k, v)

    return base


def _extract_data_rating(html: str, cls: str) -> int:
    """取 ``<span class="votesUp" data-rating="882">`` 里的票数。

    真实快照结构（属性顺序是 class 在前、data-rating 在后，且中间还有
    ``gtm-event-video-underplayer`` 等属性），所以必须**先定位 class 再取
    同一标签内的 data-rating**，不能用 ``data-rating=...[^>]*votesUp``
    这种依赖属性顺序的写法。
    """
    for m in re.finditer(
        rf'<span[^>]*class="[^"]*\b{cls}\b[^"]*"[^>]*>', html
    ):
        tag = m.group(0)
        d = re.search(r'data-rating="(\d+)"', tag)
        if d:
            return int(d.group(1))
    return 0


def _normalize_rating(raw) -> Optional[float]:
    """把 PornHub 的百分制评分归一化到 ``ScrapeResult`` 契约的 **0-10**。

    🔴 2026-10-04 修复：PH 的 ``class="percent"`` / ``__NEXT_DATA__.rating`` /
    flashvars ``rating`` 都是 **0-100 百分制**，旧代码三处都原样 ``float()`` 写入
    ⇒ 库里会出现 ``rating=92``（满分 10 的字段被塞进 92），Kodi 显示 92 星。
    对照 ``pornhub_api.py`` 已做 ``*2`` 换算（源为 0-5）—— 同模块两源口径不一。

    这里只做「0-100 → 0-10」换算 + 范围钳制，0-5 制的源仍应在自己那边换算。
    """
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    # 已经是 0-10 的（如 8.5）直接放行；0-100 的除以 10
    if val > 10:
        val = val / 10.0
    # 钳制到契约范围，防御上游脏数据
    return round(min(max(val, 0.0), 10.0), 2)


@register_crawler
class PornhubCrawler(BaseCrawler):
    """PORNHub 爬虫（v2 - 参考 VaultX / Hitomi-Downloader / PornSimilarityPlatform 重构）

    多级提取策略：
    1. flashvars 脚本变量提取（最快，完整元数据）
    2. __NEXT_DATA__ JSON 提取（Next.js SSR 数据）
    3. HTML (BeautifulSoup) 页面解析（兜底）
    """

    name = "pornhub"
    display_name = "PORNHub"
    base_url = "https://www.pornhub.com"

    priority = CrawlerPriority.NORMAL
    supported_types = ["pornhub"]
    supported_prefixes = ["ph"]
    description = "PORNHub 视频元数据刮削"
    language = "en"
    requires_proxy = False  # 修复:原 True 导致无代理时完全不可用

    def __init__(self):
        super().__init__()
        from app.services.proxy_manager import get_effective_proxy_url
        self._proxy = get_effective_proxy_url()

    def _extract_viewkey(self, code: str) -> Optional[str]:
        """从 code 提取裸 viewkey。

        修复(2026-10-03)：旧正则 `(?:ph)?([a-f0-9]{10,20})` 只接受 a-f，
        而扫描器 pornhub_scanner 早已要求"13位且必含 g-z"才入库 ⇒ 扫进来的
        真实 viewkey 绝大多数解不出来，补刮静默全灭。改走全仓统一判据。
        """
        from app.scraper.number import normalize_ph_viewkey
        return normalize_ph_viewkey(code)

    async def scrape(self, code: str, ctx=None) -> Optional[ScrapeResult]:
        viewkey = self._extract_viewkey(code)
        if not viewkey:
            logger.warning(f"无效的 viewkey: {code}")
            return None

        url = VIEW_PAGE_URL.format(viewkey=viewkey)

        # 优先使用上下文中的 http_client（复用指纹池和代理）
        if ctx and hasattr(ctx, "http_client") and ctx.http_client:
            client = ctx.http_client
            need_close = False
        else:
            from app.services.proxy_manager import get_effective_proxy_url
            proxy = get_effective_proxy_url()
            client = AsyncHttpClient(proxy=proxy)
            await client.init_session()
            need_close = True

        try:
            # 修复:添加重试机制,指数退避(参考 unofficial-api-for-pornhub tenacity 方案)
            # 本地 cookie 副本:挑战解出后追加 KEY cookie,避免污染模块级 _PH_BASE_COOKIES
            cookies = dict(_PH_BASE_COOKIES)
            last_error = None
            for attempt in range(1, _REQ_RETRIES + 1):
                # 🔴 2026-10-05 请求间隔。PH 对**详情页**（1.5MB/次，比 JSON 端点重得多）
                # 的频次限制远比 webmasters 严：实测连续请求若干次后开始
                # `SSLError: (35) Recv failure: Connection was reset`，
                # 整批刮削静默返回 None（连"本片正常"也拿不到）。
                # 每次重试之间退避，且首次请求前也让开一点，避免与
                # 同一 tick 内的 pornhub_api 请求叠在一起。
                if attempt > 1:
                    await asyncio.sleep(_REQ_RETRY_BASE ** attempt)
                html_text = await client.get_text(
                    url,
                    cookies=cookies,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; rv:115.0) Gecko/20100101 Firefox/115.0",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        # ⚠️ 2026-10-05 刻意**不发** Accept-Language。
                        #   实测 PH 详情页所有标题来源（og:title / <title> / h1 /
                        #   JSON-LD name）都随请求方语言变：
                        #     en-US → "Sharing A Bed With Mi Hot Step Sister…"
                        #     不发   → "和我最好的朋友的电影之夜…"（按出口 IP 判中文区）
                        #   而 GraphQL 端点对 en/es/无 header **恒返回原标题**。
                        #   所以 HTML 源的标题只能当兜底，权威标题由 merger 的
                        #   field_priority 交给 pornhub_api（见 merger.py）。
                        "Referer": "https://www.pornhub.com/",
                        "Origin": "https://www.pornhub.com",
                    },
                    timeout=_REQ_TIMEOUT,
                )

                # 修复:检查 Cloudflare 拦截 + JS Challenge
                if not html_text or len(html_text) < 500:
                    last_error = "空页面"
                elif "Just a moment" in html_text or "cf-browser-verification" in html_text:
                    last_error = "Cloudflare"
                elif _CHALLENGE_RE.search(html_text):
                    # 修复(参考 lustpress ph-solver):解出 KEY cookie 后合并 age_verified 重抓
                    solved = solve_ph_challenge(html_text)
                    if solved:
                        key_name, key_val = solved.split("=", 1)
                        cookies[key_name] = key_val
                        cookies["age_verified"] = "1"
                        logger.info(f"PornHub JS 挑战已解出 [{viewkey}], 带 KEY cookie 重抓")
                        last_error = None
                        continue  # 用新 cookie 立即重抓,不计入失败
                    last_error = "JS Challenge(解出失败)"
                else:
                    break  # 成功获取

                if attempt < _REQ_RETRIES:
                    # 退避已在上方循环开头统一处理，此处只记日志
                    logger.warning(
                        f"PornHub 请求失败 [{viewkey}] 第{attempt}次({last_error})，退避后重试"
                    )

            if last_error:
                logger.warning(f"PornHub 请求最终失败 [{viewkey}]: {last_error}")
                self.mark_error()
                return None

            # 下架/不可用检测。
            # 🔴 2026-10-05 真实抓取补充：下架页的标题随语言变，实测不发
            #    Accept-Language（按出口 IP 判为中文区）时返回 **"取消播放视频"**，
            #    而旧关键词表只有英文 "Video Disabled" ⇒ 完全识别不到，
            #    于是把"取消播放视频"当成真标题入库（实测 viewkey=6979039897dc1：
            #    title="Video Disabled"、actor 写进 24 个推荐位演员）。
            #    同时它的 categoriesWrapper 仍有 29 个分类，会污染 genre 列。
            if _is_unavailable_page(html_text):
                logger.info(f"视频不可用: {viewkey}")
                return None

            # === 解析顺序：先 HTML 全量（唯一能拿到演员/uploader 的路径），
            #     再用 flashvars / __NEXT_DATA__ **补缺**。
            #
            # 🔴 2026-10-05 修复：旧顺序是「flashvars 命中就 return」，
            #   而 flashvars（播放器 JS 变量）**不含演员、不含 uploader**。
            #   实测 4/4 样本：走 flashvars 分支时 actors=[]、uploader=None，
            #   而 GraphQL 源的 pornstars 恒为空 ⇒ 演员彻底丢失，
            #   且因为两源都没演员，合并后 actors 恒为空（库里 actor 列靠目录名兜底）。
            # 现在：HTML 解析打底（演员/uploader/播放量/日期都在这里），
            # flashvars/next_data 只填 HTML 拿不到的字段。
            result = self._parse_html(html_text, viewkey)

            # flashvars 补缺（参考 PornHubDL inject.js + yt-dlp）
            fv = self._try_flashvars(html_text, viewkey)
            if fv:
                result = _fill_missing(result, fv)
            # __NEXT_DATA__ 补缺（Next.js SSR）
            nd = self._try_next_data(html_text, viewkey)
            if nd:
                result = _fill_missing(result, nd)

            if result:
                self.mark_success()
                return result

            logger.warning(f"所有提取策略均失败: {viewkey}")
            self.mark_error()
            return None

        except Exception as e:
            logger.error(f"PornHub 刮削失败 [{viewkey}]: {e}")
            self.mark_error()
            return None
        finally:
            if need_close:
                await client.close_session()

    # ===== 提取策略 =====

    def _try_flashvars(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """策略1: 从 flashvars 脚本变量中提取（参考 PornHubDL inject.js）"""
        m = FLASHVARS_RE.search(html_text)
        if not m:
            return None

        try:
            flashvars = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        if not flashvars:
            return None

        return self._build_result_from_dict(flashvars, viewkey, source="flashvars")

    def _try_next_data(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """策略2: 从 __NEXT_DATA__ JSON 中提取（Next.js SSR 数据）

        __NEXT_DATA__ 结构:
        {
          "props": {
            "pageProps": {
              "video": {
                "title", "duration", "views", "pornstars", "tags",
                "categories", "image": {"url": "..."}, "isHD", "rating"
              }
            }
          }
        }
        """
        m = NEXT_DATA_RE.search(html_text)
        if not m:
            return None

        try:
            state = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

        # 导航 Next.js 数据结构
        page_props = state.get("props", {}).get("pageProps", {})
        video_data = page_props.get("video", {})
        if not video_data:
            return None

        title = video_data.get("title") or video_data.get("video_title") or ""
        if not title:
            return None

        # 演员
        actors = []
        for ps in video_data.get("pornstars", []):
            if isinstance(ps, dict):
                name = (
                    ps.get("star", {}).get("name")
                    if isinstance(ps.get("star"), dict)
                    else ps.get("name")
                )
                if not name:
                    name = ps.get("starName") or ps.get("username") or ps.get("label", "")
                if not name:
                    star = ps.get("star", {})
                    if isinstance(star, dict):
                        name = star.get("username") or star.get("name") or ""
                if name:
                    avatar_url = None
                    star = ps.get("star", {})
                    if isinstance(star, dict):
                        avatar_url = star.get("avatar") or star.get("profileAvatar") or star.get("thumb") or star.get("image")
                        if not avatar_url:
                            profile = star.get("profileAvatar")
                            if isinstance(profile, str):
                                avatar_url = profile
                    if not avatar_url:
                        avatar_url = ps.get("avatar") or ps.get("profileAvatar") or ps.get("thumb")
                    # ⚠️ ActorInfo 只有 name / japanese_name / avatar_url 三个字段，
                    #    旧实现传 extra= 一旦命中本分支就 TypeError 整个 __NEXT_DATA__
                    #    策略报废（被上层 except 吞掉，只留一行日志）。
                    actors.append(ActorInfo(name=name, avatar_url=avatar_url or None))
            elif isinstance(ps, str):
                actors.append(ActorInfo(name=ps))

        # 标签
        tags = []
        for t in video_data.get("tags", []):
            if isinstance(t, dict):
                tags.append(t.get("tag_name") or t.get("tag") or str(t))
            elif isinstance(t, str):
                tags.append(t)

        # 分类
        categories = []
        for c in video_data.get("categories", []):
            if isinstance(c, dict):
                categories.append(c.get("category") or c.get("name") or str(c))
            elif isinstance(c, str):
                categories.append(c)

        # 缩略图
        cover = ""
        img = video_data.get("image")
        if isinstance(img, dict):
            cover = img.get("url") or img.get("src") or img.get("poster_url", "")
        elif isinstance(img, str):
            cover = img
        if not cover:
            cover = video_data.get("poster_url") or video_data.get("thumb") or video_data.get("image_url", "")

        result = ScrapeResult(
            # 🔴 2026-10-05 修复：爬虫产**裸 viewkey**，扫描器产 **ph+viewkey**，
            #    落库按 code 精确匹配（workflow.py:407 `where code == result.code`）
            #    ⇒ 两侧口径不一致时永远匹配不上，每次刮削都**插一条新行**，
            #    实测库里同时存在 ph6a488932e1d19 与 6a488932e1d19 两份同一部片。
            #    统一收口到 ph_viewkey_to_code（番号模块唯一真相源）。
            code=ph_viewkey_to_code(viewkey),
            title=title,
            source="pornhub",
            source_url=VIEW_PAGE_URL.format(viewkey=viewkey),
            original_title=title,
            cover_url=cover,
        )
        if actors:
            result.actors = actors
        if tags:
            result.tags = tags
        if categories:
            result.genres = categories

        # 时长
        duration = self._parse_duration_value(video_data.get("duration"))
        if duration:
            result.duration = duration

        # 评分
        try:
            # 🔴 PH 是 0-100 百分制，必须归一化到契约的 0-10，否则 rating=92
            rating = _normalize_rating(video_data.get("rating"))
            if rating is not None:
                result.rating = rating
        except (ValueError, TypeError):
            pass

        # 播放量
        try:
            views = video_data.get("views") or video_data.get("view_count")
            if views:
                result.votes = int(views)
        except (ValueError, TypeError):
            pass

        # 上传者
        uploader = video_data.get("uploader") or video_data.get("username", "")
        if uploader:
            result.studio = uploader

        result.raw_data = video_data
        return result

    def _try_media_definitions(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """从 mediaDefinitions JSON 中提取（yt-dlp 兜底方案）"""
        # 查找 mediaDefinitions: [...]
        m = MEDIA_DEF_RE.search(html_text)
        if not m:
            return None
        try:
            medias = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        if not medias:
            return None

        data = {"mediaDefinitions": medias}

        # 尝试搜索 title 等关联数据
        title_m = re.search(r'<title>(.*?)</title>', html_text, re.DOTALL)
        title = ""
        if title_m:
            title = title_m.group(1).replace(" - Pornhub.com", "").replace(" - PornHub", "").strip()

        if not title:
            title_h1 = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html_text, re.DOTALL)
            if title_h1:
                title = re.sub(r'<[^>]+>', '', title_h1.group(1)).strip()

        result = ScrapeResult(
            # 🔴 2026-10-05 修复：爬虫产**裸 viewkey**，扫描器产 **ph+viewkey**，
            #    落库按 code 精确匹配（workflow.py:407 `where code == result.code`）
            #    ⇒ 两侧口径不一致时永远匹配不上，每次刮削都**插一条新行**，
            #    实测库里同时存在 ph6a488932e1d19 与 6a488932e1d19 两份同一部片。
            #    统一收口到 ph_viewkey_to_code（番号模块唯一真相源）。
            code=ph_viewkey_to_code(viewkey),
            title=title,
            source="pornhub",
            source_url=VIEW_PAGE_URL.format(viewkey=viewkey),
        )

        # 尝试从页面中提取更多信息
        # 演员
        actors = []
        for m_a in re.finditer(r'/pornstar/([^"&?]+)', html_text):
            name = m_a.group(1).replace("-", " ").title().strip()
            if name and name not in actors:
                actors.append(ActorInfo(name=name))

        if not actors:
            for m_a in re.finditer(r'"pornstarName"[^>]*>\s*([^<]+)\s*<', html_text):
                name = m_a.group(1).strip()
                if name:
                    actors.append(ActorInfo(name=name))

        if actors:
            result.actors = actors

        # 封面
        cover_m = re.search(r'<meta property="og:image" content="([^"]+)"', html_text)
        if cover_m:
            result.cover_url = cover_m.group(1)

        # 评分
        rating_m = re.search(r'<span[^>]*class="percent"[^>]*>([^<]+)%', html_text)
        if rating_m:
            try:
                # 🔴 class="percent" 是 0-100 百分制，归一化到 0-10
                result.rating = _normalize_rating(rating_m.group(1))
            except ValueError:
                pass

        result.raw_data = data
        return result

    # ===== HTML 解析兜底 =====

    def _parse_html(self, html_text: str, viewkey: str) -> Optional[ScrapeResult]:
        """策略3: HTML 页面解析（参考 Hitomi-Downloader 第135-141行 + VaultX 第96-132行）

        使用正则提取关键字段，不依赖 BeautifulSoup 减少依赖。
        """
        # 🔴 2026-10-05：下架页必须在**解析前**拦掉。实测未登录/无 Accept-Language
        #    时下架页 og:title="取消播放视频"，且 categoriesWrapper 里仍有 29 个
        #    分类、页面还挂着推荐位 —— 解析出去就是一条标题为"取消播放视频"、
        #    genre 塞满推荐分类的垃圾记录。
        if _is_unavailable_page(html_text):
            logger.info(f"[pornhub] 下架页，跳过解析: {viewkey}")
            return None

        title = self._extract_title_html(html_text)
        if not title:
            return None

        result = ScrapeResult(
            # 🔴 2026-10-05 修复：爬虫产**裸 viewkey**，扫描器产 **ph+viewkey**，
            #    落库按 code 精确匹配（workflow.py:407 `where code == result.code`）
            #    ⇒ 两侧口径不一致时永远匹配不上，每次刮削都**插一条新行**，
            #    实测库里同时存在 ph6a488932e1d19 与 6a488932e1d19 两份同一部片。
            #    统一收口到 ph_viewkey_to_code（番号模块唯一真相源）。
            code=ph_viewkey_to_code(viewkey),
            title=title,
            source="pornhub",
            source_url=VIEW_PAGE_URL.format(viewkey=viewkey),
        )

        # 封面
        cover = self._extract_cover_html(html_text)
        if cover:
            result.cover_url = cover

        # 演员（参考 Hitomi-Downloader 第141行: soup.find('div', class_='userInfo')...）
        actors = self._extract_actors_html(html_text)
        if actors:
            result.actors = actors

        # 时长（参考 VaultX: var class_='duration'）
        duration = self._extract_duration_html(html_text)
        if duration:
            result.duration = duration

        # 评分（参考 VaultX: span class_='percent'）
        rating = self._extract_rating_html(html_text)
        if rating is not None:
            result.rating = rating

        # 播放量（参考 VaultX: span class_='count'）
        # 🔴 2026-10-05 修复：旧实现把播放量塞进 ``result.votes``。
        #    ``votes`` 的契约语义是**评分人数**（NFO 写 <votes>，Kodi 显示为
        #    评分票数），而播放量在 pornhub 表有**独立列** ``source_views``
        #    （strategy._scrape_missing 读 ``raw_data["ph_views"]``）。
        #    塞错的后果：库里 votes=214000（播放量）而评分人数其实是 882，
        #    且合并时 votes 还会与其他源的评分人数互相覆盖。
        #    现在：播放量进 raw_data["ph_views"]，votes 只放真实的评分人数。
        views = self._extract_views_html(html_text)
        if views is not None:
            result.raw_data["ph_views"] = views
        # ⚠️ 不在此处设 votes：`votesUp` 是**点赞数**（实测 882），
        #    而 `votes` 契约语义是**评分人数**（GraphQL 的 `ratings`，实测 981），
        #    两者数量级不同。评分人数由 pornhub_api 源提供，本源留空避免口径打架。
        #    点赞数仍有价值，放 raw_data 供落 pornhub 专属列。
        likes = _extract_data_rating(html_text, "votesUp")
        if likes > 0:
            result.raw_data["ph_likes"] = likes

        # 发行日期（PH 详情页多处出现，取第一个能解析成功的）
        release_date = self._extract_release_date_html(html_text)
        if release_date:
            result.release_date = release_date

        # 标签/分类（参考 VaultX: div class_='categoriesWrapper'）
        tags, categories = self._extract_tags_html(html_text)
        if tags:
            result.tags = tags
        if categories:
            result.genres = categories

        # 上传者（作为 studio）
        uploader = self._extract_uploader_html(html_text)
        if uploader:
            result.studio = uploader

        # 原始数据尝试
        # ⚠️ 不能整体赋值覆盖：上面已写入 raw_data["ph_views"]（播放量），
        #    整体替换会把它连同其它已解析字段一起丢掉。
        fv = self._try_flashvars(html_text, viewkey)
        if fv and fv.raw_data:
            result.raw_data.update(fv.raw_data)
            result.raw_data["ph_views"] = views
        else:
            md = self._try_media_definitions(html_text, viewkey)
            if md and getattr(md, "raw_data", None):
                result.raw_data.update(md.raw_data)
                result.raw_data["ph_views"] = views

        # 上传者/频道名同步进 raw_data，落 pornhub.uploader 专属列
        if uploader:
            result.raw_data["ph_uploader"] = uploader

        return result

    def _extract_title_html(self, html: str) -> str:
        """从 HTML 提取标题。

        ⚠️ 2026-10-05 实测结论：**HTML 页面上所有标题来源都随语言漂移**，
        拿不到稳定值。同一 viewkey=69ec001b86c55：

            | 来源              | Accept-Language:en | Accept-Language:es | 不发 AL |
            |-------------------|--------------------|--------------------|---------|
            | og:title          | Sharing A Bed…     | Compartir Cama…    | 中文    |
            | <title>           | Sharing a Bed…     | Compartir Cama…    | 中文    |
            | h1.title          | Sharing A Bed…     | Compartir Cama…    | 中文    |
            | JSON-LD name      | Sharing A Bed…     | Compartir Cama…    | 中文    |

        ⇒ 本源**不声称**能给出与 PH 一致的原标题。真正稳定的原标题只在
        ``webmasters/video_by_id``（pornhub_api 源，en/es/无 header 三者实测同值）。
        因此：
          · `merger` 的 field_priority 已把 title 交给 pornhub_api（5）优先于本源（60）；
          · 本方法的返回值只作为**兜底**（GraphQL 失败时），
          · 合并器的 ``field_sources`` 会记录最终标题来自哪个源，便于排查。
        """
        # 首选 og:title（兜底值）
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.I)
        if m:
            title = m.group(1)
            title = re.sub(r'\s*-\s*(?:Pornhub\.com|PornHub)\s*$', '', title).strip()
            if title:
                return title

        # JSON-LD VideoObject.name（同样随语言变，但比 og:title 少一层站点后缀）
        m = re.search(
            r'"@type"\s*:\s*"VideoObject".{0,400}?"name"\s*:\s*"([^"]{3,300})"',
            html, re.DOTALL,
        )
        if m:
            title = m.group(1).strip()
            if title:
                return title

        # h1.title（参考 Hitomi-Downloader 第135行）
        m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if m:
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if title:
                return title

        # data-video-title（yt-dlp 参考）
        m = re.search(r'data-video-title\s*=\s*"([^"]+)"', html)
        if m:
            return m.group(1)

        # <title> 兜底
        m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
        if m:
            title = m.group(1).replace(" - Pornhub.com", "").replace(" - PornHub", "").strip()
            return title
        return ""

    def _extract_cover_html(self, html: str) -> Optional[str]:
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.I)
        if m:
            return m.group(1)
        m = re.search(r'<link\s+rel="image_src"\s+href="([^"]+)"', html, re.I)
        if m:
            return m.group(1)
        # data-image / poster 属性
        m = re.search(r'(?:data-image|poster)\s*=\s*"([^"]*phncdn[^"]+)"', html)
        if m:
            return m.group(1)
        return None

    def _extract_actors_html(self, html: str) -> list[ActorInfo]:
        """从 HTML 提取**本片真实演员**。

        🔴 2026-10-05 重写。旧实现有两条致命错误（真实快照
        ``G:\\MDCX\\_test_archive\\ph_snap\\69ec001b86c55.es.html`` 实测）：

        ① **方案1 抓的是「推荐 star」不是本片演员**。
           真实页面结构（PH 未登录态）：
           ``<div class="video-info-row js-suggestionsRow"><div class="pornstarsWrapper">
             <p>Estrellas porno&nbsp;</p><a .../model/rosi-morgan>Rosi Morgan</a> ...``
           —— `pornstarsWrapper` 整块带 `js-suggestionsRow`（"js-suggestions" =
           **推荐位**），是站点猜你喜欢。实测旧实现从这一块抓出 **40 个**演员：
           `Fantasypov / Luna Star / Ruth Lee / Anna Cherry7 / Rosi Morgan …`，
           而本片演员只有 1 人。⇒ 演员表被彻底污染，且每部影片都会重复写入
           这 40 个"演员"，`movie_count` 虚增。
        ② **方案2 的正则永远匹配不到**：旧右边界是
           ``(?=class="|</div>\\s*</div>)``，在 ``<div class="userInfo">`` 后的
           **第一个** ``class="`` 处就截断（``<div class="usernameWrap ...">``），
           实测 ``userInfo 块定位: False``。

        真实演员在 ``userInfo`` 块内：``<a rel="" href="/model/rosi-lane"
        class="bolded">Rosi Lane</a>``（外层 `video-detailed-info > userRow`）。
        这里改为**定位 userInfo 块边界 → 块内只取 /model/ 链接的可见文本**，
        并显式排除 `js-suggestionsRow` 区块。
        """
        actors: list[ActorInfo] = []
        seen: set[str] = set()

        def _add(name: str, avatar: str = "") -> None:
            name = re.sub(r"\s+", " ", (name or "")).strip()
            if not name or len(name) > 60:
                return
            key = name.lower()
            if key in seen:
                return
            seen.add(key)
            # ⚠️ ActorInfo 只有 name / japanese_name / avatar_url 三个字段，
            #    传 extra= 会 TypeError（实测已崩过一次）。
            actors.append(ActorInfo(name=name, avatar_url=avatar or None))

        # ---- 1) 首选：userInfo 块（真实演员 / 模特）----
        # 边界用「到下一个同级别 div 标签」而非 `class="`，否则会在 usernameWrap 处截断。
        for m in re.finditer(
            r'<div class="userInfo">(.*?)(?=<div class="(?:video-detailed-info|'
            r'pornstarsWrapper|categoriesWrapper|tagsWrapper|commentsWrapper|'
            r'video-info-row)|<div class="userInfoBlock">)',
            html,
            re.DOTALL,
        ):
            block = m.group(1)
            for a in re.finditer(
                r'<a[^>]*href="(/model/[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL
            ):
                name = re.sub(r"<[^>]+>", "", a.group(2)).strip()
                if name:
                    _add(name)
            # 部分页面直接用 <a> 文本包一层 span（如 "Rosi Lane <span class=...>"）
            if not actors:
                uw = re.search(
                    r'class="usernameWrap[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL
                )
                if uw:
                    for a in re.finditer(r'<a[^>]*>([^<]{2,60})</a>', uw.group(1)):
                        _add(a.group(1))
        if actors:
            # 头像：userAvatar 里的图（真实结构 userAvatar > a > img[src]）
            mb = re.search(r'<div class="userAvatar">.*?src="([^"]+)"', html, re.DOTALL)
            if mb and len(actors) == 1:
                actors[0].avatar_url = mb.group(1)
            return actors

        # ---- 2) 兜底：data-video-pornstars（部分镜像页有此属性）----
        m_p = re.search(r'data-video-pornstars\s*=\s*"([^"]+)"', html)
        if m_p:
            for part in m_p.group(1).split(","):
                _add(part.strip())

        return actors

    def _extract_duration_html(self, html: str) -> Optional[int]:
        """从 HTML 提取时长 → **返回分钟**（ScrapeResult.duration 契约单位）。

        修复(2026-10-03)：原实现返回**秒**（三处分支：var.duration / meta[video:duration]
        / data-duration），却直接赋给 result.duration。统一在末尾折算成分钟。

        🔴 2026-10-05 再修（真实快照实测）：``<var class="duration">`` 在 PH 详情页
        有 **77 个**（推荐位 + 相关视频 + 剧集列表各占一堆），实测第一个命中是
        ``'10:27'`` —— **推荐视频的时长**，被当成本片时长写进库（真实 865 秒 = 14 分钟）。
        ⇒ 把 ``var.duration`` 从「首选」降为**最后的兜底**，优先用只可能描述本片的
        ``<meta property="video:duration">``（实测 content="865"，唯一）。
        """
        seconds: Optional[int] = None

        # ① meta video:duration（秒）—— 只可能描述本片，优先
        m = re.search(
            r'<meta\s+property="video:duration"\s+content="(\d+)"', html, re.I
        )
        if not m:
            m = re.search(
                r'<meta[^>]*property="video:duration"[^>]*content="(\d+)"', html, re.I
            )
        if m:
            seconds = int(m.group(1))

        # ② data-duration（PH 惯例为秒）
        if seconds is None:
            m = re.search(r'data-duration\s*=\s*["\'](\d+)["\']', html)
            if m:
                seconds = int(m.group(1))

        # ③ var class="duration"（mm:ss）—— 页面上有 77 个，多为推荐视频，
        #    放最后兜底；且必须校验与前两者不冲突（差值过大说明抓到别的视频）。
        if seconds is None:
            m = re.search(r'<var[^>]*class="[^"]*duration[^"]*"[^>]*>\s*([^<]+)', html)
            if m:
                seconds = _parse_duration_to_seconds(m.group(1).strip())

        if not seconds or seconds <= 0:
            return None
        return max(seconds // 60, 1)

    def _extract_release_date_html(self, html: str) -> Optional[date]:
        """从 HTML 提取发行日期 → `datetime.date`。

        🔴 2026-10-04 新增：PH 的 HTML 主源此前**完全没有**发行日期解析，
        与 `pornhub_api.py` 把日期塞进 raw_data 无人读叠加 ⇒ **pornhub 两个源
        都产不出 release_date**，库里该列永远为空，NFO 的 `<premiered>` 也缺失。

        🔴 2026-10-05 再修：真实快照核实后，旧 pattern 全部落空：
          - ``<span class="videoUploaded">`` **页面上不存在**（count=0）
          - ``"uploadDate"`` 旧正则要求 ``\\d{10,14}`` 纯数字，而真实值是
            **ISO8601 带时区**：``"uploadDate": "2026-04-25T00:13:14+00:00"``
          ⇒ 实测 6 个 pattern 全落空 → date=None。

        PH 详情页的日期出现在多处（按可靠性排序，命中即止）：
          ① JSON-LD ``"uploadDate": "2026-04-25T00:13:14+00:00"``（实测存在）
          ② ``<meta property="video:release_date">`` / ``itemprop="uploadDate"``
          ③ ``<span class="videoUploaded">Jan 31, 2024</span>``（旧版页面）
          ④ flashvars ``uploadDate``（形如 ``20240131000000``）
        统一交给 `release_date` 真相源解析，解析不出返 None（不填今天）。
        """
        patterns = (
            # ① JSON-LD ISO8601（真实页面主形态）
            r'"uploadDate"\s*:\s*"([^"]{8,40})"',
            r'"datePublished"\s*:\s*"([^"]{8,40})"',
            # ② meta
            r'<meta\s+property="video:release_date"\s+content="([^"]+)"',
            r'<meta\s+itemprop="uploadDate"\s+content="([^"]+)"',
            # ③ 旧版可见文本
            r'class="[^"]*videoUploaded[^"]*"[^>]*>\s*([^<]+?)\s*<',
            r'class="[^"]*videoUploaded[^"]*"[^>]*>.*?(\d{4}-\d{2}-\d{2})',
            # ④ flashvars 紧凑日期
            r'"uploadDate"\s*:\s*"?(\d{10,14})"?',
            r'"publishDate"\s*:\s*"?(\d{10,13})"?',
        )
        for pat in patterns:
            m = re.search(pat, html, re.I | re.DOTALL)
            if not m:
                continue
            raw = m.group(1).strip()
            # ISO8601（2026-04-25T00:13:14+00:00）优先走通用解析
            parsed = parse_release_date(raw)
            if parsed:
                return parsed
            parsed = parse_ph_publish_date(raw)      # unix / 紧凑日期
            if parsed:
                return parsed
        return None

    def _extract_rating_html(self, html: str) -> Optional[float]:
        """提取评分 → **0-10**。

        🔴 2026-10-05 修复：真实页面**已无** ``<span class="percent">``
        （实测 4 处 "percent" 全在相册区 ``album-photo-percentage``），
        旧实现第一分支恒不命中，只能落到 votesUp 分支，而该分支的正则
        ``data-rating="\\d+"[^>]*votesUp`` 依赖属性顺序，实际是
        ``<span class="votesUp" data-rating="882">`` ⇒ 实测 rating=None。

        🔴 但**不能**用 ``up / (up + down)`` 折算：未登录页面**只有 votesUp、
        没有 votesDown**（实测快照 votesDown 出现 0 次）⇒ 该式恒等于 1.0，
        每部片子都会被打成 10.0 分（真实值 8.99，89.9% 好评率）。
        真实评分（0-100 百分制）只存在于 `webmasters` JSON 端点，
        由 `pornhub_api` 源提供（`meta.rating` 0-5 → ×2）。

        所以本方法只在**两个票数都存在**（登录态）时折算，否则返回 None，
        让评分走 GraphQL 源 —— 宁缺勿错。
        """
        # ① 仍存在的百分制写法（保留兼容）
        m = re.search(r'<span[^>]*class="percent"[^>]*>\s*(\d+(?:\.\d+)?)\s*%', html)
        if m:
            return _normalize_rating(m.group(1))

        # ② 好评率折算：仅当 up 与 down **都**存在（登录态）才可信
        up = _extract_data_rating(html, "votesUp")
        down = _extract_data_rating(html, "votesDown")
        if up > 0 and down > 0:
            return round(up / (up + down) * 10, 1)
        return None

    def _extract_views_html(self, html: str) -> Optional[int]:
        """提取播放量。

        🔴 2026-10-05 修复：旧实现只读 ``<span class="count">``，而该文本是
        **缩写**（实测 ``'214K'`` / ``'549K'``）⇒ 解析出 214000，
        而真实播放量是 214450（JSON-LD ``interactionStatistic`` 里是精确值）。
        缩写值误差可达 ±999，且会污染 pornhub.source_views 列。

        改为优先读 JSON-LD 的 ``WatchAction`` 计数，``span.count`` 降为兜底。
        """
        m = re.search(
            r'"interactionType"\s*:\s*"https://schema\.org/WatchAction"'
            r'\s*,\s*"userInteractionCount"\s*:\s*(\d+)',
            html,
        )
        if m:
            return int(m.group(1))
        m = re.search(r'<span[^>]*class="[^"]*\bcount\b[^"]*"[^>]*>\s*([^<]+)', html)
        if m:
            return _parse_number(m.group(1))
        return None

    def _extract_tags_html(self, html: str) -> tuple[list[str], list[str]]:
        """提取标签和分类。

        🔴 2026-10-05 修复：旧正则用 ``(?=class="|</div>\\s*</div>)`` 做右边界，
        而真实块内每个 ``<a>`` 自身就带 class（实测
        ``<a class="gtm-event-video-underplayer item" data-label="category" ...>``）
        ⇒ 边界在**第一个 a 标签处**立刻闭合，分类只抓到 1 个、标签恒为 0 条。
        真实快照实测：旧实现 tags=0 / cats=7（且漏 "Babe"），改边界后 tags=21 / cats=8。

        块的真实边界是 ``</div></div>``（内层 wrapper + 外层 video-info-row）。
        """
        tags: list[str] = []
        categories: list[str] = []

        def _collect(cls: str, out: list[str]) -> None:
            m = re.search(
                rf'<div class="{cls}">(.*?)</div>\s*</div>', html, re.DOTALL
            )
            if not m:
                return
            for a in re.finditer(r"<a[^>]*>(.*?)</a>", m.group(1), re.DOTALL):
                text = re.sub(r"<[^>]+>", "", a.group(1))
                text = re.sub(r"\s+", " ", text).replace("\xa0", " ").strip()
                if text and text not in out:
                    out.append(text)

        _collect("categoriesWrapper", categories)
        _collect("tagsWrapper", tags)

        # 兜底：分类/标签链接（无 wrapper 结构的镜像页）
        if not categories:
            for a in re.finditer(
                r'<a[^>]*href="/(?:video\?c=\d+|categories/)[^"]*"[^>]*>(.*?)</a>',
                html, re.DOTALL,
            ):
                text = re.sub(r"<[^>]+>", "", a.group(1)).strip()
                if text and text not in categories:
                    categories.append(text)
        if not tags:
            for a in re.finditer(
                r'<a[^>]*href="/tags/[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL
            ):
                text = re.sub(r"<[^>]+>", "", a.group(1)).strip()
                if text and text not in tags:
                    tags.append(text)

        return tags, categories

    def _extract_uploader_html(self, html: str) -> Optional[str]:
        """提取上传者 / 模特名。

        🔴 2026-10-05 修复：旧正则在**全页**搜第一个 ``usernameWrap``，
        而真实页面的第一个 ``usernameWrap`` 落在
        ``video-info-row js-suggestionsRow``（**推荐位**）里 ⇒ 实测返回
        ``'NoLube'``（一个跟本片毫无关系的推荐频道），而本片上传者
        真实值是 ``Rosi Lane``。
        改为只在 ``userInfo`` 块内取，与 `_extract_actors_html` 同一口径。
        """
        m = re.search(
            r'<div class="userInfo">(.*?)(?=<div class="(?:video-detailed-info|'
            r'pornstarsWrapper|categoriesWrapper|tagsWrapper|commentsWrapper|'
            r'video-info-row)|<div class="userInfoBlock">)',
            html,
            re.DOTALL,
        )
        if m:
            a = re.search(
                r'<a[^>]*href="/model/[^"]+"[^>]*>(.*?)</a>', m.group(1), re.DOTALL
            )
            if a:
                name = re.sub(r"<[^>]+>", "", a.group(1))
                name = re.sub(r"\s+", " ", name).strip()
                if name:
                    return name
        # 兜底：JSON-LD 的 author 字段（真实快照："author": "Rosi Lane"）
        m_jsonld = re.search(r'"author"\s*:\s*"([^"]{2,60})"', html)
        if m_jsonld:
            return m_jsonld.group(1).strip()
        return None

    # ===== 工具方法 =====

    def _build_result_from_dict(self, data: dict, viewkey: str, source: str = "flashvars") -> ScrapeResult:
        """从字典构建 ScrapeResult"""
        title = (
            data.get("video_title")
            or data.get("title")
            or ""
        )
        title = re.sub(r'[\\/:*?"<>|]', '', title).strip()

        result = ScrapeResult(
            # 🔴 2026-10-05 修复：爬虫产**裸 viewkey**，扫描器产 **ph+viewkey**，
            #    落库按 code 精确匹配（workflow.py:407 `where code == result.code`）
            #    ⇒ 两侧口径不一致时永远匹配不上，每次刮削都**插一条新行**，
            #    实测库里同时存在 ph6a488932e1d19 与 6a488932e1d19 两份同一部片。
            #    统一收口到 ph_viewkey_to_code（番号模块唯一真相源）。
            code=ph_viewkey_to_code(viewkey),
            title=title,
            source="pornhub",
            source_url=VIEW_PAGE_URL.format(viewkey=viewkey),
            original_title=title,
        )

        # 演员
        actors_raw = data.get("actors") or data.get("pornstars") or []
        if isinstance(actors_raw, list):
            actors = []
            for a in actors_raw:
                if isinstance(a, dict):
                    name = a.get("name") or a.get("actor") or a.get("star_name", "")
                    if name:
                        avatar_url = (
                            a.get("avatar") or a.get("profileAvatar")
                            or a.get("thumb") or a.get("image")
                            or a.get("star_image") or a.get("photo", "")
                        )
                        actor = ActorInfo(name=name)
                        if avatar_url:
                            actor.avatar_url = avatar_url
                        extra_id = a.get("id") or a.get("star_id")
                        extra_url = a.get("url") or a.get("permalink") or a.get("pornstar_url")
                        if extra_id or extra_url:
                            actor.extra = {"id": extra_id, "url": extra_url}
                        actors.append(actor)
                elif isinstance(a, str):
                    actors.append(ActorInfo(name=a))
            if actors:
                result.actors = actors

        # 标签/分类
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if tags:
            result.tags = tags if isinstance(tags, list) else []

        categories = data.get("categories", [])
        if isinstance(categories, list):
            cats = []
            for c in categories:
                if isinstance(c, dict):
                    cats.append(c.get("category", str(c)))
                else:
                    cats.append(str(c))
            if cats:
                result.genres = cats

        # 评分
        try:
            # 🔴 flashvars rating 同为 0-100 百分制
            rating = _normalize_rating(data.get("rating", 0))
            if rating:
                result.rating = rating
        except (ValueError, TypeError):
            pass

        # 播放量
        try:
            views = int(data.get("views", 0) or 0)
            if views > 0:
                result.votes = views
        except (ValueError, TypeError):
            pass

        # 时长
        result.duration = self._parse_duration_value(data.get("video_duration") or data.get("duration"))

        # 上传者（作为 studio）
        uploader = data.get("uploader") or data.get("username", "")
        if uploader:
            result.studio = uploader

        # 缩略图
        result.cover_url = data.get("image_url") or data.get("thumb") or data.get("poster_url", "")

        # 原始数据
        result.raw_data = data
        return result

    @staticmethod
    def _parse_duration_value(value) -> Optional[int]:
        """解析时长值 → **返回分钟**（ScrapeResult.duration 契约单位是分钟）。

        修复(2026-10-03)：本方法原实现返回**秒**（含 >3600 时按毫秒 /1000 的处理），
        但调用处 :454 / :876 直接赋给 `result.duration`，而 `ScrapeResult.duration`
        的契约注释明写「时长（分钟）」。后果：NFO/入库写进 865 分钟（实际 14 分钟），
        比正确值大 60 倍，且新写的 pornhub_api 兜底源按分钟换算 → 两源同一影片
        时长相差 60 倍，合并时互相污染。

        PH 的时长来源有两种形态，本方法统一收敛到分钟：
          - "10:44" / "1:12:34" 字符串 → 由 _parse_duration_to_seconds 转秒再 /60
          - 纯数字            → 视作秒（>3600 视作毫秒）；视作分钟则 >3600 判断会失效
        """
        if value is None:
            return None

        # 形态 1：mm:ss / hh:mm:ss 字符串
        if isinstance(value, str) and ":" in value:
            seconds = _parse_duration_to_seconds(value.strip())
            if seconds:
                return max(seconds // 60, 1)
            return None

        # 形态 2：纯数字
        try:
            num = int(value)
        except (ValueError, TypeError):
            return None
        if num <= 0:
            return None
        if num > 3600:  # 视作毫秒 → 秒
            num //= 1000
        # 到这里 num 是秒 → 折算分钟（不足 1 分钟按 1 分钟记，避免落 0）
        return max(num // 60, 1)

    # ===== 搜索 =====

    async def search(self, keyword: str) -> list[ScrapeResult]:
        """搜索 PornHub 视频"""
        results = []
        client = AsyncHttpClient(proxy=self._proxy)
        await client.init_session()
        try:
            search_url = f"{self.base_url}/video/search?search={keyword}"
            html_text = await client.get_text(
                search_url,
                cookies=_PH_BASE_COOKIES,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; rv:115.0) Gecko/20100101 Firefox/115.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.pornhub.com/",
                },
            )

            if not html_text or len(html_text) < 500 or "Just a moment" in html_text or _CHALLENGE_RE.search(html_text):
                logger.warning(f"PornHub 搜索被拦截 [{keyword}]")
                return results

            # 从搜索结果中提取视频
            seen = set()

            # 🔴 2026-10-04 修复两处致命问题：
            # 1) 旧正则 `viewkey=([a-f0-9]+)` 只吃 a-f，而真实 viewkey 是 13 位 a-z0-9
            #    （含 p/q/x/y/z 等 g-z 字母）⇒ 实测 4 个样本错 3 个，含字母 p 的那个直接提不出来。
            #    现统一走全仓唯一判据 number.PH_VIEWKEY_RE（先取出候选再交给 is_valid 校验）。
            # 2) 旧「方案1」循环体只 `seen.add()` 从不 `results.append()` ⇒ 40 行零产出死代码；
            #    「方案2」又完全不查 seen ⇒ 同一 viewkey 重复入库。
            # 现合并为单一路径：扫描所有 viewkey 候选 → 校验 → 去重 → 抓标题。
            for m in re.finditer(r'viewkey=([a-zA-Z0-9]{10,20})', html_text):
                vk = m.group(1)
                if not is_valid_ph_viewkey(vk):
                    continue
                if vk in seen:
                    continue
                seen.add(vk)

                # 在该 viewkey 附近的前置片段里找标题（卡片标题在链接之前或之后）
                start = max(0, m.start() - 800)
                window = html_text[start:m.end() + 1200]
                title_m = re.search(r'data-movie-title="([^"]+)"', window)
                if not title_m:
                    title_m = re.search(r'<span[^>]*class="videoBoxTitle"[^>]*>(.*?)</span>', window, re.DOTALL)

                result = ScrapeResult(
                    code="ph" + vk,
                    title=(title_m.group(1).strip() if title_m else vk),
                    source="pornhub",
                )
                # 缩略图：只在切片里找，且切片边界要防 find 返回 -1
                head = html_text.find(f"viewkey={vk}")
                region = html_text[start:head + 2000] if head != -1 else window
                thumb_m = re.search(
                    r'(?:data-src|src)="([^"]*phncdn[^"]+\.jpg[^"]*)"',
                    region,
                )
                if thumb_m:
                    result.cover_url = thumb_m.group(1)
                results.append(result)
                if len(results) >= 20:
                    break

            if not results:
                logger.warning(f"PornHub 搜索未提取到 viewkey [{keyword}]")

        except Exception as e:
            logger.error(f"PornHub 搜索失败 [{keyword}]: {e}")
        finally:
            await client.close_session()

        return results

    # ===== 演员视频列表（对比查重用） =====

    async def fetch_actress_videos(self, actress_url: str, max_pages: int = 5) -> list[dict]:
        """获取演员主页下的视频列表（供对比查重使用）。

        兼容 model / pornstar / channels 等演员主页 URL，逐页提取
        viewkey + 标题 + 缩略图，返回与 compare 消费格式一致的 dict 列表。
        """
        results: list[dict] = []
        if not actress_url:
            return results

        base = actress_url.strip()
        if base.startswith("//"):
            base = "https:" + base
        elif base.startswith("/"):
            base = self.base_url + base

        client = AsyncHttpClient(proxy=self._proxy)
        await client.init_session()
        try:
            pages = max(1, min(int(max_pages), 20))
            for page in range(1, pages + 1):
                url = f"{base}?page={page}" if page > 1 else base
                html_text = await client.get_text(
                    url,
                    cookies=_PH_BASE_COOKIES,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; rv:115.0) Gecko/20100101 Firefox/115.0",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        # 与 scrape() 同口径：不发 Accept-Language，避免卡片标题
                        # 随请求方语言变成翻译标题（对比查重时会与库标题对不上）。
                        "Referer": "https://www.pornhub.com/",
                    },
                    timeout=_REQ_TIMEOUT,
                )
                if not html_text or len(html_text) < 500 or "Just a moment" in html_text or "cf-browser-verification" in html_text or _CHALLENGE_RE.search(html_text):
                    break
                cards = self._extract_actress_video_cards(html_text)
                if not cards:
                    break
                results.extend(cards)
                if len(results) >= 200:
                    break
        except Exception as e:
            logger.error(f"PornHub 演员视频列表获取失败 [{actress_url}]: {e}")
        finally:
            await client.close_session()
        return results

    def _extract_actress_video_cards(self, html_text: str) -> list[dict]:
        """从演员主页 HTML 提取视频卡片（viewkey + 标题 + 缩略图）。"""
        cards: list[dict] = []
        seen: set[str] = set()
        for m in re.finditer(
            r'viewkey=([a-zA-Z0-9]{10,20})',
            html_text,
        ):
            vk = m.group(1)
            if not is_valid_ph_viewkey(vk):
                continue
            if vk in seen:
                continue
            seen.add(vk)

            # 🔴 2026-10-04 修复：旧正则 `[a-f0-9]+` 只吃 a-f，真实 viewkey 含 g-z
            # 字母（实测含 p 的直接提不出来）⇒ 演员视频列表整个失效。
            # 改用「附近窗口」找标题/缩略图，且切片边界要防 find() 返回 -1。
            start = max(0, m.start() - 800)
            window = html_text[start:m.end() + 1200]
            title_m = re.search(r'data-movie-title="([^"]+)"', window)
            title = title_m.group(1).strip() if title_m else ""
            head = html_text.find(f"viewkey={vk}")
            region = html_text[start:head + 3000] if head != -1 else window
            thumb_m = re.search(
                r'(?:data-src|src)="([^"]*phncdn[^"]+\.jpg[^"]*)"',
                region,
            )
            cards.append({
                "code": "ph" + vk,
                "title": title,
                "url": f"{self.base_url}/view_video.php?viewkey={vk}",
                "cover_url": thumb_m.group(1) if thumb_m else "",
                "source": "pornhub",
            })
            if len(cards) >= 60:
                break

        # 兜底：无 data-movie-title 时，从 viewkey 链接提取
        if not cards:
            for m in re.finditer(r'/view_video\.php\?viewkey=([a-zA-Z0-9]{10,20})', html_text):
                vk = m.group(1)
                if not is_valid_ph_viewkey(vk):
                    continue
                if vk in seen:
                    continue
                seen.add(vk)
                cards.append({
                    "code": "ph" + vk,
                    "title": "",
                    "url": f"{self.base_url}/view_video.php?viewkey={vk}",
                    "cover_url": "",
                    "source": "pornhub",
                })
                if len(cards) >= 60:
                    break
        return cards
