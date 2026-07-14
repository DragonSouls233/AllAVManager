"""
模块数据库管理器
支持各模块使用独立的 SQLite 数据库文件
"""

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ModuleBase(DeclarativeBase):
    """模块数据库 SQLAlchemy 基类"""
    pass


class ModuleDatabase:
    """模块数据库管理器

    每个模块（chinese/uncensored/fc2/pornhub）使用独立的 .db 文件
    共享数据库基类 ModuleBase，但使用不同的引擎和会话
    """

    _instances: dict[str, "ModuleDatabase"] = {}

    def __init__(self, module_name: str, db_path: str | None = None) -> None:
        self.module_name = module_name

        if db_path:
            self.db_path = db_path
        else:
            config = get_config()
            base_dir = Path(config.database.url.split("///")[0] if "///" in config.database.url else "data/database")
            if "sqlite" in config.database.url:
                base_dir = Path(config.database.url.split("///")[-1]).parent
            self.db_path = str(base_dir / f"{module_name}.db")

        db_url = f"sqlite+aiosqlite:///{self.db_path}"

        self.engine = create_async_engine(
            db_url,
            echo=False,
            pool_size=5,
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
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=60000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=-64000")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.close()

    async def init(self) -> None:
        """初始化数据库：创建目录 + 创建表"""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"初始化模块数据库 [{self.module_name}]: {self.db_path}")

        async with self.engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(ModuleBase.metadata.create_all)

        self._initialized = True

    async def get_session(self) -> AsyncSession:
        if not self._initialized:
            await self.init()
        return self.session_factory()

    async def close(self) -> None:
        await self.engine.dispose()
        self._initialized = False

    @classmethod
    def get_instance(cls, module_name: str, db_path: str | None = None) -> "ModuleDatabase":
        if module_name not in cls._instances:
            cls._instances[module_name] = cls(module_name, db_path)
        return cls._instances[module_name]

    @classmethod
    async def init_all(cls) -> dict[str, "ModuleDatabase"]:
        """初始化所有模块数据库

        需显式导入各模块的模型文件，确保 SQLAlchemy Metadata 有完整的表注册。
        """
        # 显式导入所有模块模型以确保表被创建
        import app.db.chinese_models  # noqa: F401
        import app.db.uncensored_models  # noqa: F401
        import app.db.fc2_models  # noqa: F401
        import app.db.pornhub_models  # noqa: F401
        import app.db.western_models  # noqa: F401

        instances = {}
        for name in ["chinese", "uncensored", "fc2", "pornhub", "western"]:
            db = cls.get_instance(name)
            await db.init()
            # 每个数据库引擎单独创建表
            async with db.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.run_sync(ModuleBase.metadata.create_all)
            instances[name] = db
        return instances

    @classmethod
    async def close_all(cls) -> None:
        for name, instance in cls._instances.items():
            await instance.close()
        cls._instances.clear()
