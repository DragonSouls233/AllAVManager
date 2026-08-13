"""
日本里番 · 指定目录刮削后台服务

供 anime_routes 的 POST /anime/scrape-dir 调用。

设计要点：
- 只对「用户指定目录」（如 J:\\动漫\\2026）下的影片发起 getchu 网络刮削，
  天然不波及 1999~2025 的全部内容。
- 仅刮削已扫描入库（库中存在 code）的影片；未入库的跳过（提示先扫描）。
- only_missing=True 时进一步跳过已完整刮削（status=completed 且有 plot/maker）的影片。
- 并发限流 + 单任务超时，best-effort：单部失败不中断整体。
- 进程内维护 _JOBS 进度字典，由 GET /anime/scrape-dir/{job_id}/status 查询。
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from app.db.anime_models import AnimeMovie
from app.db.module_db import ModuleDatabase
from app.scraper.anime_getchu import scrape_anime_and_apply
from app.tasks.anime_scanner import (
    VIDEO_EXTS,
    generate_anime_code,
    parse_anime_filename,
)
from app.tasks.base_scanner import iter_media_entries
from app.utils.logger import get_logger

logger = get_logger(__name__)

_JOBS: dict[str, dict] = {}
_CONCURRENCY = 5  # 目录刮削并发上限（getchu 内部还有 Semaphore(2) 二次限流）


def get_anime_dir_scrape_status(job_id: str) -> Optional[dict]:
    """查询目录刮削任务进度；不存在返回 None。"""
    return _JOBS.get(job_id)


async def run_anime_dir_scrape(job_id: str, directory: str, only_missing: bool) -> None:
    """遍历 directory 下的 anime 影片，逐部调 getchu 刮削（后台协程）。"""
    _JOBS[job_id] = {
        "job_id": job_id,
        "directory": directory,
        "status": "running",
        "total": 0,
        "done": 0,
        "success": 0,
        "failed": 0,
        "skipped_not_scanned": 0,
        "skipped_complete": 0,
        "current": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "errors": [],
    }
    try:
        # 1) 收集目录下所有视频 → (code, title, maker)
        walk_entries = await asyncio.to_thread(iter_media_entries, Path(directory))
        candidates = []
        for root, _dirs, files in walk_entries:
            for file_name in files:
                ext = Path(file_name).suffix.lower()
                if ext not in VIDEO_EXTS:
                    continue
                parsed = parse_anime_filename(file_name)
                code = generate_anime_code(parsed, Path(file_name).stem)
                title = parsed["title"] or Path(file_name).stem
                candidates.append((code, title, parsed.get("maker")))

        # 2) 查库：已扫描入库的影片 code → (status, has_plot, has_maker)
        db = ModuleDatabase.get_instance("anime")
        session = await db.get_session()
        try:
            rows = (
                await session.execute(
                    select(AnimeMovie.code, AnimeMovie.status, AnimeMovie.plot, AnimeMovie.maker)
                )
            ).all()
        finally:
            await session.close()
        info = {c: (st, bool(plot), bool(mk)) for c, st, plot, mk in rows}

        # 3) 过滤：仅库内 + （only_missing 时）跳过已完整刮削
        to_scrape = []
        skipped_not_scanned = 0
        skipped_complete = 0
        for code, title, maker in candidates:
            rec = info.get(code)
            if not rec:
                skipped_not_scanned += 1
                continue
            st, has_plot, has_maker = rec
            if only_missing and st == "completed" and has_plot and has_maker:
                skipped_complete += 1
                continue
            to_scrape.append((code, title, maker))

        _JOBS[job_id]["total"] = len(to_scrape)
        _JOBS[job_id]["skipped_not_scanned"] = skipped_not_scanned
        _JOBS[job_id]["skipped_complete"] = skipped_complete

        if not to_scrape:
            _JOBS[job_id]["status"] = "completed"
            logger.info(
                f"[anime-scrape] 目录 {directory} 无需要刮削的影片"
                f"（未扫描入库 {skipped_not_scanned}，已完整跳过 {skipped_complete}）"
            )
            return

        # 4) 并发刮削（限流 + 单任务超时，best-effort）
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def _one(code: str, title: str, maker):
            async with sem:
                try:
                    _JOBS[job_id]["current"] = code
                    r = await asyncio.wait_for(
                        scrape_anime_and_apply(code, title or "", maker),
                        timeout=60,
                    )
                    if r.get("ok"):
                        _JOBS[job_id]["success"] += 1
                    else:
                        _JOBS[job_id]["failed"] += 1
                except Exception as e:  # 单部失败不中断整体
                    _JOBS[job_id]["failed"] += 1
                    _JOBS[job_id]["errors"].append(f"{code}: {e}")
                finally:
                    _JOBS[job_id]["done"] += 1
                    _JOBS[job_id]["current"] = None

        await asyncio.gather(*(_one(c, t, m) for c, t, m in to_scrape))
        _JOBS[job_id]["status"] = "completed"
        logger.info(
            f"[anime-scrape] 目录 {directory} 刮削完成："
            f"总 {len(to_scrape)}，成功 {_JOBS[job_id]['success']}，"
            f"失败 {_JOBS[job_id]['failed']}，未扫描入库跳过 {skipped_not_scanned}"
        )
    except Exception as e:
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["errors"].append(str(e))
        logger.error(f"[anime-scrape] 目录刮削异常 {directory}: {e}")
    finally:
        _JOBS[job_id]["finished_at"] = datetime.now().isoformat()
