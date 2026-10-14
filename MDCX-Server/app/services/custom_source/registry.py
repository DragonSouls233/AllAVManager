"""自定义来源规则档的登记、持久化与离线验收。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from app.services.custom_source import crawler as _crawler
from app.services.custom_source.parser import is_not_found
from app.services.custom_source.schema import (
    CustomSourceSpec,
    load_spec_from_yaml,
    spec_from_dict,
    validate_spec,
)

_EXT = ".yaml"


def _safe_name(name: str) -> str:
    base = os.path.basename(str(name)).replace("\\", "/").split("/")[-1]
    if base.endswith(_EXT):
        base = base[: -len(_EXT)]
    # 只允许字母数字下划线连字符，避免路径穿越
    cleaned = "".join(c for c in base if c.isalnum() or c in "-_")
    return cleaned or "unnamed"


def load_all() -> list[tuple[CustomSourceSpec, list[str]]]:
    """读取 data/custom_sources 下所有 YAML，返回 (spec, errors) 列表。"""
    d = _sources_dir()
    out: list[tuple[CustomSourceSpec, list[str]]] = []
    for p in sorted(d.glob(f"*{_EXT}")):
        try:
            text = p.read_text(encoding="utf-8")
            spec = spec_from_dict(load_spec_from_yaml(text))
            errors = validate_spec(load_spec_from_yaml(text))
        except Exception as e:  # noqa: BLE001
            out.append((CustomSourceSpec(name=p.stem, display_name=p.stem, base_url=""),
                        [f"读取失败: {e}"]))
            continue
        out.append((spec, errors))
    return out


def save_spec(name: str, yaml_text: str) -> tuple[CustomSourceSpec, list[str]]:
    """校验并保存一个规则档。返回 (spec, errors)。errors 非空时不落盘。"""
    spec_dict = load_spec_from_yaml(yaml_text)
    errors = validate_spec(spec_dict)
    spec = spec_from_dict(spec_dict)
    if errors:
        return spec, errors
    d = _sources_dir()
    path = d / f"{_safe_name(name or spec.name)}{_EXT}"
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml_text, encoding="utf-8")
    os.replace(tmp, path)
    return spec, []


def delete_spec(name: str) -> bool:
    path = _sources_dir() / f"{_safe_name(name)}{_EXT}"
    if path.exists():
        path.unlink()
        return True
    return False


def run_test_cases(spec_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """离线运行规则档里的 test_cases（用内联 html fixture 验收）。

    每条用例：
    - 若含 ``html``（搜索页 fixture），用假 http_get 喂给它；
    - 若含 ``detail_html``，详情页也喂 fixture；
    - 断言 ``expect`` 与实测（found / not_found）一致。

    Returns: 每条 [{code, expect, got, passed, detail}]
    """
    import asyncio

    from app.services.custom_source.schema import spec_from_dict

    spec = spec_from_dict(spec_dict)
    results: list[dict[str, Any]] = []

    async def _run() -> None:
        for case in spec.test_cases:
            code = str(case.get("code", ""))
            expect = str(case.get("expect", "")).lower()
            search_html = case.get("html")
            detail_html = case.get("detail_html")
            captured_detail_link = case.get("detail_url")

            async def _fake_get(url, *, method="GET", headers=None, encoding="utf-8"):
                # 详情页请求优先用 detail_html，否则回退搜索 fixture
                if detail_html is not None and captured_detail_link and captured_detail_link in url:
                    return 200, str(detail_html)
                return 200, str(search_html if search_html is not None else "")

            found = False
            detail = ""
            try:
                res = await _crawler.scrape_with_spec(spec, code, _fake_get, encoding=spec.encoding)
                found = res is not None
                if not found and search_html is not None:
                    # 解释为何判 not_found
                    if is_not_found(str(search_html), spec.search.get("not_found") or {},
                                    status_code=200):
                        detail = "not_found 规则命中"
                    else:
                        detail = "未抽到标题"
            except Exception as e:  # noqa: BLE001
                detail = f"异常: {e}"
                found = False

            passed = (expect == "found" and found) or (expect == "not_found" and not found)
            results.append({
                "code": code,
                "expect": expect,
                "got": "found" if found else "not_found",
                "passed": passed,
                "detail": detail,
            })

    asyncio.run(_run())
    return results


def _sources_dir() -> Path:
    from app.services.custom_source.schema import sources_dir

    return sources_dir()


__all__ = [
    "load_all",
    "save_spec",
    "delete_spec",
    "run_test_cases",
]
