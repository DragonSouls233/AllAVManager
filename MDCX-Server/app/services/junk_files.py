"""垃圾文件检测服务（样本片 / 预告片 / 广告推广 / 系统垃圾）

扫描配置的媒体目录，按文件名特征识别「非正片」文件：
- sample：含 sample 字样的样本切片（常见下载站附带的试看片段）
- trailer：预告片 / 宣传短片
- ad：广告 / 推广残留（含广告、promo、advert、宣传等字样）
- system：系统自动生成的垃圾（thumbs.db / .ds_store / desktop.ini）

只读扫描，返回按原因分组的清单；删除动作复用 ad_residue 的回收站机制（可恢复）。
"""

import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)

# 最大扫描文件数 / 最大返回条数，防止超大目录导致请求超时
_MAX_FILES = 500_000
_MAX_RESULTS = 3000
_MAX_DEPTH = 5

# 原因 → 正则（小写文件名匹配）
_REASON_PATTERNS = {
    "sample": re.compile(r"(?:^|[\s_\-\(])sample(?:[\s_\-\)]|$)", re.I),
    "trailer": re.compile(r"trailer|预告|teaser|预览片", re.I),
    "ad": re.compile(r"(?:^|[\s_\-])ad[\s_\-]|promo|advert|广告|宣传|推广", re.I),
}


def _classify(name: str) -> str | None:
    low = name.lower()
    # 系统垃圾文件优先判定（精确文件名）
    if low in ("thumbs.db", ".ds_store", "desktop.ini"):
        return "system"
    for reason, pat in _REASON_PATTERNS.items():
        if pat.search(low):
            return reason
    return None


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _scan_sync(directories, max_files=_MAX_FILES, max_results=_MAX_RESULTS, max_depth=_MAX_DEPTH):
    results = {"sample": [], "trailer": [], "ad": [], "system": []}
    scanned = 0
    limited = False

    for root in directories:
        if limited:
            break
        if not os.path.isdir(root):
            continue
        stack = [(root, 0)]
        while stack and not limited:
            cur, depth = stack.pop()
            try:
                entries = list(os.scandir(cur))
            except (OSError, PermissionError):
                continue
            for e in entries:
                if scanned >= max_files:
                    limited = True
                    break
                scanned += 1
                if e.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        stack.append((e.path, depth + 1))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                reason = _classify(e.name)
                if not reason:
                    continue
                try:
                    size = e.stat().st_size
                except OSError:
                    size = 0
                bucket = results[reason]
                if len(bucket) < max_results:
                    # 仅保留最小必要字段，控制响应体积
                    bucket.append({"path": e.path, "size": size})
                total = sum(len(v) for v in results.values())
                if total >= max_results:
                    limited = True
                    break

    by_reason = {}
    total = 0
    total_size = 0
    for reason, items in results.items():
        if items:
            by_reason[reason] = {
                "count": len(items),
                "total_size": sum(i["size"] for i in items),
                "items": items,
            }
            total += len(items)
            total_size += by_reason[reason]["total_size"]
    return {
        "total": total,
        "total_size": total_size,
        "total_size_human": _human_size(total_size),
        "limited": limited,
        "scanned": scanned,
        "by_reason": by_reason,
    }


async def scan(directories=None, cfg=None):
    """扫描媒体目录产出垃圾文件候选（只读）。

    directories 为 None 时自动取配置中的 media_dirs 并过滤可达项。
    """
    if not directories:
        from app.utils.media_helpers import collect_media_dirs, filter_reachable
        if cfg is None:
            try:
                from app.config.manager import get_config
                cfg = get_config()
            except Exception:
                cfg = None
        dirs = collect_media_dirs(cfg) if cfg else []
        directories = filter_reachable(dirs)
    return await asyncio.to_thread(_scan_sync, directories)
