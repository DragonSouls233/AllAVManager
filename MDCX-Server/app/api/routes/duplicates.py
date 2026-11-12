"""重复番号扫描 API 路由

GET  /api/v1/duplicates/scan?module=jav&module=chinese  → 实时全盘扫描（慢，约 30-60s）
GET  /api/v1/duplicates/preview?module=jav               → /scan 的别名
GET  /api/v1/duplicates/cached?module=jav&module=chinese → 读缓存（毫秒级，未命中返回 404）
POST /api/v1/duplicates/refresh?module=jav               → 强制重扫并刷新缓存

==================== 缓存说明 ====================
/scan 是同步全盘遍历 media_dirs，媒体库上万文件时每次都要 30~60 秒。
为让「从 MDCX 导入配对」秒开，本路由在**每次扫描成功后按模块落盘缓存**
（DATA_DIR/duplicates_cache/<module>.json），另提供 /cached 纯读接口：
- 命中：毫秒级返回，结构与 /scan 完全一致，额外带 from_cache / cached_at / cache_age_seconds
- 未命中或超过 max_age：返回 404，调用方（subx.mdcx_bridge）自动回退 /scan
- 只要有人在 MDCX 网页点过一次「开始扫描」，缓存即自动生成，无需额外操作
仅在 content=False（默认）时写缓存；content=True 的全量指纹结果不缓存，避免混淆。
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.services.duplicate_scanner import scan_duplicates
from app.utils.logger import get_logger

try:  # 与 compare.py 保持一致的数据目录来源
    from app.config.manager import DATA_DIR
except Exception:  # pragma: no cover - 配置模块不可用时退到项目内 data 目录
    DATA_DIR = Path(__file__).resolve().parents[3] / "data"

logger = get_logger(__name__)

router = APIRouter()

_DUP_CACHE_DIR = Path(DATA_DIR) / "duplicates_cache"
DEFAULT_CACHE_MAX_AGE = 3600  # 秒；超过则视为过期，调用方应重新扫描


def _module_names(module: list[str]) -> list[str]:
    """规范化模块名：去空白、转小写、去重、保持顺序稳定。"""
    seen: list[str] = []
    for m in module or []:
        name = str(m).strip().lower()
        if name and name not in seen:
            seen.append(name)
    return seen


def _cache_path(name: str) -> Path:
    # 模块名来自配置，仍做一次字符白名单，避免路径穿越
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "default"
    return _DUP_CACHE_DIR / f"{safe}.json"


def _write_cache(name: str, result: dict) -> None:
    """原子写入单个模块的扫描结果（临时文件 + replace，避免读到半截 JSON）。"""
    try:
        _DUP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = dict(result)
        out["_cached_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = _cache_path(name)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
        tmp.replace(path)
        logger.info(f"[duplicates_cache] 已写入缓存: {name} -> {path.name}")
    except Exception as exc:  # 缓存失败绝不能影响扫描结果
        logger.warning(f"[duplicates_cache] 写入缓存失败 {name}: {exc}")


def _read_cache(name: str) -> dict | None:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning(f"[duplicates_cache] 读取缓存失败 {path}: {exc}")
        return None


def _cache_age(item: dict, now: datetime) -> float | None:
    """返回缓存年龄（秒）；时间戳缺失/非法返回 None。"""
    stamp = item.get("_cached_at")
    if not stamp:
        return None
    try:
        ts = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (now - ts).total_seconds())
    except ValueError:
        return None


def _public_modules(results: list[dict]) -> list[dict]:
    """去掉内部字段（下划线开头），返回给调用方的干净模块列表。"""
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]


def _merge_results(results: list[dict], from_cache: bool = False) -> dict:
    """把多个模块结果合并成 /scan 的返回结构。"""
    if not results:
        return {
            "total_files": 0,
            "total_groups": 0,
            "duplicate_files": 0,
            "space_wasted_bytes": 0,
            "space_wasted_display": "0 B",
            "modules": [],
        }
    data = {
        "total_files": sum(r["total_files"] for r in results),
        "total_groups": sum(r["total_groups"] for r in results),
        "duplicate_files": sum(r["duplicate_files"] for r in results),
        "space_wasted_bytes": sum(r["space_wasted_bytes"] for r in results),
        "space_wasted_display": _format_size_sum(
            sum(r["space_wasted_bytes"] for r in results)
        ),
        "modules": _public_modules(results),
    }
    if from_cache:
        now = datetime.now(timezone.utc)
        ages = [a for a in (_cache_age(r, now) for r in results) if a is not None]
        stamps = [r.get("_cached_at") for r in results if r.get("_cached_at")]
        data["from_cache"] = True
        data["cached_at"] = min(stamps) if stamps else None
        data["cache_age_seconds"] = round(max(ages), 1) if ages else None
    return data


@router.get("/scan")
async def scan_duplicates_endpoint(
    module: list[str] = Query(
        default=["jav"],
        description="要扫描的模块名列表，可重复传参（如 ?module=jav&module=chinese）",
    ),
    content: bool = Query(
        default=False,
        description="全量 oshash 内容指纹 pass：额外找出文件名/番号不同但内容相同的副本"
        "（改名、错贴番号、分卷误判）。代价是每个视频文件多读约 128KB，大库建议按需开启",
    ),
):
    """扫描指定模块的 media_dirs，找出同番号重复视频文件。

    返回每组重复的：
    - base_code: 基础番号（去除 -C/-UC/-U）
    - files: 每个文件路径、大小、后缀标记、oshash 内容指纹
    - keep_index: 推荐保留的文件索引（优先中字版，其次大体积）
    - wasted_bytes: 可释放的磁盘空间
    - content_match: 组内是否存在字节级相同的副本（oshash 相等）
    - content=1 时附加 content_groups: 跨文件名的内容重复组

    示例请求：
        GET /api/v1/duplicates/scan?module=jav
        GET /api/v1/duplicates/scan?module=jav&module=chinese
        GET /api/v1/duplicates/scan?module=jav&content=1
    """
    # 使用服务注册表，以防模块未初始化
    from app.config.manager import get_config

    config = get_config()
    modules_config = getattr(config, "modules", None)

    all_results = []

    for mod_name in module:
        if not modules_config:
            logger.warning(f"[duplicates_scan] modules config 不可用，跳过 {mod_name}")
            continue

        mod_cfg = getattr(modules_config, mod_name, None)
        if not mod_cfg:
            logger.warning(f"[duplicates_scan] 模块配置不存在: {mod_name}")
            continue

        media_dirs = getattr(mod_cfg, "media_dirs", None) or []
        if not media_dirs:
            logger.info(f"[duplicates_scan] 模块 {mod_name} 未配置 media_dirs，跳过")
            continue

        result = await scan_duplicates(mod_name, media_dirs, content_check=content)
        all_results.append(result)
        # 扫描成功即按模块落盘缓存；content=True 的全量指纹结果不缓存
        if not content:
            _write_cache(str(mod_name).strip().lower(), result)

    return _merge_results(all_results)


@router.get("/cached")
async def cached_duplicates(
    module: list[str] = Query(
        default=["jav"],
        description="要读取缓存的模块名列表，可重复传参（如 ?module=jav&module=chinese）",
    ),
    max_age: int = Query(
        default=DEFAULT_CACHE_MAX_AGE,
        description="缓存最大有效期（秒）；0 表示只要存在就返回，不检查过期",
    ),
):
    """读取扫描结果缓存，毫秒级返回；未命中或已过期返回 404。

    返回结构与 /scan 完全一致，额外附 ``from_cache`` / ``cached_at`` /
    ``cache_age_seconds``，方便调用方判断新鲜度。
    调用方遇到 404 应回退到 /scan（/scan 会顺带刷新缓存）。
    """
    names = _module_names(module)
    if not names:
        raise HTTPException(status_code=400, detail="未指定有效的模块名")

    now = datetime.now(timezone.utc)
    results: list[dict] = []
    for name in names:
        item = _read_cache(name)
        if item is None:
            raise HTTPException(
                status_code=404,
                detail=f"模块 {name} 尚无扫描结果缓存，请调用 /duplicates/scan 或 /duplicates/refresh",
            )
        if max_age > 0:
            age = _cache_age(item, now)
            if age is None or age > max_age:
                raise HTTPException(
                    status_code=404,
                    detail=f"模块 {name} 的扫描结果缓存已过期，请调用 /duplicates/scan 或 /duplicates/refresh",
                )
        results.append(item)

    return _merge_results(results, from_cache=True)


@router.post("/refresh")
async def refresh_duplicates(
    module: list[str] = Query(
        default=["jav"],
        description="要强制重新扫描的模块名列表，可重复传参",
    ),
):
    """强制重新全盘扫描并刷新缓存（慢，约 30-60s）。等价于 /scan 但不带 content pass。"""
    return await scan_duplicates_endpoint(module=module, content=False)


@router.get("/preview")
async def preview_duplicates(
    module: list[str] = Query(
        default=["jav"],
        description="要扫描的模块名",
    ),
    content: bool = Query(
        default=False,
        description="全量 oshash 内容指纹 pass（同 /scan 的 content 参数）",
    ),
):
    """preview 别名，与 /scan 行为一致"""
    return await scan_duplicates_endpoint(module=module, content=content)


def _format_size_sum(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / 1024:.0f} KB"
