"""
Pornhub 模块数据模型 (pornhub.db)
"""
from datetime import datetime

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class PORNHUB_BASE(DeclarativeBase):
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


class PornhubMovie(MovieMixin, PORNHUB_BASE):
    """Pornhub 影片"""
    __tablename__ = "movies"

    source_id: Mapped[str | None] = mapped_column(String(100))
    source_views: Mapped[int | None] = mapped_column(Integer)
    source_score: Mapped[float | None] = mapped_column(Float)
    source_downloads: Mapped[int | None] = mapped_column(Integer)
    uploader: Mapped[str | None] = mapped_column(String(100))
    categories: Mapped[str | None] = mapped_column(Text)  # 分类（逗号分隔或JSON）


class PornhubActor(ActorMixin, PORNHUB_BASE):
    """Pornhub 演员"""
    __tablename__ = "actors"

    nationality: Mapped[str | None] = mapped_column(String(50))


class MovieActor(MovieActorMixin, PORNHUB_BASE):
    __tablename__ = "movie_actors"

class Studio(StudioMixin, PORNHUB_BASE):
    __tablename__ = "studios"

class Series(SeriesMixin, PORNHUB_BASE):
    __tablename__ = "series"

class ActorCompareURL(ActorCompareURLMixin, PORNHUB_BASE):
    __tablename__ = "actor_compare_urls"

class SeriesSubscription(SeriesSubscriptionMixin, PORNHUB_BASE):
    __tablename__ = "series_subscriptions"

class Tag(TagMixin, PORNHUB_BASE):
    __tablename__ = "tags"

class MovieTag(MovieTagMixin, PORNHUB_BASE):
    __tablename__ = "movie_tags"

class ActorTag(ActorTagMixin, PORNHUB_BASE):
    __tablename__ = "actor_tags"

class TierConfig(TierConfigMixin, PORNHUB_BASE):
    __tablename__ = "tier_config"

class ActorTier(ActorTierMixin, PORNHUB_BASE):
    __tablename__ = "actor_tiers"

class ActorSubscription(ActorSubscriptionMixin, PORNHUB_BASE):
    __tablename__ = "actor_subscriptions"

class PlayHistory(PlayHistoryMixin, PORNHUB_BASE):
    __tablename__ = "play_history"

class ImportRecord(ImportRecordMixin, PORNHUB_BASE):
    __tablename__ = "import_records"

class PatchRecord(PatchRecordMixin, PORNHUB_BASE):
    __tablename__ = "patch_records"

class FileOrganizeJob(FileOrganizeJobMixin, PORNHUB_BASE):
    __tablename__ = "file_organize_jobs"

class AutoOrganizeRule(AutoOrganizeRuleMixin, PORNHUB_BASE):
    __tablename__ = "auto_organize_rules"

class MovieRelation(MovieRelationMixin, PORNHUB_BASE):
    __tablename__ = "movie_relations"

class UserRecommendation(UserRecommendationMixin, PORNHUB_BASE):
    __tablename__ = "user_recommendations"
# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
MovieActor.movie = _rel(PornhubMovie, foreign_keys=[MovieActor.movie_id], back_populates="actors")
MovieActor.actor = _rel(PornhubActor, foreign_keys=[MovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
MovieTag.movie = _rel(PornhubMovie, foreign_keys=[MovieTag.movie_id], back_populates="tags_rel")
MovieTag.tag = _rel(Tag, foreign_keys=[MovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
PlayHistory.movie = _rel(PornhubMovie, foreign_keys=[PlayHistory.movie_id])
ImportRecord.movie = _rel(PornhubMovie, foreign_keys=[ImportRecord.movie_id])
PatchRecord.movie = _rel(PornhubMovie, foreign_keys=[PatchRecord.movie_id])
FileOrganizeJob.movie = _rel(PornhubMovie, foreign_keys=[FileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
MovieRelation.movie = _rel(PornhubMovie, foreign_keys=[MovieRelation.movie_id])
MovieRelation.related_movie = _rel(PornhubMovie, foreign_keys=[MovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
UserRecommendation.movie = _rel(PornhubMovie, foreign_keys=[UserRecommendation.movie_id])

# --- Movie → 关联表 ---
PornhubMovie.actors = _rel(MovieActor, back_populates="movie", cascade="all, delete-orphan")
PornhubMovie.tags_rel = _rel(MovieTag, back_populates="movie", cascade="all, delete-orphan")
PornhubMovie.studio_ref = _rel(Studio, foreign_keys=[PornhubMovie.studio_id])
PornhubMovie.series_ref = _rel(Series, foreign_keys=[PornhubMovie.series_id])

# --- Actor → 关联表 ---
PornhubActor.movies = _rel(MovieActor, back_populates="actor", cascade="all, delete-orphan")
PornhubActor.tags_rel = _rel(ActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[ActorTag.actor_id])
PornhubActor.tier = _rel(ActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
PornhubActor.compare_urls = _rel(ActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
ActorTier.actor = _rel(PornhubActor, foreign_keys=[ActorTier.actor_id])
ActorCompareURL.actor = _rel(PornhubActor, foreign_keys=[ActorCompareURL.actor_id])
ActorTag.actor = _rel(PornhubActor, foreign_keys=[ActorTag.actor_id])

# --- Series → Studio ---
Series.studio = _rel(Studio, foreign_keys=[Series.studio_id])

# --- ActorSubscription / SeriesSubscription ---
ActorSubscription.actor = _rel(PornhubActor, foreign_keys=[ActorSubscription.actor_id])
SeriesSubscription.series = _rel(Series, foreign_keys=[SeriesSubscription.series_id])
