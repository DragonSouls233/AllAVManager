"""WebSocket 实时事件推送服务。

支持事件类型：
- log: 日志消息
- progress: 任务进度（刮削/下载/后处理）
- system: 系统通知
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class EventBus:
    """全局事件总线 — 管理 WebSocket 订阅者并推送事件。"""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._ws_queues: dict[str, asyncio.Queue] = {}

    def subscribe(self, event_type: str, callback: Callable) -> str:
        """订阅事件。

        Args:
            event_type: 事件类型（"all" 表示所有事件）
            callback: 回调函数 async def callback(event: dict)

        Returns:
            subscriber_id: 用于取消订阅
        """
        sid = uuid4().hex[:12]
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        return sid

    def unsubscribe(self, sid: str):
        """取消订阅。"""
        for event_type in list(self._subscribers.keys()):
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type]
                if id(cb) != sid and not hasattr(cb, "__self__")
            ]
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type]
            ]

    def add_ws_queue(self, q: asyncio.Queue):
        """注册 WebSocket 队列。"""
        qid = uuid4().hex[:12]
        self._ws_queues[qid] = q
        return qid

    def remove_ws_queue(self, qid: str):
        self._ws_queues.pop(qid, None)

    async def emit(self, event_type: str, data: Any):
        """推送事件到所有订阅者和 WebSocket 客户端。

        Args:
            event_type: "log" | "progress" | "system"
            data: 事件数据（dict）
        """
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        # 发送给回调订阅者
        callbacks = self._subscribers.get("all", []) + self._subscribers.get(event_type, [])
        for cb in callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                logger.debug("event callback failed: %s", e)

        # 发送给 WebSocket 队列
        dead_queues: list[str] = []
        for qid, q in self._ws_queues.items():
            try:
                await asyncio.wait_for(q.put(event), timeout=1.0)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                dead_queues.append(qid)
            except Exception:
                dead_queues.append(qid)

        for qid in dead_queues:
            self.remove_ws_queue(qid)

    async def emit_progress(self, task_id: str, progress: float,
                            message: str, status: str = "running",
                            module: str = ""):
        """推送任务进度。"""
        await self.emit("progress", {
            "task_id": task_id,
            "progress": progress,
            "message": message,
            "status": status,
            "module": module,
        })

    async def emit_log(self, level: str, message: str,
                       module: str = "", task_id: str = ""):
        """推送日志消息。"""
        await self.emit("log", {
            "level": level,
            "message": message,
            "module": module,
            "task_id": task_id,
        })


# 全局单例
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
