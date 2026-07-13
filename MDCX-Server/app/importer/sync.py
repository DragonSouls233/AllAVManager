"""
增量同步逻辑

检测已有刮削内容，与数据库同步
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Movie, Actor, MovieActor, Studio, Series
from app.importer.image_scanner import ImageScanner, MovieImages
from app.importer.nfo_parser import ImportedMovie, NFOParser
from app.importer.number_matcher import NumberMatcher

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """导入结果"""
    directory: str                      # 目录路径
    number: Optional[str] = None        # 番号
    status: str = "pending"             # pending/success/skipped/failed
    message: str = ""                   # 消息
    
    # 导入的数据
    nfo_data: Optional[ImportedMovie] = None
    images: Optional[MovieImages] = None
    
    # 数据库记录
    movie_id: Optional[int] = None
    
    # 元信息
    imported_at: Optional[datetime] = None


@dataclass
class ImportReport:
    """导入报告"""
    total: int = 0                      # 总数
    success: int = 0                    # 成功数
    skipped: int = 0                    # 跳过数
    failed: int = 0                     # 失败数
    
    results: list[ImportResult] = field(default_factory=list)
    
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    
    def duration_seconds(self) -> float:
        """耗时（秒）"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0


class ImportSync:
    """
    导入同步器
    
    扫描目录，识别已有刮削内容，同步到数据库
    """
    
    def __init__(
        self,
        conflict_strategy: str = "skip",  # skip/overwrite/merge
    ):
        self.conflict_strategy = conflict_strategy
        self.nfo_parser = NFOParser()
        self.image_scanner = ImageScanner()
        self.number_matcher = NumberMatcher()
        # 性能优化缓存
        self._existing_codes_cache: dict[str, int] = {}  # code -> movie_id
        self._actor_cache: dict[str, int] = {}  # actor_name -> actor_id
        self._actors_with_avatar: set[str] = set()  # 已有头像的演员名
        self._studio_cache: dict[str, int | None] = {}  # studio name(lower) -> id
        self._series_cache: dict[str, int | None] = {}  # series name(lower) -> id
        self._cache_loaded = False
    
    async def scan_directory(
        self,
        directory: str,
        recursive: bool = True,
    ) -> list[str]:
        """扫描目录，查找包含 NFO 或视频文件的子目录"""
        dir_path = Path(directory)
        scraped_dirs = []
        
        if not dir_path.exists():
            logger.warning(f"Directory not found: {directory}")
            return scraped_dirs
        
        VIDEO_EXTENSIONS = {
            ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
            ".iso", ".rmvb", ".rm", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm",
            ".vob", ".ogv", ".divx", ".asf", ".tp", ".mts",
        }
        
        SKIP_DIRS = {
            "System Volume Information", "$RECYCLE.BIN", "$Recycle.Bin",
            "Windows", "Program Files", "Program Files (x86)", "ProgramData",
            "Recovery", "Intel", "PerfLogs", "pagefile.sys", "hiberfil.sys",
            ".git", ".svn", ".hg", "node_modules", "__pycache__",
            "AppData", "Application Data",
        }
        
        def _should_skip(path: Path) -> bool:
            name = path.name
            if name in SKIP_DIRS:
                return True
            if name.startswith('.') and name != '.':
                return True
            if name.startswith('$'):
                return True
            return False
        
        def _safe_iterdir(path: Path):
            try:
                return list(path.iterdir())
            except (PermissionError, OSError):
                return []
        
        if recursive:
            queue = [dir_path]
            while queue:
                current = queue.pop(0)
                has_nfo = False
                has_video = False
                
                for item in _safe_iterdir(current):
                    if item.is_dir():
                        if not _should_skip(item):
                            queue.append(item)
                    elif item.is_file():
                        if item.suffix.lower() == '.nfo':
                            has_nfo = True
                        elif item.suffix.lower() in VIDEO_EXTENSIONS:
                            has_video = True
                
                if has_nfo or has_video:
                    parent = str(current)
                    if parent not in scraped_dirs:
                        scraped_dirs.append(parent)
        else:
            has_nfo = False
            has_video = False
            for item in _safe_iterdir(dir_path):
                if item.is_file():
                    if item.suffix.lower() == '.nfo':
                        has_nfo = True
                    elif item.suffix.lower() in VIDEO_EXTENSIONS:
                        has_video = True
            if has_nfo or has_video:
                scraped_dirs.append(str(dir_path))
        
        logger.info(f"Found {len(scraped_dirs)} directories with media files")
        return scraped_dirs
    
    async def import_directory(
        self,
        directory: str,
    ) -> ImportResult:
        """导入单个目录"""
        result = ImportResult(directory=directory)
        result.imported_at = datetime.now()
        
        dir_path = Path(directory)
        
        if not dir_path.exists():
            result.status = "failed"
            result.message = "Directory not found"
            return result
        
        VIDEO_EXTENSIONS = {
            ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
            ".iso", ".rmvb", ".rm", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm",
            ".vob", ".ogv", ".divx", ".asf", ".tp", ".mts",
        }
        
        # 1. 查找 NFO 文件
        try:
            nfo_files = list(dir_path.glob("*.nfo"))
        except (PermissionError, OSError):
            nfo_files = []
        
        # 2. 查找视频文件
        try:
            video_files = [f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS]
        except (PermissionError, OSError):
            video_files = []
        
        if not nfo_files and not video_files:
            result.status = "skipped"
            result.message = "No NFO or video file found"
            return result
        
        # 3. 如果有 NFO，走 NFO 导入流程
        if nfo_files:
            nfo_file = nfo_files[0]
            nfo_data = self.nfo_parser.parse(nfo_file)
            
            if nfo_data and nfo_data.is_valid():
                result.nfo_data = nfo_data
                
                # 扫描图片
                images = self.image_scanner.scan(directory)
                result.images = images
                
                # 匹配番号
                number, confidence = self.number_matcher.match(
                    nfo_data=nfo_data,
                    directory=directory,
                )
                
                if number:
                    result.number = number
                    
                    # 检查数据库是否已存在
                    existing_id = await self._check_existing(number)
                    
                    if existing_id and self.conflict_strategy == "skip":
                        result.status = "skipped"
                        result.message = f"Movie already exists (id={existing_id})"
                        result.movie_id = existing_id
                        return result
                    
                    # 同步到数据库
                    # 关键：NFO 分支也要传 video_files，否则 file_path 会为 None 导致播放 404
                    movie_id = await self._sync_to_db(
                        number=number,
                        nfo_data=nfo_data,
                        images=images,
                        directory=directory,
                        existing_id=existing_id,
                        video_files=video_files,
                    )
                    
                    if movie_id:
                        result.status = "success"
                        result.message = "Imported successfully"
                        result.movie_id = movie_id
                    else:
                        result.status = "failed"
                        result.message = "Failed to sync to database"
                    
                    return result
        
        # 4. 没有 NFO 或 NFO 解析失败，尝试从视频文件名提取番号
        if video_files:
            for video_file in video_files:
                number, confidence = self.number_matcher.match(
                    video_file=str(video_file),
                    directory=directory,
                )
                if number:
                    result.number = number
                    break
            
            if not result.number:
                result.status = "failed"
                result.message = "Failed to match number from video filename"
                return result
            
            existing_id = await self._check_existing(result.number)
            
            if existing_id and self.conflict_strategy == "skip":
                result.status = "skipped"
                result.message = f"Movie already exists (id={existing_id})"
                result.movie_id = existing_id
                return result
            
            images = self.image_scanner.scan(directory)
            result.images = images
            
            movie_id = await self._sync_to_db(
                number=result.number,
                nfo_data=None,
                images=images,
                directory=directory,
                video_files=[str(f) for f in video_files],
                existing_id=existing_id,
            )
            
            if movie_id:
                result.status = "success"
                result.message = "Imported from video file (no NFO)"
                result.movie_id = movie_id
            else:
                result.status = "failed"
                result.message = "Failed to sync to database"
            
            return result
        
        result.status = "failed"
        result.message = "No importable content found"
        return result
    
    async def import_batch(
        self,
        directories: list[str],
    ) -> ImportReport:
        """批量导入"""
        report = ImportReport()
        report.total = len(directories)
        report.started_at = datetime.now()
        
        for directory in directories:
            result = await self.import_directory(directory)
            report.results.append(result)
            
            if result.status == "success":
                report.success += 1
            elif result.status == "skipped":
                report.skipped += 1
            else:
                report.failed += 1
        
        report.finished_at = datetime.now()
        
        logger.info(
            f"Import completed: {report.success} success, "
            f"{report.skipped} skipped, {report.failed} failed"
        )
        
        return report
    
    async def _check_existing(self, number: str) -> Optional[int]:
        """检查数据库中是否已存在（使用缓存，番号统一大写）"""
        if not number:
            return None
        
        if not self._cache_loaded:
            await self._load_caches()
        
        # 统一用大写查询
        normalized = number.upper().replace('_', '-')
        return self._existing_codes_cache.get(normalized)
    
    async def _load_caches(self):
        """一次性加载所有已有番号和演员到缓存（番号统一大写）"""
        db = get_db()
        
        async with db.session() as session:
            # 加载所有已有番号（统一大写为键）
            result = await session.execute(select(Movie.id, Movie.code))
            rows = result.fetchall()
            for row in rows:
                movie_id, code = row
                if code:
                    normalized = code.upper().replace('_', '-')
                    self._existing_codes_cache[normalized] = movie_id
            
            # 加载所有已有演员（含头像信息）
            result = await session.execute(select(Actor.id, Actor.name, Actor.avatar_url))
            rows = result.fetchall()
            for row in rows:
                actor_id, name, avatar_url = row
                if name:
                    self._actor_cache[name] = actor_id
                    if avatar_url:
                        self._actors_with_avatar.add(name)
        
        self._cache_loaded = True
        logger.info(f"缓存加载完成: {len(self._existing_codes_cache)} 个番号, {len(self._actor_cache)} 个演员")

    async def _resolve_studio_id(self, session: AsyncSession, name: Optional[str]) -> Optional[int]:
        """把工作室名称解析为 studios.id（大小写不敏感；查不到返回 None，不新建行）"""
        if not name:
            return None
        key = name.strip().lower()
        if key in self._studio_cache:
            return self._studio_cache[key]
        row = (await session.execute(
            select(Studio.id).where(func.upper(Studio.name) == name.strip().upper())
        )).scalar_one_or_none()
        self._studio_cache[key] = row
        return row

    async def _resolve_series_id(self, session: AsyncSession, name: Optional[str]) -> Optional[int]:
        """把系列名称解析为 series.id（大小写不敏感；查不到则新建 Series 行）

        v3.4 修复：原实现只查不创建，导致 series_id 永远为 None，series sync 永远 0 个。
        """
        if not name:
            return None
        key = name.strip().lower()
        if key in self._series_cache:
            return self._series_cache[key]
        upper_name = name.strip().upper()
        row = (await session.execute(
            select(Series.id).where(func.upper(Series.name) == upper_name)
        )).scalar_one_or_none()
        if not row:
            # 查不到则新建（关联 maker 作为 studio_id 如果有）
            series = Series(name=name.strip(), movie_count=0)
            session.add(series)
            await session.flush()
            row = series.id
            logger.info(f"新建系列: {name.strip()} (id={row})")
        self._series_cache[key] = row
        return row

    @staticmethod
    def _resolve_version_flags(nfo_data: Optional[ImportedMovie]) -> tuple[bool, bool, bool, bool]:
        """
        解析版本标记，返回 (is_chinese, is_uncensored, is_leak, is_mosaic)

        优先级：
        1. NFO 解析阶段从文件名/目录名后缀识别出的 is_chinese/is_uncensored/is_leak
        2. genre 关键字（中文字幕/无码/流出）冗余叠加
        3. 默认值：is_chinese=False, is_uncensored=False, is_leak=False, is_mosaic=True（有码）

        is_mosaic 与 is_uncensored 的关系：无码 → is_mosaic=False；其余 → is_mosaic=True
        """
        is_chinese = False
        is_uncensored = False
        is_leak = False

        if nfo_data:
            # 1. NFO 解析阶段识别的后缀标记（优先）
            if nfo_data.is_chinese:
                is_chinese = True
            if nfo_data.is_uncensored:
                is_uncensored = True
            if nfo_data.is_leak:
                is_leak = True

            # 2. genre 关键字冗余叠加
            genre_text = " ".join(nfo_data.genres) if nfo_data.genres else ""
            if genre_text:
                if "中文字幕" in genre_text or "中文" in genre_text or "中字" in genre_text:
                    is_chinese = True
                if "无码" in genre_text or "無碼" in genre_text or "uncensored" in genre_text.lower():
                    is_uncensored = True
                if "流出" in genre_text or "破解" in genre_text or "leak" in genre_text.lower():
                    is_leak = True

        # 3. is_mosaic：无码 → False；有码（默认）→ True
        is_mosaic = not is_uncensored

        return is_chinese, is_uncensored, is_leak, is_mosaic

    async def _sync_to_db(
        self,
        number: str,
        nfo_data: Optional[ImportedMovie],
        images: MovieImages,
        directory: str,
        existing_id: Optional[int] = None,
        video_files: Optional[list[str]] = None,
    ) -> Optional[int]:
        """
        同步到数据库（使用 SQLAlchemy ORM，对齐 models.py 中的表结构）
        使用 INSERT OR IGNORE 跳过已存在的番号，彻底避免 UNIQUE 约束错误。
        """
        db = get_db()

        # 番号标准化（统一大写，确保缓存和数据库一致）
        if not number:
            return None
        number = number.upper().replace('_', '-')

        # 构建文件路径
        file_path = ""
        file_size = None
        if video_files:
            file_path = video_files[0]
            try:
                file_size = Path(file_path).stat().st_size
            except Exception:
                pass

        try:
            async with db.session() as session:
                # ===== 第一阶段：查询是否已存在（大小写不敏感） =====
                # 使用 func.upper() 确保查询是大小写不敏感的，避免：
                #   "miaa-105" in DB vs "MIAA-105" from parser -> 漏判 -> INSERT 失败
                from sqlalchemy import func

                check_result = await session.execute(
                    select(Movie.id).where(func.upper(Movie.code) == number)
                )
                existing = check_result.scalar_one_or_none()
                if existing:
                    # 已存在 - 根据冲突策略处理
                    self._existing_codes_cache[number] = existing

                    if self.conflict_strategy == "skip":
                        logger.debug(f"番号 {number} 已存在 (id={existing})，跳过")
                        return existing
                    elif self.conflict_strategy == "overwrite":
                        movie = await session.get(Movie, existing)
                        if movie:
                            genre_list = nfo_data.genres if nfo_data else []
                            genre_json = json.dumps(genre_list, ensure_ascii=False) if genre_list else None
                            release_date_str = None
                            if nfo_data and nfo_data.release_date:
                                release_date_str = nfo_data.release_date.strftime("%Y-%m-%d")
                            is_chinese, is_uncensored, is_leak, is_mosaic = self._resolve_version_flags(nfo_data)

                            movie.title = nfo_data.title if nfo_data else None
                            movie.plot = nfo_data.plot if nfo_data else None
                            movie.release_date = release_date_str
                            movie.duration = nfo_data.duration if nfo_data else None
                            movie.maker = nfo_data.maker if nfo_data else None
                            movie.director = nfo_data.director if nfo_data else None
                            movie.genre = genre_json
                            movie.cover_url = images.poster
                            movie.poster_url = images.fanart
                            movie.thumb_url = images.thumb
                            movie.source = nfo_data.source if nfo_data else "imported"
                            movie.file_path = file_path or None
                            movie.file_size = file_size
                            movie.is_chinese = is_chinese
                            movie.is_uncensored = is_uncensored
                            movie.is_leak = is_leak
                            movie.is_mosaic = is_mosaic
                            movie.status = "completed"
                            movie.updated_at = datetime.now()
                            await session.commit()

                            if nfo_data and nfo_data.actors:
                                await self._sync_actors(session, movie.id, nfo_data.actors, directory)
                            return existing
                    elif self.conflict_strategy == "merge":
                        movie = await session.get(Movie, existing)
                        if movie:
                            genre_list = nfo_data.genres if nfo_data else []
                            genre_json = json.dumps(genre_list, ensure_ascii=False) if genre_list else None
                            release_date_str = None
                            if nfo_data and nfo_data.release_date:
                                release_date_str = nfo_data.release_date.strftime("%Y-%m-%d")

                            if nfo_data:
                                if nfo_data.title and not movie.title:
                                    movie.title = nfo_data.title
                                if nfo_data.plot and not movie.plot:
                                    movie.plot = nfo_data.plot
                                if nfo_data.maker and not movie.maker:
                                    movie.maker = nfo_data.maker
                                if nfo_data.director and not movie.director:
                                    movie.director = nfo_data.director
                                if genre_json and not movie.genre:
                                    movie.genre = genre_json
                                if release_date_str and not movie.release_date:
                                    movie.release_date = release_date_str
                                if nfo_data.duration and not movie.duration:
                                    movie.duration = nfo_data.duration
                                # 合并版本标记（仅当原值为空/False 时补全）
                                is_chinese, is_uncensored, is_leak, is_mosaic = self._resolve_version_flags(nfo_data)
                                if is_chinese and not movie.is_chinese:
                                    movie.is_chinese = True
                                if is_uncensored and not movie.is_uncensored:
                                    movie.is_uncensored = True
                                    movie.is_mosaic = False
                                if is_leak and not movie.is_leak:
                                    movie.is_leak = True
                                if movie.is_mosaic is None:
                                    movie.is_mosaic = is_mosaic
                            if images.poster and not movie.cover_url:
                                movie.cover_url = images.poster
                            if images.fanart and not movie.poster_url:
                                movie.poster_url = images.fanart
                            if images.thumb and not movie.thumb_url:
                                movie.thumb_url = images.thumb
                            if file_path and not movie.file_path:
                                movie.file_path = file_path
                            if file_size and not movie.file_size:
                                movie.file_size = file_size
                            movie.updated_at = datetime.now()
                            await session.commit()

                            if nfo_data and nfo_data.actors:
                                existing_actors = await session.execute(
                                    select(MovieActor).where(MovieActor.movie_id == movie.id)
                                )
                                if not existing_actors.scalars().first():
                                    await self._sync_actors(session, movie.id, nfo_data.actors, directory)
                            return existing
                    else:
                        # 默认策略：skip
                        return existing

                # ===== 第二阶段：INSERT OR IGNORE 新建 =====
                # 使用原生 SQL 的 INSERT OR IGNORE，彻底避免 UNIQUE 约束错误
                # 这是 SQLite 处理并发/竞态的标准做法
                from sqlalchemy import text as sa_text

                genre_list = nfo_data.genres if nfo_data else []
                genre_json = json.dumps(genre_list, ensure_ascii=False) if genre_list else None
                tag_json = None

                release_date_str = None
                if nfo_data and nfo_data.release_date:
                    release_date_str = nfo_data.release_date.strftime("%Y-%m-%d")

                is_chinese, is_uncensored, is_leak, is_mosaic = self._resolve_version_flags(nfo_data)

                status = 'completed' if nfo_data else 'pending'

                now = datetime.now()

                # studio/series 现为外键整型列(studio_id/series_id)，
                # 需把名称解析为对应表 id（查不到则留 NULL，不新建行）
                studio_id = await self._resolve_studio_id(
                    session, nfo_data.studio if nfo_data else None)
                series_id = await self._resolve_series_id(
                    session, nfo_data.series if nfo_data else None)

                # 使用 INSERT OR IGNORE 来彻底消除 UNIQUE 约束错误
                insert_sql = sa_text("""
                    INSERT OR IGNORE INTO movies (
                        code, title, plot, release_date, duration, studio_id, maker,
                        series_id, director, genre, tag, cover_url, poster_url, thumb_url,
                        source, is_chinese, is_uncensored, is_leak, is_mosaic,
                        file_path, file_size, play_count,
                        status, created_at, updated_at
                    ) VALUES (
                        :code, :title, :plot, :release_date, :duration, :studio_id, :maker,
                        :series_id, :director, :genre, :tag, :cover_url, :poster_url, :thumb_url,
                        :source, :is_chinese, :is_uncensored, :is_leak, :is_mosaic,
                        :file_path, :file_size, :play_count,
                        :status, :created_at, :updated_at
                    )
                """)

                params = {
                    "code": number,
                    "title": nfo_data.title if nfo_data else None,
                    "plot": nfo_data.plot if nfo_data else None,
                    "release_date": release_date_str,
                    "duration": nfo_data.duration if nfo_data else None,
                    "studio_id": studio_id,
                    "maker": nfo_data.maker if nfo_data else None,
                    "series_id": series_id,
                    "director": nfo_data.director if nfo_data else None,
                    "genre": genre_json,
                    "tag": tag_json,
                    "cover_url": images.poster,
                    "poster_url": images.fanart,
                    "thumb_url": images.thumb,
                    "source": nfo_data.source if nfo_data else "imported",
                    "is_chinese": 1 if is_chinese else 0,
                    "is_uncensored": 1 if is_uncensored else 0,
                    "is_leak": 1 if is_leak else 0,
                    "is_mosaic": 1 if is_mosaic else 0,
                    "file_path": file_path or None,
                    "file_size": file_size,
                    "play_count": 0,
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                }

                await session.execute(insert_sql, params)
                await session.commit()

                # 查询实际的 movie.id（INSERT OR IGNORE 可能跳过了，所以需要查）
                id_result = await session.execute(
                    sa_text("SELECT id FROM movies WHERE code = :code"),
                    {"code": number}
                )
                movie_id_row = id_result.fetchone()
                if not movie_id_row:
                    # 被 IGNORE 了，说明并发写入了，查已存在的
                    check_again = await session.execute(
                        select(Movie.id).where(func.upper(Movie.code) == number)
                    )
                    movie_id = check_again.scalar_one_or_none()
                    if movie_id:
                        self._existing_codes_cache[number] = movie_id
                        logger.debug(f"番号 {number} 已并发存在 (id={movie_id})，跳过")
                        return movie_id
                    logger.warning(f"番号 {number} 插入后查不到 id，可能失败")
                    return None

                movie_id = movie_id_row[0]
                self._existing_codes_cache[number] = movie_id

                # 同步演员
                if nfo_data and nfo_data.actors:
                    await self._sync_actors(session, movie_id, nfo_data.actors, directory)

                return movie_id

        except Exception as e:
            logger.error(f"Sync to DB error: {e}")
            return None
    
    async def _sync_actors(
        self,
        session: AsyncSession,
        movie_id: int,
        actor_names: list[str],
        directory: str = None,
    ) -> None:
        """同步演员数据到关联表（使用缓存优化），同时导入本地演员头像"""
        # 先删除旧的关联
        from sqlalchemy import delete
        await session.execute(
            delete(MovieActor).where(MovieActor.movie_id == movie_id)
        )
        
        # 查找本地演员头像
        # 来源1: 当前目录的 actors/ 子目录 (如 S:\篠田ゆう\IPZZ-218\actors\篠田ゆう.jpg)
        # 来源2: 父目录中以演员名命名的图片 (如 S:\篠田ゆう\篠田ゆう.jpg)
        # 来源3: 父目录中的 portrait/cover/folder 图片 (如 S:\篠田ゆう\folder.jpg)
        actor_images = {}  # actor_name -> image_path
        if directory:
            dir_path = Path(directory)
            
            # 来源1: actors/ 子目录
            actors_dir = dir_path / "actors"
            if actors_dir.exists():
                try:
                    for item in actors_dir.iterdir():
                        if item.is_file() and item.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                            name = item.stem.strip()
                            if name:
                                actor_images[name] = str(item)
                except (PermissionError, OSError):
                    pass
            
            # 来源2 & 3: 父目录（可能是演员根目录，如 S:\篠田ゆう\）
            parent_dir = dir_path.parent
            try:
                for item in parent_dir.iterdir():
                    if not item.is_file():
                        continue
                    if item.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
                        continue
                    stem = item.stem.strip()
                    # 来源2: 文件名匹配演员名
                    for actor_name in actor_names:
                        if stem == actor_name.strip():
                            actor_images[actor_name.strip()] = str(item)
                            break
                    # 来源3: 常见头像文件名 (folder.jpg, portrait.jpg 等)
                    if stem.lower() in ('folder', 'portrait', 'cover', 'avatar', 'profile'):
                        # 关联到第一个没有头像的演员
                        for actor_name in actor_names:
                            an = actor_name.strip()
                            if an not in actor_images:
                                actor_images[an] = str(item)
                                break
            except (PermissionError, OSError):
                pass
        
        # 批量处理演员关联
        pending_actors = []
        pending_movie_actors = []
        avatar_updates = []

        for actor_name in actor_names:
            if not actor_name or not actor_name.strip():
                continue

            actor_name = actor_name.strip()

            actor_id = self._actor_cache.get(actor_name)
            need_update_avatar = False

            if not actor_id:
                result = await session.execute(
                    select(Actor).where(Actor.name == actor_name)
                )
                actor = result.scalar_one_or_none()

                if not actor:
                    actor = Actor(name=actor_name)
                    pending_actors.append(actor)
                    session.add(actor)
                    await session.flush()
                    need_update_avatar = True
                else:
                    need_update_avatar = not actor.avatar_url

                actor_id = actor.id
                self._actor_cache[actor_name] = actor_id
            else:
                need_update_avatar = actor_name not in self._actors_with_avatar

            if need_update_avatar and actor_name in actor_images:
                avatar_path = await self._save_actor_avatar(actor_id, actor_images[actor_name])
                if avatar_path:
                    from sqlalchemy import update as sa_update
                    avatar_updates.append(
                        sa_update(Actor)
                        .where(Actor.id == actor_id)
                        .values(avatar_url=avatar_path)
                    )
                    self._actors_with_avatar.add(actor_name)

            pending_movie_actors.append(
                MovieActor(movie_id=movie_id, actor_id=actor_id)
            )

        # 批量执行头像更新
        for stmt in avatar_updates:
            await session.execute(stmt)

        # 批量插入 MovieActor 关联
        if pending_movie_actors:
            session.add_all(pending_movie_actors)

        await session.commit()
    
    async def _save_actor_avatar(self, actor_id: int, source_path: str) -> Optional[str]:
        """将本地演员头像复制到项目数据目录"""
        import shutil
        try:
            from app.config.manager import get_config_manager
            manager = get_config_manager()
            avatar_dir = manager.computed.data_dir / "avatars"
            avatar_dir.mkdir(parents=True, exist_ok=True)
            
            dest_path = avatar_dir / f"actor_{actor_id}.jpg"
            shutil.copy2(source_path, str(dest_path))
            return str(dest_path)
        except Exception as e:
            logger.warning(f"保存演员头像失败: {e}")
            return None


async def sync_imported_data(
    directory: str,
    recursive: bool = True,
    conflict_strategy: str = "skip",
) -> ImportReport:
    """同步导入数据的便捷函数"""
    sync = ImportSync(conflict_strategy=conflict_strategy)
    directories = await sync.scan_directory(directory, recursive)
    return await sync.import_batch(directories)
