# -*- coding: utf-8 -*-
"""
演员表清理重建服务

背景：历史原因导致 actors 表被污染，常见污染源：
1. 素人企划影片的 actor 字段写入"标题式垃圾名"（长描述 / 按钮文案 / HTML 碎片），被当演员收进表
2. 刮削器把「画像を拡大する」「<img」「<i」等按钮文案 / HTML 标签当演员名
3. 素人映射公司名（amateur_prefix_map 的 value）被当作演员
4. 多演员半角逗号串（如「葵つかさ,あおいれな」）被当作单个演员名
5. 大量孤儿演员（movie_count=0 且无头像 / 资料 / 别名 / 标签 / 订阅 / 分级）

方案（用户已确认：精准清理 + 素人走公司名映射）：
1. 备份模块数据库
2. 精准识别垃圾演员并删除——保留有头像 / 资料 / 别名 / 标签 / 订阅 / 作品>=1 的正常演员
3. 素人目录影片 actor 置空 → 展示时按 amateur_prefix_map 映射公司名
4. 从 movies.actor 重新同步生成演员表（复用 module_actor_sync）
5. 支持 dry_run 预览（先看会删哪些，再实际执行）
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

# 刮削器把按钮文案当演员名的已知特征
_UI_TEXT_NAMES = {"画像を拡大する", "クリックして拡大", "拡大する"}


def is_garbage_actor_name(name: str, company_names: set[str]) -> Optional[str]:
    """判定演员名是否垃圾，返回垃圾原因；正常名字返回 None

    规则（满足任一即垃圾）：
    - HTML 碎片（含 < > &）
    - 已知刮削按钮文案
    - 素人映射公司名
    - 标题式长垃圾（长度>=12 且含 / 或 ！！ 或方括号——素人企划标题文本特征）
    - 多演员半角逗号串（actor 字段多演员被误存为单个名字）
    """
    if not name:
        return "空名"
    n = name.strip()
    if "<" in n or ">" in n or "&" in n:
        return "HTML碎片"
    if n in _UI_TEXT_NAMES:
        return "刮削按钮文案"
    if n in company_names:
        return "素人映射公司名"
    if len(n) >= 12 and ("/" in n or "！" in n or "!!" in n or "。" in n or "！" in n):
        return "标题式垃圾名"
    if "[" in n and "]" in n:
        return "标题式垃圾名"
    if "," in n:
        return "多演员逗号串"
    return None


def _in_amateur_dir(file_path: str, amateur_dirs: list[str]) -> bool:
    """判断影片是否位于素人专属目录中

    纯字符串路径前缀匹配（normcase/normpath），不做任何文件系统访问——
    影片 file_path 多为网络盘路径，resolve() 会逐文件打开句柄导致极慢。
    """
    if not file_path:
        return False
    fp = os.path.normcase(os.path.normpath(file_path))
    for d in amateur_dirs:
        if not d:
            continue
        base = os.path.normcase(os.path.normpath(d))
        if fp == base or fp.startswith(base + os.sep):
            return True
    return False


def _sanitize_movie_actor(actor_text: Optional[str], company_names: set[str]) -> tuple[Optional[str], bool]:
    """解析影片 actor 文本并剔除垃圾名，返回 (新文本, 是否变更)

    仅在存在垃圾名时才改写；正常文本原样保留。
    多演员逗号串（如「葵つかさ,あおいれな」）由 parse_actor_names 拆成多个合法名，
    同步重建时自然生成独立演员，无需在此处理。
    """
    if not actor_text or not actor_text.strip():
        return actor_text, False
    from app.scraper.module_actor_sync import parse_actor_names

    names = parse_actor_names(actor_text)
    if not names:
        return actor_text, False
    valid = [n for n in names if not is_garbage_actor_name(n, company_names)]
    if len(valid) == len(names):
        return actor_text, False  # 无垃圾名，保持原样
    new_text = ", ".join(valid) if valid else None
    return new_text, True


def _backup_db(db_path: str) -> str:
    """备份模块数据库到 backups 目录"""
    src = Path(db_path)
    backup_dir = src.parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / f"{src.stem}_actor_cleanup_{stamp}.db"
    shutil.copy2(src, dst)
    return str(dst)


async def preview_actor_cleanup(
    module: str = "jav",
    amateur_dirs: Optional[list[str]] = None,
    company_names: Optional[set[str]] = None,
) -> dict:
    """dry-run：只统计不修改，返回将被清理的演员明细与素人影片数"""
    from app.utils.module_helper import get_module_model, get_module_session
    from app.config.manager import get_config

    ActorModel = get_module_model(module, "actor")
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    # 素人配置兜底
    if amateur_dirs is None or company_names is None:
        try:
            cfg = get_config()
            jav_cfg = cfg.modules.jav
            amateur_dirs = amateur_dirs or list(getattr(jav_cfg, "amateur_media_dirs", None) or [])
            company_names = company_names or set((getattr(jav_cfg, "amateur_prefix_map", None) or {}).values())
        except Exception:
            amateur_dirs = amateur_dirs or []
            company_names = company_names or set()

    try:
        actors = (await session.execute(select(ActorModel))).scalars().all()

        # 预取每部影片，统计素人目录影片数与 actor 文本
        movies = (await session.execute(select(MovieModel))).scalars().all()
        amateur_movie_ids = {
            m.id for m in movies if _in_amateur_dir(m.file_path or "", amateur_dirs)
        }
        # 非素人影片中解析出的全部演员名（孤儿防误删防线：名字出现在影片中则保留）
        from app.scraper.module_actor_sync import parse_actor_names

        non_amateur_names: set[str] = set()
        # 非素人影片中 actor 字段含垃圾名（需要清洗，否则重建会重新生成垃圾演员）
        movies_garbage_actor = 0
        for m in movies:
            if m.id in amateur_movie_ids:
                continue
            non_amateur_names.update(parse_actor_names(m.actor or ""))
            _, changed = _sanitize_movie_actor(m.actor, company_names)
            if changed:
                movies_garbage_actor += 1

        garbage = []      # 垃圾名演员
        orphan = []       # 孤儿演员（无作品且无任何附加数据）
        kept_assets = 0   # 有附加数据而保留的
        for a in actors:
            reason = is_garbage_actor_name(a.name or "", company_names)
            if reason:
                garbage.append({"id": a.id, "name": a.name, "movie_count": a.movie_count or 0, "reason": reason})
                continue
            # 无作品判定：movie_count 列 + 影片 actor 文本倒排 + 附加数据兜底
            has_assets = any([
                a.avatar_url,
                a.birth_date, a.height, a.bust, a.waist, a.hip, a.intro,
                a.alias, a.name_jp, a.name_en,
            ])
            mc = a.movie_count or 0
            if mc == 0 and not has_assets and a.name not in non_amateur_names:
                orphan.append({"id": a.id, "name": a.name, "movie_count": 0, "reason": "孤儿（无作品且无资料）"})
            elif has_assets or a.name in non_amateur_names:
                kept_assets += 1

        return {
            "module": module,
            "dry_run": True,
            "total_actors": len(actors),
            "garbage_actors": garbage,
            "garbage_count": len(garbage),
            "orphan_actors": orphan,
            "orphan_count": len(orphan),
            "kept_assets": kept_assets,
            "amateur_movies": len(amateur_movie_ids),
            "movies_garbage_actor": movies_garbage_actor,
            "amateur_dirs": amateur_dirs,
        }
    finally:
        await session.close()


async def run_actor_cleanup(
    module: str = "jav",
    amateur_dirs: Optional[list[str]] = None,
    company_names: Optional[set[str]] = None,
    backup: bool = True,
) -> dict:
    """实际执行：备份 → 清理垃圾/孤儿演员 → 素人影片 actor 置空 → 从影片重新同步

    注意：被清理的演员若存在标签/订阅/分级等关联表，一并级联删除（ORM delete）。
    保留条件与 preview 一致：有头像 / 资料 / 别名 / 标签 / 订阅 / 作品>=1 的演员绝不删除。
    """
    from app.utils.module_helper import get_module_model, get_module_session
    from app.config.manager import get_config
    from app.db.module_db import ModuleDatabase

    ActorModel = get_module_model(module, "actor")
    MovieModel = get_module_model(module, "movie")
    session = await get_module_session(module)

    # 素人配置兜底
    if amateur_dirs is None or company_names is None:
        try:
            cfg = get_config()
            jav_cfg = cfg.modules.jav
            amateur_dirs = amateur_dirs or list(getattr(jav_cfg, "amateur_media_dirs", None) or [])
            company_names = company_names or set((getattr(jav_cfg, "amateur_prefix_map", None) or {}).values())
        except Exception:
            amateur_dirs = amateur_dirs or []
            company_names = company_names or set()

    # 备份
    backup_path = None
    db = ModuleDatabase.get_instance(module)
    if backup:
        backup_path = _backup_db(db.db_path)

    deleted = []
    deleted_orphan = []
    amateur_reset = 0
    movies_actor_cleaned = 0

    try:
        # ── 1. 删除垃圾 / 孤儿演员（ORM delete，FK 级联清理关联表）──
        actors = (await session.execute(select(ActorModel))).scalars().all()
        movies = (await session.execute(select(MovieModel))).scalars().all()
        amateur_movie_ids = {
            m.id for m in movies if _in_amateur_dir(m.file_path or "", amateur_dirs)
        }
        # 孤儿防误删防线：非素人影片 actor 文本倒排
        from app.scraper.module_actor_sync import parse_actor_names

        non_amateur_names: set[str] = set()
        for m in movies:
            if m.id in amateur_movie_ids:
                continue
            non_amateur_names.update(parse_actor_names(m.actor or ""))

        for a in actors:
            reason = is_garbage_actor_name(a.name or "", company_names)
            if reason:
                await session.delete(a)
                deleted.append({"id": a.id, "name": a.name, "movie_count": a.movie_count or 0, "reason": reason})
                continue
            has_assets = any([
                a.avatar_url,
                a.birth_date, a.height, a.bust, a.waist, a.hip, a.intro,
                a.alias, a.name_jp, a.name_en,
            ])
            mc = a.movie_count or 0
            if mc == 0 and not has_assets and a.name not in non_amateur_names:
                await session.delete(a)
                deleted_orphan.append({"id": a.id, "name": a.name, "reason": "孤儿"})
        await session.flush()

        # ── 2. 清洗 movies.actor：素人置空（走公司名映射），非素人剔除垃圾名 ──
        for m in movies:
            if m.id in amateur_movie_ids:
                if m.actor:
                    m.actor = None
                    amateur_reset += 1
            else:
                new_text, changed = _sanitize_movie_actor(m.actor, company_names)
                if changed:
                    m.actor = new_text
                    movies_actor_cleaned += 1

        await session.commit()

        # ── 3. 从 movies.actor 重新同步演员表（只新增/更新，不删除）──
        from app.scraper.module_actor_sync import sync_actors_from_movies
        sync_result = await sync_actors_from_movies(module)

        return {
            "module": module,
            "status": "ok",
            "backup": backup_path,
            "deleted_garbage": deleted,
            "deleted_garbage_count": len(deleted),
            "deleted_orphan": deleted_orphan,
            "deleted_orphan_count": len(deleted_orphan),
            "deleted_total": len(deleted) + len(deleted_orphan),
            "amateur_movies_reset": amateur_reset,
            "movies_actor_cleaned": movies_actor_cleaned,
            "sync": sync_result,
        }
    except Exception as e:
        await session.rollback()
        logger.exception(f"[{module}] 演员表清理重建失败")
        raise
    finally:
        await session.close()
