"""
FC2 模块数据模型 (fc2.db)
"""
from datetime import datetime

from sqlalchemy import Boolean, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# FC2 模块独立 Base
class FC2_BASE(DeclarativeBase):
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


class Fc2Movie(MovieMixin, FC2_BASE):
    """FC2 影片"""
    __tablename__ = "movies"

    is_mosaic: Mapped[bool | None] = mapped_column(Boolean)
    is_chinese: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 中文字幕版（-C/-UC 后缀）
    is_uncensored: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 无码版（-U/-UC 后缀）
    is_leak: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 流出/破解版
    is_4k: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 4K 分辨率版
    seller_id: Mapped[str | None] = mapped_column(String(50))


class Fc2Actor(ActorMixin, FC2_BASE):
    """FC2 演员"""
    __tablename__ = "actors"


class MovieActor(MovieActorMixin, FC2_BASE):
    __tablename__ = "movie_actors"

class Studio(StudioMixin, FC2_BASE):
    __tablename__ = "studios"

class Series(SeriesMixin, FC2_BASE):
    __tablename__ = "series"

class Tag(TagMixin, FC2_BASE):
    __tablename__ = "tags"

class MovieTag(MovieTagMixin, FC2_BASE):
    __tablename__ = "movie_tags"

class ActorTag(ActorTagMixin, FC2_BASE):
    __tablename__ = "actor_tags"

class TierConfig(TierConfigMixin, FC2_BASE):
    __tablename__ = "tier_config"

class ActorTier(ActorTierMixin, FC2_BASE):
    __tablename__ = "actor_tiers"

class ActorCompareURL(ActorCompareURLMixin, FC2_BASE):
    __tablename__ = "actor_compare_urls"

class ActorSubscription(ActorSubscriptionMixin, FC2_BASE):
    __tablename__ = "actor_subscriptions"

class SeriesSubscription(SeriesSubscriptionMixin, FC2_BASE):
    __tablename__ = "series_subscriptions"

class PlayHistory(PlayHistoryMixin, FC2_BASE):
    __tablename__ = "play_history"

class ImportRecord(ImportRecordMixin, FC2_BASE):
    __tablename__ = "import_records"

class PatchRecord(PatchRecordMixin, FC2_BASE):
    __tablename__ = "patch_records"

class FileOrganizeJob(FileOrganizeJobMixin, FC2_BASE):
    __tablename__ = "file_organize_jobs"

class AutoOrganizeRule(AutoOrganizeRuleMixin, FC2_BASE):
    __tablename__ = "auto_organize_rules"

class MovieRelation(MovieRelationMixin, FC2_BASE):
    __tablename__ = "movie_relations"

class UserRecommendation(UserRecommendationMixin, FC2_BASE):
    __tablename__ = "user_recommendations"
# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
MovieActor.movie = _rel(Fc2Movie, foreign_keys=[MovieActor.movie_id], back_populates="actors")
MovieActor.actor = _rel(Fc2Actor, foreign_keys=[MovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
MovieTag.movie = _rel(Fc2Movie, foreign_keys=[MovieTag.movie_id], back_populates="tags_rel")
MovieTag.tag = _rel(Tag, foreign_keys=[MovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
PlayHistory.movie = _rel(Fc2Movie, foreign_keys=[PlayHistory.movie_id])
ImportRecord.movie = _rel(Fc2Movie, foreign_keys=[ImportRecord.movie_id])
PatchRecord.movie = _rel(Fc2Movie, foreign_keys=[PatchRecord.movie_id])
FileOrganizeJob.movie = _rel(Fc2Movie, foreign_keys=[FileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
MovieRelation.movie = _rel(Fc2Movie, foreign_keys=[MovieRelation.movie_id])
MovieRelation.related_movie = _rel(Fc2Movie, foreign_keys=[MovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
UserRecommendation.movie = _rel(Fc2Movie, foreign_keys=[UserRecommendation.movie_id])

# --- Movie → 关联表 ---
Fc2Movie.actors = _rel(MovieActor, back_populates="movie", cascade="all, delete-orphan")
Fc2Movie.tags_rel = _rel(MovieTag, back_populates="movie", cascade="all, delete-orphan")
Fc2Movie.studio_ref = _rel(Studio, foreign_keys=[Fc2Movie.studio_id])
Fc2Movie.series_ref = _rel(Series, foreign_keys=[Fc2Movie.series_id])

# --- Actor → 关联表 ---
Fc2Actor.movies = _rel(MovieActor, back_populates="actor", cascade="all, delete-orphan")
Fc2Actor.tags_rel = _rel(ActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[ActorTag.actor_id])
Fc2Actor.tier = _rel(ActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
Fc2Actor.compare_urls = _rel(ActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
ActorTier.actor = _rel(Fc2Actor, foreign_keys=[ActorTier.actor_id])
ActorCompareURL.actor = _rel(Fc2Actor, foreign_keys=[ActorCompareURL.actor_id])
ActorTag.actor = _rel(Fc2Actor, foreign_keys=[ActorTag.actor_id])

# --- Series → Studio ---
Series.studio = _rel(Studio, foreign_keys=[Series.studio_id])

# --- ActorSubscription / SeriesSubscription ---
ActorSubscription.actor = _rel(Fc2Actor, foreign_keys=[ActorSubscription.actor_id])
SeriesSubscription.series = _rel(Series, foreign_keys=[SeriesSubscription.series_id])
