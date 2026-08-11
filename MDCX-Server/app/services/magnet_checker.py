"""磁力评分 + tracker 存活探测。

两部分（来源均为参考项目移植）：
1. JHS `calcMagnetScore` 五维加权评分：
   - seeders(35)：≥50→35, ≥10→25, ≥1→15, else 3
   - resolution(25)：4k/2160p→25, 1080p→20, 720p→15, else 5
   - subtitle(20)：含 -c/-uc/chinese/中字/字幕 → 20
   - freshness(15)：≤7天→15, ≤30→12, ≤90→8, else 3
   - completeness(-15)：含 sample/预告/trailer → -15
   total = clamp(0,100)

2. Tracker 存活探测（JavDB_magnet_Spider `magnet_checker`）：
   - HTTP/HTTPS tracker：urllib 发 announce → 解析 seeders/leechers
   - UDP tracker：socket 手写 bittorrent 协议（connect + announce）
   - 判定：seeders>0→active, 仅leechers→weak, 都0→dead
"""
from __future__ import annotations

import logging
import random
import re
import socket
import struct
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "magnet_score",
    "MagnetScore",
    "check_magnet_alive",
    "extract_info_hash",
]

# ===========================================================================
# Part 1: JHS 五维磁力评分
# ===========================================================================

_SUBTITLE_RE = re.compile(r"-c\b|-uc\b|chinese|中字|字幕", re.IGNORECASE)
_COMPLETENESS_RE = re.compile(r"sample|预告|trailer", re.IGNORECASE)


@dataclass
class MagnetScore:
    total: int = 0
    seeders: int = 0
    resolution: int = 0
    subtitle: int = 0
    freshness: int = 0
    completeness: int = 0


def _days_since(date_str: str) -> int:
    if not date_str:
        return 999
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return max(0, int((datetime.now() - dt).total_seconds() // 86400))
        except ValueError:
            continue
    return 999


def magnet_score(
    title: str,
    seeders: int = 0,
    date: str = "",
    resolution: str = "",
) -> MagnetScore:
    """JHS 五维磁力评分。

    Args:
        title: 磁力文件名（用于字幕/完整性/分辨率正则）
        seeders: 做种数（可来自 tracker 探测）
        date: 发布日期字符串（用于新鲜度）
        resolution: 显式分辨率（可选，优先级高于 title 正则）
    """
    s = MagnetScore()
    se = int(seeders or 0)
    s.seeders = 35 if se >= 50 else 25 if se >= 10 else 15 if se >= 1 else 3

    a = (title or "").lower()
    res = (resolution or "").lower()
    if res or "4k" in a or "2160p" in a:
        s.resolution = 25
    elif "1080p" in a:
        s.resolution = 20
    elif "720p" in a:
        s.resolution = 15
    else:
        s.resolution = 5

    s.subtitle = 20 if _SUBTITLE_RE.search(a) else 0

    d = _days_since(date)
    s.freshness = 15 if d <= 7 else 12 if d <= 30 else 8 if d <= 90 else 3

    s.completeness = -15 if _COMPLETENESS_RE.search(a) else 0

    s.total = max(0, min(100, s.seeders + s.resolution + s.subtitle + s.freshness + s.completeness))
    return s


# ===========================================================================
# Part 2: Tracker 存活探测
# ===========================================================================

_DEFAULT_TRACKERS = [
    "http://tracker.opentrackr.org:1337/announce",
    "http://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
]

_MAGNET_TIMEOUT_SECONDS = 8.0
_TRACKER_TIMEOUT_SECONDS = 4.0
_TRACKER_CONCURRENCY_LIMIT = 8
_HTTP_USER_AGENT = "mdcx-magnet-checker/1.0"


def extract_info_hash(magnet_link: str) -> str:
    m = re.search(r"urn:btih:([a-zA-Z0-9]{40})", magnet_link or "", re.IGNORECASE)
    if not m:
        raise ValueError(f"无法从磁力链接提取 info_hash: {magnet_link[:60]}")
    return m.group(1).lower()


def _bdecode(data: bytes, pos: int = 0):
    """最小 bencode 解码器（仅需 dict/int/bytes/bytes str 键）。"""
    if pos >= len(data):
        raise ValueError("bencode 越界")
    c = data[pos:pos + 1]
    if c == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1:end]), end + 1
    if c == b"l":
        pos += 1
        items = []
        while data[pos:pos + 1] != b"e":
            v, pos = _bdecode(data, pos)
            items.append(v)
        return items, pos + 1
    if c == b"d":
        pos += 1
        d = {}
        while data[pos:pos + 1] != b"e":
            k, pos = _bdecode(data, pos)
            v, pos = _bdecode(data, pos)
            d[k if isinstance(k, (str, bytes)) else bytes(k)] = v
        return d, pos + 1
    # 数字前缀 + 长度
    end = data.index(b":", pos)
    length = int(data[pos:end])
    return data[end + 1:end + 1 + length], end + 1 + length


