# -*- coding: utf-8 -*-
"""
文件夹归属演员回填脚本 v3（JAV 有码模块）

问题：演员页作品数按 movies.actor 字段匹配统计。很多影片存放在按演员命名的
文件夹里（如 J:\\165-169\\森日向子\\、H:\\多人作品\\木下ひまり,森日向子\\），但
movies.actor 字段没写入这些演员名，导致演员页作品数少于文件夹里的实际文件数。

v3 回填规则（解决 v1 垃圾占位名 / v2 系列名误判）：
1. 组合目录（多人作品/共演/コラボ/合作/W主演 等标记）：下一级目录名按分隔符拆成
   多个演员，直接回填追加 —— 目录结构可靠，满足"多人作品要填写多个演员"。
2. 单人目录候选名：必须同时满足
   a) 人名规则（纯中文2-8字 / 汉字+假名 / 英文人名）
   b) 存在于 actors 表（排除"经典名录/素人/经典系列"等收藏分类目录）
   c) 不在系列词黑名单（原作改編/催眠系列/洗脳/部屋結界 等被扫描器误收的系列名）
3. 写库后自动重算全部演员 movie_count（列表页排序/过滤依赖它）。

用法：python backfill-folder-actors.py [0|1]   1=预览(默认) 0=执行写库
"""
import functools
import re
import sqlite3
import sys

DB = r"L:\data\database\jav.db"
DRY_RUN = int(sys.argv[1]) if len(sys.argv) > 1 else 1

# 输出立即刷屏（后台运行时便于观察进度）
print = functools.partial(print, flush=True)

# 组合目录标记：其下一级目录名即为演员列表
COMBO_MARKERS = ("多人作品", "共演", "コラボ", "合作", "合作作品", "多人", "W主演")
# 系列词/分类词黑名单（扫描器曾把这些目录名当演员收进 actors 表，实际是系列名/收藏分类）
SERIES_BLACKLIST = {
    # 收藏/分类目录
    "经典名录", "素人", "经典系列", "美魔女",
    # 系列名（被扫描器误收进 actors 表）
    "原作改編", "催眠系列", "洗脳", "洗脳催眠", "部屋結界", "黑船",
    "極上自慰幫手", "彼女のお姉さんは", "诱惑ヤリたがり娘", "呼べば即舐め",
    "練習の息抜きと", "連射", "男潮", "挟撃", "現代の国語", "自分の旦",
    # 标记词本身
    "多人作品", "共演", "コラボ", "合作", "合作作品", "多人", "W主演",
}
# 组合分隔符（与文件夹命名习惯一致）
_COMBO_SPLIT = re.compile(r"[,，、+&＆|｜/／．.・·\s]+")
# 日期目录 / 番号目录段（跳过）
_RE_DATE_SEG = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]")
_RE_CODE_SEG = re.compile(r"^[A-Za-z0-9]+[-_][A-Za-z0-9]+([-_][A-Za-z0-9]+)*$")

# 人名规则
_RE_CN = re.compile(r"^[\u4e00-\u9fff]{2,8}$")                                   # 纯中文
_RE_JP = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\u3040-\u30ff]{1,7}$")       # 汉字开头+假名
_RE_EN = re.compile(r"^[A-Z][a-z]{1,20}(?:[ '-][A-Z]?[a-z]{1,20})*$")            # 英文人名


def is_human_name(s: str) -> bool:
    if not s or len(s) > 12:
        return False
    if _RE_CODE_SEG.match(s) or _RE_DATE_SEG.match(s):
        return False
    return bool(_RE_CN.match(s) or _RE_JP.match(s) or _RE_EN.match(s))


