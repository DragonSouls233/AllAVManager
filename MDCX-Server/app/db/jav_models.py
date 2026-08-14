"""
JAV 有码模块数据模型 (jav.db)
继承自 _module_mixins，完整的规范化表结构
"""
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JAV 模块独立 Base（避免跨模块表名冲突）
class JAV_BASE(DeclarativeBase):
    pass

from app.db._module_mixins import (
    MovieMixin, ActorMixin,
    MovieActorMixin, StudioMixin, SeriesMixin,
    TagMixin, MovieTagMixin, ActorTagMixin,
    TierConfigMixin, ActorTierMixin, ActorCompareURLMixin,
    PlayHistoryMixin, ImportRecordMixin, PatchRecordMixin,
    FileOrganizeJobMixin, AutoOrganizeRuleMixin,
    MovieRelationMixin, UserRecommendationMixin,
    ActorSubscriptionMixin, SeriesSubscriptionMixin,
)


# ===== 影片 =====
class JavMovie(MovieMixin, JAV_BASE):
    """JAV 有码影片"""
    __tablename__ = "movies"

    # 模块特有
    is_chinese: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_uncensored: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_mosaic: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_leak: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 流出/破解版
    is_4k: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 4K 分辨率版（文件名 -4K/-UHD 后缀）
    label: Mapped[str | None] = mapped_column(String(100))
    tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)  # TMDB ID（fanart.tv查询）


# ===== 演员 =====
class JavActor(ActorMixin, JAV_BASE):
    """JAV 演员"""
    __tablename__ = "actors"


# ===== 关联表 =====
class MovieActor(MovieActorMixin, JAV_BASE):
    __tablename__ = "movie_actors"

class Studio(StudioMixin, JAV_BASE):
    __tablename__ = "studios"

class Series(SeriesMixin, JAV_BASE):
    __tablename__ = "series"

class Tag(TagMixin, JAV_BASE):
    __tablename__ = "tags"

class MovieTag(MovieTagMixin, JAV_BASE):
    __tablename__ = "movie_tags"

class ActorTag(ActorTagMixin, JAV_BASE):
    __tablename__ = "actor_tags"


# ===== 分级 =====
class TierConfig(TierConfigMixin, JAV_BASE):
    __tablename__ = "tier_config"

class ActorTier(ActorTierMixin, JAV_BASE):
    __tablename__ = "actor_tiers"


# ===== 演员增强 =====
class ActorCompareURL(ActorCompareURLMixin, JAV_BASE):
    __tablename__ = "actor_compare_urls"

class ActorSubscription(ActorSubscriptionMixin, JAV_BASE):
    __tablename__ = "actor_subscriptions"


# ===== 系列订阅 =====
class SeriesSubscription(SeriesSubscriptionMixin, JAV_BASE):
    __tablename__ = "series_subscriptions"


# ===== 播放 & 导入 & 补刮 =====
class PlayHistory(PlayHistoryMixin, JAV_BASE):
    __tablename__ = "play_history"

class ImportRecord(ImportRecordMixin, JAV_BASE):
    __tablename__ = "import_records"

class PatchRecord(PatchRecordMixin, JAV_BASE):
    __tablename__ = "patch_records"


# ===== 文件整理 =====
class FileOrganizeJob(FileOrganizeJobMixin, JAV_BASE):
    __tablename__ = "file_organize_jobs"

class AutoOrganizeRule(AutoOrganizeRuleMixin, JAV_BASE):
    __tablename__ = "auto_organize_rules"


# ===== 关联 & 推荐 =====
class MovieRelation(MovieRelationMixin, JAV_BASE):
    __tablename__ = "movie_relations"

class UserRecommendation(UserRecommendationMixin, JAV_BASE):
    __tablename__ = "user_recommendations"
# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
MovieActor.movie = _rel(JavMovie, foreign_keys=[MovieActor.movie_id], back_populates="actors")
MovieActor.actor = _rel(JavActor, foreign_keys=[MovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
MovieTag.movie = _rel(JavMovie, foreign_keys=[MovieTag.movie_id], back_populates="tags_rel")
MovieTag.tag = _rel(Tag, foreign_keys=[MovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
PlayHistory.movie = _rel(JavMovie, foreign_keys=[PlayHistory.movie_id])
ImportRecord.movie = _rel(JavMovie, foreign_keys=[ImportRecord.movie_id])
PatchRecord.movie = _rel(JavMovie, foreign_keys=[PatchRecord.movie_id])
FileOrganizeJob.movie = _rel(JavMovie, foreign_keys=[FileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
MovieRelation.movie = _rel(JavMovie, foreign_keys=[MovieRelation.movie_id])
MovieRelation.related_movie = _rel(JavMovie, foreign_keys=[MovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
UserRecommendation.movie = _rel(JavMovie, foreign_keys=[UserRecommendation.movie_id])

# --- Movie → 关联表 ---
JavMovie.actors = _rel(MovieActor, back_populates="movie", cascade="all, delete-orphan")
JavMovie.tags_rel = _rel(MovieTag, back_populates="movie", cascade="all, delete-orphan")
JavMovie.studio_ref = _rel(Studio, foreign_keys=[JavMovie.studio_id])
JavMovie.series_ref = _rel(Series, foreign_keys=[JavMovie.series_id])

# --- Actor → 关联表 ---
JavActor.movies = _rel(MovieActor, back_populates="actor", cascade="all, delete-orphan")
JavActor.tags_rel = _rel(ActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[ActorTag.actor_id])
JavActor.tier = _rel(ActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
JavActor.compare_urls = _rel(ActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
ActorTier.actor = _rel(JavActor, foreign_keys=[ActorTier.actor_id])
ActorCompareURL.actor = _rel(JavActor, foreign_keys=[ActorCompareURL.actor_id])
ActorTag.actor = _rel(JavActor, foreign_keys=[ActorTag.actor_id])

# --- Series → Studio ---
Series.studio = _rel(Studio, foreign_keys=[Series.studio_id])

# --- ActorSubscription / SeriesSubscription ---
ActorSubscription.actor = _rel(JavActor, foreign_keys=[ActorSubscription.actor_id])
SeriesSubscription.series = _rel(Series, foreign_keys=[SeriesSubscription.series_id])
