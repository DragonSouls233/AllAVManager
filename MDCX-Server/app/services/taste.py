"""口味画像服务 /taste

只依赖**库内既有行为**，不做任何外部抓取（浏览器历史/书签属隐私且需本机权限，
Peach 在本机客户端里读；服务端版本走库内信号即可）：

- 播放历史 ``play_history`` —— 最强信号
- 影片自身的 ``play_count`` / ``view_status``（用户观看行为，非站点评分）
- 系统库收藏 ``favorite_items``、想要清单 ``wants_items``

🔴 站点刮来的 ``rating`` 一律**不参与**画像：那是源站口碑，不是用户口味。
   否则 PH 等模块数万条 ``rating>=7`` 会把画像污染成「源站高分榜」。

产出三维偏好画像（厂商 / 演员 / 系列）+ 基于画像的「你可能想看」。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from sqlalchemy import select

from app.utils.module_helper import (
    MODULE_MODELS,
    get_module_base,
    get_module_model,
)

logger = logging.getLogger(__name__)

_MODULE_LABELS = {
    "jav": "JAV有码", "uncensored": "JAV无码", "fc2": "FC2", "pornhub": "PORNHUB",
    "anime": "里番", "western": "欧美", "chinese": "国产",
}

# 行为权重：单个影片对某个维度（厂商/演员/系列）的贡献
W_PLAYED = 3.0       # 有播放记录
W_WATCHED = 2.0      # view_status=watched
W_FAVORITE = 2.5     # 被收藏
W_WANTED = 1.0       # 想要 / browsed
TOP_DIMENSIONS = 30
CANDIDATE_LIMIT = 3000  # 候选池：取最近入库的影片，在其上打分，避免全库捞取


def module_label(m: str) -> str:
    return _MODULE_LABELS.get(m, m)


def _split_actors(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [a.strip() for a in str(raw).replace("、", ",").split(",")]
    return [a for a in parts if a and len(a) < 40][:8]


@asynccontextmanager
async def _module_session(module: str):
    """模块库会话：**用完立即归还**，不走 get_session 的请求级延迟回收。

    🔴 taste 一次请求要在 7 个模块上各采集一遍，裸 session 会同时占位到请求结束，
    15 个连接的池会被占满导致后续查询超时。
    """
    from app.db.module_db import ModuleDatabase

    try:
        db = ModuleDatabase.get_instance(module)
    except ValueError:
        # 首次调用必须提供 base_class 以注册表结构
        db = ModuleDatabase.get_instance(module, base_class=get_module_base(module))
    async with db.session_scope() as session:
        yield session


@asynccontextmanager
async def _system_session():
    from app.db.system_db import SystemDatabase

    session = await SystemDatabase.get_instance().get_session()
    try:
        yield session
    finally:
        await session.close()


async def _collect_signals(module: str) -> dict:
    """采集单模块的行为信号，返回该模块的「已看过集」与各维度加权表"""
    Movie = get_module_model(module, "movie")
    PlayHistory = get_module_model(module, "play_history")

    async with _module_session(module) as session:
        played: dict[int, int] = {}
        try:
            rows = (await session.execute(
                select(PlayHistory.movie_id, PlayHistory.id)
            )).all()
            for mid, _pid in rows:
                played[mid] = played.get(mid, 0) + 1
        except Exception as e:
            logger.debug(f"[taste] {module} 播放历史读取失败（表可能不存在）: {e}")

        seen_ids = set(played)
        favorite_ids: set[int] = set()
        wants_codes: set[str] = set()
        try:
            from app.db.system_models import FavoriteItem, WantsItem

            async with _system_session() as sys_session:
                rows = (await sys_session.execute(
                    select(FavoriteItem.entity_id).where(
                        FavoriteItem.module == module,
                        FavoriteItem.entity_type == "movie",
                    )
                )).all()
                favorite_ids = {r[0] for r in rows}
                # 想要的番号也表明偏好（片子可能还没入库）
                wants = (await sys_session.execute(
                    select(WantsItem.normalized_code).where(WantsItem.status == "wanted")
                )).all()
                wants_codes = {r[0] for r in wants}
        except Exception as e:
            logger.debug(f"[taste] {module} 收藏读取失败: {e}")

        seen_ids |= favorite_ids

        cols = (Movie.id, Movie.code, Movie.title, Movie.actor, Movie.studio,
                Movie.series, Movie.rating, Movie.play_count, Movie.view_status,
                Movie.release_date, Movie.cover_url, Movie.studio_id, Movie.series_id,
                Movie.created_at)
        FIELDS = ("id", "code", "title", "actor", "studio", "series", "rating",
                  "play_count", "view_status", "release_date", "cover_url",
                  "studio_id", "series_id", "created_at")

        def to_dict(r) -> dict:
            return dict(zip(FIELDS, r))

        # 🔴 信号只取「真实用户行为」：播放过(play_history) 或 收藏(favorites)。
        # 站点刮来的 rating（PH 库有 4 万+ 条 rating>=7）和 actor==studio 等同字段
        # 一律不当偏好信号，否则画像会失真成「PH 高分频道榜」而不是用户口味。
        signals: list[dict] = []
        if seen_ids:
            rows = (await session.execute(
                select(*cols).where(Movie.id.in_(list(seen_ids)[:2000]))
            )).all()
            signals.extend(to_dict(r) for r in rows)

        # 候选池：最近入库的影片（推荐来源），不含偏好信号
        try:
            cand_rows = (await session.execute(
                select(*cols).order_by(Movie.created_at.desc()).limit(CANDIDATE_LIMIT)
            )).all()
            candidates = [to_dict(r) for r in cand_rows]
        except Exception as e:
            logger.debug(f"[taste] {module} 候选池读取失败: {e}")
            candidates = []

    return {
        "module": module,
        "played": played,
        "favorites": favorite_ids,
        "wants_codes": wants_codes,
        "signals": signals,
        "candidates": candidates,
    }


def _movie_weight(row: dict, played: dict[int, int], favorites: set[int]) -> float:
    """单部影片的正向权重：代表它对各维度的贡献强度"""
    w = 0.0
    mid = row["id"]

    if played.get(mid):
        w += W_PLAYED + min(played[mid], 5) * 0.4
    if row.get("view_status") == "watched":
        w += W_WATCHED
    elif row.get("view_status") in ("browsed", "wanted"):
        w += W_WANTED
    if mid in favorites:
        w += W_FAVORITE
    pc = row.get("play_count") or 0
    if pc > 0:
        w += min(pc, 10) * 0.2
    return w


async def _gather(modules: list[str]) -> list[dict]:
    """逐模块采集；失败模块跳过（库缺表/损坏不该拖垮整个画像）"""
    datas = []
    for m in modules:
        try:
            datas.append(await _collect_signals(m))
        except Exception as e:
            logger.warning(f"[taste] 模块 {m} 采集失败: {type(e).__name__}: {e}")
    return datas


def _top(d: dict[str, float], n: int) -> list[dict]:
    items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
    if not items:
        return []
    mx = items[0][1] or 1.0
    return [{"name": k, "score": round(v, 2), "weight": round(v / mx, 3)} for k, v in items]


def build_profile_from(datas: list[dict]) -> dict:
    """由已采集的数据算画像（纯计算，不碰数据库）"""
    studio_score: dict[str, float] = defaultdict(float)
    actor_score: dict[str, float] = defaultdict(float)
    series_score: dict[str, float] = defaultdict(float)
    evidence_count = 0
    per_module: dict[str, dict] = {}

    for data in datas:
        unique: dict[int, dict] = {}
        for row in data["signals"]:
            unique[row["id"]] = row

        weighted = 0
        for row in unique.values():
            w = _movie_weight(row, data["played"], data["favorites"])
            if w <= 0:
                continue
            weighted += 1
            for name, bucket in (
                ((row.get("studio") or "").strip(), studio_score),
                ((row.get("series") or "").strip(), series_score),
            ):
                if name:
                    bucket[name] += w
            for a in _split_actors(row.get("actor")):
                # 🔴 跳过与厂牌同名的演员：PH 等模块 actor/studio 同字段，
                # 否则厂商榜和演员榜会完全相同（失真）
                if a and a == (row.get("studio") or "").strip():
                    continue
                actor_score[a] += w

        evidence_count += weighted
        per_module[data["module"]] = {
            "label": module_label(data["module"]),
            "evidence": weighted,
            "played": len(data["played"]),
            "favorites": len(data["favorites"]),
        }

    return {
        "studios": _top(studio_score, TOP_DIMENSIONS),
        "actors": _top(actor_score, TOP_DIMENSIONS),
        "series": _top(series_score, TOP_DIMENSIONS),
        "evidence_count": evidence_count,
        "per_module": per_module,
    }


def recommend_from(datas: list[dict], profile: dict, limit: int) -> list[dict]:
    """由同一批数据产出推荐，避免为了推荐再采集一遍"""
    sw = {s["name"]: s["weight"] for s in profile["studios"]}
    aw = {a["name"]: a["weight"] for a in profile["actors"]}
    sew = {s["name"]: s["weight"] for s in profile["series"]}

    out: list[dict] = []
    for data in datas:
        seen_ids = set(data["played"]) | data["favorites"]
        for row in data["candidates"]:
            mid = row["id"]
            if mid in seen_ids or row.get("view_status") == "watched":
                continue  # 看过的不再推荐

            score = 0.0
            reasons: list[str] = []
            studio = (row.get("studio") or "").strip()
            if studio in sw:
                score += sw[studio] * 2.0
                reasons.append(f"厂商 {studio}")
            series = (row.get("series") or "").strip()
            if series in sew:
                score += sew[series] * 1.5
                reasons.append(f"系列 {series}")
            actors = _split_actors(row.get("actor"))
            if actors:
                best = max((aw.get(a, 0.0) for a in actors), default=0.0)
                if best > 0:
                    score += best * 2.5
                    reasons.append(f"演员 {max(actors, key=lambda a: aw.get(a, 0.0))}")

            if score <= 0:
                continue
            out.append({
                "module": data["module"],
                "module_label": module_label(data["module"]),
                "id": mid,
                "code": row.get("code"),
                "title": row.get("title"),
                "cover_url": row.get("cover_url"),
                "release_date": row.get("release_date"),
                "rating": row.get("rating"),
                "actor": row.get("actor"),
                "studio": studio,
                "score": round(score, 3),
                "reasons": reasons[:3],
            })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


async def build_profile(modules: list[str]) -> dict:
    """构建跨模块口味画像"""
    return build_profile_from(await _gather(modules))


async def recommend(modules: list[str], limit: int) -> list[dict]:
    """基于画像推荐「你可能想看」：未看过、且与偏好高分维度匹配的影片

    🔴 内部只采集一次：画像与推荐共用同一批数据（早期版本各采一遍，
    7 模块等于 14 次会话，会打满连接池）。
    """
    datas = await _gather(modules)
    profile = build_profile_from(datas)
    if not profile["evidence_count"]:
        return []
    return recommend_from(datas, profile, limit)
