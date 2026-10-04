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
from app.scraper.number import extract_number, infer_module

# 模块名 → (models 模块路径, Movie 类名, Actor 类名, Base 类名)
# 全仓唯一映射：`_get_module_models` 与 `_module_base_class` 共用，避免两处漂移。
_MODULE_MODEL_MAP: dict[str, tuple[str, str, str, str]] = {
    "jav":        ("app.db.jav_models",        "JavMovie",       "JavActor",       "JAV_BASE"),
    "chinese":    ("app.db.chinese_models",    "ChineseMovie",   "ChineseActor",   "CHINESE_BASE"),
    "uncensored": ("app.db.uncensored_models", "UncensoredMovie", "UncensoredActor", "UNCENSORED_BASE"),
    "fc2":        ("app.db.fc2_models",        "Fc2Movie",       "Fc2Actor",       "FC2_BASE"),
    "pornhub":    ("app.db.pornhub_models",    "PornhubMovie",   "PornhubActor",   "PORNHUB_BASE"),
    "western":    ("app.db.western_models",    "WesternMovie",   "WesternActor",   "WESTERN_BASE"),
    # 🔴 2026-10-04 补：里番 = anime 模块，但本表从来没有 anime 键
    # ⇒ `_get_module_models("anime")` 恒返回 None ⇒ 走本路径的里番落盘
    #    静默失效（无异常、无日志）。anime_models.py 确实存在。
    "anime":      ("app.db.anime_models",      "AnimeMovie",     "AnimeActor",     "ANIME_BASE"),
}


