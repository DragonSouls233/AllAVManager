"""
模块数据库共享基类 (Mixin) v2.1
所有 6 个模块的 Movie/Actor 及关联表均继承自此文件定义的抽象基类。
每个模块文件只需 import 对应 Mixin 并创建具体类，无需重复定义列。

注意：Mixin 中不定义跨类 relationship（如 MovieActor → Movie），因为各模块的 Movie 类名不同（JavMovie / Fc2Movie / ...）。
这些 relationship 在每个模块文件的末尾显式声明。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr


# ======================================================================
# Movie Mixin
# ======================================================================

class MovieMixin:
    """影片表通用列定义"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))
    director: Mapped[str | None] = mapped_column(String(100))
    release_date: Mapped[str | None] = mapped_column(String(20), index=True)
    duration: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    plot: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(Text)   # JSON
    tag: Mapped[str | None] = mapped_column(Text)      # JSON

    # 冗余文本缓存（向后兼容路由的直接字符串访问）
    actor: Mapped[str | None] = mapped_column(Text)      # 逗号分隔演员名
    studio: Mapped[str | None] = mapped_column(String(200))  # 厂商名文本
    series: Mapped[str | None] = mapped_column(String(200))  # 系列名文本
    maker: Mapped[str | None] = mapped_column(String(100))   # 制作商文本

    # 图片
    cover_url: Mapped[str | None] = mapped_column(String(500))
    poster_url: Mapped[str | None] = mapped_column(String(500))
    thumb_url: Mapped[str | None] = mapped_column(String(500))
    trailer_url: Mapped[str | None] = mapped_column(String(500))
    sample_images: Mapped[str | None] = mapped_column(Text)

    # 来源
    source: Mapped[str | None] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))

    # 文件
    file_path: Mapped[str | None] = mapped_column(String(1000))
    output_dir: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)

    # 播放状态
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    view_status: Mapped[str | None] = mapped_column(String(20), index=True)

    # 状态
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime)

    # 外键列
    @declared_attr
    def studio_id(cls) -> Mapped[int | None]:
        return mapped_column(Integer, ForeignKey("studios.id", ondelete="SET NULL"), index=True)

    @declared_attr
    def series_id(cls) -> Mapped[int | None]:
        return mapped_column(Integer, ForeignKey("series.id", ondelete="SET NULL"), index=True)


# ======================================================================
# Actor Mixin
# ======================================================================

class ActorMixin:
    """演员表通用列定义"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True, unique=True)
    name_jp: Mapped[str | None] = mapped_column(String(100))
    name_en: Mapped[str | None] = mapped_column(String(100), index=True)
    alias: Mapped[str | None] = mapped_column(Text)
    birth_date: Mapped[str | None] = mapped_column(String(20))
    age: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[str | None] = mapped_column(String(20))
    bust: Mapped[int | None] = mapped_column(Integer)
    waist: Mapped[int | None] = mapped_column(Integer)
    hip: Mapped[int | None] = mapped_column(Integer)
    cup: Mapped[str | None] = mapped_column(String(5))
    birthplace: Mapped[str | None] = mapped_column(String(100))
    hobby: Mapped[str | None] = mapped_column(String(500))
    intro: Mapped[str | None] = mapped_column(Text)
    zodiac: Mapped[str | None] = mapped_column(String(20))
    debut_year: Mapped[int | None] = mapped_column(Integer)
    social_links: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(50))
    source_site: Mapped[str | None] = mapped_column(String(50))
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


# ======================================================================
# 关联表 Mixin（仅列定义，不含跨类 relationship—由模块文件声明）
# ======================================================================

class MovieActorMixin:
    """影片-演员关联表"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str | None] = mapped_column(String(50))
    __table_args__ = (
        UniqueConstraint("movie_id", "actor_id", name="uq_movie_actor"),
        {"sqlite_autoincrement": True},
    )

    @declared_attr
    def movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    @declared_attr
    def actor_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)


class StudioMixin:
    """厂商/工作室表"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    name_jp: Mapped[str | None] = mapped_column(String(100))
    alias: Mapped[str | None] = mapped_column(Text)
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class SeriesMixin:
    """系列表"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    name_jp: Mapped[str | None] = mapped_column(String(200))
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    @declared_attr
    def studio_id(cls) -> Mapped[int | None]:
        return mapped_column(Integer, ForeignKey("studios.id", ondelete="SET NULL"))


