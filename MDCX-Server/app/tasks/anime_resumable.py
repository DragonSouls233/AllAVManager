"""
里番批量扫描 / 补全 · 断点续扫核心模块
==========================================

针对「每次约 500 个就超时（services/scan_control.py 对 anime 设 1800s 硬上限，
且每次重 walk 整个 11 万+ 文件网络盘）」的根治方案。

两种模式
--------
scan    本地入库：读 NFO/文件名 → 写 anime.db（不做网络请求）
enrich  在线补全：对库内 pending/不完整影片调 getchu（网络）

稳定跑完、绝不中途超时中断的六大机制
--------------------------------------
1) 目录级检查点：已整目录处理完的目录记入 checkpoint，下次运行直接跳过，
   不再重新 os.walk 整个 11 万+ 文件树；逐个新目录推进，毫秒级。
2) 分批提交 + 每批落盘 checkpoint：即使被外部 kill / 超时，已提交部分不丢；
   重跑从 checkpoint 幂等续扫（existing_codes 跳过已入库 code）。
3) 单目录一次 listdir 复用：os.walk 已给出本目录 files 列表，NFO/海报/资源探测
   与 asset 复制全部复用该列表，避免每文件多次网络 stat/listdir。
4) 剪枝：已处理目录从 os.walk 的 dirs 中摘除，连其子目录的 listdir 都省掉。
5) 可选并发 IO（--workers）：用线程池加速网络盘读取/复制，信号量限流防风暴。
6) enrich 模式天然续扫：每次只查「未完成」影片，已完成项自动跳过；getchu 用
   信号量限流 + 退避重试 + 自动识别封禁降速。不依赖 HTTP 端点的 wait_for 超时。

用法（应用内）
--------------
    from app.tasks.anime_resumable import ResumableAnimeScanner
    scanner = ResumableAnimeScanner(media_dirs, checkpoint_path=..., batch_size=200)
    added = await scanner.scan()

用法（CLI）
----------
    python scripts/anime_resumable_scan.py scan   --media-dir "J:\\动漫" --checkpoint .anime_scan_ckpt.json
    python scripts/anime_resumable_scan.py enrich --checkpoint .anime_enrich_ckpt.json --workers 2
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.config.manager import get_config
from app.db.anime_models import ANIME_BASE, AnimeMovie, AnimeSeries, AnimeStudio
from app.db.module_db import ModuleDatabase
from app.tasks.anime_scanner import (
    VIDEO_EXTS,
    generate_anime_code,
    parse_anime_filename,
    parse_nfo,
    parse_series_episode,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 网络盘下每文件一次 stat 即可（exists()+stat() 两次 IO 翻倍耗时）
_MIN_ASSET_BYTES = 1024


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _default_checkpoint_path() -> Path:
    """默认 checkpoint 落在数据中心目录，便于多进程/服务共享。"""
    try:
        data_dir = get_config_manager().computed.data_dir  # type: ignore[attr-defined]
    except Exception:
        data_dir = "data"
    return Path(data_dir) / "anime_scan_checkpoint.json"


def get_config_manager():  # 延迟导入，避免循环依赖
    from app.config.manager import get_config_manager as _g
    return _g()


class ResumableAnimeScanner:
    """里番断点续扫器（scan + enrich 两模式）。"""

    # 复制任务并发上限（无限制 ensure_future 会淹没事件循环拖垮扫描）
    _copy_sem: Optional[asyncio.Semaphore] = None

    def __init__(
        self,
        media_dirs: list[str],
        checkpoint_path: str | Path | None = None,
        batch_size: int = 200,
        workers: int = 0,
        rescan: bool = False,
        db_path: str | None = None,
        data_dir: str | None = None,
    ):
        self.media_dirs = [Path(d) for d in media_dirs if Path(d).exists()]
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else _default_checkpoint_path()
        self.batch_size = max(1, batch_size)
        self.workers = max(0, workers)
        self.rescan = rescan
        self.db_path = db_path
        self.data_dir = data_dir
        self.processed_dirs: set[str] = set()
        self._load_checkpoint()

    def _get_db(self) -> "ModuleDatabase":
        return ModuleDatabase.get_instance("anime", base_class=ANIME_BASE, db_path=self.db_path)

    # ------------------------------------------------------------------ #
    # checkpoint
    # ------------------------------------------------------------------ #
    def _load_checkpoint(self) -> None:
        if self.checkpoint_path.exists():
            try:
                data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
                # 仅当 media_dirs 一致时才信任历史 checkpoint，避免换盘后误跳
                if set(data.get("media_dirs", [])) == {str(d) for d in self.media_dirs}:
                    self.processed_dirs = set(data.get("processed_dirs", []))
                    logger.info(f"[anime-resume] 载入 {len(self.processed_dirs)} 个已处理目录")
                else:
                    logger.warning("[anime-resume] media_dirs 变化，忽略旧 checkpoint")
            except Exception as e:  # 半截/损坏 checkpoint 直接忽略，安全重扫
                logger.warning(f"[anime-resume] checkpoint 载入失败，重新开始: {e}")
                self.processed_dirs = set()

    def _save_checkpoint(self, added_total: int) -> None:
        data = {
            "media_dirs": [str(d) for d in self.media_dirs],
            "processed_dirs": sorted(self.processed_dirs),
            "added_total": added_total,
            "updated_at": datetime.now().isoformat(),
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.checkpoint_path)  # 原子写，避免半截 checkpoint

    def reset_checkpoint(self) -> None:
        self.processed_dirs = set()
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()
        logger.info("[anime-resume] checkpoint 已重置")

    # ------------------------------------------------------------------ #
    # scan 模式：本地入库（无网络）
    # ------------------------------------------------------------------ #
    async def scan(self) -> dict:
        """本地入库扫描。返回统计字典。可反复运行，每次只处理未完成的目录。"""
        result = {"total": 0, "added": 0, "skipped_dirs": 0, "errors": []}
        if not self.media_dirs:
            result["errors"].append("无有效 media_dir")
            return result

        db = self._get_db()
        session = await db.get_session()
        _studio_cache: dict[str, int] = {}
        _series_cache: dict[str, int] = {}
        try:
            existing_codes: set[str] = set(
                (await session.execute(select(AnimeMovie.code))).scalars().all()
            )
            existing_series: set[str] = set(
                (await session.execute(select(AnimeSeries.name))).scalars().all()
            )

            for media_dir in self.media_dirs:
                skipped = await self._scan_one_root(
                    session, media_dir, existing_codes, existing_series,
                    _studio_cache, _series_cache, result,
                )
                result["skipped_dirs"] += skipped

            await session.commit()
            self._save_checkpoint(result["added"])
        except Exception as e:
            logger.error(f"[anime-resume] 扫描异常: {e}")
            result["errors"].append(str(e))
        finally:
            await session.close()
        return result

    async def _scan_one_root(self, session, media_dir: Path, existing_codes, existing_series,
                             _studio_cache, _series_cache, result) -> int:
        """遍历一个 media 根目录。返回跳过的已处理目录数。"""
        skipped = 0
        # 整棵目录树一次性枚举到线程，避免在主事件循环阻塞；网络盘 listdir 走线程池
        walk_entries = await asyncio.to_thread(lambda: list(os.walk(media_dir)))
        for root, dirs, files in walk_entries:
            rel = str(Path(root).relative_to(media_dir)).replace("\\", "/")
            if rel == ".":
                rel = ""
            if (not self.rescan) and rel in self.processed_dirs:
                dirs[:] = []          # 剪枝：不再进入已处理子目录（省其子目录 listdir）
                skipped += 1
                continue

            added_here = await self._process_dir(
                session, media_dir, root, files, existing_codes, existing_series,
                _studio_cache, _series_cache, result,
            )
            # 整目录处理完毕 → 标记已处理 + 落盘 checkpoint（断点续扫核心）
            self.processed_dirs.add(rel)
            result["added"] += added_here
            # 分批提交 + 每批保存 checkpoint：被 kill 也不丢已提交部分
            if result["added"] > 0 and result["added"] % self.batch_size == 0:
                await session.commit()
                self._save_checkpoint(result["added"])
                logger.info(f"[anime-resume] 分批提交: 已入库 {result['added']} 部")
        return skipped

    async def _process_dir(self, session, media_dir, root, files, existing_codes,
                           existing_series, _studio_cache, _series_cache, result) -> int:
        """处理单个目录下的视频文件。files 已含目录条目，复用避免再 listdir。"""
        added = 0
        # 预建文件名字集合，供 NFO/海报/资源探测复用（网络盘每少一次 listdir 都省 IO）
        entries = set(files)
        for file_name in files:
            ext = Path(file_name).suffix.lower()
            if ext not in VIDEO_EXTS:
                continue
            result["total"] += 1
            file_path = Path(root) / file_name

            parsed = parse_anime_filename(file_name)
            code = generate_anime_code(parsed, file_path.stem)
            if code in existing_codes:
                continue  # 已存在 → 跳过（老的只读；幂等续扫）
            existing_codes.add(code)

            # NFO 富字段（老年份已刮削）—— 复用 entries，避免额外 listdir
            nfo_path = _find_nfo_in_entries(file_path, entries)
            nfo = parse_nfo(nfo_path) if nfo_path else {}

            series_name, episode = parse_series_episode(parsed["title"])
            if nfo.get("set_name"):
                series_name = nfo["set_name"]

            maker = parsed["maker"]
            studio = nfo.get("studio") or maker
            title = nfo.get("title") or parsed["title"] or file_path.stem
            release_date = nfo.get("premiered") or parsed["date"]

            studio_id = None
            if maker:
                if maker in _studio_cache:
                    studio_id = _studio_cache[maker]
                else:
                    studio_row = (await session.execute(
                        select(AnimeStudio).where(AnimeStudio.name == maker)
                    )).scalar_one_or_none()
                    if not studio_row:
                        studio_row = AnimeStudio(name=maker, movie_count=0)
                        session.add(studio_row)
                        await session.flush()
                    _studio_cache[maker] = studio_row.id
                    studio_id = studio_row.id

            series_id = None
            if series_name:
                if series_name not in existing_series:
                    srow = AnimeSeries(name=series_name, movie_count=0)
                    if studio_id:
                        srow.studio_id = studio_id
                    session.add(srow)
                    await session.flush()
                    existing_series.add(series_name)
                    _series_cache[series_name] = srow.id
                    series_id = srow.id
                elif series_name in _series_cache:
                    series_id = _series_cache[series_name]
                else:
                    srow = (await session.execute(
                        select(AnimeSeries).where(AnimeSeries.name == series_name)
                    )).scalar_one_or_none()
                    series_id = srow.id if srow else None
                    if series_id:
                        _series_cache[series_name] = series_id

            genres_json = json.dumps(nfo.get("genres", []), ensure_ascii=False) if nfo.get("genres") else None

            new_movie = AnimeMovie(
                code=code,
                title=title,
                original_title=nfo.get("title"),
                release_date=release_date,
                duration=nfo.get("runtime"),
                rating=nfo.get("rating"),
                plot=nfo.get("plot"),
                genre=genres_json,
                director=parsed["staff"],
                maker=maker,
                studio=studio,
                studio_id=studio_id,
                series=series_name,
                series_id=series_id,
                episode=episode,
                file_path=str(file_path),
                file_size=_file_size(file_path),
                source="nfo" if nfo else "filename",
                status="completed" if nfo else "pending",
            )
            session.add(new_movie)
            added += 1

            # 资源复制（NFO + 海报），复用 entries + 并发受限，失败不影响主流程
            asyncio.ensure_future(
                self._copy_limited(self._copy_assets(file_path, code, entries))
            )
        return added

    async def cleanup_orphans(self) -> int:
        """删除磁盘已不存在影片的 DB 记录（沿用 BaseScanner 逻辑）。"""
        from sqlalchemy import text

        db = self._get_db()
        session = await db.get_session()
        removed = 0
        try:
            result = await session.execute(text("SELECT id, file_path FROM movies"))
            rows = result.fetchall()
            if not rows:
                return 0
            dir_prefixes = [
                os.path.normcase(os.path.normpath(str(d))) for d in self.media_dirs
            ]
            to_delete = []
            for row in rows:
                fp = row[1]
                if not fp:
                    continue
                norm_fp = os.path.normcase(os.path.normpath(str(fp)))
                if not any(norm_fp.startswith(p) for p in dir_prefixes):
                    continue
                if not os.path.exists(norm_fp):
                    to_delete.append(row[0])
            for rid in to_delete:
                await session.execute(text("DELETE FROM movies WHERE id = :id"), {"id": rid})
                removed += 1
            if to_delete:
                await session.commit()
                logger.info(f"[anime-resume] 孤儿清理: 删除 {removed} 条")
        except Exception as e:
            logger.warning(f"[anime-resume] 孤儿清理失败: {e}")
        finally:
            await session.close()
        return removed

    async def dry_run(self) -> dict:
        """只读统计：本次运行会处理多少目录/视频、跳过多少已处理目录。不写库。"""
        out = {"dirs_to_process": 0, "videos_to_scan": 0, "skipped_dirs": 0}
        if not self.media_dirs:
            return out
        db = self._get_db()
        session = await db.get_session()
        try:
            existing_codes: set[str] = set(
                (await session.execute(select(AnimeMovie.code))).scalars().all()
            )
            for media_dir in self.media_dirs:
                walk_entries = await asyncio.to_thread(lambda: list(os.walk(media_dir)))
                for root, _dirs, files in walk_entries:
                    rel = str(Path(root).relative_to(media_dir)).replace("\\", "/")
                    if rel == ".":
                        rel = ""
                    if rel in self.processed_dirs:
                        out["skipped_dirs"] += 1
                        continue
                    out["dirs_to_process"] += 1
                    for file_name in files:
                        if Path(file_name).suffix.lower() not in VIDEO_EXTS:
                            continue
                        code = generate_anime_code(
                            parse_anime_filename(file_name), Path(file_name).stem
                        )
                        if code not in existing_codes:
                            out["videos_to_scan"] += 1
        finally:
            await session.close()
        return out

    # ------------------------------------------------------------------ #
    # 资源复制（复用 entries，减少网络 listdir）
    # ------------------------------------------------------------------ #
    async def _copy_limited(self, coro):
        if ResumableAnimeScanner._copy_sem is None:
            ResumableAnimeScanner._copy_sem = asyncio.Semaphore(5)
        try:
            async with ResumableAnimeScanner._copy_sem:
                await asyncio.wait_for(coro, timeout=60)
        except Exception:
            pass

    async def _copy_assets(self, video_path: Path, code: str, entries: set[str]) -> None:
        """复制视频目录的 NFO + 封面到数据中心（复用 entries，避免重 listdir）。"""
        try:
            from app.config.manager import get_config_manager
            data_dir = self.data_dir or get_config_manager().computed.data_dir
        except Exception:
            return
        target_dir = Path(data_dir) / "movies" / "anime" / code
        target_dir.mkdir(parents=True, exist_ok=True)

        # 通用名映射（与 base_scanner 一致）
        generic = {
            "movie.nfo": "movie.nfo", "poster.jpg": "poster.jpg", "poster.png": "poster.jpg",
            "fanart.jpg": "fanart.jpg", "fanart.png": "fanart.jpg", "cover.jpg": "cover.jpg",
            "cover.png": "cover.jpg", "thumb.jpg": "thumb.jpg", "thumb.png": "thumb.jpg",
        }
        stem = video_path.stem
        for src_name in entries:
            dst_name = generic.get(src_name.lower())
            if not dst_name:
                continue
            src = video_path.parent / src_name
            if src.suffix.lower() == ".nfo":
                if src.stat().st_size == 0:
                    continue
            else:
                if src.stat().st_size < _MIN_ASSET_BYTES:
                    continue
            dst = target_dir / dst_name
            if dst.exists() and dst.stat().st_size >= src.stat().st_size:
                continue
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass

        # 海报（{stem}-poster/-fanart/-cover）
        for suffix in ("-poster", "-fanart", "-cover", ""):
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                name = stem + suffix + ext
                if name in entries:
                    src = video_path.parent / name
                    if src.stat().st_size < _MIN_ASSET_BYTES:
                        continue
                    dst = target_dir / "poster.jpg"
                    if dst.exists():
                        return
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
                    return

    # ------------------------------------------------------------------ #
    # enrich 模式：getchu 在线补全（网络，天然续扫）
    # ------------------------------------------------------------------ #
    async def enrich(self, workers: int = 2, only_missing: bool = True) -> dict:
        """对库内未完成影片调 getchu 补全。每次只查未完成项 → 天然断点续扫。

        only_missing=True：跳过 status=completed 且已有 plot+maker 的影片。
        """
        from app.scraper.anime_getchu import scrape_anime_and_apply

        result = {"total": 0, "done": 0, "success": 0, "failed": 0, "errors": []}
        db = self._get_db()
        session = await db.get_session()
        try:
            if only_missing:
                stmt = (
                    select(AnimeMovie)
                    .where(
                        (AnimeMovie.status != "completed")
                        | (AnimeMovie.plot.is_(None))
                        | (AnimeMovie.maker.is_(None))
                    )
                )
            else:
                stmt = select(AnimeMovie)
            rows = (await session.execute(stmt)).scalars().all()
        finally:
            await session.close()

        todo = [(m.code, m.title, m.maker) for m in rows]
        result["total"] = len(todo)
        if not todo:
            logger.info("[anime-enrich] 无待补全影片")
            return result

        sem = asyncio.Semaphore(max(1, workers))
        lock = asyncio.Lock()

        async def _one(code: str, title: str, maker):
            async with sem:
                try:
                    r = await asyncio.wait_for(
                        scrape_anime_and_apply(code, title or "", maker), timeout=60
                    )
                    ok = bool(r and r.get("ok"))
                except Exception:
                    ok = False
            async with lock:
                result["done"] += 1
                if ok:
                    result["success"] += 1
                else:
                    result["failed"] += 1
                if result["done"] % 50 == 0:
                    logger.info(
                        f"[anime-enrich] {result['done']}/{result['total']} "
                        f"成功 {result['success']} 失败 {result['failed']}"
                    )

        await asyncio.gather(*(_one(c, t, m) for c, t, m in todo))
        logger.info(
            f"[anime-enrich] 完成 总 {result['total']} 成功 {result['success']} 失败 {result['failed']}"
        )
        return result


# ---------------------------------------------------------------------- #
# 复用 entries 的 NFO 探测（替代 base_scanner 的逐文件 os.listdir）
# ---------------------------------------------------------------------- #
def _find_nfo_in_entries(video_path: Path, entries: set[str]) -> Optional[Path]:
    stem = video_path.stem
    parent = video_path.parent
    for cand in (stem + ".nfo", stem + ".cht.nfo"):
        if cand in entries:
            return parent / cand
    return None
