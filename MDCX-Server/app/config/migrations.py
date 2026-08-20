"""
配置迁移管线 - 统一处理配置结构变更（借鉴 ref42-Kesuy-mdcx 的 mdcx/config/migrations.py）

MDCX-Server 的 Config 为嵌套 Pydantic 模型（extra="forbid"），所有可恢复的旧配置
差异都应在这里归一化后再交给 Pydantic 做强校验，避免整份配置回退为默认值。

当前迁移项（v1）：
- 类型归一：list 字段以字符串形式出现时转 list（兼容历史手写 config.yaml / 旧 API 格式）
- 代理 scheme 补全：proxy.http / proxy.socks5 缺 scheme 时补 http://
  （ProxyConfig._sync_proxy_fields 依赖 "://" 解析，缺 scheme 会静默失效）
- 命名模板旧语法：{field} -> {{ field }}（Jinja2 兼容，Kesuy 同款转换器）
- config_version 版本标记

约定：
- migrate_config_data 只做纯内存 dict 操作，幂等；有实际变更时由 caller 决定是否写回
- 迁移在 manager._load_unlocked() 内、Config.model_validate 之前调用，
  写回必须走 _save_unlocked（caller 已持锁，避免自我死锁）
"""

import re
from typing import Any

# 当前配置结构版本（models.Config.config_version 与之保持一致）
CURRENT_CONFIG_VERSION = 1

# 可能以字符串形式出现在旧配置中的 list 字段名（递归匹配，任意嵌套层）
_LIST_FIELD_NAMES: frozenset[str] = frozenset(
    {
        # modules.*.media_dirs 及各模块独有 list
        "media_dirs",
        "amateur_media_dirs",
        "folder_pattern",
        "actor_blacklist",
        "video_extensions",
        "trusted_ips",
    }
)


def _str_to_list(v: str | list[Any] | None, sep: str = ",", unique: bool = True) -> list[str]:
    """字符串 -> list（支持中文逗号），列表原样归一；空值 -> []。"""
    if v is None:
        return []
    if isinstance(v, list):
        items = [str(item).strip() for item in v]
    else:
        items = [item.strip() for item in v.replace("，", sep).split(sep)]
    items = [item for item in items if item]
    if unique:
        return list(dict.fromkeys(items))
    return items


def _migrate_list_fields(data: dict[str, Any]) -> None:
    """递归归一：已知 list 字段以 str 出现时转为 list（幂等，list 原样跳过）。"""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _LIST_FIELD_NAMES and isinstance(value, str):
                    node[key] = _str_to_list(value, ",")
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)


def _migrate_proxy_scheme(data: dict[str, Any]) -> None:
    """代理 URL scheme 补全：缺失时补 http://（Kesuy 同款逻辑）。"""
    proxy = data.get("proxy")
    if not isinstance(proxy, dict):
        return
    for key in ("http", "socks5"):
        raw = proxy.get(key)
        if isinstance(raw, str):
            raw = raw.strip()
            if raw and all(
                schema not in raw
                for schema in ("http://", "https://", "socks5://", "socks5h://", "socks4://")
            ):
                proxy[key] = "http://" + raw


def _convert_braced_template(template: str) -> str:
    """旧版 {field} / {?field:content?} 模板 -> Jinja2 写法（Kesuy 同款转换器）。"""
    if "{{" in template or "{%" in template:
        return template

    def replace_field(text: str) -> str:
        return re.sub(r"\{([A-Za-z0-9_]+)\}", r"{{ \1 }}", text)

    while "{?" in template:
        start = template.find("{?")
        colon = template.find(":", start + 2)
        if colon < 0:
            break
        depth = 0
        end = -1
        for index in range(colon + 1, len(template)):
            if template[index] == "{":
                depth += 1
            elif template[index] == "}":
                if depth == 0:
                    end = index
                    break
                depth -= 1
        if end < 0:
            break
        field = template[start + 2 : colon].strip()
        content = replace_field(template[colon + 1 : end])
        optional = f"{{% if {field} %}}{content}{{% endif %}}"
        template = template[:start] + optional + template[end + 1 :]
    return replace_field(template)


def _migrate_naming_templates(data: dict[str, Any]) -> None:
    """命名模板旧语法 {field} -> {{ field }}（Jinja2 兼容）。"""
    naming = data.get("naming")
    if not isinstance(naming, dict):
        return
    for key in ("file_template", "dir_template", "poster_template", "thumb_template"):
        value = naming.get(key)
        if isinstance(value, str):
            naming[key] = _convert_braced_template(value)


def migrate_config_data(data: dict[str, Any]) -> list[str]:
    """统一处理配置结构变更，返回迁移说明列表（供日志记录）。

    所有可恢复的旧配置差异都应在这里归一化，再交给 Pydantic 做强校验。
    函数幂等：对已迁移/新格式配置调用不产生任何变更。
    """
    warnings: list[str] = []
    source_version = data.get("config_version", 1)
    try:
        source_version = int(source_version)
    except (TypeError, ValueError):
        source_version = 1

    _migrate_list_fields(data)
    _migrate_proxy_scheme(data)
    _migrate_naming_templates(data)

    if source_version < CURRENT_CONFIG_VERSION:
        warnings.append(f"配置已从 v{source_version} 迁移到 v{CURRENT_CONFIG_VERSION}")
    data["config_version"] = CURRENT_CONFIG_VERSION
    return warnings
