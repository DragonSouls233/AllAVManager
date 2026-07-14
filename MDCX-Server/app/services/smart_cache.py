"""
Smart Cache 增量更新模块

参考来源:
- P1: PornSimilarityPlatform/modules/detection/core/modules/javdb/javdb.py (smart_cache 集成)
- P1: PSP get_incremental_fetch_range / should_update_page 模式

整合说明:
- 核心策略: 100% 复用 P1 增量抓取逻辑
  - get_incremental_fetch_range(model_name, max_pages) -> (start_page, max_pages)
  - should_update_page(model_name, page_num) -> bool
  - get_cached_titles(model_name) -> Set[str]
  - record_page(model_name, page_num, titles) -> None
- 存储: 从 P1 的 JSON 升级为 MDCX SQLite (避免并发冲突)
- 失效: 7 天 TTL，可配置

适用场景:
  - 演员页/番号列表的增量抓取（避免重复抓取已缓存的页）
  - 跳过上 N 页（演员新增的作品总是从 page 1 开始）
  - 自动延长抓取页数（增量模式 + 完整模式）

存储 schema:
  - model_name TEXT  (PK)
  - last_update_time INTEGER
  - last_total_pages INTEGER
  - last_max_titles INTEGER
  - cached_titles TEXT  (JSON 数组)
  - page_timestamps TEXT  (JSON {page_num: timestamp})
  - total_titles INTEGER
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "smart_cache.db"
DEFAULT_TTL_DAYS = 7
DEFAULT_RECENT_PAGES = 3  # 总是重新检查前 N 页（演员新作品）


@dataclass
class CacheEntry:
    """单条缓存"""
    model_name: str
    last_update_time: float = 0.0
    last_total_pages: int = 0
    last_max_titles: int = 0
    cached_titles: list[str] = field(default_factory=list)
    page_timestamps: dict[int, float] = field(default_factory=dict)
    total_titles: int = 0

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "last_update_time": self.last_update_time,
            "last_total_pages": self.last_total_pages,
            "last_max_titles": self.last_max_titles,
            "cached_titles": self.cached_titles,
            "page_timestamps": {str(k): v for k, v in self.page_timestamps.items()},
            "total_titles": self.total_titles,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "CacheEntry":
        if not row:
            return cls(model_name="")
        name, last_update, last_pages, last_max, titles_json, page_ts_json, total = row
        try:
            cached = json.loads(titles_json or "[]")
        except Exception:
            cached = []
        try:
            pages = {int(k): v for k, v in (json.loads(page_ts_json or "{}")).items()}
        except Exception:
            pages = {}
        return cls(
            model_name=name,
            last_update_time=last_update or 0.0,
            last_total_pages=last_pages or 0,
            last_max_titles=last_max or 0,
            cached_titles=cached,
            page_timestamps=pages,
            total_titles=total or 0,
        )


class SmartCache:
    """Smart Cache 增量更新管理器

    行为模式（100% 复用 P1 javdb.py 的 smart_cache 集成）:
      1. 首次抓取：完整抓 max_pages
      2. 再次抓取：
         - 如果上次抓取时间 < TTL → start_page = 上次 last_total_pages - RECENT_PAGES + 1
         - 加载已缓存标题 → 跳过重复
         - 仅抓取前 RECENT_PAGES + 1 页
      3. 单页级：should_update_page 检查每页时间戳
    """

    def __init__(
        self,
        db_path: Path = DB_PATH,
        ttl_days: int = DEFAULT_TTL_DAYS,
        recent_pages: int = DEFAULT_RECENT_PAGES,
    ):
        self.db_path = db_path
        self.ttl_seconds = ttl_days * 86400
        self.recent_pages = recent_pages
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 数据库"""
        try:
            import sqlite3

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_cache (
                    model_name TEXT PRIMARY KEY,
                    last_update_time REAL,
                    last_total_pages INTEGER,
                    last_max_titles INTEGER,
                    cached_titles TEXT,
                    page_timestamps TEXT,
                    total_titles INTEGER
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"smart_cache 数据库初始化失败: {e}")

    def _connect(self):
        import sqlite3
        return sqlite3.connect(str(self.db_path))

    def get_entry(self, model_name: str) -> Optional[CacheEntry]:
        """获取缓存条目"""
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT model_name, last_update_time, last_total_pages, last_max_titles, "
                "cached_titles, page_timestamps, total_titles FROM smart_cache WHERE model_name=?",
                (model_name,),
            ).fetchone()
            conn.close()
            if row:
                return CacheEntry.from_row(row)
        except Exception as e:
            logger.debug(f"get_entry 失败: {e}")
        return None

    def save_entry(self, entry: CacheEntry) -> None:
        """保存缓存条目"""
        try:
            conn = self._connect()
            conn.execute(
                """
                INSERT OR REPLACE INTO smart_cache
                (model_name, last_update_time, last_total_pages, last_max_titles,
                 cached_titles, page_timestamps, total_titles)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.model_name,
                    entry.last_update_time,
                    entry.last_total_pages,
                    entry.last_max_titles,
                    json.dumps(entry.cached_titles, ensure_ascii=False),
                    json.dumps({str(k): v for k, v in entry.page_timestamps.items()}, ensure_ascii=False),
                    entry.total_titles,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"save_entry 失败: {e}")

    def get_incremental_fetch_range(self, model_name: str, max_pages: int) -> tuple[int, int]:
        """获取增量抓取范围（参考 P1 javdb.py:104）

        Returns:
            (start_page, max_pages)
        """
        entry = self.get_entry(model_name)
        if not entry:
            return 1, max_pages

        # TTL 内 → 增量模式
        if time.time() - entry.last_update_time < self.ttl_seconds:
            # 从 (总页数 - recent_pages + 1) 开始抓，max_pages = 总页数
            start = max(1, entry.last_total_pages - self.recent_pages + 1)
            new_max = max(max_pages, entry.last_total_pages)
            logger.debug(
                f"smart_cache 增量模式: {model_name} "
                f"start_page={start}, max_pages={new_max}"
            )
            return start, new_max

        # 过期 → 全量重抓
        return 1, max_pages

    def should_update_page(self, model_name: str, page_num: int) -> bool:
        """检查某页是否需要更新（参考 P1 javdb.py:128）

        规则:
          - 总是更新前 RECENT_PAGES 页
          - 超过的部分：检查 page_timestamps，TTL 内跳过
        """
        if page_num <= self.recent_pages:
            return True

        entry = self.get_entry(model_name)
        if not entry:
            return True

        ts = entry.page_timestamps.get(page_num, 0)
        if not ts:
            return True
        return (time.time() - ts) >= self.ttl_seconds

    def get_cached_titles(self, model_name: str) -> set[str]:
        """获取已缓存的标题集合"""
        entry = self.get_entry(model_name)
        if not entry:
            return set()
        return set(entry.cached_titles)

    def record_page(self, model_name: str, page_num: int, titles: list[str]) -> None:
        """记录单页抓取结果（增量写入）"""
        entry = self.get_entry(model_name) or CacheEntry(model_name=model_name)
        entry.page_timestamps[page_num] = time.time()
        # 合并标题去重
        existing = set(entry.cached_titles)
        existing.update(titles)
        entry.cached_titles = list(existing)
        entry.total_titles = len(entry.cached_titles)
        entry.last_update_time = time.time()
        entry.last_max_titles = max(entry.last_max_titles, len(titles))
        self.save_entry(entry)

    def record_full_scrape(
        self, model_name: str, total_pages: int, all_titles: list[str]
    ) -> None:
        """记录完整抓取结果"""
        entry = CacheEntry(
            model_name=model_name,
            last_update_time=time.time(),
            last_total_pages=total_pages,
            last_max_titles=len(all_titles) if all_titles else 0,
            cached_titles=all_titles,
            page_timestamps={i: time.time() for i in range(1, total_pages + 1)},
            total_titles=len(all_titles),
        )
        self.save_entry(entry)
        logger.info(
            f"smart_cache 记录完整抓取: {model_name} "
            f"pages={total_pages}, titles={len(all_titles)}"
        )

    def clear(self, model_name: Optional[str] = None) -> None:
        """清空缓存（不传 model_name 则清空全部）"""
        try:
            conn = self._connect()
            if model_name:
                conn.execute("DELETE FROM smart_cache WHERE model_name=?", (model_name,))
            else:
                conn.execute("DELETE FROM smart_cache")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"clear 失败: {e}")

    def stats(self) -> dict:
        """统计信息"""
        try:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM smart_cache").fetchone()[0]
            sum_titles = conn.execute(
                "SELECT SUM(total_titles), SUM(last_total_pages) FROM smart_cache"
            ).fetchone()
            conn.close()
            return {
                "models": total,
                "total_titles": sum_titles[0] or 0,
                "total_pages": sum_titles[1] or 0,
            }
        except Exception as e:
            return {"error": str(e)}


# 全局单例
_cache: Optional[SmartCache] = None


def get_smart_cache() -> SmartCache:
    """获取全局 smart_cache 单例"""
    global _cache
    if _cache is None:
        _cache = SmartCache()
    return _cache
