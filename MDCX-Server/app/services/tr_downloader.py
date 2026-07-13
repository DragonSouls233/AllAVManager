"""Transmission 下载器实现（§7.11）

通过 Transmission 的 RPC 端点（/transmission/rpc）对接：
- 鉴权：HTTP Basic Auth + session-header（X-Transmission-Session-Id）
  首次请求会返回 409 Conflict 与 X-Transmission-Session-Id，需带上重试。
- 添加种子：method=torrent-add（filename=URL 或 magnet）
- 任务列表：method=torrent-get（fields=id,name,status,...）
- 删除任务：method=torrent-remove（ids + delete-local-data）
- 暂停：method=torrent-stop（ids）
- 恢复：method=torrent-start（ids）
- 会话信息：method=session-get / session-stats

参考：https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md
"""

import json
from typing import Optional

import httpx

from app.config.manager import get_config
from app.services.downloader import DownloaderBase, TaskStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30

# Transmission 状态码 → 统一 TaskStatus 映射
# 0=已停止 1=检查等待 2=检查中 3=下载等待 4=下载中 5=做种等待 6=做种中
_TR_STATUS_MAP = {
    0: TaskStatus.PAUSED,
    1: TaskStatus.PENDING,
    2: TaskStatus.PENDING,
    3: TaskStatus.PENDING,
    4: TaskStatus.DOWNLOADING,
    5: TaskStatus.SEEDING,
    6: TaskStatus.SEEDING,
}


