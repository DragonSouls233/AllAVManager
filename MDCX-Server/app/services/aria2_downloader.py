"""Aria2 下载器实现（§7.11）

通过 aria2 的 JSON-RPC 接口对接：
- 协议：JSON-RPC 2.0 over HTTP（POST）
- 鉴权：每个请求 params 数组首个元素为 "token:<secret>"（无 secret 时省略）
- 添加任务：aria2.addUri(uris, options)
- 列表：aria2.tellActive / aria2.tellWaiting / aria2.tellStopped
- 详情：aria2.tellStatus(gid)
- 删除：aria2.remove(gid)
- 暂停：aria2.pause(gid)
- 恢复：aria2.unpause(gid)
- 全局状态：aria2.getGlobalStat / aria2.getVersion

参考：https://aria2.github.io/manual/en/html/aria2c.html#rpc-interface
"""

import json
from typing import Optional

import httpx

from app.config.manager import get_config
from app.services.downloader import DownloaderBase, TaskStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30

# aria2 任务状态 → 统一 TaskStatus 映射
# active/waiting/paused/complete/error/removed
_ARIA_STATUS_MAP = {
    "active": TaskStatus.DOWNLOADING,
    "waiting": TaskStatus.PENDING,
    "paused": TaskStatus.PAUSED,
    "complete": TaskStatus.COMPLETED,
    "error": TaskStatus.ERROR,
    "removed": TaskStatus.ERROR,
}


