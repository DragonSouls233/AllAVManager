"""
PORNHUB 演员头像补全 · 服务端内置任务
====================================

替代原来在服务器上用 schtasks 跑的独立脚本 `_backfill_actor_avatar.py`。

设计要点（用户要求：必须内置服务端，不能单独跑脚本）：
- 通过 API 触发（POST /api/v1/pornhub/actors/avatar-fill），在服务进程内后台运行；
- 单实例锁（进程内 `_running` 标识），重复触发直接拒绝，不会双开；
- 覆盖**全部**演员（不限 2000），按「本地文件是否存在且有效」判缺，
  幂等续跑（已有有效头像的直接跳过），即使中途被杀，重触发从缺头像处继续；
- 每 50 位一个事务（避免挤爆服务器自己的 PH 扫描，实测曾导致 database is locked）；
- 进度通过模块级单例 `_fill_state` 暴露，GET /actors/avatar-fill/status 可查。

🔴 2026-10-14：原独立脚本的并发双开 + 逐条 commit 曾两次搞崩服务（见 MEMORY.md）。
   内置后由服务进程统一管理，天然单实例，且只在服务运行时存在，重启后需手动再触发。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 进程内单例：跨请求共享进度与运行状态
_fill_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "done": 0,
    "success": 0,
    "skipped": 0,
    "no_source": 0,
    "failed": 0,
    "last_actor": "",
    "last_update": 0,
}

# 保活后台任务引用（避免被 GC）
_fill_task: Optional[asyncio.Task] = None


def get_avatar_fill_status() -> dict:
    """返回当前进度快照（只读副本）。"""
    return dict(_fill_state)


async def run_pornhub_avatar_fill(write: bool = True, batch_size: int = 50) -> dict:
    """在服务进程内运行头像补全，覆盖全部演员。返回最终统计。

    write=False 仅统计（不下载/不写库），便于先看清缺口规模。
    """
    global _fill_state

    if _fill_state["running"]:
        return {"status": "already_running", "state": dict(_fill_state)}

    _fill_state = {
        "running": True,
        "started_at": time.time(),
        "finished_at": None,
        "total": 0,
        "done": 0,
        "success": 0,
        "skipped": 0,
        "no_source": 0,
        "failed": 0,
        "last_actor": "",
        "last_update": time.time(),
    }
    try:
        from app.db.pornhub_models import PornhubActor
        from app.db.module_db import ModuleDatabase
        from sqlalchemy import select

        from app.scraper.pornhub_actor_scraper import (
            AVATAR_DIR,
            _valid_avatar_file,
            scrape_actor_profile,
        )
        # 延迟 import，避免 pornhub_routes ↔ 本模块循环依赖
        from app.api.routes.pornhub_routes import _store_pornhub_actor_avatar

        db = ModuleDatabase.get_instance("pornhub")
        session = await db.get_session()
        try:
            actors = (await session.execute(select(PornhubActor))).scalars().all()
            _fill_state["total"] = len(actors)
            logger.info("[avatar-fill] 启动，共 %d 位演员", len(actors))

            for act in actors:
                _fill_state["last_actor"] = act.name
                _fill_state["last_update"] = time.time()

                # 本地已有有效头像 → 跳过（幂等续跑核心）
                local = Path(AVATAR_DIR) / f"actor_{act.id}.jpg"
                if local.exists() and _valid_avatar_file(local):
                    _fill_state["skipped"] += 1
                    _fill_state["done"] += 1
                    continue

                if not write:
                    # 仅统计缺口
                    _fill_state["no_source"] += 1
                    _fill_state["done"] += 1
                    continue

                # 刮 profile 拿头像（源内：PORNHUB 自己的页面，不碰 javdb）
                avatar_url: Optional[str] = None
                try:
                    profile = await scrape_actor_profile(act.name, act.nationality,
                                                        profile_url=act.profile_url)
                    if profile and profile.avatar_url:
                        avatar_url = profile.avatar_url
                except Exception as e:
                    logger.debug(
                        "[avatar-fill] 刮削失败 %s: %s", act.name, type(e).__name__
                    )

                # 落盘（内部已含 pornhub 默认占位图过滤）
                local_path = await _store_pornhub_actor_avatar(act, avatar_url, act.name)
                if local_path:
                    _fill_state["success"] += 1
                elif avatar_url:
                    # 有源地址但下载/落盘失败（被封/超时）
                    _fill_state["failed"] += 1
                else:
                    # 源里没有该演员的头像 → 留空，不猜（不污染）
                    _fill_state["no_source"] += 1

                _fill_state["done"] += 1

                # 每 batch_size 位提交一次，缩小写锁窗口
                if _fill_state["done"] % batch_size == 0:
                    await session.commit()
                    logger.info(
                        "[avatar-fill] 进度 %d/%d 成功 %d 无源 %d 失败 %d",
                        _fill_state["done"], _fill_state["total"],
                        _fill_state["success"], _fill_state["no_source"],
                        _fill_state["failed"],
                    )
                # 轻微限速，避免对 pornhub 与服务器自身扫描造成冲击
                await asyncio.sleep(0.2)

            if write:
                await session.commit()
        finally:
            await session.close()

        logger.info(
            "[avatar-fill] 完成: 总数 %d 成功 %d 跳过 %d 无源 %d 失败 %d",
            _fill_state["total"], _fill_state["success"], _fill_state["skipped"],
            _fill_state["no_source"], _fill_state["failed"],
        )
        return {"status": "completed", "state": dict(_fill_state)}
    except Exception as e:
        logger.exception("[avatar-fill] 异常终止: %s", e)
        return {"status": "error", "error": str(e), "state": dict(_fill_state)}
    finally:
        _fill_state["running"] = False
        _fill_state["finished_at"] = time.time()
        _fill_state["last_update"] = time.time()


async def _run_wrapper(write: bool) -> None:
    """后台包装：吞掉异常，避免未处理异常导致 task 警告。"""
    try:
        await run_pornhub_avatar_fill(write=write)
    except Exception:
        logger.exception("[avatar-fill] 后台任务异常")


def start_avatar_fill_task(write: bool = True) -> str:
    """触发头像补全（进程内单实例）。返回 'started' 或 'already_running'。"""
    global _fill_task
    if _fill_state["running"]:
        return "already_running"
    _fill_task = asyncio.create_task(_run_wrapper(write))
    return "started"
