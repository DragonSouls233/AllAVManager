"""
数据库模型定义
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Movie(Base):
    """视频元数据表"""
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))  # 原始标题（日文/英文）
    title_jp: Mapped[str | None] = mapped_column(String(500))
    studio_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("studios.id", ondelete="SET NULL"), index=True)
    maker: Mapped[str | None] = mapped_column(String(100))
    series_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("series.id", ondelete="SET NULL"), index=True)
    director: Mapped[str | None] = mapped_column(String(100))
    release_date: Mapped[str | None] = mapped_column(String(20), index=True)
    duration: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    plot: Mapped[str | None] = mapped_column(Text)
    plot_short: Mapped[str | None] = mapped_column(String(500))
    genre: Mapped[str | None] = mapped_column(Text)  # JSON 数组
    tag: Mapped[str | None] = mapped_column(Text)  # JSON 数组
    cover_url: Mapped[str | None] = mapped_column(String(500))
    poster_url: Mapped[str | None] = mapped_column(String(500))
    thumb_url: Mapped[str | None] = mapped_column(String(500))
    trailer_url: Mapped[str | None] = mapped_column(String(500))
    sample_images: Mapped[str | None] = mapped_column(Text)  # JSON 数组
    source: Mapped[str | None] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))
    # TMDB 影片 ID（用于 fanart.tv 等外部服务查询，v4.1 C1）
    tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    is_uncensored: Mapped[bool | None] = mapped_column(Boolean)  # 是否无码
    is_mosaic: Mapped[bool | None] = mapped_column(Boolean)
    is_chinese: Mapped[bool | None] = mapped_column(Boolean)
    is_leak: Mapped[bool | None] = mapped_column(Boolean)  # 是否流出/破解版（配合 NFO 后缀 -Leak 识别）
    file_path: Mapped[str | None] = mapped_column(String(1000))
    # 服务端刮削输出目录（迁移 003 已在 DB 加列，此处补齐 ORM 映射）
    output_dir: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_date: Mapped[str | None] = mapped_column(String(30))
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)  # 视频感知哈希，用于去重
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    # v3.0 三态视频标记：browsed（浏览过）/ watched（已观看）/ wanted（想看）/ None（未标记）
    view_status: Mapped[str | None] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime)

    # 关系
    actors: Mapped[list["MovieActor"]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    tags: Mapped[list["MovieTag"]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    studio_ref: Mapped["Studio | None"] = relationship(foreign_keys=[studio_id])
    series_ref: Mapped["Series | None"] = relationship(foreign_keys=[series_id])


class Actor(Base):
    """演员表"""
    __tablename__ = "actors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name_jp: Mapped[str | None] = mapped_column(String(100))
    name_en: Mapped[str | None] = mapped_column(String(100), index=True)  # 英文名（迁移 013）
    alias: Mapped[str | None] = mapped_column(Text)  # 别名（多个用逗号分隔，迁移 013）
    birth_date: Mapped[str | None] = mapped_column(String(20))
    age: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bust: Mapped[int | None] = mapped_column(Integer)
    waist: Mapped[int | None] = mapped_column(Integer)
    hip: Mapped[int | None] = mapped_column(Integer)
    cup: Mapped[str | None] = mapped_column(String(5))
    birthplace: Mapped[str | None] = mapped_column(String(100))
    hobby: Mapped[str | None] = mapped_column(String(500))
    intro: Mapped[str | None] = mapped_column(Text)  # 简介（迁移 013）
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(50))  # 资料来源（迁移 013）
    source_url: Mapped[str | None] = mapped_column(String(500))  # 来源 URL（迁移 013）
    zodiac: Mapped[str | None] = mapped_column(String(20))  # 星座（迁移 014）
    debut_year: Mapped[int | None] = mapped_column(Integer)  # 出道年份（迁移 014）
    social_links: Mapped[str | None] = mapped_column(Text)  # 社交账号 JSON（迁移 014）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    movies: Mapped[list["MovieActor"]] = relationship(back_populates="actor", cascade="all, delete-orphan")
    tags: Mapped[list["ActorTag"]] = relationship(back_populates="actor", cascade="all, delete-orphan",
                                                   foreign_keys="ActorTag.actor_id")


class MovieActor(Base):
    """视频-演员关联表"""
    __tablename__ = "movie_actors"
    __table_args__ = (
        UniqueConstraint("movie_id", "actor_id", name="uq_movie_actor"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str | None] = mapped_column(String(50))

    # 关系
    movie: Mapped["Movie"] = relationship(back_populates="actors")
    actor: Mapped["Actor"] = relationship(back_populates="movies")


class Tag(Base):
    """标签表"""
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(50))  # 分类: genre/theme/style 等
    color: Mapped[str | None] = mapped_column(String(20))  # 标签颜色
    is_user: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # True=用户标签 / False=抓取标签
    movie_count: Mapped[int] = mapped_column(Integer, default=0)  # 冗余计数
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 关系
    movies: Mapped[list["MovieTag"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class MovieTag(Base):
    """视频-标签关联表"""
    __tablename__ = "movie_tags"
    __table_args__ = (
        UniqueConstraint("movie_id", "tag_id", name="uq_movie_tag"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)

    # 关系
    movie: Mapped["Movie"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship(back_populates="movies")


class ActorTag(Base):
    """演员标签表（迁移 015）

    支持自由文本标签（如"业界第一"/"传奇"/"国民老婆"等），
    与结构化的 Tier 分级系统（S/A/B/C/D）互补。
    """
    __tablename__ = "actor_tags"
    __table_args__ = (
        UniqueConstraint("actor_id", "name", name="uq_actor_tag"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # 标签名
    color: Mapped[str | None] = mapped_column(String(20))  # 标签颜色
    is_user: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # True=用户标签 / False=系统标签
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 关系
    actor: Mapped["Actor"] = relationship(back_populates="tags", foreign_keys=[actor_id])


class Studio(Base):
    """厂商/工作室表"""
    __tablename__ = "studios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name_jp: Mapped[str | None] = mapped_column(String(100))
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class Series(Base):
    """系列表"""
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    name_jp: Mapped[str | None] = mapped_column(String(200))
    studio_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("studios.id", ondelete="SET NULL"))
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 关系
    studio: Mapped["Studio | None"] = relationship()


class Task(Base):
    """任务表"""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    movie_code: Mapped[str | None] = mapped_column(String(50), index=True)
    file_path: Mapped[str | None] = mapped_column(String(1000))
    site: Mapped[str | None] = mapped_column(String(50))
    options: Mapped[str | None] = mapped_column(Text)  # JSON
    result: Mapped[str | None] = mapped_column(Text)  # JSON
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class ImportRecord(Base):
    """导入记录表"""
    __tablename__ = "import_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    movie_code: Mapped[str | None] = mapped_column(String(50), index=True)
    movie_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("movies.id", ondelete="SET NULL"))
    source_type: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    imported_fields: Mapped[str | None] = mapped_column(Text)  # JSON
    conflict: Mapped[str | None] = mapped_column(String(50))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)


class PatchRecord(Base):
    """补刮记录表"""
    __tablename__ = "patch_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    missing_fields: Mapped[str | None] = mapped_column(Text)  # JSON
    missing_images: Mapped[str | None] = mapped_column(Text)  # JSON
    patch_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    result: Mapped[str | None] = mapped_column(Text)  # JSON
    patched_at: Mapped[datetime | None] = mapped_column(DateTime)


class Workflow(Base):
    """工作流表"""
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class Setting(Base):
    """设置表"""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class Cache(Base):
    """通用缓存表"""
    __tablename__ = "cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class Migration(Base):
    """数据库迁移记录表"""
    __tablename__ = "migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class FavoriteGroup(Base):
    """收藏夹（支持 movie/actor/studio/series 四类实体）"""
    __tablename__ = "favorite_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # movie/actor/studio/series
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 关系
    items: Mapped[list["FavoriteItem"]] = relationship(back_populates="group", cascade="all, delete-orphan", order_by="FavoriteItem.sort_order")


class FavoriteItem(Base):
    """收藏夹条目"""
    __tablename__ = "favorite_items"
    __table_args__ = (
        UniqueConstraint("group_id", "entity_id", name="uq_favorite_item"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("favorite_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)  # Movie/Actor/Studio/Series 的 ID
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 冗余存一份，方便查询
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 关系
    group: Mapped["FavoriteGroup"] = relationship(back_populates="items")


# ============================================
# Tier 分级系统（参考 JATLAS）
# ============================================

class TierConfig(Base):
    """分级档位全局配置"""
    __tablename__ = "tier_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tier: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)  # S/A/B/C/D
    name: Mapped[str] = mapped_column(String(20), nullable=False)  # 神话/传奇/优秀/普通/收藏
    max_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 表示无上限
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#95A5A6")  # 显示颜色
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ActorTier(Base):
    """演员分级（每个演员一个 tier）"""
    __tablename__ = "actor_tiers"
    __table_args__ = (
        UniqueConstraint("actor_id", name="uq_actor_tier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(2), nullable=False, default="D")  # S/A/B/C/D
    max_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 表示用全局配置
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    actor: Mapped["Actor"] = relationship()


class AssetChangeLog(Base):
    """资产变化日志"""
    __tablename__ = "asset_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # movie/actor/tag/studio/series
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_name: Mapped[str | None] = mapped_column(String(200))
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)  # added/removed/tier_changed/rating_changed/scraped
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)


class ActorCompareURL(Base):
    """演员对比URL配置表：每个演员可配置对应的JavBus/JavDB演员页URL和本地目录"""
    __tablename__ = "actor_compare_urls"
    __table_args__ = (
        UniqueConstraint("actor_id", "source", name="uq_actor_compare_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # javbus/javdb
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    local_directory: Mapped[str | None] = mapped_column(String(500))
    auto_detected_dir: Mapped[bool] = mapped_column(Boolean, default=False)
    last_compare_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


# ===== 多用户权限 / 观影历史 / 演员订阅 =====

class User(Base):
    """用户表（多用户权限）"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)  # admin / user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    nsfw_allowed: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否允许成人内容
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class UserSession(Base):
    """用户会话表（设备管理）"""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)  # JWT 或 session token
    device_name: Mapped[str | None] = mapped_column(String(100))  # 设备名
    device_type: Mapped[str | None] = mapped_column(String(30))  # web/desktop/mobile
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PlayHistory(Base):
    """观影历史记录（用于 AI 观影报告）"""
    __tablename__ = "play_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_code: Mapped[str] = mapped_column(String(50), index=True)  # 冗余：影片番号
    duration_watched: Mapped[int] = mapped_column(Integer, default=0)  # 本次观看秒数
    total_duration: Mapped[int | None] = mapped_column(Integer)  # 影片总时长
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 播放进度 0-1
    completed: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否看完
    played_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(50))


