"""
模块数据库管理器 v2.0
每个模块使用独立的 DeclarativeBase，允许各模块使用相同表名（如 movies/actors）而不冲突。
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import time

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
            pool_size=20,
            max_overflow=30,
            pool_pre_ping=True,
            pool_recycle=600,
            connect_args={"check_same_thread": False},
        )

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # 慢查询标记：仅在 DEBUG 级别提示网络盘慢查询，不报 WARNING
        @event.listens_for(self.engine.sync_engine, "before_cursor_execute")
        def _slow_query_mark(conn, cursor, statement, parameters, context, executemany):
            conn._mdcx_sql_start = time.monotonic()

        @event.listens_for(self.engine.sync_engine, "after_cursor_execute")
        def _slow_query_report(conn, cursor, statement, parameters, context, executemany):
            start = getattr(conn, "_mdcx_sql_start", None)
            if start is None:
                return
            elapsed = time.monotonic() - start
            if elapsed > 30.0:
                logger.warning(
                    f"[db-slow] 模块 [{self.module_name}] SQL 耗时 {elapsed:.1f}s: "
                    f"{str(statement)[:200]}"
                )

        self._initialized = False

        if "sqlite" in db_url:
            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=120000")  # 120s, 12并发补刮时避免锁冲突
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=-256000")  # 256MB, 32GB内存充裕
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.execute("PRAGMA mmap_size=2147483648")  # mmap 2GB 加速只读查询
                cursor.execute("PRAGMA page_size=16384")       # 16KB 页减少I/O次数
                cursor.close()

    async def init(self) -> None:
        """初始化数据库：创建目录 + 用模块自己的 Base 创建表"""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"初始化模块数据库 [{self.module_name}]: {self.db_path}")

        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.run_sync(self.base_class.metadata.create_all)
                # 旧表补齐缺失列（create_all 只建表、不加列，见 _migrate_schema 说明）
                await self._migrate_schema(conn)
        except Exception:
            # 数据库损坏/磁盘满/表结构冲突都在这暴露，否则只会看到调用方一串下游报错
            logger.exception(f"模块数据库 [{self.module_name}] 初始化失败: {self.db_path}")
            raise

        self._initialized = True
        logger.info(f"模块数据库 [{self.module_name}] 初始化完成，表: {list(self.base_class.metadata.tables.keys())}")

    async def _migrate_schema(self, conn) -> None:
        """补齐已存在旧表缺失的列（幂等）。

        ``metadata.create_all`` 只会创建缺失的【表】，不会给已存在的旧表追加新列。
        若服务器上的 ``*.db`` 是在模型新增列（如 ``title_jp`` / ``plot_short`` /
        ``studio_id`` 等）之前创建的，旧表缺列，扫描器 INSERT 带上新列会触发
        SQLite ``no such column``，导致整批 ``commit`` 回滚——而扫描计数已乐观 +1，
        于是出现“扫描报新增 N、库里却没增加”的假计数。

        此处遍历模型元数据，对旧表缺失的列执行 ``ALTER TABLE ADD COLUMN``。
        当前所有可能因版本迭代新增的列均为 Optional 或有默认值，迁移安全。
        """
        from sqlalchemy import inspect as sa_inspect

        def _collect(sync_conn):
            insp = sa_inspect(sync_conn)
            schema: dict[str, set[str]] = {}
            for tname in insp.get_table_names():
                schema[tname] = {c["name"] for c in insp.get_columns(tname)}
            return schema

        db_schema = await conn.run_sync(_collect)

        for table_name, table in self.base_class.metadata.tables.items():
            if table_name not in db_schema:
                continue
            existing_cols = db_schema[table_name]
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = str(col.type)
                sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'
                # SQLite 不允许给“已有数据且 NOT NULL 且无默认值”的表加列
                if not col.nullable:
                    if col.server_default is not None:
                        sql += f" DEFAULT {col.server_default.arg}"
                    elif getattr(col.default, "is_scalar", False) and col.default.arg is not None:
                        lit = col.default.arg
                        sql += f" DEFAULT {repr(lit) if isinstance(lit, str) else lit}"
                    else:
                        sql += " DEFAULT NULL"
                try:
                    await conn.execute(text(sql))
                    logger.info(
                        f"模块 [{self.module_name}] 表 {table_name} 补齐缺失列 "
                        f"{col.name} ({col_type})"
                    )
                except Exception as e:  # 单列出错不影响其它列
                    logger.warning(
                        f"模块 [{self.module_name}] 补齐列 {col.name} 失败: {e}"
                    )

    async def get_session(self) -> AsyncSession:
        if not self._initialized:
            await self.init()
        session = self.session_factory()
        # 登记到请求级回收注册表，避免调用方忘记 close 导致连接池泄漏（GC 警告）
        from app.db.session_registry import register_session
        register_session(session)
        return session

    @asynccontextmanager
    async def session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """获取模块数据库会话上下文管理器（推荐替代 get_session）

        用法::

            async with mod_db.session_scope() as session:
                ...

        async with 退出时自动 close 归还连接池；异常时自动 rollback。
        已自管理连接，无需依赖 session_registry 兜底。
        """
        if not self._initialized:
            await self.init()
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()
        self._initialized = False
        logger.info(f"模块数据库 [{self.module_name}] 连接池已释放")

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
        from app.db.anime_models import ANIME_BASE

        module_configs = [
            ("jav", JAV_BASE),
            ("fc2", FC2_BASE),
            ("uncensored", UNCENSORED_BASE),
            ("chinese", CHINESE_BASE),
            ("western", WESTERN_BASE),
            ("pornhub", PORNHUB_BASE),
            ("anime", ANIME_BASE),
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
