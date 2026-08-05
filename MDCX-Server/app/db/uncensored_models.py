"""
JAV 无码模块数据模型 (uncensored.db)
"""
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class UNCENSORED_BASE(DeclarativeBase):
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


class UncensoredMovie(MovieMixin, UNCENSORED_BASE):
    """无码影片"""
    __tablename__ = "movies"

    source_platform: Mapped[str | None] = mapped_column(String(50), index=True)


class UncensoredActor(ActorMixin, UNCENSORED_BASE):
    """无码演员"""
    __tablename__ = "actors"


class MovieActor(MovieActorMixin, UNCENSORED_BASE):
    __tablename__ = "movie_actors"

class Studio(StudioMixin, UNCENSORED_BASE):
    __tablename__ = "studios"

class Series(SeriesMixin, UNCENSORED_BASE):
    __tablename__ = "series"

class Tag(TagMixin, UNCENSORED_BASE):
    __tablename__ = "tags"

class MovieTag(MovieTagMixin, UNCENSORED_BASE):
    __tablename__ = "movie_tags"

class ActorTag(ActorTagMixin, UNCENSORED_BASE):
    __tablename__ = "actor_tags"

class TierConfig(TierConfigMixin, UNCENSORED_BASE):
    __tablename__ = "tier_config"

class ActorTier(ActorTierMixin, UNCENSORED_BASE):
    __tablename__ = "actor_tiers"

class ActorCompareURL(ActorCompareURLMixin, UNCENSORED_BASE):
    __tablename__ = "actor_compare_urls"

class ActorSubscription(ActorSubscriptionMixin, UNCENSORED_BASE):
    __tablename__ = "actor_subscriptions"

class SeriesSubscription(SeriesSubscriptionMixin, UNCENSORED_BASE):
    __tablename__ = "series_subscriptions"

class PlayHistory(PlayHistoryMixin, UNCENSORED_BASE):
    __tablename__ = "play_history"

class ImportRecord(ImportRecordMixin, UNCENSORED_BASE):
    __tablename__ = "import_records"

class PatchRecord(PatchRecordMixin, UNCENSORED_BASE):
    __tablename__ = "patch_records"

class FileOrganizeJob(FileOrganizeJobMixin, UNCENSORED_BASE):
    __tablename__ = "file_organize_jobs"

class AutoOrganizeRule(AutoOrganizeRuleMixin, UNCENSORED_BASE):
    __tablename__ = "auto_organize_rules"

class MovieRelation(MovieRelationMixin, UNCENSORED_BASE):
    __tablename__ = "movie_relations"

class UserRecommendation(UserRecommendationMixin, UNCENSORED_BASE):
    __tablename__ = "user_recommendations"
# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
MovieActor.movie = _rel(UncensoredMovie, foreign_keys=[MovieActor.movie_id], back_populates="actors")
MovieActor.actor = _rel(UncensoredActor, foreign_keys=[MovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
MovieTag.movie = _rel(UncensoredMovie, foreign_keys=[MovieTag.movie_id], back_populates="tags_rel")
MovieTag.tag = _rel(Tag, foreign_keys=[MovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
PlayHistory.movie = _rel(UncensoredMovie, foreign_keys=[PlayHistory.movie_id])
ImportRecord.movie = _rel(UncensoredMovie, foreign_keys=[ImportRecord.movie_id])
PatchRecord.movie = _rel(UncensoredMovie, foreign_keys=[PatchRecord.movie_id])
FileOrganizeJob.movie = _rel(UncensoredMovie, foreign_keys=[FileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
MovieRelation.movie = _rel(UncensoredMovie, foreign_keys=[MovieRelation.movie_id])
MovieRelation.related_movie = _rel(UncensoredMovie, foreign_keys=[MovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
UserRecommendation.movie = _rel(UncensoredMovie, foreign_keys=[UserRecommendation.movie_id])

# --- Movie → 关联表 ---
UncensoredMovie.actors = _rel(MovieActor, back_populates="movie", cascade="all, delete-orphan")
UncensoredMovie.tags_rel = _rel(MovieTag, back_populates="movie", cascade="all, delete-orphan")
UncensoredMovie.studio_ref = _rel(Studio, foreign_keys=[UncensoredMovie.studio_id])
UncensoredMovie.series_ref = _rel(Series, foreign_keys=[UncensoredMovie.series_id])

# --- Actor → 关联表 ---
UncensoredActor.movies = _rel(MovieActor, back_populates="actor", cascade="all, delete-orphan")
UncensoredActor.tags_rel = _rel(ActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[ActorTag.actor_id])
UncensoredActor.tier = _rel(ActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
UncensoredActor.compare_urls = _rel(ActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
ActorTier.actor = _rel(UncensoredActor, foreign_keys=[ActorTier.actor_id])
ActorCompareURL.actor = _rel(UncensoredActor, foreign_keys=[ActorCompareURL.actor_id])
ActorTag.actor = _rel(UncensoredActor, foreign_keys=[ActorTag.actor_id])

# --- Series → Studio ---
Series.studio = _rel(Studio, foreign_keys=[Series.studio_id])

# --- ActorSubscription / SeriesSubscription ---
ActorSubscription.actor = _rel(UncensoredActor, foreign_keys=[ActorSubscription.actor_id])
SeriesSubscription.series = _rel(Series, foreign_keys=[SeriesSubscription.series_id])
