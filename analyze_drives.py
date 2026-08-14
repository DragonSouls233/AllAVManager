# -*- coding: utf-8 -*-
"""验证：目录出现次数 vs actors.movie_count 比例，能否可靠区分演员文件夹 vs 系列文件夹"""
import re
import sqlite3
from collections import Counter

DB = r"L:\data\database\jav.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("SELECT name, movie_count FROM actors")
actor_mc = {r[0]: r[1] for r in cur.fetchall()}

cur.execute("SELECT file_path FROM movies WHERE file_path IS NOT NULL")
fps = [r[0] for r in cur.fetchall()]

_RE_CN = re.compile(r"^[\u4e00-\u9fff]{2,8}$")
_RE_JP = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\u3040-\u30ff]{1,7}$")
_RE_EN = re.compile(r"^[A-Z][a-z]{1,20}(?:[ '-][A-Z]?[a-z]{1,20})*$")

def is_human(s):
    if not s or len(s) > 12: return False
    return bool(_RE_CN.match(s) or _RE_JP.match(s) or _RE_EN.match(s))

folder_cnt = Counter()
for fp in fps:
    parts = [s for s in fp.replace("/", "\\").split("\\") if s]
    for seg in parts[1:-1]:
        if re.match(r"^\[\d{4}-\d{2}-\d{2}\]", seg): continue
        if re.match(r"^[A-Za-z0-9]+[-_][A-Za-z0-9]+([-_][A-Za-z0-9]+)*$", seg): continue
        if "." in seg: continue
        folder_cnt[seg] += 1

print(f"{'目录名':<34}{'目录次数':>7}{'actor匹配':>8}{'比例':>7}  判定")
rows = []
for seg, fc in folder_cnt.items():
    if fc < 3 or not is_human(seg):
        continue
    ac = actor_mc.get(seg, 0)
    ratio = ac / fc if fc else 0
    rows.append((seg, fc, ac, ratio))

for seg, fc, ac, ratio in sorted(rows, key=lambda r: -r[1]):
    tag = "演员" if ratio >= 0.5 else ("系列/收藏" if ratio < 0.3 else "？")
    print(f"{seg:<34}{fc:>7}{ac:>8}{ratio:>7.2f}  {tag}")

conn.close()
