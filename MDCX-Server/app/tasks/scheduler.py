"""
任务调度器

管理任务调度和执行
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.tasks.queue import TaskQueue, TaskType, TaskStatus, TaskPriority
from app.tasks.worker import TaskWorker

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    任务调度器
    
    管理任务队列和 Worker
    """
    
    def __init__(
        self,
        num_workers: int = 1,
    ):
        """
        初始化
        
        Args:
            num_workers: Worker 数量
        """
        self.num_workers = num_workers
        self.queue = TaskQueue()
        self.workers: list[TaskWorker] = []
        self._running = False
    
    async def start(self) -> None:
        """启动调度器"""
        self._running = True
        
        # 创建并启动 Workers
        for i in range(self.num_workers):
            worker = TaskWorker(worker_id=f"worker-{i}")
            self.workers.append(worker)
        
        # 启动所有 Workers 作为后台任务(避免死锁)
        # worker.start() 是无限循环,使用 create_task 而非 gather
        for worker in self.workers:
            asyncio.create_task(worker.start())

        logger.info(f"Scheduler started with {self.num_workers} workers")
    
    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        
        # 停止所有 Workers
        for worker in self.workers:
            await worker.stop()
        
        self.workers.clear()
        
        logger.info("Scheduler stopped")
    
    async def submit_scrape_file(
        self,
        file_path: str,
        output_dir: str,
        sources: Optional[list[str]] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> int:
        """
        提交单文件刮削任务
        
        Args:
            file_path: 文件路径
            output_dir: 输出目录
            sources: 指定站点
            priority: 优先级
            
        Returns:
            任务ID
        """
        task = await self.queue.add(
            type=TaskType.SCRAPE_FILE,
            data={
                "file_path": file_path,
                "output_dir": output_dir,
                "sources": sources,
            },
            priority=priority,
        )
        
        return task.id
    
    async def submit_scrape_batch(
        self,
        file_paths: list[str],
        output_dir: str,
        sources: Optional[list[str]] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> int:
        """
        提交批量刮削任务
        
        Args:
            file_paths: 文件路径列表
            output_dir: 输出目录
            sources: 指定站点
            priority: 优先级
            
        Returns:
            任务ID
        """
        task = await self.queue.add(
            type=TaskType.SCRAPE_BATCH,
            data={
                "file_paths": file_paths,
                "output_dir": output_dir,
                "sources": sources,
            },
            priority=priority,
        )
        
        return task.id
    
    async def submit_import(
        self,
        directory: str,
        recursive: bool = True,
        conflict_strategy: str = "skip",
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> int:
        """
        提交导入任务
        
        Args:
            directory: 目录路径
            recursive: 是否递归
            conflict_strategy: 冲突策略
            priority: 优先级
            
        Returns:
            任务ID
        """
        task = await self.queue.add(
            type=TaskType.IMPORT,
            data={
                "directory": directory,
                "recursive": recursive,
                "conflict_strategy": conflict_strategy,
            },
            priority=priority,
        )
        
        return task.id
    
    async def get_task_status(self, task_id: int) -> Optional[dict]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务状态字典
        """
        task = await self.queue.get(task_id)
        
        if task:
            return task.to_dict()
        
        return None
    
    async def cancel_task(self, task_id: int) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否成功取消
        """
        task = await self.queue.get(task_id)
        
        if task and task.status in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RETRY):
            await self.queue.cancel(task_id)
            return True
        
        return False
    
    async def get_queue_stats(self) -> dict:
        """
        获取队列统计
        
        Returns:
            统计信息
        """
        pending_count = await self.queue.count(TaskStatus.PENDING)
        queued_count = await self.queue.count(TaskStatus.QUEUED)
        running_count = await self.queue.count(TaskStatus.RUNNING)
        success_count = await self.queue.count(TaskStatus.SUCCESS)
        failed_count = await self.queue.count(TaskStatus.FAILED)
        
        return {
            "pending": pending_count,
            "queued": queued_count,
            "running": running_count,
            "success": success_count,
            "failed": failed_count,
            "total": pending_count + queued_count + running_count + success_count + failed_count,
        }


# 全局调度器实例
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """获取全局调度器实例"""
    global _scheduler
    
    if _scheduler is None:
        _scheduler = TaskScheduler()
    
    return _scheduler