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

#: 🔴 2026-10-06 实测（120 服务器，MIDE-834 / SSIS-001 逐源真跑）：
#: **主力源 javdb / javmenu / javbus / dmm_web 全都不返回 plot**，能给简介的
#: 只有 3 个辅助源，且质量差距极大：
#:     thejavdb   171~199 字日文真简介   ← 最好，优先
#:     javplace    34~40 字中文机翻     ← 能用
#:     javmost     42 字 "Watch XXX JAV movie online streaming..." ← **SEO 垃圾**
#: 原实现「首个源命中即 break」，javdb 排第一 ⇒ 永远走不到能给 plot 的源
#: ⇒ 用户看到「200 部完成」但 plot 缺口一个没少（实测 17479→17367 只掉 112，
#: 掉的还是 studio/series）。现在改为**按「是否补齐目标缺口」决定是否继续试源**。
#:
#: 且 javmost 那种 SEO 模板文案写进库比留空更糟（前端会把它当剧情简介展示），
#: 必须显式拦掉，见 ``_is_junk_plot``。
_JUNK_PLOT_MARKERS = (
    "jav movie online",
    "movie online streaming",
    "watch online free",
    "free porn video",
    "watch porn",
)


def _is_junk_plot(plot: str | None) -> bool:
    """判断简介是否是 SEO 模板垃圾文案（写进库比留空更糟）。"""
    if not plot:
        return True
    p = plot.strip().lower()
    if len(p) < 15:                                  # 太短，基本是占位
        return True
    if any(m in p for m in _JUNK_PLOT_MARKERS):      # javmost 的 "Watch XXX JAV movie online…"
        return True
    if p.startswith("watch ") and "online" in p[:60]:
        return True
    return False


def _result_covers(result, reasons: set[str]) -> set[str]:
    """该刮削结果实际能补上 ``reasons`` 里的哪几类缺口。

    🔴 这是「完成 200 部却只少 3 个」的根治点：刮削成功 ≠ 缺口被补上。
    旧代码只看 ``result is not None`` 就 break，于是 javdb 命中（有标题/演员/
    厂牌）就收工，而它根本不给 plot ⇒ 整批处理完 plot 缺口纹丝不动。
    """
    got: set[str] = set()
    if "plot" in reasons and not _is_junk_plot(getattr(result, "plot", None)):
        got.add("plot")
    if "series" in reasons and (getattr(result, "series", None) or "").strip():
        got.add("series")
    if "studio" in reasons and (getattr(result, "studio", None) or "").strip():
        got.add("studio")
    if "actor" in reasons and getattr(result, "actors", None):
        got.add("actor")
    # 图片类：源给了封面/剧照 URL 才算能补（能不能下载成不成功另说）
    if "cover" in reasons and getattr(result, "cover_url", None):
        got.add("cover")
    if "preview" in reasons and (getattr(result, "sample_images", None)
                                 or getattr(result, "extrafanart", None)):
        got.add("preview")
    return got

#: 补全进度（单任务；重复发起返回 busy）
_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "fixed": 0,
    "no_source": 0,
    "failed": 0,
    "started_at": 0.0,
    "finished_at": 0.0,
    "current": "",
    "cancel_requested": False,
    "by_reason": {},
    "failed_list": [],
    "log": [],
}

#: 阶段日志上限。后端每部影片会产生 3~6 行（开始/试源/命中/落盘/完成），
#: 2000 部就能刷出上万行 —— 不截断会把内存和前端 DOM 一起撑爆。
_LOG_MAX = 400


def _log(msg: str) -> None:
    """追加一条阶段日志（带时间戳 + 环形截断）。"""
    _state["log"].append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
    if len(_state["log"]) > _LOG_MAX:
        del _state["log"][: len(_state["log"]) - _LOG_MAX]

#: 刮削源熔断（复用 refill 端点的机制，但独立计数，互不干扰）
_fail_streak: dict[str, int] = {}
_blackout_until: dict[str, float] = {}
_FAIL_THRESHOLD = 5
_BLACKOUT_SECS = 180

