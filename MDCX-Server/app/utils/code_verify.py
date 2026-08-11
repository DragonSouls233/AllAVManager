"""番号反向校验与等价比较工具（防抓错片串号入库）。

来源：移植 JavLibrarian 的 `_same_code`（忽略大小写、分隔符与前导零的强等价比较）。

用途：
- 刮削拿到元数据后，用返回的番号（或标题中解析出的番号）与目标番号做反向比对。
- 若不一致，说明刮削源返回了错误/无关影片，应拒绝入库或降级，避免串号。

提供：
- normalize_code：标准归一化（复用 number.normalize_number）
- same_code：强等价比较（IPVR-256 == ipvr_0256）
- reverse_code_check：反向校验入口，返回 (is_match, normalized_expected, normalized_got)
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Union

logger = logging.getLogger(__name__)

__all__ = [
    "normalize_code",
    "same_code",
    "reverse_code_check",
]


def normalize_code(code: str) -> str:
    """标准归一化番号：大写、统一分隔符、清理 FC2 前缀。"""
    from app.scraper.number import normalize_number

    return normalize_number(code or "")


def _strong_norm(code: Optional[str]) -> str:
    """JavLibrarian 强归一化：字母-数字，数字去前导零。

    'IPVR-256' / 'ipvr_0256' / 'IPVR0256' 全部归一为 'IPVR-256'。
    """
    code = (code or "").strip()
    m = re.match(r"^([A-Za-z]+)[-_]?0*(\d+)$", code)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2))}"
    return code.upper()


def same_code(a: str, b: str) -> bool:
    """强等价比较：忽略大小写、分隔符、前导零。

    >>> same_code("IPVR-256", "ipvr_0256")
    True
    >>> same_code("ABP-123", "ABP-124")
    False
    """
    return _strong_norm(a) == _strong_norm(b)


def reverse_code_check(expected: str, got: Optional[str]) -> tuple[bool, str, str]:
    """反向校验：刮削返回的番号 got 是否与目标 expected 一致。

    Args:
        expected: 目标番号（文件名/请求的番号）
        got: 刮削源返回的番号（可为空）

    Returns:
        (is_match, normalized_expected, normalized_got)
        - is_match=True：一致，可入库
        - got 为空：返回 (False, norm_e, "")，调用方可选择放行或拒绝
    """
    norm_e = normalize_code(expected)
    if not got:
        return False, norm_e, ""
    norm_g = normalize_code(got)
    return same_code(norm_e, norm_g), norm_e, norm_g


if __name__ == "__main__":
    assert same_code("IPVR-256", "ipvr_0256") is True
    assert same_code("ABP-123", "ABP-124") is False
    assert same_code("SDDE-611", "SDDE611") is True
    ok, e, g = reverse_code_check("SDDE-611", "SDDE-611")
    assert ok and e == "SDDE-611" and g == "SDDE-611"
    ok, _, _ = reverse_code_check("SDDE-611", "SDDE-999")
    assert ok is False
    ok, _, _ = reverse_code_check("SDDE-611", "")
    assert ok is False
    print("code_verify OK")
