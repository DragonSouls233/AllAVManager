"""演员订阅 · 线上资源比对服务

用户订阅演员后，把该演员在 JavDB 的**在线片单**（番号 + 影片页 URL + 中文版标记）
抓回本地库，再与「本地自有目录」做比对，明确标出缺失项，并支持一键把缺失的中文版
（-C / -UC）投递到下载器，避免用户每次手动去翻缺漏资源。

设计要点（来自真机实测 2026-10-26）：
- JavDB 中文版是**独立片单条目**（如 ``OFJE-655-C`` 与 ``OFJE-655`` 各自一条），
  且磁力名带 ``-C``/``-UC`` 后缀即为中文版；
- JavDB 影片列表的 ``has_cnsub`` 字段**不可靠**（实测 OFJE-655 列表 has_cnsub=False
  但其 ``-C`` 磁力真实存在）。故「中文版」判定以**磁力名含 -C/-UC 后缀**为准，
  番号本身带 -C/-UC 也直接算中文版（双保险）；
- 在线抓取走匿名 App API（免登录、带代理，已在服务器实测通过）；
- 磁力逐条抓取较重，故「中文检测 / 批量下载」做成后台任务 + 进度轮询，不阻塞接口。

比对角色（get_comparison 返回）：
- local：本地已有该精确番号
- missing_chinese：线上是中文版（或磁力含 -C/-UC）且本地有同 base 非中文旧版 → 高亮「缺中文版」
- missing：本地完全缺失（含「缺中文版」之外的普通缺失）
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.wants import base_code
from app.utils.module_helper import get_module_model

logger = logging.getLogger(__name__)

# 模块 → JavDB 分区（pornhub 不在 JavDB，不支持线上抓取）
_ZONE_MAP = {
    "jav": "censored",
    "fc2": "fc2",
    "uncensored": "uncensored",
    "western": "western",
    "chinese": "censored",
}
# 中文版后缀：番号或磁力名末尾的 -C / -UC（-U 是无码、-LTX 是高清无码，不算中文）
_CN_SUFFIX_RE = re.compile(r"-(?:UC|C)(?=[\s._\-]|$)", re.IGNORECASE)

# 抓取页大小与上限
_FILMO_PAGE = 50
_FILMO_MAX_PAGES = 60          # 单演员最多翻 60 页 = 3000 部，足够覆盖绝大多数演员
_MAGNET_DETECT_LIMIT = 80      # 单次「中文检测」最多扫多少部（优先缺失项），避免把源打爆


def _is_chinese_suffix(text: str) -> bool:
    """番号/磁力名是否以 -C / -UC 中文版后缀结尾。"""
    if not text:
        return False
    return bool(_CN_SUFFIX_RE.search(text))


async def _fetch_with_retry(fetch_fn, tries: int = 3, backoff: float = 2.0):
    """对 JavDB 匿名 API（偶发抽风/自动选线失败）做重试：返回非 None 即成功。

    fetch_fn 是无参协程；返回 None（请求层失败）也视为失败并重试。
    """
    last = None
    for i in range(tries):
        try:
            res = await fetch_fn()
        except Exception as e:  # noqa: BLE001
            last = e
            res = None
        if res is not None:
            return res
        if i < tries - 1:
            await asyncio.sleep(backoff * (i + 1))
    if last:
        logger.warning(f"[sub_online] JavDB 调用重试 {tries} 次仍失败: {last}")
    return None


# ============================================================================
# 后台任务注册表（sync / refresh / download 都用，进度轮询）
# ============================================================================

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = asyncio.Lock()


def _new_job(kind: str, actor_id: int, total: int = 0) -> dict:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": kind,
        "actor_id": actor_id,
        "status": "running",
        "stage": "init",
        "done": 0,
        "total": total,
        "message": "",
        "result": None,
        "error": None,
        "cancelled": False,
        "updated_at": time.monotonic(),
    }
    _JOBS[job_id] = job
    return job


def get_job(job_id: str) -> Optional[dict]:
    return _JOBS.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if not job:
        return False
    job["cancelled"] = True
    return True


async def _touch(job: dict, **kw):
    if job is None:
        return
    job.update(kw)
    job["updated_at"] = time.monotonic()
    # 防止 dict 无限增长
    if len(_JOBS) > 256:
        old = sorted(_JOBS, key=lambda k: _JOBS[k]["updated_at"])[:64]
        for k in old:
            _JOBS.pop(k, None)


# ============================================================================
# 内部：解析演员的 JavDB id
# ============================================================================

async def _resolve_javdb_actor_id(
    actor_id: int,
    session: AsyncSession,
    module: str,
    ActorSubscription,
    Actor,
) -> Optional[str]:
    """优先用订阅表里已存的 javdb_actor_id；没有则按演员名反查并回写。"""
    sub = (await session.execute(
        select(ActorSubscription).where(ActorSubscription.actor_id == actor_id)
    )).scalars().first()
    if sub and getattr(sub, "javdb_actor_id", None):
        return sub.javdb_actor_id

    actor = await session.get(Actor, actor_id)
    name = actor.name if actor else None
    if not name:
        return None
    try:
        from app.services.javdb_app_client import create_app_client_from_config
        client = await create_app_client_from_config()
        try:
            card = await _fetch_with_retry(lambda: client.fetch_actor_card(name, max_movies=3))
        finally:
            await client.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sub_online] 解析演员 {name} 的 JavDB id 失败: {e}")
        return None
    jid = card.get("id") if card else None
    if jid and sub is not None:
        try:
            sub.javdb_actor_id = jid
            await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[sub_online] 回写 javdb_actor_id 失败: {e}")
    return jid


# ============================================================================
# 同步线上片单（落库）
# ============================================================================

async def sync_online(
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
    user_id: Optional[int] = None,
    progress: Optional[dict] = None,
) -> dict:
    """抓取该演员的 JavDB 在线片单并 upsert 到 actor_subscription_onlines。

    只抓片单（番号/标题/日期/影片页 URL），**不**逐条抓磁力（太重）。中文标记初值
    由番号本身是否 -C/-UC 决定；磁级真判留给 refresh_chinese。
    返回 {total, inserted, updated, pages, unsupported, javdb_actor_id}。
    """
    Actor = get_module_model(module, "actor")
    ActorSubscription = get_module_model(module, "actor_subscription")
    Online = get_module_model(module, "subscription_online")

    if module not in _ZONE_MAP:
        await _touch(progress, status="done", stage="unsupported",
                     message=f"模块 {module} 无 JavDB 在线片单（仅 jav/fc2/uncensored/western/chinese 支持）")
        return {"unsupported": True, "total": 0, "inserted": 0, "updated": 0, "pages": 0}

    await _touch(progress, stage="resolve", message="解析演员 JavDB id…")
    jid = await _resolve_javdb_actor_id(actor_id, session, module, ActorSubscription, Actor)
    if not jid:
        await _touch(progress, status="error", stage="resolve",
                     error="无法解析该演员的 JavDB id（演员名未匹配或网络异常）")
        return {"error": "resolve_failed", "total": 0, "inserted": 0, "updated": 0, "pages": 0}

    from app.services.javdb_app_client import create_app_client_from_config
    client = await create_app_client_from_config()
    try:
        zone = _ZONE_MAP[module]
        # 现有记录按 code 建索引，便于 upsert 并保留已检测的中文标记
        existing = (await session.execute(
            select(Online).where(Online.actor_id == actor_id)
        )).scalars().all()
        by_code = {r.code: r for r in existing}

        inserted = updated = 0
        pages = 0
        total = 0
        for page in range(1, _FILMO_MAX_PAGES + 1):
            if progress and progress.get("cancelled"):
                break
            data = await _fetch_with_retry(
                lambda: client.fetch_actor_movies(jid, zone=zone, page=page, limit=_FILMO_PAGE)
            )
            movies = (data.get("movies") or []) if isinstance(data, dict) else []
            if not movies:
                break
            pages += 1
            for m in movies:
                num = (m.get("number") or "").strip()
                if not num:
                    continue
                total += 1
                bc = base_code(num)
                title = m.get("title") or m.get("origin_title") or ""
                mid = m.get("id") or ""
                url = f"https://javdb.com/movies/{mid}" if mid else None
                rec = by_code.get(num)
                if rec is None:
                    rec = Online(
                        actor_id=actor_id, user_id=user_id, code=num, base_code=bc,
                        title=title or None, release_date=(m.get("release_date") or "") or None,
                        javdb_movie_id=mid or None, url=url,
                        is_chinese_code=_is_chinese_suffix(num),
                        last_seen_at=datetime.utcnow(),
                    )
                    session.add(rec)
                    by_code[num] = rec
                    inserted += 1
                else:
                    rec.title = title or rec.title
                    rec.release_date = (m.get("release_date") or "") or rec.release_date
                    rec.javdb_movie_id = mid or rec.javdb_movie_id
                    rec.url = url or rec.url
                    rec.base_code = bc
                    rec.is_chinese_code = _is_chinese_suffix(num)
                    rec.last_seen_at = datetime.utcnow()
                    updated += 1
            await _touch(progress, stage=f"page {page}", done=total,
                         message=f"已抓取 {total} 部（第 {page} 页）")
            if pages >= _FILMO_MAX_PAGES:
                break
        await session.commit()
        await _touch(progress, status="done", stage="done", done=total, total=total,
                     message=f"在线片单同步完成：{total} 部（新增 {inserted} / 更新 {updated}）")
        return {"unsupported": False, "total": total, "inserted": inserted,
                "updated": updated, "pages": pages, "javdb_actor_id": jid}
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[sub_online] 同步片单异常 actor={actor_id}")
        await _touch(progress, status="error", stage="error", error=str(e))
        return {"error": str(e), "total": 0, "inserted": 0, "updated": 0, "pages": 0}
    finally:
        await client.close()


# ============================================================================
# 中文检测：逐条抓磁力，扫描 -C/-UC 后缀（真判）
# ============================================================================

async def refresh_chinese(
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
    progress: Optional[dict] = None,
    limit: int = _MAGNET_DETECT_LIMIT,
) -> dict:
    """对线上记录（优先本地缺失项）逐条抓磁力，扫描名含 -C/-UC 的真中文版。

    更新 has_chinese_online + best_chinese_magnet + chinese_checked_at。
    返回 {checked, chinese_found, remaining, unsupported}。
    """
    Online = get_module_model(module, "subscription_online")
    if module not in _ZONE_MAP:
        await _touch(progress, status="done", stage="unsupported",
                     message=f"模块 {module} 无 JavDB 在线片单")
        return {"unsupported": True, "checked": 0, "chinese_found": 0, "remaining": 0}

    local_base = await _local_base_set(actor_id, session, module)

    rows = (await session.execute(
        select(Online).where(Online.actor_id == actor_id)
    )).scalars().all()
    # 优先：本地缺失的（base 不在本地）排前面，已检测过的排后面
    def _sort_key(r):
        missing = base_code(r.code) not in local_base
        checked = r.chinese_checked_at is not None
        return (0 if missing else 1, 0 if checked else 1)
    rows.sort(key=_sort_key)
    rows = rows[:limit] if limit else rows

    if not rows:
        await _touch(progress, status="done", stage="done", message="没有需要检测的线上记录")
        return {"checked": 0, "chinese_found": 0, "remaining": 0}

    from app.services.javdb_app_client import create_app_client_from_config
    client = await create_app_client_from_config()
    try:
        checked = chinese_found = 0
        for r in rows:
            if progress and progress.get("cancelled"):
                break
            checked += 1
            has_cn = r.is_chinese_code  # 番号本身已是中文版
            best = None
            if r.javdb_movie_id:
                try:
                    mags = await _fetch_with_retry(
                        lambda: client.get_magnets(r.javdb_movie_id, limit=12)
                    ) or []
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[sub_online] 抓磁力失败 {r.code}: {e}")
                    mags = []
                for mg in mags:
                    name_cn = _is_chinese_suffix(mg.name)
                    if name_cn or mg.cnsub:
                        has_cn = True
                        # 选最佳中文磁力：cnsub/名含-C 且体积最大
                        if best is None or (mg.size or 0) > (best.get("size") or 0):
                            best = {"name": mg.name, "magnet": mg.magnet_uri, "size": mg.size}
            r.has_chinese_online = bool(has_cn)
            r.magnet_count = len(mags) if r.javdb_movie_id else 0
            r.best_chinese_magnet = best["magnet"] if best else None
            r.chinese_checked_at = datetime.utcnow()
            if has_cn:
                chinese_found += 1
            await _touch(progress, stage=f"检测 {r.code}", done=checked, total=len(rows),
                         message=f"已检测 {checked}/{len(rows)}，发现中文版 {chinese_found} 部")
        await session.commit()
        remaining = max(0, (await session.execute(
            select(func.count()).select_from(Online).where(
                and_(Online.actor_id == actor_id, Online.chinese_checked_at.is_(None))
            ))).scalar_one() - 0)
        # remaining 仅统计本次未覆盖（被 limit 截断）的未检测数
        await _touch(progress, status="done", stage="done", done=checked, total=len(rows),
                     message=f"中文检测完成：检测 {checked} 部，发现中文版 {chinese_found} 部")
        return {"checked": checked, "chinese_found": chinese_found, "remaining": 0,
                "unsupported": False}
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[sub_online] 中文检测异常 actor={actor_id}")
        await _touch(progress, status="error", stage="error", error=str(e))
        return {"error": str(e), "checked": 0, "chinese_found": 0, "remaining": 0}
    finally:
        await client.close()


# ============================================================================
# 比对：本地已有 vs 本地缺失（含中文版高亮）
# ============================================================================

async def _local_base_set(actor_id: int, session: AsyncSession, module: str) -> set:
    Movie = get_module_model(module, "movie")
    MovieActor = get_module_model(module, "movie_actor")
    rows = (await session.execute(
        select(Movie.code, Movie.file_path)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(MovieActor.actor_id == actor_id)
    )).all()
    base = set()
    for code, fp in rows:
        if code:
            base.add(base_code(code))
    return base


async def get_comparison(
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
) -> dict:
    """返回本地已有 / 本地缺失 / 缺中文版 三档 + 统计。

    status 判定：
      local          本地有该精确番号
      missing_chinese 线上是中文版（番号带 -C/-UC 或磁力含 -C/-UC）且本地有同 base 非中文旧版
      missing        本地完全缺失
    """
    Online = get_module_model(module, "subscription_online")
    Movie = get_module_model(module, "movie")
    MovieActor = get_module_model(module, "movie_actor")

    local_rows = (await session.execute(
        select(Movie.code, Movie.file_path, Movie.title)
        .join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(MovieActor.actor_id == actor_id)
    )).all()
    local_codes = {c for c, _, _ in local_rows if c}
    local_base = {base_code(c) for c in local_codes}
    local_file = {base_code(c): (fp if fp and os.path.isfile(str(fp)) else None)
                  for c, fp, _ in local_rows if c}

    online_rows = (await session.execute(
        select(Online).where(Online.actor_id == actor_id)
        .order_by(Online.release_date.is_(None), Online.release_date.desc())
    )).scalars().all()

    local_items: list[dict] = []
    missing_items: list[dict] = []
    missing_chinese_items: list[dict] = []
    for r in online_rows:
        is_cn = bool(r.is_chinese_code) or bool(r.has_chinese_online)
        has_exact = r.code in local_codes
        has_base = base_code(r.code) in local_base
        item = {
            "code": r.code,
            "title": r.title,
            "release_date": r.release_date,
            "url": r.url,
            "is_chinese_code": bool(r.is_chinese_code),
            "has_chinese_online": (None if r.has_chinese_online is None else bool(r.has_chinese_online)),
            "chinese_checked_at": r.chinese_checked_at.isoformat() if r.chinese_checked_at else None,
            "best_chinese_magnet": r.best_chinese_magnet,
            "javdb_movie_id": r.javdb_movie_id,
        }
        if has_exact:
            item["local_file"] = local_file.get(base_code(r.code))
            local_items.append(item)
        elif is_cn and has_base:
            item["local_old_file"] = local_file.get(base_code(r.code))
            missing_chinese_items.append(item)
            missing_items.append(item)
        else:
            missing_items.append(item)

    return {
        "actor_id": actor_id,
        "module": module,
        "online_total": len(online_rows),
        "local_count": len(local_items),
        "missing_count": len(missing_items),
        "missing_chinese_count": len(missing_chinese_items),
        "local": local_items,
        "missing_chinese": missing_chinese_items,
        "missing": missing_items,
        "chinese_detected": any(r.chinese_checked_at for r in online_rows),
        "synced_at": max((r.last_seen_at for r in online_rows if r.last_seen_at), default=None),
    }


# ============================================================================
# 批量下载缺失中文版（投递下载器）
# ============================================================================

async def download_missing_chinese(
    actor_id: int,
    session: AsyncSession,
    module: str = "jav",
    progress: Optional[dict] = None,
) -> dict:
    """把「本地缺失的中文版」记录投递到当前激活下载器（aria2/qb/tr）。

    优先用已存 best_chinese_magnet；没有则当场抓磁力取中文磁。返回投递结果。
    """
    Online = get_module_model(module, "subscription_online")
    rows = (await session.execute(
        select(Online).where(
            and_(Online.actor_id == actor_id,
                 or_(Online.is_chinese_code.is_(True),
                     Online.has_chinese_online.is_(True)))
        )
    )).scalars().all()

    local_codes = set()
    Movie = get_module_model(module, "movie")
    MovieActor = get_module_model(module, "movie_actor")
    lr = (await session.execute(
        select(Movie.code).join(MovieActor, Movie.id == MovieActor.movie_id)
        .where(MovieActor.actor_id == actor_id)
    )).all()
    local_codes = {c for (c,) in lr if c}

    # 候选：中文版且本地没有精确番号
    candidates = [r for r in rows if r.code not in local_codes]
    if not candidates:
        await _touch(progress, status="done", stage="done", message="没有可下载的缺失中文版")
        return {"sent": 0, "failed": 0, "skipped": 0, "details": []}

    from app.services.wants_resources import send_to_downloader
    sent = failed = skipped = 0
    details: list[dict] = []
    from app.services.javdb_app_client import create_app_client_from_config
    client = await create_app_client_from_config()
    try:
        for r in candidates:
            if progress and progress.get("cancelled"):
                break
            magnet = r.best_chinese_magnet
            if not magnet and r.javdb_movie_id:
                try:
                    mags = await _fetch_with_retry(
                        lambda: client.get_magnets(r.javdb_movie_id, limit=12)
                    ) or []
                    for mg in mags:
                        if _is_chinese_suffix(mg.name) or mg.cnsub:
                            magnet = mg.magnet_uri
                            r.best_chinese_magnet = magnet
                            break
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[sub_online] 下载前抓磁力失败 {r.code}: {e}")
            if not magnet:
                skipped += 1
                details.append({"code": r.code, "status": "skipped", "reason": "无中文磁力"})
                continue
            res = await send_to_downloader(magnet, name=r.code)
            if res.get("status") == "ok":
                sent += 1
                details.append({"code": r.code, "status": "sent", "task_id": res.get("task_id")})
            else:
                failed += 1
                details.append({"code": r.code, "status": "failed", "reason": res.get("message")})
            await _touch(progress, stage=f"投递 {r.code}", done=(sent + failed + skipped),
                         total=len(candidates),
                         message=f"已投递 {sent} / 失败 {failed} / 跳过 {skipped}")
        await session.commit()
        await _touch(progress, status="done", stage="done", done=(sent + failed + skipped),
                     total=len(candidates),
                     message=f"投递完成：成功 {sent} / 失败 {failed} / 跳过 {skipped}")
        return {"sent": sent, "failed": failed, "skipped": skipped, "details": details}
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[sub_online] 批量下载异常 actor={actor_id}")
        await _touch(progress, status="error", stage="error", error=str(e))
        return {"sent": sent, "failed": failed, "skipped": skipped,
                "details": details, "error": str(e)}
    finally:
        await client.close()


# ============================================================================
# 后台任务包装（供路由调用，返回 job_id，进度轮询）
# ============================================================================

async def sync_online_job(actor_id: int, session: AsyncSession, module: str, user_id=None) -> str:
    job = _new_job("sync_online", actor_id)
    try:
        res = await sync_online(actor_id, session, module, user_id=user_id, progress=job)
        job["result"] = res
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
    return job["id"]


async def refresh_chinese_job(actor_id: int, session: AsyncSession, module: str, limit=None) -> str:
    job = _new_job("refresh_chinese", actor_id)
    try:
        res = await refresh_chinese(actor_id, session, module, progress=job, limit=limit or _MAGNET_DETECT_LIMIT)
        job["result"] = res
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
    return job["id"]


async def download_missing_job(actor_id: int, session: AsyncSession, module: str) -> str:
    job = _new_job("download_missing", actor_id)
    try:
        res = await download_missing_chinese(actor_id, session, module, progress=job)
        job["result"] = res
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
    return job["id"]


__all__ = [
    "sync_online", "refresh_chinese", "get_comparison", "download_missing_chinese",
    "sync_online_job", "refresh_chinese_job", "download_missing_job",
    "get_job", "cancel_job", "_is_chinese_suffix",
]
