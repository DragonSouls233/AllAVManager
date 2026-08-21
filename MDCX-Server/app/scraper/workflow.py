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
from app.db.module_db import ModuleDatabase
from app.output.images import ImageProcessor, download_movie_images
from app.output.nfo import NFOGenerator, generate_nfo
from app.scraper.engine import ScraperEngine, get_scraper_engine
from app.scraper.number import extract_number

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
    6. 数据库写入（模块数据库）
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

    def _source_to_module(self, source: str) -> str:
        """将刮削来源映射到模块子目录名称"""
        if not source:
            return "jav"
        _SOURCE_MODULE_MAP = {
            "javdb": "jav", "javbus": "jav", "dmm": "jav",
            "javlibrary": "jav", "arzon": "jav",
            "mgstage": "jav", "faleno": "jav", "prestige": "jav",
            "kawaii": "jav", "madou": "chinese", "guochan": "chinese",
            "fc2": "fc2", "fc2club": "fc2", "fc2ppvdb": "fc2",
            "pornhub": "pornhub", "western": "western",
            "adulttime": "western", "theporndb": "western",
            "aylo": "western",
        }
        return _SOURCE_MODULE_MAP.get(source, source)

    @staticmethod
    def _get_module_models(module: str):
        """根据模块名动态加载对应的模块模型类

        返回 (MovieModel, ActorModel, ModuleDatabase) 三元组。
        如果模块名无效或未注册，返回 None。
        """
        _MODEL_MAP = {
            "jav":       ("app.db.jav_models",       "JavMovie",       "JavActor"),
            "chinese":   ("app.db.chinese_models",   "ChineseMovie",   "ChineseActor"),
            "uncensored":("app.db.uncensored_models","UncensoredMovie","UncensoredActor"),
            "fc2":       ("app.db.fc2_models",       "Fc2Movie",       "Fc2Actor"),
            "pornhub":   ("app.db.pornhub_models",   "PornhubMovie",   "PornhubActor"),
            "western":   ("app.db.western_models",   "WesternMovie",   "WesternActor"),
        }
        entry = _MODEL_MAP.get(module)
        if not entry:
            return None
        import importlib
        mod = importlib.import_module(entry[0])
        MovieCls = getattr(mod, entry[1])
        ActorCls = getattr(mod, entry[2])
        db = ModuleDatabase.get_instance(module)
        return MovieCls, ActorCls, db
    
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
        
        # 3. 按模块分目录创建输出目录（data/movies/{模块}/{番号}/）
        module_name = self._source_to_module(result.source or "")
        movie_dir = self.output_dir / module_name / number
        movie_dir.mkdir(parents=True, exist_ok=True)
        
        # 4. 下载图片
        if self.download_images and result.cover_url:
            logger.info("正在下载图片")

            _referer = getattr(result, "source_url", None)
            if not _referer:
                _origin_map = {
                    "fc2": "https://adult.contents.fc2.com",
                    "javdb": "https://javdb.com",
                    "javbus": "https://www.javbus.com",
                    "avsox": "https://avsox.click",
                }
                _referer = _origin_map.get(result.source)

            async with ImageProcessor(str(movie_dir)) as processor:
                # 下载封面
                poster_path = await processor.download_cover(
                    result.cover_url,
                    str(movie_dir),
                    referer=_referer,
                )

                if poster_path:
                    logger.info(f"海报已保存: {poster_path}")

                # 下载背景图（使用封面）
                fanart_path = await processor.download_fanart(
                    result.cover_url,
                    str(movie_dir),
                    referer=_referer,
                )

                # 下载样图
                if result.sample_images:
                    sample_paths = await processor.download_samples(
                        result.sample_images,
                        str(movie_dir),
                        referer=_referer,
                    )
                    logger.info(f"已下载 {len(sample_paths)} 张预览图")
        
        # 5. 生成NFO
        if self.generate_nfo:
            logger.info("正在生成NFO")
            nfo_path = generate_nfo(result, str(movie_dir))
            
            if nfo_path:
                logger.info(f"NFO已保存: {nfo_path}")
        
        # 6. 保存到模块数据库
        if self.save_to_db:
            logger.info("正在保存到数据库")
            module_name = self._source_to_module(result.source or "")
            await self._save_to_db(result, str(movie_dir), file_path, module=module_name)
        
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
        module: Optional[str] = None,
    ) -> None:
        """保存到模块数据库（使用 SQLAlchemy ORM）

        始终写入模块数据库。当 module 未指定时，从刮削结果推断。
        中心数据库（scraper.db）已废弃。
        """
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

        # 无 module 时从来源推断
        if not module:
            if result.source:
                module = self._source_to_module(result.source)
            else:
                module = "jav"

        # ---- 写入模块数据库 ----
        models = self._get_module_models(module)
        if models is None:
            logger.warning(f"未知模块 [{module}]，默认回退到 jav")
            models = self._get_module_models("jav")
            if models is None:
                logger.error("无法获取任何模块数据库，跳过保存")
                return
            module = "jav"

        MovieCls, ActorCls, mod_db = models

        # 模块数据库没有 Studio/Series/MovieActor 关联表，使用简单字段
        async with mod_db.session_factory() as session:
            from sqlalchemy import select

            existing = await session.execute(
                select(MovieCls).where(MovieCls.code == result.code)
            )
            movie = existing.scalar_one_or_none()

            # 构造共有的字段字典
            common_fields = dict(
                title=result.title,
                original_title=original_title,
                cover_url=_local_cover or result.cover_url,
                poster_url=_local_cover or result.poster_url,
                thumb_url=_local_cover or result.poster_url or result.cover_url,
                sample_images=json.dumps(_local_samples or result.sample_images, ensure_ascii=False) if (_local_samples or result.sample_images) else None,
                release_date=str(result.release_date) if result.release_date else None,
                duration=result.duration,
                rating=result.rating,
                plot=result.plot,
                genre=genre_str,
                tag=tag_str,
                source=result.source,
                source_url=raw.get("website") or raw.get("source_url"),
                file_path=file_path,
                file_size=file_size,
                status="completed",
                scraped_at=datetime.now(),
            )

            # 模块特有字段
            # 大部分模块的 Movie 类有 actor 字段（逗号分隔名称）
            if result.actors:
                actor_names = ", ".join(a.name for a in result.actors)
                common_fields["actor"] = actor_names
            # studio 字段（不是外键，是普通字符串）
            if hasattr(MovieCls, "studio") and result.studio:
                common_fields["studio"] = result.studio
            if hasattr(MovieCls, "series") and result.series:
                common_fields["series"] = result.series
            if hasattr(MovieCls, "is_uncensored"):
                common_fields["is_uncensored"] = result.is_uncensored
            if hasattr(MovieCls, "is_mosaic"):
                common_fields["is_mosaic"] = result.is_mosaic

            if movie:
                # 更新现有记录
                for key, value in common_fields.items():
                    setattr(movie, key, value)
                # 额外字段只更新非空值
                if result.maker:
                    movie.studio = result.maker
            else:
                # 创建新记录
                movie = MovieCls(
                    code=result.code,
                    **common_fields,
                )
                session.add(movie)

            await session.flush()
            _movie_id = movie.id

            # 模块数据库的 Actor 通常是独立的，没有多对多关联表，直接记录名称
            # 无需创建 MovieActor 关联（模块模型没有该表）

        logger.info(f"已保存到模块数据库 [{module}]: {result.code}")

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
