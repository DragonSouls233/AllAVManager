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
from dataclasses import dataclass
from typing import Literal, Optional
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
    use_cache: bool = True,
) -> BrowserFingerprint:
    """按 host 和用途选择浏览器指纹。

    策略：
    - amazon.co.jp 走专用池（其实同默认池，但 build_headers 会切换语言）
    - api 用途使用较新 Chrome 指纹池
    - asset/download 用途使用默认池
    - use_cache=True 时，同一 host 在同一进程内复用同一指纹（减少漂移）

    Args:
        host: 目标主机名（域名）
        purpose: 请求用途
        exclude_fingerprint_id: 需排除的指纹 ID（避免连续重复）
        use_cache: 是否使用 host 缓存

    Returns:
        BrowserFingerprint 实例
    """
    normalized_host = (host or "").lower()

    # 缓存命中（仅当不排除时）
    if use_cache and normalized_host and not exclude_fingerprint_id:
        with _host_cache_lock:
            cached = _host_fingerprint_cache.get(normalized_host)
            if cached is not None:
                return cached

    # 按用途/主机选择候选池
    if normalized_host.endswith("amazon.co.jp"):
        chosen = _choose_fingerprint(_AMAZON_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)
    elif purpose == "api":
        chosen = _choose_fingerprint(_API_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)
    elif purpose in ("asset", "download"):
        chosen = _choose_fingerprint(_ASSET_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)
    else:
        chosen = _choose_fingerprint(_DEFAULT_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)

    # 写入缓存
    if use_cache and normalized_host and not exclude_fingerprint_id:
        with _host_cache_lock:
            _host_fingerprint_cache[normalized_host] = chosen

    return chosen


def select_amazon_fingerprint(*, exclude_fingerprint_id: str = "") -> BrowserFingerprint:
    """选择 Amazon.co.jp 专用指纹"""
    return _choose_fingerprint(_AMAZON_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)


def _choose_fingerprint(
    fingerprints: tuple[BrowserFingerprint, ...],
    *,
    exclude_fingerprint_id: str = "",
) -> BrowserFingerprint:
    """从候选池中随机选择一个指纹，支持排除指定 ID"""
    if exclude_fingerprint_id:
        candidates = [f for f in fingerprints if f.fingerprint_id != exclude_fingerprint_id]
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
]
