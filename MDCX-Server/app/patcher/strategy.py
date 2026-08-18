"""
补刮策略引擎

定义不同的补刮策略：
- 只补图片：仅下载缺失的封面/海报/剧照
- 只补元数据：仅抓取缺失的标题/简介/标签
- 完整补刮：缺失严重时重新全量刮削
- 自定义：用户选择具体补哪些字段
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import text, select

from pathlib import Path
from app.patcher.detector import FieldType, ImageType, MissingInfo
from app.scraper.engine import ScraperEngine
from app.output.images import ImageProcessor
from app.output.nfo import NFOGenerator
from app.db.module_db import ModuleDatabase
from app.utils.module_helper import MODULE_TABLES

logger = logging.getLogger(__name__)


def _origin_of(url: str) -> Optional[str]:
    """取 URL 的源站（scheme://netloc），用作下载 Referer 以绕过防盗链。"""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return None


# 来源站点基础域名（用于构造详情页 Referer，绕过 javbus 等防盗链）
_SOURCE_BASE = {
    "javbus": "https://www.javbus.com",
    "javdb": "https://javdb.com",
    "javdatabase": "https://javdatabase.com",
    "avmoo": "https://avmoo.shop",
    "avsox": "https://avsox.click",
    "fanart": "https://fanart.tv",
}


def _detail_referer(source: Optional[str], code: Optional[str]) -> Optional[str]:
    """构造详情页 Referer（如 https://www.javbus.com/ABP-001）。

    javbus 等站点对封面/预览图有防盗链，仅带源站 Referer 仍会 403，
    必须带"来源详情页"才能下载。
    """
    if not source or not code:
        return None
    base = _SOURCE_BASE.get(source)
    if not base:
        return None
    return f"{base}/{code}"


def _is_downloadable_url(url: Optional[str]) -> bool:
    """判断是否是可下载的远程 URL。

    防线：本地文件路径（如 E:\\data\\movies\\jav\\ABC-123\\poster.jpg）
    绝不能进下载器——curl 会把 "E:" 解析成协议、冒号后的内容当端口，
    报 "URL rejected: Port number was not a decimal number between 0 and 65535"。
    """
    if not url or not isinstance(url, str):
        return False
    return url.startswith(("http://", "https://"))


def _complete_url(url: str, source: Optional[str] = None) -> str:
    """补全相对路径图片 URL 为完整 URL

    示例: /pics/sample/954d_1.jpg -> https://www.javbus.com/pics/sample/954d_1.jpg
    """
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if source:
        base = _SOURCE_BASE.get(source)
        if base:
            return f"{base.rstrip('/')}{url}" if url.startswith("/") else f"{base}/{url}"
    return url


def _json_safe(o):
    """json.dumps 容错：将 ActorInfo 等不可序列化对象转为可读字符串。"""
    if isinstance(o, list):
        return [_json_safe(v) for v in o]
    if hasattr(o, "name"):
        return getattr(o, "name")
    if hasattr(o, "__dict__"):
        return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
    return str(o)


class PatchType(str, Enum):
    """补刮类型"""
    IMAGES_ONLY = "images_only"       # 只补图片
    METADATA_ONLY = "metadata_only"   # 只补元数据
    FULL = "full"                     # 完整补刮
    CUSTOM = "custom"                 # 自定义
    SMART = "smart"                   # 智能选择


class PatchStatus(str, Enum):
    """补刮状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"   # 部分成功
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PatchPlan:
    """补刮计划"""
    movie_id: int
    movie_code: str
    patch_type: PatchType
    
    # 要补的字段
    fields_to_patch: list[FieldType] = field(default_factory=list)
    
    # 要补的图片
    images_to_patch: list[ImageType] = field(default_factory=list)
    
    # 是否需要重新刮削
    need_scrape: bool = False
    
    # 是否需要下载图片
    need_download_images: bool = False
    
    # 是否需要更新 NFO
    need_update_nfo: bool = False
    
    def to_dict(self) -> dict:
        return {
            "movie_id": self.movie_id,
            "movie_code": self.movie_code,
            "patch_type": self.patch_type.value,
            "fields_to_patch": [f.value for f in self.fields_to_patch],
            "images_to_patch": [i.value for i in self.images_to_patch],
            "need_scrape": self.need_scrape,
            "need_download_images": self.need_download_images,
            "need_update_nfo": self.need_update_nfo,
        }


@dataclass
class PatchResult:
    """补刮结果"""
    movie_id: int
    movie_code: str
    patch_type: PatchType
    status: PatchStatus
    
    # 补刮的字段
    patched_fields: list[str] = field(default_factory=list)
    
    # 补刮的图片
    patched_images: list[str] = field(default_factory=list)
    
    # 失败的字段
    failed_fields: list[str] = field(default_factory=list)
    
    # 失败的图片
    failed_images: list[str] = field(default_factory=list)
    
    # 错误信息
    error_message: Optional[str] = None
    
    # 时间信息
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    
    def duration_seconds(self) -> float:
        """耗时（秒）"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
    
    def to_dict(self) -> dict:
        return {
            "movie_id": self.movie_id,
            "movie_code": self.movie_code,
            "patch_type": self.patch_type.value,
            "status": self.status.value,
            "patched_fields": self.patched_fields,
            "patched_images": self.patched_images,
            "failed_fields": self.failed_fields,
            "failed_images": self.failed_images,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds(),
        }


