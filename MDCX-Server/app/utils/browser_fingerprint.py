"""
浏览器指纹池 - v3.1

基于 Hazard804 MDCX 的 network_fingerprint.py 实现，提供：
- 6 个预定义浏览器指纹（Chrome 136/131/124 Win/Mac + Firefox 135/133 Win）
- 与 curl_cffi TLS impersonate 对齐
- 按 host + 用途选择指纹
- 请求用途推断（document/api/asset/download）
- Amazon.co.jp 自动切换日语 Accept-Language
- 本地地址与 CF bypass URL 跳过指纹注入

设计目标：
- 保持 TLS 指纹与 HTTP 请求头一致，避免被反爬识别
- 同一 host 在同一会话中尽量使用同一指纹（减少指纹漂移）
- 支持排除上一次使用的指纹（避免连续重复）
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Literal, Optional
from urllib.parse import urlsplit

logger = None  # 延迟初始化，避免循环导入

RequestPurpose = Literal["document", "api", "asset", "download"]


@dataclass(frozen=True)
class BrowserFingerprint:
    """一组保持 TLS impersonate 与 HTTP 请求头一致的浏览器画像。

    frozen=True 使实例不可变，可作为字典 key 与集合元素。
    """

    fingerprint_id: str
    impersonate: str  # curl_cffi 的 impersonate 参数值
    family: Literal["chrome", "firefox"]
    platform: str
    headers: dict[str, str]


# ============================================
# 预定义指纹池（与 curl_cffi 支持的版本对齐）
# ============================================

_CHROME_136_WIN = BrowserFingerprint(
    fingerprint_id="chrome136_win",
    impersonate="chrome136",
    family="chrome",
    platform="Windows",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
)

_CHROME_131_WIN = BrowserFingerprint(
    fingerprint_id="chrome131_win",
    impersonate="chrome131",
    family="chrome",
    platform="Windows",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
)

_CHROME_124_WIN = BrowserFingerprint(
    fingerprint_id="chrome124_win",
    impersonate="chrome124",
    family="chrome",
    platform="Windows",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
)

_CHROME_136_MAC = BrowserFingerprint(
    fingerprint_id="chrome136_macos",
    impersonate="chrome136",
    family="chrome",
    platform="macOS",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    },
)

_FIREFOX_135_WIN = BrowserFingerprint(
    fingerprint_id="firefox135_win",
    impersonate="firefox135",
    family="firefox",
    platform="Windows",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
)

_FIREFOX_133_WIN = BrowserFingerprint(
    fingerprint_id="firefox133_win",
    impersonate="firefox133",
    family="firefox",
    platform="Windows",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
)


_DEFAULT_FINGERPRINTS: tuple[BrowserFingerprint, ...] = (
    _CHROME_136_WIN,
    _CHROME_131_WIN,
    _CHROME_124_WIN,
    _CHROME_136_MAC,
    _FIREFOX_135_WIN,
    _FIREFOX_133_WIN,
)

# Amazon.co.jp 使用与默认池相同的指纹，但 build_fingerprint_headers 会切换 Accept-Language
_AMAZON_FINGERPRINTS: tuple[BrowserFingerprint, ...] = _DEFAULT_FINGERPRINTS

# API 请求倾向使用较新的 Chrome 指纹（更广泛的兼容性）
_API_FINGERPRINTS: tuple[BrowserFingerprint, ...] = (_CHROME_136_WIN, _CHROME_131_WIN)

# 资源/下载请求可以使用任意指纹
_ASSET_FINGERPRINTS: tuple[BrowserFingerprint, ...] = _DEFAULT_FINGERPRINTS


# 资源文件后缀（用于推断 asset 用途）
_ASSET_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg", ".ico",
    ".mp4", ".m4v", ".webm", ".m3u8", ".ts",
    ".zip", ".7z", ".rar",
)


# ============================================
# host → fingerprint 缓存（同一会话内同一 host 尽量使用同一指纹）
# ============================================

_host_fingerprint_cache: dict[str, BrowserFingerprint] = {}
_host_cache_lock = threading.Lock()


# ============================================
# TLS 指纹封禁记录（被拦时自动轮换）— amane #364
# ============================================
# 现象：javdb / javbus / dmm 一类站点会按「TLS 指纹（JA3/JA4）+ UA」组合封禁，
# 表现是**稳定返回 403/503 挑战页**，而不是偶发超时。
#
# 旧实现的缺陷：指纹在请求开始前**只选一次**，重试 N 次全用同一个指纹 ⇒
# 一旦被指纹封禁，本次请求 100% 全失败，接着整源被判失败并喂给熔断器。
#
# 新实现：
#   1) 识别「被拦」信号（状态码 + 挑战页特征），记入 host 级封禁表（默认 30 分钟）；
#   2) 后续请求自动避开已封禁指纹（池子全封才回退到全池，保证不死循环）；
#   3) 同一次请求的重试循环里**立刻轮换**（见 http_client._get_impl/_post_impl）。
#
# ⚠️ 只认「站方主动拒绝」类信号；404/410 是「资源不存在」，绝不轮换
#    （换指纹也拿不到，只会白白放大请求量）。

# 有可能属于「指纹被封」的状态码。⚠️ 注意：进了这个集合**不等于**要轮换，
# 还必须有正文/响应头证据（见 should_rotate_fingerprint 的注释）。
_ROTATABLE_STATUSES = frozenset({403, 405, 406, 429, 503, 521, 522, 523, 524})

# 挑战页 / WAF 拦截页正文特征（小写比对；只扫正文前 4KB，避免大页面开销）
_BLOCK_BODY_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "enable javascript and cookies to continue",
    "please enable javascript",
    "cf-browser-verification",
    "__cf_chl",
    "cf_chl_opt",
    "challenge-platform",
    "error code: 1020",
    "access denied",
    "you have been blocked",
    "request unsuccessful",
    "_incapsula_resource",
    "incapsula",
    "imperva",
)

# WAF 特征响应头（出现即说明这一跳被 WAF 处理过；比正文更省、更准）
_BLOCK_HEADER_MARKERS = (
    "cf-mitigated",      # Cloudflare: challenge / origin 等
    "cf-chl-out",
    "x-sucuri-id",       # Sucuri WAF
    "x-incapsula",       # Imperva/Incapsula
    "x-iinfo",
    "x-protected-by",
    "x-waf-event",
)

_BLOCK_BODY_SCAN_LIMIT = 4096
_BLOCK_TTL_SECONDS = 1800.0  # 30 分钟：足够熬过一次封禁，又不至于永久误判
_BLOCK_MAX_TRACKED_PER_HOST = 16

# host(小写) → {fingerprint_id: 过期时间戳}
_blocked_fingerprints: dict[str, dict[str, float]] = {}
_blocked_lock = threading.Lock()


def has_challenge_markers(body: str = "", headers: Optional[dict] = None) -> bool:
    """响应里是否带 WAF / 挑战页特征（只看证据，不看状态码）。

    只扫正文前 4KB：挑战页特征都在页面头部，没必要为几十 MB 的页面全量 decode。
    任一环节出错都返回 False —— 判不出来就当作「不是挑战页」，绝不改变既有行为。
    """
    if headers:
        try:
            lowered = {str(k).lower() for k in headers}
        except Exception:
            lowered = set()
        if any(marker in lowered for marker in _BLOCK_HEADER_MARKERS):
            return True

    if not body:
        return False
    try:
        head = body[:_BLOCK_BODY_SCAN_LIMIT].lower()
    except Exception:
        return False
    return any(marker in head for marker in _BLOCK_BODY_MARKERS)


def should_rotate_fingerprint(
    status_code: Optional[int] = None,
    body: str = "",
    headers: Optional[dict] = None,
) -> bool:
    """是否值得「换一个 TLS 指纹再试一次」。

    🔴 判据必须是「状态码可能属于封禁」**且**「响应里有 WAF 证据」，两者缺一不可。

    只看状态码为什么不行：403/429 既可能是封禁，也可能是纯业务拒绝
    （theporndb / missav_api 未配 Token 时源站恒返 403）。2026-09-29 刚把 403
    放进「不重试」集合，省下每番号约 20s 的重试开销；若这里改回「见 403 就轮换」，
    等于把那次优化全退掉。同理 429 纯限流换指纹没有任何收益。

    代价是「正文没有特征字的挑战页」识别不到 —— 那种情况维持现状（不重试），
    属于**没有变好，也没有变坏**，可接受。
    """
    if status_code is None:
        return False
    try:
        if int(status_code) not in _ROTATABLE_STATUSES:
            return False
    except (TypeError, ValueError):
        return False
    return has_challenge_markers(body, headers)


def mark_fingerprint_blocked(
    host: str,
    fingerprint_id: str,
    *,
    ttl: float = _BLOCK_TTL_SECONDS,
) -> None:
    """把某个指纹在该 host 上标记为「被封禁」，有效期内自动避开。"""
    if not host or not fingerprint_id:
        return
    key = host.lower()
    expire = time.time() + (ttl if ttl and ttl > 0 else _BLOCK_TTL_SECONDS)
    with _blocked_lock:
        bucket = _blocked_fingerprints.setdefault(key, {})
        # 顺带清理已过期的，防止表无限增长
        now = time.time()
        for fid in [k for k, v in bucket.items() if v <= now]:
            bucket.pop(fid, None)
        if len(bucket) >= _BLOCK_MAX_TRACKED_PER_HOST and fingerprint_id not in bucket:
            # 极端情况（全池被封）丢弃最早过期的一条，保持表有界
            oldest = min(bucket, key=lambda k: bucket[k])
            bucket.pop(oldest, None)
        bucket[fingerprint_id] = expire
    _get_logger().info(
        "TLS 指纹 %s 在 %s 上被判定封禁，%d 秒内自动避开",
        fingerprint_id, key, int(ttl or _BLOCK_TTL_SECONDS),
    )


def blocked_fingerprint_ids(host: str) -> set[str]:
    """返回该 host 当前仍处于封禁期的指纹 ID 集合（已过期的顺带清理）。"""
    if not host:
        return set()
    key = host.lower()
    now = time.time()
    with _blocked_lock:
        bucket = _blocked_fingerprints.get(key)
        if not bucket:
            return set()
        alive = {k for k, v in bucket.items() if v > now}
        if len(alive) != len(bucket):
            _blocked_fingerprints[key] = {k: bucket[k] for k in alive} or {}
            if not _blocked_fingerprints[key]:
                _blocked_fingerprints.pop(key, None)
        return set(alive)


def clear_blocked(host: Optional[str] = None) -> None:
    """清空封禁记录（测试用；host=None 表示全清）。"""
    with _blocked_lock:
        if host is None:
            _blocked_fingerprints.clear()
        else:
            _blocked_fingerprints.pop(host.lower(), None)


def _get_logger():
    """延迟获取 logger，避免循环导入"""
    global logger
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    return logger


# ============================================
# 核心函数
# ============================================

def select_fingerprint(
    host: str,
    *,
    purpose: RequestPurpose = "document",
    exclude_fingerprint_id: str = "",
    exclude_ids: Optional[Iterable[str]] = None,
    use_cache: bool = True,
) -> BrowserFingerprint:
    """按 host 和用途选择浏览器指纹。

    策略：
    - amazon.co.jp 走专用池（其实同默认池，但 build_headers 会切换语言）
    - api 用途使用较新 Chrome 指纹池
    - asset/download 用途使用默认池
    - use_cache=True 时，同一 host 在同一进程内复用同一指纹（减少漂移）
    - **自动避开该 host 上已被判定封禁的指纹**（见上节封禁记录）

    Args:
        host: 目标主机名（域名）
        purpose: 请求用途
        exclude_fingerprint_id: 需排除的指纹 ID（避免连续重复）
        exclude_ids: 需排除的指纹 ID 集合（重试轮换时把本轮已试过的全排掉）
        use_cache: 是否使用 host 缓存

    Returns:
        BrowserFingerprint 实例
    """
    normalized_host = (host or "").lower()

    excluded: set[str] = set(exclude_ids or ())
    if exclude_fingerprint_id:
        excluded.add(exclude_fingerprint_id)

    # 封禁记录：即使调用方没要求轮换，也要避开已封指纹
    blocked = blocked_fingerprint_ids(normalized_host) if normalized_host else set()

    # 缓存命中（缓存里的指纹没被排除、也没被封禁才用）
    if use_cache and normalized_host:
        with _host_cache_lock:
            cached = _host_fingerprint_cache.get(normalized_host)
        if (
            cached is not None
            and cached.fingerprint_id not in excluded
            and cached.fingerprint_id not in blocked
        ):
            return cached

    candidates: set[str] = excluded | blocked

    # 按用途/主机选择候选池
    if normalized_host.endswith("amazon.co.jp"):
        pool = _AMAZON_FINGERPRINTS
    elif purpose == "api":
        pool = _API_FINGERPRINTS
    elif purpose in ("asset", "download"):
        pool = _ASSET_FINGERPRINTS
    else:
        pool = _DEFAULT_FINGERPRINTS

    chosen = _choose_fingerprint(pool, exclude_ids=candidates)

    # 写入缓存（仅为「轮换请求」写缓存会污染 host 稳定性，故仅在无排除时写）
    if use_cache and normalized_host and not excluded:
        with _host_cache_lock:
            _host_fingerprint_cache[normalized_host] = chosen

    return chosen


def select_amazon_fingerprint(
    *,
    exclude_fingerprint_id: str = "",
    exclude_ids: Optional[Iterable[str]] = None,
) -> BrowserFingerprint:
    """选择 Amazon.co.jp 专用指纹"""
    ids: set[str] = set(exclude_ids or ())
    if exclude_fingerprint_id:
        ids.add(exclude_fingerprint_id)
    return _choose_fingerprint(_AMAZON_FINGERPRINTS, exclude_ids=ids)


def _choose_fingerprint(
    fingerprints: tuple[BrowserFingerprint, ...],
    *,
    exclude_fingerprint_id: str = "",
    exclude_ids: Optional[Iterable[str]] = None,
) -> BrowserFingerprint:
    """从候选池中随机选择一个指纹，支持排除多个 ID。

    🔴 池子被排除空时**必须回退到全池**随机：全池都被标记封禁的情况下
    若返回 None 或抛错，请求链会直接断掉（宁可用一个可能也被封的指纹再试）。
    """
    excluded: set[str] = set(exclude_ids or ())
    if exclude_fingerprint_id:
        excluded.add(exclude_fingerprint_id)
    if excluded:
        candidates = [f for f in fingerprints if f.fingerprint_id not in excluded]
        if candidates:
            return random.choice(candidates)
    return random.choice(fingerprints)


def infer_request_purpose(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    stream: bool = False,
    json_data: object = None,
) -> RequestPurpose:
    """推断请求用途。

    判断优先级：
    1. stream=True → download
    2. 含 Range 头 → download
    3. json_data 非空 → api
    4. Accept/Content-Type 含 application/json → api
    5. HEAD 方法 → asset
    6. URL 路径以资源后缀结尾 → asset
    7. 默认 → document
    """
    if stream:
        return "download"
    if _has_header(headers, "range"):
        return "download"
    if json_data is not None:
        return "api"

    accept = _get_header(headers, "accept").lower()
    content_type = _get_header(headers, "content-type").lower()
    if "application/json" in accept or "application/json" in content_type:
        return "api"
    if str(method).upper() == "HEAD":
        return "asset"

    try:
        path = urlsplit(url).path.lower()
    except Exception:
        path = ""
    if any(path.endswith(ext) for ext in _ASSET_EXTENSIONS):
        return "asset"
    return "document"


def should_apply_fingerprint(url: str, *, cf_bypass_url: str = "") -> bool:
    """判断是否应该对指定 URL 应用浏览器指纹。

    跳过条件：
    - 本地地址（127.0.0.1/localhost/::1）
    - 与 cf_bypass_url 同 host（已通过其他方式绕过 CF）
    """
    try:
        parsed = urlsplit(url)
    except Exception:
        return True

    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return False

    if cf_bypass_url:
        try:
            bypass_host = (urlsplit(cf_bypass_url).hostname or "").lower()
        except Exception:
            bypass_host = ""
        if bypass_host and host == bypass_host:
            return False
    return True


def build_fingerprint_headers(
    url: str,
    *,
    fingerprint: BrowserFingerprint,
    purpose: RequestPurpose = "document",
) -> dict[str, str]:
    """根据指纹和用途构建请求头。

    策略：
    - 以指纹 headers 为基础
    - api 用途：移除 Upgrade-Insecure-Requests/Sec-Fetch-User，调整 Accept/Sec-Fetch-*
    - asset/download 用途：同上但 Accept 为 */*
    - amazon.co.jp：强制 Accept-Language 为日语
    """
    headers = dict(fingerprint.headers)

    if purpose == "api":
        for key in ("Upgrade-Insecure-Requests", "Sec-Fetch-User"):
            _pop_case_insensitive(headers, key)
        headers["Accept"] = "application/json,text/plain,*/*"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Site"] = "same-origin"
    elif purpose in ("asset", "download"):
        for key in ("Upgrade-Insecure-Requests", "Sec-Fetch-User"):
            _pop_case_insensitive(headers, key)
        headers["Accept"] = "*/*"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "no-cors"
        headers["Sec-Fetch-Site"] = "same-origin"

    # Amazon.co.jp 自动切换日语
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.endswith("amazon.co.jp"):
        headers["Accept-Language"] = "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    return headers


