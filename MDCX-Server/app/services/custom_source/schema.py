"""自定义来源的 YAML 结构定义与校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # PyYAML
except Exception:  # noqa: BLE001
    yaml = None  # type: ignore[assignment]


# 允许在 not_found / fields 里出现的字段键（白名单，防止误配）
_KNOWN_FIELDS = {
    "title", "cover", "release_date", "duration", "studio", "series",
    "plot", "actors", "genres", "maker", "label", "director", "rating",
    "thumbnail", "preview",
}


@dataclass
class CustomSourceSpec:
    """解析后的规则档。"""
    name: str
    display_name: str
    base_url: str
    enabled: bool = True
    encoding: str = "utf-8"
    search: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    test_cases: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_search(self) -> bool:
        return bool(self.search.get("url"))

    @property
    def has_detail(self) -> bool:
        return bool(self.detail.get("url"))


def load_spec_from_yaml(text: str) -> dict:
    """解析 YAML 文本为 dict；失败抛 ValueError。"""
    if yaml is None:
        raise RuntimeError("PyYAML 未安装，无法解析自定义来源规则档")
    try:
        data = yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"YAML 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("规则档顶层必须是对象")
    return data


def validate_spec(spec: dict) -> list[str]:
    """结构校验。返回错误列表（空列表 = 通过）。

    硬规则（openaver 验收条件）：
    - 必须有 name / base_url
    - 必须有 search 或 detail 至少一个可抓取的 url
    - 必须有 test_cases，且**至少一例 expect == not_found**
    - fields / not_found 里的选择器必须是字符串
    """
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["规则档必须是对象"]
    name = spec.get("name")
    if not name or not isinstance(name, str):
        errors.append("缺少 name（字符串）")
    base_url = spec.get("base_url")
    if not base_url or not isinstance(base_url, str):
        errors.append("缺少 base_url（字符串）")

    search = spec.get("search") or {}
    detail = spec.get("detail") or {}
    if not isinstance(search, dict) or not isinstance(detail, dict):
        errors.append("search / detail 必须是对象")
    if not search.get("url") and not detail.get("url"):
        errors.append("search.url 与 detail.url 至少提供一个")

    # 校验 selectors / fields 结构
    for section_key, section in (("search", search), ("detail", detail)):
        if not section:
            continue
        fields = section.get("fields") or {}
        if not isinstance(fields, dict):
            errors.append(f"{section_key}.fields 必须是对象")
            continue
        for fk, fv in fields.items():
            if fk not in _KNOWN_FIELDS:
                # 非白名单字段允许（用户自定），但必须是字符串
                pass
            if not isinstance(fv, str) or not fv.strip():
                errors.append(f"{section_key}.fields.{fk} 必须是非空字符串选择器")
        nf = section.get("not_found") or {}
        if nf:
            if not isinstance(nf, dict):
                errors.append(f"{section_key}.not_found 必须是对象")
            else:
                for k in ("status", "text", "selectors"):
                    v = nf.get(k)
                    if v is not None and not isinstance(v, list):
                        errors.append(f"{section_key}.not_found.{k} 必须是数组")

    # test_cases 硬规则
    cases = spec.get("test_cases")
    if not isinstance(cases, list) or not cases:
        errors.append("必须提供 test_cases（数组）")
    else:
        if not any(
            isinstance(c, dict) and str(c.get("expect", "")).lower() == "not_found"
            for c in cases
        ):
            errors.append("test_cases 必须至少包含一例 expect: not_found（验收硬条件）")
        for i, c in enumerate(cases):
            if not isinstance(c, dict):
                errors.append(f"test_cases[{i}] 必须是对象")
                continue
            if not c.get("code"):
                errors.append(f"test_cases[{i}] 缺少 code")
            expect = str(c.get("expect", "")).lower()
            if expect not in ("found", "not_found"):
                errors.append(f"test_cases[{i}].expect 必须是 found 或 not_found")
            # not_found 用例最好带可复现的 html fixture（离线验收）
    return errors


def spec_from_dict(spec: dict) -> CustomSourceSpec:
    """把已校验（或未经校验）的 dict 包装成 CustomSourceSpec。"""
    return CustomSourceSpec(
        name=str(spec.get("name", "")),
        display_name=str(spec.get("display_name") or spec.get("name") or ""),
        base_url=str(spec.get("base_url", "")),
        enabled=bool(spec.get("enabled", True)),
        encoding=str(spec.get("encoding") or "utf-8"),
        search=spec.get("search") or {},
        detail=spec.get("detail") or {},
        test_cases=spec.get("test_cases") or [],
    )


def sources_dir() -> Path:
    from app.config.manager import DATA_DIR

    d = Path(DATA_DIR) / "custom_sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = [
    "CustomSourceSpec",
    "load_spec_from_yaml",
    "validate_spec",
    "spec_from_dict",
    "sources_dir",
    "KNOWN_FIELDS",
]
