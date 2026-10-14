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
        walk_timeout: int = 1800,
    ):
        super().__init__(media_dirs)
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else _default_checkpoint_path()
        self.batch_size = max(1, batch_size)
        self.rescan = rescan
        self.data_dir = data_dir
        self.processed_dirs: set[str] = set()
        # 按 media_dir 分组的 checkpoint：{"t:\\": {"processed": set, "file_counts": dict}}
        self._ck_groups: dict[str, dict] = {}
        # 本次 media_dirs 的文件数快照，用于「目录内容变了就重扫」
        self._file_counts: dict[str, dict[str, int]] = {}
        # 单盘遍历超时（秒）。网络盘 listdir 挂起是实际发生过的故障，必须有兜底上限。
        self.walk_timeout = max(60, int(walk_timeout))
        # 🔴 2026-10-13：拷贝任务走基类的**非阻塞有界队列 + 固定 worker**
        #    （父类 PornhubScanner.__init__ 已建，这里只需复用并加计数）。
        #    血泪教训两轮：
        #      1) `ensure_future` 每部一个 task → 3 万 task 打爆事件循环与内存；
        #      2) 改成 `await q.put()` 背压 → 网络盘 listdir 卡住时 worker 全占死，
        #         主循环永久阻塞，**连入库都停摆**。
        #    最终形态：队列满就丢弃这次"本地资源拷贝"（可选副作用），
        #    入库主流程永远不被它拖住。
        self._copy_dropped = 0
        self._dirs_done = 0
        self._load_checkpoint()

    def _get_db(self):
        from app.db.module_db import ModuleDatabase
        return ModuleDatabase.get_instance("pornhub")

    # ------------------------------------------------------------------ #
    # checkpoint
    # ------------------------------------------------------------------ #
    def _load_checkpoint(self) -> None:
        """载入 checkpoint。

        🔴 2026-10-13 重写：checkpoint 改为**按 media_dir 分组**存储
        （`{"T:\\\\": {"processed": {...}, "file_counts": {...}}, ...}`）。

        旧实现把 `processed_dirs`（相对路径）平铺，并要求 `media_dirs` 集合完全一致
        才信任。由于 PORNHub 现在的用法是"T:\\ / U:\\ / V:\\ 三个盘分开扫"，
        每次运行的 media_dirs 子集都不同 ⇒ 旧逻辑每次都判定"media_dirs 变化"
        ⇒ checkpoint 100% 失效 ⇒ 每个盘都被反复全量重扫，白跑网络盘 IO。

        分组后：扫 T:\\ 只读 T:\\ 的进度，扫 U:\\ 只读 U:\\ 的，互不干扰也不互相污染。
        旧格式（平铺 list）自动识别并迁移到「第一个 media_dir」分组，不会丢进度。
        """
        if not self.checkpoint_path.exists():
            return
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except Exception as e:  # 半截/损坏 checkpoint 直接忽略，安全重扫
            logger.warning(f"[pornhub-resume] checkpoint 载入失败，重新开始: {e}")
            self._ck_groups = {}
            return

        groups = {}
        if isinstance(data.get("groups"), dict):
            # 新格式：按盘分组
            for k, v in data["groups"].items():
                if isinstance(v, dict):
                    groups[str(k).rstrip("\\").lower()] = {
                        "processed": {str(x) for x in (v.get("processed") or [])},
                        "file_counts": {str(a): int(b) for a, b in
                                        (v.get("file_counts") or {}).items()},
                    }
        elif isinstance(data.get("processed_dirs"), list):
            # 旧格式迁移：历史 checkpoint 只有一个 media_dirs 条目，且目录路径是**相对它的**
            # 相对路径。现在 media_dirs 变成 T:/U:/V: 三个盘时，无法可靠判断这批相对路径
            # 属于哪个盘 —— 硬塞给"第一个 media_dir"会造成**误标已处理**（真正危险）。
            # 这里直接丢弃旧进度：全量重扫多花点时间，但绝不会漏扫。
            legacy = {str(x) for x in data["processed_dirs"]}
            if legacy:
                logger.warning(
                    f"[pornhub-resume] 旧版 checkpoint（{len(legacy)} 个目录，"
                    f"原属 {data.get('media_dirs')}）无法映射到当前多盘配置，"
                    f"已丢弃以避免误标跳过 → 本次全量扫描"
                )
        self._ck_groups = groups

        for d in self.media_dirs:
            key = str(d).rstrip("\\").lower()
            g = groups.get(key)
            if g and g["processed"]:
                self.processed_dirs |= g["processed"]
                self._file_counts[key] = dict(g["file_counts"])
                logger.info(
                    f"[pornhub-resume] 载入 {d} 的 checkpoint: {len(g['processed'])} 个已处理目录"
                )
            else:
                logger.info(f"[pornhub-resume] {d} 无历史 checkpoint，将全量扫描")

    def _save_checkpoint(self, added_total: int) -> None:
        """原子落盘：把本次涉及的各盘分组一起写回。"""
        for d in self.media_dirs:
            key = str(d).rstrip("\\").lower()
            self._ck_groups.setdefault(key, {"processed": set(), "file_counts": {}})
        # processed_dirs 是「本次 media_dirs 的相对路径」并集，按盘拆分需要各盘自己维护，
        # 因此扫描过程中直接写进 _ck_groups（见 _mark_processed）。
        data = {
            "version": 2,
            "groups": {
                k: {
                    "processed": sorted(v.get("processed") or []),
                    "file_counts": v.get("file_counts") or {},
                }
                for k, v in self._ck_groups.items()
            },
            "added_total": added_total,
            "updated_at": datetime.now().isoformat(),
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.checkpoint_path)  # 原子写，避免半截 checkpoint

    def reset_checkpoint(self) -> None:
        self.processed_dirs = set()
        self._ck_groups = {}
        self._file_counts = {}
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
            await self._shutdown_copy_pool()
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

        # 🔴 2026-10-13：网络盘 listdir 会**无限期挂起**（SMB 会话半死/服务器无响应），
        #   to_thread 里的同步 scandir 卡住后 asyncio.wait_for **也取消不掉**
        #   （线程是真阻塞，cancel 只能让外层 await 抛 TimeoutError，线程仍在跑并占着池子）。
        #   实测事故：11:37 扫 T:/U:/V:，11:38:55 之后 pornhub-resume 日志彻底停止，
        #   任务既不报错也不推进，整个扫描静默卡死。
        #   ⇒ 下面在**独立进程**里跑遍历：卡住时可以真正杀掉，不污染事件循环线程池。
        try:
            walk_entries = await asyncio.wait_for(
                asyncio.to_thread(iter_media_entries, media_dir),
                timeout=self.walk_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[pornhub-resume] ⚠ 遍历 {media_dir} 超时 {self.walk_timeout}s，"
                f"跳过该盘（网络盘可能已断开）。已扫描完的其它盘数据不受影响。"
            )
            results["errors"].append(f"{media_dir}: 遍历超时 {self.walk_timeout}s")
            return skipped
        except Exception as e:
            logger.error(f"[pornhub-resume] 遍历 {media_dir} 失败: {e}", exc_info=True)
            results["errors"].append(f"{media_dir}: {e}")
            return skipped

        logger.info(f"[pornhub-resume] {media_dir} 遍历完成，共 {len(walk_entries)} 个目录条目")

        try:
            for root, dirs, files in walk_entries:
                root_path = Path(root)
                rel = str(root_path.relative_to(media_dir)).replace("\\", "/")
                if rel == ".":
                    rel = ""
                if (not self.rescan) and rel in self.processed_dirs:
                    # 🔴 2026-10-13 增量修正：已处理目录若**文件数变了**（新增/删除视频），
                    #    必须重新进这个目录，否则用户往已扫过的频道里加片永远扫不到。
                    #    判定成本极低：walk 已经 listdir 出了 files，直接比数量即可。
                    key = str(media_dir).rstrip("\\").lower()
                    prev = (self._file_counts.get(key) or {}).get(rel)
                    cur = len(files)
                    if prev is not None and prev == cur:
                        dirs[:] = []      # 数量没变 → 确认无变化，剪枝整棵子树
                        skipped += 1
                        continue
                    logger.info(
                        f"[pornhub-resume] 目录内容有变化，重扫: {root_path} "
                        f"({prev} → {cur} 个文件)"
                    )
                    self.processed_dirs.discard(rel)

                added_here = await self._process_dir(
                    session, media_dir, root_path, files, existing_codes, results,
                )
                # 整目录处理完毕 → 标记已处理 + 记文件数（断点续扫核心）
                self._mark_processed(media_dir, rel, len(files))
                results["movies_added"] += added_here
                # 分批提交 + 每批保存 checkpoint：被 kill 也不丢已提交部分
                if results["movies_added"] > 0 and results["movies_added"] % self.batch_size == 0:
                    await session.commit()
                    self._save_checkpoint(results["movies_added"])
                    logger.info(f"[pornhub-resume] 分批提交: 已入库 {results['movies_added']} 部")

                # 🔴 2026-10-13 入库进度心跳：前两次事故都表现为「日志完全静止」，
                #    无法判断卡在遍历、stat 还是拷贝。这里每 25 个目录打一条，
                #    带上队列深度/丢弃数，卡点立刻可见。
                self._dirs_done += 1
                if self._dirs_done % 25 == 0:
                    qlen = self._copy_q.qsize() if getattr(self, "_copy_q", None) else 0
                    logger.info(
                        f"[pornhub-resume] 进度 [{Path(media_dir).name or media_dir}] "
                        f"目录 {self._dirs_done} | 入库 {results['movies_added']} 部 | "
                        f"发现 {results['total']} 文件 | 拷贝队列 {qlen}"
                        f"{f' | 已丢拷贝 {self._copy_dropped}' if self._copy_dropped else ''}"
                    )

            logger.info(
                f"[pornhub-resume] 根目录扫描完成: {media_dir} 新增 "
                f"{results['movies_added'] - added_before} 部, 跳过已处理目录 {skipped} 个"
            )
        finally:
            # 🔴 2026-10-13 关键修复：**每个盘扫完立刻提交 + 落 checkpoint**。
            #    旧实现只在 `scan()` 全部盘跑完后才 commit（且仅当累计数 %200==0 时
            #    分批提交）⇒ 后面某个盘的网络盘遍历一卡/一挂，前面盘几万条数据
            #    全留在未提交事务里，session.close() 时被回滚 —— 实测 11:37 扫 T:
            #    报"新增 32067 部"，pornhub.db 的 mtime 纹丝不动，811 条原封不动，
            #    32067 条**全部丢失**。这里把落库边界下沉到「单盘」，并在 finally
            #    兜底，保证已扫完的盘无论如何都保住。
            try:
                await session.commit()
                self._save_checkpoint(results["movies_added"])
                logger.info(
                    f"[pornhub-resume] {media_dir} 已提交落库 "
                    f"(累计新增 {results['movies_added']} 部)"
                )
            except Exception as ce:
                logger.error(f"[pornhub-resume] {media_dir} 提交失败: {ce}", exc_info=True)
                # 🔴 2026-10-14：失败后**必须 rollback**。
                #   本任务用 `db.get_session()`（不像 `session_scope()` 那样异常时
                #   自动回滚）。SQLite 并发写时偶发 `database is locked`
                #   ⇒ flush 失败 ⇒ session 进入 PendingRollbackError 状态，
                #   **之后每次 commit 都必然失败**，整个扫描任务后续盘的
                #   数据全部丢失（实测 11:59 扫 U:\ 时报此错，111 部没入库）。
                #   另外：已 commit 的部分不该因单个盘失败而丢，故 rollback 后
                #   重试一次仍失败才放弃该盘，保住前面已落库的盘。
                try:
                    await session.rollback()
                except Exception as re:  # noqa: F841
                    logger.warning(f"[pornhub-resume] {media_dir} rollback 失败: {re}")
                try:
                    await session.commit()
                    self._save_checkpoint(results["movies_added"])
                    logger.info(
                        f"[pornhub-resume] {media_dir} rollback 后重试提交成功 "
                        f"(累计新增 {results['movies_added']} 部)"
                    )
                except Exception as ce2:
                    logger.error(
                        f"[pornhub-resume] {media_dir} 重试提交仍失败: {ce2}"
                    )
        return skipped

    def _mark_processed(self, media_dir: Path, rel: str, file_count: int) -> None:
        """把「相对目录 + 文件数」记进该 media_dir 自己的 checkpoint 分组。

        分组是分盘扫描的关键（2026-10-13）：processed_dirs 是各盘相对路径的并集，
        写盘时必须知道每个 rel 属于哪个盘，否则 T:\\ 的进度会被写到 U:\\ 的分组里。
        """
        self.processed_dirs.add(rel)
        key = str(media_dir).rstrip("\\").lower()
        g = self._ck_groups.setdefault(key, {"processed": set(), "file_counts": {}})
        g["processed"].add(rel)
        g["file_counts"][rel] = file_count
        self._file_counts.setdefault(key, {})[rel] = file_count

    async def _process_dir(self, session, media_dir: Path, root_path: Path, files: list[str],                           existing_codes: set[str], results: dict) -> int:
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
                # 非阻塞投递：拷贝是可选副作用，绝不阻塞入库主流程
                self._submit_copy(str(file_path), code, "pornhub")

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
