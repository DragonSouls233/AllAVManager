"""
文件夹归属演员检测 / 回填工具（JAV 有码模块）

背景
----
演员页作品数按 movies.actor 字段匹配统计。很多影片存放在按演员命名的
文件夹里（如 J:\\165-169\\森日向子\\、H:\\多人作品\\木下ひまり,森日向子\\），但
movies.actor 字段没写入这些演员名（素人企划用素人名 / 佚名 / 艺名、多人片只写
部分人），导致该演员作品数少于文件夹里的实际文件数。

检测规则（防误判）
----------------
1. 组合目录（多人作品/共演/コラボ/合作/W主演 等标记）：下一级目录名按分隔符拆成
   多个演员，作为归属 —— 目录结构可靠，满足"多人作品要填写多个演员"。
2. 所有候选目录名（组合拆分出的演员 + 单人目录名）必须通过【前置校验】：
   目录名是【演员名】才能参与本功能 —— 系列/收藏目录（素人/原作改編/催眠系列/
   经典名录 等）不参与。
   前置校验（_is_actor_dir，条件须全部满足）：
   a) 人名规则（纯中文2-8字 / 汉字开头+假名 / 英文人名）
   b) 存在于 actors 表（是已收录演员，而非扫描器兜底收进的系列名）
   c) 不在系列词黑名单（原作改編/催眠系列/洗脳/部屋結界 等被扫描器误收的系列名）
   d) 目录占比校验：该目录名下影片数 ≈ 该演员在 actor 字段的匹配数
      （比例 >= 0.5）。真实演员目录比例约 1.0（如 篠田ゆう 1.02、森日向子 1.13），
      系列/收藏目录比例约 0（素人 0.00、原作改編 0.08、催眠系列 0.00）——
      用比例硬排除"目录名恰好长成人名样子的系列目录"。
"""
from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import func, select

from app.db.module_db import ModuleDatabase
from app.db.jav_models import JavActor, JavMovie

# 组合目录标记：其下一级目录名即为演员列表
COMBO_MARKERS = ("多人作品", "共演", "コラボ", "合作", "合作作品", "多人", "W主演")
# 系列词/分类词黑名单（扫描器曾把这些目录名当演员收进 actors 表，实际是系列名/收藏分类）
SERIES_BLACKLIST = {
    "经典名录", "素人", "经典系列", "美魔女",                    # 收藏/分类目录
    "原作改編", "催眠系列", "洗脳", "洗脳催眠", "部屋結界", "黑船",  # 系列名（被误收进 actors 表）
    "極上自慰幫手", "彼女のお姉さんは", "诱惑ヤリたがり娘", "呼べば即舐め",
    "練習の息抜きと", "連射", "男潮", "挟撃", "現代の国語", "自分の旦",
    "多人作品", "共演", "コラボ", "合作", "合作作品", "多人", "W主演",  # 标记词本身
}
# 组合分隔符（与文件夹命名习惯一致）
_COMBO_SPLIT = re.compile(r"[,，、+&＆|｜/／．.・·\s]+")
# 日期目录 / 番号目录段（跳过）
_RE_DATE_SEG = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]")
_RE_CODE_SEG = re.compile(r"^[A-Za-z0-9]+[-_][A-Za-z0-9]+([-_][A-Za-z0-9]+)*$")
# 人名规则
_RE_CN = re.compile(r"^[\u4e00-\u9fff]{2,8}$")                              # 纯中文
_RE_JP = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\u3040-\u30ff]{1,7}$")  # 汉字开头+假名
_RE_EN = re.compile(r"^[A-Z][a-z]{1,20}(?:[ '-][A-Z]?[a-z]{1,20})*$")       # 英文人名


def _is_human_name(s: str) -> bool:
    if not s or len(s) > 12:
        return False
    if _RE_CODE_SEG.match(s) or _RE_DATE_SEG.match(s):
        return False
    return bool(_RE_CN.match(s) or _RE_JP.match(s) or _RE_EN.match(s))


