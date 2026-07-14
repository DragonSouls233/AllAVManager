"""
PORNHub 模块数据模型
番号格式：ph1234567890abcdef（viewkey）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.module_db import ModuleBase


class PornhubMovie(ModuleBase):
    """PORNHub 影片模型"""
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))

    source_id: Mapped[str | None] = mapped_column(String(100))
    source_views: Mapped[int | None] = mapped_column(Integer)
    source_score: Mapped[float | None] = mapped_column(Float)
    source_downloads: Mapped[int | None] = mapped_column(Integer)
    uploader: Mapped[str | None] = mapped_column(String(100))

    cover_url: Mapped[str | None] = mapped_column(String(500))
    poster_url: Mapped[str | None] = mapped_column(String(500))
    thumb_url: Mapped[str | None] = mapped_column(String(500))
    trailer_url: Mapped[str | None] = mapped_column(String(500))
    sample_images: Mapped[str | None] = mapped_column(Text)

    actor: Mapped[str | None] = mapped_column(String(100))
    studio: Mapped[str | None] = mapped_column(String(100))
    categories: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(Text)

    release_date: Mapped[str | None] = mapped_column(String(20))
    duration: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    plot: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str | None] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))

    file_path: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64))

    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    view_status: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class PornhubActor(ModuleBase):
    """PORNHub 演员表"""
    __tablename__ = "pornhub_actors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True, unique=True)
    alias: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default="scraper")
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