class ActorSubscription(Base):
    """演员订阅（新片监控）"""
    __tablename__ = "actor_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "actor_id", name="uq_user_actor_subscription"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # NULL=全局订阅
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False, index=True)
    notify_new_movie: Mapped[bool] = mapped_column(Boolean, default=True)  # 新片通知
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动下载（迁移 016）
    preferred_quality: Mapped[str] = mapped_column(String(20), default="1080p")  # 偏好画质（迁移 016）
    preferred_tags: Mapped[str | None] = mapped_column(Text)  # 偏好标签（JSON，迁移 016）
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)  # 上次检查时间
    last_movie_count: Mapped[int] = mapped_column(Integer, default=0)  # 上次检查时的影片数
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class FileOrganizeJob(Base):
    """文件整理任务（v3.0：5 种整理模式）

    job_type 取值：
    - hardlink: 硬链接（同盘符，不占额外空间）
    - copy: 复制（跨盘符或需独立副本）
    - move: 移动（迁移到目标目录）
    - symlink: 软链接（符号链接，跨盘符可用）
    - rename: 原地点名（仅重命名，不改变目录）
    """
    __tablename__ = "file_organize_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # hardlink/copy/move/symlink/rename
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    target_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    movie_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("movies.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/running/completed/failed/skipped
    conflict_strategy: Mapped[str] = mapped_column(String(20), default="skip")  # skip/overwrite/rename
    error_message: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ===== v4.1 系列订阅 / 自动整理规则 / 影片关联图谱 / AI 推荐 =====

class SeriesSubscription(Base):
    """系列订阅（迁移 016，新片监控与自动下载）"""
    __tablename__ = "series_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "series_id", name="uq_user_series_subscription"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # NULL=全局订阅
    series_id: Mapped[int] = mapped_column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    notify_new_movie: Mapped[bool] = mapped_column(Boolean, default=True)  # 新片通知
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动下载
    preferred_quality: Mapped[str] = mapped_column(String(20), default="1080p")  # 偏好画质
    preferred_tags: Mapped[str | None] = mapped_column(Text)  # 偏好标签（JSON）
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)  # 上次检查时间
    last_movie_count: Mapped[int] = mapped_column(Integer, default=0)  # 上次检查时的影片数
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AutoOrganizeRule(Base):
    """自动整理规则（迁移 016，条件触发的文件整理）"""
    __tablename__ = "auto_organize_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # 规则名称
    condition_field: Mapped[str] = mapped_column(String(50), nullable=False)  # 条件字段
    condition_op: Mapped[str] = mapped_column(String(20), nullable=False)  # 条件操作符（eq/contains/regex 等）
    condition_value: Mapped[str] = mapped_column(String(500), nullable=False)  # 条件值
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # 动作（move/copy/hardlink/symlink 等）
    target_path: Mapped[str | None] = mapped_column(String(1000))  # 目标路径
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否启用
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class MovieRelation(Base):
    """影片关联图谱（迁移 016，影片间的关系，用于推荐）"""
    __tablename__ = "movie_relations"
    __table_args__ = (
        UniqueConstraint("movie_id", "related_movie_id", "relation_type", name="uq_movie_relation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    related_movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 关系类型（same_series/same_actor/same_studio 等）
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # 关系权重
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class UserRecommendation(Base):
    """AI 推荐结果（迁移 016，基于用户行为的个性化推荐）"""
    __tablename__ = "user_recommendations"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_user_movie_recommendation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # NULL=全局推荐
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 推荐分数（0-1）
    reason: Mapped[str | None] = mapped_column(Text)  # 推荐理由
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否被用户忽略
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
