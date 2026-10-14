"""
跨机路径对照表（openaver 0.17.7 移植）。

背景
----
片库常放在另一台机器 / NAS 上。当 MDCX 客户端连到「主机」时，主机 DB 里存的是
主机侧路径（如 ``/volume1/av/ABC-123/ABC-123.mp4``），而客户端本机挂载的是
``\\\\NAS\\av\\...``。直接拿主机路径去播放 / 开文件夹会失败。

openaver 的做法是维护一张「路径对照表」：

    /volume1/av  ↔  \\\\NAS\\av
    E:\\mdcx     ↔  /mnt/mdcx

凡是「读出来要给用户用的路径」（播放、开文件夹、拖放），都先过一遍本模块，
把远端前缀换成客户端本机前缀；写回时再换回来（本模块只提供双向映射函数）。

配置档：``<DATA_DIR>/config/path_map.json``
    {"enabled": true, "rules": [{"remote": "/volume1/av", "local": "\\\\NAS\\av", "enabled": true}]}

匹配规则（区分大小写不敏感）：
- 按「最长前缀」匹配，避免 ``/volume1`` 误伤 ``/volume1/av``。
- remote / local 互为镜像：map_to_local 用 remote→local，map_to_remote 反过来。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Optional[dict[str, Any]] = None
_cache_ts: float = 0.0
_cache_mtime: float = -1.0
_TTL = 5.0


def _data_dir() -> Path:
    from app.config.manager import DATA_DIR

    return Path(DATA_DIR)


def config_path() -> Path:
    return _data_dir() / "config" / "path_map.json"


def _read_unlocked() -> dict[str, Any]:
    global _cache, _cache_ts, _cache_mtime
    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    now = time.time()
    if _cache is not None and mtime == _cache_mtime and (now - _cache_ts) < _TTL:
        return _cache
    data: dict[str, Any] = {}
    if mtime >= 0:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except Exception as e:  # noqa: BLE001
            logger.warning("path_map.json 解析失败，忽略: %s", e)
            data = {}
    _cache = data
    _cache_ts = now
    _cache_mtime = mtime
    return data


def load_config() -> dict[str, Any]:
    with _lock:
        return dict(_read_unlocked())


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    global _cache, _cache_ts, _cache_mtime
    if not isinstance(data, dict):
        raise ValueError("配置必须是对象")
    rules = data.get("rules")
    if rules is None:
        rules = []
    if not isinstance(rules, list):
        raise ValueError("rules 必须是数组")

    clean_rules = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        remote = (item.get("remote") or "").strip()
        local = (item.get("local") or "").strip()
        if not remote or not local:
            continue
        clean_rules.append({
            "remote": remote,
            "local": local,
            "enabled": bool(item.get("enabled", True)),
        })

    payload = {"enabled": bool(data.get("enabled", True)), "rules": clean_rules}
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    with _lock:
        _cache = None
        _cache_ts = 0.0
        _cache_mtime = -1.0
    return payload


def _prefix_match(path: str, prefix: str) -> Optional[str]:
    """path 是否以 prefix 开头（大小写不敏感）。

    返回「去掉前缀后剩余的后缀」（含前导分隔符），不匹配返回 None。
    要求 prefix 之后是路径分隔符或字符串结束，避免 ``/volume1`` 误中 ``/volume1x``。
    """
    if not path or not prefix:
        return None
    lp, lpfx = len(path), len(prefix)
    # 逐字符大小写不敏感比较
    if lp < lpfx:
        return None
    if path[:lpfx].lower() != prefix.lower():
        return None
    if lpfx == lp:
        return ""  # 完全相等
    ch = path[lpfx]
    if ch in ("/", "\\"):
        return path[lpfx:]  # 含前导分隔符
    return None


def _apply(path: str, rules: list[dict], from_key: str, to_key: str) -> Optional[str]:
    """按最长前缀把 path 的 from_key 前缀替换成 to_key。无匹配返回 None。"""
    if not path:
        return None
    best_len = -1
    best_repl: Optional[str] = None
    best_suffix: Optional[str] = None
    for r in rules:
        if not r.get("enabled", True):
            continue
        suffix = _prefix_match(path, r[from_key])
        if suffix is None:
            continue
        if len(r[from_key]) > best_len:
            best_len = len(r[from_key])
            best_repl = r[to_key]
            best_suffix = suffix
    if best_repl is None:
        return None
    result = best_repl + best_suffix
    # 后缀分隔符跟随目标前缀风格（Linux / ↔ Windows \），避免 /volume1/av/x
    # 映射到 \\NAS\av 后残留 / 造成混排
    if "\\" in best_repl and "/" in result:
        result = result.replace("/", "\\")
    elif "/" in best_repl and "\\" in result:
        result = result.replace("\\", "/")
    return result


def map_to_local(path: str) -> str:
    """把远端路径映射为本机路径；无匹配原样返回。"""
    with _lock:
        cfg = _read_unlocked()
    if not cfg.get("enabled", True):
        return path
    rules = cfg.get("rules") or []
    mapped = _apply(path, rules, "remote", "local")
    return mapped if mapped is not None else path


def map_to_remote(path: str) -> str:
    """把本机路径映射回远端路径；无匹配原样返回。"""
    with _lock:
        cfg = _read_unlocked()
    if not cfg.get("enabled", True):
        return path
    rules = cfg.get("rules") or []
    mapped = _apply(path, rules, "local", "remote")
    return mapped if mapped is not None else path


def describe() -> dict[str, Any]:
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "rules": cfg.get("rules") or [],
    }


__all__ = [
    "load_config",
    "save_config",
    "map_to_local",
    "map_to_remote",
    "describe",
    "config_path",
]
