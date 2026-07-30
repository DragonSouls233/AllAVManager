"""
数据库迁移修复脚本 - 添加 studios.alias 列
由 AI 在 2026-07-30 诊断生成

错误: sqlite3.OperationalError: no such column: studios.alias
原因: Studio ORM 模型新增了 alias 字段，但 SQLite 表结构未同步

使用方法:
  将此文件放到服务器 E:\MDCX-Server 目录下，然后运行:
  cd E:\MDCX-Server
  python fix_db_migration.py
  
  或者直接在服务器任意位置运行:
  python E:\MDCX-Server\fix_db_migration.py

注意: 运行前请确保服务器已停止 (Ctrl+C 停止 uvicorn)
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "database", "scraper.db")

def fix_database():
    if not os.path.exists(DB_PATH):
        print(f"[-] 数据库文件不存在: {DB_PATH}")
        print("[*] 请确认路径是否正确，或直接指定数据库路径:")
        print(f"    python {sys.argv[0]} /path/to/scraper.db")
        return False

    print(f"[*] 连接数据库: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 检查 studios 表当前列
    cursor.execute("PRAGMA table_info(studios)")
    columns = {row[1]: row for row in cursor.fetchall()}
    print(f"[*] studios 表现有列: {list(columns.keys())}")

    fixes = []

    # 1. 修复 studios.alias
    if "alias" not in columns:
        print("[!] studios 表缺少 alias 列，正在添加...")
        cursor.execute("ALTER TABLE studios ADD COLUMN alias TEXT")
        fixes.append("studios.alias")
        print("[+] studios.alias 列已添加")
    else:
        print("[✓] studios.alias 列已存在")

    # 2. 检查 actors 表是否有 name_en 和 alias（迁移 013）
    cursor.execute("PRAGMA table_info(actors)")
    actor_cols = {row[1]: row for row in cursor.fetchall()}
    print(f"[*] actors 表现有列: {list(actor_cols.keys())}")

    if "name_en" not in actor_cols:
        print("[!] actors 表缺少 name_en 列，正在添加...")
        cursor.execute("ALTER TABLE actors ADD COLUMN name_en VARCHAR(100)")
        fixes.append("actors.name_en")
        print("[+] actors.name_en 列已添加")
    else:
        print("[✓] actors.name_en 列已存在")

    if "alias" not in actor_cols:
        print("[!] actors 表缺少 alias 列，正在添加...")
        cursor.execute("ALTER TABLE actors ADD COLUMN alias TEXT")
        fixes.append("actors.alias")
        print("[+] actors.alias 列已添加")
    else:
        print("[✓] actors.alias 列已存在")

    conn.commit()
    conn.close()

    if fixes:
        print(f"\n[✓] 迁移完成，已修复: {', '.join(fixes)}")
    else:
        print("\n[✓] 数据库结构已是最新，无需修复")

    return True

if __name__ == "__main__":
    # 支持通过命令行参数指定数据库路径
    if len(sys.argv) > 1:
        DB_PATH = sys.argv[1]

    print("=" * 50)
    print("   MDCX 数据库迁移修复工具")
    print("=" * 50)
    fix_database()
