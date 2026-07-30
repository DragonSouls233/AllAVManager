"""
缺失检测器

检测已有刮削内容的缺失字段和图片
支持：
- 字段级检测：title, plot, genre, actor, rating, releaseDate...
- 图片级检测：poster, fanart, thumb, extrafanart, actors
- NFO 文件存在性检测
- 演员头像缺失检测

数据库模式：
1. 中心数据库模式（module_name=None）— 查询 scraper.db 的 movies 表
2. 模块数据库模式（module_name=jav/fc2/...）— 查询对应模块的 xxx_movies 表
"""

import json
import logging
import os
from dataclasses import dataclass, field

from sqlalchemy import text as sa_text
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from app.db.database import get_db
from app.db.models import Movie
from app.db.module_db import ModuleDatabase

logger = logging.getLogger(__name__)


def _source_to_module(source: str) -> str:
    """将刮削来源映射到模块子目录名称"""
    if not source:
        return "jav"
    _map = {
        "javdb": "jav", "javbus": "jav", "dmm": "jav",
        "javlibrary": "jav", "jav321": "jav", "arzon": "jav",
        "mgstage": "jav", "faleno": "jav", "prestige": "jav",
        "kawaii": "jav", "madou": "chinese", "guochan": "chinese",
        "fc2": "fc2", "fc2club": "fc2", "fc2ppvdb": "fc2",
        "pornhub": "pornhub", "western": "western",
        "adulttime": "western", "theporndb": "western",
        "aylo": "western",
    }
    return _map.get(source, source)


# 各模块数据库的表名映射
MODULE_TABLE_MAP = {
    "jav": "jav_movies",
    "fc2": "fc2_movies",
    "uncensored": "uncensored_movies",
    "chinese": "chinese_movies",
    "western": "western_movies",
    "pornhub": "movies",
}


class MissingType(str, Enum):
    """缺失类型"""
    FIELD = "field"       # 字段缺失
    IMAGE = "image"       # 图片缺失
    NFO = "nfo"           # NFO 文件缺失
    ACTOR_IMAGE = "actor_image"  # 演员头像缺失


class FieldType(str, Enum):
    """字段类型"""
    TITLE = "title"
    TITLE_JP = "title_jp"
    PLOT = "plot"
    PLOT_SHORT = "plot_short"
    RELEASE_DATE = "release_date"
    DURATION = "duration"
    RATING = "rating"
    STUDIO = "studio"
    MAKER = "maker"
    SERIES = "series"
    DIRECTOR = "director"
    GENRE = "genre"
    TAG = "tag"
    COVER_URL = "cover_url"
    POSTER_URL = "poster_url"
    THUMB_URL = "thumb_url"
    TRAILER_URL = "trailer_url"
    SOURCE = "source"
    ACTORS = "actors"


class ImageType(str, Enum):
    """图片类型"""
    POSTER = "poster"           # poster.jpg
    FANART = "fanart"           # fanart.jpg
    THUMB = "thumb"             # thumb.jpg
    COVER = "cover"             # cover.jpg
    EXTRAFANART = "extrafanart" # extrafanart/*.jpg
    ACTORS = "actors"           # actors/*.jpg


@dataclass
class MissingField:
    """缺失字段信息"""
    field_type: FieldType
    current_value: Optional[str] = None
    importance: str = "normal"  # critical/normal/optional
    
    def to_dict(self) -> dict:
        return {
            "field": self.field_type.value,
            "current_value": self.current_value,
            "importance": self.importance,
        }


@dataclass
class MissingImage:
    """缺失图片信息"""
    image_type: ImageType
    expected_path: Optional[str] = None
    exists: bool = False
    importance: str = "normal"  # critical/normal/optional
    
    def to_dict(self) -> dict:
        return {
            "image_type": self.image_type.value,
            "expected_path": self.expected_path,
            "exists": self.exists,
            "importance": self.importance,
        }


