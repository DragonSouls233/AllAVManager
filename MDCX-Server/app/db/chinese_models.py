"""
国产模块数据模型 (chinese.db)
"""
from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class CHINESE_BASE(DeclarativeBase):
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


class ChineseMovie(MovieMixin, CHINESE_BASE):
    """国产影片"""
    __tablename__ = "movies"

    folder_name: Mapped[str | None] = mapped_column(String(200), index=True)
    folder_based_actors: Mapped[str | None] = mapped_column(Text)
    extracted_actor: Mapped[str | None] = mapped_column(String(100))


class ChineseActor(ActorMixin, CHINESE_BASE):
    """国产演员"""
    __tablename__ = "actors"

    # 国产特有：演员所属工作室/平台
    studio: Mapped[str | None] = mapped_column(String(100))


class MovieActor(MovieActorMixin, CHINESE_BASE):
    __tablename__ = "movie_actors"

class Studio(StudioMixin, CHINESE_BASE):
    __tablename__ = "studios"

class Series(SeriesMixin, CHINESE_BASE):
    __tablename__ = "series"

class Tag(TagMixin, CHINESE_BASE):
    __tablename__ = "tags"

class MovieTag(MovieTagMixin, CHINESE_BASE):
    __tablename__ = "movie_tags"

class ActorTag(ActorTagMixin, CHINESE_BASE):
    __tablename__ = "actor_tags"

class TierConfig(TierConfigMixin, CHINESE_BASE):
    __tablename__ = "tier_config"

class ActorTier(ActorTierMixin, CHINESE_BASE):
    __tablename__ = "actor_tiers"

class ActorCompareURL(ActorCompareURLMixin, CHINESE_BASE):
    __tablename__ = "actor_compare_urls"

class ActorSubscription(ActorSubscriptionMixin, CHINESE_BASE):
    __tablename__ = "actor_subscriptions"

class SeriesSubscription(SeriesSubscriptionMixin, CHINESE_BASE):
    __tablename__ = "series_subscriptions"

class PlayHistory(PlayHistoryMixin, CHINESE_BASE):
    __tablename__ = "play_history"

class ImportRecord(ImportRecordMixin, CHINESE_BASE):
    __tablename__ = "import_records"

class PatchRecord(PatchRecordMixin, CHINESE_BASE):
    __tablename__ = "patch_records"

class FileOrganizeJob(FileOrganizeJobMixin, CHINESE_BASE):
    __tablename__ = "file_organize_jobs"

class AutoOrganizeRule(AutoOrganizeRuleMixin, CHINESE_BASE):
    __tablename__ = "auto_organize_rules"

class MovieRelation(MovieRelationMixin, CHINESE_BASE):
    __tablename__ = "movie_relations"

class UserRecommendation(UserRecommendationMixin, CHINESE_BASE):
    __tablename__ = "user_recommendations"
# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
MovieActor.movie = _rel(ChineseMovie, foreign_keys=[MovieActor.movie_id], back_populates="actors")
MovieActor.actor = _rel(ChineseActor, foreign_keys=[MovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
MovieTag.movie = _rel(ChineseMovie, foreign_keys=[MovieTag.movie_id], back_populates="tags_rel")
MovieTag.tag = _rel(Tag, foreign_keys=[MovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
PlayHistory.movie = _rel(ChineseMovie, foreign_keys=[PlayHistory.movie_id])
ImportRecord.movie = _rel(ChineseMovie, foreign_keys=[ImportRecord.movie_id])
PatchRecord.movie = _rel(ChineseMovie, foreign_keys=[PatchRecord.movie_id])
FileOrganizeJob.movie = _rel(ChineseMovie, foreign_keys=[FileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
MovieRelation.movie = _rel(ChineseMovie, foreign_keys=[MovieRelation.movie_id])
MovieRelation.related_movie = _rel(ChineseMovie, foreign_keys=[MovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
UserRecommendation.movie = _rel(ChineseMovie, foreign_keys=[UserRecommendation.movie_id])

# --- Movie → 关联表 ---
ChineseMovie.actors = _rel(MovieActor, back_populates="movie", cascade="all, delete-orphan")
ChineseMovie.tags_rel = _rel(MovieTag, back_populates="movie", cascade="all, delete-orphan")
ChineseMovie.studio_ref = _rel(Studio, foreign_keys=[ChineseMovie.studio_id])
ChineseMovie.series_ref = _rel(Series, foreign_keys=[ChineseMovie.series_id])

# --- Actor → 关联表 ---
ChineseActor.movies = _rel(MovieActor, back_populates="actor", cascade="all, delete-orphan")
ChineseActor.tags_rel = _rel(ActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[ActorTag.actor_id])
ChineseActor.tier = _rel(ActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
ChineseActor.compare_urls = _rel(ActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
ActorTier.actor = _rel(ChineseActor, foreign_keys=[ActorTier.actor_id])
ActorCompareURL.actor = _rel(ChineseActor, foreign_keys=[ActorCompareURL.actor_id])
ActorTag.actor = _rel(ChineseActor, foreign_keys=[ActorTag.actor_id])

# --- Series → Studio ---
Series.studio = _rel(Studio, foreign_keys=[Series.studio_id])

# --- ActorSubscription / SeriesSubscription ---
ActorSubscription.actor = _rel(ChineseActor, foreign_keys=[ActorSubscription.actor_id])
SeriesSubscription.series = _rel(Series, foreign_keys=[SeriesSubscription.series_id])
