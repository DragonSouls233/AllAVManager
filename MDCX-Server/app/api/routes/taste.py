"""口味画像 API /taste

纯库内信号（播放历史 / 评分 / 收藏 / 观看状态 / 想要清单），**不做外部抓取**：
浏览器历史与书签属本机隐私数据，服务端版本刻意不碰，避免给用户意外惊喜。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.services import taste as ts
from app.utils.module_helper import MODULE_MODELS

router = APIRouter()


def _resolve(module: str) -> list[str]:
    """all → 磁盘上存在库文件的模块（不给空模块凭空建库）"""
    from app.config.manager import get_config

    try:
        db_url = get_config().database.url
        base = Path(db_url.split("///")[-1]).parent if "///" in db_url else Path("data/database")
    except Exception:
        base = Path("data/database")

    available = []
    for m in MODULE_MODELS:
        p = base / f"{m}.db"
        try:
            if p.exists() and p.stat().st_size > 0:
                available.append(m)
        except OSError:
            continue

    if module == "all":
        return available
    wanted = [x.strip() for x in module.split(",") if x.strip()]
    bad = [x for x in wanted if x not in MODULE_MODELS]
    if bad:
        raise HTTPException(400, f"未知模块: {bad}，有效值: {list(MODULE_MODELS)} 或 all")
    return [x for x in wanted if x in available]


@router.get("/profile", summary="口味画像")
async def get_profile(module: str = Query("all", description="模块名 / 逗号分隔 / all")):
    """返回厂商 / 演员 / 系列三维偏好，按归一化权重降序。

    ``evidence_count`` 为参与计算的行为影片数；为 0 时说明还没有任何观看行为，
    前端应提示「先去看几部片」而不是展示空图表。
    """
    modules = _resolve(module)
    profile = await ts.build_profile(modules)
    profile["modules"] = [{"key": k, "label": v["label"], **{kk: vv for kk, vv in v.items() if kk != "label"}}
                          for k, v in profile.pop("per_module", {}).items()]
    profile["signal_weights"] = [
        {"name": "播放历史", "weight": ts.W_PLAYED, "desc": "有播放记录，最强信号"},
        {"name": "收藏", "weight": ts.W_FAVORITE, "desc": "加入收藏夹"},
        {"name": "已观看", "weight": ts.W_WATCHED, "desc": "view_status=watched"},
        {"name": "想要/浏览过", "weight": ts.W_WANTED, "desc": "wanted / browsed"},
    ]
    return profile


@router.get("/recommend", summary="按口味推荐")
async def get_recommend(
    module: str = Query("all"),
    limit: int = Query(24, ge=1, le=200),
):
    """推荐未看过且与偏好匹配的影片"""
    modules = _resolve(module)
    items = await ts.recommend(modules, limit)
    return {"total": len(items), "items": items}


@router.get("/stats", summary="行为源统计")
async def get_taste_stats(module: str = Query("all")):
    """各模块可用于画像的行为数据量"""
    modules = _resolve(module)
    per: dict[str, dict] = {}
    for m in modules:
        try:
            data = await ts._collect_signals(m)
            per[m] = {
                "label": ts.module_label(m),
                "played_movies": len(data["played"]),
                "favorites": len(data["favorites"]),
                "signal_movies": len({r["id"] for r in data["signals"]}),
                "candidate_pool": len(data["candidates"]),
            }
        except Exception as e:
            per[m] = {"label": ts.module_label(m), "error": f"{type(e).__name__}: {e}"}
    return {"modules": per}
