"""JavDB App API 自动选线模块 — 移植自 javdb-cli v0.7.2（route 包）。

来源：github.com/FlanChanXwO/javdb-cli v0.7.2
  internal/javdb/appapi/endpoint/route/decrypt.go   ← backup_domains_data AES-CBC 解密
  internal/javdb/appapi/endpoint/route/selector.go  ← 并发 /startup 测速选线

功能：
  1. GET /api/v1/startup 探测（带 jdsignature + public 参数），响应含加密的
     backup_domains_data（内含官方动态 API 域名候选 apiDomains）。
  2. 复刻 APK 1.9.28 common_tools.dart 的解密链路：
       key/iv = getDecryptString(input, 常量)    // md5 -> 逐字节相减 -> base64
       明文    = base64 -> AES-CBC(key, iv) -> PKCS7 unpad -> UTF-8 JSON object
  3. 并发测速：验证 preferred 线路（上次缓存）→ 并发探测固定 bootstrap →
     并发探测动态候选 → 选单次 /startup 耗时最短者（tie-break：动态响应顺序
     优先，其次固定 bootstrap 顺序）。

用法（在 javdb_app_client 内延迟调用）：
    from app.services.javdb_autohost import select_auto_host
    result = await select_auto_host(preferred=上次缓存host, proxy=proxy)
    host, latency = result.host, result.latency  # 用 host 构造客户端
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

# 复用 javdb_app_client 的签名与常量（该模块顶层无副作用，不构成循环依赖；
# app_client 只在方法内延迟导入本模块）。
from app.services.javdb_app_client import (
    _APP_VERSION,
    _APP_VERSION_NUMBER,
    _BASE_URL,
    _LANG,
    _USER_AGENT,
    make_signature,
)

log = logging.getLogger(__name__)

# --- 固定 bootstrap 入口（顺序即 tie-break 的固定顺序，与 selector.go 一致）----
BOOTSTRAP_HOSTS = [
    _BASE_URL,                          # https://jdforrepam.com（App 镜像，主推）
    "https://apidd.spthgb.com",
    "https://apidd.czssdgz.com",
    "https://javdb.com",                # 主站
]

# --- APK 1.9.28 派生 backup_domains_data 的 AES key/IV 常量（decrypt.go）--------
_BACKUP_KEY_INPUT = "30820"
_BACKUP_IV_INPUT = "astarte"
_BACKUP_KEY_CONST = (
    "WzE5OSwxNjksMTYwLDE3NCwxOTksMTA2LDEyNCwxNzQsMTM4LDE3MywxNjIsMTQ5LDE5MCwx"
    "NzksMTU3LDIwNiwxMjgsMjA5LDEyNSwxNzIsMTI4LDE4MiwxNjIsMTYxXQ=="
)
_BACKUP_IV_CONST = (
    "WzE1MSwxNDMsMTI3LDEwMywxOTksMTQwLDIwMCwxNjksMTU3LDE2MiwxNjUsMTAxLDE5OCwx"
    "NjMsMTc0LDE1NywyMDMsMTI1LDE1NiwxNjksMTQxLDIyMCwxMTEsMTYyXQ=="
)

_AES_BLOCK_SIZE = 16


@dataclass
class AutoHostResult:
    """自动选线结果。Latency 为单次 /startup 耗时（秒）。"""
    host: str
    latency: float
    reused_preferred: bool


# --- 解密链路 ------------------------------------------------------------------

def get_decrypt_string(input_str: str, encoded: str) -> str:
    """复刻 common_tools.dart 字符串还原算法。

    key_hex = md5(input).hexdigest()（32 个小写 hex 字符）
    plain   = json(base64decode(encoded))（整数数组）
    chars[i]= (plain[i] - ord(key_hex[min(i, 31)])) & 0xff
    result  = base64decode(chars)
    """
    key_hex = hashlib.md5(input_str.encode("utf-8")).hexdigest()
    raw = base64.b64decode(encoded)
    plain = json.loads(raw.decode("utf-8"))
    chars = bytes(
        (int(p) - ord(key_hex[min(i, 31)])) & 0xFF for i, p in enumerate(plain)
    )
    return base64.b64decode(chars).decode("utf-8")


def _derive_key_iv() -> tuple[bytes, bytes]:
    return get_decrypt_string(_BACKUP_KEY_INPUT, _BACKUP_KEY_CONST).encode(
        "utf-8"
    ), get_decrypt_string(_BACKUP_IV_INPUT, _BACKUP_IV_CONST).encode("utf-8")


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data or len(data) % _AES_BLOCK_SIZE != 0:
        raise ValueError(f"padded length {len(data)}")
    pad = data[-1]
    if pad == 0 or pad > _AES_BLOCK_SIZE or pad > len(data):
        raise ValueError(f"padding length {pad}")
    if data[-pad:] != bytes([pad]) * pad:
        raise ValueError("padding bytes do not match length")
    return data[:-pad]


def decrypt_backup_domains_data(encoded: str) -> dict[str, Any]:
    """解密 startup 响应的 backup_domains_data，返回 JSON payload dict。

    链路：base64 -> AES-CBC -> PKCS7 unpad -> UTF-8 JSON object。
    密钥/IV 由 getDecryptString 一次性派生（复刻 APK 1.9.28）。
    """
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    encrypted = base64.b64decode(encoded)
    if not encrypted or len(encrypted) % _AES_BLOCK_SIZE != 0:
        raise ValueError(f"cipher length {len(encrypted)} not multiple of 16")
    key, iv = _derive_key_iv()
    if len(iv) != _AES_BLOCK_SIZE:
        raise ValueError(f"iv length {len(iv)} not multiple of 16")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    plain = cipher.decryptor().update(encrypted) + cipher.decryptor().finalize()
    plain = _pkcs7_unpad(plain)
    payload = json.loads(plain.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("decrypted payload is not a JSON object")
    return payload


def _normalize_candidate(value: str) -> str:
    """校验并规范化 apiDomains 条目：去空白与尾随 /，必须 http/https 且带 host。"""
    candidate = value.strip().rstrip("/")
    if "://" not in candidate:
        raise ValueError(f"invalid url: {value!r}")
    scheme, _, rest = candidate.partition("://")
    if scheme.lower() not in ("http", "https") or not rest:
        raise ValueError(f"invalid url: {value!r}")
    if "?" in candidate or "#" in candidate:
        raise ValueError(f"query/fragment not allowed: {value!r}")
    return candidate


def api_hosts_from_startup_data(startup: dict[str, Any]) -> list[str]:
    """从 /startup 的 data 提取规范化、去重后的 apiDomains 候选。

    backup_domains_data 缺失或解密失败返回空列表（不抛错），调用方可回退到
    已验证 bootstrap；字段类型非法时抛 ValueError。
    """
    encoded = startup.get("backup_domains_data")
    if not isinstance(encoded, str):
        return []
    try:
        payload = decrypt_backup_domains_data(encoded)
    except Exception as e:  # noqa: BLE001
        log.debug("backup_domains_data 解密失败: %s", e)
        return []
    raw_domains = payload.get("apiDomains")
    if not isinstance(raw_domains, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_domains:
        if not isinstance(item, str):
            continue
        try:
            candidate = _normalize_candidate(item)
        except ValueError:
            continue
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


# --- startup 探测 ----------------------------------------------------------------

def _public_params(device_uuid: str) -> dict[str, str]:
    """与 javdb_app_client._public_params 保持一致（startup 探测也需全套参数）。"""
    return {
        "app_channel": "official",
        "app_version": _APP_VERSION,
        "app_version_number": _APP_VERSION_NUMBER,
        "platform": "android",
        "system_version": "13",
        "device_model": "Pixel 6",
        "device_name": "Pixel",
        "device_uuid": device_uuid,
    }


async def probe_startup(
    host: str,
    proxy: Optional[str] = None,
    device_uuid: Optional[str] = None,
    timeout: float = 8.0,
    lang: str = _LANG,
) -> tuple[float, dict[str, Any]]:
    """对单个 host 发起一次 /api/v1/startup 请求，返回 (耗时秒, data dict)。

    带完整 public 参数 + jdsignature（同普通 API 请求），单次探测无重试。
    失败抛异常（由调用方收集为失败原因）。
    """
    base = host.rstrip("/")
    uuid_val = device_uuid or str(uuid.uuid4())
    ts = int(time.time())
    url = f"{base}/api/v1/startup?" + urlencode(_public_params(uuid_val))
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "accept-language": lang,
        "jdsignature": make_signature(ts),
    }
    async with httpx.AsyncClient(
        timeout=timeout,
        proxy=proxy,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        start = time.monotonic()
        r = await client.get(url, headers=headers)
        latency = time.monotonic() - start
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    env = r.json()
    if not env.get("success"):
        raise RuntimeError(f"biz error: {env.get('action')} / {env.get('message') or ''}")
    data = env.get("data")
    return latency, data if isinstance(data, dict) else {}


# --- 选线主逻辑 ----------------------------------------------------------------

async def select_auto_host(
    preferred: Optional[str] = None,
    proxy: Optional[str] = None,
    timeout: float = 8.0,
    device_uuid: Optional[str] = None,
    lang: str = _LANG,
) -> AutoHostResult:
    """并发动态线路选择（移植 selector.go，简化取消逻辑）。

    顺序：
      1. preferred 严格校验并单次探测，成功立即复用；
      2. 并发探测固定 bootstrap，首个解出非空 apiDomains 的响应成为动态候选来源；
      3. 并发探测尚未探测过的动态候选；
      4. 全部成功候选中选单次耗时最短者；相同耗时按动态响应顺序、再按固定
         bootstrap 顺序稳定决胜。
    全部失败抛 RuntimeError（含逐 host 原因）。
    """
    uuid_val = device_uuid or str(uuid.uuid4())
    failures: list[str] = []

    if preferred:
        try:
            normalized = _normalize_candidate(preferred)
        except ValueError as e:
            failures.append(f"preferred host: {e}")
        else:
            try:
                latency, _ = await probe_startup(
                    normalized, proxy, uuid_val, timeout, lang
                )
                return AutoHostResult(normalized, latency, reused_preferred=True)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{normalized}: {e}")

    # 并发探测固定 bootstrap
    boot_results: list[tuple[str, float]] = []
    dynamic_data: Optional[dict[str, Any]] = None
    gathered = await asyncio.gather(
        *[probe_startup(h, proxy, uuid_val, timeout, lang) for h in BOOTSTRAP_HOSTS],
        return_exceptions=True,
    )
    for host, result in zip(BOOTSTRAP_HOSTS, gathered):
        if isinstance(result, BaseException):
            failures.append(f"{host}: {result}")
            continue
        latency, data = result
        boot_results.append((host, latency))
        if dynamic_data is None:
            domains = api_hosts_from_startup_data(data)
            if domains:
                dynamic_data = data

    # 动态候选（完整读取、去重）；已探测的 URL 复用结果
    dynamic_hosts: list[str] = []
    if dynamic_data is not None:
        dynamic_hosts = api_hosts_from_startup_data(dynamic_data)
    probed = {host for host, _ in boot_results}
    todo = [h for h in dynamic_hosts if h not in probed]

    dyn_results: list[tuple[str, float]] = []
    if todo:
        gathered2 = await asyncio.gather(
            *[probe_startup(h, proxy, uuid_val, timeout, lang) for h in todo],
            return_exceptions=True,
        )
        for host, result in zip(todo, gathered2):
            if isinstance(result, BaseException):
                failures.append(f"{host}: {result}")
            else:
                dyn_results.append((host, result[0]))

    # 排序：耗时最短；tie-break 动态响应顺序优先，其次固定 bootstrap 顺序
    dynamic_order = {h: i for i, h in enumerate(dynamic_hosts)}
    bootstrap_order = {h: i for i, h in enumerate(BOOTSTRAP_HOSTS)}

    def rank_key(item: tuple[str, float]) -> tuple[float, int, int]:
        host, latency = item
        dyn_idx = dynamic_order.get(host, -1)
        boot_idx = bootstrap_order.get(host, -1)
        is_dyn = dyn_idx >= 0
        return (latency, 0 if is_dyn else 1, dyn_idx if is_dyn else boot_idx)

    ranked = dyn_results + boot_results
    if not ranked:
        raise RuntimeError(f"route selection failed: {'; '.join(failures)}")
    ranked.sort(key=rank_key)
    winner = ranked[0]
    return AutoHostResult(winner[0], winner[1], reused_preferred=False)


__all__ = [
    "AutoHostResult",
    "BOOTSTRAP_HOSTS",
    "api_hosts_from_startup_data",
    "decrypt_backup_domains_data",
    "get_decrypt_string",
    "probe_startup",
    "select_auto_host",
]
