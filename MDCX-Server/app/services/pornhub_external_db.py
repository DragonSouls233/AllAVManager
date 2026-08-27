"""
L:\\data\\PORNHUB\\models.db 导入器
=================================

L:\\data\\PORNHUB\\models.db 是另一个下载项目（专门用于下载 PornHub）的数据库，
里面维护了 803 个 model（演员）记录 + 84,381 个 video 记录，每条 model
都带有 https://cn.pornhub.com/model/{name}/videos 形式的 URL。

本模块把这个外部 DB 作为「演员 URL 种子源」：
  1. 启动时一次性把 models 表载入内存（O(1) 查询）
  2. 提供按名查询演员 URL 的接口
  3. 提供「批量回填 URL」端点，把 MDCX 库中没有 profile_url 的演员补上
  4. 提供「整库种子」端点，把整个 models 表作为初始演员导入

设计要点：
  - 只读访问 models.db（外部项目 DB，永不修改）
  - 倒排索引 by lowercased name → row，O(1) 查询
  - 名称变体匹配：支持 "Anna Cherry" / "anna-cherry" / "Anna Cherry7" 等
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认种子源路径（用户可在 config / 端点中覆盖）
DEFAULT_DB_PATH = Path(r"L:\data\PORNHUB\models.db")


class PornhubExternalDB:
    """L:\\data\\PORNHUB\\models.db 只读访问器（线程安全）"""

    _instance: Optional["PornhubExternalDB"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._name_index: dict[str, dict] = {}        # lowercased name → row
        self._url_index: dict[str, dict] = {}         # url → row
        self._loaded = False
        self._load_lock = threading.Lock()

    # ---------- 单例 ----------

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> "PornhubExternalDB":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path or DEFAULT_DB_PATH)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    # ---------- 连接管理 ----------

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        with self._load_lock:
            if self._loaded:
                return True
            if not self.db_path.exists():
                logger.warning(f"[pornhub-ext] 外部 DB 不存在: {self.db_path}")
                return False
            try:
                self._conn = sqlite3.connect(
                    f"file:{self.db_path}?mode=ro", uri=True, timeout=10,
                    check_same_thread=False,
                )
                self._conn.row_factory = sqlite3.Row
                self._build_index()
                self._loaded = True
                logger.info(
                    f"[pornhub-ext] 已加载外部模型库: {self.db_path} "
                    f"models={len(self._name_index)}"
                )
                return True
            except Exception as e:
                logger.error(f"[pornhub-ext] 加载外部 DB 失败: {e}")
                return False

    def _build_index(self) -> None:
        """一次性把 models 表全部载入倒排索引"""
        if not self._conn:
            return
        cur = self._conn.execute(
            "SELECT id, name, url, country, mode, local_directory, "
            "online_count, local_count, missing_count "
            "FROM models"
        )
        for row in cur.fetchall():
            entry = dict(row)
            self._name_index[row["name"].lower()] = entry
            self._url_index[row["url"]] = entry

    def reload(self) -> bool:
        """强制重载（外部 DB 被另一个项目更新时使用）"""
        with self._load_lock:
            try:
                if self._conn:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._name_index.clear()
            self._url_index.clear()
            self._loaded = False
        return self._ensure_loaded()

    # ---------- 查询 ----------

    def get_by_name(self, name: str) -> Optional[dict]:
        """按演员名查找（精确匹配，忽略大小写与多余空格）"""
        if not self._ensure_loaded() or not name:
            return None
        key = re.sub(r"\s+", " ", name.strip().lower())
        row = self._name_index.get(key)
        if row:
            return row
        # 回退：忽略空格 / 标点
        flat = re.sub(r"[\s\-_\.]+", "", key)
        for k, v in self._name_index.items():
            if re.sub(r"[\s\-_\.]+", "", k) == flat:
                return v
        return None

    def get_by_url(self, url: str) -> Optional[dict]:
        if not self._ensure_loaded() or not url:
            return None
        return self._url_index.get(url)

    def find_candidates(self, keyword: str, limit: int = 20) -> list[dict]:
        """模糊搜索（按名子串匹配）"""
        if not self._ensure_loaded() or not keyword:
            return []
        kw = keyword.strip().lower()
        results: list[dict] = []
        for name, row in self._name_index.items():
            if kw in name:
                results.append(row)
                if len(results) >= limit:
                    break
        return results

    def stats(self) -> dict:
        """返回外部 DB 的概况（country 分布等）"""
        if not self._ensure_loaded():
            return {"available": False, "path": str(self.db_path)}
        countries: dict[str, int] = {}
        modes: dict[str, int] = {}
        for row in self._name_index.values():
            c = row.get("country") or "未知"
            countries[c] = countries.get(c, 0) + 1
            m = row.get("mode") or "model"
            modes[m] = modes.get(m, 0) + 1
        return {
            "available": True,
            "path": str(self.db_path),
            "total_models": len(self._name_index),
            "total_videos": self._count_videos(),
            "countries": countries,
            "modes": modes,
        }

    def _count_videos(self) -> int:
        if not self._conn:
            return 0
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM videos")
            return cur.fetchone()[0]
        except Exception:
            return 0

    # ---------- 实用 ----------

    def build_profile_url(self, name: str) -> Optional[str]:
        """根据演员名推断 PornHub 个人主页 URL（优先查表，缺失则按命名规则构造）"""
        row = self.get_by_name(name)
        if row:
            return row["url"]
        slug = name.strip().replace(" ", "-")
        if not slug:
            return None
        return f"https://cn.pornhub.com/model/{slug}/videos"


# ===================================================================
# 批量回填：把外部 DB 里的 URL 灌到 MDCX 的 PornhubActor
# ===================================================================

async def backfill_actor_urls(session, actor_names: list[str] | None = None,
                              only_missing: bool = True,
                              db_path: Path | str | None = None) -> dict:
    """把外部 DB 的 URL 写回 PornhubActor.profile_url

    Args:
        session: 活跃的 SQLAlchemy AsyncSession
        actor_names: 仅处理这些演员；None 表示处理全部
        only_missing: True 时只回填还没有 URL 的演员
        db_path: 外部 DB 路径（None 用默认 L:\\data\\PORNHUB\\models.db）
    """
    from sqlalchemy import select
    from app.db.pornhub_models import PornhubActor

    ext = PornhubExternalDB.get_instance(db_path)
    if not ext._ensure_loaded():
        return {"status": "error", "message": f"外部 DB 不可用: {ext.db_path}"}

    stmt = select(PornhubActor)
    if actor_names:
        stmt = stmt.where(PornhubActor.name.in_(actor_names))
    if only_missing:
        stmt = stmt.where(
            (PornhubActor.profile_url.is_(None)) | (PornhubActor.profile_url == "")
        )
    rows = (await session.execute(stmt)).scalars().all()

    matched = 0
    not_found = 0
    skipped_has_url = 0
    for actor in rows:
        if only_missing and actor.profile_url:
            skipped_has_url += 1
            continue
        row = ext.get_by_name(actor.name)
        if row:
            actor.profile_url = row["url"]
            if not actor.nationality and row.get("country"):
                actor.nationality = row["country"]
            matched += 1
        else:
            not_found += 1
    await session.commit()
    return {
        "status": "ok",
        "total_actors": len(rows),
        "matched": matched,
        "not_found": not_found,
        "skipped_has_url": skipped_has_url,
        "external_db": str(ext.db_path),
    }


async def seed_actors_from_external(session,
                                    db_path: Path | str | None = None,
                                    only_active: bool = True,
                                    country_filter: list[str] | None = None,
                                    limit: int | None = None) -> dict:
    """把外部 DB 整个 models 表作为初始演员导入到 PornhubActor

    Args:
        only_active: 仅导入 status='active' 的 model
        country_filter: 仅导入指定国家的 model
        limit: 最多导入多少
    """
    from sqlalchemy import select
    from app.db.pornhub_models import PornhubActor

    ext = PornhubExternalDB.get_instance(db_path)
    if not ext._ensure_loaded():
        return {"status": "error", "message": f"外部 DB 不可用: {ext.db_path}"}

    rows = list(ext._name_index.values())
    if only_active:
        rows = [r for r in rows if (r.get("status") or "active") == "active"]
    if country_filter:
        cf = set(country_filter)
        rows = [r for r in rows if (r.get("country") or "") in cf]
    if limit:
        rows = rows[:limit]

    # 已存在的演员集合（按名）
    existing = set(
        (await session.execute(select(PornhubActor.name))).scalars().all()
    )

    added = 0
    updated = 0
    for row in rows:
        name = row["name"]
        if name in existing:
            # 已存在 → 只补 URL
            stmt = select(PornhubActor).where(PornhubActor.name == name)
            actor = (await session.execute(stmt)).scalar_one_or_none()
            if actor and not actor.profile_url:
                actor.profile_url = row["url"]
                if not actor.nationality and row.get("country"):
                    actor.nationality = row["country"]
                updated += 1
            continue
        session.add(PornhubActor(
            name=name,
            nationality=row.get("country"),
            profile_url=row.get("url"),
            source="external_seed",
            movie_count=row.get("online_count") or 0,
            alias=row.get("mode"),
        ))
        added += 1

    await session.commit()
    return {
        "status": "ok",
        "total_in_external": len(rows),
        "added": added,
        "updated": updated,
        "external_db": str(ext.db_path),
    }


# ===================================================================
# 路由层便捷包装函数（供 pornhub_routes 直接 import 使用）
# ===================================================================


def get_external_status(db_path: Path | str | None = None) -> dict:
    """检查外部 DB 是否可用并返回统计信息。"""
    ext = PornhubExternalDB.get_instance(db_path)
    if not ext._ensure_loaded():
        return {
            "available": False,
            "path": str(ext.db_path),
            "error": "外部 DB 文件不可读或不存在",
        }
    return {
        "available": True,
        "path": str(ext.db_path),
        "model_count": ext.model_count(),
        "video_count": ext.video_count(),
        "cached": bool(ext._name_index),
    }


def search_models(keyword: str, db_path: Path | str | None = None, limit: int = 50) -> list[dict]:
    """按名称模糊搜索演员。返回 [{name, profile_url, video_count, mode, country}]。"""
    ext = PornhubExternalDB.get_instance(db_path)
    if not ext._ensure_loaded():
        return []
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []
    out = []
    for row in ext._name_index.values():
        if keyword in (row.get("name") or "").lower():
            out.append({
                "name": row.get("name"),
                "profile_url": row.get("url"),
                "video_count": row.get("online_count"),
                "mode": row.get("mode"),
                "country": row.get("country"),
            })
            if len(out) >= limit:
                break
    return out


def get_model_by_name(name: str, db_path: Path | str | None = None) -> Optional[dict]:
    """按精确名取一条外部 DB 记录。"""
    ext = PornhubExternalDB.get_instance(db_path)
    if not ext._ensure_loaded():
        return None
    row = ext.get_by_name(name)
    if not row:
        return None
    return {
        "name": row.get("name"),
        "profile_url": row.get("url"),
        "video_count": row.get("online_count"),
        "mode": row.get("mode"),
        "country": row.get("country"),
    }


def iter_models(db_path: Path | str | None = None):
    """惰性遍历所有外部 model 记录（用于大批量后台种子）。"""
    ext = PornhubExternalDB.get_instance(db_path)
    if not ext._ensure_loaded():
        return
    for row in ext._name_index.values():
        yield {
            "name": row.get("name"),
            "profile_url": row.get("url"),
            "video_count": row.get("online_count"),
            "mode": row.get("mode"),
            "country": row.get("country"),
        }
