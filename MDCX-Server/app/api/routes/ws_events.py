"""WebSocket 实时事件推送端点。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.event_bus import get_event_bus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    """WebSocket 实时事件推送端点。

    前端连接：
      const ws = new WebSocket("ws://host:8420/api/ws/events")
      ws.onmessage = (e) => {
        const { type, data, timestamp } = JSON.parse(e.data)
      }

    事件类型：
      - log:     {"level":"info","message":"...","module":"..."}
      - progress: {"task_id":"...","progress":0.5,"message":"...","status":"running"}
      - system:   {"action":"restart","message":"..."}
    """
    await ws.accept()

    event_bus = get_event_bus()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    qid = event_bus.add_ws_queue(queue)

    # 发送连接确认
    await ws.send_json({
        "type": "connected",
        "data": {"message": "connected to MDCX event stream"},
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    })

    try:
        while True:
            # 检查前端发来的消息（ping/pong）
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                if raw.strip().lower() == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break

            # 出队事件并发送
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        event_bus.remove_ws_queue(qid)
        try:
            await ws.close()
        except Exception:
            pass
