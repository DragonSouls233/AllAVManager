"""多来源数据手动精选修正路由 - v3.1 第五批

参考 mdc-ng 的设计，提供字段级数据精选修正能力：
- 列出影片当前所有可编辑字段及其来源
- 触发指定来源的预览刮削（不写入数据库，仅返回字段值供对比）
- 应用用户选择的字段值到数据库

支持的来源：javdb / javbus / dmm / mgstage / fancentro / manual（手动输入）
"""

import logging
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Movie

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Pydantic 模型 ==============

class FieldValue(BaseModel):
    """字段值（带来源标记）"""
    field: str
    value: Optional[Any] = None
    source: Optional[str] = None  # 来源：javdb/javbus/dmm/manual


class MovieFieldsResponse(BaseModel):
    """影片字段响应"""
    movie_id: int
    code: str
    fields: list[FieldValue] = []
    available_sources: list[str] = []


class ScrapePreviewRequest(BaseModel):
    """预览刮削请求"""
    source: str = Field(..., description="来源：javdb/javbus/dmm/mgstage")


class ScrapePreviewResponse(BaseModel):
    """预览刮削响应"""
    source: str
    success: bool
    fields: list[FieldValue] = []
    message: str = ""


class ApplyMergeRequest(BaseModel):
    """应用精选修正请求"""
    fields: list[FieldValue] = Field(..., description="要更新的字段列表")


class ApplyMergeResponse(BaseModel):
    """应用精选修正响应"""
    success: bool
    updated_fields: list[str] = []
    message: str = ""


# ============== 字段定义 ==============

# 可编辑字段及其类型
EDITABLE_FIELDS = {
    "title": {"type": "str", "label": "标题"},
    "original_title": {"type": "str", "label": "原始标题"},
    "title_jp": {"type": "str", "label": "日文标题"},
    "release_date": {"type": "str", "label": "发行日期"},
    "duration": {"type": "int", "label": "时长（分钟）"},
    "director": {"type": "str", "label": "导演"},
    "maker": {"type": "str", "label": "制作商"},
    "series": {"type": "str", "label": "系列"},
    "plot": {"type": "str", "label": "简介"},
    "plot_short": {"type": "str", "label": "短简介"},
    "genre": {"type": "str", "label": "标签（逗号分隔）"},
    "cover_url": {"type": "str", "label": "封面 URL"},
    "poster_url": {"type": "str", "label": "海报 URL"},
    "thumb_url": {"type": "str", "label": "缩略图 URL"},
    "trailer_url": {"type": "str", "label": "预告片 URL"},
    "is_uncensored": {"type": "bool", "label": "无码"},
    "is_chinese": {"type": "bool", "label": "中字"},
}

# 默认可用来源
DEFAULT_SOURCES = ["javdb", "javbus", "dmm", "mgstage", "fancentro", "manual"]


# ============== 辅助函数 ==============

def _get_field_value(movie: Movie, field: str) -> tuple[Any, Optional[str]]:
    """从 Movie 实例获取字段值和来源"""
    value = getattr(movie, field, None)
    # source 字段记录当前数据主要来源
    source = getattr(movie, "source", None) if field != "source" else None
    return value, source


def _set_field_value(movie: Movie, field: str, value: Any) -> bool:
    """设置 Movie 实例的字段值

    Returns:
        True 表示字段已变更
    """
    if field not in EDITABLE_FIELDS:
        return False

    field_type = EDITABLE_FIELDS[field]["type"]
    current = getattr(movie, field, None)

    # 类型转换
    if value is None or value == "":
        new_value = None
    elif field_type == "int":
        try:
            new_value = int(value)
        except (ValueError, TypeError):
            return False
    elif field_type == "bool":
        if isinstance(value, bool):
            new_value = value
        elif isinstance(value, str):
            new_value = value.lower() in ("true", "1", "yes", "是")
        else:
            new_value = bool(value)
    else:
        new_value = str(value)

    if current == new_value:
        return False

    setattr(movie, field, new_value)
    return True


