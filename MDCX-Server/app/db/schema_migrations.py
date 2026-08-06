"""系统库表结构迁移（单一真相源）

背景 / 踩坑记录
--------------
项目里存在两个都会打开 system.db 的类:

* ``app.db.database.Database``      —— 启动流程 (main.py -> init_database) 实际使用的
* ``app.db.system_db.SystemDatabase`` —— 另一套封装

历史上迁移只写在 ``SystemDatabase`` 里, 而启动跑的是 ``Database``,
导致 "迁移代码明明存在却完全没生效", 最终在 INSERT 时才报出
``table scan_records has no column named removed_files``。

为避免同类问题复发, 迁移逻辑集中在本模块, 两个类都必须调用
``apply_required_columns()``, 需要补的列只在 ``SYSTEM_REQUIRED_COLUMNS`` 声明一次。

新增历史列时: 只改 ``SYSTEM_REQUIRED_COLUMNS``, 不要在别处再写 ALTER。
"""

from sqlalchemy import text

from app.utils.logger import get_logger

logger = get_logger(__name__)


# 需要幂等补列的历史迁移: {表名: {列名: SQLite 列类型}}
SYSTEM_REQUIRED_COLUMNS: dict[str, dict[str, str]] = {
    # 2026-08-05: 扫描删除检测，scan_records 增加 removed_files
    "scan_records": {"removed_files": "INTEGER"},
}


async def apply_required_columns(
    conn,
    required: dict[str, dict[str, str]] | None = None,
    *,
    db_label: str = "system.db",
) -> None:
    """幂等补齐历史遗留表的缺失列。

    与早期实现的区别: 早期把 ALTER 异常整体吞掉只打 warning, 列没补上服务
    照样启动, 最终在 INSERT 时才抛出难以定位的 OperationalError。
    这里改为「补列 -> 复查 -> 仍缺失则明确报错」, 把问题暴露在启动阶段。

    Args:
        conn: 处于事务中的 AsyncConnection (``async with engine.begin()``)
        required: 需要的列声明, 默认使用 ``SYSTEM_REQUIRED_COLUMNS``
        db_label: 报错提示里显示的数据库标识
    """
    required = SYSTEM_REQUIRED_COLUMNS if required is None else required

    for table, columns in required.items():
        # 表不存在则跳过: create_all 已按最新模型建好, 无需迁移
        exists = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        )
        if exists.fetchone() is None:
            continue

        info = await conn.execute(text(f"PRAGMA table_info({table})"))
        present = {row[1] for row in info.fetchall()}

        for col, col_type in columns.items():
            if col in present:
                continue
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                )
                logger.info(f"数据库迁移[{db_label}]: {table} 已增加 {col} 列")
            except Exception as e:
                logger.error(f"数据库迁移失败[{db_label}]: {table}.{col} -> {e}")

        # 复查: 迁移后仍缺列说明库只读或被锁, 必须立刻暴露而不是继续启动
        recheck = await conn.execute(text(f"PRAGMA table_info({table})"))
        after = {row[1] for row in recheck.fetchall()}
        still_missing = sorted(c for c in columns if c not in after)
        if still_missing:
            first = still_missing[0]
            raise RuntimeError(
                f"数据库 {db_label} 的表 {table} 缺少列 {still_missing}，"
                "且自动迁移未能补齐。常见原因: 数据库文件只读 / 被其他进程占用 / "
                "残留 -wal -shm 文件。请停止所有后端进程后重试，或手动执行: "
                f"ALTER TABLE {table} ADD COLUMN {first} {columns[first]}"
            )
