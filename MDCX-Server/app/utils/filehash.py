"""文件内容指纹工具。

来源参考：``ref73-stash``（stash 的 phasher）—— 报告里归类为「oshash 快速指纹预筛」。
stash 自身用的是需要 ffmpeg 的感知哈希，而 MDCX 当前**完全没有基于内容的文件指纹**
（``app/tasks/western_scanner.py:167`` 只对文件路径做 sha256 生成 code，无法做内容去重）。

这里落地的是 **OpenSubtitles oshash**：只读文件首尾各 64KB，对 8 字节小端字求和（模 2^64，
带进位）后加上文件大小。不论文件多大，恒定约 128KB 磁盘读取，适合海量媒体库的精确去重预筛。

性质（也是测试用例要验证的）：
- 相同内容 → 相同哈希（确定性）
- 仅改动文件中间段落不影响哈希（这是 oshash 的设计特性，不是 bug）
- 哈希与文件大小相关（不同大小即便首尾相同也不同）
- 与 stash / OpenSubtitles 官方 C#/Java 实现**模 2^64 等价**

许可：oshash 算法本身为 OpenSubtitles 公开规范，MDCX 内部使用，引用来源
``stashapp/stash``（ref73，GPL 相关）仅作思路来源说明。
"""

from __future__ import annotations

import hashlib
import os
import struct

# ---------------------------------------------------------------------------
# OpenSubtitles oshash
# ---------------------------------------------------------------------------

_CHUNK = 65536  # 64 KB：首尾各读一块
_LONG = struct.Struct("<Q")  # 无符号 64 位小端
_MASK = 0xFFFFFFFFFFFFFFFF  # 2^64 - 1


def _accumulate(data: bytes, h: int) -> int:
    """把一段字节按 8 字节小端字累加进哈希，并归约到 64 位。

    归约方式：``h &= _MASK``（模 2^64）。这与 OpenSubtitles 官方 C# ``Hash.cs`` 等价——
    官方 ``hash`` 是 64 位无符号类型，``hash += l`` 已自动模 2^64，其
    ``(hash & mask) + (hash >> 64)`` 在该类型上是空操作。在 Python 无界整数里，
    必须用 ``&=`` 显式丢掉高位。**切勿写成 ``(h & MASK) + (h >> 64)``**，那会把进位
    又加回来，偏离真值。尾部不足 8 字节的字节直接忽略（官方按 sizeof(long)=8 整字读取）。
    """
    # 步长 8，且保证 i+8 不越界
    for i in range(0, len(data) - 7, 8):
        (word,) = _LONG.unpack_from(data, i)
        h += word
        h &= _MASK
    return h


def oshash(path: str | os.PathLike) -> str:
    """计算文件的 OpenSubtitles oshash（16 位小写十六进制）。

    参数：
        path：文件路径。

    返回：
        形如 ``"8e245d9679d31e12"`` 的 16 位十六进制串。

    复杂度：无论文件多大，只读取约 128KB（首尾各 64KB），O(1) 磁盘 I/O。
    """
    path = str(path)
    filesize = os.path.getsize(path)
    h = filesize  # 文件大小作为初始累加项（加法在模 2^64 下交换，等价于最后再加）
    with open(path, "rb") as f:
        # 首 64KB
        h = _accumulate(f.read(_CHUNK), h)
        # 尾 64KB：小文件时自然回到起点（与首块重叠是标准行为）
        f.seek(max(0, filesize - _CHUNK), os.SEEK_SET)
        h = _accumulate(f.read(_CHUNK), h)
    # 末次归约（filesize 作为初始累加项，加法在模 2^64 下交换，等价于最后再加）
    h &= _MASK
    return "%016x" % h


# ---------------------------------------------------------------------------
# 完整内容哈希（小文件 / 需要严格去重时）
# ---------------------------------------------------------------------------

def sha256_file(path: str | os.PathLike, limit: int | None = None) -> str:
    """计算文件内容 sha256。

    参数：
        path：文件路径。
        limit：若给定，只读前 ``limit`` 字节（用于超大文件的「头指纹」快速比对）；
            为 None 则读取整个文件。

    返回：
        64 位十六进制摘要。
    """
    path = str(path)
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        if limit is not None:
            digest.update(f.read(limit))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 视频扩展名白名单（供扫描器使用）
# ---------------------------------------------------------------------------

VIDEO_EXTS = (
    ".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".mpeg", ".mpg",
    ".ts", ".m2ts", ".iso", ".rmvb", ".webm", ".3gp", ".mpg", ".vob",
)