class TagMixin:
    """标签表"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(50))
    color: Mapped[str | None] = mapped_column(String(20))
    is_user: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class MovieTagMixin:
    """影片-标签关联表"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    __table_args__ = (
        UniqueConstraint("movie_id", "tag_id", name="uq_movie_tag"),
        {"sqlite_autoincrement": True},
    )

    @declared_attr
    def movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    @declared_attr
    def tag_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)


class ActorTagMixin:
    """演员标签表"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    color: Mapped[str | None] = mapped_column(String(20))
    is_user: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    __table_args__ = (
        UniqueConstraint("actor_id", "name", name="uq_actor_tag"),
        {"sqlite_autoincrement": True},
    )

    @declared_attr
    def actor_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)


# ======================================================================
# Tier 分级 Mixin
# ======================================================================

class TierConfigMixin:
    """分级档位配置"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tier: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    max_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#95A5A6")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ActorTierMixin:
    """演员分级"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tier: Mapped[str] = mapped_column(String(2), nullable=False, default="D")
    max_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("actor_id", name="uq_actor_tier"),
    )

    @declared_attr
    def actor_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)


# ======================================================================
# 其他辅助表 Mixin
# ======================================================================

class ActorCompareURLMixin:
    """演员对比 URL"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    local_directory: Mapped[str | None] = mapped_column(String(500))
    auto_detected_dir: Mapped[bool] = mapped_column(Boolean, default=False)
    last_compare_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("actor_id", "source", name="uq_actor_compare_source"),
    )

    @declared_attr
    def actor_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)


class PlayHistoryMixin:
    """播放历史"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    movie_code: Mapped[str] = mapped_column(String(50), index=True)
    duration_watched: Mapped[int] = mapped_column(Integer, default=0)
    total_duration: Mapped[int | None] = mapped_column(Integer)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(50))

    @declared_attr
    def movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)


class ImportRecordMixin:
    """导入记录"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    movie_code: Mapped[str | None] = mapped_column(String(50), index=True)
    source_type: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    imported_fields: Mapped[str | None] = mapped_column(Text)
    conflict: Mapped[str | None] = mapped_column(String(50))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)

    @declared_attr
    def movie_id(cls) -> Mapped[int | None]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="SET NULL"), index=True)


class PatchRecordMixin:
    """补刮记录"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    missing_fields: Mapped[str | None] = mapped_column(Text)
    missing_images: Mapped[str | None] = mapped_column(Text)
    patch_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    result: Mapped[str | None] = mapped_column(Text)
    patched_at: Mapped[datetime | None] = mapped_column(DateTime)

    @declared_attr
    def movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)


class FileOrganizeJobMixin:
    """文件整理任务"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    target_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    conflict_strategy: Mapped[str] = mapped_column(String(20), default="skip")
    error_message: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    @declared_attr
    def movie_id(cls) -> Mapped[int | None]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="SET NULL"), index=True)


class AutoOrganizeRuleMixin:
    """自动整理规则"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    condition_field: Mapped[str] = mapped_column(String(50), nullable=False)
    condition_op: Mapped[str] = mapped_column(String(20), nullable=False)
    condition_value: Mapped[str] = mapped_column(String(500), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_path: Mapped[str | None] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class MovieRelationMixin:
    """影片关联"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    __table_args__ = (
        UniqueConstraint("movie_id", "related_movie_id", "relation_type", name="uq_movie_relation"),
    )

    @declared_attr
    def movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    @declared_attr
    def related_movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)


class UserRecommendationMixin:
    """AI 推荐"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_user_movie_recommendation"),
    )

    @declared_attr
    def movie_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)


class ActorSubscriptionMixin:
    """演员订阅"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    notify_new_movie: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_quality: Mapped[str] = mapped_column(String(20), default="1080p")
    preferred_tags: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "actor_id", name="uq_user_actor_subscription"),
    )

    @declared_attr
    def actor_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)


class SeriesSubscriptionMixin:
    """系列订阅"""
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    notify_new_movie: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_quality: Mapped[str] = mapped_column(String(20), default="1080p")
    preferred_tags: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "series_id", name="uq_user_series_subscription"),
    )

    @declared_attr
    def series_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