def build_amazon_headers(
    url: str,
    explicit_headers: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """构建 Amazon.co.jp 专用请求头"""
    headers: dict[str, str] = {
        "accept-language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
        "Host": "www.amazon.co.jp",
    }
    return merge_headers(None, headers, explicit_headers)


def merge_headers(
    fingerprint_headers: Optional[dict[str, str]],
    site_headers: Optional[dict[str, str]],
    explicit_headers: Optional[dict[str, str]],
) -> dict[str, str]:
    """合并多来源请求头，后者优先级高（大小写不敏感）。

    优先级：explicit > site > fingerprint
    """
    result: dict[str, str] = {}
    for source in (fingerprint_headers or {}, site_headers or {}, explicit_headers or {}):
        for key, value in source.items():
            _set_case_insensitive(result, str(key), str(value))
    return result


def clear_host_cache() -> None:
    """清空 host → fingerprint 缓存（用于测试或会话重置）"""
    with _host_cache_lock:
        _host_fingerprint_cache.clear()


def reset_all_state() -> None:
    """清空全部进程内状态（缓存 + 封禁记录），仅测试用。"""
    clear_host_cache()
    clear_blocked()


def get_host_fingerprint(host: str) -> Optional[BrowserFingerprint]:
    """查询当前 host 缓存的指纹（仅用于调试）"""
    with _host_cache_lock:
        return _host_fingerprint_cache.get((host or "").lower())


# ============================================
# 大小写不敏感的 headers 工具函数
# ============================================

def _get_header(headers: Optional[dict[str, str]], key: str) -> str:
    if not headers:
        return ""
    key_lower = key.lower()
    for k, v in headers.items():
        if str(k).lower() == key_lower:
            return str(v)
    return ""


def _has_header(headers: Optional[dict[str, str]], key: str) -> bool:
    return bool(_get_header(headers, key))


def _set_case_insensitive(headers: dict[str, str], key: str, value: str) -> None:
    key_lower = key.lower()
    for existing in list(headers):
        if existing.lower() == key_lower:
            headers.pop(existing, None)
    headers[key] = value


def _pop_case_insensitive(headers: dict[str, str], key: str) -> None:
    key_lower = key.lower()
    for existing in list(headers):
        if existing.lower() == key_lower:
            headers.pop(existing, None)


__all__ = [
    "BrowserFingerprint",
    "RequestPurpose",
    "select_fingerprint",
    "select_amazon_fingerprint",
    "infer_request_purpose",
    "should_apply_fingerprint",
    "build_fingerprint_headers",
    "build_amazon_headers",
    "merge_headers",
    "clear_host_cache",
    "get_host_fingerprint",
    # TLS 指纹轮换（amane #364）
    "should_rotate_fingerprint",
    "has_challenge_markers",
    "mark_fingerprint_blocked",
    "blocked_fingerprint_ids",
    "clear_blocked",
    "reset_all_state",
]
