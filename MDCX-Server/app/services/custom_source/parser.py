"""基于 bs4 的 HTML 字段抽取与 not_found 判定。"""
from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup


def parse_html(html: str, encoding: str = "utf-8") -> BeautifulSoup:
    """把 HTML 文本解析为 BeautifulSoup 对象（优先 lxml，回退 html.parser）。"""
    parser = "lxml" if _has_lxml() else "html.parser"
    return BeautifulSoup(html or "", parser)


_lxml_cache: Optional[bool] = None


def _has_lxml() -> bool:
    global _lxml_cache
    if _lxml_cache is None:
        try:
            import lxml  # noqa: F401

            _lxml_cache = True
        except Exception:  # noqa: BLE001
            _lxml_cache = False
    return _lxml_cache


def _parse_rule(rule: str) -> tuple[str, Optional[str], bool]:
    """解析选择器规则字符串。

    Returns:
        (css_selector, attr_or_None, as_list)
    例：
        ".title"              → (".title", None, False)
        ".poster img @src"    → (".poster img", "src", False)
        ".tags a | list"      → (".tags a", None, True)
        ".tags a @href | list"→ (".tags a", "href", True)
    """
    rule = (rule or "").strip()
    as_list = False
    if rule.endswith("| list") or rule.endswith("|list"):
        as_list = True
        rule = rule.rsplit("|", 1)[0].strip()
    attr: Optional[str] = None
    if "@" in rule:
        css, _, attr = rule.partition("@")
        css = css.strip()
        attr = attr.strip().lower() or None
    else:
        css = rule
    return css, attr, as_list


def extract_value(soup: BeautifulSoup, rule: str) -> Any:
    """按规则从 soup 抽取单个值（str 或 list[str]）。"""
    css, attr, as_list = _parse_rule(rule)
    if not css:
        return [] if as_list else None
    elems = soup.select(css)
    if not elems:
        return [] if as_list else None
    if as_list:
        out = []
        for e in elems:
            v = e.get(attr) if attr else e.get_text(strip=True)
            if v:
                out.append(str(v))
        return out
    e = elems[0]
    if attr:
        return str(e.get(attr)) if e.get(attr) is not None else None
    return e.get_text(strip=True) or None


def extract_fields(soup: BeautifulSoup, fields: dict[str, str]) -> dict[str, Any]:
    """按 fields 映射抽取全部字段。"""
    result: dict[str, Any] = {}
    for key, rule in fields.items():
        val = extract_value(soup, rule)
        if val is None or (isinstance(val, list) and not val):
            continue
        result[key] = val
    return result


def is_not_found(
    html: str,
    not_found_cfg: dict[str, Any],
    *,
    status_code: Optional[int] = None,
) -> bool:
    """判定一次响应是否是「找不到该影片」。

    满足任一条件即返回 True：
    - status_code 在 not_found.status 列表中
    - 正文（小写）包含 not_found.text 任一字符串
    - not_found.selectors 任一 CSS 命中元素
    """
    if not not_found_cfg:
        return False
    # 1) 状态码
    status_list = not_found_cfg.get("status") or []
    if status_code is not None and status_code in status_list:
        return True
    # 2) 正文文本
    texts = not_found_cfg.get("text") or []
    if texts and html:
        low = html.lower()
        if any(str(t).lower() in low for t in texts):
            return True
    # 3) 选择器命中
    selectors = not_found_cfg.get("selectors") or []
    if selectors:
        soup = parse_html(html)
        if any(soup.select(s) for s in selectors if s):
            return True
    return False


def _build_url(template: str, code: str) -> str:
    """把 {code} 占位符替换成番号。"""
    return (template or "").replace("{code}", code)


def normalize_url(url: str, base_url: str) -> str:
    """相对 URL 补全为绝对 URL。"""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    base = base_url.rstrip("/")
    if url.startswith("/"):
        return base + url
    return f"{base}/{url}"


__all__ = [
    "parse_html",
    "extract_value",
    "extract_fields",
    "is_not_found",
    "normalize_url",
]
