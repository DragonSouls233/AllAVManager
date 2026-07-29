"""女优收藏系统 — 参考 OpenAver 的女优管理功能。

功能：
1. 女优收藏（跨模块收藏，各模块演员统一管理）
2. 相似探索（基于 tag IDF 权重的本地相似影片推荐）
3. 收藏分级（参考 JATLAS）
4. 封面墙浏览
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ActressCollect:
    """女优收藏条目。"""
    name: str
    aliases: list[str] = field(default_factory=list)
    module: str = ""          # jav / fc2 / chinese / pornhub / western / uncensored
    movie_count: int = 0
    studio: str = ""
    cover_url: str = ""
    avatar_url: str = ""
    tags: list[str] = field(default_factory=list)
    rating: float = 0.0
    tier: int = 3             # 1-5 分级（1 最高）
    birth_date: str = ""
    height: str = ""
    measurements: str = ""
    cup: str = ""
    favorite: bool = False
    notes: str = ""


@dataclass
class SimilarMovie:
    """相似影片推荐条目。"""
    id: str
    code: str
    title: str
    score: float       # 相似度 0-1
    reasons: list[str] = field(default_factory=list)
    cover_url: str = ""


class ActressDatabase:
    """女优数据库（JSON 持久化）。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "actress_db.json",
        )
        self._actresses: dict[str, ActressCollect] = {}
        self._load()

    def _load(self):
        if os.path.isfile(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        a = ActressCollect(**item)
                        self._actresses[a.name] = a
            except Exception as e:
                logger.warning("actress db load failed: %s", e)

    def _save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump([a.__dict__ for a in self._actresses.values()],
                      f, ensure_ascii=False, indent=2)

    def get(self, name: str) -> Optional[ActressCollect]:
        return self._actresses.get(name)

    def all(self) -> list[ActressCollect]:
        return sorted(self._actresses.values(), key=lambda a: a.movie_count, reverse=True)

    def add(self, actress: ActressCollect):
        existing = self._actresses.get(actress.name)
        if existing:
            actress.movie_count = max(actress.movie_count, existing.movie_count)
            if actress.aliases:
                existing.aliases = list(set(existing.aliases + actress.aliases))
            if actress.cover_url:
                existing.cover_url = actress.cover_url
            existing.favorite = actress.favorite or existing.favorite
        else:
            self._actresses[actress.name] = actress
        self._save()

    def remove(self, name: str):
        self._actresses.pop(name, None)
        self._save()

    def set_favorite(self, name: str, favorite: bool):
        a = self._actresses.get(name)
        if a:
            a.favorite = favorite
            self._save()

    def set_tier(self, name: str, tier: int):
        a = self._actresses.get(name)
        if a and 1 <= tier <= 5:
            a.tier = tier
            self._save()

    def search(self, keyword: str) -> list[ActressCollect]:
        kw = keyword.lower()
        results = []
        for a in self._actresses.values():
            if kw in a.name.lower():
                results.append(a)
                continue
            for alias in a.aliases:
                if kw in alias.lower():
                    results.append(a)
                    break
        return results

    def get_by_tier(self, tier: int) -> list[ActressCollect]:
        return [a for a in self._actresses.values() if a.tier == tier]

    def get_favorites(self) -> list[ActressCollect]:
        return [a for a in self._actresses.values() if a.favorite]

    def stats(self) -> dict:
        return {
            "total": len(self._actresses),
            "favorites": sum(1 for a in self._actresses.values() if a.favorite),
            "by_module": dict(Counter(a.module for a in self._actresses.values() if a.module)),
            "by_tier": dict(Counter(a.tier for a in self._actresses.values())),
        }

    def sync_from_db(self):
        """从各模块数据库同步女优信息。"""
        import asyncio
        try:
            from app.db.database import get_db_session
            from sqlalchemy import text

            async def _sync():
                async with get_db_session() as session:
                    modules = [
                        ("jav", "jav_movies"), ("fc2", "fc2_movies"),
                        ("chinese", "chinese_movies"), ("pornhub", "pornhub_movies"),
                        ("western", "western_movies"), ("uncensored", "uncensored_movies"),
                    ]
                    for module, table in modules:
                        sql = text(f"SELECT actors, code, studio FROM {table}")
                        try:
                            rows = (await session.execute(sql)).fetchall()
                        except Exception:
                            continue
                        for row in rows:
                            actors_raw = row[0] or ""
                            code = row[1] or ""
                            studio = row[2] or ""
                            if not actors_raw:
                                continue
                            actor_names = [
                                a.strip() for a in actors_raw.replace(";", ",").split(",") if a.strip()
                            ]
                            for name in actor_names:
                                existing = self._actresses.get(name)
                                if existing:
                                    existing.movie_count += 1
                                    if studio and studio not in existing.tags:
                                        existing.tags.append(studio)
                                else:
                                    self._actresses[name] = ActressCollect(
                                        name=name, module=module,
                                        movie_count=1, studio=studio,
                                    )
                    self._save()
            asyncio.run(_sync())
        except Exception as e:
            logger.warning("actress db sync failed: %s", e)


# 全局单例
_actress_db: Optional[ActressDatabase] = None


def get_actress_db() -> ActressDatabase:
    global _actress_db
    if _actress_db is None:
        _actress_db = ActressDatabase()
    return _actress_db


# ---------------------------------------------------------------------------
# 相似探索引擎
# ---------------------------------------------------------------------------

class SimilarityEngine:
    """基于 tag IDF 加权的内容相似探索。"""

    def __init__(self):
        self._tag_idf: dict[str, float] = {}
        self._movie_tags: dict[str, list[str]] = {}

    def build_index(self, movies: list[SimilarMovie]):
        """构建 tag IDF 索引。"""
        tag_count: Counter = Counter()
        for m in movies:
            for tag in m.reasons:
                tag_count[tag] += 1
                self._movie_tags.setdefault(m.code, []).append(tag)
        n = len(movies)
        for tag, count in tag_count.items():
            self._tag_idf[tag] = math.log(n / (1 + count))

    def find_similar(self, code: str, top_n: int = 10) -> list[SimilarMovie]:
        """查找相似影片。"""
        tags = self._movie_tags.get(code, [])
        if not tags or not self._tag_idf:
            return []

        scores: list[tuple[str, float]] = []
        for other_code, other_tags in self._movie_tags.items():
            if other_code == code:
                continue
            score = sum(self._tag_idf.get(t, 0) for t in tags if t in other_tags)
            if score > 0:
                scores.append((other_code, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [
            SimilarMovie(id=c, code=c, title=c, score=s)
            for c, s in scores[:top_n]
        ]
