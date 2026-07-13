"""Schema 字段 UI 组件类型推断工具（§7.9 Schema 驱动设置页）

根据字段名和 JSON Schema 片段，推断前端应使用的 Element Plus 组件类型。
组件类型约定：
    input            普通文本输入框
    password         密码输入框（show-password）
    textarea         多行文本
    input_number     数字输入框
    slider           滑块（适用于范围较小的整数）
    switch           开关
    select           下拉选择（基于 enum）
    date_picker      日期选择器
    color_picker     颜色选择器
    tags_input       标签输入（数组，每项一个 tag）
    directory_picker 目录选择器（input + 浏览按钮）
    json_editor      JSON 编辑器（textarea + 校验）
"""

from __future__ import annotations

from typing import Any


def _normalize(name: str) -> str:
    """将字段名归一化为小写，便于子串匹配"""
    return name.lower().replace("-", "_")


def infer_widget(field_name: str, schema: dict[str, Any]) -> str:
    """根据字段名和 JSON Schema 片段推断 UI 组件类型

    Args:
        field_name: 字段名（如 enabled / api_key / output_dir）
        schema: 字段对应的 JSON Schema 片段（如 {"type": "string", "enum": [...]}）

    Returns:
        widget 类型字符串（见模块文档字符串）
    """
    name = _normalize(field_name)

    # 先解析 anyOf（Optional 字段），提取真实类型
    field_type = schema.get("type")
    if field_type is None and "anyOf" in schema:
        for sub in schema["anyOf"]:
            if isinstance(sub, dict) and sub.get("type") != "null":
                field_type = sub.get("type")
                # 同步 format / enum 等信息到 schema
                if "format" not in schema and "format" in sub:
                    schema = {**schema, "format": sub["format"]}
                if "enum" not in schema and "enum" in sub:
                    schema = {**schema, "enum": sub["enum"]}
                break

    # ===== 1. 复合类型优先（数组/对象）：避免被字段名误判 =====
    # 例如 media_dirs: list[str] 字段名含 _dir 但实际是数组，
    # 应使用 tags_input 而非 directory_picker
    if field_type == "array":
        items = schema.get("items", {})
        # 字符串数组 → tags_input；其他 → textarea（每行一个）
        if isinstance(items, dict) and items.get("type") == "string":
            return "tags_input"
        return "textarea"

    if field_type == "object":
        return "object"

    # ===== 2. 字段名优先匹配（针对标量字段）=====
    if "enabled" in name:
        return "switch"
    # 密码 / 密钥 / Cookie / Token 类字段
    for kw in ("password", "secret", "api_key", "apikey", "cookie", "token"):
        if kw in name:
            return "password"
    if "color" in name:
        return "color_picker"
    # 语言字段 → 选择器（前端会补充 zh/en/ja 选项）
    if "language" in name or name == "lang":
        return "select"
    # 目录 / 路径字段（仅对标量字符串生效）
    if any(k in name for k in ("_dir", "dir_", "directory", "_path", "path_", "filepath")):
        return "directory_picker"
    if name in ("dir", "path", "output_dir"):
        return "directory_picker"
    # 邮箱字段
    if "email" in name:
        return "input"
    # URL / Host 字段（仍用 input，但前端会附 url 校验）
    if any(k in name for k in ("url", "host", "server_url", "rpc_url")):
        return "input"

    # ===== 3. 按 JSON Schema 标量类型匹配 =====
    # 布尔 → switch
    if field_type == "boolean":
        return "switch"

    # 整数 / 数字
    if field_type in ("integer", "number"):
        if "minimum" in schema and "maximum" in schema:
            try:
                lo = float(schema.get("minimum", 0))
                hi = float(schema.get("maximum", 0))
                # 范围 <= 100 用 slider，否则用 input_number
                if hi - lo <= 100:
                    return "slider"
            except (TypeError, ValueError):
                pass
        return "input_number"

    # 字符串
    if field_type == "string":
        # 枚举 → 下拉选择
        if "enum" in schema:
            return "select"
        fmt = schema.get("format", "")
        if fmt == "date":
            return "date_picker"
        if fmt == "json":
            return "json_editor"
        # 模板类字段（如命名模板、URL 模板）→ textarea
        if any(k in name for k in ("template", "format")):
            return "textarea"
        return "input"

    # ===== 4. 默认 =====
    return "input"


def enhance_schema_with_widgets(schema: dict[str, Any]) -> dict[str, Any]:
    """递归地为 schema 中的所有叶子字段添加 widget 字段

    遍历 schema 的 properties，对每个字段调用 infer_widget，并递归处理嵌套对象。

    Args:
        schema: 完整的 JSON Schema（含 properties / $defs 等）

    Returns:
        增强 widget 字段后的 schema（原地修改并返回）
    """
    _enhance_properties(schema)
    return schema


def _enhance_properties(schema_node: dict[str, Any]) -> None:
    """递归处理 schema 节点的 properties"""
    if not isinstance(schema_node, dict):
        return

    properties = schema_node.get("properties")
    if not isinstance(properties, dict):
        return

    for fname, fschema in properties.items():
        if not isinstance(fschema, dict):
            continue

        # 处理嵌套对象：递归
        if fschema.get("type") == "object" and "properties" in fschema:
            _enhance_properties(fschema)
            fschema.setdefault("widget", "object")
            continue

        # 处理 array of objects
        if fschema.get("type") == "array":
            items = fschema.get("items", {})
            if isinstance(items, dict) and items.get("type") == "object":
                _enhance_properties(items)

        # 叶子字段：推断 widget
        if "widget" not in fschema:
            fschema["widget"] = infer_widget(fname, fschema)
