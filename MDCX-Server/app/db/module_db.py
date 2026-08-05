"""
模块数据库管理器 v2.0
每个模块使用独立的 DeclarativeBase，允许各模块使用相同表名（如 movies/actors）而不冲突。
"""
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 保留共享基类（向后兼容），但各模块应使用自己的 Base
class ModuleBase(DeclarativeBase):
    """模块数据库 SQLAlchemy 基类（向后兼容，新代码请使用 per-module Base）"""
    pass


class ModuleDatabase:
    """模块数据库管理器 v2.0

    每个模块使用独立的 DeclarativeBase，允许重用表名如 movies/actors/studios 等。
    每个模块只需要导入自己的模型文件，不与其他模块冲突。
    """

    _instances: dict[str, "ModuleDatabase"] = {}

    def __init__(
        self,
        module_name: str,
        db_path: str | None = None,
        base_class: type[DeclarativeBase] | None = None,
    ) -> None:
        self.module_name = module_name
        self.base_class = base_class or ModuleBase

        if db_path:
            self.db_path = db_path
        else:
            config = get_config()
            db_url = config.database.url
            if "///" in db_url:
                base_dir = Path(db_url.split("///")[-1]).parent
            else:
                base_dir = Path("data/database")
            self.db_path = str(base_dir / f"{module_name}.db")

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
        """初始化数据库：创建目录 + 用模块自己的 Base 创建表"""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"初始化模块数据库 [{self.module_name}]: {self.db_path}")

        async with self.engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(self.base_class.metadata.create_all)

        self._initialized = True
        logger.info(f"模块数据库 [{self.module_name}] 初始化完成，表: {list(self.base_class.metadata.tables.keys())}")

    async def get_session(self) -> AsyncSession:
        if not self._initialized:
            await self.init()
        return self.session_factory()

    async def close(self) -> None:
        await self.engine.dispose()
        self._initialized = False

    @classmethod
    def get_instance(
        cls,
        module_name: str,
        db_path: str | None = None,
        base_class: type[DeclarativeBase] | None = None,
    ) -> "ModuleDatabase":
        """获取模块数据库实例（单例）。

        首次调用时必须传入 base_class 以注册表结构。
        """
        if module_name not in cls._instances:
            if base_class is None:
                raise ValueError(f"模块 '{module_name}' 首次初始化必须提供 base_class")
            cls._instances[module_name] = cls(module_name, db_path, base_class)
        return cls._instances[module_name]

    @classmethod
    async def init_all(cls) -> dict[str, "ModuleDatabase"]:
        """初始化所有模块数据库"""
        # 延迟导入：每个模块模型文件定义自己的 Base 类
        from app.db.jav_models import JAV_BASE
        from app.db.fc2_models import FC2_BASE
        from app.db.uncensored_models import UNCENSORED_BASE
        from app.db.chinese_models import CHINESE_BASE
        from app.db.western_models import WESTERN_BASE
        from app.db.pornhub_models import PORNHUB_BASE

        module_configs = [
            ("jav", JAV_BASE),
            ("fc2", FC2_BASE),
            ("uncensored", UNCENSORED_BASE),
            ("chinese", CHINESE_BASE),
            ("western", WESTERN_BASE),
            ("pornhub", PORNHUB_BASE),
        ]

        instances = {}
        for name, base in module_configs:
            db = cls.get_instance(name, base_class=base)
            await db.init()
            instances[name] = db

        return instances

    @classmethod
    async def close_all(cls) -> None:
        for name, instance in cls._instances.items():
            await instance.close()
        cls._instances.clear()
