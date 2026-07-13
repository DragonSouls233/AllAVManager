"""
完整刮削流程
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.crawlers.base import ScrapeResult
from app.db.database import get_db
from app.db.models import Movie, Actor, MovieActor
from app.output.images import ImageProcessor, download_movie_images
from app.output.nfo import NFOGenerator, generate_nfo
from app.scraper.engine import ScraperEngine, get_scraper_engine
from app.scraper.number import extract_number
from sqlalchemy import func

logger = logging.getLogger(__name__)


class ScraperWorkflow:
    """
    完整刮削流程
    
    串联所有模块完成单个文件的完整刮削：
    1. 番号识别
    2. 多站点刮削
    3. 结果合并
    4. 图片下载
    5. NFO生成
    6. 数据库写入
    """
    
    def __init__(
        self,
        output_dir: str,
        media_dir: Optional[str] = None,
        save_to_db: bool = True,
        download_images: bool = True,
        generate_nfo: bool = True,
    ):
        """
        初始化刮削流程
        
        Args:
            output_dir: 输出目录
            media_dir: 媒体目录（用于定位视频文件）
            save_to_db: 是否保存到数据库
            download_images: 是否下载图片
            generate_nfo: 是否生成NFO
        """
        self.output_dir = Path(output_dir)
        self.media_dir = Path(media_dir) if media_dir else None
        self.save_to_db = save_to_db
        self.download_images = download_images
        self.generate_nfo = generate_nfo
        
        self.engine = get_scraper_engine()
        self.nfo_generator = NFOGenerator(str(self.output_dir))
    
    async def process_file(
        self,
        file_path: str,
        sources: Optional[list[str]] = None,
    ) -> Optional[ScrapeResult]:
        """
        处理单个文件
        
        Args:
            file_path: 文件路径
            sources: 指定站点列表
            
        Returns:
            最终的刮削结果
        """
        logger.info(f"正在处理文件: {file_path}")
        
        # 1. 番号识别
        filename = os.path.basename(file_path)
        number_result = extract_number(filename)
        
        if not number_result.number:
            logger.warning(f"无法提取番号: {filename}")
            return None
        
        number = number_result.number
        logger.info(f"已提取番号: {number} (type={number_result.number_type})")
        
        # 2. 多站点刮削
        result = await self.engine.scrape_number(number, sources)
        
        if not result:
            logger.warning(f"刮削失败: {number}")
            return None
        
        logger.info(f"刮削来源: {result.source}")
        
        # 3. 创建输出目录
        movie_dir = self.output_dir / number
        movie_dir.mkdir(parents=True, exist_ok=True)
        
        # 4. 下载图片
        if self.download_images and result.cover_url:
            logger.info("正在下载图片")
            
            async with ImageProcessor(str(movie_dir)) as processor:
                # 下载封面
                poster_path = await processor.download_cover(
                    result.cover_url,
                    str(movie_dir),
                    referer=result.source,
                )
                
                if poster_path:
                    logger.info(f"海报已保存: {poster_path}")
                
                # 下载背景图（使用封面）
                fanart_path = await processor.download_fanart(
                    result.cover_url,
                    str(movie_dir),
                    referer=result.source,
                )
                
                # 下载样图
                if result.sample_images:
                    sample_paths = await processor.download_samples(
                        result.sample_images,
                        str(movie_dir),
                        referer=result.source,
                    )
                    logger.info(f"已下载 {len(sample_paths)} 张预览图")
        
        # 5. 生成NFO
        if self.generate_nfo:
            logger.info("正在生成NFO")
            nfo_path = generate_nfo(result, str(movie_dir))
            
            if nfo_path:
                logger.info(f"NFO已保存: {nfo_path}")
        
        # 6. 保存到数据库
        if self.save_to_db:
            logger.info("正在保存到数据库")
            await self._save_to_db(result, str(movie_dir), file_path)
        
        logger.info(f"处理完成: {number}")
        
        return result
    
    async def process_batch(
        self,
        file_paths: list[str],
        sources: Optional[list[str]] = None,
    ) -> dict[str, Optional[ScrapeResult]]:
        """
        批量处理文件
        
        Args:
            file_paths: 文件路径列表
            sources: 指定站点列表
            
        Returns:
            文件路径 -> 结果 的映射
        """
        results = {}
        
        for file_path in file_paths:
            result = await self.process_file(file_path, sources)
            results[file_path] = result
        
        return results
    
    async def _save_to_db(
        self,
        result: ScrapeResult,
        movie_dir: str,
        file_path: Optional[str] = None,
    ) -> None:
        """保存到数据库（使用 SQLAlchemy ORM）"""
        from app.db.models import Movie, Actor, MovieActor, Studio, Series
        from sqlalchemy import select

        db = get_db()

        # 规则3：刮削内容已在 output_dir(服务端目录) 落地，DB 引用本地路径，
        # 避免存远程 URL 导致封面解析回退扫描视频源目录。
        from pathlib import Path
        _movie_dir_path = Path(movie_dir).resolve() if movie_dir else None
        _local_cover = None
        _local_samples = None
        if _movie_dir_path and _movie_dir_path.exists():
            _p = _movie_dir_path / "poster.jpg"
            if _p.exists():
                _local_cover = str(_p)
            _ex = _movie_dir_path / "extrafanart"
            if _ex.is_dir():
                _imgs = sorted(str(x) for x in _ex.glob("*") if x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
                if _imgs:
                    _local_samples = _imgs

        async with db.session() as session:
            # 检查是否已存在
            existing = await session.execute(
                select(Movie).where(Movie.code == result.code)
            )
            movie = existing.scalar_one_or_none()

            # 构建标签 JSON
            genre_str = ",".join(result.genres) if result.genres else None
            tag_str = json.dumps(result.tags, ensure_ascii=False) if result.tags else None

            # 从 raw_data 提取额外字段
            raw = result.raw_data or {}
            director = raw.get("director") or raw.get("directors")
            if isinstance(director, list):
                director = ",".join(director) if director else None
            original_title = result.original_title or raw.get("original_title") or raw.get("originaltitle")

            # 提取文件信息
            file_size = None
            file_date = None
            if file_path:
                try:
                    fp = Path(file_path)
                    if fp.exists():
                        stat = fp.stat()
                        file_size = stat.st_size
                        file_date = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            # 查找或创建 Studio（FK 关联）
            studio_id = None
            if result.studio:
                existing_studio = await session.scalar(
                    select(Studio).where(Studio.name == result.studio)
                )
                if existing_studio:
                    studio_id = existing_studio.id
                else:
                    new_studio = Studio(name=result.studio, movie_count=0)
                    session.add(new_studio)
                    await session.flush()
                    studio_id = new_studio.id

            # 查找或创建 Series（FK 关联）
            series_id = None
            if result.series:
                existing_series = await session.scalar(
                    select(Series).where(Series.name == result.series)
                )
                if existing_series:
                    series_id = existing_series.id
                else:
                    new_series = Series(name=result.series, studio_id=studio_id, movie_count=0)
                    session.add(new_series)
                    await session.flush()
                    series_id = new_series.id

            if movie:
                # 更新现有记录
                movie.title = result.title
                movie.original_title = original_title
                movie.title_jp = original_title
                movie.studio_id = studio_id
                movie.maker = result.maker
                movie.series_id = series_id
                movie.director = director
                movie.release_date = str(result.release_date) if result.release_date else None
                movie.duration = result.duration
                movie.plot = result.plot
                movie.plot_short = (result.plot[:200] + "...") if result.plot and len(result.plot) > 200 else result.plot
                movie.cover_url = _local_cover or result.cover_url
                movie.poster_url = _local_cover or result.poster_url
                movie.thumb_url = _local_cover or result.poster_url or result.cover_url
                movie.sample_images = json.dumps(_local_samples or result.sample_images, ensure_ascii=False) if (_local_samples or result.sample_images) else None
                movie.trailer_url = result.trailer_url
                movie.rating = result.rating
                movie.source = result.source
                movie.source_url = raw.get("website") or raw.get("source_url")
                movie.genre = genre_str
                movie.tag = tag_str
                movie.is_uncensored = result.is_uncensored
                movie.is_mosaic = result.is_mosaic
                movie.is_chinese = result.is_chinese
                movie.file_size = file_size
                movie.file_date = file_date
                movie.status = "completed"
                movie.scraped_at = datetime.now()

                # 清除旧的演员关联，重新建立
                from sqlalchemy import delete as sa_delete
                await session.execute(
                    sa_delete(MovieActor).where(MovieActor.movie_id == movie.id)
                )

                # 清除旧的标签关联，重新建立
                from app.db.models import Tag, MovieTag
                await session.execute(
                    sa_delete(MovieTag).where(MovieTag.movie_id == movie.id)
                )
            else:
                # 创建新记录
                movie = Movie(
                    code=result.code,
                    title=result.title,
                    original_title=original_title,
                    title_jp=original_title,
                    studio_id=studio_id,
                    maker=result.maker,
                    series_id=series_id,
                    director=director,
                    release_date=str(result.release_date) if result.release_date else None,
                    duration=result.duration,
                    plot=result.plot,
                    plot_short=(result.plot[:200] + "...") if result.plot and len(result.plot) > 200 else result.plot,
                    cover_url=_local_cover or result.cover_url,
                    poster_url=_local_cover or result.poster_url,
                    thumb_url=_local_cover or result.poster_url or result.cover_url,
                    sample_images=json.dumps(_local_samples or result.sample_images, ensure_ascii=False) if (_local_samples or result.sample_images) else None,
                    trailer_url=result.trailer_url,
                    rating=result.rating,
                    source=result.source,
                    source_url=raw.get("website") or raw.get("source_url"),
                    genre=genre_str,
                    tag=tag_str,
                    is_uncensored=result.is_uncensored,
                    is_mosaic=result.is_mosaic,
                    is_chinese=result.is_chinese,
                    file_path=file_path,
                    file_size=file_size,
                    file_date=file_date,
                    status="completed",
                    scraped_at=datetime.now(),
                )
                session.add(movie)
                await session.flush()

            movie_id = movie.id

            # 保存演员
            for actor_info in result.actors:
                # 检查演员是否存在
                existing_actor = await session.execute(
                    select(Actor).where(Actor.name == actor_info.name)
                )
                actor = existing_actor.scalar_one_or_none()

                if not actor:
                    # 创建演员
                    actor = Actor(
                        name=actor_info.name,
                        name_jp=actor_info.japanese_name,
                        avatar_url=actor_info.avatar_url,
                    )
                    session.add(actor)
                    await session.flush()

                # 创建关联（避免重复）
                existing_link = await session.execute(
                    select(MovieActor).where(
                        MovieActor.movie_id == movie_id,
                        MovieActor.actor_id == actor.id,
                    )
                )
                if not existing_link.scalar_one_or_none():
                    link = MovieActor(movie_id=movie_id, actor_id=actor.id)
                    session.add(link)

            # 保存标签关联
            if result.genres:
                from app.db.models import Tag, MovieTag

                for genre_name in result.genres:
                    genre_name = genre_name.strip()
                    if not genre_name:
                        continue
                    # 查找或创建标签
                    existing_tag = await session.execute(
                        select(Tag).where(Tag.name == genre_name)
                    )
                    tag = existing_tag.scalar_one_or_none()
                    if not tag:
                        tag = Tag(name=genre_name, movie_count=0)
                        session.add(tag)
                        await session.flush()

                    # 创建关联
                    existing_mt = await session.execute(
                        select(MovieTag).where(
                            MovieTag.movie_id == movie_id,
                            MovieTag.tag_id == tag.id,
                        )
                    )
                    if not existing_mt.scalar_one_or_none():
                        link = MovieTag(movie_id=movie_id, tag_id=tag.id)
                        session.add(link)
                        tag.movie_count = (tag.movie_count or 0) + 1

            # 更新 Studio/Series 的 movie_count
            if studio_id:
                studio_obj = await session.get(Studio, studio_id)
                if studio_obj:
                    count = await session.scalar(
                        select(func.count()).select_from(
                            select(Movie.id).where(Movie.studio_id == studio_id).subquery()
                        )
                    )
                    studio_obj.movie_count = count or 0

            if series_id:
                series_obj = await session.get(Series, series_id)
                if series_obj:
                    count = await session.scalar(
                        select(func.count()).select_from(
                            select(Movie.id).where(Movie.series_id == series_id).subquery()
                        )
                    )
                    series_obj.movie_count = count or 0

            await session.commit()

        logger.info(f"已保存到数据库: {result.code}")

        # 推送刮削结果到 Emby（如果配置了）
        await self._push_to_emby(result, movie_dir)

    async def _push_to_emby(
        self,
        result: ScrapeResult,
        movie_dir: str,
    ) -> None:
        """推送刮削结果到 Emby（如果已配置）"""
        try:
            from app.config.manager import get_config
            config = get_config()

            if not config.emby.enabled or not config.emby.url or not config.emby.api_key:
                return

            from app.utils.emby import EmbyClient, EmbyConfig

            emby_config = EmbyConfig(
                url=config.emby.url,
                api_key=config.emby.api_key,
            )
            client = EmbyClient(emby_config)

            # 通过文件路径查找 Emby 中的项目
            if movie_dir:
                emby_item = await client.get_item_by_path(movie_dir)
                if not emby_item:
                    logger.info(f"Emby未找到路径: {movie_dir}")
                    return

                # 构建演员列表
                actors = [
                    {"name": a.name, "type": "Actor"}
                    for a in result.actors
                ] if result.actors else None

                # 构建制作商
                studios = []
                if result.studio:
                    studios.append(result.studio)
                if result.maker and result.maker != result.studio:
                    studios.append(result.maker)

                # 查找封面图片
                poster_path = None
                poster_file = Path(movie_dir) / "poster.jpg"
                if poster_file.exists():
                    poster_path = str(poster_file)

                # 推送
                success = await client.push_scraped_result(
                    item_id=emby_item.id,
                    title=result.title,
                    overview=result.plot,
                    genres=result.genres if result.genres else None,
                    actors=actors,
                    studios=studios if studios else None,
                    premiere_date=str(result.release_date) if result.release_date else None,
                    community_rating=result.rating,
                    image_path=poster_path,
                )

                if success:
                    logger.info(f"已推送到Emby: {result.code}")
                else:
                    logger.warning(f"Emby推送失败: {result.code}")

        except Exception as e:
            logger.warning(f"Emby推送已跳过: {e}")


async def scrape_file(
    file_path: str,
    output_dir: str,
    sources: Optional[list[str]] = None,
) -> Optional[ScrapeResult]:
    """
    刮削单个文件的便捷函数
    
    Args:
        file_path: 文件路径
        output_dir: 输出目录
        sources: 指定站点列表
        
    Returns:
        刮削结果
    """
    workflow = ScraperWorkflow(output_dir)
    return await workflow.process_file(file_path, sources)