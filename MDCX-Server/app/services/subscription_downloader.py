"""
自动搜索订阅下载服务（v4.1）

职责：
- 定时检查订阅（演员 + 系列的新片）
- 番号搜索（qBittorrent search engine，若下载器支持）
- 自动下载（依据订阅的 auto_download / preferred_quality 配置）
- 完成回调由下载器自身的事件机制处理（自动整理 + 刮削 + 入库 + 通知）

设计要点：
- 复用 downloader_manager 与 actor_subscription / series_subscription 的检测逻辑
- 全异步；后台任务用 get_module_session 获取会话
- 服务在 app.main lifespan 中启动/停止
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.config.manager import get_config
from app.utils.module_helper import get_module_model, get_module_session

logger = logging.getLogger(__name__)


class SubscriptionDownloaderService:
    """订阅自动下载服务"""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

    # ============== 生命周期 ==============

    async def start(self):
        """启动定时检查"""
        config = get_config()
        if not config.subscription_downloader.enabled:
            logger.info("订阅自动下载服务未启用（subscription_downloader.enabled=False）")
            return

        self._running = True
        interval = config.subscription_downloader.check_interval_minutes * 60
        self._task = asyncio.create_task(self._run_loop(interval))
        logger.info(
            f"订阅自动下载服务已启动，检查间隔 {config.subscription_downloader.check_interval_minutes} 分钟"
        )

    async def stop(self):
        """停止"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("订阅自动下载服务已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    # ============== 内部循环 ==============

    async def _run_loop(self, interval: int):
        """定时循环"""
        # 启动后先等一个间隔，避免与 lifespan 其他启动逻辑抢资源
        await asyncio.sleep(min(interval, 60))
        while self._running:
            try:
                await self.check_all_subscriptions()
            except Exception as e:
                logger.error(f"订阅检查失败: {e}", exc_info=True)
            await asyncio.sleep(interval)

    # ============== 对外接口 ==============

    async def check_all_subscriptions(self, module: str = "jav"):
        """检查所有订阅（演员 + 系列），并处理自动下载"""
        session = await get_module_session(module)

        # 检查演员订阅新片
        try:
            from app.services.actor_subscription import check_all_subscriptions
            await check_all_subscriptions(session, module=module)
        except Exception as e:
            logger.error(f"演员订阅检测失败: {e}", exc_info=True)

        # 检查系列订阅新片
        try:
            from app.services.series_subscription import check_all_series_subscriptions
            await check_all_series_subscriptions(module=module)
        except Exception as e:
            logger.error(f"系列订阅检测失败: {e}", exc_info=True)

        # 处理自动下载
        try:
            await self._process_auto_downloads(module=module)
        except Exception as e:
            logger.error(f"自动下载处理失败: {e}", exc_info=True)

    async def _process_auto_downloads(self, module: str = "jav"):
        """处理启用了 auto_download 的订阅：搜索并下载最新影片"""
        now = datetime.utcnow()
        session = await get_module_session(module)
        MovieModel = get_module_model(module, "movie")
        MovieActorModel = get_module_model(module, "movie_actor")
        ActorSubscriptionModel = get_module_model(module, "actor_subscription")
        SeriesSubscriptionModel = get_module_model(module, "series_subscription")

        # ---- 演员订阅 ----
        actor_subs = await session.execute(
            select(ActorSubscriptionModel).where(ActorSubscriptionModel.auto_download == True)  # noqa: E712
        )
        for sub in actor_subs.scalars():
            try:
                # 获取该演员最新影片（按创建时间倒序，取一部）
                movies_stmt = (
                    select(MovieModel)
                    .join(MovieActorModel, MovieModel.id == MovieActorModel.movie_id)
                    .where(MovieActorModel.actor_id == sub.actor_id)
                    .order_by(MovieModel.created_at.desc())
                    .limit(1)
                )
                movie = (await session.execute(movies_stmt)).scalars().first()
                if not movie:
                    continue
                # 仅对自上次检查之后新增的影片触发下载
                if sub.last_checked_at is not None and movie.created_at and movie.created_at <= sub.last_checked_at:
                    continue
                quality = sub.preferred_quality or get_config().subscription_downloader.preferred_quality_default
                await self._search_and_download(movie.code, quality)
                sub.last_checked_at = now
                sub.last_movie_count += 1
            except Exception as e:
                logger.error(f"演员订阅自动下载失败 actor_id={sub.actor_id}: {e}", exc_info=True)

        # ---- 系列订阅 ----
        series_subs = await session.execute(
            select(SeriesSubscriptionModel).where(SeriesSubscriptionModel.auto_download == True)  # noqa: E712
        )
        for sub in series_subs.scalars():
            try:
                movies_stmt = (
                    select(MovieModel)
                    .where(MovieModel.series_id == sub.series_id)
                    .order_by(MovieModel.created_at.desc())
                    .limit(1)
                )
                movie = (await session.execute(movies_stmt)).scalars().first()
                if not movie:
                    continue
                if sub.last_checked_at is not None and movie.created_at and movie.created_at <= sub.last_checked_at:
                    continue
                quality = sub.preferred_quality or get_config().subscription_downloader.preferred_quality_default
                await self._search_and_download(movie.code, quality)
                sub.last_checked_at = now
                sub.last_movie_count += 1
            except Exception as e:
                logger.error(f"系列订阅自动下载失败 series_id={sub.series_id}: {e}", exc_info=True)

        await session.commit()

    async def _search_and_download(self, code: str, quality: str = "1080p"):
        """搜索并下载指定番号"""
        try:
            from app.services.downloader_manager import downloader_manager
            downloader = downloader_manager.get_active()
            if not downloader:
                logger.warning(f"无可用下载器，跳过 {code}")
                return

            # 优先用下载器自带 search（若将来有下载器实现）；否则走聚合搜索。
            # 🔴 2026-10-20：qb/tr/aria2 三个下载器都没实现 search（基类也没定义），
            #    旧代码到此 always 落「不支持搜索」分支 ⇒ 订阅自动下载是死功能。
            #    改走 AggregateSearcher（内置 sukebei 源，代理走唯一入口
            #    get_effective_proxy_url），让链路真正活过来。
            if hasattr(downloader, "search"):
                results = await downloader.search(code)
            else:
                from app.services.aggregate_searcher import create_default_searcher

                searcher = create_default_searcher()
                agg = await searcher.search(code)
                results = [
                    {
                        "name": r.name,
                        "magnet": r.magnet,
                        "size": r.size,
                        "seeders": r.seeders,
                        "source": r.source,
                    }
                    for r in agg.results
                ]
                if agg.errors:
                    logger.debug(f"聚合搜索部分源失败 {code}: {agg.errors}")
            if not results:
                logger.info(f"搜索无结果: {code}")
                return
            # 排除已试：下载器现有任务的 hash 集合（qb 的 id=hash、tr 的 id=hashString）
            tried_hashes: set[str] = set()
            try:
                for t in await downloader.list_tasks():
                    h = str(t.get("id") or "").lower()
                    if h:
                        tried_hashes.add(h)
            except Exception as e:
                logger.debug(f"读取下载器任务列表失败（不影响选优）: {e}")
            best = self._select_best_torrent(results, quality, tried_hashes=tried_hashes)
            if not best:
                logger.info(f"未找到合适资源: {code}")
                return
            magnet = best.get("magnet") or best.get("url") or best.get("torrent_url")
            if not magnet:
                logger.warning(f"搜索结果缺少磁力链/URL: {code}")
                return
            await downloader.add_torrent(magnet, name=code)
            logger.info(f"已添加下载: {code} (来源: {best.get('name', '?')})")
        except Exception as e:
            logger.error(f"搜索下载失败 {code}: {e}", exc_info=True)

    def _select_best_torrent(
        self,
        results: list,
        quality: str,
        tried_hashes: Optional[set[str]] = None,
    ) -> Optional[dict]:
        """选择最佳种子：infohash 去重 + 排除已试 + magnet_score 五维打分。

        🔴 2026-10-20 修：旧实现是「首个画质关键词命中即返回」——
        搜索结果顺序不等于质量顺序，且同一 infohash 的重复条目、下载器里
        已存在的任务会被反复选中。现改为：
        1. infohash 去重（无 magnet 的退化为 name 前 60 字符）
        2. 排除已试（tried_hashes，通常来自下载器现有任务的 hash 集合）
        3. 存在偏好画质候选时只在候选内打分，否则全量打分（旧逻辑的
           「偏好画质优先」保留为软偏好，不再一命中就返回）
        4. magnet_score 五维打分（seeders/分辨率/字幕/新鲜度/完整性），
           同分按 size 降序
        """
        from app.services.magnet_checker import extract_info_hash, magnet_score

        if not results:
            return None

        def _infohash(r: dict) -> str:
            magnet = r.get("magnet") or r.get("url") or r.get("torrent_url") or ""
            try:
                return extract_info_hash(magnet)
            except (ValueError, TypeError):
                return ""

        # 1) infohash 去重
        seen: set[str] = set()
        deduped: list[tuple[dict, str]] = []
        for r in results:
            h = _infohash(r)
            key = h or (r.get("name") or "")[:60]
            if key and key in seen:
                continue
            seen.add(key)
            deduped.append((r, h))

        # 2) 排除已试
        tried = tried_hashes or set()
        if tried:
            fresh = [(r, h) for r, h in deduped if not (h and h in tried)]
            if fresh:
                deduped = fresh

        pool = [r for r, _ in deduped]

        # 3) 偏好画质软过滤（有候选才用）
        quality_keywords = [kw for kw in (quality, "1080p", "720p") if kw]
        preferred = [
            r for r in pool
            if any(kw.lower() in (r.get("name") or "").lower() for kw in quality_keywords)
        ]
        if preferred:
            pool = preferred

        # 4) 五维打分，同分比大小
        def _score(r: dict) -> tuple:
            s = magnet_score(
                title=r.get("name") or "",
                seeders=int(r.get("seeders") or 0),
            )
            return (s.total, int(r.get("size") or 0))

        return max(pool, key=_score)

    async def manual_download(self, code: str, quality: str = "1080p") -> dict:
        """手动触发下载（不更新订阅状态）"""
        await self._search_and_download(code, quality)
        return {"status": "ok", "code": code, "quality": quality}


# 全局单例
subscription_downloader_service = SubscriptionDownloaderService()

__all__ = ["SubscriptionDownloaderService", "subscription_downloader_service"]
