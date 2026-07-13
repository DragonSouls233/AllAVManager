"""
app/utils/i18n.py — MDCX-Server 国际化核心模块

借鉴 OpenAver core/i18n.py,适配 MDCX-Server 的 FastAPI + Pydantic 架构。

提供:
- load_locale(): 载入并缓存 locale JSON
- t(): 带 fallback chain 的翻译函数(永不抛异常)
- get_merged_translations(): 深合并 zh-CN base + overlay(供前端 window.__i18n)
- detect_locale_from_accept_language(): 解析 HTTP Accept-Language header

locale 文件位置: data/locales/{zh_CN,zh_TW,en,ja}.json
fallback 顺序: 当前 locale → zh-CN(base) → [key]
"""

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

# locale 文件目录:data/locales/
# 与 data/config/ 同级,运行时由 ConfigManager 创建
LOCALES_DIR = Path("data") / "locales"
SUPPORTED_LOCALES = ("zh-CN", "zh-TW", "ja", "en")
FALLBACK_LOCALE = "zh-CN"  # MDCX-Server 以简体中文为 base(与 AGENTS.md 一致)


@lru_cache(maxsize=8)
def load_locale(locale: str) -> dict:
    """载入并缓存一个 locale 的 JSON。找不到时回传空 dict。

    借鉴 OpenAver load_locale:用 lru_cache 缓存,零重复 I/O。
    """
    if not locale:
        return {}
    filename = locale.replace("-", "_") + ".json"
    path = LOCALES_DIR / filename
    if not path.exists():
        logger.debug(f"[i18n] locale 档案不存在: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[i18n] 无法载入 locale 档案 {path}: {e}")
        return {}


def _nested_get(data: dict, key: str):
    """dot-path 取值;找不到回传 None。

    借鉴 OpenAver _nested_get:支持 "search.button.search_all" 嵌套 key。
    """
    if not key:
        return None
    parts = key.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _substitute_params(text: str, params: dict) -> str:
    """用 {placeholder} 格式替换参数。缺少的 param 保留原样。永不抛例外。

    借鉴 OpenAver _substitute_params:正则 re.sub(r"\\{(\\w+)\\}", replacer, text)
    """
    if not params:
        return text

    def replacer(match):
        key = match.group(1)
        if key in params:
            return str(params[key])
        return match.group(0)  # 保留 {placeholder} 原样

    try:
        return re.sub(r"\{(\w+)\}", replacer, text)
    except Exception:
        return text


def t(key: str, locale: str = FALLBACK_LOCALE, **params) -> str:
    """翻译函数,fallback chain: 当前 locale → zh-CN → [key]

    借鉴 OpenAver t():永不抛异常,找不到 key 时返回 "[key]"。
    params 以 {placeholder} 格式填入(缺 param 保留原样)。

    Args:
        key: dot-path 翻译键(如 "error.validation")
        locale: 目标 locale(如 "zh-CN" / "en" / "ja")
        **params: 参数替换(如 t("scraper.scrape_failed", number="ABC-123"))

    Returns:
        翻译后的字符串,找不到时返回 "[key]"
    """
    try:
        effective_locale = locale if locale else FALLBACK_LOCALE

        # 尝试当前 locale
        if effective_locale != FALLBACK_LOCALE:
            data = load_locale(effective_locale)
            value = _nested_get(data, key)
            if isinstance(value, str):
                return _substitute_params(value, params)

        # 尝试 zh-CN fallback
        data = load_locale(FALLBACK_LOCALE)
        value = _nested_get(data, key)
        if isinstance(value, str):
            return _substitute_params(value, params)

        # 所有 locale 都找不到 → 回传 [key]
        return f"[{key}]"

    except Exception as e:
        logger.warning(f"[i18n] t('{key}', locale='{locale}') 发生例外: {e}")
        return f"[{key}]"


def _deep_merge(base: dict, overlay: dict) -> dict:
    """深合并:overlay 的值覆盖 base,但不清除 base 中 overlay 没有的 key。

    借鉴 OpenAver _deep_merge:供 get_merged_translations 用。
    """
    result = deepcopy(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result


def get_merged_translations(locale: str) -> dict:
    """回传 zh-CN base dict 深合并 locale overlay。

    借鉴 OpenAver get_merged_translations:供前端 window.__i18n 直接使用,
    前端无需自己实现 fallback chain。
    """
    base = load_locale(FALLBACK_LOCALE)
    if locale == FALLBACK_LOCALE:
        return deepcopy(base)
    overlay = load_locale(locale)
    if not overlay:
        return deepcopy(base)
    return _deep_merge(base, overlay)


def detect_locale_from_accept_language(accept_language: str) -> str:
    """解析 HTTP Accept-Language header,回传 SUPPORTED_LOCALES 之一。

    借鉴 OpenAver detect_locale_from_accept_language:尊重 q-value 权重(RFC 7231)。
    无法解析或对应不到时回传 "en"。

    Args:
        accept_language: HTTP Accept-Language header 值
            (如 "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7")

    Returns:
        SUPPORTED_LOCALES 之一(如 "zh-CN" / "en" / "ja")
    """
    if not accept_language or not accept_language.strip():
        return "en"

    entries = []
    for part in accept_language.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if ";q=" in part:
            lang, q = part.split(";q=", 1)
            try:
                weight = float(q.strip())
            except ValueError:
                weight = 0.0
        else:
            lang = part
            weight = 1.0
        entries.append((lang.strip(), weight))
    entries.sort(key=lambda x: x[1], reverse=True)

    for lang, _ in entries:
        if lang in ("zh-cn", "zh-hans"):
            return "zh-CN"
        if lang in ("zh-tw", "zh-hant"):
            return "zh-TW"
        if lang == "zh":
            return "zh-CN"
        if lang == "ja" or lang.startswith("ja-"):
            return "ja"
        if lang == "en" or lang.startswith("en-"):
            return "en"

    return "en"


def get_supported_locales() -> tuple[str, ...]:
    """获取支持的 locale 列表"""
    return SUPPORTED_LOCALES


def is_supported(locale: str) -> bool:
    """检查 locale 是否受支持"""
    return locale in SUPPORTED_LOCALES
