"""
数据库连接和初始化
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


class Database:
    """数据库管理器"""

    def __init__(self, database_url: str | None = None) -> None:
        config = get_config()
        self.database_url = database_url or config.database.url
        self.echo = config.database.echo

        # 创建引擎 - SQLite aiosqlite 对并发写入敏感，使用更保守的连接池
        self.engine = create_async_engine(
            self.database_url,
            echo=self.echo,
            pool_size=config.database.pool_size,
            connect_args={"check_same_thread": False} if "sqlite" in self.database_url else {},
        )

        # 创建会话工厂
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._initialized = False

        # SQLite 连接事件：每个新连接都设置必要的 PRAGMA
        if "sqlite" in self.database_url:
            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=60000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=-128000")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.execute("PRAGMA mmap_size=1073741824")
                cursor.execute("PRAGMA page_size=16384")
                cursor.close()

    async def init(self) -> None:
        """初始化数据库"""
        if self._initialized:
            return

        logger.info(f"初始化数据库: {self.database_url}")

        # 确保数据库目录存在
        if "sqlite" in self.database_url:
            db_path = self.database_url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # 启用 WAL 模式和相关优化（在每个新连接上执行）
        if "sqlite" in self.database_url:
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA busy_timeout=60000"))
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                await conn.execute(text("PRAGMA synchronous=NORMAL"))
                await conn.execute(text("PRAGMA cache_size=-128000"))
                await conn.execute(text("PRAGMA temp_store=MEMORY"))
                await conn.execute(text("PRAGMA mmap_size=1073741824"))
                await conn.execute(text("PRAGMA page_size=16384"))
                logger.info("SQLite 优化: WAL + mmap(1GB) + 128MB缓存 + 16KB页")

        # 创建表
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 标记为已初始化(迁移过程中会用到 session,必须在迁移前设置,避免递归调用)
        self._initialized = True

        # 数据库迁移:统一走 MigrationManager(删除旧的 _run_migrations 方法)
        # 018 迁移整合了 studio_id/series_id/original_title/is_uncensored/
        # sample_images/play_count/last_played_at/fingerprint 等所有列迁移
        try:
            from app.db.migrations import MigrationManager
            manager = MigrationManager()
            applied = await manager.upgrade()
            if applied:
                logger.info(f"数据库迁移完成: 已应用 {len(applied)} 个迁移 {applied}")
        except Exception as e:
            logger.warning(f"数据库迁移失败(可能已应用过): {e}")

        logger.info("数据库初始化完成")

    async def close(self) -> None:
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("数据库连接已关闭")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话(无异常时自动 commit,异常时 rollback)

        这是 SQLAlchemy 官方推荐的 FastAPI 集成模式,避免调用方忘记 commit 丢数据。
        """
        if not self._initialized:
            await self.init()

        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def execute(self, statement: any) -> any:
        """执行 SQL 语句"""
        async with self.session() as session:
            result = await session.execute(statement)
            return result


# 全局数据库实例
_database: Database | None = None


async def init_database(database_url: str | None = None) -> Database:
    """
    初始化数据库

    Args:
        database_url: 数据库连接 URL

    Returns:
        Database 实例
    """
    global _database
    if _database is not None and _database._initialized:
        return _database
    _database = Database(database_url)
    await _database.init()
    return _database


def get_database() -> Database:
    """
    获取数据库实例

    Returns:
        Database 实例
    """
    global _database
    if _database is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    return _database


# 别名 - 兼容旧代码中 from app.db.database import get_db 的用法
get_db = get_database


def get_session_factory():
    """获取异步会话工厂（用于非依赖注入场景）

    返回 async_sessionmaker，调用方需要用 `async with factory() as session:` 使用。
    """
    db = get_database()
    return db.session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话（用于依赖注入）

    Yields:
        AsyncSession 实例
    """
    db = get_database()
    async with db.session() as session:
        yield session


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话上下文管理器（用于后台任务等非依赖注入场景）

    用法:
        async with get_session_context() as session:
            ...

    事务由调用方控制（commit / rollback）。
    """
    db = get_database()
    async with db.session() as session:
        yield session
