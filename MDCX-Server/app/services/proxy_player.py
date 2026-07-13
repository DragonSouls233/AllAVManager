"""
302 反代播放服务

- CloudDrive2 视频:获取流式 URL 后 302 重定向(不消耗服务器带宽)
- 115 网盘视频:通过 pickcode 获取直链后 302 重定向
- 本地文件:返回 None,路由层回退到本地流媒体端点

设计说明:
- CloudDrive2 的 get_stream_url 为同步方法,直接返回 /Api/fs/Redirect/{path} 形式的重定向 URL
- 115 网盘 get_download_url 接收 pickcode(非路径),需从 movie.file_path 中解析
  支持格式:115:pickcode=XXX / 115:XXX / 115:pickcode:XXX
- 复用全局单例 cloud_drive2_client / pan_115_client,不新建实例
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Movie
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ProxyPlayerService:
    """302 反代播放服务"""

    async def get_play_url(self, movie_id: int, session: AsyncSession) -> Optional[str]:
        """获取影片播放 URL(用于 302 重定向)

        Args:
            movie_id: 影片 ID
            session: 数据库会话

        Returns:
            可重定向的播放 URL;本地文件或无可用源时返回 None
        """
        movie = await session.get(Movie, movie_id)
        if not movie:
            return None

        file_path = movie.file_path or ""

        # 1. CloudDrive2 网盘路径
        if file_path and self._is_cloud_drive2_path(file_path):
            try:
                from app.services.cloud_drive2 import cloud_drive2_client

                if not cloud_drive2_client._token:
                    await cloud_drive2_client.start()
                # get_stream_url 为同步方法,直接构造重定向 URL
                url = cloud_drive2_client.get_stream_url(file_path)
                if url:
                    logger.info(
                        f"CD2 302 重定向: movie_id={movie_id}, path={file_path}"
                    )
                    return url
            except Exception as e:
                logger.warning(f"CloudDrive2 获取直链失败: {e}")

        # 2. 115 网盘路径
        if file_path and self._is_115_path(file_path):
            pickcode = self._extract_115_pickcode(file_path)
            if not pickcode:
                logger.warning(
                    f"115 路径无法解析 pickcode,跳过 302: movie_id={movie_id}, "
                    f"path={file_path}"
                )
            else:
                try:
                    from app.services.pan_115 import pan_115_client

                    if not pan_115_client.is_logged_in:
                        await pan_115_client.start()
                    result = await pan_115_client.get_download_url(pickcode)
                    url = result.get("url") if result else None
                    if url:
                        logger.info(
                            f"115 302 重定向: movie_id={movie_id}, pickcode={pickcode}"
                        )
                        return url
                except Exception as e:
                    logger.warning(f"115 网盘获取直链失败: {e}")

        # 3. 已有 HTTP(S) 直链(source_url)
        if movie.source_url and movie.source_url.startswith(("http://", "https://")):
            logger.info(f"使用 source_url 重定向: movie_id={movie_id}")
            return movie.source_url

        # 4. 本地文件:返回 None,由路由层回退到本地流媒体端点
        if file_path and not file_path.startswith(("http://", "https://")):
            logger.debug(f"本地播放回退: movie_id={movie_id}, path={file_path}")
            return None

        return None

    def _is_cloud_drive2_path(self, path: str) -> bool:
        """判断是否为 CloudDrive2 路径"""
        return path.startswith("/CloudDrive2/") or path.startswith("CloudDrive2:")

    def _is_115_path(self, path: str) -> bool:
        """判断是否为 115 网盘路径"""
        return path.startswith("/115/") or path.startswith("115:")

    def _extract_115_pickcode(self, path: str) -> Optional[str]:
        """从 115 路径中提取 pickcode

        支持格式:
        - 115:pickcode=XXXX
        - 115:pickcode:XXXX
        - 115:XXXX  (裸 pickcode,要求非空且不含 / )

        Returns:
            pickcode 字符串;无法解析时返回 None
        """
        if not path.startswith("115:"):
            # /115/... 形式的路径无法直接得到 pickcode
            return None
        body = path[len("115:"):].strip()
        if not body:
            return None
        # 115:pickcode=XXXX
        if body.startswith("pickcode="):
            return body[len("pickcode="):].strip() or None
        # 115:pickcode:XXXX
        if body.startswith("pickcode:"):
            return body[len("pickcode:"):].strip() or None
        # 115:XXXX (裸 pickcode,不能包含路径分隔符)
        if "/" in body or "\\" in body:
            return None
        return body


proxy_player_service = ProxyPlayerService()

__all__ = ["proxy_player_service", "ProxyPlayerService"]
