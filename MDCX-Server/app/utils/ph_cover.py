"""PORNHUB 封面图址解析兜底。

## 为什么需要这个（2026-10-13 实测）

PornHub 现在混用三种图址形态，可用性差别极大：

1. **旧形态** ``ei.phncdn.com/videos/YYYY/MM/DD/<id>/original/(m=..)(mh=..)0.jpg``
   —— 哈希签名，基本长效，可用。
2. **新形态** ``pix-fl / pix-cdn77.phncdn.com/.../original/<uuid>.jpg/plain/rs:fit:320:240
   ?hdnea=st=..~exp=..~hmac=..``（或 ``?hash=..&validto=..``）
   —— **令牌只有 24 小时有效**（``exp`` 字段），过期后必然 403/470；
   并且**对一部分视频返回的是 MP4 而不是图片**（响应头 ``ftyp``），下载器按魔数校验会
   正确地拒收，于是表现为"刮削成功但没有封面"。
3. **长效形态** ``pix-egi.phncdn.com/.../original/<uuid>.jpg/plain/rs:fit:350:196
   ?validfrom=1751342400&validto=4891363200&hash=..``
   —— ``validto`` 到公元 2124 年，实测 200 真 JPEG，是唯一稳定形态。

🔴 **关键约束**：长效地址**只能从 ``view_video`` 页面原文里整段取**。
实测把 DB 里已有签名地址的 host 换成 ``pix-egi``、查询换成 ``validfrom/validto``
（不带 hash）会直接返回 **HTTP 470**，所以不要试图"改写"已有 URL。

## 用途

刮削 / 补刮 / 批量补封面时，当爬虫给的签名图址下载失败（过期、被拒、返回 MP4），
调用本模块抓一次详情页，按"长效 > 新签名 > 旧签名"排序给出候选，逐个尝试即可下到图。
"""

from __future__ import annotations

import re
from typing import List, Optional

VIEW_PAGE = "https://www.pornhub.com/view_video.php?viewkey={vk}"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 只接受「带 .jpg 且带缩略变换参数」的 phncdn 地址，避免把视频流/头像/推荐位当封面
_IMG_URL_RE = re.compile(
    r'https?://[a-z0-9.\-]*phncdn\.com/[^\s"\'<>\\]+', re.I
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I
)
# 取路径里的数字视频 id：/videos/202606/06/51387735/...
_VIDEO_ID_RE = re.compile(r'/videos/\d{6}/\d{2}/\d+/(\d+)/')


def viewkey_from_code(code: str) -> Optional[str]:
    """从库里的 code（``ph<viewkey>`` 或裸 viewkey）取出裸 viewkey。

    判据统一走 ``app.scraper.number.is_valid_ph_viewkey``，不在这里另立标准。
    """
    if not code:
        return None
    try:
        from app.scraper.number import is_valid_ph_viewkey
    except Exception:
        is_valid_ph_viewkey = None

    c = code.strip()
    if c.lower().startswith("ph"):
        c = c[2:]
    c = c.strip().lower()
    if not c:
        return None
    if is_valid_ph_viewkey is not None:
        return c if is_valid_ph_viewkey(c) else None
    return c if re.fullmatch(r"[a-z0-9]{10,20}", c) else None


def _is_imageish(u: str) -> bool:
    if "phncdn" not in u.lower():
        return False
    if ".jpg" not in u.lower():
        return False
    # 要么是 ei 老形态 original/(m=..)0.jpg，要么是 pix 新形态带 /plain/rs:fit:
    if "/plain/rs:fit:" in u:
        return True
    return "/original/" in u and "ei.phncdn.com" in u.lower()


def _tier(u: str) -> int:
    """候选排序：数字越小越优先。"""
    ul = u.lower()
    if "pix-egi.phncdn.com" in ul:
        return 0                      # 长效，validto≈2124
    if "pix-fl.phncdn.com" in ul:
        return 1                      # 新签名，hdnea 令牌
    if "pix-cdn77.phncdn.com" in ul:
        return 3                      # 新签名，hash 令牌（实测常返 MP4）
    return 2                          # ei 老形态


def _rank(urls: List[str], prefer_id: Optional[str], limit: int) -> List[str]:
    seen, out = set(), []
    if prefer_id:
        exact = [u for u in urls if f"/{prefer_id}/" in u]
        other = [u for u in urls if f"/{prefer_id}/" not in u]
        urls = exact + other
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append((_tier(u), len(out), u))
    out.sort(key=lambda t: (t[0], t[1]))
    return [u for _, _, u in out[:limit]]


def extract_candidates(html: str, prefer_id: Optional[str] = None,
                       limit: int = 5) -> List[str]:
    """从 view_video 页面 HTML 里提取候选封面图址（已按可用性排序）。"""
    if not html:
        return []
    og = None
    m = _OG_IMAGE_RE.search(html) or _OG_IMAGE_RE_ALT.search(html)
    if m:
        og = m.group(1).replace("&amp;", "&")

    vid = prefer_id
    if not vid:
        for src in (og,):
            if src:
                mm = _VIDEO_ID_RE.search(src)
                if mm:
                    vid = mm.group(1)
                    break

    urls = [u for u in _IMG_URL_RE.findall(html) if _is_imageish(u)]
    if og and _is_imageish(og):
        urls.insert(0, og)
    return _rank(urls, vid, limit)


async def fetch_cover_candidates(code: str, limit: int = 5,
                                 timeout: int = 45) -> List[str]:
    """抓 view_video 页面，返回候选封面图址（长效优先）。

    任何异常都吞掉并返回空列表 —— 这是刮削链路的兜底，绝不能把主流程带崩。
    """
    vk = viewkey_from_code(code)
    if not vk:
        return []
    try:
        from app.services.proxy_manager import get_effective_proxy_url
        from app.utils.http_client import AsyncHttpClient

        client = AsyncHttpClient(proxy=get_effective_proxy_url(), timeout=timeout)
        resp = await client.get(
            VIEW_PAGE.format(vk=vk),
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
        )
        if not resp or resp.status_code != 200:
            return []
        return extract_candidates(getattr(resp, "text", "") or "", None, limit)
    except Exception:
        return []