"""
NFO 免改名半自动刮削路由（C9）

提供目录扫描、单文件解析、预览功能。前缀 /nfo-scrape。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services.nfo_scraper import import_to_db, parse_nfo, scan_directory

router = APIRouter()
logger = logging.getLogger(__name__)


class ScanDirRequest(BaseModel):
    """扫描目录请求"""
    model_config = ConfigDict(extra="forbid")

    dir_path: str = Field(..., description="要扫描的目录绝对路径")
    recursive: bool = Field(default=True, description="是否递归扫描子目录")


class ScrapeFileRequest(BaseModel):
    """单个 NFO 文件导入请求"""
    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(..., description="NFO 文件绝对路径")


@router.post("/scan-dir")
async def scan_dir(
    payload: ScanDirRequest,
    session: AsyncSession = Depends(get_session),
):
    """扫描目录中所有 .nfo 文件

    返回解析结果列表（不会自动导入数据库，需调用 /scrape-file 或单独触发导入）。
    """
    try:
        results = scan_directory(payload.dir_path, recursive=payload.recursive)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotADirectoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"扫描目录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描目录失败: {e}")

    return {
        "total": len(results),
        "items": results,
    }


@router.post("/scrape-file")
async def scrape_file(
    payload: ScrapeFileRequest,
    session: AsyncSession = Depends(get_session),
):
    """解析单个 NFO 文件并导入数据库

    若影片已存在则仅补全缺失字段，不重复创建。
    """
    try:
        nfo_data = parse_nfo(payload.file_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"解析 NFO 文件失败 {payload.file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"NFO 解析失败: {e}")

    if not nfo_data.get("code"):
        raise HTTPException(status_code=400, detail="NFO 文件中未找到番号，无法导入")

    try:
        result = await import_to_db(nfo_data, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"导入数据库失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")

    return {
        "status": "ok",
        "nfo_format": nfo_data.get("nfo_format"),
        **result,
    }


@router.get("/preview/{file_path:path}")
async def preview_nfo(file_path: str):
    """预览 NFO 解析结果（不导入数据库）

    file_path 为 NFO 文件的绝对路径（URL 编码后会自动解码）。
    """
    try:
        nfo_data = parse_nfo(file_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"预览 NFO 解析失败 {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"NFO 解析失败: {e}")

    return nfo_data
