"""
系统数据库管理器 (system.db)
管理跨模块全局数据：用户、认证、设置、收藏夹等
"""
from pathlib import Path

from sqlalchemy import event, text
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
            base_dir = Path(config.database.url).parent if "sqlite" in config.database.url else Path("data/database")
            self.db_path = str(base_dir / "system.db")

        db_url = f"sqlite+aiosqlite:///{self.db_path}"

        self.engine = create_async_engine(
            db_url,
            echo=False,
            pool_size=5,
            max_overflow=0,
            pool_pre_ping=True,
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

        self._initialized = True
        logger.info("系统数据库初始化完成")

    async def get_session(self) -> AsyncSession:
        if not self._initialized:
            await self.init()
        return self.session_factory()

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
