"""qBittorrent 下载器实现（§7.11）

通过 qBittorrent 的 Web API（/api/v2/*）对接：
- 登录：POST /api/v2/auth/login（form 表单 username/password，返回 SID Cookie）
- 添加种子：POST /api/v2/torrents/add（urls + savepath）
- 任务列表：GET /api/v2/torrents/info（可选 filter=downloading/paused/...）
- 删除任务：POST /api/v2/torrents/delete（hashes + deleteFiles）
- 暂停：POST /api/v2/torrents/pause（hashes）
- 恢复：POST /api/v2/torrents/resume（hashes）
- 全局状态：GET /api/v2/transfer/info / GET /api/v2/app/version

参考：https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)
"""

import logging
from typing import Optional

import httpx

from app.config.manager import get_config
from app.services.downloader import DownloaderBase, TaskStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 请求超时（秒）
DEFAULT_TIMEOUT = 30
# qBittorrent 任务状态 → 统一 TaskStatus 映射
_QB_STATE_MAP = {
    "error": TaskStatus.ERROR,
    "missingFiles": TaskStatus.ERROR,
    "uploading": TaskStatus.SEEDING,
    "queuedUP": TaskStatus.SEEDING,
    "stalledUP": TaskStatus.SEEDING,
    "forcedUP": TaskStatus.SEEDING,
    "pausedUP": TaskStatus.PAUSED,
    "checkingUP": TaskStatus.SEEDING,
    "checkingDL": TaskStatus.PENDING,
    "checkingResumeData": TaskStatus.PENDING,
    "forcedDL": TaskStatus.DOWNLOADING,
    "downloading": TaskStatus.DOWNLOADING,
    "metaDL": TaskStatus.DOWNLOADING,
    "stalledDL": TaskStatus.PENDING,
    "queuedDL": TaskStatus.PENDING,
}


