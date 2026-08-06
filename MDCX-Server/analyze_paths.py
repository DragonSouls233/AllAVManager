import sqlite3, os, statistics
from collections import Counter

con = sqlite3.connect("file:L:/data/database/jav.db?mode=ro", uri=True)
cur = con.cursor()
cur.execute("SELECT file_path FROM movies")
rows = cur.fetchall()
paths = [r[0] for r in rows if r[0]]
print("total records with path:", len(paths))

drives = Counter()
lengths = []
over260 = 0
over240 = 0
for p in paths:
    drives[p[:2]] += 1
    l = len(p)
    lengths.append(l)
    if l > 260:
        over260 += 1
    if l > 240:
        over240 += 1

print("drive prefixes:", drives.most_common())
print("len min/mean/max:", min(lengths), round(statistics.mean(lengths), 1), max(lengths))
print(f"paths > 260 chars (MAX_PATH bug zone): {over260} ({over260/len(paths)*100:.1f}%)")
print(f"paths > 240 chars: {over240} ({over240/len(paths)*100:.1f}%)")

# 抽样最长的 5 条
longest = sorted(paths, key=len, reverse=True)[:5]
print("\nLongest 5 paths:")
for p in longest:
    print(f"  [{len(p)}] {p}")
con.close()
print("\nDONE")
