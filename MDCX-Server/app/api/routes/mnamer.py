"""mnamer 智能重命名路由

基于 mnamer 整包(MIT)提供智能元数据识别与重命名能力:
- GET  /health     : 健康检查(mnamer 是否可用 + 版本)
- POST /candidates : 获取候选列表(预览模式,不执行重命名)
- POST /target     : 预览目标路径(指定候选下标,不执行)
- POST /rename     : 执行重命名(指定候选下标)
- GET  /config     : 获取 mnamer 配置(API Key / hits / enabled)
- PUT  /config     : 更新 mnamer 配置

复用 app.services.naming_mnamer_bridge 桥接层,不直接触碰 mnamer 内部。
API Key 从 AppConfig.mnamer 自动读取(§B4)。
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.manager import get_config, get_config_manager
from app.services.naming_mnamer_bridge import (
    build_mnamer_target,
    execute_mnamer_rename,
    is_mnamer_available,
    mnamer_version,
    try_mnamer_fallback,
)

router = APIRouter()


# ============================================================
# 请求模型
# ============================================================
class CandidatesRequest(BaseModel):
    """获取候选列表请求"""

    file_path: str = Field(..., description="视频文件绝对路径")
    hits: Optional[int] = Field(None, ge=1, le=20, description="返回候选数量上限(留空用配置默认值)")


class TargetRequest(BaseModel):
    """预览目标路径请求(不执行重命名)"""

    file_path: str = Field(..., description="视频文件绝对路径")
    match_index: int = Field(..., ge=0, description="选中的候选下标(从 /candidates 返回)")


class RenameRequest(BaseModel):
    """执行重命名请求"""

    file_path: str = Field(..., description="视频文件绝对路径")
    match_index: int = Field(..., ge=0, description="选中的候选下标")


class MnamerConfigUpdate(BaseModel):
    """mnamer 配置更新请求(所有字段可选)"""

    enabled: Optional[bool] = None
    omdb_api_key: Optional[str] = None
    tmdb_api_key: Optional[str] = None
    tvdb_api_key: Optional[str] = None
    hits: Optional[int] = Field(None, ge=1, le=20)
    prefer_move: Optional[bool] = None


# ============================================================
# 健康检查
# ============================================================
@router.get("/health")
async def health():
    """mnamer 引擎健康检查"""
    return {
        "available": is_mnamer_available(),
        "version": mnamer_version(),
    }


# ============================================================
# 获取候选列表(预览,不执行)
# ============================================================
@router.post("/candidates")
async def candidates(req: CandidatesRequest):
    """获取智能重命名候选列表

    返回 guessit 解析字段 + 远端候选(OMDB/TMDB/TVDB,需配置 API Key)。
    本地 guessit 解析无需网络即可工作。
    """
    fp = Path(req.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {req.file_path}")

    if not is_mnamer_available():
        raise HTTPException(status_code=503, detail="mnamer 引擎不可用(整包未正确加载)")

    result = await try_mnamer_fallback(fp, hits=req.hits)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="mnamer 查询失败(文件不存在或引擎内部错误)",
        )

    data = result.to_dict()
    return {
        "source": data["source"],
        "parsed": data["parsed"],
        "candidates": data["candidates"],
        "media_type": data["media_type"],
        "error": data["error"],
        "count": len(data["candidates"]),
    }


# ============================================================
# 预览目标路径(不执行)
# ============================================================
@router.post("/target")
async def preview_target(req: TargetRequest):
    """预览重命名后的目标路径(不实际执行重命名)

    前端在用户点选候选后,先调本端点展示"将重命名为: xxx",
    用户确认后再调 /rename。
    """
    fp = Path(req.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {req.file_path}")

    target = await build_mnamer_target(fp, req.match_index)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail="无法计算目标路径(下标越界或查询无结果)",
        )

    return {
        "original_path": req.file_path,
        "target_path": target,
    }


# ============================================================
# 执行重命名
# ============================================================
@router.post("/rename")
async def rename(req: RenameRequest):
    """执行智能重命名(含目录移动)

    前端流程:
    1. POST /candidates 获取候选列表
    2. 用户选择第 N 个候选
    3. POST /target 预览目标路径(可选,用于二次确认)
    4. POST /rename 执行重命名
    """
    fp = Path(req.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {req.file_path}")

    if not is_mnamer_available():
        raise HTTPException(status_code=503, detail="mnamer 引擎不可用(整包未正确加载)")

    final = await execute_mnamer_rename(fp, req.match_index)
    if final is None:
        raise HTTPException(
            status_code=500,
            detail="重命名失败(下标越界、查询无结果或文件系统错误)",
        )

    return {
        "status": "ok",
        "original_path": req.file_path,
        "final_path": final,
    }


# ============================================================
# 配置管理(§B4)
# ============================================================
@router.get("/config")
async def get_mnamer_config():
    """获取 mnamer 智能重命名配置

    返回 enabled / api_key(掩码) / hits / prefer_move。
    API Key 出于安全考虑返回掩码(仅显示前 4 位 + ****)。
    """
    cfg = get_config().mnamer
    return {
        "enabled": cfg.enabled,
        "omdb_api_key": _mask_key(cfg.omdb_api_key),
        "tmdb_api_key": _mask_key(cfg.tmdb_api_key),
        "tvdb_api_key": _mask_key(cfg.tvdb_api_key),
        "hits": cfg.hits,
        "prefer_move": cfg.prefer_move,
        "has_omdb": bool(cfg.omdb_api_key),
        "has_tmdb": bool(cfg.tmdb_api_key),
        "has_tvdb": bool(cfg.tvdb_api_key),
    }


@router.put("/config")
async def update_mnamer_config(req: MnamerConfigUpdate):
    """更新 mnamer 配置

    所有字段可选,仅更新传入的字段。
    API Key 传入空字符串 "" 可清除已有值(设为 None)。
    使用 mutate_config 直接操作 dict(绕过 _set_nested 的字符串类型假设)。
    """
    cm = get_config_manager()

    def _mutator(cfg: dict[str, Any]) -> None:
        mnamer = cfg.setdefault("mnamer", {})
        if req.enabled is not None:
            mnamer["enabled"] = req.enabled
        if req.omdb_api_key is not None:
            mnamer["omdb_api_key"] = req.omdb_api_key or None
        if req.tmdb_api_key is not None:
            mnamer["tmdb_api_key"] = req.tmdb_api_key or None
        if req.tvdb_api_key is not None:
            mnamer["tvdb_api_key"] = req.tvdb_api_key or None
        if req.hits is not None:
            mnamer["hits"] = req.hits
        if req.prefer_move is not None:
            mnamer["prefer_move"] = req.prefer_move

    errors = cm.mutate_config(_mutator)
    if errors:
        raise HTTPException(status_code=400, detail=f"配置验证失败: {errors}")
    return {"status": "ok"}


def _mask_key(key: str | None) -> str:
    """API Key 掩码:前 4 位 + ****,无 key 返回空字符串。"""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return key[:4] + "****"