class PatchStrategy:
    """
    补刮策略
    
    根据缺失情况决定补刮策略
    """
    
    # 触发完整补刮的关键缺失阈值
    CRITICAL_THRESHOLD = 3
    
    # 触发完整补刮的总缺失阈值
    TOTAL_THRESHOLD = 10
    
    def __init__(
        self,
        critical_threshold: int = 3,
        total_threshold: int = 10,
    ):
        """
        初始化
        
        Args:
            critical_threshold: 关键缺失阈值
            total_threshold: 总缺失阈值
        """
        self.critical_threshold = critical_threshold
        self.total_threshold = total_threshold
    
    def create_plan(
        self,
        missing_info: MissingInfo,
        patch_type: Optional[PatchType] = None,
        custom_fields: Optional[list[FieldType]] = None,
        custom_images: Optional[list[ImageType]] = None,
    ) -> PatchPlan:
        """
        创建补刮计划
        
        Args:
            missing_info: 缺失信息
            patch_type: 指定补刮类型（None 为智能选择）
            custom_fields: 自定义字段列表（CUSTOM 类型时使用）
            custom_images: 自定义图片列表（CUSTOM 类型时使用）
            
        Returns:
            PatchPlan 补刮计划
        """
        plan = PatchPlan(
            movie_id=missing_info.movie_id,
            movie_code=missing_info.movie_code,
            patch_type=patch_type or PatchType.SMART,
        )
        
        # 根据类型决定补刮内容
        if plan.patch_type == PatchType.IMAGES_ONLY:
            plan.images_to_patch = self._get_missing_image_types(missing_info)
            plan.need_download_images = bool(plan.images_to_patch)
            # 下载图片必须先拿到 URL：重新刮削以取得封面/预览图地址
            plan.need_scrape = bool(plan.images_to_patch)
            plan.need_update_nfo = False
        
        elif plan.patch_type == PatchType.METADATA_ONLY:
            plan.fields_to_patch = self._get_missing_field_types(missing_info)
            plan.need_scrape = bool(plan.fields_to_patch)
            plan.need_update_nfo = bool(plan.fields_to_patch)
            plan.need_download_images = False
        
        elif plan.patch_type == PatchType.CUSTOM:
            plan.fields_to_patch = custom_fields or []
            plan.images_to_patch = custom_images or []
            plan.need_scrape = bool(plan.fields_to_patch)
            plan.need_download_images = bool(plan.images_to_patch)
            plan.need_update_nfo = bool(plan.fields_to_patch)
        
        elif plan.patch_type == PatchType.FULL:
            plan.fields_to_patch = list(FieldType)
            plan.images_to_patch = list(ImageType)
            plan.need_scrape = True
            plan.need_download_images = True
            plan.need_update_nfo = True
        
        else:  # SMART
            plan = self._create_smart_plan(missing_info)
        
        return plan
    
    def _create_smart_plan(self, missing_info: MissingInfo) -> PatchPlan:
        """创建智能补刮计划"""
        plan = PatchPlan(
            movie_id=missing_info.movie_id,
            movie_code=missing_info.movie_code,
            patch_type=PatchType.SMART,
        )
        
        # 计算缺失程度
        critical_count = missing_info.critical_missing_count()
        total_count = missing_info.total_missing_count()
        
        # 判断是否需要完整补刮
        if critical_count >= self.critical_threshold or total_count >= self.total_threshold:
            logger.info(
                f"Movie {missing_info.movie_code} 需要完整补刮: "
                f"critical={critical_count}, total={total_count}"
            )
            plan.patch_type = PatchType.FULL
            plan.fields_to_patch = self._get_missing_field_types(missing_info)
            plan.images_to_patch = self._get_missing_image_types(missing_info)
            plan.need_scrape = True
            plan.need_download_images = True
            plan.need_update_nfo = True
            return plan
        
        # 分别处理字段和图片
        missing_fields = self._get_missing_field_types(missing_info)
        missing_images = self._get_missing_image_types(missing_info)
        
        plan.fields_to_patch = missing_fields
        plan.images_to_patch = missing_images
        
        plan.need_scrape = bool(missing_fields)
        plan.need_download_images = bool(missing_images)
        plan.need_update_nfo = bool(missing_fields) or not missing_info.nfo_exists
        
        return plan
    
    def _get_missing_field_types(self, missing_info: MissingInfo) -> list[FieldType]:
        """获取缺失的字段类型列表"""
        return [f.field_type for f in missing_info.missing_fields]
    
    def _get_missing_image_types(self, missing_info: MissingInfo) -> list[ImageType]:
        """获取缺失的图片类型列表"""
        return [i.image_type for i in missing_info.missing_images]


