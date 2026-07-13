"""
标签管理路由

API 端点：
- GET  /api/v1/tags           - 标签列表（支持分页、搜索、按分类筛选）
- GET  /api/v1/tags/stats     - 标签统计
- POST /api/v1/tags           - 创建标签
- POST /api/v1/tags/batch     - 批量创建标签
- PATCH /api/v1/tags/{id}     - 更新标签
- DELETE /api/v1/tags/{id}    - 删除标签
- POST /api/v1/tags/sync-from-movies - 从现有电影的 genre 字段同步标签
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import Database, get_session
from app.db.models import Tag, MovieTag, Movie

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Response Models =====

class TagResponse(BaseModel):
    """标签响应模型"""
    id: int
    name: str
    category: Optional[str] = None
    color: Optional[str] = None
    is_user: bool = False
    movie_count: int = 0

    class Config:
        from_attributes = True


class TagListResponse(BaseModel):
    """标签列表响应"""
    total: int
    items: list[TagResponse]


class TagCreateRequest(BaseModel):
    """创建标签请求"""
    name: str
    category: Optional[str] = None
    color: Optional[str] = None
    is_user: bool = False        # True=用户标签 / False=抓取标签


class TagBatchCreateRequest(BaseModel):
    """批量创建标签请求"""
    tags: list[TagCreateRequest]


class TagUpdateRequest(BaseModel):
    """更新标签请求"""
    name: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    is_user: Optional[bool] = None


# ===== API Endpoints =====

@router.get("/stats")
async def get_tag_stats(
    session: AsyncSession = Depends(get_session),
):
    """
    获取标签统计

    - 总数
    - 各分类标签数
    - 关联作品最多的标签 TOP 10
    """
    # 总数
    total = await session.scalar(select(func.count(Tag.id))) or 0

    # 各分类标签数
    category_query = (
        select(Tag.category, func.count(Tag.id).label("count"))
        .group_by(Tag.category)
        .order_by(func.count(Tag.id).desc())
    )
    result = await session.execute(category_query)
    categories = [{"category": row[0] or "未分类", "count": row[1]} for row in result.fetchall()]

    # 关联作品最多的 TOP 10
    top_query = (
        select(Tag.name, Tag.movie_count)
        .order_by(Tag.movie_count.desc())
        .limit(10)
    )
    result = await session.execute(top_query)
    top_tags = [{"name": row[0], "movie_count": row[1]} for row in result.fetchall()]

    return {
        "total": total,
        "categories": categories,
        "top_tags": top_tags,
    }


@router.get("", response_model=TagListResponse)
async def list_tags(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: Optional[str] = None,
    category: Optional[str] = None,
    is_user: Optional[bool] = Query(None, description="true=仅用户标签 / false=仅抓取标签 / null=全部"),
    session: AsyncSession = Depends(get_session),
):
    """
    获取标签列表

    - 支持搜索（按名字）
    - 支持按分类筛选
    - 支持 is_user 区分用户/抓取标签
    - 支持分页
    """
    query = select(Tag)

    if search:
        query = query.where(Tag.name.contains(search))
    if category:
        query = query.where(Tag.category == category)
    if is_user is not None:
        query = query.where(Tag.is_user.is_(is_user))

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    # 排序和分页
    query = query.order_by(Tag.movie_count.desc(), Tag.name.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    tags = result.scalars().all()

    items = [
        TagResponse(
            id=t.id, name=t.name, category=t.category,
            color=t.color, is_user=t.is_user, movie_count=t.movie_count,
        )
        for t in tags
    ]

    return TagListResponse(
        total=total or 0,
        items=items,
    )


@router.post("", response_model=TagResponse)
async def create_tag(
    body: TagCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    创建标签

    - 标签名唯一
    """
    # 检查是否已存在
    existing = await session.scalar(
        select(Tag).where(Tag.name == body.name)
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"标签 '{body.name}' 已存在")

    tag = Tag(
        name=body.name,
        category=body.category,
        color=body.color,
        is_user=body.is_user,
        movie_count=0,
    )
    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    return TagResponse(
        id=tag.id, name=tag.name, category=tag.category,
        color=tag.color, is_user=tag.is_user, movie_count=tag.movie_count,
    )


