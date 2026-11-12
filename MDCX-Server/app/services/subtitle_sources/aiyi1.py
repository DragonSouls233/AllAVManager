"""爱译网（aiyi1）适配器：搜索列表页 → 文章页 → CDN .srt 直链。

页面结构（2026-11 实测）：
- 列表页 ``GET /?s={code}``，每个结果是一张 ``div.post-box``：
  ``h2 a[href]`` 指向 ``https://www.aiyi1.com/{id}.html``，
  正文是纯文本字段：``字幕语种：中文简体`` / ``字幕格式：SRT`` /
  ``下载字幕 | 61KB`` / ``文件名：xxx.srt``。
- 文章页在 ``.main-content`` 内给出 ``下载字幕`` 链接，指向
  ``https://a.hinimg.com/aiyi-files/...-zh-CN.srt``（也见过 aiyi1 自身域名）。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.services.subtitle_sources.base import (
    SEARCH_RESULTS_LIMIT,
    Budget,
    DownloadFailed,
    SourceBlocked,
    SubtitleCandidate,
    fetch_text,
    parse_size,
    request,
    title_matches_code,
)

logger = logging.getLogger(__name__)

SITE = "https://www.aiyi1.com"
_SEARCH_URL = SITE + "/?s={code}"
_TRANSLATED_RE = re.compile(r"\s*\((?:translated|automatic)[^)]*\)\s*$", re.I)
_ARTICLE_RE = re.compile(r"^https://www\.aiyi1\.com/\d+\.html$")

_LANG_RE = re.compile(r"字幕语种[：:]\s*([^\n]{1,20})")
_FMT_RE = re.compile(r"字幕格式[：:]\s*([A-Za-z0-9]{1,8})")
_SIZE_RE = re.compile(r"下载字幕\s*[|｜]\s*([\d.]+\s*[KMG]B)")
_NAME_RE = re.compile(r"文件名[：:]\s*([^\n]{1,120})")
_MATCH_RE = re.compile(r"匹配视频[：:]\s*([^\n]{1,80})")


def _language_of(text: str) -> str | None:
    """语种字段 → zh-CN / zh-TW；其它语种（英文/日文）不产生候选。"""
    value = (text or "").strip()
    if not value:
        return None
    if "简" in value or "chs" in value.lower() or "zh-cn" in value.lower():
        return "zh-CN"
    if "繁" in value or "cht" in value.lower() or "zh-tw" in value.lower():
        return "zh-TW"
    return None


def _safe_article(value: str) -> str | None:
    try:
        url = urlsplit(urljoin(SITE + "/", value))
    except ValueError:
        return None
    if url.scheme != "https" or (url.hostname or "").lower() != "www.aiyi1.com":
        return None
    return url.geturl()


def _safe_download(value: str, base: str) -> str | None:
    """只接受 https + (a.hinimg.com | *.aiyi1.com) 的字幕直链。"""
    try:
        url = urlsplit(urljoin(base, value))
    except ValueError:
        return None
    host = (url.hostname or "").lower()
    if url.scheme != "https":
        return None
    if not (host == "a.hinimg.com" or host == "aiyi1.com" or host.endswith(".aiyi1.com")):
        return None
    if url.username or url.password:
        return None
    return url.geturl()


class Aiyi1Source:
    name = "aiyi1"

    async def search(self, code: str, *, budget: Budget) -> list[SubtitleCandidate]:
        search_url = _SEARCH_URL.format(code=code)
        html, _ = await fetch_text(search_url, gate_name="aiyi1", budget=budget)
        soup = BeautifulSoup(html, "html.parser")

        results: list[dict] = []
        for box in soup.select("div.post-box"):
            link = box.select_one("h2 a[href]")
            if link is None:
                continue
            article = _safe_article(str(link.get("href") or ""))
            if not article or not _ARTICLE_RE.match(article):
                continue
            title = _TRANSLATED_RE.sub("", link.get_text(" ", strip=True)).strip()
            if not title_matches_code(title, code):
                continue
            text = box.get_text("\n", strip=True)
            language = _language_of((_LANG_RE.search(text) or [None, ""])[1])
            if not language:
                continue
            # 本模块统一规范化 SRT，ASS/SSA 一律丢弃（避免写出非 SRT 内容）
            fmt = ((_FMT_RE.search(text) or [None, "SRT"])[1] or "SRT").upper()
            if fmt != "SRT":
                logger.info("[aiyi1] 跳过非 SRT 候选 %s (%s)", title, fmt)
                continue
            size_match = _SIZE_RE.search(text)
            name_match = _NAME_RE.search(text)
            match_match = _MATCH_RE.search(text)
            if match_match and not title_matches_code(match_match.group(1), code):
                continue
            results.append({
                "title": title,
                "article": article,
                "language": language,
                "size": parse_size(size_match.group(1)) if size_match else None,
                "file_name": (name_match.group(1).strip() if name_match else ""),
            })
            if len(results) >= SEARCH_RESULTS_LIMIT:
                break

        candidates: list[SubtitleCandidate] = []
        for item in results:
            if budget.expired():
                break
            try:
                page_html, final_url = await fetch_text(
                    item["article"], referer=search_url, gate_name="aiyi1", budget=budget,
                )
            except SourceBlocked:
                raise
            except Exception as exc:  # noqa: BLE001 - 单篇文章页失败不中断整体
                logger.info("[aiyi1] 文章页跳过 %s: %s", item["article"], exc)
                continue

            page = BeautifulSoup(page_html, "html.parser")
            container = page.select_one(".main-content") or page
            download = None
            for link in container.select("a[href]"):
                href = str(link.get("href") or "")
                if ".srt" not in href.lower():
                    continue
                if "下载" not in link.get_text(" ", strip=True) and "download" not in href.lower():
                    continue
                download = _safe_download(href, final_url or item["article"])
                if download:
                    break
            if not download:
                logger.info("[aiyi1] 文章页未找到下载直链: %s", item["article"])
                continue

            candidates.append(
                SubtitleCandidate(
                    source=self.name,
                    language=item["language"],
                    title=item["title"],
                    detail_url=final_url or item["article"],
                    download_url=download,
                    referer=final_url or item["article"],
                    size_declared=item["size"],
                    file_name=item["file_name"] or urlsplit(download).path.rsplit("/", 1)[-1],
                )
            )
        return candidates

    async def probe_size(self, cand: SubtitleCandidate, *, budget: Budget) -> int | None:
        # 列表页已声明大小，不再额外发请求
        return cand.size_declared

    async def download(self, cand: SubtitleCandidate, *, budget: Budget) -> bytes:
        _, body = await request(
            cand.download_url, referer=cand.referer, budget=budget, gate_name="subtitle_cdn",
        )
        if not body:
            raise DownloadFailed("站点返回空字幕文件")
        return body
