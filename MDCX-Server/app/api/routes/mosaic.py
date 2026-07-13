"""马赛克识别路由（管理 API）"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager
from app.services import mosaic as mosaic_service

router = APIRouter()


class MosaicConfigUpdate(BaseModel):
    """马赛克配置更新"""
    enabled: Optional[bool] = None
    auto_update_movie: Optional[bool] = None


class IdentifyRequest(BaseModel):
    """识别请求"""
    code: str
    title: Optional[str] = None
    studio: Optional[str] = None


class BatchIdentifyRequest(BaseModel):
    """批量识别请求"""
    codes: list[str]


@router.get("/config")
async def get_mosaic_config():
    """获取马赛克识别配置"""
    cfg = get_config().mosaic
    return {
        "enabled": cfg.enabled,
        "auto_update_movie": cfg.auto_update_movie,
    }


@router.put("/config")
async def update_mosaic_config(req: MosaicConfigUpdate):
    """更新马赛克识别配置"""
    cm = get_config_manager()
    current = cm.config

    if req.enabled is not None:
        current.mosaic.enabled = req.enabled
    if req.auto_update_movie is not None:
        current.mosaic.auto_update_movie = req.auto_update_movie

    cm.save()
    return {"status": "ok"}


@router.post("/identify")
async def identify_mosaic(req: IdentifyRequest):
    """识别单个番号的马赛克类型"""
    result = mosaic_service.identify_mosaic_type(
        code=req.code,
        title=req.title,
        studio=req.studio,
    )
    return {
        "code": result.code,
        "display_name": result.display_name,
        "is_mosaic": result.is_mosaic,
        "is_uncensored": result.is_uncensored,
        "is_chinese": result.is_chinese,
        "confidence": result.confidence,
        "reason": result.reason,
    }


@router.post("/identify-batch")
async def identify_batch(req: BatchIdentifyRequest):
    """批量识别马赛克类型"""
    if not req.codes:
        raise HTTPException(status_code=400, detail="codes 不能为空")

    results = []
    for code in req.codes[:200]:  # 限制单次最多 200 个
        r = mosaic_service.identify_mosaic_type(code=code)
        results.append({
            "code": code,
            "display_name": r.display_name,
            "is_mosaic": r.is_mosaic,
            "is_uncensored": r.is_uncensored,
            "is_chinese": r.is_chinese,
            "confidence": r.confidence,
            "reason": r.reason,
        })

    return {"results": results, "total": len(results)}


@router.get("/uncensored-patterns")
async def list_uncensored_patterns():
    """列出无码番号识别规则（供前端文档展示）"""
    return {
        "patterns": [
            {"pattern": "FC2-PPV-xxxxxxx", "desc": "FC2-PPV 系列（无码）"},
            {"pattern": "HEYZO-xxx", "desc": "Heyzo（无码片商）"},
            {"pattern": "Caribbeancom-xxxxxx", "desc": "加勒比（无码片商）"},
            {"pattern": "1pondo-xxxxxx", "desc": "一本道（无码片商）"},
            {"pattern": "1000giri-xxx", "desc": "1000giri（无码片商）"},
            {"pattern": "Pacopacomama-xxxxxx", "desc": "Pacopacomama（无码片商）"},
            {"pattern": "Muramura-xxxxxx", "desc": "Muramura（无码片商）"},
            {"pattern": "H0930-xxx", "desc": "H0930（无码人妻）"},
            {"pattern": "H4610-xxx", "desc": "H4610（无码素人）"},
            {"pattern": "C0930-xxx", "desc": "C0930（无码人妻）"},
            {"pattern": "Tokyo Hot-xxx", "desc": "Tokyo Hot（无码片商）"},
            {"pattern": "nxxxx", "desc": "n系列（无码）"},
        ],
        "chinese_keywords": mosaic_service.CHINESE_KEYWORDS,
        "censored_format": "ABC-123 / ABC_123（2-6 个字母 + 2-5 位数字）",
    }