def _query_http_tracker(tracker_url: str, info_hash: bytes, peer_id: bytes, timeout: float):
    import urllib.request
    sep = "&" if "?" in tracker_url else "?"
    query = {
        "peer_id": peer_id.decode("latin1"),
        "port": "6881", "uploaded": "0", "downloaded": "0",
        "left": "0", "compact": "1", "event": "started",
    }
    url = (
        f"{tracker_url}{sep}info_hash={urllib.parse.quote_from_bytes(info_hash)}&"
        f"{urllib.parse.urlencode(query, encoding='latin1')}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    data, _ = _bdecode(payload)
    if not isinstance(data, dict):
        raise ValueError("tracker 响应无效")
    complete = data.get(b"complete", 0) or 0
    incomplete = data.get(b"incomplete", 0) or 0
    return int(complete), int(incomplete)


def _query_udp_tracker(tracker_url: str, info_hash: bytes, peer_id: bytes, timeout: float):
    parsed = urllib.parse.urlparse(tracker_url)
    if not parsed.hostname or not parsed.port:
        raise ValueError("UDP tracker 地址无效")
    address = (parsed.hostname, parsed.port)
    tx = random.randint(0, 0xFFFFFFFF)
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(max(0.1, deadline - time.monotonic()))
        sock.sendto(struct.pack(">QII", 0x41727101980, 0, tx), address)
        data, _ = sock.recvfrom(2048)
        if len(data) < 16:
            raise ValueError("UDP tracker 响应无效")
        action, rtx, conn_id = struct.unpack(">IIQ", data[:16])
        if action != 0 or rtx != tx:
            raise ValueError("UDP tracker 握手失败")
        ann_tx = random.randint(0, 0xFFFFFFFF)
        key = random.randint(0, 0xFFFFFFFF)
        packet = struct.pack(
            ">QII20s20sQQQIIIiH",
            conn_id, 1, ann_tx, info_hash, peer_id,
            0, 0, 0, 2, 0, key, -1, 6881,
        )
        sock.settimeout(max(0.1, deadline - time.monotonic()))
        sock.sendto(packet, address)
        data, _ = sock.recvfrom(2048)
    if len(data) < 20:
        raise ValueError("UDP tracker 响应无效")
    action, rtx, _interval, leechers, seeders = struct.unpack(">IIIII", data[:20])
    if action == 3:
        raise ValueError("UDP tracker 返回失败")
    if action != 1 or rtx != ann_tx:
        raise ValueError("UDP tracker announce 失败")
    return seeders, leechers


def _classify(seeders: int, leechers: int) -> str:
    seeders, leechers = int(seeders or 0), int(leechers or 0)
    if seeders > 0:
        return "active"
    if leechers > 0:
        return "weak"
    return "dead"


@dataclass
class MagnetAlive:
    status: str = "dead"   # active / weak / dead / error
    seeders: int = 0
    leechers: int = 0
    trackers_ok: int = 0
    error: str = ""


def check_magnet_alive(
    magnet_link: str,
    trackers: Optional[list[str]] = None,
    timeout: float = _MAGNET_TIMEOUT_SECONDS,
) -> MagnetAlive:
    """探测磁力存活状态。

    并发查询多个 tracker，取 seeders/leechers 最高结果。
    """
    import concurrent.futures

    result = MagnetAlive()
    try:
        info_hash_hex = extract_info_hash(magnet_link)
        info_hash = bytes.fromhex(info_hash_hex)
    except (ValueError, TypeError) as e:
        result.status = "error"
        result.error = str(e)
        return result

    peer_id = b"-MC0001-" + bytes(random.randint(0, 255) for _ in range(12))
    all_trackers = list(dict.fromkeys((trackers or []) + _DEFAULT_TRACKERS))
    deadline = time.monotonic() + timeout

    def query_one(tracker: str):
        t = min(_TRACKER_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic()))
        try:
            parsed = urllib.parse.urlparse(tracker)
            if parsed.scheme.lower() in {"http", "https"}:
                return _query_http_tracker(tracker, info_hash, peer_id, t)
            if parsed.scheme.lower() == "udp":
                return _query_udp_tracker(tracker, info_hash, peer_id, t)
            return (0, 0)
        except Exception as e:
            logger.debug("tracker 查询失败 %s: %s", tracker, e)
            return None

    results = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(_TRACKER_CONCURRENCY_LIMIT, max(1, len(all_trackers)))
    ) as ex:
        futures = [ex.submit(query_one, tr) for tr in all_trackers]
        for f in concurrent.futures.as_completed(futures):
            r = f.result()
            if r is not None:
                results.append(r)
            if time.monotonic() >= deadline:
                break

    if not results:
        result.status = "error"
        result.error = "所有 tracker 查询失败"
        return result

    result.trackers_ok = len(results)
    best_s, best_l = max(results, key=lambda x: (x[0], x[1]))
    result.seeders, result.leechers = int(best_s), int(best_l)
    result.status = _classify(result.seeders, result.leechers)
    return result


if __name__ == "__main__":
    # 自测评分
    s = magnet_score("SDDE-611-UC 1080p 中字", seeders=60, date="2021-05-09")
    print(f"score: total={s.total} seeders={s.seeders} res={s.resolution} sub={s.subtitle} fresh={s.freshness} comp={s.completeness}")
    # 2021 年旧片：seeders35 + res20 + sub20 + fresh3 = 78
    assert s.total == 78, s.total
    # 新鲜片：fresh 升到 15 → 90
    s2 = magnet_score("SDDE-611-UC 1080p 中字", seeders=60, date=datetime.now().strftime("%Y-%m-%d"))
    assert s2.total == 90, s2.total
    # sample 扣分
    s3 = magnet_score("xxx sample", seeders=100, date=datetime.now().strftime("%Y-%m-%d"))
    assert s3.completeness == -15 and s3.total < 85
    print("magnet_score OK")
