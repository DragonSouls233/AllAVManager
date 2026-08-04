"""
数据库迁移脚本 - 为 favorite_items 表添加 module 字段
运行方式: python L:\migrate_db.py

说明：
- favorite_items 表新增 module 字段（TEXT, DEFAULT ''）
- 唯一约束改为 (group_id, entity_id, module)
- 中心数据库 scraper.db 各模块数据库不需要修改
"""

import sqlite3
import os
import shutil
from pathlib import Path

DB_DIR = Path("L:/data/database")
BACKUP_DIR = DB_DIR / "backup_before_migrate"
DB_PATH = DB_DIR / "scraper.db"


def backup_db(db_path: Path):
    """备份数据库"""
    backup_dir = Path("L:/data/database/backup_before_migrate")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / db_path.name
    shutil.copy2(str(db_path), str(backup_path))
    print(f"  ✅ 已备份到: {backup_path}")
    return backup_path


def migrate_favorite_items(db_path: Path):
    """为 favorite_items 表添加 module 字段并重建唯一约束"""
    print(f"\n📦 处理: {db_path}")

    if not db_path.exists():
        print(f"  ⚠️  文件不存在，跳过")
        return

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # 检查表是否存在
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='favorite_items'")
    if not c.fetchone():
        print(f"  ⚠️  favorite_items 表不存在，跳过")
        conn.close()
        return

    # 检查 module 字段是否已存在
    c.execute("PRAGMA table_info(favorite_items)")
    cols = {row[1] for row in c.fetchall()}

    if "module" in cols:
        print(f"  ✅ module 字段已存在，跳过")
        conn.close()
        return

    # 备份
    backup_db(db_path)

    # 添加 module 字段
    c.execute('ALTER TABLE favorite_items ADD COLUMN module TEXT DEFAULT ""')
    print("  ✅ 已添加 module 字段 (TEXT, DEFAULT '')")

    # 删除旧唯一约束并重建（SQLite 需要重建表）
    # 步骤1: 获取原表结构
    c.execute("PRAGMA table_info(favorite_items)")
    all_cols = [row[1] for row in c.fetchall()]

    # 步骤2: 创建新表
    new_table_sql = f"""CREATE TABLE favorite_items_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL REFERENCES favorite_groups(id) ON DELETE CASCADE,
        entity_id INTEGER NOT NULL,
        entity_type VARCHAR(20) NOT NULL,
        module VARCHAR(20) DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (group_id) REFERENCES favorite_groups(id) ON DELETE CASCADE
    )"""

    c.execute("DROP TABLE IF EXISTS favorite_items_new")
    c.execute(new_table_sql)
    print("  ✅ 已创建新表 (含唯一约束)")

    # 步骤3: 复制数据
    col_list = ", ".join(all_cols)
    c.execute(f"INSERT INTO favorite_items_new ({col_list}) SELECT {col_list} FROM favorite_items")
    row_count = c.rowcount if c.rowcount > 0 else 0
    print(f"  📋 已复制 {len(c.execute(f'SELECT COUNT(*) FROM favorite_items').fetchone()[0])} 条数据")

    # 步骤4: 删除旧表，重命名新表
    c.execute("DROP TABLE favorite_items")
    c.execute("ALTER TABLE favorite_items_new RENAME TO favorite_items")
    print("  ✅ 表结构重建完成")

    # 步骤5: 重新创建唯一索引（SQLite 会在 ALTER TABLE 时丢弃索引）
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_favorite_items_uniq ON favorite_items(group_id, entity_id, module)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_favorite_items_group ON favorite_items(group_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_favorite_items_entity ON favorite_items(entity_id)")
    print("  ✅ 索引重建完成")

    conn.commit()
    conn.close()
    print(f"  🎉 迁移完成")


def migrate_module_dbs():
    """为模块数据库添加 actor 和 movie 的 module 标识字段（如果需要）"""
    modules = ["jav", "fc2", "chinese", "uncensored", "western", "pornhub"]
    for mod in modules:
        db_path = DB_DIR / f"{mod}.db"
        if not db_path.exists():
            continue
        # 模块数据库不需要改 favorite_items（他们用独立库）
        # 这里可以放后续其他迁移


if __name__ == "__main__":
    print("=" * 60)
    print("  MDCX 数据库迁移脚本")
    print("  说明: 为 favorite_items 表添加 module 字段")
    print("=" * 60)

    migrate_favorite_items(DB_PATH)
    migrate_module_dbs()

    print("\n" + "=" * 60)
    print("  迁移完成！")
    print("  如需回滚，可从以下目录恢复备份:")
    print(f"    {BACKUP_DIR}")
    print("=" * 60)
