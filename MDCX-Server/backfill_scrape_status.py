"""
刮削 status 回填脚本 — 扫描所有模块库，把已有刮削数据但 status 仍为 pending 的影片标为 scraped。
运行：python backfill_scrape_status.py
"""
import asyncio, sqlite3, os, sys

DB_DIR = "L:/data/database"
MODULES = ["jav", "fc2", "uncensored", "chinese", "western", "pornhub"]

def has_data(row):
    """判断影片是否有刮削数据（title/plot/cover_url/rating 任意有值）"""
    title = row.get("title") or ""
    plot = row.get("plot") or ""
    cover = row.get("cover_url") or ""
    rating = row.get("rating")
    return bool(title.strip()) or bool(plot.strip()) or bool(cover.strip()) or (rating is not None and float(rating) > 0)

async def main():
    for mod in MODULES:
        db_path = os.path.join(DB_DIR, f"{mod}.db")
        if not os.path.exists(db_path):
            print(f"[{mod}] 库不存在: {db_path}")
            continue
        conn = sqlite3.connect(db_path, uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, code, title, plot, cover_url, rating, status FROM movies WHERE status = 'pending'").fetchall()
        to_fix = [(r["id"], r["code"]) for r in rows if has_data(r)]
        if to_fix:
            ids = [f[0] for f in to_fix]
            conn.execute(f"UPDATE movies SET status = 'scraped' WHERE id IN ({','.join('?'*len(ids))})", ids)
            conn.commit()
            print(f"[{mod}] 修复 {len(to_fix)} 部: {', '.join(f[1] for f in to_fix[:10])}{'...' if len(to_fix)>10 else ''}")
        else:
            print(f"[{mod}] 无待修复")
        conn.close()

    print("完成")

asyncio.run(main())