@dataclass
class MissingInfo:
    """缺失信息汇总"""
    movie_id: int
    movie_code: str
    
    # 缺失的字段
    missing_fields: list[MissingField] = field(default_factory=list)
    
    # 缺失的图片
    missing_images: list[MissingImage] = field(default_factory=list)
    
    # NFO 文件状态
    nfo_exists: bool = False
    nfo_path: Optional[str] = None
    
    # 演员头像状态
    actor_images_missing: list[str] = field(default_factory=list)
    
    # 元信息
    detected_at: datetime = field(default_factory=datetime.now)
    output_dir: Optional[str] = None
    
    def has_missing(self) -> bool:
        """是否有缺失"""
        return bool(
            self.missing_fields or 
            self.missing_images or 
            not self.nfo_exists or 
            self.actor_images_missing
        )
    
    def critical_missing_count(self) -> int:
        """关键缺失数量"""
        count = 0
        for f in self.missing_fields:
            if f.importance == "critical":
                count += 1
        for i in self.missing_images:
            if i.importance == "critical":
                count += 1
        return count
    
    def total_missing_count(self) -> int:
        """总缺失数量"""
        return (
            len(self.missing_fields) + 
            len(self.missing_images) + 
            len(self.actor_images_missing) +
            (0 if self.nfo_exists else 1)
        )
    
    def to_dict(self) -> dict:
        return {
            "movie_id": self.movie_id,
            "movie_code": self.movie_code,
            "missing_fields": [f.to_dict() for f in self.missing_fields],
            "missing_images": [i.to_dict() for i in self.missing_images],
            "nfo_exists": self.nfo_exists,
            "nfo_path": self.nfo_path,
            "actor_images_missing": self.actor_images_missing,
            "total_missing": self.total_missing_count(),
            "critical_missing": self.critical_missing_count(),
            "output_dir": self.output_dir,
        }


