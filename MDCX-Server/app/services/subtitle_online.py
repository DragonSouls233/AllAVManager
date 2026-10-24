"""SubtitleCat 在线中文字幕搜索（移植自 peach，独立实现，仅借鉴思路）。

peach 为 AGPL-3.0、MDCX 为 MIT，故本文件不复制其源码，只复用其 SubtitleCat
页面结构与「按番号匹配、简繁中文、统一转 WebVTT」策略。

对外提供三个 async 协程：
- search(code, offset=0) -> {results:[{id,title,language,format}], more, source}
- files(subtitle_id)     -> {files:[{index,language,format,name}]}
- load(subtitle_id, index) -> (text, encoding, filename)  text 已是 WebVTT 文本
"""
from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

MAX_BYTES = 4 * 1024 * 1024
SITE = "https://www.subtitlecat.com"
PAGE_SIZE = 6
LANGUAGES = {"zh-CN": "简体中文", "zh-TW": "繁体中文"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SubtitleSearchError(ValueError):
    """字幕搜索/下载失败（含参数非法、页面结构变化、超 4MiB 等）。"""


def _url(value: str, suffix: str) -> str:
    """校验并规整 SubtitleCat 内部地址，只允许 https 的 /subs/<数字>/<名><suffix>。"""
    try:
        url = urlsplit(urljoin(SITE + "/", value))
        valid = url.port in (None, 443)
    except ValueError as error:
        raise SubtitleSearchError("字幕下载地址不受支持") from error
    path = unquote(url.path)
    if (
        not valid
        or url.scheme != "https"
        or url.hostname != "www.subtitlecat.com"
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not re.fullmatch(r"/subs/\d+/[^/\\\x00-\x1f]+" + re.escape(suffix), path)
    ):
        raise SubtitleSearchError("字幕下载地址不受支持")
    return url.geturl()


async def _get(client: httpx.AsyncClient, url: str, *, suffix: str = "", params: dict | None = None) -> bytes:
    try:
        for _ in range(4):
            async with client.stream("GET", url, params=params) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = _url(str(response.url.join(response.headers.get("location", ""))), suffix)
                    params = None
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise SubtitleSearchError("字幕响应超过 4 MiB")
                return bytes(data)
    except httpx.HTTPError as error:
        raise SubtitleSearchError("SubtitleCat 暂时无法连接，请稍后重试") from error
    raise SubtitleSearchError("字幕下载重定向次数过多")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def _id(url: str) -> str:
    return base64.urlsafe_b64encode(urlsplit(url).path.encode()).decode().rstrip("=")


def _detail(subtitle_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,1600}", subtitle_id):
        raise SubtitleSearchError("字幕编号无效")
    try:
        path = base64.b64decode(
            subtitle_id + "=" * (-len(subtitle_id) % 4), altchars=b"-_", validate=True
        ).decode()
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise SubtitleSearchError("字幕编号无效") from error
    return _url(path, ".html")


async def _files(client: httpx.AsyncClient, url: str) -> list[dict]:
    page = BeautifulSoup(await _get(client, url, suffix=".html"), "html.parser")
    rows: dict[str, dict] = {}
    for link in page.select("a[href]"):
        href = str(link["href"])
        language = next((code for code in LANGUAGES if href.endswith(f"-{code}.srt")), None)
        if language:
            try:
                download = _url(href, ".srt")
            except SubtitleSearchError:
                continue
            rows.setdefault(
                language,
                {
                    "name": unquote(urlsplit(download).path.rsplit("/", 1)[-1]),
                    "language": LANGUAGES[language],
                    "url": download,
                },
            )
    return [
        dict(index=index, playable=True, **rows[code])
        for index, code in enumerate(LANGUAGES)
        if code in rows
    ]


def _extract_code(text: str) -> str | None:
    """从用户输入里提取番号（SSIS-001 / 259LUXU-1004 / ABP-001 等）。

    前缀允许字母开头、可含数字（如 259LUXU），但必须至少含一个字母，
    避免把纯日期/纯数字误当番号。
    """
    m = re.search(r"\b([A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*)[-_]?(\d{2,5})\b", text.strip().upper())
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _norm_code(code: str) -> str:
    return code.replace("_", "-").upper()


def _matches(title: str, code: str) -> bool:
    """标题是否命中目标番号：先从标题提取番号做精确比对，再用边界兜底。

    精确比对能避免 `SSIS-1` 误中 `SSIS-100` 这类前缀陷阱。
    """
    norm = _norm_code(code)
    title_code = _extract_code(title)
    if title_code and _norm_code(title_code) == norm:
        return True
    # 兜底：标题里直接出现规整后的番号（数字后须有边界，防止 001 命中 0012）
    esc = re.escape(norm)
    return bool(re.search(r"(?<![A-Za-z0-9])" + esc + r"(?![0-9])", title.upper().replace("_", "-")))


async def search(query: str, offset: int = 0) -> dict:
    query = (query or "").strip()
    if not (3 <= len(query) <= 200) or not (0 <= offset < 60) or offset % PAGE_SIZE:
        raise SubtitleSearchError("搜索词需为 3–200 个字符，分页位置无效时请重新搜索")
    code = _extract_code(query)
    with_query = code or query
    async with _client() as client:
        page = BeautifulSoup(
            await _get(client, SITE + "/index.php", params={"search": with_query}),
            "html.parser",
        )
        table = page.select_one("table.sub-table")
        if table is None:
            raise SubtitleSearchError("SubtitleCat 搜索页面未取得，请稍后重试")
        candidates: dict[str, str] = {}
        for link in table.select("a[href]"):
            title = link.get_text(" ", strip=True)
            if code and not _matches(title, code):
                continue
            try:
                url = _url(str(link["href"]), ".html")
            except SubtitleSearchError:
                continue
            candidates.setdefault(url, title)
        results = []
        for url, title in list(candidates.items())[offset : offset + PAGE_SIZE]:
            files = await _files(client, url)
            if files:
                results.append(
                    {
                        "id": _id(url),
                        "title": title,
                        "language": " / ".join(row["language"] for row in files),
                        "format": "SRT",
                    }
                )
    return {
        "results": results,
        "more": offset + PAGE_SIZE < min(len(candidates), 60),
        "source": "SubtitleCat",
    }


async def files(subtitle_id: str) -> dict:
    async with _client() as client:
        rows = await _files(client, _detail(subtitle_id))
    return {"files": [{k: v for k, v in row.items() if k != "url"} for row in rows]}


async def load(subtitle_id: str, index: int) -> tuple[str, str, str]:
    """下载并返回某个字幕文件的 WebVTT 文本、编码与文件名。"""
    async with _client() as client:
        row = next(
            (r for r in await _files(client, _detail(subtitle_id)) if r["index"] == index),
            None,
        )
        if row is None:
            raise SubtitleSearchError("中文字幕文件不存在")
        raw = await _get(client, row["url"], suffix=".srt")
    text, encoding = _to_webvtt(raw)
    return text, encoding, row["name"]


# ----------------------------------------------------------------------
# 字幕转 WebVTT（覆盖 SRT / ASS / SSA / VTT；不依赖第三方转码库）
# ----------------------------------------------------------------------

_SUB_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")


def _sub_time_to_vtt(mm: re.Match) -> str:
    h, m, s, f = mm.groups()
    frac = f.ljust(3, "0")[:3]
    return f"{int(h):02d}:{m}:{s}.{frac}"


def _strip_ass_styles(text: str) -> str:
    """去掉 ASS/SSA 行内样式标签（花括号包裹）与软换行标记。"""
    text = re.sub(r"\{\\[^}]*\}", "", text)
    return text.replace("\\N", "\n").replace("\\n", "\n").strip()


def _to_webvtt(raw: bytes) -> tuple[str, str]:
    """把 SRT/ASS/SSA/VTT 字节统一转成 WebVTT 文本。返回 (vtt_text, source_encoding)。"""
    if len(raw) > MAX_BYTES:
        raise SubtitleSearchError("字幕文件超过 4 MiB")
    # 探测编码：先 UTF-8，再 Big5（繁中），再 GBK（简中）
    text: str | None = None
    encoding = "utf-8"
    for enc in ("utf-8", "utf-8-sig", "big5", "gbk", "shift_jis"):
        try:
            text = raw.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
        encoding = "utf-8(replace)"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lowered = text.lstrip().lower()
    if lowered.startswith("webvtt"):
        return text, encoding
    if lowered.startswith("[script info]") or lowered.startswith("[v4") or lowered.startswith("[v3"):
        return _ass_to_vtt(text), encoding
    if "-->" in text:
        return _srt_to_vtt(text), encoding
    # 兜底：无时间轴的纯文本，原样返回
    return text, encoding


def _srt_to_vtt(text: str) -> str:
    out = ["WEBVTT", ""]
    block = []
    for line in text.split("\n"):
        if line.strip() == "":
            if len(block) >= 2:
                # 去掉序号行（纯数字），仅保留时间轴 + 文本
                body = block[1:] if re.match(r"^\d+$", block[0].strip()) else block
                joined = "\n".join(body)
                if "-->" in joined:
                    joined = _SUB_TIME.sub(_sub_time_to_vtt, joined)
                    out.append(joined)
                    out.append("")
            block = []
        else:
            block.append(line)
    if len(block) >= 2:
        body = block[1:] if re.match(r"^\d+$", block[0].strip()) else block
        joined = "\n".join(body)
        if "-->" in joined:
            joined = _SUB_TIME.sub(_sub_time_to_vtt, joined)
            out.append(joined)
            out.append("")
    return "\n".join(out).strip() + "\n"


def _ass_to_vtt(text: str) -> str:
    # 解析 [Events] 里的 Format 行（含 start/text 的那条），定位 Start/End/Text 列。
    # 注意 [V4+ Styles] 段也有一条 Format:，必须跳过，只取事件格式。
    fmt = None
    for line in text.split("\n"):
        if line.strip().lower().startswith("format:"):
            cand = [p.strip().lower() for p in line.split(":", 1)[1].split(",")]
            if "start" in cand and "text" in cand:
                fmt = cand
                break
    start_i = end_i = text_i = None
    if fmt:
        for i, name in enumerate(fmt):
            if name == "start":
                start_i = i
            elif name == "end":
                end_i = i
            elif name in ("text", "text/"):
                text_i = i
    out = ["WEBVTT", ""]
    for line in text.split("\n"):
        if not line.strip().lower().startswith("dialogue:"):
            continue
        payload = line.split(":", 1)[1]
        parts = payload.split(",", maxsplit=max((text_i or 0), (start_i or 0), (end_i or 0)))
        if start_i is None or end_i is None or text_i is None:
            continue
        start = _SUB_TIME.sub(_sub_time_to_vtt, parts[start_i].strip())
        end = _SUB_TIME.sub(_sub_time_to_vtt, parts[end_i].strip())
        body = _strip_ass_styles(parts[text_i])
        if "-->" in f"{start} --> {end}":
            out.append(f"{start} --> {end}")
            out.append(body)
            out.append("")
    return "\n".join(out).strip() + "\n"
