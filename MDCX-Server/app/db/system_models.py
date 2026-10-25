"""
系统数据库模型 (system.db)
管理跨模块的全局数据：用户、认证、设置、任务、收藏夹等
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class SystemBase(DeclarativeBase):
    """系统库 SQLAlchemy 基类"""
    pass


# ========== 用户与认证 ==========

class User(SystemBase):
    """用户表（多用户权限）"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)  # admin / user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    nsfw_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class UserSession(SystemBase):
    """用户会话表"""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    device_name: Mapped[str | None] = mapped_column(String(100))
    device_type: Mapped[str | None] = mapped_column(String(30))
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ========== 全局配置 ==========

class Setting(SystemBase):
    """Key-Value 全局设置"""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class Cache(SystemBase):
    """通用缓存表"""
    __tablename__ = "cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ========== 任务与工作流 ==========

class Task(SystemBase):
    """任务队列"""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    movie_code: Mapped[str | None] = mapped_column(String(50), index=True)
    file_path: Mapped[str | None] = mapped_column(String(1000))
    site: Mapped[str | None] = mapped_column(String(50))
    module: Mapped[str | None] = mapped_column(String(20), index=True)  # 新增: 模块名
    options: Mapped[str | None] = mapped_column(Text)  # JSON
    result: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class Workflow(SystemBase):
    """工作流定义"""
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


# ========== 扫描记录 ==========

class ScanRecord(SystemBase):
    """扫描记录（跨模块）"""
    __tablename__ = "scan_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    module_name: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    total_files: Mapped[int | None] = mapped_column(Integer)
    added_files: Mapped[int | None] = mapped_column(Integer)
    removed_files: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ========== 资产变更日志 ==========

class AssetChangeLog(SystemBase):
    """全局资产变更日志"""
    __tablename__ = "asset_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module: Mapped[str | None] = mapped_column(String(20), index=True)  # 新增: 模块名
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_name: Mapped[str | None] = mapped_column(String(200))
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)


# ========== 跨模块收藏夹 ==========

class FavoriteGroup(SystemBase):
    """收藏夹分组"""
    __tablename__ = "favorite_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    items: Mapped[list["FavoriteItem"]] = relationship(
        back_populates="group", cascade="all, delete-orphan",
        order_by="FavoriteItem.sort_order",
    )


class FavoriteItem(SystemBase):
    """收藏夹条目（跨模块：module 字段标识来源模块）"""
    __tablename__ = "favorite_items"
    __table_args__ = (
        UniqueConstraint("group_id", "entity_id", "module", name="uq_favorite_item"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("favorite_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False, default="", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    group: Mapped["FavoriteGroup"] = relationship(back_populates="items")


# ========== 想要清单（待找的片子） ==========

class WantsItem(SystemBase):
    """想要清单：还没找到的片子，按番号记录（跨模块）

    与 FavoriteItem（已入库实体的收藏夹）互补：本表存**尚未入库**的番号，
    用户手动记下；找到/入库后标记 found。设计要点：
    - normalized_code 为匹配键（大写去空白），用户输 ssis-001 与 SSIS-001
      视为同一条；唯一约束 (user_id, normalized_code) 防重复记
    - magnet 字段：找到资源（磁链）时先存着，对应 peach wants_magnets 的思路
    - status: wanted（想要中）/ found（已找到）/ dropped（不想要了）
    - 检查接口实时查各模块 movies 表，标出 in_library / chinese_available
      （该 base 番号已有中字版入库）——后者是订阅中字替换的判定基础
    """
    __tablename__ = "wants_items"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_code", name="uq_wants_user_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)  # None = 全局清单
    code: Mapped[str] = mapped_column(String(100), nullable=False)  # 用户输入的原始番号
    normalized_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))  # 备注标题
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="wanted", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 0 普通 / 1 想要
    magnet: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


# ========== 播放列表（跨模块连播队列） ==========

class Playlist(SystemBase):
    """播放列表：跨模块的连播队列（jav + PH 可以混在一个列表里）

    与 wants（未入库待找）不同：本表存**已入库影片**的播放队列。
    mpv 原生支持多文件连播，播放时按 sort_order 依次传文件路径。
    """
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)  # None = 全局
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    items: Mapped[list["PlaylistItem"]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan",
        order_by="PlaylistItem.sort_order",
    )


class PlaylistItem(SystemBase):
    """播放列表条目：(module, movie_id) 定位跨模块影片"""
    __tablename__ = "playlist_items"
    __table_args__ = (
        UniqueConstraint("playlist_id", "module", "movie_id", name="uq_playlist_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(String(20), nullable=False, default="jav", index=True)
    movie_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    playlist: Mapped["Playlist"] = relationship(back_populates="items")


# ========== 数据库迁移记录 ==========

class Migration(SystemBase):
    """系统库迁移版本记录"""
    __tablename__ = "migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