#: 自动源序的**兜底补充源**。
#:
#: 🔴 2026-10-05 起本模块不再自己硬编码源序 —— 完整源序（含日本 DMM 与辅助源）
#: 统一由 ``canon.source_order_for(code)`` 维护。之前这里写死 ``DEFAULT_SOURCES``
#: 不含 ``dmm_web``，且逐个 ``scrape_number(sources=[src])`` 单源调用会旁路 engine 的
#: ``PRIMARY_CRAWLERS`` / ``JP_TAIL_CRAWLERS`` 整套编排，
#: 导致「DMM 已进主力」这条决定在缺口补全页完全失效。
#:
#: 源序结构（2026-10-05 用户决定 DMM 优先于 thejavdb）：
#:     主力(有码) javdb→javmenu→javmost→javbus
#:     主力(素人) javmenu→javmost→javdb→javbus
#:     日本官方   dmm_web          ← 在 thejavdb 之前
#:     辅助源     thejavdb→avmoo→javbooks→freejavbt
#: 本模块只负责**逐部取序并逐个试**，不再关心序里有哪些源。


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
    """竖版封面是否存在、够大、且**真的能解码**。

    只看 poster* 是历史遗留口径；实际上 fanart/thumb/cover 任一有效即可视为
    「有封面」（workflow._save_to_db 就是这么兜底选 _local_cover 的）。

    🔴 2026-10-06 合并「封面问题修复」能力：原实现只判「文件在不在、>1024 字节」，
    于是 182KB 但完全无法解码的损坏封面（CDN 半截下载 / 格式损坏）被判为**有效**
    ⇒ 缺口体检永远看不见它们。实测 120 服务器 covers/problems 报 2772 部坏封面，
    而旧 gaps 口径对同一批番号命中 **0**。现在改为复用 jav_routes 的
    ``_inspect_cover_problem``（读文件头 + PIL 解码）逐个校验。
    """
    # 损坏检测按需导入：避免本模块对 jav_routes 形成导入依赖
    from app.api.routes.jav_routes import _inspect_cover_problem

    for name in ("poster.jpg", "fanart.jpg", "thumb.jpg", "cover.jpg"):
        p = d / name
        try:
            if not (p.is_file() and p.stat().st_size > 1024):
                continue
        except OSError:
            continue
        # 文件在且够大 → 再验内容。_inspect_cover_problem 返回 None = 图片正常
        if _inspect_cover_problem(p) is None:
            return True
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


def _row_of(item: dict):
    """从缺口 item 还原一个只带字段值的壳，供 _reasons_for 复查用。"""
    class _R:
        pass
    r = _R()
    r.plot = item.get("plot")
    r.studio = item.get("studio")
    r.series = item.get("series")
    r.actor = item.get("actor")
    return r


