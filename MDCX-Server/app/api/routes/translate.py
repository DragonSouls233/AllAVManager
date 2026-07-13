"""翻译路由

提供文本翻译能力（标题、简介、演员名等），支持单条/批量翻译，
以及将翻译结果写回到影片的 title 字段。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import Movie
from app.config.manager import get_config
from app.utils.translate import TranslateEngine, TranslateConfig, TranslateService

router = APIRouter()


class TranslateRequest(BaseModel):
    """翻译请求"""
    text: str
    source_lang: Optional[str] = "ja"
    target_lang: Optional[str] = "zh"
    engine: Optional[str] = None  # 不传则用配置中的默认引擎
    api_key: Optional[str] = None  # 不传则用配置中的 key


class TranslateBatchRequest(BaseModel):
    """批量翻译请求"""
    texts: list[str]
    source_lang: Optional[str] = "ja"
    target_lang: Optional[str] = "zh"
    engine: Optional[str] = None
    api_key: Optional[str] = None


class MovieTranslateRequest(BaseModel):
    """影片标题翻译请求"""
    movie_id: int
    field: str = "title"  # 翻译哪个字段: title / plot
    source_lang: Optional[str] = "ja"
    target_lang: Optional[str] = "zh"
    write_back: bool = True  # 是否写回数据库


def _build_service(
    body_engine: Optional[str],
    body_api_key: Optional[str],
    body_source: Optional[str],
    body_target: Optional[str],
) -> TranslateService:
    """根据请求与全局配置构建 TranslateService"""
    cfg = get_config().translate

    engine_str = (body_engine or cfg.engine or "google").lower()
    try:
        engine = TranslateEngine(engine_str)
    except ValueError:
        engine = TranslateEngine.GOOGLE

    config = TranslateConfig(
        engine=engine,
        api_key=body_api_key or cfg.api_key,
        api_base=cfg.api_base,
        source_lang=body_source or cfg.source_lang or "ja",
        target_lang=body_target or cfg.target_lang or "zh",
        model=cfg.model,
        timeout=cfg.timeout or 30,
    )
    return TranslateService(config)


@router.post("")
async def translate_text(req: TranslateRequest):
    """翻译单条文本"""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="文本不能为空")

    service = _build_service(req.engine, req.api_key, req.source_lang, req.target_lang)
    result = await service.translate(req.text)

    if result is None:
        raise HTTPException(status_code=502, detail="翻译失败，请检查 API Key 或网络")

    return {
        "source": req.text,
        "target": result,
        "engine": service.config.engine.value,
        "source_lang": service.config.source_lang,
        "target_lang": service.config.target_lang,
    }


@router.post("/batch")
async def translate_batch(req: TranslateBatchRequest):
    """批量翻译文本"""
    if not req.texts:
        raise HTTPException(status_code=400, detail="文本列表不能为空")

    service = _build_service(req.engine, req.api_key, req.source_lang, req.target_lang)
    results = await service.translate_batch(req.texts)

    return {
        "items": [
            {"source": src, "target": tgt}
            for src, tgt in zip(req.texts, results)
        ],
        "engine": service.config.engine.value,
    }


@router.post("/movie")
async def translate_movie(
    req: MovieTranslateRequest,
    session: AsyncSession = Depends(get_session),
):
    """翻译影片标题或简介，可选写回数据库"""
    movie = await session.get(Movie, req.movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="影片不存在")

    if req.field not in ("title", "plot"):
        raise HTTPException(status_code=400, detail="field 仅支持 title / plot")

    raw = getattr(movie, req.field) if req.field == "title" else movie.plot
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail=f"影片{req.field}为空，无法翻译")

    service = _build_service(None, None, req.source_lang, req.target_lang)
    translated = await service.translate(raw)

    if translated is None:
        raise HTTPException(status_code=502, detail="翻译失败")

    written = False
    if req.write_back:
        # 标题翻译写回 title 字段（保留 original_title 原文）
        if req.field == "title":
            if not movie.original_title:
                movie.original_title = movie.title
            movie.title = translated
        else:
            # 简介翻译追加到 plot 末尾（保留原文）
            movie.plot = f"{movie.plot}\n\n[翻译]\n{translated}"
        await session.commit()
        written = True

    return {
        "movie_id": movie.id,
        "field": req.field,
        "source": raw,
        "target": translated,
        "written_back": written,
    }


@router.get("/config")
async def get_translate_config():
    """获取当前翻译配置（脱敏：不返回 api_key）"""
    cfg = get_config().translate
    return {
        "engine": cfg.engine,
        "api_base": cfg.api_base,
        "source_lang": cfg.source_lang,
        "target_lang": cfg.target_lang,
        "model": cfg.model,
        "timeout": cfg.timeout,
        "has_api_key": bool(cfg.api_key),
        # 支持的引擎列表(便于前端渲染选项)
        "supported_engines": [
            {"value": "google", "label": "Google 翻译", "needs_key": False},
            {"value": "openai", "label": "OpenAI", "needs_key": True},
            {"value": "deepl", "label": "DeepL", "needs_key": True},
            {"value": "baidu", "label": "百度翻译", "needs_key": True, "key_hint": "app_id|api_key"},
            {"value": "bing", "label": "微软 Bing", "needs_key": True},
            {"value": "claude", "label": "Anthropic Claude", "needs_key": True},
        ],
    }
