"""
日本里番 · 自刮削器（getchu 源）

用途：当新增的里番文件没有（或只有很瘦的）本地 NFO 时，自动从 getchu.com 补全元数据：
    标题 / 制作商(studio) / 发行日 / 时长 / 类型 / 简介 / 导演 / 封面图。

设计：
- 复用 MDCX 迁移来的 getchu 解析逻辑（lxml xpath，已在 getchu.py 验证可靠）。
- 网络层用项目统一的 AsyncHttpClient（curl_cffi + 指纹 + httpx 降级），不再依赖 legacy manager。
- 以 DVD 番号（如 DBLG-9456 / ACDDL-1014）为首选检索词；无番号时回退按 标题+制作商 检索。
- 处理 getchu 的年龄确认中转页（点击「すすむ」继续）。
- 刮完后把封面下载到数据中心 {data_dir}/movies/anime/{code}/poster.jpg，
  并写出 Jellyfin 兼容 NFO（含 studio/set/plot/premiered/runtime/genre），
  使后续扫描幂等、且可被 Jellyfin 直接消费。
- 全程 best-effort：任何异常都返回 None / 跳过，绝不阻断主扫描流程。
"""
import asyncio
import contextlib
import datetime
import json
import logging
import re
import unicodedata
import urllib.parse
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

from lxml import etree

from app.utils.http_client import AsyncHttpClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

GETCHU_BASE = "https://www.getchu.com"
GETCHU_SEARCH = "http://www.getchu.com/php/search.phtml?genre=all&search_keyword={kw}&gc=gc"

# 限制并发，避免对 getchu 造成压力
_SEM = asyncio.Semaphore(2)


# ===== 从 getchu.py 复用的纯解析函数（lxml 元素入参） =====
def normalize_detail_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"(?:soft\.phtml\?id=|/item/)(\d+)", url)
    if not match:
        return url
    item_id = match.group(1)
    return f"https://www.getchu.com/item/{item_id}/?gc=gc"


def get_attestation_continue_url(html) -> str:
    result = html.xpath("//h1[contains(., '年齢認証ページ')]/following::a[contains(., 'すすむ')][1]/@href")
    return normalize_detail_url(result[0].strip()) if result else ""


def get_title(html):
    result = html.xpath('//h1[@id="soft-title"]/text()')
    if result:
        return result[0].strip()
    result = html.xpath('//meta[@property="og:title"]/@content')
    if result:
        title = re.sub(r"\s*\|\s*.*$", "", result[0]).strip()
        if title:
            return title
    result = html.xpath("//title/text()")
    if result:
        title = re.sub(r"\s+", " ", result[0]).strip()
        title = re.sub(r"\s*\|.*$", "", title).strip()
        title = re.sub(r"\s*\(.*?\)$", "", title).strip()
        return title
    return ""


def get_studio(html):
    result = html.xpath('//a[@class="glance"]/text()')
    return result[0].strip() if result else ""


def get_release(html):
    result = html.xpath("//td[contains(text(),'発売日：')]/following-sibling::td/a/text()")
    return result[0].replace("/", "-") if result and re.search(r"\d+", result[0]) else ""


def get_year(release):
    try:
        return str(re.search(r"\d{4}", release).group())
    except Exception:
        return ""


def get_director(html):
    result = html.xpath("//td[contains(text(),'監督：')]/following-sibling::td/text()")
    if not result:
        result = html.xpath("//a[contains(@href,'person=')]/text()")
    if not result:
        result = html.xpath("//td[contains(text(),'キャラデザイン：')]/following-sibling::td/text()")
    return result[0].strip() if result else ""


def get_runtime(html):
    result = html.xpath("//td[contains(text(),'時間：')]/following-sibling::td/text()")
    if result:
        nums = re.findall(r"\d+", result[0])
        return nums[0] if nums else ""
    return ""


def get_tag(html):
    result = html.xpath(
        "//td[contains(text(), 'サブジャンル：') or contains(text(), 'カテゴリ：')]/following-sibling::td/a/text()"
    )
    return [r.strip() for r in result if r.strip()] if result else []


def get_cover(html):
    result = html.xpath('//meta[@property="og:image"]/@content')
    if result:
        return "http://www.getchu.com" + result[0] if "http" not in result[0] else result[0]
    return ""


def get_outline(html):
    all_info = html.xpath('//div[@class="tablebody"]')
    result = ""
    for each in all_info:
        info = each.xpath("normalize-space(string())")
        result += "\n" + info
    return result.strip()


