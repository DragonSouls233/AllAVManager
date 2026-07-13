"""
AI 智能推荐服务
- 从用户收藏夹 + PlayHistory 提取偏好向量
- 偏好维度:演员/标签/系列/厂商/评分分布
- 匹配算法:余弦相似度 + 偏好权重
"""
import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import (
    User, Movie, PlayHistory, FavoriteItem, FavoriteGroup,
    MovieActor, MovieTag, Tag, Actor
)
from app.config.manager import get_config

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """AI 智能推荐引擎"""

    async def get_recommendations(
        self,
        user_id: Optional[int] = None,
        limit: int = 20,
        session: AsyncSession = None
    ) -> list[dict]:
        """获取推荐列表"""
        config = get_config()

        # 1. 提取用户偏好
        preferences = await self._extract_preferences(user_id, session)
        if not self._has_preferences(preferences):
            # 无偏好数据:返回热门影片
            return await self._get_popular_movies(limit, session)

        # 2. 查询候选影片(排除已看过的)
        watched_ids = await self._get_watched_ids(user_id, session)

        # 3. 计算每部候选影片的推荐分数
        candidates = await self._get_candidates(watched_ids, session)

        # 批量加载候选影片的 actors/tags,避免在循环中 await
        candidate_ids = [m.id for m in candidates]
        movie_actors = await self._batch_load_actors(candidate_ids, session)
        movie_tags = await self._batch_load_tags(candidate_ids, session)

        scored = []
        for movie in candidates:
            actors_set = movie_actors.get(movie.id, set())
            tags_set = movie_tags.get(movie.id, set())
            score, reasons = self._calculate_score(
                movie, actors_set, tags_set, preferences, config
            )
            if score > 0:
                scored.append({
                    "id": movie.id,
                    "code": movie.code,
                    "title": movie.title,
                    "cover_url": movie.cover_url,
                    "poster_url": movie.poster_url,
                    "release_date": movie.release_date,
                    "rating": movie.rating,
                    "score": score,
                    "reasons": reasons
                })

        # 4. 排序并取 Top N
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _has_preferences(self, prefs: dict) -> bool:
        """判断是否有任何偏好数据"""
        return any(
            len(prefs.get(k, Counter())) > 0
            for k in ("actors", "tags", "series", "studios", "ratings")
        )

    async def _batch_load_actors(
        self, movie_ids: list[int], session: AsyncSession
    ) -> dict[int, set[int]]:
        """批量加载多个影片的 actor_id 集合"""
        result: dict[int, set[int]] = {mid: set() for mid in movie_ids}
        if not movie_ids:
            return result
        rows = await session.execute(
            select(MovieActor.movie_id, MovieActor.actor_id)
            .where(MovieActor.movie_id.in_(movie_ids))
        )
        for movie_id, actor_id in rows.all():
            result.setdefault(movie_id, set()).add(actor_id)
        return result

    async def _batch_load_tags(
        self, movie_ids: list[int], session: AsyncSession
    ) -> dict[int, set[int]]:
        """批量加载多个影片的 tag_id 集合"""
        result: dict[int, set[int]] = {mid: set() for mid in movie_ids}
        if not movie_ids:
            return result
        rows = await session.execute(
            select(MovieTag.movie_id, MovieTag.tag_id)
            .where(MovieTag.movie_id.in_(movie_ids))
        )
        for movie_id, tag_id in rows.all():
            result.setdefault(movie_id, set()).add(tag_id)
        return result

    async def _extract_preferences(self, user_id: Optional[int], session: AsyncSession) -> dict:
        """提取用户偏好向量"""
        prefs = {
            "actors": Counter(),
            "tags": Counter(),
            "series": Counter(),
            "studios": Counter(),
            "ratings": Counter()
        }

        # 从 PlayHistory 提取
        if user_id:
            history = await session.execute(
                select(Movie).join(PlayHistory, PlayHistory.movie_id == Movie.id)
                .where(PlayHistory.user_id == user_id)
                .order_by(PlayHistory.played_at.desc())
                .limit(100)
            )
        else:
            history = await session.execute(
                select(Movie).join(PlayHistory, PlayHistory.movie_id == Movie.id)
                .order_by(PlayHistory.played_at.desc())
                .limit(100)
            )

        history_movies = history.scalars().all()
        history_ids = [m.id for m in history_movies]

        # 批量加载 actors/tags,避免在循环中 await
        history_actors = await self._batch_load_actors(history_ids, session)
        history_tags = await self._batch_load_tags(history_ids, session)

        for movie in history_movies:
            for actor_id in history_actors.get(movie.id, set()):
                prefs["actors"][actor_id] += 1
            for tag_id in history_tags.get(movie.id, set()):
                prefs["tags"][tag_id] += 1
            if movie.series_id:
                prefs["series"][movie.series_id] += 1
            if movie.studio_id:
                prefs["studios"][movie.studio_id] += 1
            if movie.rating:
                prefs["ratings"][round(movie.rating)] += 1

        # 从收藏夹提取(权重更高)
        if user_id:
            favorites = await session.execute(
                select(Movie).join(FavoriteItem, FavoriteItem.entity_id == Movie.id)
                .where(FavoriteItem.entity_type == "movie")
            )
            fav_movies = favorites.scalars().all()
            fav_ids = [m.id for m in fav_movies]
            fav_actors = await self._batch_load_actors(fav_ids, session)
            for movie in fav_movies:
                for actor_id in fav_actors.get(movie.id, set()):
                    prefs["actors"][actor_id] += 3  # 收藏权重 3x
                if movie.series_id:
                    prefs["series"][movie.series_id] += 3
                if movie.studio_id:
                    prefs["studios"][movie.studio_id] += 3

        return prefs

    async def _get_watched_ids(self, user_id: Optional[int], session: AsyncSession) -> set[int]:
        """获取已观看影片 ID"""
        if user_id:
            result = await session.execute(
                select(PlayHistory.movie_id).where(PlayHistory.user_id == user_id)
            )
        else:
            result = await session.execute(select(PlayHistory.movie_id))
        return set(result.scalars().all())

    async def _get_candidates(self, exclude_ids: set[int], session: AsyncSession) -> list[Movie]:
        """获取候选影片(排除已看)"""
        stmt = select(Movie).where(
            Movie.id.notin_(exclude_ids) if exclude_ids else True,
            Movie.cover_url.isnot(None)
        ).order_by(desc(Movie.release_date)).limit(500)
        result = await session.execute(stmt)
        return result.scalars().all()

    def _calculate_score(
        self,
        movie: Movie,
        actors_set: set[int],
        tags_set: set[int],
        preferences: dict,
        config
    ) -> tuple[float, list[str]]:
        """计算推荐分数

        返回 (score, reasons)。基于偏好向量的加权匹配:
        - 演员: 候选影片演员与偏好演员 Counter 的重叠次数(归一化)
        - 标签: 同上
        - 系列: 直接命中偏好 series Counter
        - 厂商: 直接命中偏好 studios Counter
        """
        w_actor = config.recommendation.weight_actor
        w_tag = config.recommendation.weight_tag
        w_series = config.recommendation.weight_series
        w_studio = config.recommendation.weight_studio

        actor_counter: Counter = preferences.get("actors", Counter())
        tag_counter: Counter = preferences.get("tags", Counter())
        series_counter: Counter = preferences.get("series", Counter())
        studio_counter: Counter = preferences.get("studios", Counter())

        actor_scores = [actor_counter.get(aid, 0) for aid in actors_set]
        tag_scores = [tag_counter.get(tid, 0) for tid in tags_set]

        max_actor = max(actor_counter.values()) if actor_counter else 0
        max_tag = max(tag_counter.values()) if tag_counter else 0
        max_series = max(series_counter.values()) if series_counter else 0
        max_studio = max(studio_counter.values()) if studio_counter else 0

        # 归一化到 [0,1]:取候选影片中最大的偏好次数 / 全局最大偏好次数
        actor_norm = (max(actor_scores) / max_actor) if max_actor > 0 and actor_scores else 0.0
        tag_norm = (max(tag_scores) / max_tag) if max_tag > 0 and tag_scores else 0.0

        series_score = series_counter.get(movie.series_id, 0) if movie.series_id else 0
        series_norm = (series_score / max_series) if max_series > 0 else 0.0

        studio_score = studio_counter.get(movie.studio_id, 0) if movie.studio_id else 0
        studio_norm = (studio_score / max_studio) if max_studio > 0 else 0.0

        score = (
            w_actor * actor_norm
            + w_tag * tag_norm
            + w_series * series_norm
            + w_studio * studio_norm
        )

        # 构建推荐理由
        reasons: list[str] = []
        if actor_norm >= 0.5 and actor_scores:
            top_actor_id = max(actors_set, key=lambda aid: actor_counter.get(aid, 0))
            reasons.append(f"常看演员")
        if tag_norm >= 0.5:
            reasons.append("兴趣标签")
        if series_norm >= 0.5:
            reasons.append("同系列")
        if studio_norm >= 0.5:
            reasons.append("常看厂商")
        if movie.rating and movie.rating >= 8:
            reasons.append("高分影片")
        if not reasons and score > 0:
            reasons.append("可能感兴趣")

        return score, reasons

    def _get_reasons(self, movie: Movie, preferences: dict) -> list[str]:
        """获取推荐理由(兼容旧调用,保留简化版)"""
        reasons = []
        if movie.rating and movie.rating >= 8:
            reasons.append("高分影片")
        return reasons

    async def _get_popular_movies(self, limit: int, session: AsyncSession) -> list[dict]:
        """获取热门影片(无偏好数据时)"""
        result = await session.execute(
            select(Movie).where(Movie.cover_url.isnot(None))
            .order_by(desc(Movie.play_count), desc(Movie.rating))
            .limit(limit)
        )
        movies = result.scalars().all()
        return [{
            "id": m.id, "code": m.code, "title": m.title,
            "cover_url": m.cover_url, "poster_url": m.poster_url,
            "release_date": m.release_date,
            "rating": m.rating, "score": 0.0,
            "reasons": ["热门影片"]
        } for m in movies]

    async def dismiss_recommendation(self, user_id: Optional[int], movie_id: int, session: AsyncSession) -> bool:
        """忽略推荐"""
        from app.db.models import UserRecommendation
        # 校验影片存在,避免外键约束失败
        movie = await session.get(Movie, movie_id)
        if not movie:
            return False
        existing = await session.execute(
            select(UserRecommendation).where(
                UserRecommendation.user_id == user_id,
                UserRecommendation.movie_id == movie_id
            )
        )
        rec = existing.scalars().first()
        if rec:
            rec.dismissed = True
        else:
            rec = UserRecommendation(
                user_id=user_id, movie_id=movie_id,
                score=0.0, dismissed=True
            )
            session.add(rec)
        await session.commit()
        return True

    async def refresh_recommendations(self, user_id: Optional[int], session: AsyncSession) -> dict:
        """刷新推荐"""
        recs = await self.get_recommendations(user_id, 20, session)

        # 保存到数据库
        from app.db.models import UserRecommendation
        for rec in recs:
            existing = await session.execute(
                select(UserRecommendation).where(
                    UserRecommendation.user_id == user_id,
                    UserRecommendation.movie_id == rec["id"]
                )
            )
            record = existing.scalars().first()
            if record:
                record.score = rec["score"]
                record.reason = ", ".join(rec.get("reasons", []))
                record.dismissed = False
                record.created_at = datetime.utcnow()
            else:
                record = UserRecommendation(
                    user_id=user_id, movie_id=rec["id"],
                    score=rec["score"], reason=", ".join(rec.get("reasons", []))
                )
                session.add(record)

        await session.commit()
        return {"status": "ok", "count": len(recs)}


recommendation_engine = RecommendationEngine()
