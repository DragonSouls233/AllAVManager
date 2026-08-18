"""
系统数据库管理器 (system.db)
管理跨模块全局数据：用户、认证、设置、收藏夹等
"""
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 注意：不要在模块级别导入 system_models，循环依赖风险
# 在 init_all() 中按需导入


class SystemDatabase:
    """系统数据库管理器（单例）

    管理 system.db 中的所有全局表。
    """

    _instance: "SystemDatabase | None" = None

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self.db_path = db_path
        else:
            from app.config.manager import get_config
            config = get_config()
            # 正确解析 SQLAlchemy URL 中的文件路径（旧写法 Path(url).parent 会带上
            # "sqlite+aiosqlite:" 前缀生成无效路径，导致 system.db 永远打不开）
            base_dir = Path("data/database")
            if config.database.url and "sqlite" in config.database.url:
                try:
                    parsed = make_url(config.database.url)
                    if parsed.database:
                        base_dir = Path(parsed.database).parent
                except Exception:
                    pass
            self.db_path = str(base_dir / "system.db")

        db_url = f"sqlite+aiosqlite:///{self.db_path}"

        self.engine = create_async_engine(
            db_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"check_same_thread": False},
        )

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._initialized = False

        if "sqlite" in db_url:
            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=60000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=-64000")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.close()

    async def init(self) -> None:
        """创建表结构"""
        if self._initialized:
            return

        from app.db.system_models import SystemBase

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"初始化系统数据库: {self.db_path}")

        async with self.engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(SystemBase.metadata.create_all)
            await self._migrate_schema(conn)

        self._initialized = True
        logger.info("系统数据库初始化完成")

    async def _migrate_schema(self, conn) -> None:
        """幂等补齐历史遗留表的缺失列。

        具体逻辑与需要补的列声明统一在 app.db.schema_migrations 中，
        与 app.db.database.Database 共用同一份实现，避免两处各写一套
        导致「迁移写在没被调用的类里」而完全失效。
        """
        from app.db.schema_migrations import apply_required_columns

        await apply_required_columns(conn, db_label=str(self.db_path))

    async def get_session(self) -> AsyncSession:
        if not self._initialized:
            await self.init()
        session = self.session_factory()
        # 登记到请求级回收注册表，避免调用方忘记 close 导致连接池泄漏（GC 警告）
        from app.db.session_registry import register_session
        register_session(session)
        return session

    async def close(self) -> None:
        await self.engine.dispose()
        self._initialized = False

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> "SystemDatabase":
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    async def close_instance(cls) -> None:
        if cls._instance:
            await cls._instance.close()
            cls._instance = None


# ========== 兼容旧代码的别名 ==========

# 提供 get_session 依赖注入函数
async def get_system_session():
    """获取系统数据库 session（FastAPI Depends 用）"""
    db = SystemDatabase.get_instance()
    return await db.get_session()
