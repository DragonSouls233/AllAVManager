"""
下载缓存去重模块

基于 SQLite 实现下载缓存去重，避免重复下载相同 URL/文件。

去重策略:
  1. URL 去重: 同一 URL 只下载一次
  2. 文件哈希去重: 相同 sha1 的文件跳过
  3. 下载状态追踪: pending/downloading/completed/failed
  4. TTL 过期: 失败的下载 24 小时后可重试
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "download_cache.db"
FAILED_TTL = 86400  # 24 小时


@dataclass
class DownloadCacheEntry:
    """缓存条目"""
    url: str
    file_path: Optional[str] = None
    file_size: int = 0
    hash: Optional[str] = None
    status: str = "pending"
    engine: str = ""
    error: Optional[str] = None
    created_at: float = 0.0
    completed_at: Optional[float] = None
    metadata: dict = field(default_factory=dict)


class DownloadCacheDB:
    """下载缓存去重数据库"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS download_cache (
                url TEXT PRIMARY KEY,
                file_path TEXT,
                file_size INTEGER DEFAULT 0,
                hash TEXT,
                status TEXT DEFAULT 'pending',
                engine TEXT DEFAULT '',
                error TEXT,
                created_at REAL,
                completed_at REAL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_download_hash ON download_cache(hash)
            WHERE hash IS NOT NULL AND hash != ''
        """)
        conn.commit()
        conn.close()

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def get(self, url: str) -> Optional[DownloadCacheEntry]:
        """按 URL 查询"""
        conn = self._connect()
        row = conn.execute(
            "SELECT url, file_path, file_size, hash, status, engine, error, created_at, completed_at, metadata "
            "FROM download_cache WHERE url=?",
            (url,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return DownloadCacheEntry(
            url=row[0],
            file_path=row[1],
            file_size=row[2] or 0,
            hash=row[3],
            status=row[4],
            engine=row[5] or "",
            error=row[6],
            created_at=row[7] or 0,
            completed_at=row[8],
            metadata=json.loads(row[9] or "{}"),
        )

    def get_by_hash(self, file_hash: str) -> Optional[DownloadCacheEntry]:
        """按哈希值查询"""
        if not file_hash:
            return None
        conn = self._connect()
        row = conn.execute(
            "SELECT url, file_path, file_size, hash, status, engine, error, created_at, completed_at, metadata "
            "FROM download_cache WHERE hash=?",
            (file_hash,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return DownloadCacheEntry(
            url=row[0],
            file_path=row[1],
            file_size=row[2] or 0,
            hash=row[3],
            status=row[4],
            engine=row[5] or "",
            error=row[6],
            created_at=row[7] or 0,
            completed_at=row[8],
            metadata=json.loads(row[9] or "{}"),
        )

    def exists(self, url: str) -> bool:
        """URL 是否已缓存且成功"""
        conn = self._connect()
        row = conn.execute(
            "SELECT status FROM download_cache WHERE url=?",
            (url,),
        ).fetchone()
        conn.close()
        return row is not None and row[0] == "completed"

    def save(self, entry: DownloadCacheEntry) -> None:
        """保存/更新缓存"""
        now = time.time()
        conn = self._connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO download_cache
            (url, file_path, file_size, hash, status, engine, error, created_at, completed_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.url,
                entry.file_path,
                entry.file_size,
                entry.hash,
                entry.status,
                entry.engine,
                entry.error,
                entry.created_at or now,
                entry.completed_at,
                json.dumps(entry.metadata, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

    def set_status(self, url: str, status: str, error: Optional[str] = None) -> None:
        """更新状态"""
        conn = self._connect()
        completed_at = time.time() if status in ("completed", "failed") else None
        conn.execute(
            "UPDATE download_cache SET status=?, error=?, completed_at=? WHERE url=?",
            (status, error, completed_at, url),
        )
        conn.commit()
        conn.close()

    def mark_completed(self, url: str, file_path: str, file_size: int, file_hash: str) -> None:
        """标记为完成"""
        conn = self._connect()
        now = time.time()
        conn.execute(
            "UPDATE download_cache SET status='completed', file_path=?, file_size=?, hash=?, completed_at=? WHERE url=?",
            (file_path, file_size, file_hash, now, url),
        )
        conn.commit()
        conn.close()

    def update_metadata(self, url: str, key: str, value) -> None:
        """更新元数据字段"""
        entry = self.get(url)
        if entry:
            entry.metadata[key] = value
            conn = self._connect()
            conn.execute(
                "UPDATE download_cache SET metadata=? WHERE url=?",
                (json.dumps(entry.metadata, ensure_ascii=False), url),
            )
            conn.commit()
            conn.close()

    def is_retryable(self, url: str) -> bool:
        """检查是否可重试（失败后 24 小时）"""
        entry = self.get(url)
        if not entry:
            return True
        if entry.status == "completed":
            return False
        if entry.status == "failed" and entry.completed_at:
            return (time.time() - entry.completed_at) > FAILED_TTL
        if entry.status == "downloading":
            return False
        return True

    def cleanup_expired(self) -> int:
        """清理过期失败记录"""
        cutoff = time.time() - FAILED_TTL * 30  # 30 天
        conn = self._connect()
        deleted = conn.execute(
            "DELETE FROM download_cache WHERE status='failed' AND completed_at < ?",
            (cutoff,),
        ).rowcount
        conn.commit()
        conn.close()
        return deleted

    def stats(self) -> dict:
        """统计信息"""
        conn = self._connect()
        total = conn.execute("SELECT COUNT(*) FROM download_cache").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM download_cache WHERE status='completed'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM download_cache WHERE status='failed'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM download_cache WHERE status='pending' OR status='downloading'").fetchone()[0]
        total_bytes = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM download_cache WHERE status='completed'").fetchone()[0]
        conn.close()
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "total_bytes": total_bytes,
        }


# 全局单例
_cache: Optional[DownloadCacheDB] = None


def get_download_cache() -> DownloadCacheDB:
    global _cache
    if _cache is None:
        _cache = DownloadCacheDB()
    return _cache
