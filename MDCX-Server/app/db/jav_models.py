"""
JAV 有码模块数据模型
番号格式：ABC-123 / IPZZ-219 / SDDE-611
支持 -C(中字)/-UC(无码中字)/-U(无码) 后缀
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.module_db import ModuleBase


class JavMovie(ModuleBase):
    """有码影片模型"""
    __tablename__ = "jav_movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))

    is_chinese: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_uncensored: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_mosaic: Mapped[bool | None] = mapped_column(Boolean, default=True)

    cover_url: Mapped[str | None] = mapped_column(String(500))
    poster_url: Mapped[str | None] = mapped_column(String(500))
    thumb_url: Mapped[str | None] = mapped_column(String(500))
    sample_images: Mapped[str | None] = mapped_column(Text)

    actor: Mapped[str | None] = mapped_column(String(100))
    studio: Mapped[str | None] = mapped_column(String(100))
    series: Mapped[str | None] = mapped_column(String(100))
    label: Mapped[str | None] = mapped_column(String(100))

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


class JavActor(ModuleBase):
    """有码演员表"""
    __tablename__ = "jav_actors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True, unique=True)
    alias: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default="folder")
    source_site: Mapped[str | None] = mapped_column(String(50))
    movie_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
