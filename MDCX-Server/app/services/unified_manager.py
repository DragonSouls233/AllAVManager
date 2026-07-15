"""
统一下载管理器

整合 BT 下载器（qBittorrent/Transmission/Aria2）与直链下载引擎（yt-dlp/m3u8/http），
对外提供统一的任务提交和下载路径模板解析接口。

下载路径模板：
  - jav:        downloads/jav/{actor}/{code}-{title}.{ext}
  - uncensored: downloads/uncensored/{actor}/{code}-{title}.{ext}
  - fc2:        downloads/fc2/{code}-{title}.{ext}
  - chinese:    downloads/chinese/{actor}/下载视频/{title}.{ext}
  - pornhub:    downloads/pornhub/{actor}/{upload_date}-{title}.{ext}
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config.manager import get_config
from app.services.downloader_manager import downloader_manager
from app.services.download.temp_download_manager import get_download_manager
from app.services.download.download_models import DownloadResult, DownloadTask
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ============== 下载路径模板 ==============

DOWNLOAD_PATH_TEMPLATES = {
    "jav":       "downloads/jav/{actor}/{code}-{title}.{ext}",
    "uncensored": "downloads/uncensored/{actor}/{code}-{title}.{ext}",
    "fc2":       "downloads/fc2/{code}-{title}.{ext}",
    "chinese":   "downloads/chinese/{actor}/下载视频/{title}.{ext}",
    "pornhub":   "downloads/pornhub/{actor}/{upload_date}-{title}.{ext}",
}


def resolve_download_path(
    module: str,
    *,
    actor: str = "",
    code: str = "",
    title: str = "",
    upload_date: str = "",
    ext: str = "mp4",
) -> str:
    """根据模块类型和变量解析下载路径

    Args:
        module: 模块类型 (jav/uncensored/fc2/chinese/pornhub)
        actor: 演员名
        code: 番号
        title: 视频标题
        upload_date: 上传日期
        ext: 文件扩展名

    Returns:
        解析后的相对路径
    """
    template = DOWNLOAD_PATH_TEMPLATES.get(module)
    if not template:
        logger.warning(f"未找到模块 '{module}' 的路径模板，使用默认模板")
        template = "downloads/{module}/{title}.{ext}"
        return template.format(module=module, title=_sanitize_filename(title), ext=ext)

    # 安全处理各变量（移除非法文件名字符）
    safe_actor = _sanitize_filename(actor) if actor else "unknown"
    safe_code = _sanitize_filename(code) if code else "unknown"
    safe_title = _sanitize_filename(title) if title else "unknown"
    safe_date = _sanitize_filename(upload_date) if upload_date else "unknown"

    path = template.format(
        actor=safe_actor,
        code=safe_code,
        title=safe_title,
        upload_date=safe_date,
        ext=ext,
    )
    return path


def _sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符，限制长度"""
    # 移除 Windows 非法字符: \ / : * ? " < > |
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    # 限制单段长度（避免路径过长）
    MAX_SEGMENT = 120
    if len(name) > MAX_SEGMENT:
        name = name[:MAX_SEGMENT].rsplit(" ", 1)[0] if " " in name[:MAX_SEGMENT] else name[:MAX_SEGMENT]
    return name.strip() or "download"


# ============== 统一下载管理器 ==============

class UnifiedDownloadManager:
    """统一下载管理器（BT + 直链）

    整合 BT 下载器（qBittorrent/Transmission/Aria2）与直链下载引擎，
    根据 URL 类型自动选择合适的下载通道。
    """

    def __init__(self):
        self._bt_manager = downloader_manager
        self._direct_manager = get_download_manager()
        self._output_base = self._get_output_base()

    def _get_output_base(self) -> str:
        """获取下载根目录"""
        try:
            config = get_config()
            return config.get("downloader.output_dir", "./downloads")
        except Exception:
            return "./downloads"

    async def add_task(self, url: str, *, module: str = "",
                       download_type: str = "auto",
                       output_path: Optional[str] = None,
                       metadata: Optional[dict] = None) -> str:
        """添加下载任务

        Args:
            url: 下载 URL
            module: 模块类型 (jav/uncensored/fc2/chinese/pornhub)
            download_type: 下载类型 (auto/bt_magnet/direct)
            output_path: 指定输出路径（优先级高于模板）
            metadata: 附加元数据（用于路径模板填充）

        Returns:
            任务 ID
        """
        # 解析下载类型
        if download_type == "auto" or not download_type:
            download_type = self._detect_type(url)

        # 解析输出路径
        if not output_path and module:
            actor = (metadata or {}).get("actor", "")
            code = (metadata or {}).get("code", "")
            title = (metadata or {}).get("title", "")
            upload_date = (metadata or {}).get("upload_date", "")
            ext = (metadata or {}).get("ext", "mp4")
            output_path = resolve_download_path(
                module, actor=actor, code=code,
                title=title, upload_date=upload_date, ext=ext,
            )
            # 如果 output_path 是相对路径，拼接根目录
            if not os.path.isabs(output_path):
                output_path = os.path.join(self._output_base, output_path)

        if download_type in ("bt_magnet", "bt"):
            # 走 BT 下载通道
            return await self._add_bt_task(url, output_path)
        else:
            # 走直链下载通道
            return await self._add_direct_task(url, output_path, metadata)

    def _detect_type(self, url: str) -> str:
        """自动检测下载类型"""
        url_lower = url.lower().strip()
        if url_lower.startswith("magnet:") or url_lower.endswith(".torrent"):
            return "bt_magnet"
        return "direct"

    async def _add_bt_task(self, url: str, output_path: Optional[str] = None) -> str:
        """通过 BT 下载器添加任务"""
        try:
            downloader = self._bt_manager.get_active()
            if not downloader:
                logger.warning("没有激活的 BT 下载器，尝试使用第一个可用的")
                downloader = self._bt_manager.get_downloader("qbittorrent")
            if not downloader:
                raise RuntimeError("没有可用的 BT 下载器")

            if url.lower().startswith("magnet:"):
                result = await downloader.add_torrent_magnet(url, output_path)
            else:
                result = await downloader.add_torrent_file(url, output_path)
            task_id = getattr(result, "id", None) or str(hash(url))
            logger.info(f"BT 下载任务已添加: {task_id}")
            return task_id
        except Exception as e:
            logger.error(f"添加 BT 下载任务失败: {e}")
            raise

    async def _add_direct_task(self, url: str, output_path: Optional[str] = None,
                                metadata: Optional[dict] = None) -> str:
        """通过直链下载引擎添加任务"""
        try:
            manager = self._direct_manager
            task_id = await manager.submit(
                url=url,
                output_path=output_path,
                metadata=metadata,
            )
            logger.info(f"直链下载任务已添加: {task_id}")
            return task_id
        except Exception as e:
            logger.error(f"添加直链下载任务失败: {e}")
            raise

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """查询任务状态"""
        return self._direct_manager.get_task(task_id)

    def list_tasks(self) -> list[DownloadTask]:
        """列出所有直链下载任务"""
        return self._direct_manager.list_tasks()

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        return await self._direct_manager.cancel(task_id)


# ============== 全局单例 ==============

_unified_manager: Optional[UnifiedDownloadManager] = None


def get_unified_download_manager() -> UnifiedDownloadManager:
    """获取统一下载管理器单例"""
    global _unified_manager
    if _unified_manager is None:
        _unified_manager = UnifiedDownloadManager()
    return _unified_manager
