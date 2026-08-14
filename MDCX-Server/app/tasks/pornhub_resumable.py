"""
PORNHub 扫描 · 断点续扫核心模块
================================

针对 pornhub 模块扫 M:\\N:\\O:\\ 三整盘、被 scan_control 600s 硬超时掐断、
且每次重 walk 整盘导致线程泄漏的根治方案（与 app/tasks/anime_resumable.py
同款机制）。

稳定跑完、绝不中途超时中断的机制
--------------------------------
1) 目录级检查点：已整目录处理完的目录记入 checkpoint，下次运行直接跳过，
   不再重新 os.walk 整棵树（三整盘毫秒级推进）。
2) 分批提交 + 每批落盘 checkpoint：即使被外部 kill / 超时，已提交部分不丢；
   重跑从 checkpoint 幂等续扫（existing_codes 跳过已入库 code）。
3) 剪枝：已处理目录从 walk 的 dirs 中摘除，连其子目录的 listdir 都省掉。
4) 不依赖 HTTP 端点的 wait_for 超时：scan_control / modules 对 pornhub 直接
   await scanner.scan()，整盘扫不完也不会被 600s 掐断，更不会泄漏线程。

用法（应用内）
--------------
    from app.tasks.pornhub_resumable import ResumablePornhubScanner
    scanner = ResumablePornhubScanner(media_dirs, batch_size=200)
    added = await scanner.scan()
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from app.tasks.base_scanner import copy_video_assets_to_data_dir, iter_media_entries, _file_size
from app.tasks.pornhub_scanner import (
    PornhubScanner,
    _split_actor_names,
    extract_pornhub_code,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _default_checkpoint_path() -> Path:
    """默认 checkpoint 落在数据中心目录，便于多进程/服务共享。"""
    try:
        from app.config.manager import get_config_manager
        data_dir = get_config_manager().computed.data_dir
    except Exception:
        data_dir = "data"
    return Path(data_dir) / "pornhub_scan_checkpoint.json"


class ResumablePornhubScanner(PornhubScanner):
    """PORNHub 断点续扫器：目录级 checkpoint + 分批提交 + 已处理目录剪枝。

    复用 PornhubScanner 的落库逻辑（viewkey 提取、演员/国籍解析、
    _get_actor_from_path、_update_actor_counts、_copy_limited）。
    """

    def __init__(
        self,
        media_dirs: list[str],
        checkpoint_path: str | Path | None = None,
        batch_size: int = 200,
        rescan: bool = False,
        data_dir: str | None = None,
    ):
        super().__init__(media_dirs)
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else _default_checkpoint_path()
        self.batch_size = max(1, batch_size)
        self.rescan = rescan
        self.data_dir = data_dir
        self.processed_dirs: set[str] = set()
        self._load_checkpoint()

    def _get_db(self):
        from app.db.module_db import ModuleDatabase
        return ModuleDatabase.get_instance("pornhub")

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
                    logger.info(f"[pornhub-resume] 载入 {len(self.processed_dirs)} 个已处理目录")
                else:
                    logger.warning("[pornhub-resume] media_dirs 变化，忽略旧 checkpoint")
            except Exception as e:  # 半截/损坏 checkpoint 直接忽略，安全重扫
                logger.warning(f"[pornhub-resume] checkpoint 载入失败，重新开始: {e}")
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
        logger.info("[pornhub-resume] checkpoint 已重置")

    # ------------------------------------------------------------------ #
    # scan 模式：本地入库（无网络）
    # ------------------------------------------------------------------ #
    async def scan(self) -> dict:
        """断点续扫：只处理未完成目录，可反复运行。"""
        from app.db.pornhub_models import PornhubActor, PornhubMovie

        results = {
            "total": 0,
            "scanned": 0,
            "matched": 0,
            "movies_added": 0,
            "skipped_dirs": 0,
            "actors_found": {},
            "errors": [],
        }
        if not self.media_dirs:
            results["errors"].append("无有效 media_dir")
            return results

        logger.info(
            f"[pornhub-resume] 断点续扫启动: media_dirs={[str(d) for d in self.media_dirs]}, "
            f"rescan={self.rescan}, checkpoint 已处理目录 {len(self.processed_dirs)} 个"
        )
        db = self._get_db()
        session = await db.get_session()
        try:
            existing_codes: set[str] = set(
                (await session.execute(select(PornhubMovie.code))).scalars().all()
            )
            logger.info(f"[pornhub-resume] 已载入 {len(existing_codes)} 条影片记录")
            for media_dir in self.media_dirs:
                skipped = await self._scan_one_root(session, media_dir, existing_codes, results)
                results["skipped_dirs"] += skipped

            # 同步演员表：新演员写入（正确记录每个演员的国籍）
            for actor_name, actor_nationality in results["actors_found"].items():
                ext_actor = await session.execute(
                    select(PornhubActor).where(PornhubActor.name == actor_name)
                )
                existing_actor = ext_actor.scalar_one_or_none()
                if not existing_actor:
                    session.add(PornhubActor(
                        name=actor_name,
                        nationality=actor_nationality,
                        source="folder",
                        movie_count=1,
                    ))
                elif actor_nationality and not existing_actor.nationality:
                    existing_actor.nationality = actor_nationality
                    existing_actor.movie_count += 1
                else:
                    existing_actor.movie_count += 1

            await session.commit()
            self._save_checkpoint(results["movies_added"])
        except Exception as e:
            logger.error(f"[pornhub-resume] 扫描异常: {e}")
            results["errors"].append(str(e))
        finally:
            await session.close()

        # 重算全部演员作品数（与 PornhubScanner 口径一致：movie.actor LIKE）
        try:
            await self._update_actor_counts()
            logger.info("[pornhub-resume] 演员作品数重算完成")
        except Exception as e:
            logger.warning(f"[pornhub-resume] 演员计数更新失败: {e}")

        results["actors_found"] = list(results["actors_found"].keys())
        if results["errors"]:
            logger.warning(
                f"[pornhub-resume] 扫描结束，共 {len(results['errors'])} 个错误: {results['errors']}"
            )
        return results

    async def _scan_one_root(self, session, media_dir: Path, existing_codes: set[str], results: dict) -> int:
        """遍历一个 media 根目录。返回跳过的已处理目录数。"""
        skipped = 0
        added_before = results["movies_added"]
        logger.info(f"[pornhub-resume] 开始扫描根目录: {media_dir}")
        # 整棵目录树一次性枚举到线程，避免在主事件循环阻塞；网络盘 listdir 走线程池
        walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
        for root, dirs, files in walk_entries:
            root_path = Path(root)
            rel = str(root_path.relative_to(media_dir)).replace("\\", "/")
            if rel == ".":
                rel = ""
            if (not self.rescan) and rel in self.processed_dirs:
                dirs[:] = []          # 剪枝：不再进入已处理子目录（省其子目录 listdir）
                skipped += 1
                continue

            added_here = await self._process_dir(
                session, media_dir, root_path, files, existing_codes, results,
            )
            # 整目录处理完毕 → 标记已处理 + 落盘 checkpoint（断点续扫核心）
            self.processed_dirs.add(rel)
            results["movies_added"] += added_here
            # 分批提交 + 每批保存 checkpoint：被 kill 也不丢已提交部分
            if results["movies_added"] > 0 and results["movies_added"] % self.batch_size == 0:
                await session.commit()
                self._save_checkpoint(results["movies_added"])
                logger.info(f"[pornhub-resume] 分批提交: 已入库 {results['movies_added']} 部")
        logger.info(
            f"[pornhub-resume] 根目录扫描完成: {media_dir} 新增 {results['movies_added'] - added_before} 部, "
            f"跳过已处理目录 {skipped} 个"
        )
        return skipped

    async def _process_dir(self, session, media_dir: Path, root_path: Path, files: list[str],
                           existing_codes: set[str], results: dict) -> int:
        """处理单个目录下的视频文件（落库逻辑与 PornhubScanner._scan_directory 一致）。"""
        from app.db.pornhub_models import PornhubMovie

        added = 0
        actor_name, nationality = self._get_actor_from_path(root_path / "dummy.mp4", media_dir)

        for file_name in files:
            ext = Path(file_name).suffix.lower()
            if ext not in self.video_extensions:
                continue
            results["total"] += 1
            file_path = root_path / file_name

            code = extract_pornhub_code(file_name)
            if not code:
                # 文件名不含 viewkey → 回退用「相对路径」做 code（跨目录同名文件不冲突）
                try:
                    rel_path = file_path.relative_to(media_dir)
                except ValueError:
                    rel_path = Path(file_path.name)
                code = re.sub(r"[^\w\-]", "_", rel_path.with_suffix("").as_posix())
            results["matched"] += 1

            if code in existing_codes:
                continue  # 已存在 → 跳过（幂等续扫）
            existing_codes.add(code)

            new_movie = PornhubMovie(
                code=code,
                title=Path(file_name).stem,
                actor=actor_name,
                file_path=str(file_path),
                file_size=_file_size(file_path),
                status="pending",
            )
            session.add(new_movie)
            added += 1
            results["scanned"] += 1

            if code:
                # 并发受限（防整盘扫描时无限制 ensure_future 风暴拖死事件循环）
                asyncio.ensure_future(
                    self._copy_limited(
                        copy_video_assets_to_data_dir(str(file_path), code, "pornhub")
                    )
                )

            if actor_name:
                for single_name in _split_actor_names(actor_name):
                    results["actors_found"].setdefault(single_name, nationality)

        return added

    async def dry_run(self) -> dict:
        """只读统计：本次运行会处理多少目录/视频、跳过多少已处理目录。不写库。"""
        from app.db.pornhub_models import PornhubMovie

        out = {"dirs_to_process": 0, "videos_to_scan": 0, "skipped_dirs": 0}
        if not self.media_dirs:
            return out
        db = self._get_db()
        session = await db.get_session()
        try:
            existing_codes: set[str] = set(
                (await session.execute(select(PornhubMovie.code))).scalars().all()
            )
            for media_dir in self.media_dirs:
                walk_entries = await asyncio.to_thread(iter_media_entries, media_dir)
                for root, _dirs, files in walk_entries:
                    root_path = Path(root)
                    rel = str(root_path.relative_to(media_dir)).replace("\\", "/")
                    if rel == ".":
                        rel = ""
                    if rel in self.processed_dirs:
                        out["skipped_dirs"] += 1
                        continue
                    out["dirs_to_process"] += 1
                    for file_name in files:
                        if Path(file_name).suffix.lower() not in self.video_extensions:
                            continue
                        code = extract_pornhub_code(file_name)
                        if not code:
                            try:
                                rp = (root_path / file_name).relative_to(media_dir)
                            except ValueError:
                                rp = Path(file_name)
                            code = re.sub(r"[^\w\-]", "_", rp.with_suffix("").as_posix())
                        if code not in existing_codes:
                            out["videos_to_scan"] += 1
        finally:
            await session.close()
        return out
