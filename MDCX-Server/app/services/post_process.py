"""
下载后处理管道

下载完成后执行：
  1. 文件移动到 {actor}/下载视频/（按路径模板）
  2. 触发刮削（各模块对应刮削引擎）
  3. 生成 NFO 文件（Jellyfin/Emby 兼容）
  4. 更新演员统计（play_count、last_downloaded_at）
  5. 通知前端刷新
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config.manager import get_config
from app.services.download.download_models import DownloadResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_post_process(
    result: DownloadResult,
    *,
    module: str = "",
    actor: str = "",
) -> dict:
    """执行下载后处理管道

    Args:
        result: 下载结果
        module: 模块类型 (jav/uncensored/fc2/chinese/pornhub)
        actor: 演员名

    Returns:
        处理结果摘要
    """
    summary = {"file_moved": False, "scraped": False, "nfo_generated": False, "actor_updated": False}
    config = _get_post_process_config()

    file_path = result.file_path
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"下载文件不存在，跳过后续处理: {file_path}")
        return summary

    # 1. 文件移动
    if config.get("move_to_media_dir", True) and module and actor:
        try:
            new_path = _move_to_actor_dir(file_path, module=module, actor=actor, title=result.title)
            if new_path:
                result.file_path = new_path
                summary["file_moved"] = True
                logger.info(f"文件已移动到: {new_path}")
        except Exception as e:
            logger.error(f"文件移动失败: {e}")

    # 2. 触发刮削
    if config.get("scrape_after_download", True):
        try:
            await _trigger_scrape(result, module=module)
            summary["scraped"] = True
        except Exception as e:
            logger.error(f"下载后刮削失败: {e}")

    # 3. 生成 NFO
    if config.get("nfo_after_download", True):
        try:
            await _generate_nfo(result, module=module, actor=actor)
            summary["nfo_generated"] = True
        except Exception as e:
            logger.error(f"NFO 生成失败: {e}")

    # 4. 更新演员统计
    if module and actor:
        try:
            await _update_actor_stats(module=module, actor=actor)
            summary["actor_updated"] = True
        except Exception as e:
            logger.error(f"更新演员统计失败: {e}")

    # 5. 通知前端刷新（通过 WebSocket）
    try:
        await _notify_frontend(module, actor)
    except Exception as e:
        logger.debug(f"前端通知失败（非关键）: {e}")

    return summary


def _get_post_process_config() -> dict:
    """获取后处理配置"""
    try:
        config = get_config()
        return config.get("downloader.post_process", {})
    except Exception:
        return {}


def _move_to_actor_dir(
    file_path: str,
    *,
    module: str,
    actor: str,
    title: Optional[str] = None,
) -> Optional[str]:
    """将文件移动到演员目录

    按路径模板规则移动文件：
      chinese: downloads/chinese/{actor}/下载视频/{title}.{ext}
      其他:    downloads/{module}/{actor}/{title}.{ext}
    """
    src = Path(file_path)
    if not src.exists():
        return None

    try:
        config = get_config()
        output_base = config.get("downloader.output_dir", "./downloads")
    except Exception:
        output_base = "./downloads"

    # 构建目标文件夹路径
    if module == "chinese":
        target_dir = Path(output_base) / "chinese" / _sanitize_dirname(actor) / "下载视频"
    else:
        target_dir = Path(output_base) / module / _sanitize_dirname(actor)

    target_dir.mkdir(parents=True, exist_ok=True)

    # 确定目标文件名
    stem = src.stem
    if title:
        safe_title = _sanitize_dirname(title)
        if len(safe_title) > 80:
            safe_title = safe_title[:80]
        stem = safe_title
    target_path = target_dir / f"{stem}{src.suffix}"

    # 避免覆盖
    counter = 1
    while target_path.exists():
        target_path = target_dir / f"{stem}_{counter}{src.suffix}"
        counter += 1

    # 移动文件
    os.renames(str(src), str(target_path))
    return str(target_path)


def _sanitize_dirname(name: str) -> str:
    """清理目录名"""
    import re
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    return name.strip() or "unknown"


async def _trigger_scrape(result: DownloadResult, *, module: str = "") -> None:
    """触发刮削（骨架方法，后续可对接具体刮削引擎）"""
    file_path = result.file_path
    if not file_path:
        return
    logger.info(f"[{module}] 触发下载后刮削: {file_path}")
    # TODO: 对接各模块刮削引擎
    #   JAV → jav_scanner 或直接调用 engine.py
    #   chinese → chinese_scanner + folder_actor
    #   pornhub → pornhub_scanner
    #   fc2 → fc2_scanner
    #   uncensored → uncensored_scanner


async def _generate_nfo(result: DownloadResult, *, module: str = "", actor: str = "") -> None:
    """生成 NFO 文件（骨架方法）"""
    file_path = result.file_path
    if not file_path:
        return
    logger.info(f"[{module}] 生成 NFO: {file_path}")
    # TODO: 调用 NFO 生成服务


async def _update_actor_stats(*, module: str, actor: str) -> None:
    """更新演员下载统计"""
    logger.info(f"[{module}] 更新演员统计: {actor}")
    # TODO: 对接数据库更新 play_count、last_downloaded_at


async def _notify_frontend(module: str, actor: str) -> None:
    """通知前端刷新"""
    try:
        from app.services.websocket import manager as ws_manager
        await ws_manager.broadcast({
            "type": "download_complete",
            "module": module,
            "actor": actor,
        })
    except ImportError:
        pass  # WebSocket 未启用，静默跳过
    except Exception as e:
        logger.debug(f"WebSocket 通知失败: {e}")
