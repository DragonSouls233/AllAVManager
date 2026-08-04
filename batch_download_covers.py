"""
批量下载 JAV 模块缺失封面脚本
运行方式: python L:\batch_download_covers.py
效果: 扫描 JAV 数据库所有记录，对有 cover_url 但本地无 poster.jpg 的，下载到 L:\data\movies\jav\{code}\poster.jpg
"""

import asyncio
import sqlite3
import os
from pathlib import Path

DATA_BASE = Path("L:/data")
DB_PATH = "L:/data/database/jav.db"
COVERS_DIR = DATA_BASE / "movies" / "jav"

async def download_one(sem: asyncio.Semaphore, client, code: str, url: str, target: Path, referer: str):
    async with sem:
        if target.exists() and target.stat().st_size > 500:
            return f"✅ {code} 已有封面"
        try:
            import httpx
            resp = await asyncio.wait_for(
                client.get(url, headers={"Referer": referer} if referer else None),
                timeout=15.0,
            )
            if resp.status_code == 200 and len(resp.content) > 500:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "wb") as f:
                    f.write(resp.content)
                return f"✅ {code} 下载成功 ({len(resp.content)} bytes)"
            else:
                return f"❌ {code} HTTP {resp.status_code}"
        except Exception as e:
            return f"❌ {code} 失败: {type(e).__name__}"

async def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, cover_url, poster_url, source FROM jav_movies WHERE cover_url IS NOT NULL AND cover_url != ''")
    rows = c.fetchall()
    conn.close()

    print(f"找到 {len(rows)} 条有 cover_url 的记录")

    import httpx
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        tasks = []
        for code, cover_url, poster_url, source in rows:
            target = COVERS_DIR / code / "poster.jpg"
            ref = ""
            if source == "javbus":
                ref = "https://www.javbus.com/"
            elif source == "xcity":
                ref = "https://xcity.jp/"
            elif source == "javdatabase":
                ref = "https://javdatabase.com/"
            url = cover_url or poster_url or ""
            if url:
                tasks.append(download_one(sem, client, code, url, target, ref))

        results = await asyncio.gather(*tasks)
        success = sum(1 for r in results if r.startswith("✅"))
        failed = sum(1 for r in results if r.startswith("❌"))
        for r in results:
            print(r)
        print(f"\n完成: {success} 成功, {failed} 失败")

if __name__ == "__main__":
    asyncio.run(main())
