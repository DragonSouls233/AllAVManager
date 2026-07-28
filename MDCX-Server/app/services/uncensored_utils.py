"""无码/FC2 专用工具集。

功能：
1. 无码番号检测增强（移植自 mdcx-diy number.py is_uncensored）
2. 无码封面补填（AVSOX 专用，比通用 cover_refill 更激进的重试）
3. 纯数字番号格式化（1pondo, caribbeancom 等）
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 无码番号检测（移植自 mdcx-diy number.py）
# ---------------------------------------------------------------------------

# 无码站点前缀列表
UNCENSORED_PREFIXES: set[str] = {
    "1PONDO", "10MUSUME", "CARIBBEANCOM", "CARIBBEAN",
    "PACOPACOMAMA", "TOKYO-HOT", "TOKYOHOT",
    "HEYZO", "KIN8TENGOKU", "GACHI", "GACHINET",
    "MKD", "BT", "CT", "EMP", "CCDV", "CWP",
    "JAV", "KTG", "S2M", "SKY", "SKYHD", "RED",
    "MGR", "DQ", "MKY", "MMR", "MD", "H4610",
    "H0930", "C0930", "LAF", "IK", "SMD", "T28",
    "TH101", "XCITY", "OKUW", "NAGO", "NAC",
    "SGA", "STAR", "GQ", "FHD", "MXB", "MX2",
    "PPS", "ONE", "DVAJ", "XVSR", "BRO",
}

# 无码数字番号模式
_PATTERN_DIGIT_UNCENSORED = re.compile(r"\b(\d{6,8}[-_]\d{2,5})\b")
_PATTERN_TIME_UNCENSORED = re.compile(
    r"\b([^.]+\.\d{2}\.\d{2}\.\d{2})\b"
)
_PATTERN_PREFIX_UNCENSORED = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in sorted(UNCENSORED_PREFIXES, key=len, reverse=True)) +
    r")[-_ ]?(\d{2,6}[A-Za-z]?\d{0,4})\b",
    re.I,
)
_PATTERN_N_DIGIT = re.compile(r"\b(n\d{4})\b", re.I)


@dataclass
class UncensoredResult:
    code: str
    prefix: str = ""
    raw: str = ""
    source: str = ""         # "amazon" | "avsox" | "digit" | "time" | "prefix"
    confidence: float = 1.0


def is_uncensored_code(text: str) -> Optional[UncensoredResult]:
    """检测文本中的无码番号。

    优先级:
    1. 纯数字模式: 111111-111
    2. 时间格式: 1pondo.11.11.11
    3. 前缀模式: HEYZO-1234, TOKYO-HOT-n1234
    4. n 数字: n1234 (Tokyo-Hot)
    """
    text = text.strip().upper()

    # 1. 纯数字无码
    m = _PATTERN_DIGIT_UNCENSORED.search(text)
    if m:
        return UncensoredResult(
            code=m.group(1).replace("_", "-"),
            source="digit",
        )

    # 2. 前缀无码
    m = _PATTERN_PREFIX_UNCENSORED.search(text)
    if m:
        prefix = m.group(1).upper()
        num = m.group(2)
        if prefix in UNCENSORED_PREFIXES:
            return UncensoredResult(
                code=f"{prefix}-{num}",
                prefix=prefix,
                source="prefix",
            )

    # 3. n 数字 (Tokyo-Hot)
    m = _PATTERN_N_DIGIT.search(text)
    if m:
        return UncensoredResult(
            code=m.group(1),
            prefix="TOKYO-HOT",
            source="prefix",
        )

    return None


def format_uncensored_code(code: str) -> str:
    """格式化无码番号为标准形式。

    Examples:
        "1pondo-111111-111" → "1PONDO-111111-111"
        "HEYZO 1234" → "HEYZO-1234"
        "caribbeancom-111111-001" → "CARIBBEANCOM-111111-001"
    """
    code = code.strip().upper()

    # 特殊处理 1pondo/caribbeancom 的时间格式
    for prefix in ("1PONDO", "CARIBBEANCOM", "10MUSUME", "PACOPACOMAMA"):
        if code.startswith(prefix):
            # 提取数字部分
            nums = re.findall(r"\d+", code)
            if len(nums) >= 2:
                return f"{prefix}-{nums[-2]}-{nums[-1]}"

    # 一般格式
    parts = re.split(r"[-_\s]+", code, maxsplit=1)
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"

    return code


# ---------------------------------------------------------------------------
# AVSOX 无码封面补填
# ---------------------------------------------------------------------------

async def fetch_uncensored_cover(code: str) -> Optional[bytes]:
    """从 AVSOX 获取无码封面图片。

    AVSOX 是无码 JAV 的主要封面源，比 JavBus 覆盖率更高。
    """
    import httpx
    from bs4 import BeautifulSoup

    base = "https://www.avsox.click"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Language": "zh-CN",
    }

    # 先搜索
    search_url = f"{base}/cn/search/{code}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            r = await client.get(search_url, headers=headers)
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, "html.parser")
            box = soup.select_one("a.movie-box")
            if not box or not box.get("href"):
                return None

            detail_url = box["href"]
            if detail_url.startswith("//"):
                detail_url = "https:" + detail_url
            elif not detail_url.startswith("http"):
                detail_url = base + detail_url

            # 获取详情页
            rd = await client.get(detail_url, headers=headers)
            if rd.status_code != 200:
                return None

            detail_soup = BeautifulSoup(rd.text, "html.parser")
            big = detail_soup.select_one("a.bigImage")
            cover_url = None
            if big:
                href = big.get("href") or ""
                img = big.select_one("img")
                cover_url = href or (img.get("src", "") if img else "")

            if not cover_url:
                og = detail_soup.select_one('meta[property="og:image"]')
                if og and og.get("content"):
                    cover_url = og["content"]

            if cover_url:
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url
                elif not cover_url.startswith("http"):
                    cover_url = base + cover_url

                ri = await client.get(cover_url, headers={"Referer": base + "/"})
                if ri.status_code == 200 and len(ri.content) > 2000:
                    return ri.content

    except Exception as e:
        logger.warning("AVSOX cover fetch failed for %s: %s", code, e)

    return None


async def bulk_check_uncensored(codes: list[str], concurrency: int = 3) -> dict[str, bool]:
    """批量检查无码番号在 AVSOX 上是否有封面。

    Returns:
        {code: has_cover}
    """
    sem = asyncio.Semaphore(concurrency)

    async def _check_one(code: str) -> tuple[str, bool]:
        async with sem:
            cover = await fetch_uncensored_cover(code)
            return code, cover is not None

    results = await asyncio.gather(*(
        _check_one(c) for c in codes
    ))
    return dict(results)
