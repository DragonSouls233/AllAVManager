# -*- coding: utf-8 -*-
"""验证前置校验 _is_actor_dir 在真实 jav.db 上的通过/拒绝结果"""
import re
import sqlite3
from collections import Counter

DB = r"L:\data\database\jav.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("SELECT name FROM actors")
actor_names = {r[0] for r in cur.fetchall()}

cur.execute("SELECT file_path, actor FROM movies WHERE file_path IS NOT NULL")
rows = cur.fetchall()

_RE_CN = re.compile(r"^[\u4e00-\u9fff]{2,8}$")
_RE_JP = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\u3040-\u30ff]{1,7}$")
_RE_EN = re.compile(r"^[A-Z][a-z]{1,20}(?:[ '-][A-Z]?[a-z]{1,20})*$")
_RE_DATE_SEG = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]")
_RE_CODE_SEG = re.compile(r"^[A-Za-z0-9]+[-_][A-Za-z0-9]+([-_][A-Za-z0-9]+)*$")

def is_human(s):
    if not s or len(s) > 12: return False
    if _RE_CODE_SEG.match(s) or _RE_DATE_SEG.match(s): return False
    return bool(_RE_CN.match(s) or _RE_JP.match(s) or _RE_EN.match(s))

def iter_folder_segs(fp):
    parts = [s for s in fp.replace("/", "\\").split("\\") if s]
    for seg in parts[1:-1]:
        if _RE_DATE_SEG.match(seg) or _RE_CODE_SEG.match(seg): continue
        if "." in seg: continue
        yield seg

folder_cnt, actor_match = Counter(), Counter()
actors = []
for fp, actor_str in rows:
    for seg in iter_folder_segs(fp):
        folder_cnt[seg] += 1
    actors.append(actor_str or "")
for seg, fc in folder_cnt.items():
    if fc < 3 or not is_human(seg): continue
    actor_match[seg] = sum(1 for a in actors if seg in a)

# 模拟 SERIES_BLACKLIST（与 folder_actor_check 同步）
SERIES_BLACKLIST = {
    "经典名录", "素人", "经典系列", "美魔女",
    "原作改編", "催眠系列", "洗脳", "洗脳催眠", "部屋結界", "黑船",
    "極上自慰幫手", "彼女のお姉さんは", "诱惑ヤリたがり娘", "呼べば即舐め",
    "練習の息抜きと", "連射", "男潮", "挟撃", "現代の国語", "自分の旦",
    "多人作品", "共演", "コラボ", "合作", "合作作品", "多人", "W主演",
}

def is_actor_dir(seg):
    if not is_human(seg): return False
    if seg in SERIES_BLACKLIST: return False
    if seg not in actor_names: return False
    fc = folder_cnt.get(seg, 0)
    ac = actor_match.get(seg, 0)
    if fc > 0 and ac / fc < 0.5: return False
    return True

print(f"{'目录名':<34}{'目录数':>6}{'actor匹配':>8}{'比例':>7}  前置结果")
print("-" * 78)
# 有意义的段：目录数>=3 且能当候选（不论演员表）
cands = sorted({seg for seg in folder_cnt if folder_cnt[seg] >= 3}, key=lambda s: -folder_cnt[s])
pass_cnt = rej_cnt = 0
for seg in cands:
    fc, ac = folder_cnt[seg], actor_match.get(seg, 0)
    ok = is_actor_dir(seg)
    if ok: pass_cnt += 1
    else: rej_cnt += 1
    print(f"{seg:<34}{fc:>6}{ac:>8}{ac/fc if fc else 0:>7.2f}  {'通过' if ok else '拒绝'}")
print(f"\n通过 {pass_cnt} / 拒绝 {rej_cnt}")
conn.close()
