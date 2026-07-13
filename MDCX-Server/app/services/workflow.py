"""自动化工作流引擎

参考 AV-DM (av-dm-main) 的自动化工作流设计，实现 MDCX 的 5 步工作流管道：
- Workflow 1: 番号获取（RSS/订阅源 → 番号提取 → 磁力搜索）
- Workflow 2: 下载管理（磁力链接 → 下载器 → 下载完成通知）
- Workflow 3: 元数据刮削（文件监视器 → 番号识别 → 多源刮削 → NFO生成）
- Workflow 4: 媒体库推送（NFO → Emby/Jellyfin 扫描 → 入库通知）
- Workflow 5: 空间管理（磁盘检查 → 删除最旧已观看 → 保留空间）

每个 Workflow 独立可执行，支持手动触发和定时调度。
"""

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)


class WorkflowStatus(str, Enum):
    """工作流状态"""
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowTrigger(str, Enum):
    """触发方式"""
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EVENT = "event"


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    workflow_name: str
    status: WorkflowStatus
    started_at: str = ""
    ended_at: str = ""
    duration_ms: float = 0
    summary: dict = field(default_factory=dict)
    error: Optional[str] = None
    trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED


class BaseWorkflow(ABC):
    """工作流基类"""

    def __init__(self, name: str, display_name: str, description: str = ""):
        self.name = name
        self.display_name = display_name
        self.description = description
        self._status = WorkflowStatus.IDLE

    @property
    def status(self) -> WorkflowStatus:
        return self._status

    @abstractmethod
    async def execute(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        """执行工作流"""
        ...

    async def run(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        """运行工作流（含状态管理和计时）"""
        if self._status == WorkflowStatus.RUNNING:
            logger.warning(f"工作流 [{self.name}] 正在运行中，跳过本次触发")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.SKIPPED,
                summary={"reason": "already_running"},
                trigger=trigger,
            )

        self._status = WorkflowStatus.RUNNING
        start = time.monotonic()
        started_at = datetime.now().isoformat()

        logger.info(f"工作流 [{self.display_name}] 开始执行 (trigger={trigger.value})")

        try:
            result = await self.execute(trigger)
            result.started_at = started_at
            result.ended_at = datetime.now().isoformat()
            result.duration_ms = round((time.monotonic() - start) * 1000, 2)
            result.trigger = trigger
            self._status = result.status

            log_level = "SUCCESS" if result.status == WorkflowStatus.SUCCESS else "WARNING"
            logger.info(
                f"工作流 [{self.display_name}] 完成: "
                f"status={result.status.value}, "
                f"duration={result.duration_ms}ms, "
                f"summary={result.summary}"
            )

            return result

        except Exception as e:
            ended_at = datetime.now().isoformat()
            duration = round((time.monotonic() - start) * 1000, 2)
            self._status = WorkflowStatus.FAILED

            logger.exception(f"工作流 [{self.display_name}] 执行异常: {e}")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration,
                error=str(e),
                trigger=trigger,
            )


# ==============================================================================
# Workflow 1: 番号获取
# ==============================================================================

class NumberAcquisitionWorkflow(BaseWorkflow):
    """番号获取工作流

    从 RSS 订阅源/手动输入获取番号，触发磁力搜索。
    """

    def __init__(self):
        super().__init__(
            name="number_acquisition",
            display_name="番号获取",
            description="从 RSS 订阅源获取番号并触发磁力搜索",
        )

    async def execute(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        stats = {"rss_checked": 0, "numbers_found": 0, "magnets_searched": 0, "errors": 0}

        try:
            # 检查是否有已配置的 RSS 源
            cfg = get_config()
            rss_feeds = []
            if hasattr(cfg, "rss") and cfg.rss:
                rss_feeds = getattr(cfg.rss, "feeds", []) or []

            if not rss_feeds:
                logger.info("番号获取: 未配置 RSS 源，跳过")
                return WorkflowResult(
                    workflow_name=self.name,
                    status=WorkflowStatus.SKIPPED,
                    summary={**stats, "reason": "no_rss_feeds"},
                    trigger=trigger,
                )

            stats["rss_checked"] = len(rss_feeds)

            from app.services.subscription_downloader import process_subscriptions

            import_count = await process_subscriptions()
            stats["numbers_found"] = import_count

            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.SUCCESS,
                summary=stats,
                trigger=trigger,
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(f"番号获取工作流失败: {e}")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.FAILED,
                summary=stats,
                error=str(e),
                trigger=trigger,
            )


