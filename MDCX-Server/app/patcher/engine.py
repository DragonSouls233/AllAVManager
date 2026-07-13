"""
补刮引擎主入口

整合缺失检测、智能跳过、补刮策略、报告生成
提供完整的补刮工作流
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import text as sa_text

from app.db.database import get_db
from app.patcher.detector import MissingDetector, MissingInfo
from app.patcher.skipper import Skipper, SkipResult
from app.patcher.strategy import PatchEngine, PatchResult, PatchType, PatchStatus
from app.patcher.reporter import PatchReporter, PatchReport

logger = logging.getLogger(__name__)


class PatchMode(str, Enum):
    """补刮模式"""
    ALL = "all"               # 全库补刮
    DIRECTORY = "directory"   # 目录级补刮
    SELECTED = "selected"     # 选定电影补刮
    SCHEDULED = "scheduled"   # 定时补刮


@dataclass
class PatchOptions:
    """补刮选项"""
    mode: PatchMode = PatchMode.ALL
    
    # 补刮类型
    patch_type: PatchType = PatchType.SMART
    
    # 目录级补刮的目录列表
    directories: list[str] = field(default_factory=list)
    
    # 选定补刮的电影 ID 或番号列表
    movie_ids: list[int] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)

    # 刮削来源站点（如 ['javbus','javdb']）；None 表示自动选择
    sources: Optional[list[str]] = None

    # 跳过选项
    skip_recent_days: int = 7
    skip_verified: bool = True
    skip_complete: bool = True
    
    # 并发控制
    concurrency: int = 6
    
    # 报告选项
    generate_report: bool = True
    report_format: str = "json"  # json/markdown/both
    report_output_dir: str = "/data/logs/patch"


@dataclass
class PatchJobResult:
    """补刮任务结果"""
    job_id: str
    mode: PatchMode
    started_at: datetime
    finished_at: Optional[datetime] = None

    # 每个电影的补刮明细结果（供 _save_patch_records 落库）
    results: list[PatchResult] = field(default_factory=list)
    
    # 检测结果
    total_detected: int = 0
    total_skipped: int = 0
    total_to_patch: int = 0
    
    # 补刮结果
    total_patched: int = 0
    total_success: int = 0
    total_partial: int = 0
    total_failed: int = 0
    
    # 报告
    report: Optional[PatchReport] = None
    
    # 错误信息
    error_message: Optional[str] = None
    
    def duration_seconds(self) -> float:
        """耗时（秒）"""
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
    
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "mode": self.mode.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds(),
            "total_detected": self.total_detected,
            "total_skipped": self.total_skipped,
            "total_to_patch": self.total_to_patch,
            "total_patched": self.total_patched,
            "total_success": self.total_success,
            "total_partial": self.total_partial,
            "total_failed": self.total_failed,
            "error_message": self.error_message,
        }


class PatchWorkflow:
    """
    补刮工作流
    
    完整的补刮流程：
    1. 检测缺失
    2. 智能跳过
    3. 执行补刮
    4. 生成报告
    """
    
    def __init__(
        self,
        detector: Optional[MissingDetector] = None,
        skipper: Optional[Skipper] = None,
        engine: Optional[PatchEngine] = None,
    ):
        """
        初始化
        
        Args:
            detector: 缺失检测器
            skipper: 智能跳过器
            engine: 补刮引擎
        """
        self.detector = detector or MissingDetector()
        self.skipper = skipper or Skipper()
        self.engine = engine or PatchEngine()
    
    async def run(
        self,
        options: PatchOptions,
        progress_callback=None,
    ) -> PatchJobResult:
        """
        执行补刮任务

        Args:
            options: 补刮选项
            progress_callback: 可选的进度回调函数，签名 (status_dict) -> None

        Returns:
            PatchJobResult 任务结果
        """
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        result = PatchJobResult(
            job_id=job_id,
            mode=options.mode,
            started_at=datetime.now(),
        )

        def _emit():
            if progress_callback:
                progress_callback({
                    "status": "running",
                    "total_detected": result.total_detected,
                    "total_skipped": result.total_skipped,
                    "total_to_patch": result.total_to_patch,
                    "total_patched": result.total_patched,
                    "total_success": result.total_success,
                    "total_partial": result.total_partial,
                    "total_failed": result.total_failed,
                    "current_code": getattr(result, "_current_code", None),
                })

        try:
            # 1. 检测缺失
            logger.info(f"开始补刮任务 {job_id}, mode={options.mode.value}")

            missing_infos = await self._detect_missing(options)
            result.total_detected = len(missing_infos)
            _emit()

            logger.info(f"检测到 {result.total_detected} 部影片数据缺失")

            # 2. 智能跳过
            to_patch, skipped = await self._filter_skipped(
                missing_infos, options, result
            )
            result.total_skipped = len(skipped)
            result.total_to_patch = len(to_patch)
            _emit()

            # 统计跳过原因
            skip_reasons = {}
            for _, skip_result in skipped:
                reason = skip_result.reason.value if skip_result.reason else "unknown"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

            logger.info(
                f"筛选完成: {result.total_to_patch} 待补刮, "
                f"{result.total_skipped} 已跳过"
            )
            if skip_reasons:
                reason_str = ", ".join(f"{k}={v}" for k, v in skip_reasons.items())
                logger.info(f"跳过原因: {reason_str}")

            if result.total_to_patch == 0:
                logger.info("没有需要补刮的影片，任务结束")
            else:
                logger.info(
                    f"开始补刮 {result.total_to_patch} 部影片 "
                    f"(并发={options.concurrency})"
                )

            # 3. 执行补刮
            patch_results = await self._execute_patch(
                to_patch, options, result, progress_callback
            )

            result.results = patch_results
            result.total_patched = len(patch_results)

            # 统计结果
            for pr in patch_results:
                if pr.status.value == "success":
                    result.total_success += 1
                elif pr.status.value == "partial":
                    result.total_partial += 1
                else:
                    result.total_failed += 1
            _emit()
            
            # 4. 生成报告
            if options.generate_report:
                reporter = PatchReporter(report_id=job_id)
                
                for info in missing_infos:
                    reporter.add_missing_info(info)
                
                for pr in patch_results:
                    reporter.add_result(pr)
                
                for info, skip_result in skipped:
                    reporter.add_skipped(
                        info.movie_code,
                        skip_result.reason.value if skip_result.reason else "",
                        skip_result.message,
                    )
                
                result.report = reporter.finalize()
                
                # 保存报告
                reporter.save_report(
                    options.report_output_dir,
                    options.report_format,
                )
            
            logger.info(
                f"补刮任务完成 {job_id}: "
                f"{result.total_success} 成功, "
                f"{result.total_partial} 部分, "
                f"{result.total_failed} 失败"
            )
        
        except Exception as e:
            logger.error(f"补刮任务失败 {job_id}: {e}")
            result.error_message = str(e)
        
        finally:
            result.finished_at = datetime.now()
        
        return result
    
    async def _detect_missing(
        self,
        options: PatchOptions,
    ) -> list[MissingInfo]:
        """检测缺失"""
        if options.mode == PatchMode.ALL:
            return await self.detector.detect_all()
        
        elif options.mode == PatchMode.SELECTED:
            if options.movie_ids:
                return await self.detector.detect_batch(movie_ids=options.movie_ids)
            elif options.codes:
                return await self.detector.detect_batch(codes=options.codes)
            else:
                return []
        
        elif options.mode == PatchMode.DIRECTORY:
            # 查找目录对应的数据库记录
            movie_ids = await self._find_movies_in_directories(options.directories)
            return await self.detector.detect_batch(movie_ids=movie_ids)
        
        else:
            return []
    
    async def _find_movies_in_directories(
        self,
        directories: list[str],
    ) -> list[int]:
        """查找目录中的电影 ID"""
        movie_ids = []
        db = get_db()
        
        async with db.session() as session:
            for directory in directories:
                result = await session.execute(
                    sa_text("SELECT id FROM movies WHERE output_dir LIKE :dir OR file_path LIKE :dir"),
                    {"dir": f"%{directory}%"},
                )
                rows = result.fetchall()
                movie_ids.extend([row[0] for row in rows])
        
        return list(set(movie_ids))
    
    async def _filter_skipped(
        self,
        missing_infos: list[MissingInfo],
        options: PatchOptions,
        result: PatchJobResult,
    ) -> tuple[list[MissingInfo], list[tuple[MissingInfo, SkipResult]]]:
        """过滤跳过的记录"""
        # 更新 skipper 配置
        self.skipper.skip_recent_days = options.skip_recent_days
        self.skipper.skip_verified = options.skip_verified
        self.skipper.skip_complete = options.skip_complete

        logger.info(
            f"跳过条件: skip_recent_days={options.skip_recent_days}, "
            f"skip_verified={options.skip_verified}, "
            f"skip_complete={options.skip_complete}"
        )
        
        # 从数据库获取 scraped_at 和 verified 状态
        scraped_times = {}
        verified_ids = set()
        try:
            from app.db.database import get_db
            from app.db.models import Movie
            from sqlalchemy import select

            db = get_db()
            async with db.session() as session:
                for info in missing_infos:
                    if info.movie_id:
                        movie = await session.get(Movie, info.movie_id)
                        if movie:
                            if movie.scraped_at:
                                scraped_times[info.movie_id] = movie.scraped_at
                            if movie.status == "verified":
                                verified_ids.add(info.movie_id)
        except Exception as e:
            logger.warning(f"获取数据库状态失败: {e}")

        return self.skipper.batch_filter(
            missing_infos,
            scraped_times,
            verified_ids,
        )
    
    async def _execute_patch(
        self,
        to_patch: list[MissingInfo],
        options: PatchOptions,
        result: PatchJobResult,
        progress_callback=None,
    ) -> list[PatchResult]:
        """执行补刮（带并发控制 + 单片超时 + 详细日志）"""
        import asyncio

        semaphore = asyncio.Semaphore(options.concurrency)
        patch_results = []
        completed = 0
        total = len(to_patch)

        def _emit_progress():
            nonlocal completed
            if progress_callback:
                pct = round(completed / total * 100, 1) if total > 0 else 0
                progress_callback({
                    "status": "running",
                    "total_detected": result.total_detected,
                    "total_skipped": result.total_skipped,
                    "total_to_patch": result.total_to_patch,
                    "total_patched": completed,
                    "total_success": result.total_success,
                    "total_partial": result.total_partial,
                    "total_failed": result.total_failed,
                    "progress": pct,
                    "current_code": getattr(result, "_current_code", None),
                })

        async def _patch_one(info: MissingInfo) -> PatchResult:
            nonlocal completed
            async with semaphore:
                setattr(result, "_current_code", info.movie_code)
                idx = completed + 1
                logger.info(f"补刮进度 {idx}/{total}: 开始补刮 {info.movie_code}")
                t0 = __import__("time").time()
                try:
                    # 单片超时：最多 120 秒，防止某个源挂起导致整个任务卡死
                    pr = await asyncio.wait_for(
                        self.engine.patch(
                            info, options.patch_type, sources=options.sources
                        ),
                        timeout=120,
                    )
                    elapsed = __import__("time").time() - t0
                    logger.info(
                        f"补刮进度 {idx}/{total}: {info.movie_code} 完成 "
                        f"({pr.status.value}, {elapsed:.1f}s)"
                    )
                    return pr
                except asyncio.TimeoutError:
                    elapsed = __import__("time").time() - t0
                    logger.error(
                        f"补刮进度 {idx}/{total}: {info.movie_code} 超时 "
                        f"({elapsed:.1f}s)，跳过"
                    )
                    return PatchResult(
                        movie_id=info.movie_id,
                        movie_code=info.movie_code,
                        patch_type=options.patch_type,
                        status=PatchStatus.FAILED,
                        error_message=f"补刮超时 ({elapsed:.1f}s)",
                    )
                except Exception as e:
                    elapsed = __import__("time").time() - t0
                    logger.error(
                        f"补刮进度 {idx}/{total}: {info.movie_code} 失败 "
                        f"({elapsed:.1f}s): {e}"
                    )
                    return PatchResult(
                        movie_id=info.movie_id,
                        movie_code=info.movie_code,
                        patch_type=options.patch_type,
                        status=PatchStatus.FAILED,
                        error_message=str(e),
                    )
                finally:
                    completed += 1
                    _emit_progress()

        tasks = [_patch_one(info) for info in to_patch]
        results = await asyncio.gather(*tasks)
        patch_results.extend(results)

        return patch_results


async def run_patch_job(
    mode: PatchMode = PatchMode.ALL,
    patch_type: PatchType = PatchType.SMART,
    movie_ids: Optional[list[int]] = None,
    codes: Optional[list[str]] = None,
    directories: Optional[list[str]] = None,
    skip_recent_days: int = 7,
    concurrency: int = 3,
) -> PatchJobResult:
    """
    执行补刮任务的便捷函数
    
    Args:
        mode: 补刮模式
        patch_type: 补刮类型
        movie_ids: 电影 ID 列表
        codes: 番号列表
        directories: 目录列表
        skip_recent_days: 跳过最近 N 天
        concurrency: 并发数
        
    Returns:
        PatchJobResult 任务结果
    """
    options = PatchOptions(
        mode=mode,
        patch_type=patch_type,
        movie_ids=movie_ids or [],
        codes=codes or [],
        directories=directories or [],
        skip_recent_days=skip_recent_days,
        concurrency=concurrency,
    )
    
    workflow = PatchWorkflow()
    return await workflow.run(options)
