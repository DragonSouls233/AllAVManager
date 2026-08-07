"""
任务执行器

执行刮削任务的工作进程
"""

import asyncio
import logging
import uuid
from typing import Optional

from app.tasks.queue import TaskQueue, Task, TaskType, TaskStatus
from app.scraper.workflow import ScraperWorkflow
from app.importer.sync import ImportSync

logger = logging.getLogger(__name__)


class TaskWorker:
    """
    任务执行器
    
    从队列获取任务并执行
    """
    
    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: float = 1.0,
    ):
        """
        初始化
        
        Args:
            worker_id: Worker ID（默认自动生成）
            poll_interval: 队列轮询间隔（秒）
        """
        self.worker_id = worker_id or str(uuid.uuid4())
        self.poll_interval = poll_interval
        
        self.queue = TaskQueue()
        self._running = False
        self._current_task: Optional[Task] = None
    
    async def start(self) -> None:
        """启动 Worker"""
        self._running = True
        logger.info(f"Worker started: {self.worker_id}")
        
        while self._running:
            try:
                # 获取下一个任务
                task = await self.queue.get_next(self.worker_id)
                
                if task:
                    self._current_task = task
                    await self._execute_task(task)
                    self._current_task = None
                else:
                    # 无任务，等待
                    await asyncio.sleep(self.poll_interval)
            
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(self.poll_interval)
    
    async def stop(self) -> None:
        """停止 Worker"""
        self._running = False
        logger.info(f"Worker stopped: {self.worker_id}")
    
    async def _execute_task(self, task: Task) -> None:
        """执行任务"""
        logger.info(f"Executing task: id={task.id}, type={task.type}")
        
        try:
            result = {}
            
            if task.type == TaskType.SCRAPE_FILE:
                result = await self._execute_scrape_file(task)
            
            elif task.type == TaskType.SCRAPE_BATCH:
                result = await self._execute_scrape_batch(task)
            
            elif task.type == TaskType.IMPORT:
                result = await self._execute_import(task)
            
            elif task.type == TaskType.PATCH:
                result = await self._execute_patch(task)
            
            else:
                raise ValueError(f"Unknown task type: {task.type}")
            
            # 完成任务
            await self.queue.complete(task.id, result, TaskStatus.SUCCESS)
        
        except Exception as e:
            logger.error(f"Task execution error: {e}")
            await self.queue.fail(task.id, str(e), retry=True)
    
    async def _execute_scrape_file(self, task: Task) -> dict:
        """执行单文件刮削"""
        file_path = task.data.get("file_path")
        output_dir = task.data.get("output_dir")
        sources = task.data.get("sources")
        
        if not file_path or not output_dir:
            raise ValueError("Missing file_path or output_dir")
        
        workflow = ScraperWorkflow(output_dir)
        result = await workflow.process_file(file_path, sources)
        
        if result:
            return {
                "code": result.code,
                "title": result.title,
                "source": result.source,
            }
        else:
            raise ValueError("Scrape failed")
    
    async def _execute_scrape_batch(self, task: Task) -> dict:
        """执行批量刮削"""
        file_paths = task.data.get("file_paths", [])
        output_dir = task.data.get("output_dir")
        sources = task.data.get("sources")
        
        if not file_paths or not output_dir:
            raise ValueError("Missing file_paths or output_dir")
        
        workflow = ScraperWorkflow(output_dir)
        
        # 执行批量刮削
        results = {}
        success_count = 0
        failed_count = 0
        
        for i, file_path in enumerate(file_paths):
            # 更新进度
            progress = (i / len(file_paths)) * 100
            await self.queue.update_progress(task.id, progress)
            
            try:
                result = await workflow.process_file(file_path, sources)
                if result:
                    results[file_path] = {
                        "code": result.code,
                        "title": result.title,
                    }
                    success_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        
        return {
            "total": len(file_paths),
            "success": success_count,
            "failed": failed_count,
            "results": results,
        }
    
    async def _execute_import(self, task: Task) -> dict:
        """执行导入"""
        directory = task.data.get("directory")
        recursive = task.data.get("recursive", True)
        conflict_strategy = task.data.get("conflict_strategy", "skip")
        
        if not directory:
            raise ValueError("Missing directory")
        
        sync = ImportSync(conflict_strategy=conflict_strategy)
        
        # 扫描目录
        directories = await sync.scan_directory(directory, recursive)
        
        # 执行导入
        report = await sync.import_batch(directories)
        
        return {
            "total": report.total,
            "success": report.success,
            "skipped": report.skipped,
            "failed": report.failed,
        }
    
    async def _execute_patch(self, task: Task) -> dict:
        """执行补刮（定时/队列任务）

        修复：旧代码调用了不存在的 PatchEngine.patch_all()，定时补刮一直崩溃。
        改为走 PatchWorkflow.run（与 API 后台任务同一路径）。
        默认跳过最近 7 天已刮削的 + 字段完整的，避免"待补数量不减少"死循环。
        """
        from app.patcher.engine import PatchMode, PatchOptions, PatchType, PatchWorkflow

        mode_str = task.data.get("mode", "all")
        patch_type_str = task.data.get("patch_type", "smart")
        codes = task.data.get("codes", []) or []
        directories = task.data.get("directories", []) or []

        try:
            mode = PatchMode(mode_str)
        except ValueError:
            mode = PatchMode.ALL
        try:
            patch_type = PatchType(patch_type_str)
        except ValueError:
            patch_type = PatchType.SMART

        options = PatchOptions(
            mode=mode,
            patch_type=patch_type,
            codes=codes,
            directories=directories,
            module=task.data.get("module"),
        )
        workflow = PatchWorkflow()
        result = await workflow.run(options)

        return {
            "status": "completed",
            "job_id": getattr(result, "job_id", None),
            "total_detected": getattr(result, "total_detected", 0),
            "total_skipped": getattr(result, "total_skipped", 0),
            "total_to_patch": getattr(result, "total_to_patch", 0),
            "total_patched": getattr(result, "total_patched", 0),
            "total_success": getattr(result, "total_success", 0),
            "total_partial": getattr(result, "total_partial", 0),
            "total_failed": getattr(result, "total_failed", 0),
        }


# 全局 Worker 实例
_worker: Optional[TaskWorker] = None


def get_worker() -> TaskWorker:
    """获取全局 Worker 实例"""
    global _worker
    
    if _worker is None:
        _worker = TaskWorker()
    
    return _worker