def get_web_number(html, default):
    result = html.xpath('//td[contains(text(), "品番：")]/following-sibling::td/text()')
    return result[0].strip().upper() if result else default


# ===== 成熟度增强：编码容错 / dl.getchu 结构化解析 / 候选评分 =====
def _decode_jp(raw: bytes) -> str | None:
    """EUC-JP 优先，失败回退 Shift_JIS / CP932（页面编码不纯时的容错）。"""
    for enc in ("euc-jp", "shift_jis", "cp932"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return None


def _parse_dl_getchu(html) -> dict:
    """解析 dl.getchu.com 商品页（移植 metatube-sdk-go provider/getchu/getchu.go 选择器）。

    结构化字段表：サークル=制作商 / 配信開始日=发行日 / 趣向=类型 / 作品内容=简介，
    预览图取 background-color:#444444 单元格内的 a[href]，封面取 bgcolor=#ffffff 的 img。
    """
    meta: dict = {"preview_urls": [], "genre": []}
    base = "https://dl.getchu.com"

    for e in html.xpath('//td[.//div[contains(@style,"color: #333333") and contains(@style,"padding")]]'):
        txt = "".join(e.xpath(".//text()")).strip()
        if txt:
            meta["title"] = txt
            break
    for src in html.xpath("//td[@bgcolor='#ffffff']//img/@src"):
        meta["cover_url"] = src if src.startswith("http") else base + src
        break
    for href in html.xpath('//td[contains(@style,"background-color: #444444")]//a/@href'):
        meta["preview_urls"].append(href if href.startswith("http") else base + href)
    for tr in html.xpath("//tr"):
        cells = tr.xpath("./td")
        if len(cells) < 2:
            continue
        key = "".join(cells[0].xpath(".//text()")).strip()
        val = "".join(cells[1].xpath(".//text()")).strip()
        if key == "サークル":
            meta["maker"] = val
        elif key == "配信開始日" and val:
            meta["release_date"] = val.replace("/", "-")
        elif key == "趣向":
            meta["genre"] = [g.strip() for g in cells[1].xpath(".//a/text()") if g.strip()]
        elif key == "作品内容" and val:
            meta["plot"] = val
    meta["preview_urls"] = list(dict.fromkeys(meta["preview_urls"]))[:12]
    return meta


def _score_candidate(cand_title: str, code: str | None, title_hint: str | None,
                     maker_hint: str | None) -> int:
    """候选评分：番号命中 100 > 标题重合 50 > 制作商匹配 20。"""
    score = 0
    ct = re.sub(r"[ \[\]\［\］]+", "", cand_title or "")
    if code and code.upper() in ct.upper():
        score += 100
    if title_hint:
        nh = re.sub(r"[ \[\]\［\］]+", "", title_hint)
        if nh and (nh in ct or ct in nh):
            score += 50
    if maker_hint and maker_hint and maker_hint in (cand_title or ""):
        score += 20
    return score


# ===== 刮削器主体 =====
class AnimeGetchuScraper:
    """getchu 里番元数据刮削器（自包含、best-effort）。"""

    def __init__(self, timeout: int = 20):
        self.client = AsyncHttpClient(timeout=timeout)
        self.timeout = timeout

    async def scrape(
        self, code: str | None, title: str, maker: str | None = None
    ) -> dict | None:
        """刮削单个里番。

        Args:
            code:   DVD 番号（如 DBLG-9456）；无则传 None，回退按标题检索。
            title: 清洗后的标题（用于回退检索与结果校验）。
            maker: 制作商（增强标题检索命中率）。
        Returns:
            元数据字典，或 None（未命中/失败）。
        """
        async with _SEM:
            try:
                return await self._scrape_impl(code, title, maker)
            except Exception as e:
                logger.debug(f"[anime-getchu] 刮削失败 code={code} title={title!r}: {e}")
                return None

    async def _fetch_html(self, url: str) -> "etree._Element | None":
        """抓取并解析 HTML（编码容错 + 2 次重试退避）。返回 lxml 元素或 None。"""
        raw = b""
        for attempt in range(2):
            try:
                resp = await self.client.get(url)
                raw = getattr(resp, "content", b"") if resp else b""
                if raw:
                    break
            except Exception:
                raw = b""
            if attempt == 0:
                await asyncio.sleep(1.5 * (attempt + 1))
        if not raw:
            return None
        text = _decode_jp(raw)
        if not text:
            return None
        try:
            return etree.fromstring(text, etree.HTMLParser())
        except Exception:
            return None

    async def _scrape_impl(self, code, title, maker) -> dict | None:
        # 1) 检索：番号优先 → 失败回退「制作商+标题」（成熟度：小众品牌如 DBLG 无番号收录）
        candidates: list[tuple[str, str]] = []
        if code:
            candidates = await self._search_candidates(code, title_hint=title)
        if not candidates and title:
            keyword = (maker or "") + " " + title if maker else title
            candidates = await self._search_candidates(keyword, title_hint=title)
        if not candidates:
            return None

        # 2) 候选评分排序（番号命中 > 标题重合 > 制作商），逐个尝试详情页
        candidates.sort(key=lambda c: _score_candidate(c[1], code, title, maker), reverse=True)
        for real_url, cand_title in candidates[:6]:
            meta = await self._scrape_detail(real_url, code, title, maker)
            if meta:
                return meta
        return None

    async def _scrape_detail(self, real_url, code, title, maker) -> dict | None:
        """抓取单个商品详情页并解析（含年龄墙 + dl.getchu 桥接补全 + 结果校验）。"""
        html = await self._fetch_html(real_url)
        if html is None:
            return None

        # 年龄确认中转页（www.getchu 实体版）
        continue_url = get_attestation_continue_url(html)
        if continue_url:
            html2 = await self._fetch_html(continue_url)
            if html2 is not None:
                html = html2

        g_title = get_title(html)
        if not g_title:
            return None

        # 结果校验：番号检索看品番/标题，标题检索看重合（不再盲目信任）
        if code:
            web_number = get_web_number(html, "").upper().replace("-", "")
            code_n = code.upper().replace("-", "")
            if web_number and web_number == code_n:
                ok = True
            else:
                nh = re.sub(r"[ \[\]\［\］]+", "", title or "")
                ok = bool(nh) and (nh[:6] in g_title or g_title[:6] in nh)
        else:
            nh = re.sub(r"[ \[\]\［\］]+", "", title or "")
            ok = bool(nh) and (nh[:4] in g_title or g_title[:4] in nh)
        if not ok:
            return None

        # www.getchu 解析
        studio = get_studio(html)
        release = get_release(html)
        year = get_year(release)
        runtime = get_runtime(html)
        genre = get_tag(html)
        outline = get_outline(html)
        director = get_director(html)
        cover_url = get_cover(html)
        web_number = get_web_number(html, code or "")
        item_id = re.search(r"/item/(\d+)", real_url)
        preview_urls = self._parse_preview_images(html, item_id.group(1) if item_id else "")

        # 3) dl.getchu.com 桥接补全（方向 A：DL 版页结构化字段，尤其预览图更全）
        dl_meta: dict = {}
        dl_urls = html.xpath("//a[contains(@href,'dl.getchu.com')]/@href")
        if dl_urls:
            dl_html = await self._fetch_html(dl_urls[0])
            if dl_html is not None:
                dl_meta = _parse_dl_getchu(dl_html)

        if dl_meta.get("preview_urls"):
            preview_urls = list(dict.fromkeys(preview_urls + dl_meta["preview_urls"]))[:12]
        if not cover_url and dl_meta.get("cover_url"):
            cover_url = dl_meta["cover_url"]
        if not outline and dl_meta.get("plot"):
            outline = dl_meta["plot"]
        if not genre and dl_meta.get("genre"):
            genre = dl_meta["genre"]
        if not studio and dl_meta.get("maker"):
            studio = dl_meta["maker"]

        return {
            "title": g_title,
            "maker": studio,          # 制作商
            "studio": studio,
            "release_date": release or None,
            "year": int(year) if year.isdigit() else None,
            "runtime": int(runtime) if runtime.isdigit() else None,
            "genre": genre,
            "plot": outline,
            "director": director or None,
            "series": "",             # getchu 不提供稳定系列字段，留空（系列仍由标题解析兜底）
            "cover_url": cover_url or None,
            "preview_urls": preview_urls,
            "source_url": real_url,
            "code": web_number or code,
        }

    def _parse_preview_images(self, html, item_id: str) -> list[str]:
        """解析 getchu 商品页预览图。

        getchu 预览图 URL 形如 https://www.getchu.com/brandnew/{id}/c{id}_{n}.jpg，
        排除 _top/_logo/_left/_right 等特殊图；item_id 缺失时回退到全页 brandnew 图。
        """
        out: list[str] = []
        seen: set[str] = set()
        for src in html.xpath("//img/@src"):
            if not src:
                continue
            full = src if src.startswith("http") else GETCHU_BASE + src
            if "brandnew" not in full:
                continue
            if item_id and f"/{item_id}/" not in full and f"c{item_id}" not in full:
                continue
            name = full.rsplit("/", 1)[-1].lower()
            if any(x in name for x in ("_top", "_logo", "_left", "_right", "_s", "_list", "logo")):
                continue
            if full in seen:
                continue
            seen.add(full)
            out.append(full)

        def _num(u: str) -> int:
            m = re.search(r"_(\d+)\.(?:jpg|jpeg|png|webp)$", u)
            return int(m.group(1)) if m else 999

        out.sort(key=_num)
        return out[:12]

    async def download_previews(self, urls: list[str], save_dir: Path) -> list[str]:
        """下载预览图到 save_dir/01.jpg、02.jpg…（数据中心 extrafanart）。"""
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return []
        saved: list[str] = []
        for i, url in enumerate(urls, start=1):
            try:
                resp = await self.client.get(url)
                if not resp or not getattr(resp, "content", b""):
                    continue
                p = save_dir / f"{i:02d}.jpg"
                p.write_bytes(resp.content)
                if p.exists() and p.stat().st_size > 1024:
                    saved.append(p.name)
            except Exception as e:
                logger.debug(f"[anime-getchu] 预览图下载失败 {url}: {e}")
        return saved

    async def _search_candidates(self, keyword: str, title_hint: str | None = None) -> list[tuple[str, str]]:
        """按关键词检索 getchu，返回去重候选 [(详情URL, 标题)]（最多 10 个）。"""
        try:
            kw = unicodedata.normalize("NFC", keyword)
            with contextlib.suppress(Exception):
                kw = kw.encode("cp932").decode("shift_jis")
            keyword2 = urllib.parse.quote_plus(kw, encoding="EUC-JP")
        except Exception:
            keyword2 = urllib.parse.quote_plus(keyword)
        url = GETCHU_SEARCH.format(kw=keyword2)
        html = await self._fetch_html(url)
        if html is None:
            return []
        url_list = html.xpath("//a[@class='blueb']/@href")
        title_list = html.xpath("//a[@class='blueb']/text()")
        if not url_list:
            return []
        cands: list[tuple[str, str]] = []
        seen: set[str] = set()
        for u, t in zip(url_list, title_list):
            du = normalize_detail_url(GETCHU_BASE + u.replace("../", "/") + "&gc=gc")
            if not du or du in seen:
                continue
            seen.add(du)
            cands.append((du, (t or "").strip()))
            if len(cands) >= 10:
                break
        return cands

    async def download_cover(self, cover_url: str, save_path: Path) -> bool:
        """下载封面图到 save_path（poster.jpg）。成功返回 True。"""
        if not cover_url:
            return False
        try:
            resp = await self.client.get(cover_url)
            if not resp or not getattr(resp, "content", b""):
                return False
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(resp.content)
            return save_path.exists() and save_path.stat().st_size > 1024
        except Exception as e:
            logger.debug(f"[anime-getchu] 封面下载失败 {cover_url}: {e}")
            return False


# ===== NFO 写出（Jellyfin 兼容，确保后续扫描幂等） =====
def build_anime_nfo(meta: dict, code: str, local_title: str) -> str:
    """根据刮削元数据生成 Jellyfin/Kodi 风格 NFO 文本。"""
    root = ET.Element("movie")
    title = meta.get("title") or local_title
    ET.SubElement(root, "title").text = title
    ET.SubElement(root, "originaltitle").text = title
    ET.SubElement(root, "customrating").text = "里番"
    if meta.get("studio"):
        ET.SubElement(root, "studio").text = meta["studio"]
    if meta.get("release_date"):
        ET.SubElement(root, "premiered").text = meta["release_date"]
    if meta.get("year"):
        ET.SubElement(root, "year").text = str(meta["year"])
    if meta.get("runtime"):
        ET.SubElement(root, "runtime").text = str(meta["runtime"])
    if meta.get("plot"):
        ET.SubElement(root, "plot").text = meta["plot"]
    if meta.get("director"):
        ET.SubElement(root, "director").text = meta["director"]
    for g in meta.get("genre", []) or []:
        ET.SubElement(root, "genre").text = g
    if meta.get("source_url"):
        ET.SubElement(root, "thumb").text = meta["source_url"]
    rough = ET.tostring(root, encoding="utf-8")
    try:
        return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    except Exception:
        return rough.decode("utf-8")


def write_anime_nfo(nfo_path: Path, meta: dict, code: str, local_title: str) -> None:
    nfo_path.parent.mkdir(parents=True, exist_ok=True)
    nfo_path.write_text(build_anime_nfo(meta, code, local_title), encoding="utf-8")


# ===== 完整链路（扫描器 _self_scrape 与手动刮削端点共用） =====
_DVD_CODE_PATTERN = re.compile(r"^[A-Za-z]{2,6}-?\d{2,6}$")


def _extract_dvd_code(code: str) -> str | None:
    """从 ANI- 前缀 code 中提取纯 DVD 番号（无番号则 None，走标题检索）。"""
    raw = code
    if raw.startswith("ANI-"):
        raw = raw[4:]
    return raw if _DVD_CODE_PATTERN.match(raw) else None


async def scrape_anime_and_apply(
    code: str,
    title: str,
    maker: str | None = None,
    movie_id: int | None = None,
) -> dict:
    """完整刮削链路：getchu 刮削 → 回填 anime.db → 封面 → 预览图 → NFO。

    供扫描器 _self_scrape 与手动刮削端点共用；全程 best-effort，异常不抛出。
    Returns: {"ok": bool, "code": str, "title": str|None, "previews": int}
    """
    scraper = AnimeGetchuScraper()
    raw_code = _extract_dvd_code(code)
    meta = await scraper.scrape(raw_code, title, maker)
    if not meta:
        return {"ok": False, "code": code, "title": None, "previews": 0}
    try:
        from app.config.manager import get_config_manager
        from app.db.anime_models import AnimeMovie
        from app.db.module_db import ModuleDatabase
        from sqlalchemy import select

        db = ModuleDatabase.get_instance("anime")
        session = await db.get_session()
        try:
            if movie_id is not None:
                mv = (await session.execute(
                    select(AnimeMovie).where(AnimeMovie.id == movie_id)
                )).scalar_one_or_none()
            else:
                mv = (await session.execute(
                    select(AnimeMovie).where(AnimeMovie.code == code)
                )).scalar_one_or_none()
            if not mv:
                return {"ok": False, "code": code, "title": None, "previews": 0}

            # 仅填空字段，保留已有 NFO 数据
            if not mv.title and meta.get("title"):
                mv.title = meta["title"]
            if not mv.maker and meta.get("maker"):
                mv.maker = meta["maker"]
            if not mv.studio and meta.get("studio"):
                mv.studio = meta["studio"]
            if not mv.release_date and meta.get("release_date"):
                mv.release_date = meta["release_date"]
            if not mv.duration and meta.get("runtime"):
                mv.duration = meta["runtime"]
            if not mv.plot and meta.get("plot"):
                mv.plot = meta["plot"]
            if not mv.director and meta.get("director"):
                mv.director = meta["director"]
            if not mv.genre and meta.get("genre"):
                mv.genre = json.dumps(meta["genre"], ensure_ascii=False)
            if not mv.source_url and meta.get("source_url"):
                mv.source_url = meta["source_url"]
            mv.source = "getchu"
            mv.status = "completed"
            mv.scraped_at = datetime.datetime.utcnow()
            # 回填封面 URL（仅当 cover_url 为空且 meta 中有值）
            if not mv.cover_url and meta.get("cover_url"):
                mv.cover_url = meta["cover_url"]
            await session.commit()

            # 封面 + NFO + 预览图（数据中心，幂等：已存在跳过）
            data_dir = get_config_manager().computed.data_dir
            target_dir = Path(data_dir) / "movies" / "anime" / code
            target_dir.mkdir(parents=True, exist_ok=True)
            poster_dst = target_dir / "poster.jpg"
            if not poster_dst.exists():
                await scraper.download_cover(meta.get("cover_url") or "", poster_dst)
            nfo_dst = target_dir / "movie.nfo"
            if not nfo_dst.exists():
                write_anime_nfo(nfo_dst, meta, code, mv.title or title)
            saved: list[str] = []
            if meta.get("preview_urls"):
                saved = await scraper.download_previews(
                    meta["preview_urls"], target_dir / "extrafanart"
                )
            logger.info(f"[anime] 刮削完成: {code} -> {meta.get('title')} (预览 {len(saved)} 张)")
            return {"ok": True, "code": code, "title": meta.get("title"), "previews": len(saved)}
        finally:
            await session.close()
    except Exception as e:
        logger.debug(f"[anime] 刮削应用失败（忽略）: {e}")
        return {"ok": False, "code": code, "title": None, "previews": 0}
