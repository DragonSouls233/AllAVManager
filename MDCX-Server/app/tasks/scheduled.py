"""
定时任务调度器

基于 APScheduler 实现定时任务
"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.tasks.queue import TaskQueue, TaskType, TaskPriority

logger = logging.getLogger(__name__)


class ScheduledTaskManager:
    """
    定时任务管理器
    
    管理定时刮削、导入、补刮等任务
    """
    
    def __init__(self):
        """初始化"""
        self.scheduler = AsyncIOScheduler()
        self.queue = TaskQueue()
        self._started = False
    
    def start(self) -> None:
        """启动调度器"""
        if not self._started:
            self.scheduler.start()
            self._started = True
            logger.info("Scheduled task manager started")
    
    def stop(self) -> None:
        """停止调度器"""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("Scheduled task manager stopped")
    
    def add_scrape_job(
        self,
        job_id: str,
        directories: list[str],
        output_dir: str,
        cron: Optional[str] = None,
        interval: Optional[int] = None,
    ) -> None:
        """
        添加定时刮削任务
        
        Args:
            job_id: 任务ID
            directories: 扫描目录列表
            output_dir: 输出目录
            cron: Cron 表达式
            interval: 间隔时间（秒）
        """
        trigger = self._create_trigger(cron, interval)
        
        self.scheduler.add_job(
            self._run_scrape_job,
            trigger=trigger,
            id=job_id,
            args=(directories, output_dir),
            replace_existing=True,
        )
        
        logger.info(f"Added scheduled scrape job: {job_id}")
    
    def add_import_job(
        self,
        job_id: str,
        directory: str,
        cron: Optional[str] = None,
        interval: Optional[int] = None,
    ) -> None:
        """
        添加定时导入任务
        
        Args:
            job_id: 任务ID
            directory: 目录路径
            cron: Cron 表达式
            interval: 间隔时间（秒）
        """
        trigger = self._create_trigger(cron, interval)
        
        self.scheduler.add_job(
            self._run_import_job,
            trigger=trigger,
            id=job_id,
            args=(directory,),
            replace_existing=True,
        )
        
        logger.info(f"Added scheduled import job: {job_id}")
    
    def add_patch_job(
        self,
        job_id: str,
        cron: Optional[str] = None,
        interval: Optional[int] = None,
    ) -> None:
        """
        添加定时补刮任务
        
        Args:
            job_id: 任务ID
            cron: Cron 表达式
            interval: 间隔时间（秒）
        """
        trigger = self._create_trigger(cron, interval)
        
        self.scheduler.add_job(
            self._run_patch_job,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
        )
        
        logger.info(f"Added scheduled patch job: {job_id}")
    
    def remove_job(self, job_id: str) -> bool:
        """
        移除定时任务
        
        Args:
            job_id: 任务ID
            
        Returns:
            是否成功移除
        """
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed scheduled job: {job_id}")
            return True
        
        return False
    
    def get_jobs(self) -> list[dict]:
        """
        获取所有定时任务
        
        Returns:
            任务列表
        """
        jobs = []
        
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        
        return jobs
    
    async def _run_scrape_job(
        self,
        directories: list[str],
        output_dir: str,
    ) -> None:
        """执行定时刮削"""
        logger.info(f"Running scheduled scrape job at {datetime.now()}")
        
        from app.tasks.scanner import FileScanner
        
        scanner = FileScanner()
        
        # 扫描所有目录
        all_files = []
        for directory in directories:
            files = scanner.scan_unscraped(directory)
            all_files.extend(files)
        
        if not all_files:
            logger.info("No files to scrape")
            return
        
        # 提交批量刮削任务
        file_paths = [f.path for f in all_files]
        
        await self.queue.add(
            type=TaskType.SCRAPE_BATCH,
            data={
                "file_paths": file_paths,
                "output_dir": output_dir,
            },
            priority=TaskPriority.LOW,
        )
        
        logger.info(f"Submitted {len(file_paths)} files for scraping")
    
    async def _run_import_job(self, directory: str) -> None:
        """执行定时导入"""
        logger.info(f"Running scheduled import job at {datetime.now()}")
        
        await self.queue.add(
            type=TaskType.IMPORT,
            data={
                "directory": directory,
                "recursive": True,
                "conflict_strategy": "skip",
            },
            priority=TaskPriority.LOW,
        )
    
    async def _run_patch_job(self) -> None:
        """执行定时补刮"""
        logger.info(f"Running scheduled patch job at {datetime.now()}")
        
        await self.queue.add(
            type=TaskType.PATCH,
            data={},
            priority=TaskPriority.LOW,
        )
    
    def _create_trigger(
        self,
        cron: Optional[str] = None,
        interval: Optional[int] = None,
    ):
        """创建触发器"""
        if cron:
            return CronTrigger.from_crontab(cron)
        
        if interval:
            return IntervalTrigger(seconds=interval)
        
        # 默认每天凌晨 2 点执行
        return CronTrigger(hour=2, minute=0)


# 全局管理器实例
_manager: Optional[ScheduledTaskManager] = None


def get_scheduled_task_manager() -> ScheduledTaskManager:
    """获取全局定时任务管理器"""
    global _manager
    
    if _manager is None:
        _manager = ScheduledTaskManager()
    
    return _manager