class TRDownloader(DownloaderBase):
    """Transmission 下载器实现

    使用 httpx.AsyncClient 调用 Transmission RPC 端点。
    生命周期由 app.main lifespan 管理。
    """

    type = "transmission"

    def __init__(self):
        super().__init__(name="Transmission")
        self._client: Optional[httpx.AsyncClient] = None
        # 缓存 X-Transmission-Session-Id
        self._session_id: str = ""

    # ============== 内部辅助 ==============

    def _base_url(self) -> str:
        cfg = get_config().downloader.transmission
        scheme = "https" if cfg.use_ssl else "http"
        return f"{scheme}://{cfg.host}:{cfg.port}"

    def _auth(self) -> Optional[httpx.BasicAuth]:
        cfg = get_config().downloader.transmission
        if cfg.username:
            return httpx.BasicAuth(cfg.username, cfg.password or "")
        return None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            cfg = get_config().downloader.transmission
            verify = not cfg.use_ssl  # 自签 HTTPS 时关闭校验
            self._client = httpx.AsyncClient(
                base_url=self._base_url(),
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                follow_redirects=True,
                auth=self._auth(),
                verify=verify,
            )
        return self._client

    def _map_status(self, tr_status: int) -> str:
        ts = _TR_STATUS_MAP.get(int(tr_status), TaskStatus.UNKNOWN)
        return ts.value

    async def _rpc(self, method: str, arguments: Optional[dict] = None) -> dict:
        """执行一次 RPC 调用，自动处理 409 session-header 重试"""
        client = await self._get_client()
        cfg = get_config().downloader.transmission
        payload = {"method": method}
        if arguments:
            payload["arguments"] = arguments

        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id

        try:
            resp = await client.post(cfg.rpc_path, content=json.dumps(payload), headers=headers)
        except httpx.HTTPError as e:
            logger.error(f"Transmission RPC 调用失败 [{method}]: {e}")
            raise

        # 409 Conflict: 需要更新 session-id 后重试一次
        if resp.status_code == 409:
            new_id = resp.headers.get("X-Transmission-Session-Id", "")
            if new_id:
                self._session_id = new_id
                headers["X-Transmission-Session-Id"] = new_id
                resp = await client.post(cfg.rpc_path, content=json.dumps(payload), headers=headers)

        if resp.status_code == 401:
            logger.warning("Transmission 认证失败（401）")
            raise RuntimeError("Transmission 认证失败")

        if resp.status_code != 200:
            logger.error(f"Transmission RPC 非 200 响应: {resp.status_code} {resp.text}")
            raise RuntimeError(f"Transmission RPC 错误: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"Transmission RPC 响应解析失败: {e}")
            raise

        if data.get("result") != "success":
            logger.error(f"Transmission RPC 调用返回非 success: {data.get('result')}")
            raise RuntimeError(f"Transmission RPC 调用失败: {data.get('result')}")

        return data.get("arguments", {}) or {}

    # ============== 接口实现 ==============

    async def login(self) -> bool:
        cfg = get_config().downloader.transmission
        if not cfg.enabled:
            logger.info("Transmission 未启用，跳过登录")
            return False

        try:
            # 通过 session-get 探测连接 + 鉴权
            await self._rpc("session-get")
            self._logged_in = True
            logger.info("Transmission 连接成功")
            return True
        except Exception as e:
            logger.warning(f"Transmission 连接失败: {e}")
            return False

    async def add_torrent(
        self,
        torrent_url_or_magnet: str,
        download_dir: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        cfg = get_config().downloader.transmission
        arguments = {"filename": torrent_url_or_magnet}
        if download_dir or cfg.download_dir:
            arguments["download-dir"] = download_dir or cfg.download_dir
        # name 字段 Transmission 通过 cookies/labels 间接支持，此处不实现

        try:
            result = await self._rpc("torrent-add", arguments)
            # 返回结构：{"torrent-added": {"hashString": ..., "id": ..., "name": ...}}
            added = result.get("torrent-added") or result.get("torrent-duplicate") or {}
            task_id = added.get("hashString") or added.get("id") or ""
            if not task_id:
                # 占位 ID
                return torrent_url_or_magnet
            return str(task_id)
        except Exception as e:
            logger.error(f"Transmission 添加种子异常: {e}")
            raise

    async def list_tasks(self, status: Optional[str] = None) -> list[dict]:
        # 拉取所有任务后在内存中过滤
        fields = [
            "id", "name", "status", "hashString", "totalSize", "downloadedEver",
            "uploadRatio", "rateDownload", "rateUpload", "eta", "percentDone",
            "downloadDir", "isFinished",
        ]
        try:
            result = await self._rpc("torrent-get", {"fields": fields})
            items = result.get("torrents", []) or []
            normalized = [self._normalize_task(t) for t in items]
            if status:
                normalized = [t for t in normalized if t["status"] == status]
            return normalized
        except Exception as e:
            logger.error(f"Transmission 列任务异常: {e}")
            raise

    async def get_task(self, task_id: str) -> dict:
        fields = [
            "id", "name", "status", "hashString", "totalSize", "downloadedEver",
            "uploadRatio", "rateDownload", "rateUpload", "eta", "percentDone",
            "downloadDir", "isFinished",
        ]
        try:
            # task_id 可能是 hash 也可能是数字 id
            ids_param: dict
            if task_id.isdigit():
                ids_param = {"ids": [int(task_id)]}
            else:
                ids_param = {"ids": [task_id]}
            result = await self._rpc("torrent-get", {"fields": fields, **ids_param})
            items = result.get("torrents", []) or []
            if not items:
                raise RuntimeError(f"Transmission 任务不存在: {task_id}")
            return self._normalize_task(items[0])
        except Exception as e:
            logger.error(f"Transmission 获取任务异常: {e}")
            raise

    async def cancel_task(self, task_id: str) -> bool:
        ids_param = self._ids_param(task_id)
        try:
            await self._rpc("torrent-remove", {**ids_param, "delete-local-data": False})
            return True
        except Exception as e:
            logger.error(f"Transmission 取消任务异常: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        ids_param = self._ids_param(task_id)
        try:
            await self._rpc("torrent-stop", ids_param)
            return True
        except Exception as e:
            logger.error(f"Transmission 暂停任务异常: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        ids_param = self._ids_param(task_id)
        try:
            await self._rpc("torrent-start", ids_param)
            return True
        except Exception as e:
            logger.error(f"Transmission 恢复任务异常: {e}")
            return False

    async def get_status(self) -> dict:
        cfg = get_config().downloader.transmission
        version = ""
        download_speed = 0
        upload_speed = 0
        connected = False
        active_count = 0

        try:
            session = await self._rpc("session-get")
            version = session.get("version", "") or ""
            download_speed = int(session.get("downloadSpeed", 0) or 0)
            upload_speed = int(session.get("uploadSpeed", 0) or 0)
            connected = True
        except Exception as e:
            logger.warning(f"Transmission session-get 失败: {e}")

        try:
            stats = await self._rpc("session-stats")
            active_count = int(stats.get("activeTorrentCount", 0) or 0)
        except Exception:
            pass

        return {
            "type": self.type,
            "name": self.name,
            "enabled": cfg.enabled,
            "connected": connected,
            "logged_in": self._logged_in,
            "started": self._started,
            "host": cfg.host,
            "port": cfg.port,
            "version": version,
            "download_speed": download_speed,
            "upload_speed": upload_speed,
            "active_tasks": active_count,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._session_id = ""
        self._started = False
        self._logged_in = False
        logger.info("Transmission 客户端已关闭")

    # ============== 辅助方法 ==============

    def _ids_param(self, task_id: str) -> dict:
        """根据 task_id 类型构造 ids 参数"""
        if task_id.isdigit():
            return {"ids": [int(task_id)]}
        return {"ids": [task_id]}

    def _normalize_task(self, raw: dict) -> dict:
        size = int(raw.get("totalSize", 0) or 0)
        downloaded = int(raw.get("downloadedEver", 0) or 0)
        percent = float(raw.get("percentDone", 0.0) or 0.0)
        progress_pct = round(percent * 100, 2)
        eta = int(raw.get("eta", -1) or -1)
        task_id = str(raw.get("hashString") or raw.get("id") or "")
        # 已完成且停止做种 → completed
        unified = self._map_status(int(raw.get("status", 0) or 0))
        if raw.get("isFinished") and unified == TaskStatus.SEEDING.value:
            unified = TaskStatus.COMPLETED.value
        return {
            "id": task_id,
            "name": raw.get("name", ""),
            "status": unified,
            "progress": progress_pct,
            "size": size,
            "downloaded": downloaded,
            "download_speed": int(raw.get("rateDownload", 0) or 0),
            "upload_speed": int(raw.get("rateUpload", 0) or 0),
            "eta": eta,
            "save_path": raw.get("downloadDir", ""),
            "raw_status": int(raw.get("status", 0) or 0),
        }


__all__ = ["TRDownloader"]
