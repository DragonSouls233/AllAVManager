"""WebSocket 管理器 + 实时日志/进度推送

参考 mdc-ng 和 little6neko-mdcx 的实时日志推送方案：
- WebSocketManager 单例管理所有连接
- 支持日志流（log）和任务进度（progress）两种消息类型
- 自动重连由前端处理
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)
router = APIRouter()


class WebSocketManager:
    """WebSocket 连接管理器（单例）"""

    _instance: Optional["WebSocketManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.connections.add(websocket)
        logger.info(f"WebSocket 已连接，当前连接数: {len(self.connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.connections.discard(websocket)
        logger.info(f"WebSocket 已断开，当前连接数: {len(self.connections)}")

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        if not self.connections:
            return
        text = json.dumps(message, ensure_ascii=False, default=str)
        dead = []
        for ws in list(self.connections):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self.connections.discard(ws)

    async def broadcast_log(
        self,
        level: str,
        message: str,
        task_id: Optional[str] = None,
        module: Optional[str] = None,
    ):
        """广播日志消息

        level: INFO/WARNING/ERROR/SUCCESS/DEBUG
        """
        await self.broadcast({
            "type": "log",
            "level": level,
            "message": message,
            "task_id": task_id,
            "module": module,
            "timestamp": datetime.now().isoformat(),
        })

    async def broadcast_progress(
        self,
        task_id: str,
        task_name: str,
        current: int,
        total: int,
        status: str = "running",
        message: Optional[str] = None,
    ):
        """广播任务进度

        status: running/success/failed/cancelled
        """
        percent = round(current / total * 100, 1) if total > 0 else 0
        await self.broadcast({
            "type": "progress",
            "task_id": task_id,
            "task_name": task_name,
            "current": current,
            "total": total,
            "percent": percent,
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        })


# 全局单例
ws_manager = WebSocketManager()


# ============== WebSocket 端点 ==============

@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """实时日志流 WebSocket

    客户端连接后接收所有日志和任务进度消息。
    """
    await ws_manager.connect(websocket)
    try:
        # 发送欢迎消息
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "WebSocket 已连接",
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False))

        # 保持连接，接收客户端心跳
        while True:
            try:
                data = await websocket.receive_text()
                # 处理客户端心跳
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
    finally:
        await ws_manager.disconnect(websocket)


# ============== 工具函数（供其他模块调用） ==============

async def emit_log(level: str, message: str, task_id: Optional[str] = None, module: Optional[str] = None):
    """发送日志（供后端其他模块调用）"""
    await ws_manager.broadcast_log(level, message, task_id, module)


async def emit_progress(
    task_id: str,
    task_name: str,
    current: int,
    total: int,
    status: str = "running",
    message: Optional[str] = None,
):
    """发送任务进度（供后端其他模块调用）"""
    await ws_manager.broadcast_progress(task_id, task_name, current, total, status, message)