class PatchEngine:
    """
    补刮引擎
    
    执行补刮任务
    """
    
    def __init__(
        self,
        scraper_engine: Optional[ScraperEngine] = None,
        image_processor: Optional[ImageProcessor] = None,
        nfo_generator: Optional[NFOGenerator] = None,
        sources: Optional[list[str]] = None,
    ):
        """
        初始化
        
        Args:
            scraper_engine: 刮削引擎
            image_processor: 图片处理器
            nfo_generator: NFO 生成器
            sources: 指定刮削来源站点列表（如 ['javbus','javdb']），None 表示自动
        """
        self.scraper_engine = scraper_engine or ScraperEngine()
        self.image_processor = image_processor or ImageProcessor(output_dir=self._get_default_output_dir())
        self.nfo_generator = nfo_generator or NFOGenerator(output_dir=self._get_default_output_dir())
        self.strategy = PatchStrategy()
        self.sources = sources

    @staticmethod
    def _get_default_output_dir() -> str:
        """获取默认输出目录"""
        try:
            from app.config.manager import get_config_manager
            manager = get_config_manager()
            return str(manager.computed.data_dir / "images")
        except Exception:
            return "data/images"
    
    async def patch(
        self,
        missing_info: MissingInfo,
        patch_type: Optional[PatchType] = None,
        custom_fields: Optional[list[FieldType]] = None,
        custom_images: Optional[list[ImageType]] = None,
        sources: Optional[list[str]] = None,
        module: Optional[str] = None,
    ) -> PatchResult:
        """
        执行补刮
        
        Args:
            missing_info: 缺失信息
            patch_type: 补刮类型
            custom_fields: 自定义字段
            custom_images: 自定义图片
            
        Returns:
            PatchResult 补刮结果
        """
        result = PatchResult(
            movie_id=missing_info.movie_id,
            movie_code=missing_info.movie_code,
            patch_type=patch_type or PatchType.SMART,
            status=PatchStatus.PENDING,
        )
        
        result.started_at = datetime.now()
        
        try:
            # 1. 创建补刮计划
            plan = self.strategy.create_plan(
                missing_info,
                patch_type,
                custom_fields,
                custom_images,
            )
            
            logger.info(
                f"补刮计划: {missing_info.movie_code}: "
                f"字段={len(plan.fields_to_patch)}, 图片={len(plan.images_to_patch)}"
            )
            
            result.status = PatchStatus.RUNNING

            # 解析本次补刮使用的来源站点（显式传入优先，否则用引擎默认）
            effective_sources = sources if sources is not None else self.sources

            # 2. 执行刮削（如果需要）
            scraped_data = None
            if plan.need_scrape:
                scraped_data = await self._scrape_missing(
                    missing_info.movie_code,
                    plan.fields_to_patch,
                    sources=effective_sources,
                    missing_info=missing_info,
                    need_images=plan.need_download_images,
                    module=module or self._detect_module(missing_info),
                )
                
                if scraped_data:
                    result.patched_fields = [f.value for f in plan.fields_to_patch]
                else:
                    result.failed_fields = [f.value for f in plan.fields_to_patch]
            
            # 3. 下载图片（如果需要）
            if plan.need_download_images:
                downloaded = await self._download_missing_images(
                    missing_info,
                    plan.images_to_patch,
                    scraped_data,
                )
                
                result.patched_images = downloaded
                result.failed_images = [
                    i.value for i in plan.images_to_patch 
                    if i.value not in downloaded
                ]
            
            # 4. 更新 NFO（如果需要）
            if plan.need_update_nfo and scraped_data:
                await self._update_nfo(missing_info, scraped_data)
            
            # 5. 更新数据库（仅模块数据库）
            if scraped_data or result.patched_images:
                await self._update_database(
                    missing_info.movie_id,
                    scraped_data,
                    result.patched_images,
                    output_dir=missing_info.output_dir,
                    module=self._detect_module(missing_info),
                )
            
            # 6. 判断最终状态
            if result.failed_fields or result.failed_images:
                if result.patched_fields or result.patched_images:
                    result.status = PatchStatus.PARTIAL
                else:
                    result.status = PatchStatus.FAILED
            else:
                result.status = PatchStatus.SUCCESS

            logger.info(
                f"补刮完成: {missing_info.movie_code} "
                f"状态={result.status.value} "
                f"(字段={len(result.patched_fields)}/{len(result.failed_fields)}, "
                f"图片={len(result.patched_images)}/{len(result.failed_images)})"
            )
        
        except Exception as e:
            logger.error(f"补刮失败: {missing_info.movie_code}: {e}")
            result.status = PatchStatus.FAILED
            result.error_message = str(e)
        
        finally:
            result.finished_at = datetime.now()
        
        return result
    
    async def patch_batch(
        self,
        missing_infos: list[MissingInfo],
        patch_type: Optional[PatchType] = None,
        concurrency: int = 3,
    ) -> list[PatchResult]:
        """
        批量补刮
        
        Args:
            missing_infos: 缺失信息列表
            patch_type: 补刮类型
            concurrency: 并发数
            
        Returns:
            补刮结果列表
        """
        results = []
        semaphore = asyncio.Semaphore(concurrency)

        async def _patch_one(info: MissingInfo) -> PatchResult:
            async with semaphore:
                return await self.patch(info, patch_type)

        tasks = [_patch_one(info) for info in missing_infos]
        results = await asyncio.gather(*tasks)

        return results
    
    def _detect_module(self, missing_info: MissingInfo) -> Optional[str]:
        """从 missing_info 推断所属模块"""
        # 优先从 output_dir 路径推断（格式：.../data/movies/{module}/{code}/）
        if missing_info.output_dir:
            from pathlib import Path
            parts = Path(missing_info.output_dir).parts
            for i, part in enumerate(parts):
                if part == "movies" and i + 1 < len(parts):
                    return parts[i + 1]
        return None

    async def _get_video_file_dir(self, missing_info: MissingInfo) -> Optional[Path]:
        """从模块数据库查询 file_path，返回视频文件所在目录。

        用于在补刮时复用视频目录下已有的 NFO / 封面 / poster 等资源。
        """
        module = self._detect_module(missing_info)
        if not module or not missing_info.movie_code:
            return None
        try:
            mod_db = ModuleDatabase.get_instance(module)
            session = await mod_db.get_session()
            try:
                async with session:
                    from sqlalchemy import text
                    table_info = MODULE_TABLES.get(module)
                    if not table_info:
                        return None
                    _, movie_table = table_info
                    result = await session.execute(
                        text(f"SELECT file_path FROM {movie_table} WHERE code = :code"),
                        {"code": missing_info.movie_code},
                    )
                    row = result.fetchone()
                    if row and row[0]:
                        video_path = Path(row[0])
                        if video_path.exists():
                            return video_path.parent
            finally:
                await session.close()
        except Exception:
            pass
        return None

    async def _find_nearby_nfo(
        self, missing_info: MissingInfo,
    ) -> tuple[Optional[Path], Optional[dict]]:
        """在 output_dir（数据中心）和视频文件目录中查找 movie.nfo，返回 (nfo_path, parsed_dict)。

        优先级：output_dir > 视频目录（output_dir 是扫描时归集的单一数据源，已含视频目录
        复制来的 NFO + 后续刮削写入的本地 NFO；视频目录仅作兜底，避免读取到未刮削的瘦 NFO）
        """
        nfo_paths = []
        video_dir = await self._get_video_file_dir(missing_info)
        if video_dir:
            nfo_paths.append(video_dir / "movie.nfo")
        if missing_info.output_dir:
            nfo_paths.insert(0, Path(missing_info.output_dir) / "movie.nfo")  # 数据中心优先

        from app.importer.nfo_parser import NFOParser
        parser = NFOParser()
        for nfo_path in nfo_paths:
            if not nfo_path.exists():
                continue
            try:
                imported = parser.parse(str(nfo_path))
                if imported and imported.is_valid():
                    return nfo_path, self._nfo_to_scraped_dict(imported, missing_info.movie_code)
            except Exception:
                continue
        return None, None

    @staticmethod
    def _nfo_to_scraped_dict(imported, code: str) -> dict:
        """将 NFOParser.ImportedMovie 转为与刮削结果一致的 dict"""
        actors = list(imported.actors or [])
        return {
            "code": imported.code or code,
            "title": imported.title,
            "original_title": imported.original_title,
            "title_jp": None, "title_en": None,
            "plot": imported.plot,
            "plot_jp": None, "plot_en": None, "plot_short": None, "original_plot": None,
            "release_date": imported.release_date.isoformat() if imported.release_date else None,
            "duration": imported.duration,
            "studio": imported.studio, "maker": imported.maker,
            "publisher": None, "label": None,
            "series": imported.series, "director": imported.director,
            "genre": ",".join(imported.genres) if imported.genres else None,
            "genres": imported.genres, "tags": [],
            "actors": actors,
            "cover_url": None, "poster_url": None, "thumb_url": None, "fanart_url": None,
            "trailer_url": None, "sample_images": [],
            "rating": None, "votes": None, "website": None, "source_url": None,
            "javdb_id": None,
            "source": "nfo_cache",
            "is_uncensored": imported.is_uncensored,
            "is_chinese": imported.is_chinese,
        }

    async def _copy_nearby_cover_images(
        self, missing_info: MissingInfo, image_types: list[ImageType],
    ) -> list[str]:
        """从视频文件所在目录拷贝已有的封面/海报图片到 output_dir。

        返回已成功拷贝的图片类型名称列表。
        """
        if not missing_info.output_dir:
            return []
        output = Path(missing_info.output_dir)
        video_dir = await self._get_video_file_dir(missing_info)
        if not video_dir:
            return []

        # 视频目录中常见的封面文件命名
        COVER_CANDIDATES: dict[ImageType, list[str]] = {
            ImageType.POSTER: ["poster.jpg", "poster.png", "cover.jpg", "cover.png", "folder.jpg"],
            ImageType.FANART: ["fanart.jpg", "fanart.png", "backdrop.jpg", "background.jpg"],
            ImageType.COVER:  ["cover.jpg", "cover.png", "landscape.jpg", "poster.jpg"],
            ImageType.THUMB:  ["thumb.jpg", "thumb.png", "smallcover.jpg"],
        }

        import shutil
        copied = []
        for img_type in image_types:
            candidates = COVER_CANDIDATES.get(img_type, [])
            found = False
            for candidate in candidates:
                src = video_dir / candidate
                if src.exists() and src.stat().st_size > 1024:
                    # 拷贝到 output_dir，按标准命名（{type}.jpg）
                    dst = output / f"{img_type.value}.jpg"
                    try:
                        shutil.copy2(src, dst)
                        logger.info(f"从视频目录拷贝封面: {src} → {dst}")
                        copied.append(img_type.value)
                        found = True
                        break
                    except Exception as e:
                        logger.warning(f"拷贝封面失败: {src} → {dst}: {e}")
                # 也尝试 png 后缀
                src_png = video_dir / candidate
                if not src_png.exists():
                    src_png = video_dir / candidate.replace(".jpg", ".png")
                if src_png.exists() and src_png.stat().st_size > 1024:
                    dst = output / f"{img_type.value}.jpg"
                    try:
                        shutil.copy2(src_png, dst)
                        logger.info(f"从视频目录拷贝封面: {src_png} → {dst}")
                        copied.append(img_type.value)
                        found = True
                        break
                    except Exception as e:
                        logger.warning(f"拷贝封面失败: {src_png} → {dst}: {e}")
            if not found:
                logger.debug(f"视频目录未找到 {img_type.value} 封面: {video_dir}")
        return copied

    async def _scrape_missing(
        self,
        code: str,
        fields: list[FieldType],
        sources: Optional[list[str]] = None,
        missing_info: Optional[MissingInfo] = None,
        need_images: bool = False,
        module: Optional[str] = None,
    ) -> Optional[dict]:
        """刮削缺失字段

        优先从已存在的 NFO 文件读取（如果输出目录下有 movie.nfo 就不走网络爬虫）。

        重要：NFO 里**只有本地图片路径，没有远程图片 URL**。
        因此当本次补刮需要下载图片时，NFO 缓存不足以完成任务，
        必须继续走网络爬虫拿真实图片 URL；网络失败再回退到 NFO 字段。
        （历史 bug：曾把本地 poster.jpg 绝对路径塞进 cover_url/poster_url，
        导致 curl 把 "E:" 当协议、"\\MDCX-Server\\..." 当端口，
        报 "URL rejected: Port number was not a decimal number"，图片 100% 失败。）

        Args:
            code: 番号
            fields: 需要补的字段（用于判断是否需要重新刮削）
            sources: 指定刮削来源站点列表；None 表示自动选择
            missing_info: 缺失信息（用于获取输出目录以读取 NFO）
            need_images: 本次补刮是否需要下载图片
        """
        # ---- 优先从 NFO 缓存读取 ----
        nfo_cached: Optional[dict] = None
        if missing_info:
            nfo_path, nfo_cached = await self._find_nearby_nfo(missing_info)

        # 仅补字段时，NFO 缓存已足够，跳过网络爬虫（快速路径）
        if nfo_cached and not need_images:
            logger.info(f"NFO 缓存命中: {code} (仅补字段，跳过网络爬虫)")
            return nfo_cached

        if nfo_cached:
            logger.info(
                f"NFO 缓存命中但需下载图片: {code} "
                f"(NFO 无远程图片 URL，改走网络爬虫获取图片地址)"
            )

        # ---- 走网络爬虫 ----
        try:
            # 模块维度选爬虫：从 missing_info.output_dir 推断模块
            # （格式 .../data/movies/{module}/{code}/），保证 western/pornhub
            # 模块只走各自专属爬虫，不误用 JAV 有码爬虫。
            detected_module = module or (
                self._detect_module(missing_info) if missing_info else None
            )
            # 使用刮削引擎直接刮削番号（支持按来源站点 / 模块过滤）
            result = await self.scraper_engine.scrape_number(
                code, sources=sources, module=detected_module
            )

            if result:
                # 转换为字典（全部用 getattr 容错，避免 ScrapeResult 字段缺失导致崩溃）
                directors = getattr(result, "directors", None) or []
                director_val = ", ".join(directors) if directors else None
                return {
                    "code": code,
                    "title": getattr(result, "title", None),
                    "original_title": getattr(result, "original_title", None) or getattr(result, "title_jp", None),
                    "title_jp": getattr(result, "title_jp", None),
                    "title_en": getattr(result, "title_en", None),
                    "plot": getattr(result, "plot", None),
                    "plot_jp": getattr(result, "plot_jp", None) or getattr(result, "original_plot", None),
                    "plot_en": getattr(result, "plot_en", None),
                    "plot_short": getattr(result, "plot_short", None),
                    "original_plot": getattr(result, "original_plot", None),
                    "release_date": getattr(result, "release_date", None),
                    "duration": getattr(result, "duration", None),
                    "studio": getattr(result, "studio", None),
                    "maker": getattr(result, "maker", None),
                    "publisher": getattr(result, "publisher", None) or getattr(result, "maker", None),
                    "label": getattr(result, "label", None) or getattr(result, "series", None),
                    "series": getattr(result, "series", None),
                    "director": director_val,
                    "genre": getattr(result, "genres", None),
                    "genres": getattr(result, "genres", None),
                    "tags": getattr(result, "tags", None) or [],
                    "actors": getattr(result, "actors", None),
                    "cover_url": getattr(result, "cover_url", None),
                    "poster_url": getattr(result, "poster_url", None),
                    "thumb_url": getattr(result, "cover_url", None),
                    "fanart_url": getattr(result, "cover_url", None),
                    "trailer_url": getattr(result, "trailer_url", None),
                    "sample_images": getattr(result, "sample_images", None) or [],
                    "rating": getattr(result, "rating", None),
                    "votes": getattr(result, "votes", None),
                    "website": getattr(result, "website", None) or getattr(result, "source_url", None),
                    "source_url": getattr(result, "source_url", None),
                    "javdb_id": getattr(result, "javdb_id", None),
                    "source": getattr(result, "source", None),
                    "is_uncensored": getattr(result, "is_uncensored", None),
                    "is_chinese": getattr(result, "is_chinese", None),
                }
        
        except Exception as e:
            logger.error(f"刮削失败: {code}: {e}")

        # 网络爬虫失败：回退到 NFO 缓存（至少字段能补上，图片本轮补不了）
        if nfo_cached:
            logger.info(f"网络刮削失败，回退 NFO 缓存字段: {code}")
            return nfo_cached

        return None
    
    async def _download_missing_images(
        self,
        missing_info: MissingInfo,
        image_types: list[ImageType],
        scraped_data: Optional[dict],
    ) -> list[str]:
        """下载缺失图片

        支持 poster/fanart/thumb/cover（单图）与 extrafanart（预览图，多图目录）。

        优先从视频文件所在目录拷贝已有封面/海报（零网络开销），
        拷贝不到的才走网络下载。
        """
        downloaded = []

        if not missing_info.output_dir:
            logger.warning(f"无输出目录: {missing_info.movie_code}")
            return downloaded

        # ---- 1) 先尝试从视频目录拷贝本地封面 ----
        nearby = await self._copy_nearby_cover_images(missing_info, image_types)
        for img_type_val in nearby:
            if img_type_val not in downloaded:
                downloaded.append(img_type_val)
                logger.info(
                    f"本地封面命中: {missing_info.movie_code} {img_type_val} "
                    f"(从视频目录拷贝，无需网络)"
                )

        # 过滤：已本地拷贝成功的不再走网络
        remaining = [t for t in image_types if t.value not in downloaded]

        # ---- 2) 网络下载剩余的 ----
        if not remaining:
            return downloaded

        async with self.image_processor as proc:
            source = (scraped_data or {}).get("source")
            for image_type in remaining:
                try:
                    # 预览图（extrafanart）：多图，写入 output_dir/extrafanart/
                    if image_type == ImageType.EXTRAFANART:
                        samples = (scraped_data or {}).get("sample_images") or []
                        if not samples:
                            continue
                        samples = [_complete_url(s, source) for s in samples]
                        samples = [s for s in samples if _is_downloadable_url(s)]
                        if not samples:
                            logger.debug(
                                f"跳过 extrafanart：无合法远程 URL "
                                f"({missing_info.movie_code})"
                            )
                            continue
                        referer = _detail_referer(source, missing_info.movie_code) or _origin_of(
                            samples[0]
                        ) if samples else None
                        saved = await proc.download_samples(
                            samples,
                            missing_info.output_dir,
                            subdir="extrafanart",
                            referer=referer,
                        )
                        if saved:
                            downloaded.append(image_type.value)
                        continue

                    # 单图类型（poster/fanart/thumb/cover）：对应 <type>_url
                    url_key = f"{image_type.value}_url"
                    url = (scraped_data or {}).get(url_key)
                    if not url and missing_info.cover_url_fallback:
                        if image_type in (ImageType.POSTER, ImageType.COVER):
                            url = missing_info.cover_url_fallback
                    if not url:
                        continue

                    url = _complete_url(url, source)
                    if not _is_downloadable_url(url):
                        logger.debug(
                            f"跳过非法图片 URL ({image_type.value}): "
                            f"{missing_info.movie_code} -> {url!r}"
                        )
                        continue

                    referer = _detail_referer(source, missing_info.movie_code) or _origin_of(url)
                    output_path = f"{missing_info.output_dir}/{image_type.value}.jpg"
                    saved = await proc.download_image(url, output_path, referer=referer)
                    if saved:
                        downloaded.append(image_type.value)

                except Exception as e:
                    logger.error(f"下载图片失败 ({image_type.value}): {e}")

        return downloaded
    
    async def _update_nfo(
        self,
        missing_info: MissingInfo,
        scraped_data: dict,
    ) -> bool:
        """更新 NFO 文件

        scraped_data 是 _scrape_missing 返回的 dict，
        但 NFOGenerator.generate() 期望 ScrapeResult 对象（用属性访问）。
        用 SimpleNamespace 把 dict 包一层，让 .title / .plot 等属性访问生效。

        fix22: scraped_data 经常缺 original_title / title_jp / publisher / label /
        website / javdb_id / trailer_url / play_count / last_played_at / file_path
        等字段，直接传 dict 会 AttributeError。
        解决：先用 NFOGenerator 期望的所有字段名打地基（None 默认），
        再用 scraped_data 覆盖存在的字段，保证 NFO generator 任何属性访问都安全。
        """
        if not missing_info.output_dir:
            return False

        try:
            from types import SimpleNamespace

            # 1) 基础字段：用 scraped_data 覆盖，未提供则 None
            # 可迭代字段（NFO 生成器用 for 遍历）必须默认 [] 而非 None
            base_scalar = {
                "title", "original_title", "title_jp", "title_en",
                "plot", "plot_jp", "plot_en", "plot_short", "original_plot",
                "release_date", "year", "duration",
                "rating", "score", "votes",
                "director", "maker", "publisher", "label",
                "series", "studio", "source", "source_url", "website",
                "javdb_id", "code",
                "cover_url", "poster_url", "thumb_url", "fanart_url",
                "trailer_url",
                "is_mosaic", "is_uncensored", "is_chinese",
                "play_count", "last_played_at", "file_path",
            }
            base_list: set[str] = {
                "actors", "actresses", "all_actors", "genres", "tags", "directors",
                "sample_images", "extrafanart",
            }
            nfo_kwargs: dict = {k: None for k in base_scalar}
            nfo_kwargs.update({k: [] for k in base_list})
            nfo_kwargs.update({k: v for k, v in scraped_data.items() if k in base_scalar | base_list})
            # 2) 直接把 scraped_data 全部字段也带过来（其它 generator 可能用到）
            for k, v in scraped_data.items():
                if k not in nfo_kwargs:
                    nfo_kwargs[k] = v
            # fix26: NFO 生成器内部会读取 result.raw_data（如 javdb_id / magnets 兜底），
            # SimpleNamespace 没有该属性就会 AttributeError。统一补一个空 dict 兜底。
            nfo_kwargs.setdefault("raw_data", {})
            nfo_data = SimpleNamespace(**nfo_kwargs)

            # 3) actors：list[ActorInfo] 或 list[str] → 统一为有 .name 属性的对象列表
            raw_actors = scraped_data.get("actors") or scraped_data.get("actresses") or []
            actor_objs = []
            for a in raw_actors:
                if hasattr(a, "name"):
                    actor_objs.append(a)
                elif isinstance(a, dict):
                    actor_objs.append(SimpleNamespace(**a))
                else:
                    actor_objs.append(SimpleNamespace(name=str(a)))
            nfo_data.actors = actor_objs

            # 4) genres：scraped_data 里叫 genre，NFO 期望 genres
            nfo_data.genres = scraped_data.get("genres") or scraped_data.get("genre") or []
            # 5) directors：scraped_data 里叫 director（str），NFO 期望 list
            director_val = scraped_data.get("director")
            if isinstance(director_val, list):
                nfo_data.directors = director_val
            elif director_val:
                nfo_data.directors = [director_val]
            else:
                nfo_data.directors = []
            # 6) extrafanart 别名映射
            nfo_data.extrafanart = scraped_data.get("extrafanart") or scraped_data.get("sample_images") or []

            # 7) source 兜底
            if not nfo_data.source:
                nfo_data.source = "patcher"

            nfo_path = f"{missing_info.output_dir}/movie.nfo"
            # 确保 movie_dir 是目录（file_path 传过来时可能是文件路径）
            movie_dir = missing_info.output_dir
            if movie_dir and not os.path.isdir(movie_dir):
                parent = os.path.dirname(movie_dir)
                if parent and os.path.isdir(parent):
                    movie_dir = parent
            self.nfo_generator.generate(nfo_data, movie_dir=movie_dir)
            return True
        
        except Exception as e:
            logger.error(f"更新NFO失败: {e}")
            return False
    
    # ---- 模块数据库字段映射（scraped key → DB column） ----
    # 注意: 修复历史 bug —— "maker" 曾错误映射到 "studio" 列，导致 NFO/刮削结果里
    # studio 与 maker 同时存在时生成重复列 SET studio=:studio, studio=:studio，
    # SQLite 取最后值 → maker 值覆盖真正的 studio；director 则完全没有映射被丢弃。
    # 现各归各列：studio→studio / maker→maker / director→director。
    _MODULE_COLUMN_MAP = {
        "title": "title",
        "original_title": "original_title",
        "plot": "plot",
        "release_date": "release_date",
        "duration": "duration",
        "rating": "rating",
        "genre": "genre",
        "source": "source",
        "source_url": "source_url",
        "cover_url": "cover_url",
        "poster_url": "poster_url",
        "thumb_url": "thumb_url",
        "trailer_url": "trailer_url",
        "sample_images": "sample_images",
        "studio": "studio",
        "series": "series",
        "maker": "maker",
        "director": "director",
    }

    async def _update_module_database(
        self,
        movie_id: int,
        scraped_data: Optional[dict],
        patched_images: list[str],
        output_dir: Optional[str],
        module: str,
    ) -> bool:
        """使用原生 SQL 更新模块数据库"""
        try:
            mod_db = ModuleDatabase.get_instance(module)
            session = await mod_db.get_session()
        except Exception as e:
            logger.error(f"获取模块数据库失败 ({module}): {e}")
            return False

        table_info = MODULE_TABLES.get(module)
        if not table_info:
            logger.error(f"未知模块: {module}")
            return False
        _actor_table, movie_table = table_info

        try:
            async with session:
                # 按番号查找记录
                code = (scraped_data or {}).get("code")
                if not code:
                    logger.warning(f"模块数据库更新：无番号，movie_id={movie_id}")
                    return False

                result = await session.execute(
                    text(f"SELECT id FROM {movie_table} WHERE code = :code"),
                    {"code": code},
                )
                row = result.fetchone()
                if not row:
                    logger.warning(f"模块数据库未找到番号: {code}")
                    return False

                mod_movie_id = row[0]

                # 更新 output_dir（模块表不一定有该列，容错）
                if output_dir:
                    try:
                        await session.execute(
                            text(f"UPDATE {movie_table} SET output_dir = :dir WHERE id = :id"),
                            {"dir": output_dir, "id": mod_movie_id},
                        )
                    except Exception:
                        pass  # 该模块表没有 output_dir 列

                if scraped_data:
                    updates = []
                    params = {}

                    for key, value in scraped_data.items():
                        if value is None:
                            continue
                        col = self._MODULE_COLUMN_MAP.get(key)
                        if col is None:
                            continue
                        if isinstance(value, list):
                            value = json.dumps(value, ensure_ascii=False, default=_json_safe)
                        updates.append(f"{col} = :{col}")
                        params[col] = value

                    # --- 处理 actors（模块表多为 actor 单列，western 为 actors 文本列） ---
                    actors_data = scraped_data.get("actors")
                    if actors_data:
                        actor_names = [
                            a.name if hasattr(a, "name")
                            else a.get("name") if isinstance(a, dict)
                            else str(a)
                            for a in actors_data
                        ]
                        joined = ", ".join(filter(None, actor_names))
                        if joined:
                            updates.append("actor = :actor")
                            params["actor"] = joined

                    if updates:
                        params["id"] = mod_movie_id
                        query = f"UPDATE {movie_table} SET {', '.join(updates)} WHERE id = :id"
                        await session.execute(text(query), params)

                    # 标记刮削完成 + 更新 scraped_at，让 skip_recent_days 机制生效
                    await session.execute(
                        text(f"UPDATE {movie_table} SET status = 'scraped', scraped_at = :now WHERE id = :id"),
                        {"id": mod_movie_id, "now": datetime.now().isoformat()},
                    )

                    await session.commit()

            return True

        except Exception as e:
            logger.error(f"更新模块数据库失败 ({module}): {e}")
            return False

    async def _update_database(
        self,
        movie_id: int,
        scraped_data: Optional[dict],
        patched_images: list[str],
        output_dir: Optional[str] = None,
        module: Optional[str] = None,
    ) -> bool:
        """更新模块数据库
        
        中心数据库已废弃，仅更新模块数据库。
        当 module 未指定时，跳过更新。
        """
        if not module:
            logger.warning("模块未指定，跳过数据库更新")
            return False
        return await self._update_module_database(
            movie_id, scraped_data, patched_images, output_dir, module,
        )


async def patch_movie(
    movie_id: int,
    patch_type: PatchType = PatchType.SMART,
) -> PatchResult:
    """补刮单个电影的便捷函数"""
    from app.patcher.detector import MissingDetector
    
    detector = MissingDetector()
    missing_info = await detector.detect_movie(movie_id)
    
    if not missing_info:
        return PatchResult(
            movie_id=movie_id,
            movie_code="",
            patch_type=patch_type,
            status=PatchStatus.FAILED,
            error_message="Movie not found",
        )
    
    engine = PatchEngine()
    return await engine.patch(missing_info, patch_type)
