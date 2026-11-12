"""字幕下载编排层：两站并发搜索 → 番号守卫 → 选优 → 回退下载 → 规范化落盘 → 登记。

对外只暴露 ``fetch_for_movie`` / ``fetch_for_code`` 与批量任务三件套。
与播放器的 ``subtitle_online`` 链路互不影响（那份不落盘、不走代理）。

失败一律返回 ``ok=False`` + ``reason``（见 :class:`FailReason`），不抛给路由层，
让前端能拿到可读原因而不是 500。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.services.subtitle_sources import SOURCES
from app.services.subtitle_sources.base import (
    LANG_RANK,
    MAX_CANDIDATES_TRY,
    MAX_SIZE_PROBES,
    SOURCE_LABEL,
    VIDEO_BUDGET_S,
    Budget,
    DownloadFailed,
    SubtitleCandidate,
    SubtitleError,
    code_from_path,
    merge_and_rank,
    normalize_code,
    normalize_srt,
    registry_record,
    srt_target_path,
    title_matches_code,
)

logger = logging.getLogger(__name__)

SUPPORTED_MODULES = ("jav", "uncensored")
BATCH_CONCURRENCY_MIN, BATCH_CONCURRENCY_MAX, BATCH_CONCURRENCY_DEFAULT = 1, 4, 3
BATCH_LIMIT_MAX = 500
JOB_HISTORY = 20
JOB_ITEMS_KEEP = 500


class FailReason(str, Enum):
    NO_NUMBER = "no_number"
    NO_FILE_PATH = "no_file_path"
    ALREADY_EXISTS = "already_exists"
    SITE_EMPTY = "site_empty"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    DOWNLOAD_FAILED = "download_failed"
    WRITE_FAILED = "write_failed"
    CANCELLED = "cancelled"


# 后端兜底文案；前端另有同一份中文映射表（唯一展示源）
REASON_MESSAGE = {
    FailReason.ALREADY_EXISTS: "该影片已有字幕，已跳过",
    FailReason.NO_NUMBER: "无法从片名识别番号，无法搜索",
    FailReason.NO_FILE_PATH: "该影片没有本地文件路径，无法写入字幕",
    FailReason.SITE_EMPTY: "两个站点都没有搜到该番号的字幕",
    FailReason.BLOCKED: "站点暂时拒绝访问（可能触发风控），请稍后重试",
    FailReason.TIMEOUT: "搜索或下载超时，请稍后重试",
    FailReason.DOWNLOAD_FAILED: "字幕文件下载失败，已尝试全部候选",
    FailReason.WRITE_FAILED: "写入视频目录失败（网络盘只读/磁盘已满）",
    FailReason.CANCELLED: "已取消",
}


@dataclass
class FetchResult:
    ok: bool
    status: str                       # downloaded | skipped | failed
    movie_id: int | None = None
    code: str = ""
    reason: FailReason | None = None
    message: str = ""
    source: str | None = None
    source_label: str | None = None
    language: str | None = None
    language_label: str | None = None
    path: str | None = None
    bytes: int = 0
    lines: int = 0
    elapsed_ms: int = 0
    candidates_total: int = 0
    attempts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "movie_id": self.movie_id,
            "code": self.code,
            "reason": self.reason.value if self.reason else None,
            "message": self.message,
            "source": self.source,
            "source_label": self.source_label,
            "language": self.language,
            "language_label": self.language_label,
            "path": self.path,
            "bytes": self.bytes,
            "lines": self.lines,
            "elapsed_ms": self.elapsed_ms,
            "candidates_total": self.candidates_total,
            "attempts": self.attempts,
        }


def _failed(reason: FailReason, code: str = "", *, message: str = "", elapsed_ms: int = 0,
            movie_id: int | None = None) -> FetchResult:
    return FetchResult(
        ok=False, status="failed", movie_id=movie_id, code=code, reason=reason,
        message=message or REASON_MESSAGE[reason], elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------- 单条
def _module_db(module: str):
    from app.db.module_db import ModuleDatabase
    from app.utils.module_helper import get_module_base

    try:
        return ModuleDatabase.get_instance(module)
    except ValueError:
        return ModuleDatabase.get_instance(module, base_class=get_module_base(module))


async def _load_movie(module: str, movie_id: int) -> dict | None:
    from sqlalchemy import select

    from app.utils.module_helper import get_module_model

    Movie = get_module_model(module, "movie")
    db = _module_db(module)
    session = await db.get_session()
    try:
        row = (await session.execute(select(Movie).where(Movie.id == movie_id))).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": getattr(row, "id", movie_id),
            "code": getattr(row, "code", None),
            "file_path": getattr(row, "file_path", None),
        }
    finally:
        await session.close()


async def _sync_flags(module: str | None, movie_id: int | None) -> None:
    """成功后顺手把 has_subtitle / is_chinese 置真（只加不减，与扫描器口径一致）。"""
    if not module or movie_id is None or module not in SUPPORTED_MODULES:
        return
    from sqlalchemy import update

    from app.utils.module_helper import get_module_model

    Movie = get_module_model(module, "movie")
    values: dict[str, Any] = {"is_chinese": True}
    if hasattr(Movie, "has_subtitle"):
        values["has_subtitle"] = True
    db = _module_db(module)
    session = await db.get_session()
    try:
        await session.execute(update(Movie).where(Movie.id == movie_id).values(**values))
        await session.commit()
    except Exception:  # noqa: BLE001 - 同步失败不影响已落盘的字幕
        await session.rollback()
        logger.warning("同步 has_subtitle 失败 module=%s id=%s", module, movie_id, exc_info=True)
    finally:
        await session.close()


def _has_subtitle(video_path: str, code: str) -> bool:
    from app.tasks.base_scanner import find_external_subtitle

    return find_external_subtitle(video_path, code or None)


async def _search_sources(code: str, budget: Budget) -> tuple[list[SubtitleCandidate], list[BaseException]]:
    names = list(SOURCES)
    results = await asyncio.gather(
        *(SOURCES[name].search(code, budget=budget) for name in names),
        return_exceptions=True,
    )
    candidates: list[SubtitleCandidate] = []
    errors: list[BaseException] = []
    for name, item in zip(names, results):
        if isinstance(item, BaseException):
            logger.info("[subtitle] %s 搜索失败 code=%s: %s", name, code, item)
            errors.append(item)
        else:
            candidates.extend(item)
    return candidates, errors


def _empty_reason(candidates: list[SubtitleCandidate], errors: list[BaseException]) -> FailReason:
    if candidates:
        return FailReason.SITE_EMPTY
    if not errors:
        return FailReason.SITE_EMPTY
    if all(isinstance(err, SubtitleError) and err.reason == "blocked" for err in errors):
        return FailReason.BLOCKED
    if all(isinstance(err, SubtitleError) and err.reason == "timeout" for err in errors):
        return FailReason.TIMEOUT
    return FailReason.DOWNLOAD_FAILED


async def _probe_unknown_sizes(queue: list[SubtitleCandidate], budget: Budget) -> list[SubtitleCandidate]:
    """同语言层内若大小未知，用 HEAD 补全，让「取最大」真正生效。"""
    unknown = [cand for cand in queue if not cand.size_declared]
    if not unknown:
        return queue
    probed: dict[str, int | None] = {}
    for cand in unknown[:MAX_SIZE_PROBES]:
        if budget.expired():
            break
        try:
            probed[cand.download_url] = await SOURCES[cand.source].probe_size(cand, budget=budget)
        except Exception:  # noqa: BLE001
            probed[cand.download_url] = None
    if not probed:
        return queue
    replaced: list[SubtitleCandidate] = []
    for cand in queue:
        size = probed.get(cand.download_url)
        if size and not cand.size_declared:
            replaced.append(
                SubtitleCandidate(
                    source=cand.source, language=cand.language, title=cand.title,
                    detail_url=cand.detail_url, download_url=cand.download_url,
                    referer=cand.referer, size_declared=size, file_name=cand.file_name,
                )
            )
        else:
            replaced.append(cand)
    return merge_and_rank(replaced)


async def _write_and_record(result: FetchResult, video_path: str, text: str,
                            cand: SubtitleCandidate, meta: dict, module: str | None,
                            movie_id: int | None) -> FetchResult:
    from app.utils.atomic_write import atomic_write_bytes

    target = srt_target_path(video_path)
    parent = target.parent

    def _write() -> None:
        if not parent.is_dir():
            raise FileNotFoundError(str(parent))
        atomic_write_bytes(target, text.encode("utf-8"))

    try:
        await asyncio.to_thread(_write)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[subtitle] 写入失败 %s: %s", target, exc)
        result.ok = False
        result.status = "failed"
        result.reason = FailReason.WRITE_FAILED
        result.message = REASON_MESSAGE[FailReason.WRITE_FAILED]
        return result

    result.ok = True
    result.status = "downloaded"
    result.reason = None
    result.path = str(target)
    result.bytes = len(text.encode("utf-8"))
    result.lines = int(meta.get("lines") or 0)
    result.source = cand.source
    result.source_label = SOURCE_LABEL.get(cand.source, cand.source)
    result.language = cand.language
    result.language_label = cand.language_label
    result.message = f"已下载{cand.language_label}字幕并保存到视频同目录"

    await registry_record(video_path, {
        "code": result.code,
        "path": str(target),
        "source": cand.source,
        "source_label": result.source_label,
        "language": cand.language,
        "bytes": result.bytes,
        "lines": result.lines,
        "status": "downloaded",
        "reason": None,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    await _sync_flags(module, movie_id)
    return result


def _trial_queue(queue: list[SubtitleCandidate], limit: int) -> list[SubtitleCandidate]:
    """截取「最多试几个」，但保证每个源至少有一个候选。

    纯按 rank 截前 N 会出现「一个源的前 3 条都排在前面、另一个源永远轮不到」
    ⇒ 该源一旦整体失败就无候选可回退。这里先各源取头名，再按 rank 补满。
    """
    picked: list[SubtitleCandidate] = []
    seen_sources: set[str] = set()
    for cand in queue:
        if cand.source in seen_sources:
            continue
        seen_sources.add(cand.source)
        picked.append(cand)
        if len(picked) >= limit:
            return picked
    for cand in queue:
        if cand in picked:
            continue
        picked.append(cand)
        if len(picked) >= limit:
            break
    return picked


async def _download_for(code: str, video_path: str, budget: Budget, result: FetchResult,
                        module: str | None, movie_id: int | None) -> FetchResult:
    candidates, errors = await _search_sources(code, budget)
    candidates = [cand for cand in candidates if title_matches_code(cand.title, code)]
    queue = merge_and_rank(candidates)
    result.candidates_total = len(queue)

    if not queue:
        reason = _empty_reason(candidates, errors)
        result.ok = False
        result.status = "failed"
        result.reason = reason
        result.message = REASON_MESSAGE[reason]
        return result

    # 只保留最高语言层（有简体就不试繁体）
    best_rank = max(LANG_RANK.get(cand.language, 0) for cand in queue)
    queue = [cand for cand in queue if LANG_RANK.get(cand.language, 0) == best_rank]
    if len(queue) > 1:
        queue = await _probe_unknown_sizes(queue, budget)

    for cand in _trial_queue(queue, MAX_CANDIDATES_TRY):
        started = time.monotonic()
        attempt = {
            "source": cand.source,
            "language": cand.language,
            "ok": False,
            "reason": None,
            "message": "",
            "elapsed_ms": 0,
        }
        try:
            payload = await SOURCES[cand.source].download(cand, budget=budget)
            text, meta = normalize_srt(payload)
            if not meta.get("blocks"):
                raise DownloadFailed("字幕内容无法解析为标准 SRT")
            result = await _write_and_record(
                result, video_path, text, cand, meta, module, movie_id,
            )
            attempt["ok"] = result.ok
            attempt["reason"] = result.reason.value if result.reason else None
            attempt["message"] = "写入失败" if not result.ok else "下载成功"
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            result.attempts.append(attempt)
            if result.ok:
                return result
        except (asyncio.TimeoutError,):
            attempt["reason"] = FailReason.TIMEOUT.value
            attempt["message"] = "下载超时，已切换下一个候选"
        except SubtitleError as exc:
            attempt["reason"] = getattr(exc, "reason", "download_failed")
            attempt["message"] = str(exc) or "下载失败，已切换下一个候选"
        except Exception as exc:  # noqa: BLE001
            attempt["reason"] = FailReason.DOWNLOAD_FAILED.value
            attempt["message"] = f"下载异常：{type(exc).__name__}"
            logger.info("[subtitle] 候选下载异常 %s: %s", cand.download_url, exc)
        attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        result.attempts.append(attempt)

    reasons = {item.get("reason") for item in result.attempts}
    result.ok = False
    result.status = "failed"
    if reasons and reasons <= {FailReason.TIMEOUT.value}:
        result.reason = FailReason.TIMEOUT
    elif FailReason.WRITE_FAILED.value in reasons:
        result.reason = FailReason.WRITE_FAILED
    else:
        result.reason = FailReason.DOWNLOAD_FAILED
    result.message = REASON_MESSAGE[result.reason]
    return result


async def fetch_for_code(
    code: str,
    *,
    file_path: str,
    overwrite: bool = False,
    budget_s: float = VIDEO_BUDGET_S,
    module: str | None = None,
    movie_id: int | None = None,
) -> FetchResult:
    """跳过 DB 的纯能力入口（脚本/测试用，也是单条端点的内核）。"""
    started = time.monotonic()
    target_code = normalize_code(code) or code_from_path(file_path)

    if not target_code:
        return _failed(FailReason.NO_NUMBER, code or "", elapsed_ms=int((time.monotonic() - started) * 1000),
                       movie_id=movie_id)
    if not file_path:
        return _failed(FailReason.NO_FILE_PATH, target_code,
                       elapsed_ms=int((time.monotonic() - started) * 1000), movie_id=movie_id)

    if not overwrite:
        try:
            exists = await asyncio.to_thread(_has_subtitle, file_path, target_code)
        except Exception:  # noqa: BLE001
            exists = False
        if exists:
            return FetchResult(
                ok=True, status="skipped", movie_id=movie_id, code=target_code,
                reason=FailReason.ALREADY_EXISTS,
                message=REASON_MESSAGE[FailReason.ALREADY_EXISTS],
                path=str(srt_target_path(file_path)),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    result = FetchResult(ok=False, status="failed", movie_id=movie_id, code=target_code)
    budget = Budget.start(budget_s)
    try:
        async with asyncio.timeout(budget_s):
            result = await _download_for(target_code, file_path, budget, result, module, movie_id)
    except (asyncio.TimeoutError, TimeoutError):
        result.ok = False
        result.status = "failed"
        result.reason = FailReason.TIMEOUT
        result.message = REASON_MESSAGE[FailReason.TIMEOUT]
    except Exception as exc:  # noqa: BLE001 - 兜底，绝不 500
        logger.warning("[subtitle] 未预期异常 code=%s: %s", target_code, exc, exc_info=True)
        result.ok = False
        result.status = "failed"
        result.reason = FailReason.DOWNLOAD_FAILED
        result.message = REASON_MESSAGE[FailReason.DOWNLOAD_FAILED]
    result.elapsed_ms = int((time.monotonic() - started) * 1000)
    return result


async def fetch_for_movie(
    module: str,
    movie_id: int,
    *,
    overwrite: bool = False,
    file_path: str | None = None,
    code: str | None = None,
    budget_s: float = VIDEO_BUDGET_S,
) -> FetchResult:
    if module not in SUPPORTED_MODULES:
        raise ValueError(f"不支持的模块: {module}")
    if file_path is None or code is None:
        row = await _load_movie(module, movie_id)
        if row is None:
            raise LookupError("影片不存在")
        code = code or row["code"]
        file_path = file_path or row["file_path"]
    return await fetch_for_code(
        code or "", file_path=file_path or "", overwrite=overwrite,
        budget_s=budget_s, module=module, movie_id=movie_id,
    )


# ---------------------------------------------------------------- 批量
@dataclass
class BatchJob:
    id: str
    module: str
    total: int
    concurrency: int
    overwrite: bool = False
    status: str = "queued"          # queued | running | done | cancelled | failed
    done: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    current: dict | None = None
    items: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel_requested: bool = False

    def eta_seconds(self) -> int | None:
        if self.status != "running" or self.done <= 0:
            return None
        elapsed = time.time() - self.started_at
        per_item = elapsed / self.done
        return int(per_item * max(0, self.total - self.done))

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "module": self.module,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "ok": self.ok,
            "skipped": self.skipped,
            "failed": self.failed,
            "concurrency": self.concurrency,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "eta_seconds": self.eta_seconds(),
            "current": self.current,
            "items": self.items,
        }


_JOBS: dict[str, BatchJob] = {}
_job_seq = 0
_record_lock: asyncio.Lock | None = None
_record_loop: Any = None


class BatchBusy(RuntimeError):
    """同模块已有任务在跑。"""


class BatchEmpty(RuntimeError):
    """没有可处理的影片。"""


def _mutex() -> asyncio.Lock:
    global _record_lock, _record_loop
    loop = asyncio.get_running_loop()
    if _record_lock is None or _record_loop is not loop:
        _record_lock = asyncio.Lock()
        _record_loop = loop
    return _record_lock


def _new_job_id() -> str:
    global _job_seq
    _job_seq += 1
    return f"sb{int(time.time() * 1000):x}{_job_seq:03d}"


def _evict_jobs() -> None:
    finished = [key for key, job in _JOBS.items() if job.status in ("done", "cancelled", "failed")]
    while len(finished) > JOB_HISTORY:
        _JOBS.pop(finished.pop(0), None)


def _active_job(module: str) -> BatchJob | None:
    for job in _JOBS.values():
        if job.module == module and job.status in ("queued", "running"):
            return job
    return None


async def _select_movies(module: str, *, movie_ids: list[int] | None, only_missing: bool,
                         keyword: str | None, code_prefix: str | None, limit: int) -> list[dict]:
    from sqlalchemy import or_, select

    from app.utils.module_helper import get_module_model

    Movie = get_module_model(module, "movie")
    stmt = select(Movie.id, Movie.code, Movie.file_path).where(Movie.file_path.isnot(None))
    if movie_ids:
        stmt = stmt.where(Movie.id.in_(movie_ids))
    if only_missing and hasattr(Movie, "has_subtitle"):
        stmt = stmt.where(or_(Movie.has_subtitle.is_(None), Movie.has_subtitle == 0))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Movie.title.like(like), Movie.code.like(like)))
    if code_prefix:
        stmt = stmt.where(Movie.code.startswith(code_prefix))
    stmt = stmt.order_by(Movie.id.desc()).limit(limit)

    db = _module_db(module)
    session = await db.get_session()
    try:
        rows = (await session.execute(stmt)).all()
    finally:
        await session.close()

    movies = [
        {"id": row[0], "code": row[1] or "", "file_path": row[2] or ""}
        for row in rows
        if row[2]
    ]
    if only_missing and not hasattr(Movie, "has_subtitle"):
        # 无码库没有 has_subtitle 列：按目录实时过滤（每部一次 listdir）
        flags = await asyncio.gather(
            *(asyncio.to_thread(_has_subtitle, item["file_path"], item["code"]) for item in movies),
            return_exceptions=True,
        )
        movies = [item for item, flag in zip(movies, flags) if flag is not True]
    return movies[:limit]


async def _record(job: BatchJob, item: dict) -> None:
    async with _mutex():
        job.done += 1
        status = item.get("status")
        if status == "downloaded":
            job.ok += 1
        elif status == "skipped":
            job.skipped += 1
        else:
            job.failed += 1
        job.items.append(item)
        if len(job.items) > JOB_ITEMS_KEEP:
            del job.items[: len(job.items) - JOB_ITEMS_KEEP]


def _item_of(movie: dict, result: FetchResult | None, reason: FailReason | None = None) -> dict:
    if result is None:
        return {
            "movie_id": movie["id"], "code": movie["code"], "status": "failed",
            "reason": (reason or FailReason.CANCELLED).value,
            "message": REASON_MESSAGE[reason or FailReason.CANCELLED],
            "source": None, "elapsed_ms": 0,
        }
    return {
        "movie_id": movie["id"],
        "code": result.code or movie["code"],
        "status": result.status,
        "reason": result.reason.value if result.reason else None,
        "message": result.message,
        "source": result.source,
        "elapsed_ms": result.elapsed_ms,
    }


async def _run_batch(job: BatchJob, movies: list[dict]) -> None:
    job.status = "running"
    semaphore = asyncio.Semaphore(job.concurrency)
    recorded: set[int] = set()

    async def one(movie: dict) -> None:
        """单部处理；取消时也补一条 cancelled 明细，保证 total = ok+skipped+failed。"""
        try:
            if job.cancel_requested:
                await _record(job, _item_of(movie, None))
                recorded.add(movie["id"])
                return
            async with semaphore:
                if job.cancel_requested:
                    await _record(job, _item_of(movie, None))
                    recorded.add(movie["id"])
                    return
                job.current = {"movie_id": movie["id"], "code": movie["code"], "stage": "下载字幕中"}
                result = await fetch_for_movie(
                    job.module, movie["id"], overwrite=job.overwrite,
                    file_path=movie["file_path"], code=movie["code"],
                )
                await _record(job, _item_of(movie, result))
                recorded.add(movie["id"])
        except asyncio.CancelledError:
            if movie["id"] not in recorded:
                await _record(job, _item_of(movie, None))
                recorded.add(movie["id"])
            raise
        except Exception as exc:  # noqa: BLE001 - 单部失败不影响整批
            logger.warning("[subtitle] 批量单片失败 %s: %s", movie.get("code"), exc)
            await _record(job, {
                "movie_id": movie["id"], "code": movie["code"], "status": "failed",
                "reason": FailReason.DOWNLOAD_FAILED.value,
                "message": REASON_MESSAGE[FailReason.DOWNLOAD_FAILED],
                "source": None, "elapsed_ms": 0,
            })
            recorded.add(movie["id"])

    tasks = {asyncio.create_task(one(movie)): movie for movie in movies}
    pending = set(tasks)
    cancel_deadline: float | None = None
    try:
        # 取消后给在飞的请求最多 8s 收尾，超时直接取消任务，避免前端干等 45s
        while pending:
            done, pending = await asyncio.wait(
                pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                if task.cancelled():
                    continue
                if task.exception() is not None:
                    logger.info("[subtitle] 批量子任务异常: %s", task.exception())
            if job.cancel_requested:
                if cancel_deadline is None:
                    cancel_deadline = time.monotonic() + 8.0
                elif time.monotonic() >= cancel_deadline and pending:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    pending = set()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[subtitle] 批量任务异常 %s: %s", job.id, exc, exc_info=True)
        job.status = "failed"
    finally:
        for task, movie in tasks.items():
            if movie["id"] in recorded:
                continue
            job.current = None
            await _record(job, _item_of(movie, None))
            recorded.add(movie["id"])
            if not task.done():
                task.cancel()
        job.current = None
        if job.status != "failed":
            job.status = "cancelled" if job.cancel_requested else "done"
        job.finished_at = time.time()
        _evict_jobs()


async def start_batch(
    module: str,
    *,
    movie_ids: list[int] | None = None,
    only_missing: bool = True,
    keyword: str | None = None,
    code_prefix: str | None = None,
    limit: int = 200,
    concurrency: int = BATCH_CONCURRENCY_DEFAULT,
    overwrite: bool = False,
) -> dict:
    if module not in SUPPORTED_MODULES:
        raise ValueError(f"不支持的模块: {module}")
    running = _active_job(module)
    if running is not None:
        raise BatchBusy(running.id)

    try:
        limit = int(limit or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, BATCH_LIMIT_MAX))
    try:
        concurrency = int(concurrency or BATCH_CONCURRENCY_DEFAULT)
    except (TypeError, ValueError):
        concurrency = BATCH_CONCURRENCY_DEFAULT
    concurrency = max(BATCH_CONCURRENCY_MIN, min(concurrency, BATCH_CONCURRENCY_MAX))

    movies = await _select_movies(
        module, movie_ids=movie_ids, only_missing=bool(only_missing),
        keyword=(keyword or "").strip() or None,
        code_prefix=(code_prefix or "").strip() or None, limit=limit,
    )
    if not movies:
        raise BatchEmpty("没有符合条件的影片")

    job = BatchJob(
        id=_new_job_id(), module=module, total=len(movies),
        concurrency=concurrency, overwrite=bool(overwrite),
    )
    _JOBS[job.id] = job
    _evict_jobs()
    asyncio.create_task(_run_batch(job, movies))
    return {
        "job_id": job.id,
        "module": module,
        "total": job.total,
        "concurrency": concurrency,
        "message": f"已启动字幕补全，共 {job.total} 部（并发 {concurrency}，站点限速较慢，请勿重复点击）",
    }


def get_batch(job_id: str) -> dict | None:
    job = _JOBS.get(job_id)
    return job.to_dict() if job else None


def latest_batch(module: str) -> dict | None:
    for job in reversed(list(_JOBS.values())):
        if job.module == module:
            return job.to_dict()
    return None


def cancel_batch(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if job is None:
        raise LookupError("任务不存在")
    if job.status in ("queued", "running"):
        job.cancel_requested = True
    return {"job_id": job.id, "status": job.status, "cancelled": job.cancel_requested}
