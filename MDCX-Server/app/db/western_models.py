"""
欧美模块数据模型 (western.db)
"""
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class WESTERN_BASE(DeclarativeBase):
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


class WesternMovie(MovieMixin, WESTERN_BASE):
    """欧美影片"""
    __tablename__ = "movies"

    site: Mapped[str | None] = mapped_column(String(100), index=True)
    network: Mapped[str | None] = mapped_column(String(100))


class WesternActor(ActorMixin, WESTERN_BASE):
    """欧美演员"""
    __tablename__ = "actors"

    gender: Mapped[str | None] = mapped_column(String(20))
    birthdate: Mapped[str | None] = mapped_column(String(20))  # 注意：与 ActorMixin.birth_date 不同，这是欧美格式
    country: Mapped[str | None] = mapped_column(String(100))
    ethnicity: Mapped[str | None] = mapped_column(String(50))
    measurements: Mapped[str | None] = mapped_column(String(100))
    weight: Mapped[str | None] = mapped_column(String(20))
    twitter: Mapped[str | None] = mapped_column(String(500))
    instagram: Mapped[str | None] = mapped_column(String(500))


class MovieActor(MovieActorMixin, WESTERN_BASE):
    __tablename__ = "movie_actors"

class Studio(StudioMixin, WESTERN_BASE):
    __tablename__ = "studios"

class Series(SeriesMixin, WESTERN_BASE):
    __tablename__ = "series"

class Tag(TagMixin, WESTERN_BASE):
    __tablename__ = "tags"

class MovieTag(MovieTagMixin, WESTERN_BASE):
    __tablename__ = "movie_tags"

class ActorTag(ActorTagMixin, WESTERN_BASE):
    __tablename__ = "actor_tags"

class TierConfig(TierConfigMixin, WESTERN_BASE):
    __tablename__ = "tier_config"

class ActorTier(ActorTierMixin, WESTERN_BASE):
    __tablename__ = "actor_tiers"

class ActorCompareURL(ActorCompareURLMixin, WESTERN_BASE):
    __tablename__ = "actor_compare_urls"

class ActorSubscription(ActorSubscriptionMixin, WESTERN_BASE):
    __tablename__ = "actor_subscriptions"

class SeriesSubscription(SeriesSubscriptionMixin, WESTERN_BASE):
    __tablename__ = "series_subscriptions"

class PlayHistory(PlayHistoryMixin, WESTERN_BASE):
    __tablename__ = "play_history"

class ImportRecord(ImportRecordMixin, WESTERN_BASE):
    __tablename__ = "import_records"

class PatchRecord(PatchRecordMixin, WESTERN_BASE):
    __tablename__ = "patch_records"

class FileOrganizeJob(FileOrganizeJobMixin, WESTERN_BASE):
    __tablename__ = "file_organize_jobs"

class AutoOrganizeRule(AutoOrganizeRuleMixin, WESTERN_BASE):
    __tablename__ = "auto_organize_rules"

class MovieRelation(MovieRelationMixin, WESTERN_BASE):
    __tablename__ = "movie_relations"

class UserRecommendation(UserRecommendationMixin, WESTERN_BASE):
    __tablename__ = "user_recommendations"
# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
MovieActor.movie = _rel(WesternMovie, foreign_keys=[MovieActor.movie_id], back_populates="actors")
MovieActor.actor = _rel(WesternActor, foreign_keys=[MovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
MovieTag.movie = _rel(WesternMovie, foreign_keys=[MovieTag.movie_id], back_populates="tags_rel")
MovieTag.tag = _rel(Tag, foreign_keys=[MovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
PlayHistory.movie = _rel(WesternMovie, foreign_keys=[PlayHistory.movie_id])
ImportRecord.movie = _rel(WesternMovie, foreign_keys=[ImportRecord.movie_id])
PatchRecord.movie = _rel(WesternMovie, foreign_keys=[PatchRecord.movie_id])
FileOrganizeJob.movie = _rel(WesternMovie, foreign_keys=[FileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
MovieRelation.movie = _rel(WesternMovie, foreign_keys=[MovieRelation.movie_id])
MovieRelation.related_movie = _rel(WesternMovie, foreign_keys=[MovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
UserRecommendation.movie = _rel(WesternMovie, foreign_keys=[UserRecommendation.movie_id])

# --- Movie → 关联表 ---
WesternMovie.actors = _rel(MovieActor, back_populates="movie", cascade="all, delete-orphan")
WesternMovie.tags_rel = _rel(MovieTag, back_populates="movie", cascade="all, delete-orphan")
WesternMovie.studio_ref = _rel(Studio, foreign_keys=[WesternMovie.studio_id])
WesternMovie.series_ref = _rel(Series, foreign_keys=[WesternMovie.series_id])

# --- Actor → 关联表 ---
WesternActor.movies = _rel(MovieActor, back_populates="actor", cascade="all, delete-orphan")
WesternActor.tags_rel = _rel(ActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[ActorTag.actor_id])
WesternActor.tier = _rel(ActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
WesternActor.compare_urls = _rel(ActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
ActorTier.actor = _rel(WesternActor, foreign_keys=[ActorTier.actor_id])
ActorCompareURL.actor = _rel(WesternActor, foreign_keys=[ActorCompareURL.actor_id])
ActorTag.actor = _rel(WesternActor, foreign_keys=[ActorTag.actor_id])

# --- Series → Studio ---
Series.studio = _rel(Studio, foreign_keys=[Series.studio_id])

# --- ActorSubscription / SeriesSubscription ---
ActorSubscription.actor = _rel(WesternActor, foreign_keys=[ActorSubscription.actor_id])
SeriesSubscription.series = _rel(Series, foreign_keys=[SeriesSubscription.series_id])
