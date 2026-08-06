import sqlite3, os

def open_ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)

# ---- jav.db ----
jp = "L:/data/database/jav.db"
print("===== jav.db =====", jp)
print("exists:", os.path.exists(jp))
con = open_ro(jp)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tabs = [r[0] for r in cur.fetchall()]
print("tables:", tabs)
movie_tbl = next((t for t in tabs if 'movie' in t.lower()), None)
print("movie table:", movie_tbl)
if movie_tbl:
    cur.execute(f"SELECT COUNT(*) FROM {movie_tbl}")
    total = cur.fetchone()[0]
    print("TOTAL movie records:", total)
    cur.execute(f"PRAGMA table_info({movie_tbl})")
    cols = [c[1] for c in cur.fetchall()]
    print("cols:", cols)
    if 'file_path' in cols:
        cur.execute(f"SELECT file_path FROM {movie_tbl}")
        paths = [r[0] for r in cur.fetchall()]
        print("sample file_path:", paths[:3])
        missing = 0
        for p in paths[:800]:
            if not p:
                missing += 1
                continue
            chk = p.replace("E:\\", "L:/").replace("\\", "/") if isinstance(p, str) and p.startswith("E:") else p
            if not os.path.exists(chk):
                missing += 1
        print(f"checked {min(len(paths),800)}, missing/on-disk-not-found: {missing}")
con.close()

# ---- system.db scan_records ----
sp = "L:/data/database/system.db"
print("\n===== system.db =====", sp)
print("exists:", os.path.exists(sp))
con = open_ro(sp)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
stabs = [r[0] for r in cur.fetchall()]
print("tables:", stabs)
if 'scan_records' in stabs:
    cur.execute("SELECT * FROM scan_records ORDER BY id DESC LIMIT 6")
    names = [d[0] for d in cur.description]
    print("scan_records cols:", names)
    for row in cur.fetchall():
        print(dict(zip(names, row)))
con.close()
print("\nDONE")
