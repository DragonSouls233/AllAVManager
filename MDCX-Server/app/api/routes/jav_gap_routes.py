"""JAV 缺口体检 + 一键补全（后端）。

为什么需要它
------------
既有的三个端点各有盲区，覆盖不到「已刮削但资源不全」这个最常见的缺口：

* ``/covers/problems``  只查「文件存在但损坏」（xor_garbled / decoded_broken /
  too_small）。**缺文件**（压根没 poster.jpg）一律不算问题。
* ``/covers/fix``       修的是上面那批损坏图。
* ``/scrape/refill-nfo-cache``  只筛 ``source == "nfo_cache"`` 的影片。
  库里绝大多数是正常刮削过的（source 是 javdb/javbus 等），永远选不中。

线上实测（2026-10-05，9479 部）：缺封面 1292、缺预览图 2692，
而 ``/covers/problems`` 返回 0 —— 因为这些是「缺失」不是「损坏」。

口径
----
缺口一律**从文件系统算**，不信 DB 标志位：一行可以 DB 里有 cover_url，
但磁盘上 poster.jpg 根本没下下来（JavBus CDN 403 时就是这样）。
字段缺口（plot/studio/series）才看 DB 列。

排除项（重要）
--------------
``tag`` / ``rating`` / ``duration`` **不算缺口**。实测 tag 9190/9479 缺失、
rating 仅 64.7% 覆盖 —— 源站本身就大量没有这些数据，全量重刮 9000+ 部
纯属浪费请求且必然还是空。有效字段缺口只有 plot / studio。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.jav_models import JavMovie
from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jav", tags=["JAV缺口补全"])

MODULE = "jav"

#: 值得为补全而重新刮削的字段。刻意不含 tag/rating/duration，理由见模块 docstring。
FIELD_GAPS = ("plot", "studio", "series", "actor")

#: 补全进度（单任务；重复发起返回 busy）
_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "fixed": 0,
    "no_source": 0,
    "failed": 0,
    "started_at": 0.0,
    "by_reason": {},
    "failed_list": [],
    "log": [],
}

#: 刮削源熔断（复用 refill 端点的机制，但独立计数，互不干扰）
_fail_streak: dict[str, int] = {}
_blackout_until: dict[str, float] = {}
_FAIL_THRESHOLD = 5
_BLACKOUT_SECS = 180

#: 默认源序：JavDB 官方 App API 主力（数据最全最快），JavBus 主力辅助，
#: 其余按实测可用性兜底。素人走 canon.source_order_for 的专用序。
DEFAULT_SOURCES = ["javdb", "javbus", "avmoo", "javbooks", "freejavbt", "thejavdb"]


def _db():
    """取 jav 模块库。

    ``get_instance`` 首调必须带 base_class（生产由 main.init_all() 预注册，
    独立脚本/测试直接调用时会抛 ValueError）—— 这里兜一层。
    """
    from app.db.jav_models import JAV_BASE
    try:
        return ModuleDatabase.get_instance(MODULE)
    except ValueError:
        return ModuleDatabase.get_instance(MODULE, base_class=JAV_BASE)


# --------------------------------------------------------------------------
# 缺口判定（文件系统优先）
# --------------------------------------------------------------------------

def _has_valid_poster(d: Path) -> bool:
    """竖版封面是否存在且不是下载残留。

    只看 poster* 是历史遗留口径；实际上 fanart/thumb/cover 任一有效即可视为
    「有封面」（workflow._save_to_db 就是这么兜底选 _local_cover 的）。
    """
    for name in ("poster.jpg", "fanart.jpg", "thumb.jpg", "cover.jpg"):
        p = d / name
        try:
            if p.is_file() and p.stat().st_size > 1024:
                return True
        except OSError:
            continue
    return False


def _has_valid_preview(d: Path) -> bool:
    ex = d / "extrafanart"
    if not ex.is_dir():
        return False
    for f in ex.iterdir():
        try:
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") \
                    and f.stat().st_size > 1024:
                return True
        except OSError:
            continue
    return False


def _reasons_for(movie_dir: Path, row) -> list[str]:
    """返回该影片的缺口原因列表（空 = 完整）。"""
    out: list[str] = []
    if not movie_dir.is_dir():
        return ["no_dir"]
    if not _has_valid_poster(movie_dir):
        out.append("cover")
    if not _has_valid_preview(movie_dir):
        out.append("preview")
    for f in FIELD_GAPS:
        v = getattr(row, f, None)
        if not (v and str(v).strip()):
            out.append(f)
    return out


async def _scan(limit: int = 0) -> tuple[list[dict], dict]:
    """扫描全库缺口。返回 (items, stats)。

    items: [{movie_id, code, title, reasons:[...], output_dir}]
    """
    from app.utils.media_helpers import get_movie_local_dir

    db = _db()
    session = await db.get_session()
    try:
        rows = (await session.execute(
            select(JavMovie.id, JavMovie.code, JavMovie.title,
                   JavMovie.output_dir, JavMovie.plot, JavMovie.studio,
                   JavMovie.series, JavMovie.actor)
        )).all()
    finally:
        await session.close()

    items: list[dict] = []
    counts: dict[str, int] = {}
    for mid, code, title, output_dir, plot, studio, series, actor in rows:
        if not code:
            continue
        # output_dir 可能是空/失效，用它优先（历史数据指向真实盘符）
        d = Path(output_dir) if output_dir else None
        if d is None or not d.is_dir():
            d = get_movie_local_dir(MODULE, code)

        class _R:
            pass
        r = _R()
        r.plot, r.studio, r.series, r.actor = plot, studio, series, actor
        reasons = _reasons_for(d, r)
        if not reasons:
            continue
        for x in reasons:
            counts[x] = counts.get(x, 0) + 1
        items.append({
            "movie_id": mid,
            "code": code,
            "title": title or code,
            "reasons": reasons,
            "output_dir": str(d),
        })

    if limit and len(items) > limit:
        items = items[:limit]
    stats = {
        "total_movies": len(rows),
        "total_gap": sum(counts.values()),
        "by_reason": counts,
    }
    return items, stats


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@router.get("/gaps/audit")
async def gaps_audit(
    limit: int = Query(0, ge=0, le=20000, description="0 = 不限制"),
    offset: int = Query(0, ge=0),
    reason: str = Query("", description="按单一原因过滤：cover/preview/plot/…"),
):
    """缺口体检：返回各类缺口数量 + 明细（默认全量，只读不写）。"""
    items, stats = await _scan()
    if reason:
        items = [i for i in items if reason in i["reasons"]]
    page = items[offset: offset + limit] if limit else items[offset:]
    return {
        "stats": stats,
        "reason": reason,
        "offset": offset,
        "returned": len(page),
        "items": page,
    }


class GapFillRequest(BaseModel):
    codes: Optional[list[str]] = Field(None, description="指定番号；空 = 按缺口自动选")
    reasons: list[str] = Field(
        default_factory=lambda: ["cover", "preview"],
        description="要补的缺口类型；含字段名(plot/studio/…)则连字段一起补",
    )
    limit: int = Field(200, ge=1, le=5000)
    concurrency: int = Field(4, ge=1, le=10)
    gap_seconds: float = Field(0.0, ge=0, description="每部之间的额外间隔（秒）")
    sources: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCES))
    dry_run: bool = Field(False, description="True = 只列出将要处理的番号，不动手")


@router.post("/gaps/fill")
async def gaps_fill(data: GapFillRequest, background_tasks: BackgroundTasks):
    """一键补全缺口（后台执行 + 进度轮询）。

    每部：按源序尝试刮削 → 落盘（封面/预览图/NFO）→ 写库。
    源连续故障自动熔断 3 分钟，避免一个坏源拖死整批。
    """
    if _state.get("running"):
        return {"status": "busy", **_state}

    items, _stats = await _scan()
    want = set(data.reasons or ["cover", "preview"])
    if data.codes:
        picked = [i for i in items if i["code"] in set(data.codes)]
    else:
        picked = [i for i in items if want & set(i["reasons"])]
    picked = picked[: data.limit]

    if not picked:
        return {"status": "ok", "message": "没有匹配缺口的影片", "total": 0, "queued": 0}

    if data.dry_run:
        return {
            "status": "dry_run",
            "total": len(picked),
            "codes": [i["code"] for i in picked],
        }

    _state.update({
        "running": True, "done": 0, "total": len(picked),
        "fixed": 0, "no_source": 0, "failed": 0,
        "started_at": time.time(),
        "by_reason": {}, "failed_list": [], "log": [],
    })
    for i in picked:
        for r in i["reasons"]:
            _state["by_reason"][r] = _state["by_reason"].get(r, 0) + 1

    async def _run():
        from app.scraper.engine import ScraperEngine
        from app.scraper.workflow import ScraperWorkflow
        from app.config.manager import DATA_DIR
        from app.scraper.canon import is_amateur_code, AMATEUR_SOURCE_ORDER

        # 新任务清空熔断状态（上一轮 JAVBUS 挂了不代表这轮 JAVDB 也挂）
        _fail_streak.clear()
        _blackout_until.clear()

        wf = ScraperWorkflow(str(DATA_DIR / "movies"))
        sem = asyncio.Semaphore(data.concurrency)
        sources = list(data.sources)
        # 素人用专用源序（javbus 对素人实测 0/5，javmenu 5/5）
        amateur_set = [i["code"] for i in picked if is_amateur_code(i["code"])]
        if amateur_set:
            head = [s for s in AMATEUR_SOURCE_ORDER if s in sources]
            tail = [s for s in sources if s not in head]
            sources = head + tail
            _state["log"].append(
                "素人 %d 部，源序调整为 %s" % (len(amateur_set), sources))

        async def _try_source(code: str, src: str):
            """单源尝试。返回 ScrapeResult 或 None。超时/异常算「确定性故障」，
            「站点正常但没这片」不算 —— 否则连遇 10 个未收录片就会把好源熔断掉。"""
            if _blackout_until.get(src, 0) > time.monotonic():
                return None
            fatal = False
            try:
                task = asyncio.create_task(
                    ScraperEngine().scrape_number(code, module=MODULE, sources=[src]))
                done, _ = await asyncio.wait({task}, timeout=60.0)
                if task in done:
                    r = task.result()
                else:
                    task.cancel()   # 不等取消生效，僵尸协程后台自灭
                    r = None
                    fatal = True
            except Exception as e:  # noqa: BLE001
                r = None
                fatal = True
                logger.warning("[gaps] %s 源 %s 异常 %s", code, src, e)

            if r and r.is_valid():
                _fail_streak[src] = 0
                _blackout_until.pop(src, None)
                return r
            if fatal:
                _fail_streak[src] = _fail_streak.get(src, 0) + 1
                if _fail_streak[src] >= _FAIL_THRESHOLD:
                    _blackout_until[src] = time.monotonic() + _BLACKOUT_SECS
                    _fail_streak[src] = 0
                    _state["log"].append(
                        "源 %s 连续故障 %d 次，熔断 %ds"
                        % (src, _FAIL_THRESHOLD, _BLACKOUT_SECS))
            return None

        async def _one(item):
            code = item["code"]
            result = None
            async with sem:
                for src in sources:
                    result = await _try_source(code, src)
                    if result is not None:
                        break
            if not result:
                _state["no_source"] += 1
                _state["failed_list"].append({"code": code, "reason": "no_source"})
                return
            try:
                await wf.persist(result, module=MODULE)
                _state["fixed"] += 1
            except Exception as e:  # noqa: BLE001
                _state["failed"] += 1
                _state["failed_list"].append({"code": code, "reason": str(e)[:160]})
                logger.warning("[gaps] %s 落盘失败: %s", code, e)

        async def _worker():
            for item in picked:
                await _one(item)
                _state["done"] += 1
                if data.gap_seconds:
                    await asyncio.sleep(data.gap_seconds)

        try:
            await _worker()
        finally:
            _state["running"] = False
            _, after = await _scan()
            _state["log"].append("完成：剩余缺口 %d" % sum(after["by_reason"].values()))
            logger.info("[gaps] 补全结束 %s", {k: v for k, v in _state.items()
                                              if k != "log"})

    background_tasks.add_task(_run)
    return {"status": "started", "total": len(picked),
            "queued": len(picked), "by_reason": _state["by_reason"]}


@router.get("/gaps/fill/status")
async def gaps_fill_status():
    """一键补全进度（前端轮询）"""
    return _state
