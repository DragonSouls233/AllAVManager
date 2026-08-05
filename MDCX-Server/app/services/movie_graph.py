"""
影片图谱服务
- 基于同演员/同系列/同标签/同厂商构建关联图谱
- 图谱数据结构:nodes(影片) + edges(关联类型+权重)
- 关联推荐算法:基于图谱权重排序 Top N
"""
import importlib
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.manager import get_config
from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS

logger = logging.getLogger(__name__)


def _resolve_module(module: str) -> str:
    """解析模块名，无效时回退到 jav"""
    return module if module in MODULE_MODELS else "jav"


def _get_mod_cls(module: str, cls_name: str):
    """获取模块中的任意模型类"""
    mod_path, _, _ = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


class MovieGraphService:
    """影片图谱服务"""

    async def get_graph(
        self,
        movie_id: int,
        depth: int = 1,
        module: str = "jav",
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
        module = _resolve_module(module)
        MovieModel = get_module_model(module, "movie")
        MovieRelationCls = _get_mod_cls(module, "MovieRelation")
        MovieActorCls = _get_mod_cls(module, "MovieActor")
        MovieTagCls = _get_mod_cls(module, "MovieTag")

        if session is None:
            session = await get_module_session(module)

        config = get_config()
        max_relations = config.movie_graph.max_relations_per_movie
        min_weight = config.movie_graph.min_weight_threshold

        nodes: dict[int, dict] = {}
        edges: list[dict] = []

        # 获取中心影片
        center_movie = await session.get(MovieModel, movie_id)
        if not center_movie:
            return {"nodes": [], "edges": []}

        nodes[movie_id] = self._movie_to_node(center_movie)

        # 查询已存储的关联关系
        relations = await session.execute(
            select(MovieRelationCls).where(MovieRelationCls.movie_id == movie_id)
        )
        for rel in relations.scalars():
            if rel.weight < min_weight:
                continue
            related = await session.get(MovieModel, rel.related_movie_id)
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
            select(MovieModel).join(MovieActorCls, MovieActorCls.movie_id == MovieModel.id)
            .where(MovieActorCls.actor_id.in_(
                select(MovieActorCls.actor_id).where(MovieActorCls.movie_id == movie_id)
            ))
            .where(MovieModel.id != movie_id)
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
                select(MovieModel).where(
                    MovieModel.series_id == center_movie.series_id,
                    MovieModel.id != movie_id
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
            select(MovieModel).join(MovieTagCls, MovieTagCls.movie_id == MovieModel.id)
            .where(MovieTagCls.tag_id.in_(
                select(MovieTagCls.tag_id).where(MovieTagCls.movie_id == movie_id)
            ))
            .where(MovieModel.id != movie_id)
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
                select(MovieModel).where(
                    MovieModel.studio_id == center_movie.studio_id,
                    MovieModel.id != movie_id
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

    def _movie_to_node(self, movie) -> dict:
        return {
            "id": movie.id,
            "code": movie.code,
            "title": movie.title,
            "cover_url": movie.cover_url,
            "poster_url": movie.poster_url if hasattr(movie, "poster_url") else None,
            "release_date": movie.release_date,
            "rating": movie.rating
        }

    async def get_recommendations(
        self,
        movie_id: int,
        limit: int = 10,
        module: str = "jav",
        session: AsyncSession = None
    ) -> list[dict]:
        """基于图谱获取关联推荐"""
        graph = await self.get_graph(movie_id, module=module, session=session)

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
        module: str = "jav",
        session: AsyncSession = None
    ) -> bool:
        """保存关联关系到数据库"""
        module = _resolve_module(module)
        MovieRelationCls = _get_mod_cls(module, "MovieRelation")

        if session is None:
            session = await get_module_session(module)

        existing = await session.execute(
            select(MovieRelationCls).where(
                MovieRelationCls.movie_id == movie_id,
                MovieRelationCls.related_movie_id == related_movie_id,
                MovieRelationCls.relation_type == relation_type
            )
        )
        if existing.scalars().first():
            return False

        relation = MovieRelationCls(
            movie_id=movie_id,
            related_movie_id=related_movie_id,
            relation_type=relation_type,
            weight=weight
        )
        session.add(relation)
        await session.commit()
        return True


movie_graph_service = MovieGraphService()