def _module_base_class(module: str):
    """取某模块模型的 Declarative Base 类（供 ModuleDatabase.get_instance 首调注册用）。

    🔴 `ModuleDatabase.get_instance()` 首调不传 base_class 会抛 ValueError，
    而 base_class 只在 `ModuleDatabase.init_all()` 里注册、且 `init_all()` 仅由
    `main.py` 启动流程调用 ⇒ 独立脚本/一次性任务/测试走 workflow 落盘必炸。
    这里按模型模块里的 `<MODULE>_BASE` 补齐，做到「谁需要谁自举」。
    """
    import importlib

    entry = _MODULE_MODEL_MAP.get(module)
    if not entry:
        return None
    mod_path, _movie, _actor, base_name = entry
    return getattr(importlib.import_module(mod_path), base_name)

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
    async def _get_module_models(module: str):
        """根据模块名动态加载对应的模块模型类

        返回 (MovieModel, ActorModel, ModuleDatabase) 三元组。
        如果模块名无效或未注册，返回 None。
        """
        entry = _MODULE_MODEL_MAP.get(module)
        if not entry:
            return None
        mod_path, movie_name, actor_name, _base_name = entry
        import importlib
        mod = importlib.import_module(mod_path)
        MovieCls = getattr(mod, movie_name)
        ActorCls = getattr(mod, actor_name)
        # 🔴 `ModuleDatabase.get_instance()` 首调**必须**传 base_class，否则抛
        #   ValueError。而 base_class 只在 `init_all()` 里被注册，且 `init_all()`
        #   仅由 `main.py` 启动流程调用 ⇒ 任何非服务器进程（独立脚本 /
        #   一次性任务 / 测试）走 workflow 落盘必然抛异常：
        #   「模块 'fc2' 首次初始化必须提供 base_class」。
        #   这里自举：按模型模块里的 *_BASE 补注册。
        db = ModuleDatabase.get_instance(module, base_class=_module_base_class(module))
        # 🔴 `get_instance()` 只做**注册**，不建表也不建库文件。建表是 `init()` 的活，
        #   而 `init()` 只在 `ModuleDatabase.init_all()`（main.py 启动）里被调
        #   ⇒ 独立进程里 `session_factory()` 会在**不存在的库文件**上建 engine，
        #   首次查询即 OperationalError（no such table），或静默 0 行。
        if not getattr(db, "_workflow_self_inited", False):
            await db.init()
            db._workflow_self_inited = True
        return MovieCls, ActorCls, db
    
    async def process_file(
        self,
        file_path: str,
        sources: Optional[list[str]] = None,
        module: Optional[str] = None,
    ) -> Optional[ScrapeResult]:
        """
        处理单个文件

        Args:
            file_path: 文件路径
            sources: 指定站点列表
            module: 显式指定归属模块。**强烈建议传入**（扫描器/批处理都已知自己在
                扫哪个模块）；不给时按 infer_module() 推断。

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

        # 1.5 归属模块 —— 必须在刮削**之前**确定：
        # ① 决定用哪些爬虫（否则 FC2 番号会走 get_crawlers_for_number 选到 JAV 爬虫）
        # ② 决定写哪个模块库
        module_name = module or infer_module(file_path, number_result=number_result)
        logger.info(f"归属模块: {module_name}")

        # 2. 多站点刮削
        result = await self.engine.scrape_number(number, sources, module=module_name)

        if not result:
            logger.warning(f"刮削失败: {number}")
            return None

        # 🔴 2026-10-04：`if not result` 只挡 None，**挡不住「有对象但无实质内容」**。
        # 实测里番 DV-109：源返回 title="猜你喜欢"（推荐区块文案）+ duration=67
        # （页面里**别的条目**的时长），对象非 None ⇒ 直接落库 ⇒
        # 库里写入标题「猜你喜欢」的垃圾记录，且该源被记为健康、永不熔断。
        # `has_content()` 就是为此存在（与 patcher/strategy 同一口径），
        # 这里必须补上，否则该防护只在一半链路上生效。
        if not result.has_content():
            logger.warning(
                f"刮削结果无实质内容，放弃落盘: {number} "
                f"(source={result.source}, title={result.title!r})"
            )
            return None

        logger.info(f"刮削来源: {result.source}")

        # 3~6. 建目录 → 下载图片 → 生成 NFO → 写库（统一走 persist）
        # 🔴 不能用 _source_to_module(result.source) 决定落盘模块：
        #    主源 javdb/javbus 是**跨模块共用源**，FC2 番号由 javdb 命中时会被
        #    映射成 "jav" ⇒ FC2 影片写进 JAV 库（跨模块污染）。
        #    落盘模块必须以「这条影片属于哪个模块」为准，即上面推断出的 module_name。
        await self.persist(result, file_path=file_path, module=module_name, number=number)

        logger.info(f"处理完成: {number}")

        return result
    
    async def process_batch(
        self,
        file_paths: list[str],
        sources: Optional[list[str]] = None,
        module: Optional[str] = None,
    ) -> dict[str, Optional[ScrapeResult]]:
        """
        批量处理文件

        Args:
            file_paths: 文件路径列表
            sources: 指定站点列表
            module: 归属模块（透传给 process_file；不给则每个文件各自推断）

        Returns:
            文件路径 -> 结果 的映射
        """
        results = {}

        for file_path in file_paths:
            result = await self.process_file(file_path, sources, module=module)
            results[file_path] = result

        return results
    
    async def persist(
        self,
        result: ScrapeResult,
        file_path: Optional[str] = None,
        module: Optional[str] = None,
        number: Optional[str] = None,
    ) -> str:
        """落盘完整流程：建目录 → 下载图片 → 生成 NFO → 写库

        供「已持有 ScrapeResult、无需重复刮削」的调用方复用（如后台批量补刮），
        避免只写元数据却不落封面/NFO 的半截流程。

        Returns:
            movie_dir: 影片输出目录
        """
        number = number or result.code
        module_name = module or self._source_to_module(result.source or "")

        # 1. 按模块分目录创建输出目录（data/movies/{模块}/{番号}/）
        movie_dir = self.output_dir / module_name / number
        movie_dir.mkdir(parents=True, exist_ok=True)

        # 2. 下载图片
        if self.download_images and result.cover_url:
            logger.info("正在下载图片")

            _referer = getattr(result, "source_url", None)
            if not _referer:
                _origin_map = {
                    "fc2": "https://adult.contents.fc2.com",
                    "javdb": "https://javdb.com",
                    "javbus": "https://www.javbus.com",
                    "avsox": "https://avsox.click",
                    # 2026-10-04 实测：pix-cdn*.phncdn.com 无 Referer 直接 403，
                    # 带主站 Referer 才返回完整 image/jpeg（无 Referer 只给 avif 缩略）。
                    "pornhub": "https://www.pornhub.com",
                    "pornhub_api": "https://www.pornhub.com",
                    "javmenu": "https://javmenu.com",
                }
                _referer = _origin_map.get(result.source)

            async with ImageProcessor(str(movie_dir)) as processor:
                poster_path = await processor.download_cover(
                    result.cover_url,
                    str(movie_dir),
                    referer=_referer,
                )
                if poster_path:
                    logger.info(f"海报已保存: {poster_path}")

                fanart_path = await processor.download_fanart(
                    result.cover_url,
                    str(movie_dir),
                    referer=_referer,
                )

                # thumb.jpg（列表页缩略图）。2026-09-29 补：此前从未下载，
                # 约 989 部 JAV 缺 thumb.jpg。优先用爬虫给的 thumb_url，没有则回退封面。
                _thumb_url = getattr(result, "thumb_url", None) or result.cover_url
                if _thumb_url:
                    await processor.download_thumb(
                        _thumb_url,
                        str(movie_dir),
                        referer=_referer,
                    )

                if result.sample_images:
                    sample_paths = await processor.download_samples(
                        result.sample_images,
                        str(movie_dir),
                        referer=_referer,
                    )
                    logger.info(f"已下载 {len(sample_paths)} 张预览图")

        # 3. 生成 NFO
        if self.generate_nfo:
            logger.info("正在生成NFO")
            nfo_path = generate_nfo(result, str(movie_dir))
            if nfo_path:
                logger.info(f"NFO已保存: {nfo_path}")

        # 4. 保存到模块数据库
        if self.save_to_db:
            logger.info("正在保存到数据库")
            await self._save_to_db(result, str(movie_dir), file_path, module=module_name)

        return str(movie_dir)

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
            # 🔴 2026-10-05：只看 poster.jpg 会漏。实测 ph6a38b964c4bb0
            #    PH CDN 偶发返回 MP4（`head=b'\x00\x00\x00\x1cftyp'`，不是图）
            #    ⇒ download_cover 判无效跳过，但同目录 **fanart.jpg 下载成功了**
            #    ⇒ cover_url 退化成远程 URL、poster_url 变 NULL，前端封面靠网络。
            #    按「海报 → 背景图 → 缩略图 → 剧照首张」兜底取真实存在的那张。
            for _name in ("poster.jpg", "fanart.jpg", "thumb.jpg", "cover.jpg"):
                _p = _movie_dir_path / _name
                if _p.exists() and _p.stat().st_size > 0:
                    _local_cover = str(_p)
                    break
            if _local_cover is None:
                _first = _movie_dir_path / "extrafanart" / "01.jpg"
                if _first.exists() and _first.stat().st_size > 0:
                    _local_cover = str(_first)
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
        # 🔴 2026-10-04 修复：原先**只**读 raw_data["director"]/["directors"]，
        # 而 merge() 产出的 raw_data 只有 covers/field_sources/merged_from，
        # 导演只挂在 `result.directors` 上 ⇒ **多源合并路径下导演 100% 丢失**
        # （单源路径正常 ⇒ 只在启用多源时复现，极隐蔽）。
        # 改成「结构化字段优先，raw_data 兜底」。
        director = None
        directors = getattr(result, "directors", None) or raw.get("director") or raw.get("directors")
        if isinstance(directors, (list, tuple, set)):
            director = ",".join(str(d).strip() for d in directors if str(d).strip()) or None
        elif directors:
            director = str(directors).strip() or None
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
        models = await self._get_module_models(module)
        if models is None:
            logger.warning(f"未知模块 [{module}]，默认回退到 jav")
            models = await self._get_module_models("jav")
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
                # 🔴 2026-10-05：多数源（含 pornhub_api）只给 cover_url 不给
                # poster_url ⇒ 这一列**恒为 NULL**（实测 ph6a38b964c4bb0）。
                # thumb_url 早就写了 `or result.cover_url` 兜底，poster_url 漏了。
                poster_url=_local_cover or result.poster_url or result.cover_url,
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
                output_dir=str(movie_dir) if movie_dir else None,
                director=director,
                trailer_url=getattr(result, "trailer_url", None) or raw.get("trailer"),
                status="scraped",
                scraped_at=datetime.now(),
            )

            # 模块特有字段
            # 大部分模块的 Movie 类有 actor 字段（逗号分隔名称）
            # 只保留女演员：源站标记男演员 + 已知男演员名单双重剔除
            female_names: list[str] = []
            if result.actors:
                all_names = [a.name for a in result.actors if getattr(a, "name", None)]
                try:
                    from app.utils.actor_gender import filter_female_only

                    female_names = filter_female_only(
                        all_names, getattr(result, "male_actors", None)
                    )
                except Exception:
                    female_names = all_names
                if female_names:
                    common_fields["actor"] = ",".join(female_names)
                elif all_names:
                    # 全部被判为男演员时才回退，避免整片演员被清空
                    common_fields["actor"] = ",".join(all_names)
            # studio 字段（不是外键，是普通字符串）
            if hasattr(MovieCls, "studio") and result.studio:
                common_fields["studio"] = result.studio
            if hasattr(MovieCls, "series") and result.series:
                common_fields["series"] = result.series
            # 🔴 2026-10-04 修复：这两个**三值布尔**字段原先是无条件写入。
            # 它们的合法值包含 None（= 源站没说），而下面更新分支是
            # `for key, value in common_fields.items(): setattr(movie, key, value)`
            # —— 无条件覆盖 ⇒ **任何一次没判出无码的补刮，都会把库里已经是
            # True 的 is_uncensored/is_mosaic 清成 NULL**。这是"静默产出错误数据"
            # 的典型：库里已有的正确判定被无声抹掉，用户只在筛选"仅无码"时才发现少了片。
            # 与 studio/series 一致地只写**有值的**（None 表示未知，不该覆盖已知）。
            if hasattr(MovieCls, "is_uncensored") and result.is_uncensored is not None:
                common_fields["is_uncensored"] = result.is_uncensored
            if hasattr(MovieCls, "is_mosaic") and result.is_mosaic is not None:
                common_fields["is_mosaic"] = result.is_mosaic
            # 🟢 模块级语义兜底：uncensored 模块里的影片**按定义就是无码**。
            # 源站（尤其 javdb）对素人番号普遍不给无码标记 ⇒ 落库为 NULL
            # ⇒ 前端 `MovieCard.vue` 的「无码」徽章（`v-if="movie.is_uncensored"`）
            #    不显示 ⇒ 整个无码库在界面上看起来「不是无码」。
            # 实测生产 uncensored.db：15 条里 13 条 NULL、2 条竟是有码(0)。
            # 兜底规则：
            #   ① 源站给了值（哪怕 False）→ 以源站为准，不兜底
            #   ② 源站没说（None）→ 按模块语义填 True
            # 副作用（已知且可接受）：本模块里源站明确判「有码」的记录，
            # 后续任何一次源站没判定的补刮都会把它翻成 True。这符合
            # 「进了 uncensored 模块就是无码」的分类约定；若将来需要
            # 保留「源站判有码」这种例外，应在扫描侧拒绝入库而不是靠此字段区分。
            elif module == "uncensored" and hasattr(MovieCls, "is_uncensored"):
                common_fields["is_uncensored"] = True

            # 🔴 2026-10-05 修复：模块专属列（pornhub 的 source_id /
            # source_views / source_score / uploader / categories）此前**只有补刮
            # 路径（patcher/strategy.py）会写**，主流水线（扫库批刮 / 单曲刮削）
            # 从不写 ⇒ 生产 pornhub.db 6 条里 5 条这 5 列全 NULL（不是没数据，
            # 是链路断了）。提取逻辑收口在 app/db/module_columns.py，
            # 不要在这里再手写一份。
            # ⚠️ 必须按 MovieCls 过滤：这些列只有 pornhub 表有，别的模块盲写
            # 会在 flush 时抛 "no such column" 并回滚整条事务。
            _module_cols: dict = {}
            try:
                from app.db.module_columns import collect_module_columns

                _module_cols = {
                    k: v for k, v in collect_module_columns(result, module).items()
                    if hasattr(MovieCls, k)
                }
            except Exception as _mc_err:
                logger.debug(f"提取模块专属列失败 [{module}] {result.code}: {_mc_err}")

            if movie:
                # 更新现有记录
                for key, value in common_fields.items():
                    setattr(movie, key, value)
                # 模块专属列：只有非 None 才写（None = 源站没说，不该清掉旧值）
                for key, value in _module_cols.items():
                    setattr(movie, key, value)
                # 额外字段只更新非空值
                if result.maker:
                    movie.studio = result.maker
            else:
                # 创建新记录
                movie = MovieCls(
                    code=result.code,
                    **common_fields,
                    **_module_cols,
                )
                session.add(movie)

            await session.flush()
            _movie_id = movie.id

            # ---- 维护 actors / movie_actors 关联 ----
            # 统一走 app/db/movie_actor_sync.py：补刮路径（patcher/strategy.py）也复用它，
            # 否则只有走本流水线（batch_scrape / jav_routes）的影片才有关联，
            # 扫描器与补刮进来的影片全部缺失 ⇒ actors.movie_count 恒 0。
            try:
                from app.db.movie_actor_sync import sync_movie_actors

                _names = female_names or [
                    a.name for a in (result.actors or []) if getattr(a, "name", None)
                ]
                # ⚠️ 曾试过「源站无演员时用目录名 `[Anna Cherry7]` 兜底」，
                # 已撤回：`extract_actor_from_folder()` 是为 chinese 模块设计的
                # （假设目录名**无**方括号），实测在本场景产出错误演员：
                #   `[Channel] Anna Cherry7` → ['Anna']        （丢了 Cherry7）
                #   `[Rosi Lane]`            → ['Chica','Guapa']（从西语标题切词）
                # 写入错误演员比不写更糟（会污染演员表并影响按演员筛选）。
                # pornhub 演员为空的根因是**站点改版后演员只在登录后可见**，
                # 需登录态才能补齐，不该靠猜。
                await sync_movie_actors(session, module, _movie_id, _names)
            except Exception as e:
                logger.debug(f"写入演员关联失败 [{module}] {result.code}: {e}")

            # 🔴 2026-10-04 修复（实测：写完后用新 session 查，行数 = 0）：
            # 上游只有 `await session.flush()`，**从不 commit**。
            # 而本函数用的是 `async with mod_db.session_factory() as session:`
            # —— SQLAlchemy 的 AsyncSession 上下文管理器退出时只做 close()，
            # 对未提交事务执行 **ROLLBACK**（它不是 session_scope()，那个也不提交，
            # 只是异常时额外 rollback）。⇒ 整段落盘**全部被回滚**，
            # 表现为「日志打印『已保存到模块数据库』但库里查不到任何行」——
            # 静默失败，比抛异常更难发现。
            # 必须显式 commit；放在演员关联之后，保证 movie + movie_actors 同一事务。
            await session.commit()

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
