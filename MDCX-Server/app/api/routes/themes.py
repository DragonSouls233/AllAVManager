"""皮肤主题路由（§7.8 皮肤插件机制）

走 /api/v1/themes 前缀，受 MDCX Bearer Token 保护。
提供主题配置管理、预设主题列表、自定义主题 CRUD 能力。
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config.manager import get_config, get_config_manager

router = APIRouter()


# ===== 预设主题（与前端 src/themes/*.json 保持一致）=====

PRESET_THEMES = [
    {
        "name": "default",
        "display_name": "经典蓝紫",
        "description": "与系统默认一致的经典蓝紫色调，清爽舒适",
        "colors": {
            "primary": "#409eff",
            "success": "#67c23a",
            "warning": "#e6a23c",
            "danger": "#f56c6c",
            "info": "#909399",
            "background": "#f0f2f5",
            "surface": "#ffffff",
            "text": "#303133",
            "border": "#ebeef5",
            "link": "#409eff",
        },
        "radius": 8,
        "font_size": 14,
    },
    {
        "name": "midnight",
        "display_name": "午夜深蓝",
        "description": "深邃的午夜蓝调，适合夜间长时间使用的护眼配色",
        "colors": {
            "primary": "#5b8def",
            "success": "#4ade80",
            "warning": "#fbbf24",
            "danger": "#f87171",
            "info": "#94a3b8",
            "background": "#0f172a",
            "surface": "#1e293b",
            "text": "#e2e8f0",
            "border": "#334155",
            "link": "#7dd3fc",
        },
        "radius": 10,
        "font_size": 14,
    },
    {
        "name": "sunset",
        "display_name": "日落橙红",
        "description": "温暖的日落橙红色调，充满活力与热情",
        "colors": {
            "primary": "#f97316",
            "success": "#84cc16",
            "warning": "#facc15",
            "danger": "#ef4444",
            "info": "#94a3b8",
            "background": "#fff7ed",
            "surface": "#ffffff",
            "text": "#431407",
            "border": "#fed7aa",
            "link": "#ea580c",
        },
        "radius": 12,
        "font_size": 14,
    },
    {
        "name": "forest",
        "display_name": "森林绿意",
        "description": "清新的森林绿色调，自然宁静，缓解视觉疲劳",
        "colors": {
            "primary": "#16a34a",
            "success": "#65a30d",
            "warning": "#ca8a04",
            "danger": "#dc2626",
            "info": "#94a3b8",
            "background": "#f0fdf4",
            "surface": "#ffffff",
            "text": "#14532d",
            "border": "#bbf7d0",
            "link": "#15803d",
        },
        "radius": 6,
        "font_size": 14,
    },
    {
        "name": "rose",
        "display_name": "玫瑰粉樱",
        "description": "浪漫的玫瑰粉色调，柔美精致，个性十足",
        "colors": {
            "primary": "#e11d48",
            "success": "#16a34a",
            "warning": "#f59e0b",
            "danger": "#be123c",
            "info": "#94a3b8",
            "background": "#fff1f2",
            "surface": "#ffffff",
            "text": "#4c0519",
            "border": "#fecdd3",
            "link": "#be123c",
        },
        "radius": 14,
        "font_size": 14,
    },
]


# ===== 请求/响应模型 =====

class ThemesConfigUpdate(BaseModel):
    """主题配置更新请求"""
    active_theme: Optional[str] = None
    custom_themes: Optional[list] = None
    auto_detect_system: Optional[bool] = None


class CustomThemeSave(BaseModel):
    """自定义主题保存请求"""
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    colors: dict
    radius: Optional[int] = None
    font_size: Optional[int] = None


# ===== 辅助函数 =====

def _parse_custom_themes(raw: str | None) -> list:
    """解析 custom_themes_json 字段为列表"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _serialize_custom_themes(themes: list) -> str:
    """序列化自定义主题列表为 JSON 字符串"""
    return json.dumps(themes, ensure_ascii=False)


# ===== 路由 =====

@router.get("/config")
async def get_themes_config():
    """获取主题配置"""
    cfg = get_config().themes
    return {
        "active_theme": cfg.active_theme,
        "custom_themes": _parse_custom_themes(cfg.custom_themes_json),
        "auto_detect_system": cfg.auto_detect_system,
    }


@router.put("/config")
async def update_themes_config(req: ThemesConfigUpdate):
    """更新主题配置"""
    cm = get_config_manager()
    current = cm.config

    if req.active_theme is not None:
        current.themes.active_theme = req.active_theme
    if req.custom_themes is not None:
        # 自定义主题列表序列化为 JSON 字符串存储
        current.themes.custom_themes_json = _serialize_custom_themes(
            req.custom_themes
        )
    if req.auto_detect_system is not None:
        current.themes.auto_detect_system = req.auto_detect_system

    cm.save()
    return {"status": "ok"}


@router.get("/presets")
async def get_preset_themes():
    """返回预设主题列表"""
    return {"presets": PRESET_THEMES}


@router.post("/custom")
async def save_custom_theme(req: CustomThemeSave):
    """保存自定义主题（新增或覆盖同名）"""
    cm = get_config_manager()
    current = cm.config

    themes = _parse_custom_themes(current.themes.custom_themes_json)

    # 构造主题对象
    theme = {
        "name": req.name,
        "display_name": req.display_name or req.name,
        "description": req.description or "用户自定义主题",
        "colors": req.colors,
        "radius": req.radius if req.radius is not None else 8,
        "font_size": req.font_size if req.font_size is not None else 14,
    }

    # 覆盖同名主题
    themes = [t for t in themes if t.get("name") != req.name]
    themes.append(theme)

    current.themes.custom_themes_json = _serialize_custom_themes(themes)
    cm.save()
    return {"status": "ok", "theme": theme}


@router.delete("/custom/{name}")
async def delete_custom_theme(name: str):
    """删除自定义主题"""
    cm = get_config_manager()
    current = cm.config

    themes = _parse_custom_themes(current.themes.custom_themes_json)
    before = len(themes)
    themes = [t for t in themes if t.get("name") != name]
    after = len(themes)

    if before == after:
        raise HTTPException(status_code=404, detail=f"自定义主题「{name}」不存在")

    current.themes.custom_themes_json = _serialize_custom_themes(themes)
    # 若删除的是当前激活主题，回退到 default
    if current.themes.active_theme == name:
        current.themes.active_theme = "default"
    cm.save()
    return {"status": "ok"}