class MissingDetector:
    """
    缺失检测器
    
    检测已有刮削内容的缺失字段和图片
    支持中心数据库和模块数据库两种模式
    """
    
    # 关键字段（必须存在）
    CRITICAL_FIELDS = [
        FieldType.TITLE,
        FieldType.RELEASE_DATE,
    ]
    
    # 重要字段
    IMPORTANT_FIELDS = [
        FieldType.PLOT,
        FieldType.STUDIO,
        FieldType.MAKER,
        FieldType.GENRE,
        FieldType.ACTORS,
    ]
    
    # 可选字段
    OPTIONAL_FIELDS = [
        FieldType.TITLE_JP,
        FieldType.PLOT_SHORT,
        FieldType.DURATION,
        FieldType.RATING,
        FieldType.SERIES,
        FieldType.DIRECTOR,
        FieldType.TAG,
        FieldType.TRAILER_URL,
    ]
    
    # 关键图片
    CRITICAL_IMAGES = [
        ImageType.POSTER,
        ImageType.FANART,
    ]
    
    # 重要图片
    IMPORTANT_IMAGES = [
        ImageType.COVER,
        ImageType.THUMB,
    ]
    
    # 可选图片
    OPTIONAL_IMAGES = [
        ImageType.EXTRAFANART,
        ImageType.ACTORS,
    ]
    
    def __init__(
        self,
        output_base_dir: str = "/output",
        check_critical_only: bool = False,
        module_name: Optional[str] = None,
    ):
        """
        初始化
        
        Args:
            output_base_dir: 输出基础目录
            check_critical_only: 仅检查关键字段/图片
            module_name: 模块名（jav/fc2/uncensored/chinese/western/pornhub）
                        None 表示使用中心数据库
        """
        self.output_base_dir = output_base_dir
        self.check_critical_only = check_critical_only
        self.module_name = module_name

    def _get_db_session(self):
        """根据 module_name 获取对应的数据库 session"""
        if self.module_name:
            mod_db = ModuleDatabase.get_instance(self.module_name)
            return mod_db.get_session()
        return get_db().session()

    def _get_table_name(self) -> str:
        """获取当前模式下的表名"""
        if self.module_name:
            return MODULE_TABLE_MAP.get(self.module_name, f"{self.module_name}_movies")
        return "movies"

    def _get_actors_table_name(self) -> str:
        """获取演员关联表名（模块库）"""
        if self.module_name:
            # 模块库的 actor 是单列，没有关联表
            return None
        return "movie_actors"

    async def detect_movie(self, movie_id: int) -> Optional[MissingInfo]:
        """
        检测单个电影的缺失
        
        Args:
            movie_id: 电影 ID
            
        Returns:
            MissingInfo 缺失信息
        """
        table = self._get_table_name()
        
        async with self._get_db_session() as session:
            # 查询电影信息
            result = await session.execute(
                sa_text(f"SELECT * FROM {table} WHERE id = :id"), {"id": movie_id}
            )
            row = result.fetchone()
            
            if not row:
                logger.warning(f"影片未找到: {movie_id}")
                return None
            
            # 转换为字典
            columns = result.keys()
            movie_data = dict(zip(columns, row))
            
            return await self._detect_from_dict(movie_data)
    
    async def detect_by_code(self, code: str) -> Optional[MissingInfo]:
        """
        通过番号检测缺失
        
        Args:
            code: 番号
            
        Returns:
            MissingInfo 缺失信息
        """
        table = self._get_table_name()
        
        async with self._get_db_session() as session:
            result = await session.execute(
                sa_text(f"SELECT * FROM {table} WHERE code = :code"), {"code": code}
            )
            row = result.fetchone()
            
            if not row:
                logger.warning(f"影片未找到: {code}")
                return None
            
            columns = result.keys()
            movie_data = dict(zip(columns, row))
            
            return await self._detect_from_dict(movie_data)
    
    async def detect_batch(
        self,
        movie_ids: Optional[list[int]] = None,
        codes: Optional[list[str]] = None,
        status: Optional[str] = None,
    ) -> list[MissingInfo]:
        """
        批量检测缺失
        
        Args:
            movie_ids: 电影 ID 列表
            codes: 番号列表
            status: 按状态过滤
            
        Returns:
            缺失信息列表
        """
        results = []
        table = self._get_table_name()
        
        async with self._get_db_session() as session:
            # 构建查询
            if movie_ids:
                placeholders = ",".join(f":id_{i}" for i in range(len(movie_ids)))
                query = sa_text(f"SELECT * FROM {table} WHERE id IN ({placeholders})")
                params = {f"id_{i}": mid for i, mid in enumerate(movie_ids)}
            elif codes:
                placeholders = ",".join(f":code_{i}" for i in range(len(codes)))
                query = sa_text(f"SELECT * FROM {table} WHERE code IN ({placeholders})")
                params = {f"code_{i}": c for i, c in enumerate(codes)}
            elif status:
                query = sa_text(f"SELECT * FROM {table} WHERE status = :status")
                params = {"status": status}
            else:
                query = sa_text(f"SELECT * FROM {table}")
                params = {}
            
            result = await session.execute(query, params)
            rows = result.fetchall()
            columns = result.keys()

            total_scanned = len(rows)
            logger.info(f"数据库扫描完成: 共 {total_scanned} 部影片")

            for row in rows:
                movie_data = dict(zip(columns, row))
                info = await self._detect_from_dict(movie_data)
                if info and info.has_missing():
                    results.append(info)

        logger.info(
            f"检测完成: 扫描 {total_scanned} 部, "
            f"发现 {len(results)} 部有缺失数据, "
            f"{total_scanned - len(results)} 部数据完整"
        )
        return results
    
    async def detect_all(self) -> list[MissingInfo]:
        """
        检测所有电影的缺失
        
        Returns:
            缺失信息列表
        """
        return await self.detect_batch()
    
    async def _detect_from_dict(self, movie_data: dict) -> MissingInfo:
        """从字典检测缺失（统一处理中心库和模块库的字段差异）"""
        movie_id = movie_data["id"]
        code = movie_data.get("code", str(movie_id))
        
        info = MissingInfo(
            movie_id=movie_id,
            movie_code=code,
        )
        
        # 模块数据库模式：actor 是单列，直接读取
        if self.module_name:
            movie_data["_actors_count"] = 1 if movie_data.get("actor") else 0
            # 模块数据库的 studio/series/director 是直接列，无需查关联表
        else:
            # 中心数据库模式：预填 actors 关联表计数
            try:
                async with get_db().session() as session:
                    result = await session.execute(
                        sa_text("SELECT COUNT(*) FROM movie_actors WHERE movie_id = :mid"),
                        {"mid": movie_id},
                    )
                    movie_data["_actors_count"] = result.scalar() or 0
            except Exception:
                movie_data["_actors_count"] = 0
            
            # 预填 studio 名称
            studio_id = movie_data.get("studio_id")
            if studio_id:
                try:
                    async with get_db().session() as session:
                        result = await session.execute(
                            sa_text("SELECT name FROM studios WHERE id = :sid"),
                            {"sid": studio_id},
                        )
                        movie_data["studio"] = result.scalar()
                except Exception:
                    pass
            
            # 预填 series 名称
            series_id = movie_data.get("series_id")
            if series_id:
                try:
                    async with get_db().session() as session:
                        result = await session.execute(
                            sa_text("SELECT name FROM series WHERE id = :sid"),
                            {"sid": series_id},
                        )
                        movie_data["series"] = result.scalar()
                except Exception:
                    pass

        # 获取输出目录
        from app.config.manager import PROJECT_ROOT
        project_root = PROJECT_ROOT
        source = movie_data.get("source") or ""
        module_subdir = self.module_name or _source_to_module(source)
        server_data_dir = project_root / "data" / "movies" / module_subdir / code

        db_output_dir = movie_data.get("output_dir")
        if db_output_dir:
            db_path = Path(db_output_dir)
            if str(db_path).startswith(str(project_root)):
                output_dir = str(db_path)
            else:
                output_dir = str(server_data_dir)
        else:
            output_dir = str(server_data_dir)

        info.output_dir = output_dir
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # 1. 检测字段缺失
        info.missing_fields = self._detect_missing_fields(movie_data)

        # 2. 检测图片缺失
        if output_dir:
            info.missing_images, info.nfo_exists, info.nfo_path = \
                await self._detect_missing_images(movie_data, output_dir)
            info.actor_images_missing = await self._detect_missing_actor_images(
                movie_data, output_dir
            )
        else:
            info.missing_images = self._get_all_images_missing()
            info.nfo_exists = False
        
        return info
    
    def _detect_missing_fields(self, movie_data: dict) -> list[MissingField]:
        """检测缺失字段
        
        注意：中心库模式下 studio/series 是 FK 列（studio_id/series_id），
        actors 是关联表（movie_actors），不是直接列。
        模块库模式下 actor 是直接列，studio/series 也是直接列。
        """
        missing = []
        
        # 字段名映射：FieldType 枚举值 → 实际 DB 列名
        if self.module_name:
            # 模块数据库：简单映射，actor 列名需对应
            COLUMN_MAP = {
                "actors": "actor",         # 模块库的 actor 列 → detector 的 actors 字段
                "studio": "studio",
                "series": "series",
                "director": "director",
                "maker": "maker",
                "genre": "genre",
                "tag": "tag",
            }
        else:
            COLUMN_MAP = {
                "studio": "studio_id",    # FK → studios 表
                "series": "series_id",    # FK → series 表
                "actors": "_actors_count", # 关联表，由 _detect_from_dict 预填
            }
        
        def _get_value(field_type):
            mapped = COLUMN_MAP.get(field_type.value)
            if mapped:
                return movie_data.get(mapped)
            return movie_data.get(field_type.value)
        
        # 检查关键字段
        for field_type in self.CRITICAL_FIELDS:
            value = _get_value(field_type)
            if not value:
                missing.append(MissingField(
                    field_type=field_type,
                    current_value=value,
                    importance="critical",
                ))
        
        if self.check_critical_only:
            return missing
        
        # 检查重要字段
        for field_type in self.IMPORTANT_FIELDS:
            value = _get_value(field_type)
            if not value:
                missing.append(MissingField(
                    field_type=field_type,
                    current_value=value,
                    importance="normal",
                ))
        
        # 检查可选字段
        for field_type in self.OPTIONAL_FIELDS:
            value = _get_value(field_type)
            if not value:
                missing.append(MissingField(
                    field_type=field_type,
                    current_value=value,
                    importance="optional",
                ))
        
        return missing
    
    async def _detect_missing_images(
        self,
        movie_data: dict,
        output_dir: str,
    ) -> tuple[list[MissingImage], bool, Optional[str]]:
        """检测缺失图片"""
        missing = []
        dir_path = Path(output_dir)
        
        # 检查 NFO 文件
        nfo_path = dir_path / "movie.nfo"
        nfo_exists = nfo_path.exists()
        
        # 检查关键图片
        for image_type in self.CRITICAL_IMAGES:
            expected_path = dir_path / f"{image_type.value}.jpg"
            exists = expected_path.exists()
            
            if not exists:
                missing.append(MissingImage(
                    image_type=image_type,
                    expected_path=str(expected_path),
                    exists=exists,
                    importance="critical",
                ))
        
        if self.check_critical_only:
            return missing, nfo_exists, str(nfo_path) if nfo_exists else None
        
        # 检查重要图片
        for image_type in self.IMPORTANT_IMAGES:
            expected_path = dir_path / f"{image_type.value}.jpg"
            exists = expected_path.exists()
            
            if not exists:
                missing.append(MissingImage(
                    image_type=image_type,
                    expected_path=str(expected_path),
                    exists=exists,
                    importance="normal",
                ))
        
        # 检查剧照
        extrafanart_dir = dir_path / "extrafanart"
        if not extrafanart_dir.exists() or not any(extrafanart_dir.glob("*.jpg")):
            missing.append(MissingImage(
                image_type=ImageType.EXTRAFANART,
                expected_path=str(extrafanart_dir),
                exists=False,
                importance="optional",
            ))
        
        # 检查演员头像目录
        actors_dir = dir_path / "actors"
        if not actors_dir.exists():
            missing.append(MissingImage(
                image_type=ImageType.ACTORS,
                expected_path=str(actors_dir),
                exists=False,
                importance="optional",
            ))
        
        return missing, nfo_exists, str(nfo_path) if nfo_exists else None
    
    async def _detect_missing_actor_images(
        self,
        movie_data: dict,
        output_dir: str,
    ) -> list[str]:
        """检测缺失的演员头像"""
        missing_actors = []
        
        # 解析演员列表 - 模块库 actor 是单列字符串
        actor_val = movie_data.get("actor") or movie_data.get("actors")
        if not actor_val:
            return missing_actors
        
        actors = []
        if isinstance(actor_val, str):
            try:
                parsed = json.loads(actor_val)
                actors = parsed if isinstance(parsed, list) else [actor_val]
            except (json.JSONDecodeError, TypeError):
                # 逗号分隔
                actors = [a.strip() for a in actor_val.split(",") if a.strip()]
        elif isinstance(actor_val, list):
            actors = actor_val
        
        if not actors:
            return missing_actors
        
        # 检查头像文件
        for actor_name in actors:
            avatar_dir = Path(output_dir) / "actors"
            if not avatar_dir.exists():
                missing_actors.append(actor_name)
                continue
            
            # 找头像文件
            found = False
            for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                if (avatar_dir / f"{actor_name}{ext}").exists():
                    found = True
                    break
            
            if not found:
                missing_actors.append(actor_name)
        
        return missing_actors
    
    def _get_all_images_missing(self) -> list[MissingImage]:
        """没有输出目录时，所有图片都视为缺失"""
        missing = []
        for image_type in self.CRITICAL_IMAGES + self.IMPORTANT_IMAGES:
            missing.append(MissingImage(
                image_type=image_type,
                importance="critical" if image_type in self.CRITICAL_IMAGES else "normal",
            ))
        return missing


# ===== 便捷函数 =====

async def detect_missing(movie_id: int, module_name: Optional[str] = None) -> Optional[MissingInfo]:
    """便捷函数：检测单个电影缺失"""
    detector = MissingDetector(module_name=module_name)
    return await detector.detect_movie(movie_id)


async def detect_missing_by_code(code: str, module_name: Optional[str] = None) -> Optional[MissingInfo]:
    """便捷函数：通过番号检测缺失"""
    detector = MissingDetector(module_name=module_name)
    return await detector.detect_by_code(code)