def _extract_split(file_path: str | None) -> tuple[list[str], list[str]]:
    """从 file_path 提取文件夹归属演员，返回 (组合目录演员, 单人目录演员)"""
    if not file_path:
        return [], []
    parts = [s for s in file_path.replace("/", "\\").split("\\") if s]
    combo_hits, single_hits = [], []
    combo_seen, single_seen = set(), set()
    for i, seg in enumerate(parts):
        if any(m in seg for m in COMBO_MARKERS):
            if i + 1 < len(parts):
                for t in _COMBO_SPLIT.split(parts[i + 1]):
                    t = t.strip()
                    if _is_human_name(t) and t not in combo_seen:
                        combo_hits.append(t)
                        combo_seen.add(t)
            continue
        if _RE_DATE_SEG.match(seg) or _RE_CODE_SEG.match(seg):
            continue
        if _is_human_name(seg):
            if seg not in single_seen:
                single_hits.append(seg)
                single_seen.add(seg)
            continue
        # 段内嵌套组合（如目录名是"木下ひまり,森日向子"但无"多人作品"标记）
        for t in _COMBO_SPLIT.split(seg):
            t = t.strip()
            if t and _is_human_name(t) and t not in single_seen:
                single_hits.append(t)
                single_seen.add(t)
    return combo_hits, single_hits


def extract_folder_actors(file_path: str | None) -> list[str]:
    """从 file_path 提取文件夹归属演员（去重保序，组合在前）"""
    combo_hits, single_hits = _extract_split(file_path)
    return combo_hits + [a for a in single_hits if a not in combo_hits]


def _split_current_actor(actor_str: str | None) -> list[str]:
    return [s.strip() for s in (actor_str or "").split(",") if s.strip()]


def _iter_folder_segs(file_path: str | None):
    """遍历 file_path 的目录段（跳过盘符/文件名/日期段/番号段）"""
    if not file_path:
        return
    parts = [s for s in file_path.replace("/", "\\").split("\\") if s]
    for seg in parts[1:-1]:
        if _RE_DATE_SEG.match(seg) or _RE_CODE_SEG.match(seg):
            continue
        if "." in seg:
            continue
        yield seg


async def _build_dir_index(session) -> tuple[Counter, Counter]:
    """全库统计目录段占比指标

    :return: (folder_cnt, actor_match)
        folder_cnt[seg] = 该目录段名下影片数（全库 file_path 中出现的次数）
        actor_match[seg] = 该名字在 movies.actor 字段中被匹配的影片数（LIKE 语义）
    """
    rows = await session.execute(
        select(JavMovie.file_path, JavMovie.actor).where(JavMovie.file_path.is_not(None))
    )
    folder_cnt: Counter = Counter()
    actors = []
    for fp, actor_str in rows.all():
        for seg in _iter_folder_segs(fp):
            folder_cnt[seg] += 1
        actors.append(actor_str or "")
    actor_match: Counter = Counter()
    for seg, fc in folder_cnt.items():
        if fc < 3 or not _is_human_name(seg):
            continue
        actor_match[seg] = sum(1 for a in actors if seg in a)
    return folder_cnt, actor_match


def _is_actor_dir(seg: str, actor_names: set[str], folder_cnt: Counter, actor_match: Counter) -> bool:
    """前置校验：目录名必须是【演员名】才允许参与本功能

    系列/收藏目录（素人、原作改編、催眠系列、经典名录 等）虽然目录名长成人名
    样子、甚至被扫描器误收进 actors 表，但它们的目录占比 ≈ 0，被硬排除。
    """
    if not _is_human_name(seg):
        return False
    if seg in SERIES_BLACKLIST:
        return False
    if seg not in actor_names:
        return False
    fc = folder_cnt.get(seg, 0)
    ac = actor_match.get(seg, 0)
    if fc > 0 and ac / fc < 0.5:
        return False
    return True


