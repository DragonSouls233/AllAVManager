"""
任务队列

基于 SQLite 的任务持久化队列
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any

from app.db.database import get_db
from sqlalchemy import text

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"        # 待处理
    QUEUED = "queued"          # 已入队
    RUNNING = "running"        # 运行中
    SUCCESS = "success"        # 成功
    FAILED = "failed"          # 失败
    RETRY = "retry"            # 重试中
    CANCELLED = "cancelled"    # 已取消


class TaskPriority(int, Enum):
    """任务优先级"""
    LOW = 10
    NORMAL = 5
    HIGH = 1
    URGENT = 0


class TaskType(str, Enum):
    """任务类型"""
    SCRAPE_FILE = "scrape_file"      # 单文件刮削
    SCRAPE_BATCH = "scrape_batch"    # 批量刮削
    IMPORT = "import"                # 导入已有刮削
    PATCH = "patch"                  # 补刮
    ORGANIZE = "organize"            # 文件整理


@dataclass
class Task:
    """任务数据"""
    id: Optional[int] = None
    type: TaskType = TaskType.SCRAPE_FILE
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    
    # 任务数据
    data: dict = field(default_factory=dict)  # 任务参数
    result: dict = field(default_factory=dict)  # 执行结果
    
    # 进度
    progress: float = 0.0  # 进度百分比
    
    # 时间
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    
    # 重试
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    
    # 元信息
    worker_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "data": self.data,
            "result": self.result,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "worker_id": self.worker_id,
        }


class TaskQueue:
    """
    任务队列
    
    基于 SQLite 的持久化任务队列
    """
    
    def __init__(self):
        """初始化任务队列"""
        self.db = get_db()
    
    async def add(
        self,
        type: TaskType,
        data: dict,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
    ) -> Task:
        """
        添加任务
        
        Args:
            type: 任务类型
            data: 任务数据
            priority: 优先级
            max_retries: 最大重试次数
            
        Returns:
            Task 任务对象
        """
        task = Task(
            type=type,
            data=data,
            priority=priority,
            status=TaskStatus.QUEUED,
            max_retries=max_retries,
            created_at=datetime.now(),
        )
        
        async with self.db.session() as session:
            await session.execute(
                text("""
                INSERT INTO tasks (
                    type, status, priority, data, progress,
                    created_at, retry_count, max_retries
                ) VALUES (:type, :status, :priority, :data, 0, :created_at, 0, :max_retries)
                """),
                {
                    "type": task.type.value,
                    "status": task.status.value,
                    "priority": task.priority.value,
                    "data": json.dumps(task.data),
                    "created_at": task.created_at.isoformat(),
                    "max_retries": task.max_retries,
                },
            )
            
            # 获取ID
            result = await session.execute(
                text("SELECT id FROM tasks WHERE created_at = :created_at"),
                {"created_at": task.created_at.isoformat()},
            )
            row = result.fetchone()
            task.id = row[0] if row else None
        
        logger.info(f"Added task: id={task.id}, type={task.type}")
        
        return task
    
    async def get_next(self, worker_id: str) -> Optional[Task]:
        """
        获取下一个待处理任务
        
        Args:
            worker_id: Worker ID
            
        Returns:
            Task 任务对象，无任务返回 None
        """
        async with self.db.session() as session:
            # 查询优先级最高的待处理任务
            result = await session.execute(
                text("""
                SELECT id, type, status, priority, data, progress,
                       created_at, started_at, finished_at,
                       retry_count, max_retries, error_message
                FROM tasks
                WHERE status IN ('queued', 'retry')
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """)
            )
            
            row = result.fetchone()
            
            if not row:
                return None
            
            # 更新状态为运行中
            task_id = row[0]
            await session.execute(
                text("""
                UPDATE tasks SET
                    status = 'running',
                    started_at = :started_at,
                    worker_id = :worker_id
                WHERE id = :id
                """),
                {"started_at": datetime.now().isoformat(), "worker_id": worker_id, "id": task_id},
            )
            
            # 构建任务对象
            task = Task(
                id=row[0],
                type=TaskType(row[1]),
                status=TaskStatus.RUNNING,
                priority=TaskPriority(row[3]),
                data=json.loads(row[4]),
                progress=row[5],
                created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                started_at=datetime.fromisoformat(row[7]) if row[7] else None,
                finished_at=datetime.fromisoformat(row[8]) if row[8] else None,
                retry_count=row[9],
                max_retries=row[10],
                error_message=row[11],
                worker_id=worker_id,
            )
            
            return task
    
    async def update_progress(self, task_id: int, progress: float) -> None:
        """更新任务进度"""
        async with self.db.session() as session:
            await session.execute(
                text("UPDATE tasks SET progress = :progress WHERE id = :id"),
                {"progress": progress, "id": task_id},
            )
    
    async def complete(
        self,
        task_id: int,
        result: dict,
        status: TaskStatus = TaskStatus.SUCCESS,
    ) -> None:
        """
        完成任务
        
        Args:
            task_id: 任务ID
            result: 结果数据
            status: 最终状态
        """
        async with self.db.session() as session:
            await session.execute(
                text("""
                UPDATE tasks SET
                    status = :status,
                    result = :result,
                    progress = 100,
                    finished_at = :finished_at
                WHERE id = :id
                """),
                {
                    "status": status.value,
                    "result": json.dumps(result),
                    "finished_at": datetime.now().isoformat(),
                    "id": task_id,
                },
            )
        
        logger.info(f"Task completed: id={task_id}, status={status}")
    
    async def fail(
        self,
        task_id: int,
        error_message: str,
        retry: bool = True,
    ) -> None:
        """
        任务失败
        
        Args:
            task_id: 任务ID
            error_message: 错误信息
            retry: 是否重试
        """
        async with self.db.session() as session:
            # 获取当前重试次数
            result = await session.execute(
                text("SELECT retry_count, max_retries FROM tasks WHERE id = :id"),
                {"id": task_id},
            )
            row = result.fetchone()
            
            if not row:
                return
            
            retry_count = row[0]
            max_retries = row[1]
            
            if retry and retry_count < max_retries:
                # 设置为重试状态
                await session.execute(
                    text("""
                    UPDATE tasks SET
                        status = 'retry',
                        retry_count = :retry_count,
                        error_message = :error_message,
                        started_at = NULL,
                        worker_id = NULL
                    WHERE id = :id
                    """),
                    {"retry_count": retry_count + 1, "error_message": error_message, "id": task_id},
                )
                logger.info(f"Task retry: id={task_id}, retry_count={retry_count + 1}")
            else:
                # 设置为失败状态
                await session.execute(
                    text("""
                    UPDATE tasks SET
                        status = 'failed',
                        error_message = :error_message,
                        finished_at = :finished_at
                    WHERE id = :id
                    """),
                    {"error_message": error_message, "finished_at": datetime.now().isoformat(), "id": task_id},
                )
                logger.warning(f"Task failed: id={task_id}, error={error_message}")
    
    async def cancel(self, task_id: int) -> None:
        """取消任务"""
        async with self.db.session() as session:
            await session.execute(
                text("""
                UPDATE tasks SET
                    status = 'cancelled',
                    finished_at = :finished_at
                WHERE id = :id AND status IN ('pending', 'queued', 'retry')
                """),
                {"finished_at": datetime.now().isoformat(), "id": task_id},
            )
    
    async def get(self, task_id: int) -> Optional[Task]:
        """获取任务"""
        async with self.db.session() as session:
            result = await session.execute(
                text("""
                SELECT id, type, status, priority, data, result, progress,
                       created_at, started_at, finished_at,
                       retry_count, max_retries, error_message, worker_id
                FROM tasks WHERE id = :id
                """),
                {"id": task_id},
            )
            
            row = result.fetchone()
            
            if not row:
                return None
            
            return Task(
                id=row[0],
                type=TaskType(row[1]),
                status=TaskStatus(row[2]),
                priority=TaskPriority(row[3]),
                data=json.loads(row[4]),
                result=json.loads(row[5]) if row[5] else {},
                progress=row[6],
                created_at=datetime.fromisoformat(row[7]) if row[7] else None,
                started_at=datetime.fromisoformat(row[8]) if row[8] else None,
                finished_at=datetime.fromisoformat(row[9]) if row[9] else None,
                retry_count=row[10],
                max_retries=row[11],
                error_message=row[12],
                worker_id=row[13],
            )
    
    async def list(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """
        列出任务
        
        Args:
            status: 过滤状态
            limit: 数量限制
            offset: 偏移
            
        Returns:
            任务列表
        """
        async with self.db.session() as session:
            if status:
                result = await session.execute(
                    text("""
                    SELECT id, type, status, priority, data, result, progress,
                           created_at, started_at, finished_at,
                           retry_count, max_retries, error_message, worker_id
                    FROM tasks
                    WHERE status = :status
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                    """),
                    {"status": status.value, "limit": limit, "offset": offset},
                )
            else:
                result = await session.execute(
                    text("""
                    SELECT id, type, status, priority, data, result, progress,
                           created_at, started_at, finished_at,
                           retry_count, max_retries, error_message, worker_id
                    FROM tasks
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                    """),
                    {"limit": limit, "offset": offset},
                )
            
            tasks = []
            for row in result.fetchall():
                tasks.append(Task(
                    id=row[0],
                    type=TaskType(row[1]),
                    status=TaskStatus(row[2]),
                    priority=TaskPriority(row[3]),
                    data=json.loads(row[4]),
                    result=json.loads(row[5]) if row[5] else {},
                    progress=row[6],
                    created_at=datetime.fromisoformat(row[7]) if row[7] else None,
                    started_at=datetime.fromisoformat(row[8]) if row[8] else None,
                    finished_at=datetime.fromisoformat(row[9]) if row[9] else None,
                    retry_count=row[10],
                    max_retries=row[11],
                    error_message=row[12],
                    worker_id=row[13],
                ))
            
            return tasks
    
    async def count(self, status: Optional[TaskStatus] = None) -> int:
        """统计任务数量"""
        async with self.db.session() as session:
            if status:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM tasks WHERE status = :status"),
                    {"status": status.value},
                )
            else:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM tasks")
                )
            
            row = result.fetchone()
            return row[0] if row else 0
    
    async def clear_completed(self) -> int:
        """清理已完成的任务"""
        async with self.db.session() as session:
            result = await session.execute(
                text("DELETE FROM tasks WHERE status IN ('success', 'failed', 'cancelled')")
            )
            return result.rowcount