async def _fresh_reasons(movie_dir: Path, code: str) -> list[str] | None:
    """落盘后复查该片真实缺口：**现查数据库**，不用扫描时的旧快照。

    🔴 不能用 ``_row_of(item)``：那是从本次扫描结果还原的壳，
    字段值还是刮削**之前**的空值 ⇒ 拿它复查会永远判「仍缺」，
    等于白做一次复查（这也是「完成数看起来很漂亮但缺口不动」的帮凶）。
    查询失败返回 None（调用方按「完成」处理，不阻塞流程）。
    """
    try:
        db = _db()
        session = await db.get_session()
        try:
            row = (await session.execute(
                select(JavMovie.plot, JavMovie.studio, JavMovie.series, JavMovie.actor)
                .where(JavMovie.code == code)
            )).first()
        finally:
            await session.close()
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    class _R:
        pass
    r = _R()
    r.plot, r.studio, r.series, r.actor = row[0], row[1], row[2], row[3]
    # 🔴 本函数是 async，调用方只能 `await _fresh_reasons(...)`，
    # 绝不能再套 `asyncio.to_thread` —— 那会拿到协程对象本身，
    # `set(coroutine)` 直接抛 "'coroutine' object is not iterable"
    # （2026-10-06 实测踩到）。
    # 而 _reasons_for 内含 PIL 解码（CPU + 网络盘 I/O）⇒ 丢线程池，别阻塞事件循环。
    return await asyncio.to_thread(_reasons_for, movie_dir, r)


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

    items: [{movie_id, code, title, reasons:[...], output_dir, video_dir, 字段值…}]
    ``video_dir`` = 真实片库里视频文件所在目录，供 local_first 离线拷图用。
    """
    from app.utils.media_helpers import get_movie_local_dir

    db = _db()
    session = await db.get_session()
    try:
        rows = (await session.execute(
            select(JavMovie.id, JavMovie.code, JavMovie.title,
                   JavMovie.output_dir, JavMovie.plot, JavMovie.studio,
                   JavMovie.series, JavMovie.actor, JavMovie.file_path)
        )).all()
    finally:
        await session.close()

    total_movies = len(rows)

    # 封面校验现在含 PIL 解码（见 _has_valid_poster），是 CPU + 网络盘 I/O 混合的
    # 重活；串行做会让 9479 部体检从秒级变成分钟级。丢线程池并发，
    # 每部内部仍是「按 poster→fanart→thumb→cover 顺序，命中即停」。
    def _reasons_sync(code: str, d: Path, plot, studio, series, actor) -> list[str]:
        class _R:
            pass
        r = _R()
        r.plot, r.studio, r.series, r.actor = plot, studio, series, actor
        return _reasons_for(d, r)

    def _check(row):
        mid, code, title, output_dir, plot, studio, series, actor, file_path = row
        d = Path(output_dir) if output_dir else None
        if d is None or not d.is_dir():
            d = get_movie_local_dir(MODULE, code)
        # 真实片库目录（视频文件所在处）——local_first 离线拷图的来源
        vdir = None
        if file_path and file_path != "N/A":
            try:
                p = Path(file_path)
                if p.parent.is_dir():
                    vdir = p.parent
            except OSError:
                vdir = None
        reasons = _reasons_sync(code, d, plot, studio, series, actor)
        return (code, title, str(d), reasons, vdir,
                plot, studio, series, actor)

    rows = [r for r in rows if r[1]]
    computed = await asyncio.gather(
        *(asyncio.to_thread(_check, r) for r in rows)
    )

    items: list[dict] = []
    counts: dict[str, int] = {}
    for (mid, *_rest), (code, title, dir_str, reasons, vdir,
                        plot, studio, series, actor) in zip(rows, computed):
        if not reasons:
            continue          # 完整影片不进缺口清单
        for x in reasons:
            counts[x] = counts.get(x, 0) + 1
        items.append({
            "movie_id": mid,
            "code": code,
            "title": title or code,
            "reasons": reasons,
            "output_dir": dir_str,
            "video_dir": str(vdir) if vdir else "",
            "plot": plot, "studio": studio, "series": series, "actor": actor,
        })

    if limit and len(items) > limit:
        items = items[:limit]
    stats = {
        "total_movies": total_movies,
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
    sources: list[str] = Field(
        default_factory=list,
        description="手动指定源序（留空 = 按番号走 canon 自动序，含 DMM）",
    )
    dry_run: bool = Field(False, description="True = 只列出将要处理的番号，不动手")
    local_first: bool = Field(
        True,
        description=(
            "先从真实片库目录离线拷贝已存在的 {code}-*.jpg（不联网、秒级），"
            "拷到仍缺再走远程刮削。原「补全 NFO 缓存」页的独有能力，已并入此处"
        ),
    )


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
        # 🔴 按勾选类型**轮转**取片（2026-10-06 用户反馈「跑了 50 个，缺封面
        # 才少了几个」）：items 是 movie_id 顺序，而缺预览图的片远多于缺封面
        # （2385 vs 465）⇒ 直接切片时 50 个名额几乎全被 preview 占掉
        # （实测 49 preview / 2 cover，cover 项在队列里排在第 23、24、65… 位），
        # 用户勾了「封面」等于没勾，封面数自然纹丝不动。
        # 轮转后每类都能拿到约 1/N 的名额，勾哪类哪类就降。
        order_want = list(dict.fromkeys(
            r for r in (data.reasons or []) if r in want)) or sorted(want)
        buckets = [[i for i in items if r in i["reasons"]] for r in order_want]
        picked = []
        seen: set[str] = set()
        while len(picked) < data.limit:
            before = len(picked)
            for b in buckets:
                while b and b[0]["code"] in seen:
                    b.pop(0)          # 已被其它类型取走的（如同时缺封面+预览图）
                if b:
                    it = b.pop(0)
                    seen.add(it["code"])
                    picked.append(it)
                    if len(picked) >= data.limit:
                        break
            if len(picked) == before:
                break                 # 所有桶都空了
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
        "started_at": time.time(), "finished_at": 0.0, "current": "",
        # 🔴 必须重置：上一轮点过「中止」若残留，这轮会一部都不跑
        "cancel_requested": False,
        "by_reason": {}, "failed_list": [], "log": [],
    })
    # 🔴 by_reason 只统计**本次勾选**的缺口（want）。旧实现统计的是 picked
    # 片子的全部缺口（cover/plot/preview/series/studio），日志打出 5 类会让
    # 用户以为「只勾了 2 个却按 5 个跑」（2026-10-06 实际反馈）。
    for i in picked:
        for r in set(i["reasons"]) & want:
            _state["by_reason"][r] = _state["by_reason"].get(r, 0) + 1
    _log("任务开始：共 %d 部，并发 %d，本次只补 %s"
         % (len(picked), data.concurrency, "/".join(sorted(want))))

    async def _run():
        from app.scraper.engine import ScraperEngine
        from app.scraper.workflow import ScraperWorkflow
        from app.config.manager import DATA_DIR
        from app.scraper.canon import source_order_for

        # 新任务清空熔断状态（上一轮 JAVBUS 挂了不代表这轮 JAVDB 也挂）
        _fail_streak.clear()
        _blackout_until.clear()

        wf = ScraperWorkflow(str(DATA_DIR / "movies"))
        sem = asyncio.Semaphore(data.concurrency)
        # 手动指定则完全尊重；留空则逐部按 canon 自动序（见 _order_for）
        manual = [s.strip() for s in (data.sources or []) if s.strip()]

        def _order_for(code: str) -> list[str]:
            """该番号的完整源序（主力 + 日本源 + 辅助源），全部由 canon 决定。

            🔴 必须**逐部**算，不能全批共用一个序：``source_order_for`` 会按番号
            分流素人 / 有码（javbus 对素人实测 0/5、javmenu 5/5），全批一刀切会让
            素人和有码片共用错误的序，把可用源排到后面去。
            """
            return list(manual) if manual else list(source_order_for(code))

        if manual:
            _log("手动源序：%s" % manual)
        else:
            _log("自动源序：有码 %s｜素人 %s"
                 % ("→".join(source_order_for("ABC-123")),
                    "→".join(source_order_for("200GANA-3426"))))

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
                    _log("源 %s 连续故障 %d 次，熔断 %ds"
                         % (src, _FAIL_THRESHOLD, _BLACKOUT_SECS))
            return None

        async def _one(item):
            code = item["code"]
            result = None
            # 🔴 勾选即范围（2026-10-06）：只补**本次勾选的**缺口，不再牵连该片
            # 的其他缺口。旧实现拿 `item["reasons"]`（全部缺口）去选源 ⇒ 用户勾
            # cover/preview（本可由本地拷贝秒级解决）也会为 plot/series 试遍 11 个
            # 源，单部从秒级涨到 1-2 分钟，且日志显示 5 类缺口像是勾选没生效。
            # 落盘仍是全字段写入（顺手拿到的字段照写，不浪费），只是不为未勾选的
            # 缺口额外花时间试源、也不作为成功/失败判据。
            reasons = set(item["reasons"]) & want
            _log("▶ %s 开始（缺 %s）" % (code, "/".join(sorted(reasons))))
            extra = set(item["reasons"]) - reasons
            if extra:
                _log("  · %s 另有 %s（未勾选，本次不补）"
                     % (code, "/".join(sorted(extra))))

            # 步骤 0（可选，默认开）：先离线拷本地图。
            # 这是原「补全 NFO 缓存」页唯一的独有能力——片库里往往已经有
            # {code}-*.jpg，拷过来比联网刮削快几个数量级且不消耗站点配额。
            # 复用 refill 端点的同一个函数，别写第二份。
            if data.local_first and (reasons & {"cover", "preview"}):
                try:
                    from app.api.routes.jav_routes import _copy_local_previews
                    # 🔴 video_dir 在 _scan 里存成了 str（要进 JSON 返回给前端），
                    # 而 _copy_local_previews 内部要 .exists() ⇒ 必须转回 Path，
                    # 否则直接抛 'str' object has no attribute 'exists'。
                    vdir = item.get("video_dir")
                    if not vdir:
                        _log("  – %s 无片库目录可拷，跳过本地步骤" % code)
                        vdir = None
                    if vdir:
                        n = await asyncio.wait_for(
                            asyncio.to_thread(_copy_local_previews, Path(vdir), code),
                            timeout=20.0,
                        )
                    else:
                        n = 0
                    if n:
                        _log("  ⇩ %s 本地拷贝 %d 张图" % (code, n))
                except asyncio.TimeoutError:
                    _log("  ⏱ %s 本地拷贝超时 20s，跳过" % code)
                except Exception as e:  # noqa: BLE001
                    _log("  ! %s 本地拷贝失败：%s" % (code, str(e)[:80]))
                # 拷完重新体检：本地图可能已经把该片的缺口填平了。
                # 🔴 只复查「本次勾选的缺口」（reasons 已是 want 交集）——拷贝不可能
                # 补上 plot/studio/series/actor，拿全量 reasons 去比会永远判未补齐，
                # 于是白花一次站点请求；而拿硬编码的 {"cover","preview"} 比，
                # 用户只勾 cover 时又会被未勾选的 preview 拖住。
                still = set(_reasons_for(Path(item["output_dir"]), _row_of(item)))
                if not (still & reasons):
                    _state["fixed"] += 1
                    _log("  ✔ %s 本地图已补齐，无需联网" % code)
                    return

            # 🔴 2026-10-06 重写选源逻辑（原「首个命中即 break」是假成功的根源）：
            # 目标是**补齐本次勾选的缺口**，不是「随便拿到一个结果」。
            # 主力源 javdb/javmenu/javbus/dmm_web 实测全都不给 plot，
            # 而能给 plot 的 thejavdb/javplace 排在辅助段 —— 首个命中就收工的话
            # 永远碰不到它们。所以：命中但没覆盖目标缺口 ⇒ 记住、继续试下一个源，
            # 直到覆盖齐全或源耗尽；最终用「覆盖最多」的那个结果落盘。
            order = _order_for(code)
            best = None          # (覆盖数, result, 源名)
            covered: set[str] = set()
            async with sem:
                for src in order:
                    _log("  · %s 试源 %s" % (code, src))
                    r = await _try_source(code, src)
                    if r is None:
                        continue
                    got = _result_covers(r, reasons)
                    _log(("  ✔ %s 命中 %s：%s｜补到 %s"
                          % (code, src, r.title or "", "/".join(sorted(got)) or "无"))[:170])
                    if not best or len(got) > len(covered):
                        best, covered = (r, src), got
                    if reasons <= got:
                        break    # 目标缺口全齐，收工
            if not best:
                _state["no_source"] += 1
                _state["failed_list"].append({"code": code, "reason": "no_source"})
                _log("  ✘ %s 全部源未收录" % code)
                return
            result, hit_src = best
            missing = reasons - covered
            if missing:
                # 命中了但给不出要补的字段 —— 记进日志，让「完成数 ≠ 缺口减少」有据可查
                _log("  ⚠ %s 源 %s 未给 %s，仍会落盘其余字段"
                     % (code, hit_src, "/".join(sorted(missing))))
            try:
                _log("  ↓ %s 落盘中（写库/下封面/NFO）" % code)
                await wf.persist(result, module=MODULE)
            except Exception as e:  # noqa: BLE001
                _state["failed"] += 1
                _state["failed_list"].append({"code": code, "reason": str(e)[:160]})
                _log("  ✘ %s 落盘失败：%s" % (code, str(e)[:100]))
                logger.warning("[gaps] %s 落盘失败: %s", code, e)
                return

            # 🔴 落盘后**复查真实缺口**，只在实际补齐时才计 fixed。
            # 旧代码 persist 一成功就 fixed += 1 ⇒ 「刮削 200 部、缺口只少 3 个」
            # 这种假成功在界面上完全看不出来。
            try:
                # 🔴 `_fresh_reasons` 本身是 async（内部要先查库），**不能**再套
                # asyncio.to_thread —— 那样 await 到的是协程对象，
                # `set(coroutine)` 抛 "'coroutine' object is not iterable"。
                fresh = await _fresh_reasons(Path(item["output_dir"]), code)
            except Exception as e:  # noqa: BLE001
                fresh = None
                _log("  ! %s 复查失败：%s" % (code, str(e)[:80]))
            if fresh is None:
                _state["fixed"] += 1
                _log("  ✔ %s 完成" % code)
            else:
                left = set(fresh) & reasons
                if not left:
                    _state["fixed"] += 1
                    _log("  ✔ %s 已补齐（%s）" % (code, "/".join(sorted(reasons))))
                else:
                    _state["no_source"] += 1
                    _state["failed_list"].append(
                        {"code": code, "reason": "源无此字段: %s" % "/".join(sorted(left))})
                    _log("  ✘ %s 落盘后仍缺 %s（源站无数据，非故障）"
                         % (code, "/".join(sorted(left))))

        async def _worker():
            for item in picked:
                if _state.get("cancel_requested"):
                    _log("已中止，跳过剩余 %d 部" % (len(picked) - _state["done"]))
                    break
                _state["current"] = item["code"]
                try:
                    await _one(item)
                except Exception as e:  # noqa: BLE001
                    # 🔴 必须兜住：BackgroundTasks 里抛的异常只会进服务器日志，
                    # 前端轮询会一直看到 running=true 以为还在跑 —— 表现为
                    # 「进度条卡住、看不到任何日志」。这里单部失败不影响整批。
                    _state["failed"] += 1
                    _state["failed_list"].append(
                        {"code": item["code"], "reason": str(e)[:160]})
                    _log("  ✘ %s 处理异常：%s" % (item["code"], str(e)[:120]))
                    logger.warning("[gaps] %s 未预期异常", item["code"], exc_info=True)
                _state["done"] += 1
                if data.gap_seconds:
                    await asyncio.sleep(data.gap_seconds)

        try:
            await _worker()
        finally:
            _state["running"] = False
            _state["current"] = ""
            _state["finished_at"] = time.time()
            cost = int(_state["finished_at"] - _state["started_at"])
            _, after = await _scan()
            left = sum(after["by_reason"].values())
            _log("任务结束：耗时 %d分%02d秒，成功 %d，无源 %d，失败 %d｜剩余缺口 %d"
                 % (cost // 60, cost % 60, _state["fixed"], _state["no_source"],
                    _state["failed"], left))
            logger.info("[gaps] 补全结束 %s", {k: v for k, v in _state.items()
                                              if k not in ("log", "failed_list")})

    background_tasks.add_task(_run)
    return {"status": "started", "total": len(picked),
            "queued": len(picked), "by_reason": _state["by_reason"]}


@router.get("/gaps/fill/status")
async def gaps_fill_status():
    """一键补全进度（前端轮询）"""
    return _state


@router.post("/gaps/fill/cancel")
async def gaps_fill_cancel():
    """请求中止正在跑的批量补全。

    已在跑的一部会跑完（刮削/落盘都是不可中断的 IO，硬杀会留下半写状态），
    但不再启动下一部 —— 和 refill 端点的 cancel 语义一致。
    """
    if not _state.get("running"):
        return {"status": "idle", "running": False}
    _state["cancel_requested"] = True
    _log("收到中止请求，当前这部跑完后停止")
    return {"status": "cancel_requested", "running": True,
            "done": _state.get("done", 0), "total": _state.get("total", 0)}
