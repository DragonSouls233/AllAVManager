"""CloudDrive2 客户端服务

对接 CloudDrive2 服务器的 gRPC-Web / HTTP API，用于：
- 浏览云端文件系统（115、阿里云盘、百度网盘等聚合挂载）
- 流式播放云端视频
- 批量扫描云端目录并导入到本地数据库

CloudDrive2 项目：https://github.com/cloud-fs/cloud-fs-website

实现要点：
1. 登录：POST /Api/Auth/Login，返回 JWT token
2. 列目录：POST /Api/fs/ListWithRemotePath，返回文件列表
3. 文件信息：POST /Api/fs/GetFullInfoWithRemotePath
4. 流式 URL：直接通过 /Api/fs/Redirect/{filePath} 重定向到真实下载 URL

参考 webdav_client.py 的实现风格。
"""

import asyncio
import logging
import os
from typing import Optional
from urllib.parse import quote

import httpx

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# CloudDrive2 默认端口
DEFAULT_PORT = 19798
# 请求超时（秒）
DEFAULT_TIMEOUT = 30


class CloudDrive2Client:
    """CloudDrive2 客户端

    通过 HTTP API 与 CloudDrive2 服务交互。
    生命周期由 app.main lifespan 管理。
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._started: bool = False
        self._last_login_at: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 httpx 客户端（懒加载）"""
        if self._client is None or self._client.is_closed:
            cfg = get_config().cloud_drive2
            base_url = cfg.url.rstrip("/")
            self._client = httpx.AsyncClient(
                base_url=base_url,
                timeout=cfg.timeout,
                follow_redirects=True,
            )
        return self._client

    async def start(self) -> None:
        """启动客户端（在 lifespan 中调用）"""
        cfg = get_config().cloud_drive2
        if not cfg.enabled:
            logger.info("CloudDrive2 未启用，跳过启动")
            return

        # 预先建立连接并尝试登录
        try:
            await self.login()
            self._started = True
            logger.info(f"CloudDrive2 客户端已就绪: {cfg.url}")
        except Exception as e:
            logger.warning(f"CloudDrive2 登录失败（仍可使用匿名访问）: {e}")
            self._started = True  # 即使登录失败也标记为已启动，允许尝试匿名访问

    async def close(self) -> None:
        """关闭客户端（在 lifespan 中调用）"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        self._token = None
        self._started = False
        logger.info("CloudDrive2 客户端已关闭")

    @property
    def is_started(self) -> bool:
        return self._started

    def _get_headers(self) -> dict:
        """获取请求头（含认证 token）"""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def login(self) -> bool:
        """登录 CloudDrive2 获取 token

        Returns:
            True 登录成功，False 失败
        """
        cfg = get_config().cloud_drive2
        if not cfg.username or not cfg.password:
            logger.debug("CloudDrive2 未配置用户名/密码，跳过登录")
            return False

        client = await self._get_client()
        try:
            resp = await client.post(
                "/Api/Auth/Login",
                json={
                    "username": cfg.username,
                    "password": cfg.password,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token") or data.get("access_token")
            if token:
                self._token = token
                import time
                self._last_login_at = time.time()
                logger.info("CloudDrive2 登录成功")
                return True
            logger.warning(f"CloudDrive2 登录响应未包含 token: {data}")
            return False
        except Exception as e:
            logger.error(f"CloudDrive2 登录失败: {e}")
            return False

    async def list_dir(self, path: str) -> dict:
        """列出云端目录下的文件

        Args:
            path: 云端路径（如 /115/movies）

        Returns:
            {
                "path": "/115/movies",
                "items": [
                    {"name": "...", "is_dir": True, "size": 0, "full_path": "/115/movies/..."},
                    ...
                ],
                "total": N,
            }
        """
        client = await self._get_client()
        try:
            # CloudDrive2 API：POST /Api/fs/ListWithRemotePath
            # Body: {"path": "/path", "limit": 0, "next_page_token": ""}
            resp = await client.post(
                "/Api/fs/ListWithRemotePath",
                json={
                    "path": path,
                    "limit": 0,
                    "next_page_token": "",
                },
                headers=self._get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # 解析返回的文件列表
            file_list = data.get("file_list", {})
            items_raw = file_list.get("items", []) or []

            items = []
            for item in items_raw:
                name = item.get("name", "")
                full_path = path.rstrip("/") + "/" + name if name else path
                items.append({
                    "name": name,
                    "full_path": full_path,
                    "is_dir": item.get("is_dir", False),
                    "size": item.get("size", 0),
                    "modified_at": item.get("modified_at", ""),
                    "file_extension": item.get("file_extension", ""),
                })

            return {
                "path": path,
                "items": items,
                "total": len(items),
            }

        except httpx.HTTPStatusError as e:
            logger.warning(f"CloudDrive2 列目录失败 {path}: HTTP {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"CloudDrive2 列目录异常 {path}: {e}")
            raise

    async def get_file_info(self, path: str) -> dict:
        """获取云端文件详情

        Args:
            path: 云端文件路径

        Returns:
            文件详情字典
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                "/Api/fs/GetFullInfoWithRemotePath",
                json={"remote_path": path},
                headers=self._get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("full_info", data)
        except Exception as e:
            logger.error(f"CloudDrive2 获取文件信息失败 {path}: {e}")
            raise

    def get_stream_url(self, path: str) -> str:
        """获取流式播放 URL

        CloudDrive2 通过 /Api/fs/Redirect/{path} 重定向到真实下载 URL。
        该 URL 可直接用于播放器（mpv / HTML5 video）。

        Args:
            path: 云端文件路径

        Returns:
            可直接播放的 URL
        """
        cfg = get_config().cloud_drive2
        base = cfg.url.rstrip("/")
        encoded = quote(path, safe="")
        url = f"{base}/Api/fs/Redirect/{encoded}"
        # 如果有 token，附加为查询参数
        if self._token:
            url += f"?token={self._token}"
        return url

    async def scan_directory(
        self,
        path: str,
        recursive: bool = True,
        max_depth: int = 5,
    ) -> list[dict]:
        """扫描云端目录下的所有视频文件

        Args:
            path: 起始路径
            recursive: 是否递归扫描子目录
            max_depth: 最大递归深度

        Returns:
            视频文件列表 [{"path": "...", "name": "...", "size": N}, ...]
        """
        cfg = get_config().cloud_drive2
        video_exts = {ext.lower() for ext in cfg.video_extensions}

        results: list[dict] = []
        seen_paths: set[str] = set()

        async def _scan(current_path: str, depth: int) -> None:
            if depth > max_depth:
                return
            if current_path in seen_paths:
                return
            seen_paths.add(current_path)

            try:
                listing = await self.list_dir(current_path)
            except Exception as e:
                logger.warning(f"扫描 {current_path} 失败: {e}")
                return

            for item in listing.get("items", []):
                if item["is_dir"]:
                    if recursive:
                        await _scan(item["full_path"], depth + 1)
                else:
                    ext = (item.get("file_extension") or "").lower()
                    if not ext and item["name"]:
                        _, ext = os.path.splitext(item["name"])
                        ext = ext.lower()
                    if ext in video_exts:
                        results.append({
                            "path": item["full_path"],
                            "name": item["name"],
                            "size": item.get("size", 0),
                            "modified_at": item.get("modified_at", ""),
                        })

        await _scan(path, 0)
        logger.info(f"CloudDrive2 扫描 {path} 完成: 找到 {len(results)} 个视频文件")
        return results

    async def get_status(self) -> dict:
        """获取 CloudDrive2 连接状态"""
        cfg = get_config().cloud_drive2
        return {
            "enabled": cfg.enabled,
            "url": cfg.url,
            "started": self._started,
            "logged_in": self._token is not None,
            "has_credentials": bool(cfg.username and cfg.password),
            "base_path": cfg.base_path,
        }


# 全局单例
cloud_drive2_client = CloudDrive2Client()

__all__ = ["cloud_drive2_client", "CloudDrive2Client"]
