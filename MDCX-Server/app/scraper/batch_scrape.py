"""
批量刮削闭环（保证「一次性到位」）。

核心能力:
  - 走完整落盘流水线 workflow.persist()（下载封面/背景/预览/NFO + 写库 + movie_actors + Emby 推送）
  - 失败自动重试: 每轮只处理 status=pending 的影片，刮成功的转 completed 退出 pending 池，
    失败的留在池里，下一轮再刮，直到全部成功或达到最大轮数（避免一次跑完若有失败就永远停在 pending）。

仅适用「基于通用引擎 engine.scrape_number(module=...)」的模块:
  jav / fc2 / uncensored / chinese
（pornhub / western / anime 各有专用爬虫，走各自的刮削入口；本 helper 不直接覆盖，
 由 tools/scrape_until_done.py 统一调度。）
"""
import asyncio
import logging

from sqlalchemy import select

from app.scraper.engine import get_scraper_engine
from app.scraper.number import is_valid_ph_viewkey
from app.scraper.workflow import ScraperWorkflow
from app.config.manager import DATA_DIR

logger = logging.getLogger("mdcx.batch_scrape")


async def _ensure_actor_avatars(actors) -> None:
    """best-effort 下载演员头像到本地（与各模块手写实现保持一致的体验）。

    只处理女演员（复用 actor_gender 过滤）；任何异常都吞掉，绝不影响刮削主流程。
    """
    if not actors:
        return
    names = [getattr(a, "name", None) for a in actors if getattr(a, "name", None)]
    if not names:
        return
    try:
        from app.utils.actor_gender import filter_female_only

        female = set(filter_female_only(names))
    except Exception:
        female = set(names)
    try:
        from app.utils.media_helpers import ensure_actor_avatar_local
    except Exception:
        return
    for a in actors:
        name = getattr(a, "name", None)
        if not name or name not in female:
            continue
        try:
            await ensure_actor_avatar_local(name, getattr(a, "avatar_url", None))
        except Exception:
            pass


async def scrape_module_pending(
    module: str,
    db,
    MovieModel,
    status_field: str = "status",
    max_rounds: int = 4,
    limit: int | None = None,
    progress_cb=None,
    concurrency: int = 1,
    use_proxy_pool: bool = False,
):
    """批量刮削某模块所有 pending 影片，刮到完成为止。返回 (success, failed)。

    limit:          单次最多处理多少部（None=不限）
    progress_cb:    每部处理完回调 progress_cb(done, total, code, ok, err)
    concurrency:    并发 worker 数。1 = 串行（保持历史行为）。
    use_proxy_pool: True 时先启动「多出口代理池」，每个 worker 绑定一个独立出口 IP。

    🔴 为什么需要并发（2026-10-14）：
        本项目批量刮削此前是纯串行 ``for m in rows: await scrape(...)``。
        PH 单部耗时实测 0.9~18s（GraphQL 端点约 1~2s，HTML 详情页 3~18s），
        85805 部串行 ⇒ 10 天量级，用户直观感受就是"点了没效果"。
        串行不是出于限流考虑的唯一解 —— 真正的限流是**按出口 IP** 计的，
        所以并发要配合多出口一起上（见 scrape_proxy_pool 模块说明）。
    """
    if concurrency and concurrency > 1:
        return await _scrape_module_pending_concurrent(
            module, db, MovieModel, status_field=status_field,
            max_rounds=max_rounds, limit=limit, progress_cb=progress_cb,
            concurrency=concurrency, use_proxy_pool=use_proxy_pool,
        )

    engine = get_scraper_engine()
    workflow = ScraperWorkflow(str(DATA_DIR / "movies"))
    success = failed = 0
    processed_total = 0

    for rnd in range(1, max_rounds + 1):
        session = await db.get_session()
        try:
            rows = (
                await session.execute(
                    select(MovieModel).where(getattr(MovieModel, status_field) == "pending")
                )
            ).scalars().all()
        finally:
            await session.close()

        if not rows:
            logger.info("[%s] 无待刮削影片，结束", module)
            break

        if limit is not None:
            remain = limit - processed_total
            if remain <= 0:
                logger.info("[%s] 已达本次上限 %s，提前结束", module, limit)
                break
            rows = rows[:remain]

        round_ok = round_fail = 0
        for idx, m in enumerate(rows, 1):
            code = getattr(m, "code", None)
            ok = False
            err = ""
            if not code:
                round_fail += 1
                err = "无番号"
            else:
                try:
                    sr = await engine.scrape_number(code, module=module)
                    if sr and sr.title:
                        sr.code = code  # 强制对齐库中番号，避免源站返回不同写法新建重复记录
                        await workflow.persist(
                            sr,
                            file_path=getattr(m, "file_path", None),
                            module=module,
                            number=code,
                        )
                        await _ensure_actor_avatars(getattr(sr, "actors", None))
                        round_ok += 1
                        ok = True
                    else:
                        round_fail += 1
                        err = "未找到源"
                except Exception as e:
                    logger.warning("[%s] 刮削失败 %s: %s", module, code, e)
                    round_fail += 1
                    err = str(e)[:120]
            processed_total += 1
            if progress_cb:
                try:
                    progress_cb(processed_total, len(rows), code, ok, err)
                except Exception:
                    pass

        success += round_ok
        failed += round_fail
        logger.info("[%s] 第%d轮完成: 成功%d 失败%d (累计成功%s)", module, rnd, round_ok, round_fail, success)
        if round_fail == 0:
            break  # 本轮零失败 => 池已清空，结束
        if limit is not None and processed_total >= limit:
            break

    return success, failed


