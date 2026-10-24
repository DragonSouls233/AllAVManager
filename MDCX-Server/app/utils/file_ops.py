"""文件系统通用工具（复制/移动的容错降级）。

背景
----
MDCX 的媒体目录大多是 SMB 映射盘（``Z:`` = ``\\\\host\\share``）或网盘挂载
（CloudDrive2 / FUSE 之类）。这类文件系统有两个常见坑：

1. **拒绝写元数据**：``shutil.copy2`` 在写完文件内容后还会 ``copystat``（写 mtime
   / 权限位），网盘常常返回 ``EPERM``。此时**内容其实已经拷好了**，但 copy2 抛错
   ⇒ 调用方判定整个任务失败。参考 ref114-amane #543（``handlers/file.py``
   ``_copy_into_library``）的修法：copy2 失败后退 ``copyfile``（只拷内容），
   ``copystat`` 再单独容错。
2. **同文件多路径可达**：同一物理文件可通过不同路径到达，``copy2`` 会抛
   ``SameFileError``（原本在 ``app/tasks/base_scanner.py`` 里已单独处理）。

本模块把这两条降级链统一收口，避免各处重复实现并逐渐分叉。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["copy_file_resilient"]


def copy_file_resilient(src: str | Path, dst: str | Path) -> bool:
    """把 ``src`` 复制到 ``dst``，元数据写入失败时自动降级为「只要内容」。

    降级链：:

        samefile 短路 → shutil.copy2（保留元数据）
          → shutil.copyfile（纯内容）+ copystat 单独容错
          → 真正的内容复制失败才抛 RuntimeError

    ⚠️ 语义约定（与原先 ``base_scanner._copy_file_resilient`` 保持一致）：

    - ``True``  = 目标处已写入副本（内容可用）
    - ``False`` = 源与目标为同一文件，无需复制（**不是失败**，调用方通常跳过计数）
    - 内容层面的失败直接向上抛出原始异常（FileNotFoundError / PermissionError 等）

    因此：``file_organize`` 这类「确保内容到位」的场景可以直接忽略返回值；
    ``base_scanner`` 这类需要统计「实际复制了几份」的场景则按 False 跳过计数。

    Args:
        src: 源文件路径
        dst: 目标文件路径
    """
    src = Path(src)
    dst = Path(dst)

    # 1) 同文件短路（网络盘不支持 samefile 时 OSError，交给后续实际复制兜底）
    try:
        if dst.exists() and src.samefile(dst):
            logger.debug("源与目标为同一文件，跳过: %s", src)
            return False
    except OSError:
        pass

    # 2) 优先保留元数据的完整复制
    try:
        shutil.copy2(src, dst)
        return True
    except shutil.SameFileError:
        logger.debug("源与目标为同一文件，跳过: %s", src)
        return False
    except OSError as e:
        # SMB / 只读属性 / copystat 被拒：退化为只要内容的复制
        logger.debug("copy2 失败，降级为纯内容复制 %s -> %s: %s", src, dst, e)

    # 3) 纯内容复制（失败 = 真正的复制失败；保留原始异常类型，便于调用方按 errno 判断）
    shutil.copyfile(src, dst)

    # 4) 元数据尽力补一次，失败无所谓（2026-10-24 借鉴 amane #543）
    try:
        shutil.copystat(src, dst)
    except Exception:  # noqa: BLE001
        logger.debug("元数据复制被跳过（网盘/SMB 拒绝写权限或时间戳）: %s", src)

    return True