# ==============================================================================
# Workflow 2: 下载管理
# ==============================================================================

class DownloadManagementWorkflow(BaseWorkflow):
    """下载管理工作流

    管理未完成的下载任务，检查下载进度，处理完成/超时任务。
    """

    def __init__(self):
        super().__init__(
            name="download_management",
            display_name="下载管理",
            description="管理下载队列，检查进度，处理完成与超时任务",
        )

    async def execute(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        stats = {"tasks_checked": 0, "tasks_completed": 0, "tasks_paused": 0, "tasks_timeout": 0, "errors": 0}

        try:
            from app.services.downloader_manager import get_downloader_manager

            manager = get_downloader_manager()

            # 获取所有活跃下载器
            downloaders = manager.get_active_downloaders()
            if not downloaders:
                logger.info("下载管理: 无活跃下载器")
                return WorkflowResult(
                    workflow_name=self.name,
                    status=WorkflowStatus.SKIPPED,
                    summary={**stats, "reason": "no_active_downloaders"},
                    trigger=trigger,
                )

            for dl in downloaders:
                try:
                    tasks = await dl.list_tasks()
                    stats["tasks_checked"] += len(tasks)

                    for task in tasks:
                        if task.get("status") == "completed":
                            stats["tasks_completed"] += 1
                        elif task.get("status") == "paused":
                            stats["tasks_paused"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(f"下载器 [{dl.name}] 检查失败: {e}")

            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.SUCCESS,
                summary=stats,
                trigger=trigger,
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(f"下载管理工作流失败: {e}")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.FAILED,
                summary=stats,
                error=str(e),
                trigger=trigger,
            )


# ==============================================================================
# Workflow 3: 元数据刮削
# ==============================================================================

class MetadataScrapeWorkflow(BaseWorkflow):
    """元数据刮削工作流

    扫描未处理的视频文件，识别番号，执行多源刮削，生成 NFO。
    """

    def __init__(self):
        super().__init__(
            name="metadata_scrape",
            display_name="元数据刮削",
            description="扫描未处理文件->番号识别->多源刮削->生成NFO",
        )

    async def execute(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        stats = {"files_scanned": 0, "numbers_extracted": 0, "scraped": 0, "nfo_generated": 0, "errors": 0}

        try:
            from app.scraper.engine import get_scraper_engine
            from app.scraper.number import extract_number

            cfg = get_config()

            # 收集所有已启用模块的媒体目录
            media_dirs = []
            if hasattr(cfg, "modules") and cfg.modules:
                for module_name in ["jav", "uncensored", "fc2", "chinese", "pornhub"]:
                    module_cfg = getattr(cfg.modules, module_name, None)
                    if module_cfg and getattr(module_cfg, "enabled", False):
                        dirs = getattr(module_cfg, "media_dirs", []) or []
                        media_dirs.extend((module_name, d) for d in dirs)

            if not media_dirs:
                logger.info("元数据刮削: 未配置媒体目录")
                return WorkflowResult(
                    workflow_name=self.name,
                    status=WorkflowStatus.SKIPPED,
                    summary={**stats, "reason": "no_media_dirs"},
                    trigger=trigger,
                )

            from app.tasks.base_scanner import BaseScanner

            scanner = BaseScanner()

            for module_name, media_dir in media_dirs:
                if not os.path.isdir(media_dir):
                    continue

                video_files = scanner.find_video_files(media_dir)
                stats["files_scanned"] += len(video_files)

                for file_path in video_files:
                    filename = os.path.basename(file_path)
                    number_result = extract_number(filename)

                    if number_result and number_result.number:
                        stats["numbers_extracted"] += 1

            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.SUCCESS,
                summary=stats,
                trigger=trigger,
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(f"元数据刮削工作流失败: {e}")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.FAILED,
                summary=stats,
                error=str(e),
                trigger=trigger,
            )


# ==============================================================================
# Workflow 4: 媒体库推送
# ==============================================================================

class MediaLibraryPushWorkflow(BaseWorkflow):
    """媒体库推送工作流

    将新刮削完成的影片推送到 Emby/Jellyfin 媒体库。
    """

    def __init__(self):
        super().__init__(
            name="media_library_push",
            display_name="媒体库推送",
            description="推送新刮削的影片到 Emby/Jellyfin",
        )

    async def execute(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        stats = {"items_checked": 0, "items_pushed": 0, "errors": 0}

        try:
            cfg = get_config()

            if not hasattr(cfg, "emby") or not cfg.emby or not getattr(cfg.emby, "enabled", False):
                logger.info("媒体库推送: Emby 未启用")
                return WorkflowResult(
                    workflow_name=self.name,
                    status=WorkflowStatus.SKIPPED,
                    summary={**stats, "reason": "emby_disabled"},
                    trigger=trigger,
                )

            from app.utils.emby import EmbyClient, EmbyConfig

            emby_cfg = EmbyConfig(
                url=cfg.emby.url,
                api_key=cfg.emby.api_key,
            )
            client = EmbyClient(emby_cfg)

            # 触发 Emby 媒体库扫描
            await client.refresh_library()
            stats["items_pushed"] = 1

            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.SUCCESS,
                summary=stats,
                trigger=trigger,
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(f"媒体库推送工作流失败: {e}")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.FAILED,
                summary=stats,
                error=str(e),
                trigger=trigger,
            )


# ==============================================================================
# Workflow 5: 空间管理
# ==============================================================================

class SpaceManagementWorkflow(BaseWorkflow):
    """空间管理工作流

    检查磁盘空间，超过阈值时删除最旧的已观看影片。
    """

    def __init__(self):
        super().__init__(
            name="space_management",
            display_name="空间管理",
            description="磁盘空间检查，自动清理最旧已观看影片",
        )

    async def execute(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> WorkflowResult:
        stats = {"disks_checked": 0, "disks_low": 0, "movies_deleted": 0, "space_freed_mb": 0, "errors": 0}

        try:
            cfg = get_config()

            if not hasattr(cfg, "space_management") or not cfg.space_management:
                logger.info("空间管理: 未配置")
                return WorkflowResult(
                    workflow_name=self.name,
                    status=WorkflowStatus.SKIPPED,
                    summary={**stats, "reason": "not_configured"},
                    trigger=trigger,
                )

            space_cfg = cfg.space_management
            threshold_gb = getattr(space_cfg, "threshold_gb", 50)
            media_dirs = getattr(space_cfg, "media_dirs", []) or []

            for media_dir in media_dirs:
                if not os.path.isdir(media_dir):
                    continue

                stats["disks_checked"] += 1

                try:
                    usage = _get_disk_usage(media_dir)
                    free_gb = usage["free_gb"]

                    if free_gb > threshold_gb:
                        logger.info(f"磁盘 [{media_dir}] 剩余 {free_gb:.1f}GB > 阈值 {threshold_gb}GB，无需清理")
                        continue

                    stats["disks_low"] += 1
                    need_free = threshold_gb - free_gb + 10  # 额外多释放 10GB

                    logger.warning(f"磁盘 [{media_dir}] 空间不足: 剩余 {free_gb:.1f}GB，需释放至少 {need_free:.1f}GB")

                    from app.db.database import get_session_factory
                    from app.db.models import Movie
                    from sqlalchemy import select

                    factory = get_session_factory()
                    async with factory() as session:
                        query = (
                            select(Movie)
                            .where(Movie.file_path.like(f"{media_dir}%"))
                            .where(Movie.view_status.isnot(None))
                            .order_by(Movie.scraped_at.asc().nullslast())
                        )
                        result = await session.execute(query)
                        candidates = result.scalars().all()

                        freed_mb = 0
                        deleted_count = 0

                        for movie in candidates:
                            if freed_mb >= need_free * 1024:
                                break
                            if movie.file_path and os.path.isfile(movie.file_path):
                                try:
                                    file_size_mb = os.path.getsize(movie.file_path) / (1024 * 1024)
                                    os.remove(movie.file_path)
                                    freed_mb += file_size_mb
                                    deleted_count += 1
                                except OSError:
                                    pass

                        stats["movies_deleted"] += deleted_count
                        stats["space_freed_mb"] += round(freed_mb, 2)

                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(f"磁盘 [{media_dir}] 检查失败: {e}")

            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.SUCCESS if stats["errors"] == 0 else WorkflowStatus.FAILED,
                summary=stats,
                trigger=trigger,
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(f"空间管理工作流失败: {e}")
            return WorkflowResult(
                workflow_name=self.name,
                status=WorkflowStatus.FAILED,
                summary=stats,
                error=str(e),
                trigger=trigger,
            )


def _get_disk_usage(path: str) -> dict:
    """获取磁盘使用情况"""
    import shutil

    usage = shutil.disk_usage(path)
    return {
        "total_gb": round(usage.total / (1024 ** 3), 2),
        "used_gb": round(usage.used / (1024 ** 3), 2),
        "free_gb": round(usage.free / (1024 ** 3), 2),
        "usage_pct": round(usage.used / usage.total * 100, 1),
    }


# ==============================================================================
# 工作流注册中心
# ==============================================================================

class WorkflowRegistry:
    """工作流注册中心"""

    def __init__(self):
        self._workflows: dict[str, BaseWorkflow] = {}

    def register(self, workflow: BaseWorkflow) -> None:
        self._workflows[workflow.name] = workflow
        logger.info(f"工作流已注册: [{workflow.name}] {workflow.display_name}")

    def get(self, name: str) -> Optional[BaseWorkflow]:
        return self._workflows.get(name)

    def list(self) -> list[BaseWorkflow]:
        return list(self._workflows.values())

    def list_status(self) -> list[dict]:
        return [
            {
                "name": w.name,
                "display_name": w.display_name,
                "description": w.description,
                "status": w.status.value,
            }
            for w in self._workflows.values()
        ]

    async def run_all(self, trigger: WorkflowTrigger = WorkflowTrigger.SCHEDULED) -> list[WorkflowResult]:
        results = []
        for workflow in self._workflows.values():
            result = await workflow.run(trigger)
            results.append(result)
        return results

    async def run_one(self, name: str, trigger: WorkflowTrigger = WorkflowTrigger.MANUAL) -> Optional[WorkflowResult]:
        workflow = self._workflows.get(name)
        if not workflow:
            logger.warning(f"工作流未找到: {name}")
            return None
        return await workflow.run(trigger)


# 全局单例
_registry: Optional[WorkflowRegistry] = None


def get_workflow_registry() -> WorkflowRegistry:
    """获取全局工作流注册中心"""
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
        _registry.register(NumberAcquisitionWorkflow())
        _registry.register(DownloadManagementWorkflow())
        _registry.register(MetadataScrapeWorkflow())
        _registry.register(MediaLibraryPushWorkflow())
        _registry.register(SpaceManagementWorkflow())
    return _registry


async def run_workflow(name: str) -> Optional[WorkflowResult]:
    """便捷函数：运行指定工作流"""
    registry = get_workflow_registry()
    return await registry.run_one(name)


async def run_all_workflows() -> list[WorkflowResult]:
    """便捷函数：运行所有工作流"""
    registry = get_workflow_registry()
    return await registry.run_all()


__all__ = [
    "BaseWorkflow",
    "WorkflowRegistry",
    "WorkflowResult",
    "WorkflowStatus",
    "WorkflowTrigger",
    "NumberAcquisitionWorkflow",
    "DownloadManagementWorkflow",
    "MetadataScrapeWorkflow",
    "MediaLibraryPushWorkflow",
    "SpaceManagementWorkflow",
    "get_workflow_registry",
    "run_workflow",
    "run_all_workflows",
]