class QBDownloader(DownloaderBase):
    """qBittorrent 下载器实现

    使用 httpx.AsyncClient 调用 qBittorrent Web API。
    生命周期由 app.main lifespan 管理。
    """

    type = "qbittorrent"

    def __init__(self):
        super().__init__(name="qBittorrent")
        self._client: Optional[httpx.AsyncClient] = None

    # ============== 内部辅助 ==============

    def _base_url(self) -> str:
        cfg = get_config().downloader.qbittorrent
        return f"http://{cfg.host}:{cfg.port}"

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 httpx 客户端（懒加载，复用 SID Cookie）"""
        if self._client is None or self._client.is_closed:
            cfg = get_config().downloader.qbittorrent
            self._client = httpx.AsyncClient(
                base_url=self._base_url(),
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                follow_redirects=True,
                verify=cfg.verify_ssl,
            )
        return self._client

    def _map_state(self, qb_state: str) -> str:
        """将 qBittorrent 任务状态映射为统一 TaskStatus 值"""
        ts = _QB_STATE_MAP.get(qb_state)
        return ts.value if ts else TaskStatus.UNKNOWN.value

    # ============== 接口实现 ==============

    async def login(self) -> bool:
        cfg = get_config().downloader.qbittorrent
        if not cfg.enabled:
            logger.info("qBittorrent 未启用，跳过登录")
            return False
        if not cfg.username:
            logger.warning("qBittorrent 用户名为空，跳过登录")
            return False

        client = await self._get_client()
        try:
            resp = await client.post(
                "/api/v2/auth/login",
                data={
                    "username": cfg.username,
                    "password": cfg.password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            # qBittorrent 登录成功返回 "Ok."，失败返回 "Fails."
            text = (resp.text or "").strip()
            if resp.status_code == 200 and text == "Ok.":
                self._logged_in = True
                logger.info("qBittorrent 登录成功")
                return True
            logger.warning(f"qBittorrent 登录失败: status={resp.status_code} body={text}")
            return False
        except Exception as e:
            logger.error(f"qBittorrent 登录异常: {e}")
            return False

    async def add_torrent(
        self,
        torrent_url_or_magnet: str,
        download_dir: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """添加种子任务

        qBittorrent 通过 urls 字段接收磁力链或 HTTP 种子 URL。
        返回任务标识（这里返回原始 URL 作为占位 ID，因为 qBittorrent 的 add 端点不直接返回 hash）。
        """
        client = await self._get_client()
        cfg = get_config().downloader.qbittorrent
        save_path = download_dir or cfg.download_dir or ""

        data = {"urls": torrent_url_or_magnet}
        if save_path:
            data["savepath"] = save_path
        if name:
            data["rename"] = name

        try:
            resp = await client.post(
                "/api/v2/torrents/add",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            text = (resp.text or "").strip().lower()
            if resp.status_code == 200 and "ok" in text:
                # qBittorrent 成功响应为 "Ok."，但不返回 hash
                # 返回原 URL 作为占位 ID（list_tasks 时可通过 name 匹配）
                return torrent_url_or_magnet
            logger.warning(f"qBittorrent 添加种子失败: {resp.status_code} {resp.text}")
            raise RuntimeError(f"qBittorrent 添加种子失败: {resp.text}")
        except httpx.HTTPError as e:
            logger.error(f"qBittorrent 添加种子异常: {e}")
            raise

    async def list_tasks(self, status: Optional[str] = None) -> list[dict]:
        client = await self._get_client()
        params = {}
        # qBittorrent filter 选项：all/downloading/seeding/completed/paused/active/inactive/stalled/checking/error
        if status:
            unified_to_filter = {
                TaskStatus.DOWNLOADING.value: "downloading",
                TaskStatus.SEEDING.value: "seeding",
                TaskStatus.COMPLETED.value: "completed",
                TaskStatus.PAUSED.value: "paused",
                TaskStatus.ERROR.value: "error",
                TaskStatus.PENDING.value: "stalled",
            }
            params["filter"] = unified_to_filter.get(status, "all")

        try:
            resp = await client.get("/api/v2/torrents/info", params=params)
            resp.raise_for_status()
            items = resp.json() or []
            return [self._normalize_task(t) for t in items]
        except Exception as e:
            logger.error(f"qBittorrent 列任务异常: {e}")
            raise

    async def get_task(self, task_id: str) -> dict:
        client = await self._get_client()
        try:
            resp = await client.get("/api/v2/torrents/info", params={"hashes": task_id})
            resp.raise_for_status()
            items = resp.json() or []
            if not items:
                raise RuntimeError(f"qBittorrent 任务不存在: {task_id}")
            return self._normalize_task(items[0])
        except Exception as e:
            logger.error(f"qBittorrent 获取任务异常: {e}")
            raise

    async def cancel_task(self, task_id: str) -> bool:
        client = await self._get_client()
        try:
            resp = await client.post(
                "/api/v2/torrents/delete",
                data={"hashes": task_id, "deleteFiles": "false"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"qBittorrent 取消任务异常: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        client = await self._get_client()
        try:
            resp = await client.post(
                "/api/v2/torrents/pause",
                data={"hashes": task_id},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"qBittorrent 暂停任务异常: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        client = await self._get_client()
        try:
            resp = await client.post(
                "/api/v2/torrents/resume",
                data={"hashes": task_id},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"qBittorrent 恢复任务异常: {e}")
            return False

    async def get_status(self) -> dict:
        cfg = get_config().downloader.qbittorrent
        client = await self._get_client()
        version = ""
        download_speed = 0
        upload_speed = 0
        connected = False

        try:
            v_resp = await client.get("/api/v2/app/version")
            if v_resp.status_code == 200:
                version = v_resp.text.strip()
                connected = True
        except Exception as e:
            logger.warning(f"qBittorrent 获取版本失败: {e}")

        try:
            t_resp = await client.get("/api/v2/transfer/info")
            if t_resp.status_code == 200:
                info = t_resp.json() or {}
                download_speed = int(info.get("dl_info_speed", 0) or 0)
                upload_speed = int(info.get("up_info_speed", 0) or 0)
        except Exception as e:
            logger.warning(f"qBittorrent 获取传输信息失败: {e}")

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
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._started = False
        self._logged_in = False
        logger.info("qBittorrent 客户端已关闭")

    # ============== 字段标准化 ==============

    def _normalize_task(self, raw: dict) -> dict:
        """将 qBittorrent 任务字典标准化为统一格式"""
        size = int(raw.get("size", 0) or 0)
        downloaded = int(raw.get("downloaded", 0) or 0)
        progress = float(raw.get("progress", 0.0) or 0.0)
        # progress 字段是 0-1 的小数，转成百分比
        progress_pct = round(progress * 100, 2)
        eta = int(raw.get("eta", -1) or -1)
        return {
            "id": raw.get("hash", ""),
            "name": raw.get("name", ""),
            "status": self._map_state(raw.get("state", "")),
            "progress": progress_pct,
            "size": size,
            "downloaded": downloaded,
            "download_speed": int(raw.get("dlspeed", 0) or 0),
            "upload_speed": int(raw.get("upspeed", 0) or 0),
            "eta": eta,
            "save_path": raw.get("save_path", ""),
            "raw_state": raw.get("state", ""),
        }


__all__ = ["QBDownloader"]
