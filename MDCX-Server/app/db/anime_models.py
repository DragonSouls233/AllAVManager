"""
日本里番模块数据模型 (anime.db)
复用 _module_mixins 的规范化表结构，新增 episode（集数）列支撑"同作品相同集数"。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# 里番模块独立 Base（避免跨模块表名冲突）
class ANIME_BASE(DeclarativeBase):
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
class AnimeMovie(MovieMixin, ANIME_BASE):
    """日本里番影片"""
    __tablename__ = "movies"

    # 模块特有：集数（支撑"看同作品相同集数"）
    episode: Mapped[int | None] = mapped_column(Integer, index=True, comment="集数/卷数")


# ===== 演员 =====
class AnimeActor(ActorMixin, ANIME_BASE):
    """里番演员（默认不填充，仅保留表结构以兼容通用视图）"""
    __tablename__ = "actors"


# ===== 关联表 =====
class AnimeMovieActor(MovieActorMixin, ANIME_BASE):
    __tablename__ = "movie_actors"

class AnimeStudio(StudioMixin, ANIME_BASE):
    __tablename__ = "studios"

class AnimeSeries(SeriesMixin, ANIME_BASE):
    __tablename__ = "series"


class AnimeSeriesFavorite(ANIME_BASE):
    """用户标记的「喜好系列」（收藏夹）。

    与 series_subscriptions（订阅/自动下载）职责不同：这里只记录"我喜欢这个系列"，
    用于在「喜好」页聚合，免去在 1400+ 系列里逐个翻找。
    冗余存 series_name：系列记录被删除时仍能显示名字，便于清理。
    """
    __tablename__ = "series_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    series_name: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())
    __table_args__ = (UniqueConstraint("series_id", name="uq_anime_series_favorite"),)

class AnimeTag(TagMixin, ANIME_BASE):
    __tablename__ = "tags"

class AnimeMovieTag(MovieTagMixin, ANIME_BASE):
    __tablename__ = "movie_tags"

class AnimeActorTag(ActorTagMixin, ANIME_BASE):
    __tablename__ = "actor_tags"


# ===== 分级 =====
class AnimeTierConfig(TierConfigMixin, ANIME_BASE):
    __tablename__ = "tier_config"

class AnimeActorTier(ActorTierMixin, ANIME_BASE):
    __tablename__ = "actor_tiers"


# ===== 演员增强 =====
class AnimeActorCompareURL(ActorCompareURLMixin, ANIME_BASE):
    __tablename__ = "actor_compare_urls"

class AnimeActorSubscription(ActorSubscriptionMixin, ANIME_BASE):
    __tablename__ = "actor_subscriptions"


# ===== 系列订阅 =====
class AnimeSeriesSubscription(SeriesSubscriptionMixin, ANIME_BASE):
    __tablename__ = "series_subscriptions"


# ===== 播放 & 导入 & 补刮 =====
class AnimePlayHistory(PlayHistoryMixin, ANIME_BASE):
    __tablename__ = "play_history"

class AnimeImportRecord(ImportRecordMixin, ANIME_BASE):
    __tablename__ = "import_records"

class AnimePatchRecord(PatchRecordMixin, ANIME_BASE):
    __tablename__ = "patch_records"


# ===== 文件整理 =====
class AnimeFileOrganizeJob(FileOrganizeJobMixin, ANIME_BASE):
    __tablename__ = "file_organize_jobs"

class AnimeAutoOrganizeRule(AutoOrganizeRuleMixin, ANIME_BASE):
    __tablename__ = "auto_organize_rules"


# ===== 关联 & 推荐 =====
class AnimeMovieRelation(MovieRelationMixin, ANIME_BASE):
    __tablename__ = "movie_relations"

class AnimeUserRecommendation(UserRecommendationMixin, ANIME_BASE):
    __tablename__ = "user_recommendations"


# ===== 关系声明（跨类 relationship，因 Mixin 无法使用通用类名） =====
from sqlalchemy.orm import relationship as _rel

# --- MovieActor → Movie / Actor ---
AnimeMovieActor.movie = _rel(AnimeMovie, foreign_keys=[AnimeMovieActor.movie_id], back_populates="actors_rel")
AnimeMovieActor.actor = _rel(AnimeActor, foreign_keys=[AnimeMovieActor.actor_id], back_populates="movies")

# --- MovieTag → Movie / Tag ---
AnimeMovieTag.movie = _rel(AnimeMovie, foreign_keys=[AnimeMovieTag.movie_id], back_populates="tags_rel")
AnimeMovieTag.tag = _rel(AnimeTag, foreign_keys=[AnimeMovieTag.tag_id])

# --- PlayHistory / ImportRecord / PatchRecord / FileOrganizeJob → Movie ---
AnimePlayHistory.movie = _rel(AnimeMovie, foreign_keys=[AnimePlayHistory.movie_id])
AnimeImportRecord.movie = _rel(AnimeMovie, foreign_keys=[AnimeImportRecord.movie_id])
AnimePatchRecord.movie = _rel(AnimeMovie, foreign_keys=[AnimePatchRecord.movie_id])
AnimeFileOrganizeJob.movie = _rel(AnimeMovie, foreign_keys=[AnimeFileOrganizeJob.movie_id])

# --- MovieRelation → Movie ---
AnimeMovieRelation.movie = _rel(AnimeMovie, foreign_keys=[AnimeMovieRelation.movie_id])
AnimeMovieRelation.related_movie = _rel(AnimeMovie, foreign_keys=[AnimeMovieRelation.related_movie_id])

# --- UserRecommendation → Movie ---
AnimeUserRecommendation.movie = _rel(AnimeMovie, foreign_keys=[AnimeUserRecommendation.movie_id])

# --- Movie → 关联表 ---
AnimeMovie.actors_rel = _rel(AnimeMovieActor, back_populates="movie", cascade="all, delete-orphan")
AnimeMovie.tags_rel = _rel(AnimeMovieTag, back_populates="movie", cascade="all, delete-orphan")
AnimeMovie.studio_ref = _rel(AnimeStudio, foreign_keys=[AnimeMovie.studio_id])
AnimeMovie.series_ref = _rel(AnimeSeries, foreign_keys=[AnimeMovie.series_id])

# --- Actor → 关联表 ---
AnimeActor.movies = _rel(AnimeMovieActor, back_populates="actor", cascade="all, delete-orphan")
AnimeActor.tags_rel = _rel(AnimeActorTag, back_populates="actor", cascade="all, delete-orphan", foreign_keys=[AnimeActorTag.actor_id])
AnimeActor.tier = _rel(AnimeActorTier, back_populates="actor", uselist=False, cascade="all, delete-orphan")
AnimeActor.compare_urls = _rel(AnimeActorCompareURL, back_populates="actor", cascade="all, delete-orphan")

# --- ActorTier / ActorCompareURL / ActorTag → Actor ---
AnimeActorTier.actor = _rel(AnimeActor, foreign_keys=[AnimeActorTier.actor_id])
AnimeActorCompareURL.actor = _rel(AnimeActor, foreign_keys=[AnimeActorCompareURL.actor_id])
AnimeActorTag.actor = _rel(AnimeActor, foreign_keys=[AnimeActorTag.actor_id])

# --- Series → Studio ---
AnimeSeries.studio = _rel(AnimeStudio, foreign_keys=[AnimeSeries.studio_id])

# --- ActorSubscription / SeriesSubscription ---
AnimeActorSubscription.actor = _rel(AnimeActor, foreign_keys=[AnimeActorSubscription.actor_id])
AnimeSeriesSubscription.series = _rel(AnimeSeries, foreign_keys=[AnimeSeriesSubscription.series_id])


# ============================================================
# 兼容别名：无前缀共享类名（对齐 jav 等模块的命名约定）
# 通用服务用 get_module_model(module, "play_history" / "movie_actor" / ...) 做无前缀
# 类名查找（见 app/utils/module_helper.py::_SHARED_MODEL_CLASSES），里番模块历史遗留把
# 所有表类都加了 "Anime" 前缀，导致 view-status/续播/观影报告等跨模块服务在 anime 上
# AttributeError: module 'app.db.anime_models' has no attribute 'PlayHistory'。
# 这里补无前缀别名，确保 anime 与其他 6 个模块行为一致。
# ============================================================
PlayHistory = AnimePlayHistory
ImportRecord = AnimeImportRecord
PatchRecord = AnimePatchRecord
MovieActor = AnimeMovieActor
Studio = AnimeStudio
Series = AnimeSeries
Tag = AnimeTag
MovieTag = AnimeMovieTag
ActorTag = AnimeActorTag
TierConfig = AnimeTierConfig
ActorTier = AnimeActorTier
ActorCompareURL = AnimeActorCompareURL
ActorSubscription = AnimeActorSubscription
SeriesSubscription = AnimeSeriesSubscription
FileOrganizeJob = AnimeFileOrganizeJob
AutoOrganizeRule = AnimeAutoOrganizeRule
MovieRelation = AnimeMovieRelation
UserRecommendation = AnimeUserRecommendation
