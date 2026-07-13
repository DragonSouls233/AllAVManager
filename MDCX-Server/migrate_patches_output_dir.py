"""迁移脚本：把补刮产物从错误的 E:\data\movies 迁移到 E:\MDCX-Server\data\movies。

历史 bug：detector.py 用 .parent.parent.parent.parent 算 PROJECT_ROOT，
导致 E:\data\movies（应该是 E:\MDCX-Server\data\movies）。
本脚本一次性迁移文件 + 更新 DB。

用法:
    python migrate_patches_output_dir.py --dry-run   # 只看不改
    python migrate_patches_output_dir.py --yes       # 实际执行
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from app.config.manager import PROJECT_ROOT

WRONG_ROOT = PROJECT_ROOT.parent / "data" / "movies"   # E:\data\movies
RIGHT_ROOT = PROJECT_ROOT / "data" / "movies"          # E:\MDCX-Server\data\movies


def gather_old_dirs() -> list[Path]:
    if not WRONG_ROOT.exists():
        return []
    return [p for p in WRONG_ROOT.iterdir() if p.is_dir()]


def migrate_files(dry_run: bool) -> dict:
    """移动文件，合并已存在的目录。"""
    RIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    moved = 0
    skipped = 0
    errors = 0
    for old_dir in gather_old_dirs():
        new_dir = RIGHT_ROOT / old_dir.name
        if new_dir.exists():
            # 目标已存在，合并
            for f in old_dir.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(old_dir)
                target = new_dir / rel
                if target.exists():
                    skipped += 1
                    continue
                if dry_run:
                    print(f"  [DRY] merge: {f} -> {target}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(target))
                moved += 1
            # 清空空目录
            if not dry_run:
                for p in sorted(old_dir.rglob("*"), reverse=True):
                    if p.is_dir() and not any(p.iterdir()):
                        p.rmdir()
                try:
                    old_dir.rmdir()
                except OSError:
                    pass
        else:
            if dry_run:
                print(f"  [DRY] move: {old_dir} -> {new_dir}")
            else:
                shutil.move(str(old_dir), str(new_dir))
            moved += 1
    return {"moved": moved, "skipped": skipped, "errors": errors}


async def migrate_db(dry_run: bool) -> int:
    from sqlalchemy import select, update
    from app.db.database import async_session_maker
    from app.db.models import Movie

    updated = 0
    wrong_prefix = str(WRONG_ROOT).replace("\\", "\\\\")
    right_prefix = str(RIGHT_ROOT).replace("\\", "\\\\")

    async with async_session_maker() as session:
        # 找所有 output_dir 指向 WRONG_ROOT 的记录
        stmt = select(Movie).where(Movie.output_dir.like(f"{wrong_prefix}%"))
        result = await session.execute(stmt)
        movies = result.scalars().all()
        print(f"  DB 找到 {len(movies)} 条需迁移记录")
        for m in movies:
            if not m.output_dir:
                continue
            new_path = m.output_dir.replace(str(WRONG_ROOT), str(RIGHT_ROOT), 1)
            if dry_run:
                print(f"  [DRY] movie {m.id} {m.code}: {m.output_dir} -> {new_path}")
            else:
                m.output_dir = new_path
            updated += 1
        if not dry_run and updated:
            await session.commit()
    return updated


def main():
    parser = argparse.ArgumentParser(description="迁移补刮 output_dir 错误路径")
    parser.add_argument("--dry-run", action="store_true", help="只看不改")
    parser.add_argument("--yes", action="store_true", help="实际执行（必需）")
    parser.add_argument("--files-only", action="store_true", help="只迁移文件，不动 DB")
    parser.add_argument("--db-only", action="store_true", help="只迁移 DB，不动文件")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        print("必须指定 --dry-run 或 --yes")
        sys.exit(1)

    print("=" * 60)
    print(f"  MDCX 补刮 output_dir 迁移工具")
    print("=" * 60)
    print(f"  源 (错误): {WRONG_ROOT}")
    print(f"  目标 (正确): {RIGHT_ROOT}")
    print(f"  PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"  模式: {'DRY-RUN' if args.dry_run else 'ACTUAL'}")
    print("=" * 60)

    if not WRONG_ROOT.exists():
        print(f"\n源目录不存在，无需迁移: {WRONG_ROOT}")
        return 0

    if not args.db_only:
        print("\n[1/2] 迁移文件...")
        r = migrate_files(args.dry_run)
        print(f"  结果: {r}")
    if not args.files_only:
        print("\n[2/2] 迁移 DB...")
        n = asyncio.run(migrate_db(args.dry_run))
        print(f"  更新: {n} 条记录")

    print("\n" + "=" * 60)
    if args.dry_run:
        print("DRY-RUN 完成。实际执行请加 --yes")
    else:
        print("迁移完成 ✅")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
