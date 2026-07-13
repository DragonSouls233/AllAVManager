"""
三态视频标记服务（v3.0）

参考 JavdBviewed 项目，提供三态视频标记：
- browsed（浏览过）：用户看过详情/卡片，但未播放
- watched（已观看）：用户实际播放过影片
- wanted（想看）：用户标记想看但未播放

设计要点：
1. 状态机：browsed → watched（看完后自动转 watched）
2. wanted 与 browsed/watched 互斥（想看 → 看过 → 自动清除 wanted）
3. 支持批量标记、按状态筛选、按状态统计
4. 与 PlayHistory 集成：播放完成自动标记 watched
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Movie, PlayHistory

logger = logging.getLogger(__name__)


# 三态枚举
VIEW_STATUS_BROWSED = "browsed"   # 浏览过
VIEW_STATUS_WATCHED = "watched"   # 已观看
VIEW_STATUS_WANTED = "wanted"     # 想看

VALID_STATUSES = {VIEW_STATUS_BROWSED, VIEW_STATUS_WATCHED, VIEW_STATUS_WANTED}


class ViewStatusService:
    """三态视频标记服务"""

    async def set_status(
        self,
        session: AsyncSession,
        movie_id: int,
        status: Optional[str],
        user_id: Optional[int] = None,
    ) -> Optional[Movie]:
        """
        设置影片观看状态

        Args:
            session: 数据库会话
            movie_id: 影片 ID
            status: 状态（browsed/watched/wanted），None 表示清除标记
            user_id: 用户 ID（可选，目前 view_status 全局，预留多用户隔离）

        Returns:
            更新后的 Movie 对象，None 表示影片不存在

        状态转换规则：
        - wanted → browsed：清除 wanted，设为 browsed
        - wanted → watched：清除 wanted，设为 watched
        - browsed → watched：升级为 watched
        - watched → browsed：降级（允许，用户手动调整）
        - 任意 → wanted：标记想看
        - None：清除标记
        """
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"无效的 view_status: {status}，有效值: {VALID_STATUSES}")

        movie = await session.get(Movie, movie_id)
        if not movie:
            return None

        movie.view_status = status
        await session.commit()
        await session.refresh(movie)

        logger.info(f"影片 {movie_id} ({movie.code}) view_status → {status}")
        return movie

    async def batch_set_status(
        self,
        session: AsyncSession,
        movie_ids: list[int],
        status: str,
    ) -> int:
        """批量设置观看状态

        Args:
            session: 数据库会话
            movie_ids: 影片 ID 列表
            status: 目标状态

        Returns:
            实际更新的数量
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"无效的 view_status: {status}")

        if not movie_ids:
            return 0

        stmt = (
            update(Movie)
            .where(Movie.id.in_(movie_ids))
            .values(view_status=status)
        )
        result = await session.execute(stmt)
        await session.commit()
        updated = result.rowcount or 0
        logger.info(f"批量设置 {updated} 部影片 view_status → {status}")
        return updated

    async def get_status(self, session: AsyncSession, movie_id: int) -> Optional[str]:
        """获取单部影片观看状态"""
        movie = await session.get(Movie, movie_id)
        return movie.view_status if movie else None

    async def list_by_status(
        self,
        session: AsyncSession,
        status: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Movie]:
        """按状态列出影片"""
        if status not in VALID_STATUSES:
            raise ValueError(f"无效的 view_status: {status}")

        stmt = (
            select(Movie)
            .where(Movie.view_status == status)
            .order_by(Movie.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(self, session: AsyncSession) -> dict[str, int]:
        """统计各状态影片数量

        Returns:
            {"browsed": N, "watched": N, "wanted": N, "unmarked": N}
        """
        result = {}
        for status in VALID_STATUSES:
            stmt = select(func.count(Movie.id)).where(Movie.view_status == status)
            r = await session.execute(stmt)
            result[status] = r.scalar() or 0

        # 未标记
        stmt = select(func.count(Movie.id)).where(Movie.view_status.is_(None))
        r = await session.execute(stmt)
        result["unmarked"] = r.scalar() or 0

        return result

    async def mark_watched_on_play_complete(
        self,
        session: AsyncSession,
        movie_id: int,
        user_id: Optional[int] = None,
        progress: float = 0.0,
    ) -> None:
        """播放完成时自动标记为 watched

        阈值：进度 >= 0.85 或 completed=True 时触发

        Args:
            session: 数据库会话
            movie_id: 影片 ID
            user_id: 用户 ID
            progress: 播放进度 0-1
        """
        if progress < 0.85:
            return

        movie = await session.get(Movie, movie_id)
        if not movie:
            return

        # 已是 watched 不重复更新
        if movie.view_status == VIEW_STATUS_WATCHED:
            return

        old_status = movie.view_status
        movie.view_status = VIEW_STATUS_WATCHED
        await session.commit()

        logger.info(
            f"播放完成自动标记：影片 {movie_id} ({movie.code}) "
            f"{old_status} → {VIEW_STATUS_WATCHED} (progress={progress:.2f})"
        )

    async def mark_browsed_on_view(
        self,
        session: AsyncSession,
        movie_id: int,
    ) -> None:
        """查看影片详情时自动标记为 browsed

        仅在当前无标记或已标记为 wanted 时触发，
        不覆盖 watched 状态。
        """
        movie = await session.get(Movie, movie_id)
        if not movie:
            return

        # watched 不降级
        if movie.view_status == VIEW_STATUS_WATCHED:
            return

        # 已是 browsed 不重复
        if movie.view_status == VIEW_STATUS_BROWSED:
            return

        # wanted 保留（用户明确想看，浏览不改变）
        if movie.view_status == VIEW_STATUS_WANTED:
            return

        movie.view_status = VIEW_STATUS_BROWSED
        await session.commit()
        logger.debug(f"浏览自动标记：影片 {movie_id} → {VIEW_STATUS_BROWSED}")


# 单例
view_status_service = ViewStatusService()
