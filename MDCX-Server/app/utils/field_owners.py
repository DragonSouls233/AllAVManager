"""影片真相字段的归属与防覆盖（移植自 peach field_owners，独立实现，仅借鉴思路）。

peach 为 AGPL-3.0、MDCX 为 MIT，故本文件不复制其源码，只复用其「字段级归属」
模型：每个真相字段记录「当前值是谁写的」，用户手动填写/复核批准的值，自动刮削不得覆盖。

归属串形状：`<写入者类别>:<标识>`
- `user:manual`  用户在界面直接编辑（最高级，任何自动写入者都覆盖不掉）
- `review:<来源>` 用户在来源合并页批准了某来源的候选
- `auto:<来源>`  免复核自动落库
- `script:<脚本>` 维护脚本批量写入

覆盖规则：只有 `user:*` / `review:*` 受保护，其余（无主 / auto / script）谁都能写。

`field_owners` 列存 JSON 字符串：{"title": "user:manual", "plot": "auto:javdb"}。
解析失败（坏 JSON）一律按无主处理——这一列只是留痕，为一行坏数据让详情页 500 不划算。
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

#: 受归属保护的影片真相字段。逻辑名即列名，别处不得另立一套映射。
OWNED_FIELDS: tuple[str, ...] = (
    "title",
    "original_title",
    "plot",
    "studio",
    "series",
    "director",
    "release_date",
    "maker",
    "label",
)

#: 用户在界面上直接编辑。最高一级，任何自动写入者都覆盖不掉。
USER_MANUAL = "user:manual"

#: 来源名 / 脚本名合法形状（拼进 JSON 写库，入口处钉死）。
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]*")

#: 用户的判断，自动写入者不得覆盖。
PROTECTED_PREFIXES: tuple[str, ...] = ("user:", "review:")


def review_owner(provider: str) -> str:
    """用户在来源合并页批准了 `provider` 来源的候选。"""
    return "review:" + _identifier(provider)


def auto_owner(provider: str) -> str:
    """免复核自动落库，取值来自 `provider`。"""
    return "auto:" + _identifier(provider)


def script_owner(name: str) -> str:
    """维护脚本批量写入；`name` 是脚本名，不带 .py。"""
    return "script:" + _identifier(name)


def _identifier(value: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"归属标识只能是小写字母、数字、下划线和连字符：{value!r}")
    return text


def is_protected(owner: str | None) -> bool:
    """这个归属是用户的判断吗；无主和自动写入者都不是。"""
    return str(owner or "").startswith(PROTECTED_PREFIXES)


def parse_owners(value: object) -> dict[str, str]:
    """把 `field_owners` 列解析成 {列名: 归属串}。解析不了就当无主。"""
    if isinstance(value, Mapping):
        parsed: object = value
    else:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            return {}
    if not isinstance(parsed, Mapping):
        return {}
    return {
        str(key): str(owner)
        for key, owner in parsed.items()
        if key in OWNED_FIELDS and isinstance(owner, str) and owner
    }


def owner_of(value: object, field: str | None) -> str:
    """某一个字段现在的归属；无主返回空串。

    兼容直接传 ORM 对象（与 protected_fields 一致）：非 Mapping/字符串时取其
    .field_owners 属性。
    """
    if not field:
        return ""
    if not isinstance(value, (Mapping, str, bytes)):
        value = getattr(value, "field_owners", None)
    return parse_owners(value).get(field, "")


def owner_label(owner: str | None) -> str:
    """归属串给人看的写法；无主返回空串。"""
    kind, _, identifier = str(owner or "").partition(":")
    if kind == "user":
        return "手动填写"
    if kind == "review":
        return f"复核批准 {identifier}"
    if kind == "auto":
        return f"{identifier} 自动落库"
    if kind == "script":
        return f"维护脚本 {identifier}"
    return ""


def protected_fields(obj: Any) -> set[str]:
    """返回 `obj` 上当前受保护的字段集合（user:/review: 归属的字段）。

    `obj` 可以是 ORM 实例（读 .field_owners 属性）或普通 dict（读 ['field_owners']）。
    """
    if isinstance(obj, dict):
        raw = obj.get("field_owners")
    else:
        raw = getattr(obj, "field_owners", None)
    return {f for f, o in parse_owners(raw).items() if is_protected(o)}


def mark_owner(obj: Any, fields: list[str], owner: str = USER_MANUAL) -> list[str]:
    """把 `fields` 标记为 `owner` 归属，写回 `obj.field_owners`。

    只接受 OWNED_FIELDS 内的字段；其余忽略。返回本次「新标记」的字段清单
    （已标记同归属的不重复返回，方便调用方判断要不要记日志）。

    `obj` 可以是 ORM 实例或 dict。写回统一存 JSON 字符串。
    """
    kind, _, identifier = owner.partition(":")
    if kind not in {"user", "review", "auto", "script"}:
        raise ValueError(f"归属串类别不在清单里：{owner!r}")
    _identifier(identifier)

    cleaned = [f for f in fields if f in OWNED_FIELDS]
    if isinstance(obj, dict):
        current = dict(parse_owners(obj.get("field_owners")))
    else:
        current = dict(parse_owners(getattr(obj, "field_owners", None)))

    newly = [f for f in cleaned if current.get(f) != owner]
    if not newly:
        return []
    current.update({f: owner for f in cleaned})
    payload = json.dumps(current, ensure_ascii=False)
    if isinstance(obj, dict):
        obj["field_owners"] = payload
    else:
        setattr(obj, "field_owners", payload)
    return newly
