"""
自动搜索订阅下载服务（v4.1）

职责：
- 定时检查订阅（演员 + 系列的新片）
- 番号搜索（qBittorrent search engine，若下载器支持）
- 自动下载（依据订阅的 auto_download / preferred_quality 配置）
- 完成回调由下载器自身的事件机制处理（自动整理 + 刮削 + 入库 + 通知）

设计要点：
- 复用 downloader_manager 与 actor_subscription / series_subscription 的检测逻辑
- 全异步；后台任务用 get_session_context 获取会话
- 服务在 app.main lifespan 中启动/停止
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_session_context
from app.db.models import Movie, MovieActor, ActorSubscription, SeriesSubscription

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

    async def check_all_subscriptions(self):
        """检查所有订阅（演员 + 系列），并处理自动下载"""
        async with get_session_context() as session:
            # 检查演员订阅新片
            try:
                from app.services.actor_subscription import check_all_subscriptions
                await check_all_subscriptions(session)
            except Exception as e:
                logger.error(f"演员订阅检测失败: {e}", exc_info=True)

            # 检查系列订阅新片
            try:
                from app.services.series_subscription import check_all_series_subscriptions
                await check_all_series_subscriptions(session)
            except Exception as e:
                logger.error(f"系列订阅检测失败: {e}", exc_info=True)

            # 处理自动下载
            try:
                await self._process_auto_downloads(session)
            except Exception as e:
                logger.error(f"自动下载处理失败: {e}", exc_info=True)

    async def _process_auto_downloads(self, session: AsyncSession):
        """处理启用了 auto_download 的订阅：搜索并下载最新影片"""
        now = datetime.utcnow()

        # ---- 演员订阅 ----
        actor_subs = await session.execute(
            select(ActorSubscription).where(ActorSubscription.auto_download == True)  # noqa: E712
        )
        for sub in actor_subs.scalars():
            try:
                # 获取该演员最新影片（按创建时间倒序，取一部）
                movies_stmt = (
                    select(Movie)
                    .join(MovieActor, Movie.id == MovieActor.movie_id)
                    .where(MovieActor.actor_id == sub.actor_id)
                    .order_by(Movie.created_at.desc())
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
            select(SeriesSubscription).where(SeriesSubscription.auto_download == True)  # noqa: E712
        )
        for sub in series_subs.scalars():
            try:
                movies_stmt = (
                    select(Movie)
                    .where(Movie.series_id == sub.series_id)
                    .order_by(Movie.created_at.desc())
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

            # 使用 qBittorrent search（如果下载器实现了 search 方法）
            if hasattr(downloader, "search"):
                results = await downloader.search(code)
                if not results:
                    logger.info(f"搜索无结果: {code}")
                    return
                best = self._select_best_torrent(results, quality)
                if not best:
                    logger.info(f"未找到合适资源: {code}")
                    return
                magnet = best.get("magnet") or best.get("url") or best.get("torrent_url")
                if not magnet:
                    logger.warning(f"搜索结果缺少磁力链/URL: {code}")
                    return
                await downloader.add_torrent(magnet, name=code)
                logger.info(f"已添加下载: {code} (来源: {best.get('name', '?')})")
            else:
                logger.warning(
                    f"下载器 {downloader.type} 不支持搜索，跳过 {code}（请配置 qBittorrent 或扩展搜索源）"
                )
        except Exception as e:
            logger.error(f"搜索下载失败 {code}: {e}", exc_info=True)

    def _select_best_torrent(self, results: list, quality: str) -> Optional[dict]:
        """选择最佳种子：优先匹配偏好画质，其次按 seeder 数排序"""
        if not results:
            return None
        quality_keywords = [quality, "1080p", "720p"]
        for kw in quality_keywords:
            if not kw:
                continue
            for r in results:
                name = (r.get("name") or "").lower()
                if kw.lower() in name:
                    return r
        # 退而求其次：按 seeder 数排序
        return max(results, key=lambda x: x.get("seeders", 0) or 0)

    async def manual_download(self, code: str, quality: str = "1080p") -> dict:
        """手动触发下载（不更新订阅状态）"""
        await self._search_and_download(code, quality)
        return {"status": "ok", "code": code, "quality": quality}


# 全局单例
subscription_downloader_service = SubscriptionDownloaderService()

__all__ = ["SubscriptionDownloaderService", "subscription_downloader_service"]
