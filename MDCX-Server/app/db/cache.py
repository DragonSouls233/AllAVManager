"""
泛型缓存层

支持两级缓存：
- 第一级：内存缓存（lru_cache，同进程内共享）
- 第二级：SQLite KV 缓存（跨重启持久化）

参考 PornBoss internal/cache/sqlite_kv.go 设计
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Callable, Optional, TypeVar

from app.db.database import get_db
from app.db.models import Cache
from sqlalchemy import func

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    category: str = "default"
    ttl: Optional[int] = None  # 存活时间（秒）
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl


class MemoryCache:
    """
    内存缓存（第一级）

    使用 dict 存储，支持 TTL 过期
    """

    def __init__(self, max_size: int = 50000, cleanup_interval: int = 300):
        """
        初始化

        Args:
            max_size: 最大条目数
            cleanup_interval: 清理间隔（秒）
        """
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        self._maybe_cleanup()

        entry = self._cache.get(key)
        if entry is None:
            return None

        if entry.is_expired():
            del self._cache[key]
            return None

        return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存"""
        self._maybe_cleanup()

        if len(self._cache) >= self._max_size:
            # 移除最旧的 20%
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k].created_at,
            )
            remove_count = max(1, len(self._cache) // 5)
            for k in sorted_keys[:remove_count]:
                del self._cache[k]

        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            ttl=ttl,
        )

    def delete(self, key: str) -> bool:
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self, category: Optional[str] = None) -> int:
        """
        清理缓存

        Args:
            category: 分类，None 表示清理所有

        Returns:
            清理的条目数
        """
        if category is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        keys_to_delete = [
            k for k, v in self._cache.items()
            if v.category == category
        ]
        for k in keys_to_delete:
            del self._cache[k]
        return len(keys_to_delete)

    def _maybe_cleanup(self) -> None:
        """定期清理过期条目"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        expired = [
            k for k, v in self._cache.items()
            if v.is_expired()
        ]
        for k in expired:
            del self._cache[k]

        if expired:
            logger.debug(f"Cleaned {len(expired)} expired memory cache entries")

    @property
    def size(self) -> int:
        """当前缓存大小"""
        return len(self._cache)


class DatabaseCache:
    """
    数据库缓存（第二级）

    使用 SQLAlchemy ORM 操作 Cache 表，支持 TTL 过期。
    注意：此缓存与主业务共用同一 SQLite 文件，写入时会争锁。
    对于高频写入场景，建议仅使用 MemoryCache。
    """

    def __init__(self):
        self.db = get_db()

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        async with self.db.session() as session:
            from sqlalchemy import select as sa_select, delete as sa_delete
            result = await session.execute(
                sa_select(Cache.value, Cache.expires_at).where(Cache.key == key)
            )
            row = result.fetchone()

            if not row:
                return None

            value, expires_at = row

            # 检查是否过期
            if expires_at and datetime.fromisoformat(str(expires_at)) < datetime.now():
                await session.execute(
                    sa_delete(Cache).where(Cache.key == key)
                )
                await session.commit()
                return None

            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

    async def set(
        self,
        key: str,
        value: Any,
        category: str = "default",
        ttl: Optional[int] = None,
    ) -> None:
        """设置缓存"""
        from sqlalchemy import update as sa_update

        expires_at = None
        if ttl is not None:
            expires_at = (datetime.now() + timedelta(seconds=ttl)).isoformat()

        serialized = json.dumps(value, ensure_ascii=False, default=str)

        async with self.db.session() as session:
            # 先尝试更新
            result = await session.execute(
                sa_update(Cache).where(Cache.key == key).values(
                    value=serialized,
                    category=category,
                    expires_at=expires_at,
                )
            )
            if result.rowcount == 0:
                # 不存在则插入
                session.add(Cache(
                    category=category,
                    key=key,
                    value=serialized,
                    expires_at=expires_at,
                ))
            await session.commit()

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        from sqlalchemy import delete as sa_delete
        async with self.db.session() as session:
            result = await session.execute(
                sa_delete(Cache).where(Cache.key == key)
            )
            await session.commit()
            return result.rowcount > 0

    async def clear(self, category: Optional[str] = None) -> int:
        """清理缓存"""
        from sqlalchemy import delete as sa_delete
        async with self.db.session() as session:
            if category:
                result = await session.execute(
                    sa_delete(Cache).where(Cache.category == category)
                )
            else:
                result = await session.execute(sa_delete(Cache))
            await session.commit()
            return result.rowcount

    async def cleanup_expired(self) -> int:
        """清理过期缓存"""
        from sqlalchemy import delete as sa_delete
        async with self.db.session() as session:
            now_str = datetime.now().isoformat()
            result = await session.execute(
                sa_delete(Cache).where(
                    Cache.expires_at.isnot(None),
                    Cache.expires_at < now_str,
                )
            )
            count = result.rowcount
            if count > 0:
                await session.commit()
                logger.debug(f"Cleaned {count} expired DB cache entries")
            return count

    async def get_stats(self) -> dict:
        """获取缓存统计"""
        from sqlalchemy import select as sa_select
        async with self.db.session() as session:
            total = await session.scalar(sa_select(func.count()).select_from(Cache))
            total_count = total or 0

            by_category_result = await session.execute(
                sa_select(Cache.category, func.count()).group_by(Cache.category)
            )
            categories = {row[0]: row[1] for row in by_category_result.fetchall()}

            expired = await session.scalar(
                sa_select(func.count()).select_from(Cache).where(
                    Cache.expires_at.isnot(None),
                    Cache.expires_at < datetime.now().isoformat(),
                )
            )
            expired_count = expired or 0

            return {
                "total": total_count,
                "categories": categories,
                "expired": expired_count,
            }


class CacheService:
    """
    缓存服务

    两级缓存策略：
    1. 先查内存缓存（快速）
    2. 未命中则查数据库缓存
    3. 都未命中则调用 fetch_func 获取
    4. 获取后写入两级缓存
    """

    def __init__(
        self,
        memory_max_size: int = 50000,
        default_ttl: int = 3600,  # 默认1小时
    ):
        """
        初始化

        Args:
            memory_max_size: 内存缓存最大条目数
            default_ttl: 默认存活时间（秒）
        """
        self.memory = MemoryCache(max_size=memory_max_size)
        self.database = DatabaseCache()
        self.default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(
        self,
        key: str,
        fetch_func: Optional[Callable[[], Any]] = None,
        ttl: Optional[int] = None,
        category: str = "default",
    ) -> Any:
        """
        获取缓存

        Args:
            key: 缓存键
            fetch_func: 获取数据的函数（缓存未命中时调用）
            ttl: 存活时间（秒）
            category: 分类

        Returns:
            缓存的值
        """
        ttl = ttl or self.default_ttl

        # 1. 查内存缓存
        value = self.memory.get(key)
        if value is not None:
            return value

        # 2. 查数据库缓存
        value = await self.database.get(key)
        if value is not None:
            # 回填内存缓存
            self.memory.set(key, value, ttl)
            return value

        # 3. 都未命中，调用获取函数
        if fetch_func is None:
            return None

        async with self._lock:
            # 双重检查
            value = self.memory.get(key)
            if value is not None:
                return value

            value = await self.database.get(key)
            if value is not None:
                self.memory.set(key, value, ttl)
                return value

            # 获取数据
            if asyncio.iscoroutinefunction(fetch_func):
                value = await fetch_func()
            else:
                value = fetch_func()

            if value is not None:
                # 写入两级缓存
                self.memory.set(key, value, ttl)
                await self.database.set(key, value, category, ttl)

            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        category: str = "default",
    ) -> None:
        """
        设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 存活时间（秒）
            category: 分类
        """
        ttl = ttl or self.default_ttl

        self.memory.set(key, value, ttl)
        await self.database.set(key, value, category, ttl)

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        self.memory.delete(key)
        return await self.database.delete(key)

    async def clear(self, category: Optional[str] = None) -> int:
        """清理缓存"""
        mem_count = self.memory.clear(category)
        db_count = await self.database.clear(category)
        return mem_count + db_count

    async def cleanup_expired(self) -> int:
        """清理过期缓存"""
        return await self.database.cleanup_expired()

    async def get_stats(self) -> dict:
        """获取缓存统计"""
        db_stats = await self.database.get_stats()
        return {
            "memory_size": self.memory.size,
            "database": db_stats,
        }


# ============================================
# 便捷函数 & 装饰器
# ============================================

# 全局缓存服务实例
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """获取全局缓存服务实例"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def cached(ttl: int = 3600, category: str = "default"):
    """
    缓存装饰器

    用法:
        @cached(ttl=300, category="scraper")
        async def get_movie(code: str):
            ...

    Args:
        ttl: 存活时间（秒）
        category: 分类
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 生成缓存键
            key = f"{func.__module__}:{func.__name__}:{args}:{kwargs}"
            cache = get_cache_service()

            async def fetch() -> Any:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)

            return await cache.get(key, fetch, ttl, category)
        return wrapper
    return decorator


async def cache_get(key: str) -> Any:
    """获取缓存的便捷函数"""
    service = get_cache_service()
    return await service.get(key)


async def cache_set(
    key: str,
    value: Any,
    ttl: Optional[int] = None,
    category: str = "default",
) -> None:
    """设置缓存的便捷函数"""
    service = get_cache_service()
    await service.set(key, value, ttl, category)


async def cache_delete(key: str) -> bool:
    """删除缓存的便捷函数"""
    service = get_cache_service()
    return await service.delete(key)


async def cache_clear(category: Optional[str] = None) -> int:
    """清理缓存的便捷函数"""
    service = get_cache_service()
    return await service.clear(category)
