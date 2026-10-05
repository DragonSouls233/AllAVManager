# -*- coding: utf-8 -*-
"""Wiki 女优/番号识别爬虫（seesaa / memo.wiki 系）。

解决什么
--------
库里 469 条素人番号「刮不到资料」的根因：常规 JAV 源只收录**有艺名的女优**，
而素人作品（FANZA 素人视频）公开的是**素人名义**（`麻里`/`流川さん`/`斉藤帆夏`），
真实姓名只在专门的 wiki 上有人整理。

实测可用的三个站（2026-10-05，全部 200 且**无年龄门禁**，走项目代理即可）：

============================================  ==================================
站点                                          用途
============================================  ==================================
https://seesaawiki.jp/av_name/               **从品番识别素人女优实名**（主力）
https://shiroutoav.memo.wiki/                 素人女优名鉴
https://av-help.memo.wiki/                    AV女优大辞典（2010 年后，含厂商）
https://seesaawiki.jp/av_video/               按作品整理
============================================  ==================================

`av_name/` 详情页字段（实测 SPAY-841 / MFCW-081 结构完全规律）::

    品番      SPAY-841          ← 我们的 code
    配信品番  spay841           ← FANZA 的无连字符码
    素人名義  流川さん          ← 对外公开名义（不是人名）
    出演女優  流川はる香 （るかわ はるか）   ← **真实姓名，正是我们要的**
    配信開始日 2026-10-05       ← 可补 release_date
    レーベル   素人ペイペイ      ← **可补 studio（厂牌）**
    ジャンル   中出し、3P・4P...  ← 可补 genre

关键实测坑（都写在方法 docstring 里）
------------------------------------
1. **charset = EUC-JP**（不是 UTF-8 也不是 Shift_JIS），且 URL 的 `/d/` 片段是
   **EUC-JP 百分号编码**。用 UTF-8 解码会得到一堆 ``乱码`` ⇒ 必须显式
   `encoding="euc_jp"`。实测按 Shift_JIS 解全是乱码。
2. `/d/` 详情页对**不存在的条目返回 404**（不是 200 空页），可安全用作探测。
3. `wiki.seesaa.jp/adult/` 主站有年龄门禁（需先访问 `/adult/agree?u=<目标>`），
   但上面四个**子站本身不需要**门禁，不必走那套 cookie 流程。
4. 厂牌一览（av-help）在静态 HTML 里是 **JS 渲染**，静态抓取拿不到；
   但 `av_name` 首页内嵌的 20 条记录本身就带完整字段，够用。
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

#: 各站点主页（只放实测可程序化访问的子站，主站 wiki.seesaa.jp/adult 有年龄门禁）
SITES = {
    "av_name": "https://seesaawiki.jp/av_name/",
    "shirouto": "https://shiroutoav.memo.wiki/",
    "av_help": "https://av-help.memo.wiki/",
    "av_video": "https://seesaawiki.jp/av_video/",
}

#: 详情页字段（日文标签 → 我们的字段名）
_FIELD_MAP = (
    ("品番", "code"),
    ("配信品番", "fanza_code"),
    ("素人名義", "alias_name"),
    ("出演女優", "actor"),
    ("配信開始日", "release_date"),
    ("レーベル", "studio"),
    ("ジャンル", "genre"),
)

_CODE_RE = re.compile(r"^[A-Za-z]{2,}[-_]?\d{2,5}$")


@dataclass
class WikiHit:
    """一个番号在 wiki 上查到的记录。"""

    code: str = ""
    fanza_code: str = ""
    alias_name: str = ""        # 素人名义（对外公开名，非人名）
    actor: str = ""             # 真实姓名 / 女优艺名
    release_date: str = ""
    studio: str = ""
    genre: list = field(default_factory=list)
    source: str = ""
    url: str = ""

    def to_fields(self) -> dict:
        """转成可直接并入 ScrapeResult 的字段字典。"""
        out = {
            "title": None,
            "actors": [],
            "release_date": self.release_date or None,
            "studio": self.studio or None,
            "genre": self.genre or None,
            "source": self.source,
        }
        if self.actor:
            out["actors"] = [{"name": self.actor}]
        return out


def _decode(seg: str) -> str:
    """解码 seesaa 的 /d/ 路径片段（EUC-JP 百分号编码）。"""
    try:
        return urllib.parse.unquote(seg, encoding="euc_jp", errors="replace")
    except (UnicodeDecodeError, LookupError):
        return urllib.parse.unquote(seg)


def _encode(name: str) -> str:
    """把名字编码成 seesaa 的 /d/ 片段（EUC-JP 百分号编码）。

    🔴 连字符**必须**一起编码（实测站点用的是 `MFCW%2d081` 而非 `MFCW-081`），
    保持 urlquote 默认行为即可 —— 之前"顺手"把 %2D 还原成 `-` 导致 404。
    """
    return urllib.parse.quote_from_bytes(name.encode("euc_jp", "replace"))


def html_to_text(html: str) -> str:
    """把 wiki 正文转成逐行文本（保留换行以便按字段标签取值）。"""
    h = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</(tr|td|div|p|h\d|li)>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = h.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"[ \t]{2,}", " ", h)


def parse_detail(html: str, code: str, source: str, url: str) -> Optional[WikiHit]:
    """从详情页 HTML 解析出结构化字段。

    只认**成对出现**的标签行；取第一个值（首页/摘要区会有重复出现）。
    演员字段形如 `流川はる香 （るかわ はるか）`，括号里是读音，要剥掉。
    """
    # 🔴 必须**全文**扫描，不能只取 content_2（实测 seesaa 模板里 content_2
    # 只有导航/页脚，「品番/出演女優/レーベル」散落在 content_3~content_5 各块）。
    lines = [ln.strip() for ln in html_to_text(html).split("\n") if ln.strip()]

    got: dict = {}
    for line in lines:
        for label, key in _FIELD_MAP:
            if line.startswith(label):
                val = line[len(label):].strip().lstrip(":：").strip()
                if val and key not in got:
                    got[key] = val
                break

    # 详情页存在性：连「品番」都没有 ⇒ 不是我们要的页面
    if "code" not in got:
        return None

    hit = WikiHit(
        code=got.get("code", ""),
        fanza_code=got.get("fanza_code", ""),
        alias_name=got.get("alias_name", ""),
        actor=_clean_actor(got.get("actor", "")),
        release_date=_norm_date(got.get("release_date", "")),
        studio=got.get("studio", ""),
        genre=[g.strip() for g in re.split(r"[、,，]", got.get("genre", "")) if g.strip()],
        source=source,
        url=url,
    )
    # 番号对不上就别用（防同页串内容）
    if code and hit.code and not _same_code(hit.code, code):
        return None
    return hit


def _clean_actor(v: str) -> str:
    """`流川はる香 （るかわ はるか）` → `流川はる香`；多个人用全角/顿号分隔时取第一个。"""
    v = (v or "").strip()
    if not v:
        return ""
    v = re.split(r"[（(]", v)[0].strip()
    if re.search(r"[、,，/／]", v):
        v = re.split(r"[、,，/／]", v)[0].strip()
    return v


def _norm_date(v: str) -> str:
    """`2026-10-05` / `2026年10月05日` → `2026-10-05`。"""
    v = (v or "").strip()
    m = re.search(r"(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})", v)
    if not m:
        return ""
    return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _same_code(a: str, b: str) -> bool:
    """番号等价（忽略大小写、连字符与**数字前缀**）。

    库里是 `300MIUM-1437`，wiki 页面写 `MIUM-1437` ⇒ 前缀差异必须容忍，
    否则刚查到的页面会被自己判为不符而丢弃。
    """
    def norm(v: str) -> str:
        v = re.sub(r"^(\d{2,4})(?=[A-Za-z])", "", (v or "").strip())
        return re.sub(r"[^A-Z0-9]", "", v.upper())
    na, nb = norm(a), norm(b)
    return bool(na) and na == nb


class WikiScraper:
    """按番号查 wiki 女优/厂牌信息。

    用法::

        async with WikiScraper() as ws:
            hit = await ws.scrape("SPAY-841")
            if hit and hit.actor:
                print(hit.actor, hit.studio, hit.release_date)

    代理：走项目统一的 `get_effective_proxy_url()`（铁律：新增 httpx 会话必须传它，
    否则直连墙外必超时）。
    """

    def __init__(self, sites: tuple = ("av_name",), timeout: int = 30,
                 proxy: Optional[str] = None, delay: float = 0.8):
        self.sites = [s for s in sites if s in SITES] or ["av_name"]
        self.timeout = timeout
        self._delay = delay
        self._proxy = proxy
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "WikiScraper":
        from app.services.proxy_manager import get_effective_proxy_url
        proxy = self._proxy or get_effective_proxy_url()
        self._client = httpx.AsyncClient(
            proxy=proxy,
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": UA},
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    async def _get(self, url: str) -> Optional[str]:
        if self._client is None:
            raise RuntimeError("请在 async with 内使用 WikiScraper")
        try:
            r = await self._client.get(url)
        except Exception as e:  # noqa: BLE001
            logger.debug("wiki 请求失败 %s: %s: %s", url, type(e).__name__, e)
            return None
        if r.status_code != 200:
            # 404 = 该 wiki 没收录这部（不是故障，不计熔断）
            logger.debug("wiki %s -> HTTP %s", url, r.status_code)
            return None
        return r.text

    async def scrape(self, code: str, fanza_code: str = "") -> Optional[WikiHit]:
        """按番号查。依次尝试多种形态，直到某个命中为止。

        库里素人番号是 `300MIUM-1437` / `390JAC-016`（**数字前缀** + FANZA 配信品番），
        而 wiki 收录的是 `MFCW-081` / `SIRO-1234` 这种无数字前缀形态，
        所以候选里必须带上「剥掉数字前缀」的那一版，否则一条都查不到
        （实测首版命中率 0%）。
        """
        code = (code or "").strip()
        if not code:
            return None
        candidates: list = [code]
        bare = re.sub(r"[^A-Za-z0-9]", "", code)
        if bare and bare not in candidates:
            candidates.append(bare)
        # 300MIUM-1437 → MIUM-1437（剥掉数字前缀）
        no_prefix = re.sub(r"^\d{2,4}([A-Za-z]+)-?(\d+)$", r"\1-\2", code)
        if no_prefix != code:
            for x in (no_prefix, re.sub(r"[^A-Za-z0-9]", "", no_prefix)):
                if x and x not in candidates:
                    candidates.append(x)
        if fanza_code and fanza_code not in candidates:
            candidates.append(fanza_code)

        for site in self.sites:
            base = SITES[site]
            for cand in candidates:
                url = "%sd/%s" % (base, _encode(cand))
                html = await self._get(url)
                if not html:
                    continue
                hit = parse_detail(html, code, site, url)
                if hit:
                    logger.debug("wiki 命中 %s @ %s -> %s", code, site, hit.actor)
                    return hit
                await asyncio_sleep(self._delay)
        return None


async def asyncio_sleep(sec: float) -> None:
    """独立小函数，便于测试时打桩。"""
    import asyncio
    await asyncio.sleep(sec)


async def scrape_many(codes, sites: tuple = ("av_name",), gap: float = 1.0) -> dict:
    """批量查多个番号，返回 {code: WikiHit}。"""
    out: dict = {}
    async with WikiScraper(sites=sites) as ws:
        for i, c in enumerate(codes, 1):
            hit = await ws.scrape(c)
            if hit:
                out[c] = hit
                logger.info("[%d] %s -> 女优=%s 厂牌=%s",
                            i, c, hit.actor, hit.studio)
            if i % 10 == 0:
                await asyncio_sleep(gap)
    return out
