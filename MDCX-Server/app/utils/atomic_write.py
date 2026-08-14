"""原子文件写入工具（SMB 网络盘刚需）。

来源：移植 javdb_tool 的 `_atomic_json_write`（mkstemp + fsync + os.replace）。

为什么需要：
- MDCX 所有媒体/数据盘（H:/I:/J:/K:/Y:/Z:/G:/L:）都是 SMB 网络盘。
- 网络盘直接写目标文件，若写一半断连/断电/进程被杀，会留下**半截文件**（NFO/JSON 损坏）。
- 原子写先写同目录临时文件 → fsync 落盘 → os.replace 原子改名，保证目标文件要么是旧完整版、
  要么是新完整版，绝不出现半截。

提供三种原子写：
- atomic_write_bytes / atomic_write_text：通用字节/文本
- atomic_write_json：JSON 原子写（含 ensure_ascii=False + indent）
- atomic_read_json：带损坏容错的 JSON 读取
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

__all__ = [
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "atomic_read_json",
]


def _atomic_write(path: Path, data: bytes) -> None:
    """核心原子写：mkstemp 同目录临时文件 → 写 → fsync → os.replace。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, str(path))
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Union[str, Path], data: bytes) -> None:
    """原子写入字节数据。"""
    _atomic_write(Path(path), data)


def atomic_write_text(
    path: Union[str, Path], text: str, encoding: str = "utf-8", newline: str = "\n"
) -> None:
    """原子写入文本（默认 UTF-8 + LF 换行）。"""
    _atomic_write(Path(path), text.encode(encoding))


def atomic_write_json(
    path: Union[str, Path],
    data: Any,
    ensure_ascii: bool = False,
    indent: int = 2,
) -> None:
    """原子写入 JSON。

    默认 ensure_ascii=False（保留中文/日文原文）+ indent=2（可读）。
    """
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    # json.dumps 的默认分隔符在 ensure_ascii=False 时会输出 '": "'; 用 compact 换行保持稳定
    _atomic_write(Path(path), (text + "\n").encode("utf-8"))


def atomic_read_json(path: Union[str, Path], default: Any = None) -> Any:
    """带损坏容错的 JSON 读取。

    文件不存在 → 返回 default；文件损坏 → 记警告并返回 default（不抛异常，
    避免半截文件让调用方整个流程崩溃）。
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("JSON 文件损坏，返回默认值: %s (%s)", path, exc)
        return default


if __name__ == "__main__":
    # 自测
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "test.json"
        atomic_write_json(p, {"code": "ABP-123", "标题": "日文テスト"})
        print("written:", p.read_text(encoding="utf-8"))
        back = atomic_read_json(p)
        assert back["code"] == "ABP-123" and back["标题"] == "日文テスト"
        print("roundtrip OK")
        # 损坏容错
        p.write_text("{broken", encoding="utf-8")
        assert atomic_read_json(p, {"fallback": True}) == {"fallback": True}
        print("corrupt-fallback OK")