# ============== 路由 ==============

@router.get("/{movie_id}/fields", response_model=MovieFieldsResponse)
async def get_movie_fields(
    movie_id: int,
    session: AsyncSession = Depends(get_session),
):
    """获取影片所有可编辑字段及其当前值和来源"""
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    fields = []
    for field_name in EDITABLE_FIELDS:
        value, source = _get_field_value(movie, field_name)
        fields.append(FieldValue(
            field=field_name,
            value=value,
            source=source,
        ))

    return MovieFieldsResponse(
        movie_id=movie_id,
        code=movie.code,
        fields=fields,
        available_sources=DEFAULT_SOURCES,
    )


@router.post("/{movie_id}/preview", response_model=ScrapePreviewResponse)
async def preview_scrape(
    movie_id: int,
    req: ScrapePreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """从指定来源预览刮削（不写入数据库）

    仅返回字段值供用户对比选择。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if req.source not in DEFAULT_SOURCES:
        raise HTTPException(status_code=400, detail=f"不支持的来源: {req.source}")

    if req.source == "manual":
        return ScrapePreviewResponse(
            source=req.source,
            success=True,
            fields=[],
            message="手动模式：请直接编辑字段值",
        )

    # 调用爬虫层预览刮削
    try:
        from app.crawlers import get_crawler
        crawler = get_crawler(req.source)
        if not crawler:
            return ScrapePreviewResponse(
                source=req.source,
                success=False,
                message=f"爬虫 {req.source} 未注册或未启用",
            )

        # 异步执行刮削
        result = await crawler.scrape(movie.code)
        if not result:
            return ScrapePreviewResponse(
                source=req.source,
                success=False,
                message=f"{req.source} 未找到 {movie.code}",
            )

        # 提取字段
        preview_fields = []
        for field_name in EDITABLE_FIELDS:
            value = getattr(result, field_name, None)
            if value is not None:
                preview_fields.append(FieldValue(
                    field=field_name,
                    value=value,
                    source=req.source,
                ))

        return ScrapePreviewResponse(
            source=req.source,
            success=True,
            fields=preview_fields,
            message=f"{req.source} 返回 {len(preview_fields)} 个字段",
        )

    except Exception as e:
        logger.error(f"预览刮削失败 [{req.source}] {movie.code}: {e}")
        return ScrapePreviewResponse(
            source=req.source,
            success=False,
            message=f"刮削异常: {e}",
        )


@router.post("/{movie_id}/apply", response_model=ApplyMergeResponse)
async def apply_merge(
    movie_id: int,
    req: ApplyMergeRequest,
    session: AsyncSession = Depends(get_session),
):
    """应用字段级精选修正到数据库

    仅更新传入的字段，未传入的字段保持不变。
    source="manual" 表示手动输入，其他值表示来自指定来源。
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if not req.fields:
        return ApplyMergeResponse(
            success=False,
            message="没有需要更新的字段",
        )

    updated = []
    for f in req.fields:
        if f.field not in EDITABLE_FIELDS:
            continue
        if _set_field_value(movie, f.field, f.value):
            updated.append(f.field)

    # 更新 source 字段（记录最后修改来源）
    if updated:
        last_source = req.fields[-1].source or "manual"
        try:
            setattr(movie, "source", last_source)
        except Exception:
            pass

    await session.commit()

    return ApplyMergeResponse(
        success=True,
        updated_fields=updated,
        message=f"已更新 {len(updated)} 个字段" + (f": {', '.join(updated)}" if updated else ""),
    )


@router.get("/fields-meta")
async def get_fields_meta():
    """获取可编辑字段的元信息（前端用于渲染表单）"""
    return {
        "fields": EDITABLE_FIELDS,
        "sources": DEFAULT_SOURCES,
    }
