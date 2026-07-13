"""
影片图谱服务
- 基于同演员/同系列/同标签/同厂商构建关联图谱
- 图谱数据结构:nodes(影片) + edges(关联类型+权重)
- 关联推荐算法:基于图谱权重排序 Top N
"""
import logging
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Movie, MovieRelation, MovieActor, MovieTag, Tag
from app.config.manager import get_config

logger = logging.getLogger(__name__)


class MovieGraphService:
    """影片图谱服务"""

    async def get_graph(
        self,
        movie_id: int,
        depth: int = 1,
        session: AsyncSession = None
    ) -> dict:
        """
        获取影片关联图谱

        Returns:
            {
                "nodes": [{"id": int, "code": str, "title": str, "cover_url": str}],
                "edges": [{"source": int, "target": int, "type": str, "weight": float}]
            }
        """
        config = get_config()
        max_relations = config.movie_graph.max_relations_per_movie
        min_weight = config.movie_graph.min_weight_threshold

        nodes: dict[int, dict] = {}
        edges: list[dict] = []

        # 获取中心影片
        center_movie = await session.get(Movie, movie_id)
        if not center_movie:
            return {"nodes": [], "edges": []}

        nodes[movie_id] = self._movie_to_node(center_movie)

        # 查询已存储的关联关系
        relations = await session.execute(
            select(MovieRelation).where(MovieRelation.movie_id == movie_id)
        )
        for rel in relations.scalars():
            if rel.weight < min_weight:
                continue
            related = await session.get(Movie, rel.related_movie_id)
            if related:
                nodes[related.id] = self._movie_to_node(related)
                edges.append({
                    "source": movie_id,
                    "target": related.id,
                    "type": rel.relation_type,
                    "weight": rel.weight
                })

        # 动态计算关联(同演员)
        actor_movies = await session.execute(
            select(Movie).join(MovieActor, MovieActor.movie_id == Movie.id)
            .where(MovieActor.actor_id.in_(
                select(MovieActor.actor_id).where(MovieActor.movie_id == movie_id)
            ))
            .where(Movie.id != movie_id)
            .limit(max_relations)
        )
        for m in actor_movies.scalars():
            if m.id not in nodes:
                nodes[m.id] = self._movie_to_node(m)
            edges.append({
                "source": movie_id,
                "target": m.id,
                "type": "same_actor",
                "weight": 0.4
            })

        # 动态计算关联(同系列)
        if center_movie.series_id:
            series_movies = await session.execute(
                select(Movie).where(
                    Movie.series_id == center_movie.series_id,
                    Movie.id != movie_id
                ).limit(max_relations)
            )
            for m in series_movies.scalars():
                if m.id not in nodes:
                    nodes[m.id] = self._movie_to_node(m)
                edges.append({
                    "source": movie_id,
                    "target": m.id,
                    "type": "same_series",
                    "weight": 0.2
                })

        # 动态计算关联(同标签)
        tag_movies = await session.execute(
            select(Movie).join(MovieTag, MovieTag.movie_id == Movie.id)
            .where(MovieTag.tag_id.in_(
                select(MovieTag.tag_id).where(MovieTag.movie_id == movie_id)
            ))
            .where(Movie.id != movie_id)
            .limit(max_relations)
        )
        for m in tag_movies.scalars():
            if m.id not in nodes:
                nodes[m.id] = self._movie_to_node(m)
            edges.append({
                "source": movie_id,
                "target": m.id,
                "type": "same_tag",
                "weight": 0.3
            })

        # 动态计算关联(同厂商)
        if center_movie.studio_id:
            studio_movies = await session.execute(
                select(Movie).where(
                    Movie.studio_id == center_movie.studio_id,
                    Movie.id != movie_id
                ).limit(max_relations)
            )
            for m in studio_movies.scalars():
                if m.id not in nodes:
                    nodes[m.id] = self._movie_to_node(m)
                edges.append({
                    "source": movie_id,
                    "target": m.id,
                    "type": "same_studio",
                    "weight": 0.1
                })

        return {
            "nodes": list(nodes.values()),
            "edges": edges
        }

    def _movie_to_node(self, movie: Movie) -> dict:
        return {
            "id": movie.id,
            "code": movie.code,
            "title": movie.title,
            "cover_url": movie.cover_url,
            "poster_url": movie.poster_url,
            "release_date": movie.release_date,
            "rating": movie.rating
        }

    async def get_recommendations(
        self,
        movie_id: int,
        limit: int = 10,
        session: AsyncSession = None
    ) -> list[dict]:
        """基于图谱获取关联推荐"""
        graph = await self.get_graph(movie_id, session=session)

        # 按权重聚合
        scores: dict[int, float] = {}
        for edge in graph["edges"]:
            target = edge["target"]
            if target == movie_id:
                continue
            scores[target] = scores.get(target, 0.0) + edge["weight"]

        # 排序
        sorted_ids = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        top_id_set = {tid for tid, _ in sorted_ids}
        score_map = dict(sorted_ids)

        result = []
        for node in graph["nodes"]:
            if node["id"] in top_id_set:
                score = score_map.get(node["id"], 0.0)
                result.append({**node, "score": score})

        # 按分数排序输出
        result.sort(key=lambda x: x["score"], reverse=True)
        return result

    async def save_relation(
        self,
        movie_id: int,
        related_movie_id: int,
        relation_type: str,
        weight: float = 1.0,
        session: AsyncSession = None
    ) -> bool:
        """保存关联关系到数据库"""
        existing = await session.execute(
            select(MovieRelation).where(
                MovieRelation.movie_id == movie_id,
                MovieRelation.related_movie_id == related_movie_id,
                MovieRelation.relation_type == relation_type
            )
        )
        if existing.scalars().first():
            return False

        relation = MovieRelation(
            movie_id=movie_id,
            related_movie_id=related_movie_id,
            relation_type=relation_type,
            weight=weight
        )
        session.add(relation)
        await session.commit()
        return True


movie_graph_service = MovieGraphService()
