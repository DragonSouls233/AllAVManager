"""Schema 驱动配置路由（§7.9）

根据 Pydantic 模型自动生成 JSON Schema，前端基于 schema 动态渲染表单。
零手写表单，所有配置项由 schema 描述。

路由前缀：/schema
    GET  /                       所有配置段的 schema（按分组组织）
    GET  /values                 所有配置段当前值
    GET  /values/{section}       指定段当前值
    PUT  /values/{section}       更新指定段配置值（带校验）
    POST /validate               校验配置值（不保存）
    GET  /{section}              指定段的 schema（须放最后，避免与上面路径冲突）
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app.config.manager import get_config_manager
from app.config.models import Config
from app.utils.schema_widget import enhance_schema_with_widgets

router = APIRouter()


# ===== 配置段分组（用于左侧导航树）=====
# 顺序即展示顺序；分组名 -> 段名列表
SECTION_GROUPS: list[tuple[str, list[str]]] = [
    ("基础", ["server", "database"]),
    ("刮削", ["scraper", "crawler", "cookiecloud", "watcher"]),
    ("网络", ["proxy", "network_diag"]),
    ("媒体服务器", ["emby", "jellyfin", "emby_compat", "metatube", "tvbox"]),
    ("翻译", ["translate"]),
    ("通知", ["webhook"]),
    ("认证", ["auth"]),
    ("WebDAV", ["webdav_client", "webdav_server"]),
    ("AI 功能", ["face_crop"]),
    ("命名与 STRM", ["naming", "strm"]),
    ("内容控制", ["nsfw", "mosaic"]),
    ("站点优先级", ["site_priority"]),
    ("网盘", ["cloud_drive2", "pan_115"]),
    ("下载器", ["downloader"]),
    ("日志", ["log"]),
    ("主题", ["themes"]),
    ("部署", ["deployment"]),
]


def _get_section_models() -> dict[str, type[BaseModel]]:
    """获取所有配置段名 -> Pydantic 模型类的映射

    遍历 Config 模型的字段，挑出类型为 BaseModel 子类的字段。
    """
    sections: dict[str, type[BaseModel]] = {}
    for field_name, field_info in Config.model_fields.items():
        ann = field_info.annotation
        try:
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                sections[field_name] = ann
        except TypeError:
            continue
    return sections


def _resolve_ref(ref: str, defs: dict[str, Any]) -> dict[str, Any]:
    """解析 $ref 引用，返回被引用的 schema 节点"""
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return {}
    name = ref.rsplit("/", 1)[-1]
    return copy.deepcopy(defs.get(name, {}))


def _flatten_anyof(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """展开 anyOf（Optional 字段），提取非 null 子类型

    Pydantic 对 `str | None` 生成 anyOf [{"type":"string"}, {"type":"null"}]。
    这里把非 null 子类型的 type/format/enum 等信息提升到节点本身。
    """
    if "anyOf" not in node:
        return node

    any_of = node.get("anyOf") or []
    picked: dict[str, Any] | None = None
    for sub in any_of:
        if not isinstance(sub, dict):
            continue
        # 优先选非 null 子类型
        if sub.get("type") == "null":
            continue
        if "$ref" in sub:
            picked = _resolve_ref(sub["$ref"], defs)
        else:
            picked = copy.deepcopy(sub)
        break

    if picked is None:
        return node

    # 合并：保留原节点的 title/description/default，覆盖 type/format/enum
    merged = {k: v for k, v in node.items() if k != "anyOf"}
    for k, v in picked.items():
        # 不覆盖原节点已有的 title/description（更准确）
        if k in ("title", "description") and k in merged:
            continue
        merged[k] = v
    return merged


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """递归地把节点中的 $ref 替换为内联的 $defs 内容，并展开 anyOf"""
    if isinstance(node, dict):
        # 先处理 $ref
        if "$ref" in node:
            resolved = _resolve_ref(node["$ref"], defs)
            # 合并 $ref 之外的字段（如 title、default 可能在外层覆盖）
            merged = {k: v for k, v in node.items() if k != "$ref"}
            for k, v in resolved.items():
                if k not in merged:
                    merged[k] = v
            node = merged

        # 展开 anyOf
        node = _flatten_anyof(node, defs)

        # 递归处理所有子节点
        for k, v in list(node.items()):
            node[k] = _inline_refs(v, defs)
        return node

    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]

    return node


def _build_section_schema(section_name: str, model_cls: type[BaseModel]) -> dict[str, Any]:
    """构造单个配置段的增强 schema

    步骤：
        1. 调用 model_json_schema() 拿到原始 schema（含 $defs / $ref / anyOf）
        2. 内联所有 $ref，展开 anyOf
        3. 删除冗余的 $defs（已全部内联）
        4. 递归地为叶子字段添加 widget 字段
    """
    raw = model_cls.model_json_schema()
    defs = raw.get("$defs", {})

    # 1. 内联 $ref + 展开 anyOf
    inlined = _inline_refs(copy.deepcopy(raw), defs)

    # 2. 删除已无用的 $defs
    inlined.pop("$defs", None)

    # 3. 添加 widget 字段
    enhance_schema_with_widgets(inlined)

    # 4. 补充分段元信息
    inlined["section"] = section_name
    inlined.setdefault("title", section_name)
    inlined.setdefault("description", "")

    return inlined


# ===== 路由 =====
# 注意：FastAPI 按声明顺序匹配路由。/values、/values/{section}、/validate
# 必须声明在 /{section} 之前，否则会被 /{section} 捕获。


@router.get("")
async def get_all_schemas() -> dict[str, Any]:
    """返回所有配置段的 JSON Schema（按分组组织）

    响应结构：
        {
          "groups": [
            {
              "group": "基础",
              "sections": [
                { "section": "server", "title": "...", "properties": {...}, ... },
                ...
              ]
            },
            ...
          ]
        }
    """
    section_models = _get_section_models()

    groups: list[dict[str, Any]] = []
    for group_name, section_names in SECTION_GROUPS:
        sections: list[dict[str, Any]] = []
        for sname in section_names:
            if sname not in section_models:
                continue
            sections.append(_build_section_schema(sname, section_models[sname]))
        if sections:
            groups.append({"group": group_name, "sections": sections})

    return {"groups": groups}


@router.get("/values")
async def get_all_values() -> dict[str, Any]:
    """返回所有配置段的当前值"""
    cfg = get_config_manager().config
    return cfg.model_dump(mode="json")


@router.get("/values/{section}")
async def get_section_values(section: str) -> dict[str, Any]:
    """返回指定配置段的当前值"""
    cfg = get_config_manager().config
    if not hasattr(cfg, section):
        raise HTTPException(status_code=404, detail=f"未知的配置段: {section}")
    section_cfg = getattr(cfg, section)
    if hasattr(section_cfg, "model_dump"):
        return section_cfg.model_dump(mode="json")
    return {"value": section_cfg}


@router.put("/values/{section}")
async def update_section_values(section: str, data: dict[str, Any]) -> dict[str, Any]:
    """更新指定配置段的值（带 Pydantic 校验）

    Args:
        section: 配置段名（如 scraper / proxy / emby 等）
        data: 该段的完整字段值（RequestBody）

    Returns:
        {"status": "ok", "values": {...}}
    """
    cfg = get_config_manager().config
    if not hasattr(cfg, section):
        raise HTTPException(status_code=404, detail=f"未知的配置段: {section}")

    section_models = _get_section_models()
    if section not in section_models:
        raise HTTPException(
            status_code=400,
            detail=f"配置段 {section} 不支持 schema 驱动更新",
        )
    model_cls = section_models[section]

    # 1. 用该段的模型类校验新值
    try:
        new_section_cfg = model_cls.model_validate(data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # 2. 通过 manager 更新（带整体校验 + 重新加载计算配置）
    cm = get_config_manager()
    errors = cm.update(**{section: new_section_cfg.model_dump(mode="json")})
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    # 3. 持久化
    cm.save()

    return {
        "status": "ok",
        "values": getattr(cm.config, section).model_dump(mode="json"),
    }


@router.post("/validate")
async def validate_config(payload: dict[str, Any]) -> dict[str, Any]:
    """校验配置值（不保存）

    RequestBody:
        {
          "section": "scraper",
          "values": { ... }
        }

    Returns:
        {"valid": true/false, "errors": [...]}
    """
    section = payload.get("section")
    values = payload.get("values", {})

    if not section:
        raise HTTPException(status_code=400, detail="缺少 section 字段")

    section_models = _get_section_models()
    if section not in section_models:
        raise HTTPException(status_code=404, detail=f"未知的配置段: {section}")

    model_cls = section_models[section]
    try:
        model_cls.model_validate(values)
        return {"valid": True, "errors": []}
    except ValidationError as e:
        return {"valid": False, "errors": e.errors()}


@router.get("/{section}")
async def get_section_schema(section: str) -> dict[str, Any]:
    """返回指定配置段的 JSON Schema（含 widget 推断）

    Args:
        section: 配置段名（如 scraper / proxy / emby 等）
    """
    section_models = _get_section_models()
    if section not in section_models:
        raise HTTPException(status_code=404, detail=f"未知的配置段: {section}")
    return _build_section_schema(section, section_models[section])