def extract_folder_actors(file_path: str):
    """返回 (组合目录命中的演员, 单人目录命中的演员) —— 分开便于用不同过滤规则"""
    parts = [s for s in file_path.replace("/", "\\").split("\\") if s]
    combo_hits, single_hits = [], []
    combo_seen, single_seen = set(), set()
    for i, seg in enumerate(parts):
        if any(m in seg for m in COMBO_MARKERS):
            # 组合目录：下一级目录名 = 演员列表
            if i + 1 < len(parts):
                for t in _COMBO_SPLIT.split(parts[i + 1]):
                    t = t.strip()
                    if is_human_name(t) and t not in combo_seen:
                        combo_hits.append(t)
                        combo_seen.add(t)
            continue
        if _RE_DATE_SEG.match(seg) or _RE_CODE_SEG.match(seg):
            continue
        if is_human_name(seg):
            if seg not in single_seen:
                single_hits.append(seg)
                single_seen.add(seg)
            continue
        # 段内嵌套组合（如目录名是"木下ひまり,森日向子"但无"多人作品"标记）
        for t in _COMBO_SPLIT.split(seg):
            t = t.strip()
            if t and is_human_name(t) and t not in single_seen:
                single_hits.append(t)
                single_seen.add(t)
    return combo_hits, single_hits


conn = sqlite3.connect(f"file:{DB}?mode={'ro' if DRY_RUN else 'rw'}", uri=True)
conn.execute("PRAGMA busy_timeout = 15000")
cur = conn.cursor()

cur.execute("SELECT name FROM actors")
actor_set = {r[0] for r in cur.fetchall()}

cur.execute("SELECT id, code, actor, file_path FROM movies WHERE file_path IS NOT NULL")
movies = cur.fetchall()
print(f"影片总数(有 file_path): {len(movies)}")

to_update = []
for mid, code, actor_str, fp in movies:
    combo_hits, single_hits = extract_folder_actors(fp)
    accepted = set(combo_hits) | {a for a in single_hits if a in actor_set}
    accepted = {a for a in accepted if a not in SERIES_BLACKLIST}
    if not accepted:
        continue
    current = [s.strip() for s in (actor_str or "").split(",") if s.strip()]
    added = [a for a in accepted if a not in current]
    if added:
        to_update.append((mid, code, actor_str or "", ",".join(current + added), added))

print(f"需回填影片数: {len(to_update)}")
print("=" * 100)

# 按名字汇总
from collections import Counter
name_cnt = Counter()
for mid, code, old, new, added in to_update:
    for a in added:
        name_cnt[a] += 1

print(f"共涉及 {len(name_cnt)} 个演员名：")
for n, c in name_cnt.most_common():
    print(f"  +{n:<20} {c:>5} 部")

print("\n--- 森日向子回填明细（前 45）---")
for mid, code, old, new, added in [t for t in to_update if "森日向子" in t[4]][:45]:
    print(f"[{code}] +{','.join(added)}  | 旧={old}")
hinata = sum(1 for t in to_update if "森日向子" in t[4])
print(f"森日向子回填合计: {hinata} 部（当前 actor 匹配 219 + {hinata} = {219 + hinata}）")

if DRY_RUN:
    print("\n[DRY RUN] 未写库。确认无误后执行: python backfill-folder-actors.py 0")
    conn.close()
    sys.exit(0)

print("\n开始写库...")
cur.executemany(
    "UPDATE movies SET actor = ? WHERE id = ?",
    [(new, mid) for mid, _, _, new, _ in to_update],
)
conn.commit()
print(f"已更新 movies.actor: {len(to_update)} 条")

print("重算 movie_count ...")
cur.execute("SELECT id, name FROM actors WHERE name IS NOT NULL AND name != ''")
for aid, name in cur.fetchall():
    cur.execute("SELECT COUNT(*) FROM movies WHERE actor LIKE ?", (f"%{name}%",))
    cur.execute("UPDATE actors SET movie_count = ? WHERE id = ?", (cur.fetchone()[0], aid))
conn.commit()
print("完成。刷新演员页即可看到更新后的作品数。")
conn.close()
