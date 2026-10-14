"""
按站点覆盖代理（amane #365 移植）。

背景
----
全项目代理只有一个出口 ``get_effective_proxy_url()``（内置 xray → config.proxy → None），
这对「全局代理」是对的，但扛不住两类真实需求：

1. **某站必须直连**：站点封代理出口 IP（或国内可直连），走代理反而 100% 失败，
   而为了它把全局代理关掉又会拖垮其它站。
2. **某站必须走另一条出口**：日本地域站（DMM/FANZA）要走日本节点，其余站走默认出口。

实现方式
--------
在**唯一定义源之上加一层覆盖**，而不是另开一个代理口径：

    get_effective_proxy_url(site=..., url=...)
        └─ 命中覆盖 → 返回覆盖值（"direct" → None）
        └─ 未命中   → 原逻辑（内置 xray → config.proxy → None）

这样既满足单点定义（未配置的站点行为完全不变），又能按站点例外。

配置档：``<DATA_DIR>/config/site_proxy.json``
    {
      "enabled": true,
      "sites": {
        "javdb":    "socks5://127.0.0.1:10808",   # 按爬虫名
        "javbus.com": "direct",                    # 按域名（精确或后缀匹配）
        "dmm_web":  "http://127.0.0.1:18920"
      }
    }

键的匹配顺序（最长匹配优先，避免 javdb 误伤 javdb_new）：
    1. 爬虫名（``BaseCrawler.name``，小写精确）
    2. 域名精确
    3. 域名后缀（host 以 "." + key 结尾）
值：``direct`` / ``none`` / ``off`` / 空串 / false → 直连（None）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# 表示「这个站不要走代理」的取值
_DIRECT_TOKENS = {"", "direct", "none", "off", "false", "disable", "disabled", "no"}

_CACHE_TTL = 5.0  # 配置热更新：最多 5 秒滞后，避免每次请求都读盘

_lock = threading.Lock()
_cache: Optional[dict[str, Any]] = None
_cache_ts: float = 0.0
_cache_mtime: float = -1.0


def _data_dir() -> Path:
    from app.config.manager import DATA_DIR  # 延迟导入，避免循环依赖

    return Path(DATA_DIR)


def config_path() -> Path:
    return _data_dir() / "config" / "site_proxy.json"


def _read_unlocked() -> dict[str, Any]:
    """读配置（调用方持锁）。带 mtime + TTL 双重缓存，文件改了立刻生效。"""
    global _cache, _cache_ts, _cache_mtime

    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0

    now = time.time()
    if (
        _cache is not None
        and mtime == _cache_mtime
        and (now - _cache_ts) < _CACHE_TTL
    ):
        return _cache

    data: dict[str, Any] = {}
    if mtime >= 0:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except Exception as e:  # noqa: BLE001
            logger.warning("site_proxy.json 解析失败，本次忽略覆盖: %s", e)
            data = {}

    _cache = data
    _cache_ts = now
    _cache_mtime = mtime
    return data


def load_config() -> dict[str, Any]:
    """返回原始配置（含 enabled / sites），供 API 展示。"""
    with _lock:
        return dict(_read_unlocked())


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    """写入配置。做最小校验：结构必须是 dict，sites 的值必须是字符串或布尔。"""
    global _cache, _cache_ts, _cache_mtime

    if not isinstance(data, dict):
        raise ValueError("配置必须是对象")
    sites = data.get("sites")
    if sites is None:
        sites = {}
    if not isinstance(sites, dict):
        raise ValueError("sites 必须是对象")

    clean: dict[str, str] = {}
    for key, value in sites.items():
        if value is None:
            continue
        if isinstance(value, bool):
            # True → 继承全局；False → 直连
            if not value:
                clean[str(key).strip().lower()] = "direct"
            continue
        text = str(value).strip()
        if not text:
            continue
        clean[str(key).strip().lower()] = text

    payload = {
        "enabled": bool(data.get("enabled", True)),
        "sites": clean,
    }

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)

    with _lock:
        _cache = None
        _cache_ts = 0.0
        _cache_mtime = -1.0
    return payload


def _normalize_host(url_or_host: str) -> str:
    value = (url_or_host or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        try:
            return (urlsplit(value).hostname or "").lower()
        except Exception:  # noqa: BLE001
            return ""
    # 可能是 "host:port" 或纯 host
    return value.split(":")[0].strip().rstrip("/") or ""


def _normalize(raw: str) -> Optional[str]:
    """把配置值规范化成 '代理URL' 或 None（直连）。"""
    text = (raw or "").strip()
    if text.lower() in _DIRECT_TOKENS:
        return None
    if "://" not in text:
        text = "http://" + text
    return text or None


def resolve(site: str = "", url: str = "") -> Optional[tuple[bool, Optional[str]]]:
    """查站点覆盖。

    Returns:
        None            —— 没有覆盖，调用方应走原逻辑
        (True, url|None)—— 有覆盖；url=None 表示强制直连
    """
    with _lock:
        cfg = _read_unlocked()

    if not cfg.get("enabled", True):
        return None

    sites = cfg.get("sites") or {}
    if not isinstance(sites, dict) or not sites:
        return None

    site_key = (site or "").strip().lower()
    host = _normalize_host(url)

    # 1) 爬虫名精确匹配（最高优先级：用户写爬虫名就是要指名道姓）
    if site_key and site_key in sites:
        return True, _normalize(sites[site_key])

    if not host:
        return None

    # 2) 域名精确 / 3) 域名后缀 —— 取最长匹配，避免 javdb 覆盖到 javdb_new
    best_key = ""
    best_value: Optional[str] = None
    for key, value in sites.items():
        k = str(key).strip().lower()
        if not k or "://" in k or "/" in k:
            continue  # 域名键不该带 scheme/path；带了的当爬虫名处理
        if host == k:
            if len(k) > len(best_key):
                best_key, best_value = k, value
        elif host.endswith("." + k):
            if len(k) > len(best_key):
                best_key, best_value = k, value

    if best_key:
        return True, _normalize(best_value or "")
    return None


def describe() -> dict[str, Any]:
    """给 API 用的视图：原始配置 + 解析后的条目。"""
    cfg = load_config()
    sites = cfg.get("sites") or {}
    items = []
    for key, value in sorted(sites.items()):
        normalized = _normalize(str(value))
        items.append(
            {
                "key": key,
                "value": str(value),
                "mode": "direct" if normalized is None else "proxy",
                "proxy_url": normalized,
            }
        )
    return {"enabled": bool(cfg.get("enabled", True)), "items": items}