async def _scrape_module_pending_concurrent(
    module: str,
    db,
    MovieModel,
    status_field: str = "status",
    max_rounds: int = 4,
    limit: int | None = None,
    progress_cb=None,
    concurrency: int = 4,
    use_proxy_pool: bool = False,
):
    """批量刮削的并发实现：每 worker 一个独立出口 + 死片不再重试。

    与串行版的三点差异：
      1. 并发跑 N 个 worker（N = concurrency），worker i 固定用第 i 个出口；
      2. 刮到「源站确认无此资源」的片子 ⇒ 标 ``status='unavailable'``，
         它**不再回到 pending 池**，省掉后续轮次的无谓重试；
      3. 成功率崩塌急停：连续大量失败且无一成功 ⇒ 判定代理/接口整体不可用，
         立刻停批，避免把 8 万部全标成死片（误伤不可逆）。
    """
    engine = get_scraper_engine()
    workflow = ScraperWorkflow(str(DATA_DIR / "movies"))

    exits: list[str] = []
    pool = None
    if use_proxy_pool:
        try:
            from app.services.scrape_proxy_pool import get_scrape_proxy_pool

            pool = get_scrape_proxy_pool()
            exits = await pool.start(max_size=max(concurrency, 4))
        except Exception as e:  # pragma: no cover - 池起不来就退化为单出口
            logger.warning("[%s] 代理池不可用，回退单出口并发: %s", module, e)
            pool = None
            exits = []

    success = failed = 0
    processed_total = 0
    try:
        for rnd in range(1, max_rounds + 1):
            session = await db.get_session()
            try:
                rows = (
                    await session.execute(
                        select(MovieModel).where(
                            getattr(MovieModel, status_field) == "pending"
                        )
                    )
                ).scalars().all()
            finally:
                await session.close()

            if not rows:
                logger.info("[%s] 无待刮削影片，结束", module)
                break

            if limit is not None:
                remain = limit - processed_total
                if remain <= 0:
                    break
                rows = rows[:remain]

            # 🔴 前置过滤：把「根本不是 PH viewkey」的垃圾条目直接标 unavailable。
            #    实测 pending 里有一整块 ``_Channel__pinkloving_*`` 目录名条目
            #    （扫盘时把 [Channel] 文件夹当番号收进来了），它们**永远刮不到**，
            #    却因为没有 ORDER BY 而长期排在查询结果最前面 ⇒ 每次批量任务
            #    都先撞上它们，白跑一整轮还顺带把源喂进熔断。
            batch, junk = [], []
            for m in rows:
                raw = getattr(m, "code", None) or ""
                vk = raw[2:] if raw.startswith("ph") else raw
                if raw and is_valid_ph_viewkey(vk):
                    batch.append((raw, getattr(m, "file_path", None), m))
                else:
                    junk.append(m)
            if junk:
                logger.info("[%s] 第%d轮跳过 %d 条非 viewkey 垃圾条目",
                            module, rnd, len(junk))
                for m in junk:
                    await _mark_unavailable(db, MovieModel, m, status_field)
            if not batch:
                break
            q: asyncio.Queue = asyncio.Queue()
            for item in batch:
                q.put_nowait(item)

            lock = asyncio.Lock()
            stats = {"ok": 0, "fail": 0, "dead": 0, "round_ok": 0, "round_fail": 0}
            errs: dict[str, int] = {}

            async def worker(wid: int) -> None:
                # 🔴 必须声明 nonlocal：worker 内会写 success/failed/processed_total，
                #    不声明会被当成局部变量 → UnboundLocalError（首次读取时崩）。
                nonlocal success, failed, processed_total
                proxy = exits[wid % len(exits)] if exits else None
                client = None
                if proxy:
                    from app.utils.http_client import AsyncHttpClient

                    client = AsyncHttpClient(proxy=proxy)

                while True:
                    try:
                        code, fpath, m = q.get_nowait()
                    except asyncio.QueueEmpty:
                        return

                    ok = False
                    err = ""
                    dead = False
                    if not code:
                        err = "无番号"
                    else:
                        try:
                            from app.scraper.context import ScrapeContext

                            async with ScrapeContext.create(
                                http_client=client
                            ) as ctx:
                                sr = await engine.scrape_number_ctx(
                                    code, ctx, module=module
                                )
                                dead = bool(
                                    getattr(ctx, "resource_unavailable", False)
                                )
                            if sr and getattr(sr, "title", None):
                                sr.code = code
                                await workflow.persist(
                                    sr, file_path=fpath, module=module,
                                    number=code,
                                )
                                await _ensure_actor_avatars(
                                    getattr(sr, "actors", None)
                                )
                                ok = True
                            else:
                                err = "资源不可用" if dead else "未找到源"
                        except Exception as e:  # noqa: BLE001
                            logger.warning("[%s] 刮削失败 %s: %s", module, code, e)
                            err = str(e)[:120]

                    # 🔴 2026-11-06：dead 只代表「有某个源认为这片不存在」，
                    #    不代表整次刮削失败。多源并发时完全可能一个源抛
                    #    ResourceUnavailable、另一个源成功返回完整结果；
                    #    此时上方 workflow.persist 刚把 status 写成 scraped，
                    #    若这里无条件标 unavailable 就会**覆盖成功落盘**
                    #    （观众看到统计成功、库里却查不到数据）。
                    #    只有「确实没刮到 + 源确认不存在」才移出 pending 池。
                    if dead and not ok:
                        await _mark_unavailable(db, MovieModel, m, status_field)

                    async with lock:
                        processed_total_local = processed_total + 1
                        processed_total = processed_total_local
                        if ok:
                            stats["ok"] += 1
                            stats["round_ok"] += 1
                            success += 1
                        else:
                            stats["fail"] += 1
                        if err:
                            errs[err] = errs.get(err, 0) + 1

                    if progress_cb:
                        try:
                            progress_cb(processed_total, len(batch), code, ok, err)
                        except Exception:  # pragma: no cover
                            pass

            n_workers = min(concurrency, len(batch)) or 1
            await asyncio.gather(*[worker(i) for i in range(n_workers)])

            logger.info(
                "[%s] 第%d轮完成(并发%d): 成功%d 失败%d",
                module, rnd, n_workers, stats["round_ok"], len(batch) - stats["round_ok"],
            )

            # 🔴 急停：整批零成功且失败数不小 ⇒ 大概率是代理/接口整体挂了，
            #    而不是 8 万部片恰好都没刮到。此时**绝不能**继续标死片。
            if stats["round_ok"] == 0 and len(batch) >= 5:
                logger.error(
                    "[%s] 第%d轮 %d 部全部失败且零成功，判定代理/接口不可用，停止批量刮削",
                    module, rnd, len(batch),
                )
                break

            failed += len(batch) - stats["round_ok"]
            if stats["round_ok"] == len(batch):
                break
            if limit is not None and processed_total >= limit:
                break
    finally:
        if pool is not None:
            try:
                await pool.stop()
            except Exception:  # pragma: no cover
                pass

    return success, failed