@router.post("/batch")
async def batch_create_tags(
    body: TagBatchCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    批量创建标签

    - 跳过已存在的标签
    """
    created = 0
    skipped = 0

    for item in body.tags:
        existing = await session.scalar(
            select(Tag).where(Tag.name == item.name)
        )
        if existing:
            skipped += 1
            continue

        tag = Tag(
            name=item.name,
            category=item.category,
            color=item.color,
            is_user=item.is_user,
            movie_count=0,
        )
        session.add(tag)
        created += 1

    await session.commit()

    return {
        "status": "ok",
        "created": created,
        "skipped": skipped,
    }


@router.post("/batch-tag-movies")
async def batch_tag_movies(
    data: dict,  # {"tag_id": int, "movie_ids": [int]}
    session: AsyncSession = Depends(get_session),
):
    """批量给电影打标签"""
    tag_id = data.get("tag_id")
    movie_ids = data.get("movie_ids", [])

    if not tag_id or not isinstance(tag_id, int):
        raise HTTPException(status_code=400, detail="tag_id 必须为整数")
    if not movie_ids or not isinstance(movie_ids, list):
        raise HTTPException(status_code=400, detail="movie_ids 必须为非空列表")

    # 验证标签存在
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    success_count = 0
    for movie_id in movie_ids:
        # 检查关联是否已存在
        existing = await session.scalar(
            select(MovieTag).where(
                MovieTag.movie_id == movie_id,
                MovieTag.tag_id == tag_id,
            )
        )
        if existing:
            continue

        # 创建关联
        link = MovieTag(movie_id=movie_id, tag_id=tag_id)
        session.add(link)
        success_count += 1

    # 更新 tag.movie_count
    if success_count > 0:
        tag.movie_count = (tag.movie_count or 0) + success_count

    await session.commit()

    return {
        "status": "ok",
        "tag_id": tag_id,
        "tag_name": tag.name,
        "success_count": success_count,
        "skipped_count": len(movie_ids) - success_count,
    }


@router.post("/remove-tag-movies")
async def remove_tag_from_movies(
    data: dict,  # {"tag_id": int, "movie_ids": [int]}
    session: AsyncSession = Depends(get_session),
):
    """批量移除电影的标签 - 参考 PornBoss removeTagsFromVideos"""
    tag_id = data.get("tag_id")
    movie_ids = data.get("movie_ids", [])

    if not tag_id or not isinstance(tag_id, int):
        raise HTTPException(status_code=400, detail="tag_id 必须为整数")
    if not movie_ids or not isinstance(movie_ids, list):
        raise HTTPException(status_code=400, detail="movie_ids 必须为非空列表")

    # 验证标签存在
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    removed_count = 0
    for movie_id in movie_ids:
        result = await session.execute(
            sa_delete(MovieTag).where(
                MovieTag.movie_id == movie_id,
                MovieTag.tag_id == tag_id,
            )
        )
        removed_count += result.rowcount

    # 更新 tag.movie_count
    if removed_count > 0:
        tag.movie_count = max(0, (tag.movie_count or 0) - removed_count)

    await session.commit()

    return {
        "status": "ok",
        "tag_id": tag_id,
        "tag_name": tag.name,
        "removed_count": removed_count,
    }


@router.post("/replace-tags-movies")
async def replace_tags_for_movies(
    data: dict,  # {"movie_ids": [int], "tag_ids": [int]}
    session: AsyncSession = Depends(get_session),
):
    """批量替换电影的标签 - 参考 PornBoss replaceTagsForVideos"""
    movie_ids = data.get("movie_ids", [])
    tag_ids = data.get("tag_ids", [])

    if not movie_ids or not isinstance(movie_ids, list):
        raise HTTPException(status_code=400, detail="movie_ids 必须为非空列表")
    if not isinstance(tag_ids, list):
        raise HTTPException(status_code=400, detail="tag_ids 必须为列表")

    # 验证所有标签存在
    for tag_id in tag_ids:
        tag = await session.get(Tag, tag_id)
        if not tag:
            raise HTTPException(status_code=400, detail=f"标签 {tag_id} 不存在")

    # 对每个电影：先删除所有现有关联，再创建新关联
    total_removed = 0
    total_added = 0
    for movie_id in movie_ids:
        # 删除现有关联
        result = await session.execute(
            sa_delete(MovieTag).where(MovieTag.movie_id == movie_id)
        )
        total_removed += result.rowcount

        # 创建新关联
        for tag_id in tag_ids:
            link = MovieTag(movie_id=movie_id, tag_id=tag_id)
            session.add(link)
            total_added += 1

    await session.commit()

    # 重新计算所有涉及标签的 movie_count
    movie_count_subq = (
        select(MovieTag.tag_id, func.count(MovieTag.movie_id).label("mc"))
        .group_by(MovieTag.tag_id)
        .subquery()
    )
    update_query = (
        select(Tag, func.coalesce(movie_count_subq.c.mc, 0).label("actual_count"))
        .outerjoin(movie_count_subq, Tag.id == movie_count_subq.c.tag_id)
    )
    result = await session.execute(update_query)
    for tag, actual_count in result.fetchall():
        if tag.movie_count != actual_count:
            tag.movie_count = actual_count

    await session.commit()

    return {
        "status": "ok",
        "total_removed": total_removed,
        "total_added": total_added,
    }


@router.post("/batch-delete-tags")
async def batch_delete_tags(
    data: dict,  # {"tag_ids": [int]}
    session: AsyncSession = Depends(get_session),
):
    """批量删除标签 - 参考 PornBoss deleteTagsBatch"""
    tag_ids = data.get("tag_ids", [])

    if not tag_ids or not isinstance(tag_ids, list):
        raise HTTPException(status_code=400, detail="tag_ids 必须为非空列表")

    deleted_count = 0
    for tag_id in tag_ids:
        tag = await session.get(Tag, tag_id)
        if not tag:
            continue

        # 删除关联
        await session.execute(
            sa_delete(MovieTag).where(MovieTag.tag_id == tag_id)
        )

        # 删除标签
        await session.delete(tag)
        deleted_count += 1

    await session.commit()

    return {
        "status": "ok",
        "deleted_count": deleted_count,
    }


@router.post("/sync-from-movies")
async def sync_tags_from_movies(
    session: AsyncSession = Depends(get_session),
):
    """
    从现有电影的 genre 字段同步标签（批量优化版，避免 N+1 查询导致超时）

    - 读取所有 Movie 的 genre 字段（JSON 数组或逗号分隔）
    - 批量预加载现有 Tag，缺失的批量创建
    - 批量预加载现有 MovieTag 关联，缺失的批量创建
    - 批量更新 movie_count
    """
    import json as _json
    from sqlalchemy import insert

    # 1. 获取所有电影的 genre
    result = await session.execute(
        select(Movie.id, Movie.genre).where(Movie.genre.isnot(None))
    )
    movies = result.fetchall()

    if not movies:
        return {"status": "ok", "tags_created": 0, "associations_created": 0, "associations_skipped": 0}

    # 2. 解析所有 genre，构建 movie_id -> [genre_name] 映射
    movie_genres: dict[int, list[str]] = {}
    all_genre_names: set[str] = set()
    for movie_id, genre_str in movies:
        if not genre_str or not genre_str.strip():
            continue
        genres = []
        try:
            parsed = _json.loads(genre_str)
            if isinstance(parsed, list):
                genres = [str(g).strip() for g in parsed if str(g).strip()]
            elif isinstance(parsed, str):
                genres = [parsed.strip()]
        except (_json.JSONDecodeError, ValueError, TypeError):
            genres = [g.strip() for g in genre_str.split(",") if g.strip()]
        if not genres:
            continue
        movie_genres[movie_id] = genres
        all_genre_names.update(genres)

    # 3. 批量查询现有 Tag（一次性全部加载，避免 N+1）
    existing_tags: dict[str, int] = {}
    if all_genre_names:
        tag_result = await session.execute(
            select(Tag).where(Tag.name.in_(list(all_genre_names)))
        )
        for tag in tag_result.scalars().all():
            existing_tags[tag.name] = tag.id

    # 4. 批量创建缺失的 Tag
    tags_created = 0
    missing_names = all_genre_names - set(existing_tags.keys())
    if missing_names:
        new_tags = [Tag(name=name, category="genre", movie_count=0) for name in missing_names]
        session.add_all(new_tags)
        await session.flush()  # 一次性获取所有新 tag 的 id
        for tag in new_tags:
            existing_tags[tag.name] = tag.id
        tags_created = len(new_tags)

    # 5. 批量查询现有 MovieTag 关联（一次性加载所有涉及的 movie_id）
    all_movie_ids = list(movie_genres.keys())
    existing_assocs: set[tuple[int, int]] = set()
    if all_movie_ids:
        assoc_result = await session.execute(
            select(MovieTag.movie_id, MovieTag.tag_id).where(
                MovieTag.movie_id.in_(all_movie_ids)
            )
        )
        for mid, tid in assoc_result.fetchall():
            existing_assocs.add((mid, tid))

    # 6. 批量创建缺失的 MovieTag 关联
    associations_created = 0
    associations_skipped = 0
    new_assocs = []
    for movie_id, genres in movie_genres.items():
        for genre_name in genres:
            tag_id = existing_tags.get(genre_name)
            if not tag_id:
                continue
            if (movie_id, tag_id) in existing_assocs:
                associations_skipped += 1
                continue
            new_assocs.append({"movie_id": movie_id, "tag_id": tag_id})
            existing_assocs.add((movie_id, tag_id))
            associations_created += 1

    if new_assocs:
        await session.execute(insert(MovieTag), new_assocs)

    await session.commit()

    # 7. 批量更新所有标签的 movie_count（单条 UPDATE）
    movie_count_subq = (
        select(MovieTag.tag_id, func.count(MovieTag.movie_id).label("mc"))
        .group_by(MovieTag.tag_id)
        .subquery()
    )
    update_query = (
        select(Tag, func.coalesce(movie_count_subq.c.mc, 0).label("actual_count"))
        .outerjoin(movie_count_subq, Tag.id == movie_count_subq.c.tag_id)
    )
    result = await session.execute(update_query)
    for tag, actual_count in result.fetchall():
        if tag.movie_count != actual_count:
            tag.movie_count = actual_count

    await session.commit()

    logger.info(f"标签同步完成: 创建 {tags_created} 个标签, 创建 {associations_created} 个关联, 跳过 {associations_skipped} 个已有关联")

    return {
        "status": "ok",
        "tags_created": tags_created,
        "associations_created": associations_created,
        "associations_skipped": associations_skipped,
    }


@router.patch("/{tag_id}")
async def update_tag(
    tag_id: int,
    body: TagUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    更新标签信息

    - 支持更新: name, category, color
    """
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    if body.name is not None:
        # 检查新名称是否已被占用
        existing = await session.scalar(
            select(Tag).where(Tag.name == body.name, Tag.id != tag_id)
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"标签名 '{body.name}' 已被占用")
        tag.name = body.name
    if body.category is not None:
        tag.category = body.category
    if body.color is not None:
        tag.color = body.color
    if body.is_user is not None:
        tag.is_user = bool(body.is_user)

    await session.commit()
    await session.refresh(tag)

    return {
        "status": "ok",
        "tag": TagResponse(
            id=tag.id, name=tag.name, category=tag.category,
            color=tag.color, is_user=tag.is_user, movie_count=tag.movie_count,
        ),
    }


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    删除标签

    - 同时删除 MovieTag 关联
    """
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    # 删除关联
    await session.execute(
        sa_delete(MovieTag).where(MovieTag.tag_id == tag_id)
    )

    # 删除标签
    await session.delete(tag)
    await session.commit()

    return {"status": "ok", "message": f"标签 '{tag.name}' 已删除"}