class Aria2Downloader(DownloaderBase):
    """Aria2 下载器实现

    使用 httpx.AsyncClient 调用 aria2 JSON-RPC 接口。
    生命周期由 app.main lifespan 管理。
    """

    type = "aria2"

    def __init__(self):
        super().__init__(name="Aria2")
        self._client: Optional[httpx.AsyncClient] = None

    # ============== 内部辅助 ==============

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                follow_redirects=True,
            )
        return self._client

    def _build_params(self, *args) -> list:
        """构造 JSON-RPC params，自动在首位插入 token"""
        cfg = get_config().downloader.aria2
        params = []
        if cfg.secret:
            params.append(f"token:{cfg.secret}")
        params.extend(args)
        return params

    def _map_status(self, a_status: str) -> str:
        ts = _ARIA_STATUS_MAP.get(a_status, TaskStatus.UNKNOWN)
        return ts.value

    async def _rpc(self, method: str, *args) -> object:
        """执行一次 JSON-RPC 调用"""
        client = await self._get_client()
        cfg = get_config().downloader.aria2
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": method,
            "params": self._build_params(*args),
        }
        try:
            resp = await client.post(cfg.rpc_url, content=json.dumps(payload), headers={"Content-Type": "application/json"})
        except httpx.HTTPError as e:
            logger.error(f"Aria2 RPC 调用失败 [{method}]: {e}")
            raise

        if resp.status_code != 200:
            logger.error(f"Aria2 RPC 非 200 响应: {resp.status_code} {resp.text}")
            raise RuntimeError(f"Aria2 RPC 错误: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"Aria2 RPC 响应解析失败: {e}")
            raise

        if "error" in data and data["error"]:
            logger.error(f"Aria2 RPC 调用返回错误: {data['error']}")
            raise RuntimeError(f"Aria2 RPC 调用失败: {data['error']}")

        return data.get("result")

    # ============== 接口实现 ==============

    async def login(self) -> bool:
        cfg = get_config().downloader.aria2
        if not cfg.enabled:
            logger.info("Aria2 未启用，跳过登录")
            return False

        try:
            # 通过 getVersion 探测连接 + secret
            result = await self._rpc("aria2.getVersion")
            if isinstance(result, dict):
                self._logged_in = True
                logger.info(f"Aria2 连接成功: version={result.get('version', '')}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Aria2 连接失败: {e}")
            return False

    async def add_torrent(
        self,
        torrent_url_or_magnet: str,
        download_dir: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        cfg = get_config().downloader.aria2
        options: dict = {}
        if download_dir or cfg.download_dir:
            options["dir"] = download_dir or cfg.download_dir
        # name 在 aria2 中通过 out 选项指定下载文件名（仅对单文件有效）
        if name:
            options["out"] = name

        try:
            result = await self._rpc("aria2.addUri", [torrent_url_or_magnet], options)
            gid = str(result or "")
            if not gid:
                raise RuntimeError("Aria2 添加任务未返回 gid")
            return gid
        except Exception as e:
            logger.error(f"Aria2 添加任务异常: {e}")
            raise

    async def list_tasks(self, status: Optional[str] = None) -> list[dict]:
        """列出任务

        aria2 需要分别拉取 active/waiting/stopped 三类任务后合并。
        status 过滤在内存中进行。
        """
        try:
            # active: tellActive；waiting: tellWaiting(0, -1)；stopped: tellStopped(0, -1)
            active = await self._rpc("aria2.tellActive", 0, -1) or []
            waiting = await self._rpc("aria2.tellWaiting", 0, -1) or []
            stopped = await self._rpc("aria2.tellStopped", 0, -1) or []
            all_tasks = []
            for raw in (active + waiting + stopped):
                if isinstance(raw, dict):
                    all_tasks.append(self._normalize_task(raw))
            if status:
                all_tasks = [t for t in all_tasks if t["status"] == status]
            return all_tasks
        except Exception as e:
            logger.error(f"Aria2 列任务异常: {e}")
            raise

    async def get_task(self, task_id: str) -> dict:
        try:
            result = await self._rpc("aria2.tellStatus", task_id)
            if not isinstance(result, dict):
                raise RuntimeError(f"Aria2 任务不存在: {task_id}")
            return self._normalize_task(result)
        except Exception as e:
            logger.error(f"Aria2 获取任务异常: {e}")
            raise

    async def cancel_task(self, task_id: str) -> bool:
        try:
            # aria2.remove 删除任务（保留文件）；aria2.removeDownloadResult 清理结果记录
            await self._rpc("aria2.remove", task_id)
            return True
        except Exception as e:
            logger.error(f"Aria2 取消任务异常: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        try:
            await self._rpc("aria2.pause", task_id)
            return True
        except Exception as e:
            logger.error(f"Aria2 暂停任务异常: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        try:
            await self._rpc("aria2.unpause", task_id)
            return True
        except Exception as e:
            logger.error(f"Aria2 恢复任务异常: {e}")
            return False

    async def get_status(self) -> dict:
        cfg = get_config().downloader.aria2
        version = ""
        download_speed = 0
        upload_speed = 0
        active_count = 0
        connected = False

        try:
            ver = await self._rpc("aria2.getVersion")
            if isinstance(ver, dict):
                version = ver.get("version", "") or ""
                connected = True
        except Exception as e:
            logger.warning(f"Aria2 getVersion 失败: {e}")

        try:
            stat = await self._rpc("aria2.getGlobalStat")
            if isinstance(stat, dict):
                download_speed = int(stat.get("downloadSpeed", 0) or 0)
                upload_speed = int(stat.get("uploadSpeed", 0) or 0)
                active_count = int(stat.get("numActive", 0) or 0)
        except Exception:
            pass

        return {
            "type": self.type,
            "name": self.name,
            "enabled": cfg.enabled,
            "connected": connected,
            "logged_in": self._logged_in,
            "started": self._started,
            "rpc_url": cfg.rpc_url,
            "version": version,
            "download_speed": download_speed,
            "upload_speed": upload_speed,
            "active_tasks": active_count,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._started = False
        self._logged_in = False
        logger.info("Aria2 客户端已关闭")

    # ============== 字段标准化 ==============

    def _normalize_task(self, raw: dict) -> dict:
        size = int(raw.get("totalLength", 0) or 0)
        downloaded = int(raw.get("completedLength", 0) or 0)
        # 进度：downloaded / size
        if size > 0:
            progress_pct = round(downloaded / size * 100, 2)
        else:
            progress_pct = 0.0
        eta = int(raw.get("eta", -1) or -1)
        return {
            "id": str(raw.get("gid", "")),
            "name": raw.get("files", [{}])[0].get("path", "") if raw.get("files") else "",
            "status": self._map_status(raw.get("status", "")),
            "progress": progress_pct,
            "size": size,
            "downloaded": downloaded,
            "download_speed": int(raw.get("downloadSpeed", 0) or 0),
            "upload_speed": int(raw.get("uploadSpeed", 0) or 0),
            "eta": eta,
            "save_path": raw.get("dir", ""),
            "raw_status": raw.get("status", ""),
        }


__all__ = ["Aria2Downloader"]