async def analyze(actor_filter: str | None = None) -> dict:
    """扫描全部影片，找出「文件夹归属演员」未写入 movies.actor 的差异项

    :param actor_filter: 仅关注某演员（用于"检测单个演员缺失"）
    :return: {"summary": {...}, "items": [...], "total": n}
    """
    db = ModuleDatabase.get_instance("jav")
    session = await db.get_session()
    try:
        actor_names = set(
            (await session.execute(select(JavActor.name).where(JavActor.name.is_not(None)))).scalars().all()
        )
        folder_cnt, actor_match = await _build_dir_index(session)
        rows = await session.execute(
            select(JavMovie.id, JavMovie.code, JavMovie.title, JavMovie.actor, JavMovie.file_path)
        )
        items = []
        for mid, code, title, actor_str, fp in rows.all():
            combo_hits, single_hits = _extract_split(fp)
            # 前置校验：目录名必须是演员名（在 actors 表 + 人名规则 + 占比合理）
            accepted = {a for a in combo_hits + single_hits if _is_actor_dir(a, actor_names, folder_cnt, actor_match)}
            if not accepted:
                continue
            current = _split_current_actor(actor_str)
            missing = [a for a in accepted if a not in current]
            if not missing:
                continue
            if actor_filter and actor_filter not in missing:
                continue
            items.append({
                "id": mid,
                "code": code,
                "title": title,
                "actor": actor_str or "",
                "folder_actors": combo_hits + [a for a in single_hits if a not in combo_hits],
                "missing": missing,
            })
        by_actor: dict[str, int] = {}
        for it in items:
            for m in it["missing"]:
                by_actor[m] = by_actor.get(m, 0) + 1
        top_actors = sorted(by_actor.items(), key=lambda kv: -kv[1])
        return {
            "summary": {
                "total_movies": len(items),
                "actor_count": len(by_actor),
                "top_actors": [{"name": n, "count": c} for n, c in top_actors[:30]],
            },
            "items": items,
            "total": len(items),
        }
    finally:
        await session.close()


async def apply_fill(actor_filter: str | None = None) -> int:
    """把「文件夹归属演员」追加写入 movies.actor，并重算全部 actor 的 movie_count

    :param actor_filter: 仅回填指定演员相关的影片；None = 全部
    :return: 更新的影片数
    """
    db = ModuleDatabase.get_instance("jav")
    session = await db.get_session()
    try:
        actor_names = set(
            (await session.execute(select(JavActor.name).where(JavActor.name.is_not(None)))).scalars().all()
        )
        folder_cnt, actor_match = await _build_dir_index(session)
        rows = await session.execute(
            select(JavMovie.id, JavMovie.actor, JavMovie.file_path)
        )
        updates = []
        for mid, actor_str, fp in rows.all():
            combo_hits, single_hits = _extract_split(fp)
            # 前置校验：目录名必须是演员名（在 actors 表 + 人名规则 + 占比合理）
            accepted = {a for a in combo_hits + single_hits if _is_actor_dir(a, actor_names, folder_cnt, actor_match)}
            if not accepted:
                continue
            current = _split_current_actor(actor_str)
            missing = [a for a in accepted if a not in current]
            if not missing:
                continue
            if actor_filter and actor_filter not in missing:
                continue
            updates.append((mid, ",".join(current + missing)))
        if updates:
            # 分批写入（避免一次绑定过多参数）
            for i in range(0, len(updates), 500):
                batch = updates[i:i + 500]
                for mid, new_actor in batch:
                    movie = await session.get(JavMovie, mid)
                    if movie is not None:
                        movie.actor = new_actor
                await session.flush()
            await session.commit()
        # 重算 movie_count
        actors = await session.execute(select(JavActor))
        for actor_row in actors.scalars().all():
            count = await session.scalar(
                select(func.count()).select_from(JavMovie).where(
                    JavMovie.actor.like(f"%{actor_row.name}%")
                )
            ) or 0
            actor_row.movie_count = count
        await session.commit()
        return len(updates)
    finally:
        await session.close()
