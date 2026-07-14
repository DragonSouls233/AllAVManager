"""
FC2 模块数据模型
番号格式：FC2-123456 / FC2PPV-123456 / 123456
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.module_db import ModuleBase


class Fc2Movie(ModuleBase):
    """FC2 影片模型"""
    __tablename__ = "fc2_movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))

    is_mosaic: Mapped[bool | None] = mapped_column(Boolean)
    seller_id: Mapped[str | None] = mapped_column(String(50))

    cover_url: Mapped[str | None] = mapped_column(String(500))
    poster_url: Mapped[str | None] = mapped_column(String(500))
    thumb_url: Mapped[str | None] = mapped_column(String(500))
    sample_images: Mapped[str | None] = mapped_column(Text)

    actor: Mapped[str | None] = mapped_column(String(100))
    studio: Mapped[str | None] = mapped_column(String(100))

    release_date: Mapped[str | None] = mapped_column(String(20))
    duration: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    plot: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(Text)
    tag: Mapped[str | None] = mapped_column(Text)
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
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime)


class Fc2Actor(ModuleBase):
    """FC2 演员表"""
    __tablename__ = "fc2_actors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True, unique=True)
    alias: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default="scraper")
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