async def _mark_unavailable(db, MovieModel, movie_row, status_field: str) -> None:
    """把「源站确认没有」的片子移出 pending 池。

    ⚠️ 只标记、不删除：置 ``status='unavailable'`` 后它不再被 ``status=='pending'``
       选中（也就不会再消耗重试轮次），但记录仍在，用户可随时改回重刮。
    """
    try:
        session = await db.get_session()
        try:
            obj = await session.get(MovieModel, getattr(movie_row, "id", None))
            if obj is not None:
                setattr(obj, status_field, "unavailable")
                await session.commit()
        finally:
            await session.close()
    except Exception as e:  # pragma: no cover - 标记失败不应影响刮削主流程
        logger.debug("标记 unavailable 失败: %s", e)


async def refill_module_gaps(
    module: str,
    db,
    MovieModel,
    status_field: str = "status",
    max_rounds: int = 3,
    max_items: int = 500,
):
    """补齐「已刮削但落盘不全」的影片（output_dir 下缺 poster.jpg / movie.nfo）。

    返回 (refilled, still_missing)。

    🔴 2026-11-06 修复「批量刮削点了很久没效果」的收尾开销：
      原实现每轮 ``select(...).where(status != 'pending')`` **没有任何过滤**，
      PH 生产库只读实测 9.1 万行（scraped 62095 + unavailable 28757），
      每次批量任务收尾都要把 9 万行全部实例化成 ORM 对象再逐行 Python 判空；
      其中 unavailable 是源站确认不存在的死片，仍会被重新发请求刮一遍，
      既白耗请求，又可能把刚恢复的源再次喂进熔断器。
      现在把筛选下推到 SQL：只看「有 output_dir 且状态不是 pending/unavailable」
      的行并设单次上限，PH 这类 output_dir 多为 NULL 的库直接 0 行、零开销。
    """
    from pathlib import Path

    engine = get_scraper_engine()
    workflow = ScraperWorkflow(str(DATA_DIR / "movies"))
    still_missing: list[str] = []

    status_col = getattr(MovieModel, status_field, None)
    out_col = getattr(MovieModel, "output_dir", None)
    if status_col is None or out_col is None:
        logger.info("[%s] 模型无 status/output_dir 列，跳过补齐", module)
        return True, []

    for rnd in range(1, max_rounds + 1):
        session = await db.get_session()
        try:
            rows = (
                await session.execute(
                    select(MovieModel)
                    .where(
                        status_col != "pending",
                        status_col != "unavailable",
                        out_col.isnot(None),
                        out_col != "",
                    )
                    .limit(max_items)
                )
            ).scalars().all()
        finally:
            await session.close()

        if not rows:
            break
        if len(rows) >= max_items:
            logger.warning(
                "[%s] 补齐候选达到单次上限 %d，本轮只处理前 %d 部（下轮继续）",
                module, max_items, len(rows),
            )

        gaps = []
        for m in rows:
            code = getattr(m, "code", None)
            out = getattr(m, "output_dir", None)
            if not code or not out:
                continue
            d = Path(out)
            poster = d / "poster.jpg"
            nfo = d / "movie.nfo"
            if not poster.exists() or not nfo.exists():
                gaps.append((code, getattr(m, "file_path", None)))

        if not gaps:
            break

        done = 0
        for code, fpath in gaps:
            try:
                sr = await engine.scrape_number(code, module=module)
                if sr and sr.title:
                    sr.code = code
                    await workflow.persist(sr, file_path=fpath, module=module, number=code)
                    done += 1
                else:
                    still_missing.append(code)
            except Exception as e:
                logger.warning("[%s] 补齐失败 %s: %s", module, code, e)
                still_missing.append(code)

        logger.info("[%s] 第%d轮补齐: 完成%d / 缺口%d", module, rnd, done, len(gaps))
        if done == 0:
            break

    return len(still_missing) == 0, still_missing
