"""
健康检查路由

端点：
- GET /api/v1/health       — 存活检查
- GET /api/v1/health/ready — 就绪检查
- GET /api/v1/health/live  — 存活检查（别名）
- GET /api/v1/health/metrics — Prometheus 格式指标（供 ServiceMonitor 抓取）
- GET /api/v1/version      — 版本/补丁信息
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config.manager import get_config, PROJECT_ROOT

router = APIRouter()

_VERSION_CACHE: dict | None = None
_ENGINE_LOCK_CACHE: dict | None = None


def _load_version() -> dict:
    """读取 VERSION.json（带缓存，避免每次请求都读文件）"""
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE
    vpath = PROJECT_ROOT / "VERSION.json"
    try:
        _VERSION_CACHE = json.loads(vpath.read_text(encoding="utf-8"))
    except Exception:
        _VERSION_CACHE = {"version": "unknown", "patch_level": "unknown"}
    return _VERSION_CACHE


def _load_engine_locks() -> list[dict]:
    """读取 engine-lock.json（移植来源版本锁定清单，带缓存）。

    概念源自 ref44-AVDC-Next：repo+tag+commit 三元组锁定上游引擎版本，
    供审计与升级决策。文件缺失时返回空列表，不影响服务。
    """
    global _ENGINE_LOCK_CACHE
    if _ENGINE_LOCK_CACHE is not None:
        return _ENGINE_LOCK_CACHE
    lpath = PROJECT_ROOT / "engine-lock.json"
    try:
        data = json.loads(lpath.read_text(encoding="utf-8"))
        engines = data.get("engines", []) if isinstance(data, dict) else []
        _ENGINE_LOCK_CACHE = engines if isinstance(engines, list) else []
    except Exception:
        _ENGINE_LOCK_CACHE = []
    return _ENGINE_LOCK_CACHE


@router.get("/version")
async def version_info():
    """返回当前版本、已应用补丁列表及移植来源锁定清单"""
    version = _load_version()
    version["engine_locks"] = _load_engine_locks()
    return version


@router.get("")
async def health_check():
    """健康检查"""
    config = get_config()
    return {
        "status": "ok",
        "app_name": config.app_name,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/ready")
async def readiness_check():
    """就绪检查"""
    from app.db.database import get_database

    try:
        db = get_database()
        # 简单查询测试数据库连接
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}


@router.get("/live")
async def liveness_check():
    """存活检查"""
    return {"status": "alive"}


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标端点（exposition format，供 Prometheus / ServiceMonitor 抓取）"""
    from app.services.metrics import generate_metrics_text, get_content_type, collect_db_metrics

    # 刷新数据库指标（异步采集）
    await collect_db_metrics()

    text = generate_metrics_text()
    return Response(content=text, media_type=get_content_type())


@router.get("/sources")
async def source_status():
    """P2-1 · 源能力矩阵 + 实时熔断状态（轻量，无 DB 查询）。

    与 ``/api/v1/crawlers/health`` 的区别：
    - ``/crawlers/health`` 是**历史**视角（查 ``scrape_attempts`` 算成功率，重）；
    - 本端点是**即时**视角（注册表 + 熔断内存态 + 能力声明，轻），可高频轮询。

    每个源返回：启用状态、能力矩阵（movie/performer/gallery/...）、
    在源序里的层级（primary/aux/jp/other）、当前熔断状态（开/剩余秒/连续次数/原因）。

    这是 P2-1「源能力矩阵 + 每源熔断状态」的对外落地：运维一眼看清
    「哪些源在线、各能补什么、现在哪些被熔断跳过」。
    """
    import time

    from app.crawlers.provider import get_provider
    from app.scraper.breaker import get_breaker
    from app.scraper.canon import (
        AMATEUR_SOURCE_ORDER,
        AUX_SOURCE_ORDER,
        JP_SOURCE_ORDER,
        MAINSTREAM_SOURCE_ORDER,
    )
    from app.scraper.source_capabilities import (
        SourceCapability,
        capabilities_for_source,
    )

    provider = get_provider()
    breaker = get_breaker()
    now = time.monotonic()

    primary_set = set(MAINSTREAM_SOURCE_ORDER) | set(AMATEUR_SOURCE_ORDER)
    aux_set = set(AUX_SOURCE_ORDER)
    jp_set = set(JP_SOURCE_ORDER)

    sources = []
    for name, crawler in provider.get_all().items():
        # 层级：primary（主力）/ aux（辅助）/ jp（日本官方）/ other（不在 canon 序里）
        if name in jp_set:
            tier = "jp"
        elif name in aux_set:
            tier = "aux"
        elif name in primary_set:
            tier = "primary"
        else:
            tier = "other"

        enabled = crawler.status.value == "enabled"
        caps = capabilities_for_source(name)

        # 熔断内存态（不查库，纯即时）
        st = breaker.get_state(name)
        open_now = bool(st.open_until) and now < st.open_until
        remaining = round(st.open_until - now, 1) if open_now else 0.0

        sources.append({
            "name": name,
            "display_name": getattr(crawler, "display_name", name),
            "status": crawler.status.value,
            "enabled": enabled,
            "tier": tier,
            "in_source_order": tier != "other",
            "capabilities": sorted(c.value for c in caps),
            "breaker": {
                "open": open_now,
                "remaining_seconds": remaining,
                "strike": st.strike,
                "half_open": st.half_open,
                "last_reason": st.last_reason or "",
            },
        })

    # 熔断中的源排前面，方便一眼看到「现在谁在跳过」
    sources.sort(key=lambda s: (not s["breaker"]["open"], s["name"]))

    open_count = sum(1 for s in sources if s["breaker"]["open"])
    return {
        "total": len(sources),
        "enabled": sum(1 for s in sources if s["enabled"]),
        "circuit_open": open_count,
        "capability_axes": [c.value for c in SourceCapability],
        "sources": sources,
    }
