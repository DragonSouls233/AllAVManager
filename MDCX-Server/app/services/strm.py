"""STRM 文件生成服务

参考 MediaStationGo 的 STRM 生成机制：
- STRM 文件是文本文件，内容为视频流媒体 URL
- Emby/Jellyfin/Kodi 等媒体服务器扫描后会将其视为本地视频文件
- 同步生成 NFO 元数据文件，让客户端显示完整信息

目录结构示例：
    data/strm/
    ├── studio/2024/ABC-123/
    │   ├── ABC-123.strm         # 包含流媒体 URL
    │   └── ABC-123.nfo          # 包含元数据
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_session_factory
from app.db.models import Movie, Actor, MovieActor, Studio, Series
from app.services import naming
from app.services.websocket import emit_log
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def generate_strm_for_movie(
    movie: Movie,
    actors: Optional[list[str]] = None,
    studio_name: Optional[str] = None,
    series_name: Optional[str] = None,
) -> dict:
    """为单个影片生成 STRM 文件（和 NFO 文件）

    Args:
        movie: 影片对象
        actors: 演员名列表
        studio_name: 片商名
        series_name: 系列名

    Returns:
        { "ok": bool, "strm_path": str, "nfo_path": str, "skipped": bool, "error": str }
    """
    cfg = get_config().strm
    result = {"ok": False, "strm_path": "", "nfo_path": "", "skipped": False, "error": ""}

    if not movie.code:
        result["error"] = "影片番号为空"
        return result

    # 构建影片字典供命名模板使用
    movie_dict = {
        "code": movie.code,
        "title": movie.title or "",
        "original_title": movie.original_title or "",
        "title_jp": movie.title_jp or "",
        "studio": studio_name or "",
        "maker": movie.maker or "",
        "series": series_name or "",
        "director": movie.director or "",
        "release_date": movie.release_date or "",
        "rating": movie.rating or 0,
        "source": movie.source or "",
        "is_uncensored": movie.is_uncensored,
        "is_chinese": movie.is_chinese,
        "is_mosaic": movie.is_mosaic,
    }

    # 计算输出路径
    output_root = Path(cfg.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    if cfg.use_directory_template:
        naming_cfg = get_config().naming
        dir_path = naming.render_dirpath(naming_cfg.dir_template, movie_dict, actors)
        sub_dir = output_root / dir_path
    else:
        sub_dir = output_root

    sub_dir.mkdir(parents=True, exist_ok=True)

    # 生成 STRM 文件
    strm_filename = naming.render_filename(
        get_config().naming.file_template,
        movie_dict,
        actors,
        extension="strm",
    )
    strm_path = sub_dir / strm_filename

    # 检查是否已存在
    if strm_path.exists() and not cfg.overwrite:
        result["skipped"] = True
        result["strm_path"] = str(strm_path)
        return result

    # 生成流媒体 URL
    stream_url = cfg.url_template.format(id=movie.id)

    try:
        with open(strm_path, "w", encoding="utf-8") as f:
            f.write(stream_url)
        result["strm_path"] = str(strm_path)
    except Exception as e:
        result["error"] = f"写入 STRM 失败: {e}"
        return result

    # 同步生成 NFO 文件
    if cfg.generate_nfo:
        nfo_filename = naming.render_filename(
            get_config().naming.file_template,
            movie_dict,
            actors,
            extension="nfo",
        )
        nfo_path = sub_dir / nfo_filename
        try:
            nfo_content = _build_nfo_content(movie, actors or [], studio_name, series_name)
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write(nfo_content)
            result["nfo_path"] = str(nfo_path)
        except Exception as e:
            logger.warning(f"生成 NFO 失败: {e}")

    result["ok"] = True
    return result


def _build_nfo_content(
    movie: Movie,
    actors: list[str],
    studio: Optional[str] = None,
    series: Optional[str] = None,
) -> str:
    """构建 NFO 文件内容（兼容 Emby/Jellyfin/Kodi 格式）"""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<movie>"]

    parts.append(f"  <title>{escape(movie.title or movie.code)}</title>")
    if movie.original_title:
        parts.append(f"  <originaltitle>{escape(movie.original_title)}</originaltitle>")
    if movie.title_jp:
        parts.append(f"  <sorttitle>{escape(movie.title_jp)}</sorttitle>")

    parts.append(f"  <id>{escape(movie.code)}</id>")
    parts.append(f"  <uniqueid type=\"number\" default=\"true\">{escape(movie.code)}</uniqueid>")

    if studio:
        parts.append(f"  <studio>{escape(studio)}</studio>")
    if movie.maker:
        parts.append(f"  <maker>{escape(movie.maker)}</maker>")
    if series:
        parts.append(f"  <set>{escape(series)}</set>")
    if movie.director:
        parts.append(f"  <director>{escape(movie.director)}</director>")

    if movie.release_date:
        parts.append(f"  <premiered>{escape(movie.release_date)}</premiered>")
        parts.append(f"  <releasedate>{escape(movie.release_date)}</releasedate>")

    if movie.duration:
        parts.append(f"  <runtime>{movie.duration}</runtime>")

    if movie.plot:
        parts.append(f"  <plot>{escape(movie.plot)}</plot>")
        parts.append(f"  <outline>{escape(movie.plot[:200] if movie.plot else '')}</outline>")

    if movie.rating:
        parts.append(f"  <rating>{float(movie.rating):.1f}</rating>")

    if movie.is_uncensored:
        parts.append("  <tag>无码</tag>")
    if movie.is_chinese:
        parts.append("  <tag>国产</tag>")

    parts.append(f"  <source>{escape(movie.source or '')}</source>")

    # 演员列表
    for actor_name in actors:
        parts.append(f"  <actor>")
        parts.append(f"    <name>{escape(actor_name)}</name>")
        parts.append(f"  </actor>")

    parts.append(f"  <added>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</added>")
    parts.append("</movie>")

    return "\n".join(parts)


async def generate_strm_batch(
    movie_ids: Optional[list[int]] = None,
    overwrite: Optional[bool] = None,
    task_id: str = "strm-gen",
) -> dict:
    """批量生成 STRM 文件

    Args:
        movie_ids: 指定影片 ID 列表，None 表示所有影片
        overwrite: 是否覆盖已存在文件，None 使用配置
        task_id: 任务 ID（用于日志推送）

    Returns:
        { "total": int, "success": int, "skipped": int, "failed": int, "errors": list }
    """
    if overwrite is None:
        overwrite = get_config().strm.overwrite

    factory = get_session_factory()
    total = success = skipped = failed = 0
    errors = []

    await emit_log("INFO", "开始批量生成 STRM 文件", task_id=task_id, module="strm")

    async with factory() as session:
        # 查询影片
        query = select(Movie)
        if movie_ids:
            query = query.where(Movie.id.in_(movie_ids))
        query = query.order_by(Movie.id)

        result = await session.execute(query)
        movies = result.scalars().all()
        total = len(movies)

        await emit_log(
            "INFO",
            f"待处理影片 {total} 部",
            task_id=task_id,
            module="strm",
        )

        for idx, movie in enumerate(movies, 1):
            try:
                # 查询演员
                actors_result = await session.execute(
                    select(Actor.name)
                    .join(MovieActor, MovieActor.actor_id == Actor.id)
                    .where(MovieActor.movie_id == movie.id)
                )
                actors = [r[0] for r in actors_result.fetchall()]

                # 查询片商
                studio_name = None
                if movie.studio_id:
                    studio_obj = await session.get(Studio, movie.studio_id)
                    studio_name = studio_obj.name if studio_obj else None

                # 查询系列
                series_name = None
                if movie.series_id:
                    series_obj = await session.get(Series, movie.series_id)
                    series_name = series_obj.name if series_obj else None

                # 临时覆盖配置
                if overwrite is not None:
                    cfg = get_config()
                    original = cfg.strm.overwrite
                    cfg.strm.overwrite = overwrite

                r = await generate_strm_for_movie(movie, actors, studio_name, series_name)

                # 还原配置
                if overwrite is not None:
                    cfg.strm.overwrite = original

                if r["skipped"]:
                    skipped += 1
                elif r["ok"]:
                    success += 1
                else:
                    failed += 1
                    errors.append({"movie_id": movie.id, "code": movie.code, "error": r["error"]})

                if idx % 20 == 0 or idx == total:
                    await emit_log(
                        "DEBUG",
                        f"进度: {idx}/{total} · 成功 {success} / 跳过 {skipped} / 失败 {failed}",
                        task_id=task_id,
                        module="strm",
                    )

            except Exception as e:
                failed += 1
                errors.append({"movie_id": movie.id, "code": movie.code, "error": str(e)})
                logger.exception(f"影片 {movie.code} STRM 生成失败")

    summary = f"STRM 生成完成 · 成功 {success} / 跳过 {skipped} / 失败 {failed} / 总计 {total}"
    await emit_log(
        "SUCCESS" if failed == 0 else "WARNING",
        summary,
        task_id=task_id,
        module="strm",
    )

    return {
        "total": total,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:50],  # 限制错误列表长度
    }


async def cleanup_strm_files() -> dict:
    """清理 STRM 输出目录（删除所有 .strm 和 .nfo 文件）"""
    cfg = get_config().strm
    output_dir = Path(cfg.output_dir)
    if not output_dir.exists():
        return {"deleted_strm": 0, "deleted_nfo": 0}

    deleted_strm = 0
    deleted_nfo = 0

    for p in output_dir.rglob("*"):
        if p.is_file():
            if p.suffix == ".strm":
                try:
                    p.unlink()
                    deleted_strm += 1
                except Exception:
                    pass
            elif p.suffix == ".nfo":
                try:
                    p.unlink()
                    deleted_nfo += 1
                except Exception:
                    pass

    # 删除空目录
    for p in sorted(output_dir.rglob("*"), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            try:
                p.rmdir()
            except Exception:
                pass

    return {"deleted_strm": deleted_strm, "deleted_nfo": deleted_nfo}


def get_strm_statistics() -> dict:
    """获取 STRM 目录统计信息"""
    cfg = get_config().strm
    output_dir = Path(cfg.output_dir)
    if not output_dir.exists():
        return {"total_strm": 0, "total_nfo": 0, "total_size_kb": 0, "output_dir": str(output_dir)}

    total_strm = total_nfo = 0
    total_size = 0

    for p in output_dir.rglob("*"):
        if p.is_file():
            if p.suffix == ".strm":
                total_strm += 1
            elif p.suffix == ".nfo":
                total_nfo += 1
            total_size += p.stat().st_size

    return {
        "total_strm": total_strm,
        "total_nfo": total_nfo,
        "total_size_kb": round(total_size / 1024, 2),
        "output_dir": str(output_dir),
    }
