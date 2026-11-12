"""SubtitleCat 适配器：搜索页 → 结果详情页 → 中文 .srt 直链。

页面结构（2026-11 实测）：
- 搜索页 ``GET /index.php?search={code}`` 的 ``table.sub-table`` 每行一条结果，
  ``a[href]`` 指向 ``subs/{id}/{slug}.html``，``.sub-table__metric-value``
  第一个即 SIZE（如 ``56 KB``）。
- 详情页里中文直链形如 ``/subs/{id}/{slug}-zh-CN.srt`` / ``-zh-TW.srt``；
  下载必须带详情页 Referer。
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
    fetch_size,
    fetch_text,
    parse_size,
    request,
    title_matches_code,
)

logger = logging.getLogger(__name__)

SITE = "https://www.subtitlecat.com"
_SEARCH_URL = SITE + "/index.php?search={code}"
_DETAIL_PATH_RE = re.compile(r"/subs/\d+/[^/\\\x00-\x1f]+\.html$")
_SRT_PATH_RE = re.compile(r"/subs/\d+/[^/\\\x00-\x1f]+\.srt$")
_LANG_RE = re.compile(r"-(zh-CN|zh-TW)\.srt$")
_TRANSLATED_RE = re.compile(r"\s*\((?:translated|automatic)[^)]*\)\s*$", re.I)


def _safe_url(value: str, base: str) -> str | None:
    """只接受 https + www.subtitlecat.com + /subs/{digits}/{name}.*，防 SSRF/跳转注入。"""
    try:
        url = urlsplit(urljoin(base, value))
    except ValueError:
        return None
    if url.scheme != "https" or (url.hostname or "").lower() != "www.subtitlecat.com":
        return None
    if url.username or url.password:
        return None
    return url.geturl()


def _clean_title(text: str) -> str:
    return _TRANSLATED_RE.sub("", (text or "").strip()).strip()


class SubtitleCatSource:
    name = "subtitlecat"

    async def search(self, code: str, *, budget: Budget) -> list[SubtitleCandidate]:
        search_url = _SEARCH_URL.format(code=code)
        html, _ = await fetch_text(search_url, gate_name="subtitlecat", budget=budget)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("table.sub-table")
        if table is None:
            logger.warning("[subtitlecat] 搜索页未找到结果表（可能改版或被拦截）: %s", code)
            return []

        results: list[tuple[str, str, int | None]] = []
        for link in table.select("a[href]"):
            href = str(link.get("href") or "")
            detail = _safe_url(href, SITE)
            if not detail or not _DETAIL_PATH_RE.search(urlsplit(detail).path):
                continue
            title = _clean_title(link.get_text(" ", strip=True))
            if not title_matches_code(title, code):
                continue
            if any(detail == item[1] for item in results):
                continue
            size_text = ""
            row = link.find_parent("tr")
            if row is not None:
                cell = row.select_one(".sub-table__metric-value")
                if cell is not None:
                    size_text = cell.get_text(" ", strip=True)
            results.append((title, detail, parse_size(size_text)))
            if len(results) >= SEARCH_RESULTS_LIMIT:
                break

        candidates: list[SubtitleCandidate] = []
        for title, detail, size in results:
            if budget.expired():
                break
            try:
                page_html, _ = await fetch_text(detail, referer=search_url,
                                                gate_name="subtitlecat", budget=budget)
            except SourceBlocked:
                raise
            except Exception as exc:  # noqa: BLE001 - 单条详情页失败不中断整体
                logger.info("[subtitlecat] 详情页跳过 %s: %s", detail, exc)
                continue

            page = BeautifulSoup(page_html, "html.parser")
            seen_lang: set[str] = set()
            seen_url: set[str] = set()
            for link in page.select("a[href]"):
                href = str(link.get("href") or "")
                url = _safe_url(href, detail)
                if not url or not _SRT_PATH_RE.search(urlsplit(url).path):
                    continue
                matched = _LANG_RE.search(urlsplit(url).path)
                if not matched:
                    continue
                language = matched.group(1)
                # 同一详情页可能给出多个同语言直链，取第一个即可
                if language in seen_lang or url in seen_url:
                    continue
                seen_lang.add(language)
                seen_url.add(url)
                candidates.append(
                    SubtitleCandidate(
                        source=self.name,
                        language=language,
                        title=title,
                        detail_url=detail,
                        download_url=url,
                        referer=detail,
                        size_declared=size,
                        file_name=urlsplit(url).path.rsplit("/", 1)[-1],
                    )
                )
        return candidates

    async def probe_size(self, cand: SubtitleCandidate, *, budget: Budget) -> int | None:
        try:
            return await fetch_size(cand.download_url, referer=cand.referer, budget=budget)
        except Exception as exc:  # noqa: BLE001 - 探测失败按未知大小处理
            logger.info("[subtitlecat] HEAD 探测失败 %s: %s", cand.download_url, exc)
            return None

    async def download(self, cand: SubtitleCandidate, *, budget: Budget) -> bytes:
        _, body = await request(
            cand.download_url, referer=cand.referer, budget=budget, gate_name="subtitle_cdn",
        )
        if not body:
            raise DownloadFailed("站点返回空字幕文件")
        return body
