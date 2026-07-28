"""MCP（Model Context Protocol）服务端。

让 Claude Code / Cursor 等 AI 客户端直接操作 MDCX：
- 搜索影片 / 演员
- 触发刮削
- 管理下载器
- 控制播放

参考：Javdex 的 mcp-plugin-dev-server.ts (@modelcontextprotocol/sdk)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from app.config.manager import get_config
from app.services.javdb_api_client import create_client_from_config, JavDBMovie

logger = logging.getLogger(__name__)


MCP_CAPABILITIES = {
    "tools": [
        {
            "name": "search_movie",
            "description": "按番号搜索影片元数据",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "番号，如 SSIS-001"},
                },
                "required": ["code"],
            },
        },
        {
            "name": "trigger_scrape",
            "description": "触发指定媒体库的扫描/刮削",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "模块名: jav / uncensored / fc2 / chinese / pornhub / western",
                    },
                    "path": {
                        "type": "string",
                        "description": "可选，指定文件或目录路径",
                    },
                },
                "required": ["module"],
            },
        },
        {
            "name": "search_local_movies",
            "description": "在数据库中搜索已有影片",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "关键词"},
                    "module": {"type": "string", "description": "可选，模块名"},
                    "page": {"type": "integer", "description": "页码", "default": 1},
                    "page_size": {"type": "integer", "description": "每页数量", "default": 20},
                },
                "required": ["keyword"],
            },
        },
        {
            "name": "get_movie_detail",
            "description": "获取影片详情（含播放信息）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "movie_id": {"type": "integer", "description": "影片 ID"},
                    "module": {"type": "string", "description": "模块名"},
                },
                "required": ["movie_id", "module"],
            },
        },
        {
            "name": "list_downloading",
            "description": "列出当前下载队列",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "search_online_source",
            "description": "搜索在线播放源（聚合多站 M3U8）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "番号"},
                },
                "required": ["code"],
            },
        },
    ],
    "resources": [
        {
            "uri": "mdcx://library/stats",
            "name": "媒体库统计信息",
            "description": "各模块的影片数量和状态统计",
        },
        {
            "uri": "mdcx://system/status",
            "name": "系统运行状态",
            "description": "服务运行状态、代理状态、磁盘空间等",
        },
    ],
}


@dataclass
class MCPToolResult:
    success: bool = True
    data: Any = None
    error: str = ""
    tool_call_id: str = ""


class MCPService:
    """MCP 服务 — 封装 MDCX 业务能力供 AI 调用。"""

    def __init__(self):
        self.config = get_config()

    async def handle_tool_call(self, tool_name: str, arguments: dict) -> dict:
        """处理 AI 的工具调用请求。"""
        handler = getattr(self, f"tool_{tool_name}", None)
        if not handler:
            return {"success": False, "error": f"未知工具: {tool_name}"}
        try:
            result = await handler(**arguments)
            return {"success": True, "data": result}
        except Exception as e:
            logger.exception("MCP tool %s failed", tool_name)
            return {"success": False, "error": str(e)}

    async def tool_search_movie(self, code: str) -> dict:
        """搜索影片。"""
        client = await create_client_from_config()
        try:
            movie = await client.search_movie(code)
            if movie:
                return {
                    "code": movie.code,
                    "title": movie.title,
                    "title_cn": movie.title_cn,
                    "date": movie.date,
                    "duration": movie.duration,
                    "director": movie.director,
                    "maker": movie.maker,
                    "publisher": movie.publisher,
                    "score": movie.score,
                    "genres": movie.genres,
                    "actors": movie.actors,
                    "cover_url": movie.cover_url,
                }
            return {"note": f"未找到番号 {code} 的信息"}
        finally:
            await client.close()

    async def tool_trigger_scrape(self, module: str, path: str = "") -> dict:
        """触发刮削。"""
        from app.tasks.scheduler import scheduler
        job_id = f"scrape_{module}"
        if scheduler.get_job(job_id):
            scheduler.modify_job(job_id)
            return {"status": "rescheduled", "module": module}
        scheduler.add_job(
            "scanner", module=module,
            run_immediately=True, path=path or None,
        )
        return {"status": "started", "module": module, "path": path or "default"}

    async def tool_search_local_movies(self, keyword: str, module: str = "",
                                       page: int = 1, page_size: int = 20) -> dict:
        """搜索本地影片。"""
        from app.db.database import get_db_session
        from sqlalchemy import text

        async with get_db_session() as session:
            if module:
                model_map = {
                    "jav": "jav_movies",
                    "fc2": "fc2_movies",
                    "chinese": "chinese_movies",
                    "pornhub": "pornhub_movies",
                    "western": "western_movies",
                    "uncensored": "uncensored_movies",
                }
                table = model_map.get(module)
                if not table:
                    return {"error": f"未知模块: {module}"}
                sql = text(f"""
                    SELECT id, code, title, release_date, score
                    FROM {table}
                    WHERE code LIKE :kw OR title LIKE :kw
                    ORDER BY id DESC
                    LIMIT :limit OFFSET :offset
                """)
            else:
                sql = text("""
                    SELECT id, code, title, release_date, score, 'jav' as module
                    FROM jav_movies WHERE code LIKE :kw OR title LIKE :kw
                    UNION ALL SELECT id, code, title, release_date, score, 'fc2'
                    FROM fc2_movies WHERE code LIKE :kw OR title LIKE :kw
                    UNION ALL SELECT id, code, title, release_date, score, 'chinese'
                    FROM chinese_movies WHERE code LIKE :kw OR title LIKE :kw
                    LIMIT :limit OFFSET :offset
                """)
            kw = f"%{keyword}%"
            rows = (await session.execute(sql, {"kw": kw, "limit": page_size, "offset": (page - 1) * page_size})).fetchall()
            return {
                "total": len(rows),
                "page": page,
                "results": [dict(r._mapping) for r in rows],
            }

    async def tool_get_movie_detail(self, movie_id: int, module: str) -> dict:
        """获取影片详情。"""
        from app.db.database import get_db_session
        from sqlalchemy import text

        model_map = {
            "jav": "jav_movies", "fc2": "fc2_movies",
            "chinese": "chinese_movies", "pornhub": "pornhub_movies",
            "western": "western_movies", "uncensored": "uncensored_movies",
        }
        table = model_map.get(module)
        if not table:
            return {"error": f"未知模块: {module}"}

        async with get_db_session() as session:
            sql = text(f"SELECT * FROM {table} WHERE id = :id")
            row = (await session.execute(sql, {"id": movie_id})).fetchone()
            if row:
                return dict(row._mapping)
            return {"error": "未找到影片"}

    async def tool_list_downloading(self) -> dict:
        """列出下载队列。"""
        from app.services.downloader_manager import downloader_manager
        tasks = downloader_manager.get_running_tasks()
        return {
            "downloading_count": len(tasks),
            "tasks": [
                {"name": t.get("name"), "progress": t.get("progress", 0),
                 "speed": t.get("speed", ""), "eta": t.get("eta", "")}
                for t in tasks
            ],
        }

    async def tool_search_online_source(self, code: str) -> dict:
        """搜索在线播放源。"""
        from app.services.streaming_aggregator import search_online_source
        return await search_online_source(code)

    # ------------------------------------------------------------------ #
    # Resources
    # ------------------------------------------------------------------ #

    async def get_resource(self, uri: str) -> Optional[dict]:
        """获取资源。"""
        if uri == "mdcx://library/stats":
            return await self._resource_library_stats()
        elif uri == "mdcx://system/status":
            return await self._resource_system_status()
        return None

    async def _resource_library_stats(self) -> dict:
        from app.db.database import get_db_session
        from sqlalchemy import text

        stats = {}
        async with get_db_session() as session:
            for module, table in [
                ("jav", "jav_movies"), ("fc2", "fc2_movies"),
                ("chinese", "chinese_movies"), ("pornhub", "pornhub_movies"),
                ("western", "western_movies"), ("uncensored", "uncensored_movies"),
            ]:
                row = (await session.execute(
                    text(f"SELECT COUNT(*) as count FROM {table}")
                )).fetchone()
                stats[module] = row[0] if row else 0
        return stats

    async def _resource_system_status(self) -> dict:
        import shutil
        disk = shutil.disk_usage("/")
        return {
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "disk_free_gb": round(disk.free / (1024**3), 1),
            "disk_used_pct": round(disk.used / disk.total * 100, 1),
            "proxy_enabled": self.config.proxy.enabled,
        }
