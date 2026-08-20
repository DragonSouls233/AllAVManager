"""
文件整理服务（v3.0）

参考 mdc-ng 项目，提供 5 种整理模式：
- hardlink: 硬链接（同盘符，不占额外空间，原文件保留）
- copy: 复制（跨盘符或需独立副本，原文件保留）
- move: 移动（迁移到目标目录，原文件删除）
- symlink: 软链接（符号链接，跨盘符可用，原文件保留）
- rename: 原地点名（仅重命名，不改变目录）

冲突策略：
- skip: 跳过（目标已存在则不处理）
- overwrite: 覆盖（删除目标后重新整理）
- rename: 重命名（目标加 _1/_2 后缀）

集成 Jinja2 命名模板（复用 app.services.naming）。
"""
import asyncio
import ctypes
import errno
import hashlib
import importlib
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.module_helper import get_module_model, get_module_session, MODULE_MODELS
from app.services.naming import render_dirpath, render_filename

logger = logging.getLogger(__name__)


def _resolve_module(module: str) -> str:
    """解析模块名，无效时回退到 jav"""
    return module if module in MODULE_MODELS else "jav"


def _get_mod_cls(module: str, cls_name: str):
    """获取模块中的任意模型类"""
    mod_path, _, _ = MODULE_MODELS[module]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


class OrganizeType(str, Enum):
    """整理模式"""
    HARDLINK = "hardlink"   # 硬链接
    COPY = "copy"           # 复制
    MOVE = "move"           # 移动
    SYMLINK = "symlink"     # 软链接
    RENAME = "rename"       # 原地点名


class ConflictStrategy(str, Enum):
    """冲突策略"""
    SKIP = "skip"           # 跳过
    OVERWRITE = "overwrite" # 覆盖
    RENAME = "rename"       # 重命名


@dataclass
class OrganizeTask:
    """单个整理任务"""
    movie_id: int
    source_path: str
    target_path: str
    job_type: str
    conflict_strategy: str = "skip"


@dataclass
class OrganizeResult:
    """整理结果"""
    job_id: int
    movie_id: Optional[int]
    source_path: str
    target_path: str
    job_type: str
    status: str
    error_message: Optional[str] = None
    file_size: Optional[int] = None


class FileOrganizeService:
    """文件整理服务"""

    # 支持的视频扩展名
    VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".iso", ".webm", ".rmvb"}

    async def preview_organize(
        self,
        session: AsyncSession,
        movie_ids: list[int],
        job_type: str,
        output_dir: str,
        template: str,
        module: str = "jav",
        conflict_strategy: str = "skip",
    ) -> list[OrganizeTask]:
        """
        预览整理任务（不执行，仅生成任务列表）

        Args:
            session: 数据库会话
            movie_ids: 影片 ID 列表
            job_type: 整理模式（hardlink/copy/move/symlink/rename）
            output_dir: 输出目录（rename 模式忽略）
            template: Jinja2 命名模板（相对路径，如 "{{ actor }}/{{ code }}/{{ code }}"）
            conflict_strategy: 冲突策略

        Returns:
            整理任务列表
        """
        if job_type not in [t.value for t in OrganizeType]:
            raise ValueError(f"无效的整理模式: {job_type}")

        if conflict_strategy not in [s.value for s in ConflictStrategy]:
            raise ValueError(f"无效的冲突策略: {conflict_strategy}")

        module = _resolve_module(module)
        MovieModel = get_module_model(module, "movie")

        tasks: list[OrganizeTask] = []
        for movie_id in movie_ids:
            movie = await session.get(MovieModel, movie_id)
            if not movie:
                logger.warning(f"影片 {movie_id} 不存在，跳过")
                continue

            if not movie.file_path or not os.path.exists(movie.file_path):
                logger.warning(f"影片 {movie_id} ({movie.code}) 文件不存在: {movie.file_path}")
                continue

            # 渲染目标路径
            try:
                movie_dict = self._movie_to_dict(movie)
                actors = [a.actor.name for a in (movie.actors or []) if a.actor and a.actor.name]
                rendered = render_dirpath(template, movie_dict, actors)
            except Exception as e:
                logger.error(f"渲染命名模板失败（影片 {movie_id}）: {e}")
                continue

            source_path = movie.file_path
            source_ext = os.path.splitext(source_path)[1]

            if job_type == OrganizeType.RENAME.value:
                source_dir = os.path.dirname(source_path)
                target_path = os.path.join(source_dir, rendered + source_ext)
            else:
                target_path = os.path.join(output_dir, rendered + source_ext)

            # 冲突检测
            if os.path.exists(target_path):
                if conflict_strategy == ConflictStrategy.RENAME.value:
                    target_path = self._generate_unique_path(target_path)
                elif conflict_strategy == ConflictStrategy.SKIP.value:
                    logger.info(f"目标已存在，跳过: {target_path}")
                    continue

            tasks.append(OrganizeTask(
                movie_id=movie_id,
                source_path=source_path,
                target_path=target_path,
                job_type=job_type,
                conflict_strategy=conflict_strategy,
            ))

        return tasks

    async def execute_organize(
        self,
        session: AsyncSession,
        tasks: list[OrganizeTask],
        module: str = "jav",
    ) -> list[OrganizeResult]:
        """
        执行整理任务

        Args:
            session: 数据库会话
            tasks: 整理任务列表

        Returns:
            整理结果列表
        """
        module = _resolve_module(module)
        FileOrganizeJobCls = _get_mod_cls(module, "FileOrganizeJob")

        results: list[OrganizeResult] = []

        for task in tasks:
            job = FileOrganizeJobCls(
                job_type=task.job_type,
                source_path=task.source_path,
                target_path=task.target_path,
                movie_id=task.movie_id,
                status="running",
                conflict_strategy=task.conflict_strategy,
                started_at=datetime.now(),
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            result = await self._execute_single(session, job, task, module)
            results.append(result)

        return results

    async def _execute_single(
        self,
        session: AsyncSession,
        job,
        task: OrganizeTask,
        module: str = "jav",
    ) -> OrganizeResult:
        """执行单个整理任务"""
        module = _resolve_module(module)
        MovieModel = get_module_model(module, "movie")

        try:
            if not os.path.exists(task.source_path):
                job.status = "failed"
                job.error_message = f"源文件不存在: {task.source_path}"
                job.completed_at = datetime.now()
                await session.commit()
                return OrganizeResult(
                    job_id=job.id, movie_id=task.movie_id,
                    source_path=task.source_path, target_path=task.target_path,
                    job_type=task.job_type, status="failed",
                    error_message=job.error_message,
                )

            job.file_size = os.path.getsize(task.source_path)

            if os.path.exists(task.target_path):
                if task.conflict_strategy == ConflictStrategy.SKIP.value:
                    job.status = "skipped"
                    job.error_message = "目标已存在，跳过"
                    job.completed_at = datetime.now()
                    await session.commit()
                    return OrganizeResult(
                        job_id=job.id, movie_id=task.movie_id,
                        source_path=task.source_path, target_path=task.target_path,
                        job_type=task.job_type, status="skipped",
                        error_message=job.error_message, file_size=job.file_size,
                    )
                elif task.conflict_strategy == ConflictStrategy.OVERWRITE.value:
                    if os.path.isdir(task.target_path):
                        shutil.rmtree(task.target_path)
                    else:
                        os.remove(task.target_path)
                    logger.info(f"覆盖目标: {task.target_path}")

            target_dir = os.path.dirname(task.target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)

            # 关键修复：_do_organize 内部 shutil.copy2/shutil.move 是同步阻塞的，
            # 必须丢到线程池执行，避免阻塞事件循环导致服务端假死。
            success = await asyncio.to_thread(
                self._do_organize, task.job_type, task.source_path, task.target_path
            )
            if not success:
                job.status = "failed"
                job.error_message = f"整理失败（{task.job_type}）"
                job.completed_at = datetime.now()
                await session.commit()
                return OrganizeResult(
                    job_id=job.id, movie_id=task.movie_id,
                    source_path=task.source_path, target_path=task.target_path,
                    job_type=task.job_type, status="failed",
                    error_message=job.error_message, file_size=job.file_size,
                )

            if task.job_type in (OrganizeType.MOVE.value, OrganizeType.RENAME.value):
                movie = await session.get(MovieModel, task.movie_id)
                if movie:
                    movie.file_path = task.target_path

            job.status = "completed"
            job.completed_at = datetime.now()
            await session.commit()

            logger.info(
                f"整理完成: {task.source_path} -> {task.target_path} ({task.job_type})"
            )
            return OrganizeResult(
                job_id=job.id, movie_id=task.movie_id,
                source_path=task.source_path, target_path=task.target_path,
                job_type=task.job_type, status="completed",
                file_size=job.file_size,
            )

        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now()
            await session.commit()
            logger.exception(f"整理任务异常: {e}")
            return OrganizeResult(
                job_id=job.id, movie_id=task.movie_id,
                source_path=task.source_path, target_path=task.target_path,
                job_type=task.job_type, status="failed",
                error_message=str(e),
            )

    def _do_organize(self, job_type: str, source: str, target: str) -> bool:
        """执行实际文件操作"""
        try:
            if job_type == OrganizeType.HARDLINK.value:
                os.link(source, target)
            elif job_type == OrganizeType.COPY.value:
                shutil.copy2(source, target)
            elif job_type == OrganizeType.MOVE.value:
                # 同卷优先使用原子改名（防覆盖），跨卷回退 shutil.move
                if _same_fs(Path(source), Path(target)):
                    _rename_no_replace(Path(source), Path(target))
                else:
                    shutil.move(source, target)
            elif job_type == OrganizeType.SYMLINK.value:
                os.symlink(os.path.abspath(source), target)
            elif job_type == OrganizeType.RENAME.value:
                # 原地改名：同步伴生文件（字幕/封面/NFO 等），防覆盖
                rename_with_companions(source, target)
            else:
                logger.error(f"未知的整理模式: {job_type}")
                return False
            return True
        except OSError as e:
            if job_type == OrganizeType.HARDLINK.value and e.errno == 18:
                logger.warning(f"硬链接失败（跨盘符），降级为复制: {source} -> {target}")
                try:
                    shutil.copy2(source, target)
                    return True
                except Exception as fallback_e:
                    logger.error(f"降级复制也失败: {fallback_e}")
                    return False
            logger.error(f"整理失败 ({job_type}): {e}")
            return False

    def _generate_unique_path(self, path: str) -> str:
        """生成唯一路径（目标已存在时加 _1/_2 后缀）"""
        base, ext = os.path.splitext(path)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"

    def _movie_to_dict(self, movie) -> dict:
        """将 Movie ORM 对象转为 naming 模块所需的 dict"""
        return {
            "code": movie.code or "",
            "title": movie.title or "",
            "original_title": movie.original_title or "",
            "title_jp": movie.title_jp or "",
            "maker": movie.maker or "",
            "director": movie.director or "",
            "release_date": movie.release_date or "",
            "rating": movie.rating or 0,
            "genre": movie.genre or "",
            "tag": movie.tag or "",
            "source": movie.source or "",
            "is_uncensored": movie.is_uncensored,
            "is_chinese": movie.is_chinese,
            "is_mosaic": movie.is_mosaic,
            "studio": "",
            "series": "",
            "actor": movie.actor if hasattr(movie, "actor") else "",
            "actors": [],
        }

    async def list_jobs(
        self,
        session: AsyncSession,
        module: str = "jav",
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        """列出整理任务"""
        module = _resolve_module(module)
        FileOrganizeJobCls = _get_mod_cls(module, "FileOrganizeJob")

        stmt = select(FileOrganizeJobCls)
        if status:
            stmt = stmt.where(FileOrganizeJobCls.status == status)
        if job_type:
            stmt = stmt.where(FileOrganizeJobCls.job_type == job_type)
        stmt = stmt.order_by(FileOrganizeJobCls.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_job_stats(self, session: AsyncSession, module: str = "jav") -> dict:
        """获取任务统计"""
        module = _resolve_module(module)
        FileOrganizeJobCls = _get_mod_cls(module, "FileOrganizeJob")

        result = {}
        for status_val in ("pending", "running", "completed", "failed", "skipped"):
            stmt = select(func.count(FileOrganizeJobCls.id)).where(
                FileOrganizeJobCls.status == status_val
            )
            r = await session.execute(stmt)
            result[status_val] = r.scalar() or 0
        return result


# 单例
file_organize_service = FileOrganizeService()


# ============================================
# v4.1 B3：安全移动机制（带 SHA256 校验和回滚）
# ============================================

def _sha256_of_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """计算文件 SHA256 校验值"""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ============================================
# v5.0：安全改名原语（移植自 Kesuy-mdcx media_reorganization）
# ============================================

def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _same_spelling(left: Path, right: Path) -> bool:
    return os.path.abspath(left) == os.path.abspath(right)


def _same_fs(left: Path, right: Path) -> bool:
    """判断两个路径是否位于同一文件系统/盘符（同卷才可原子改名）"""
    try:
        return os.path.normcase(os.path.splitdrive(os.path.abspath(left))[0]) == os.path.normcase(
            os.path.splitdrive(os.path.abspath(right))[0]
        )
    except OSError:
        return False


def _renamed_companion_name(name: str, old_stem: str, new_stem: str) -> str:
    """计算伴生文件（字幕/封面/NFO 等）在主文件改名后的新文件名。

    仅当伴生文件以 old_stem 开头且紧跟着分隔符（.-_ 空格）时才跟随改名，
    避免误伤同目录下的其它文件。
    """
    if not name.startswith(old_stem) or len(name) == len(old_stem):
        return name
    if name[len(old_stem)] not in ".-_ ":
        return name
    return new_stem + name[len(old_stem):]


def _rename_no_replace(source: Path, target: Path) -> None:
    """同卷原子改名；若目标在任意时刻已存在则绝不覆盖。

    优先使用系统原子改名原语（Linux renameat2 / macOS renamex_np），
    兼容平台回退到前置 lexists 防护 + os.rename。
    """
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, "目标已存在", str(target))

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        if hasattr(libc, "renameat2"):
            source_bytes = os.fsencode(source)
            target_bytes = os.fsencode(target)
            at_fdcwd = -100
            rename_noreplace = 1
            result = libc.renameat2(at_fdcwd, source_bytes, at_fdcwd, target_bytes, rename_noreplace)
            if result == 0:
                return
            error_number = ctypes.get_errno()
            if error_number not in (errno.ENOSYS, errno.EINVAL):
                raise OSError(error_number, os.strerror(error_number), str(target))

    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        if hasattr(libc, "renamex_np"):
            source_bytes = os.fsencode(source)
            target_bytes = os.fsencode(target)
            rename_excl = 0x00000004
            result = libc.renamex_np(source_bytes, target_bytes, rename_excl)
            if result == 0:
                return
            error_number = ctypes.get_errno()
            if error_number not in (errno.ENOSYS, errno.EINVAL):
                raise OSError(error_number, os.strerror(error_number), str(target))

    # Windows 的 os.rename 不覆盖现有目标；未知平台保留前置 lexists 防护。
    source.rename(target)


def _rename_case_safe(source: Path, target: Path) -> None:
    """大小写改名安全处理：仅大小写不同的改名需经临时名中转，避免平台差异。"""
    if _same_spelling(source, target):
        return
    if os.path.normcase(str(source)) == os.path.normcase(str(target)):
        temporary = source.with_name(f"{source.name}.MDCx.rename.tmp")
        counter = 0
        while temporary.exists():
            counter += 1
            temporary = source.with_name(f"{source.name}.MDCx.rename.{counter}.tmp")
        _rename_no_replace(source, temporary)
        try:
            _rename_no_replace(temporary, target)
        except Exception:
            _rename_no_replace(temporary, source)
            raise
        return
    _rename_no_replace(source, target)


def rename_with_companions(source: str, target: str) -> list[str]:
    """原地改名并同步伴生文件（字幕/封面/NFO 等）。

    以主文件 old_stem 开头且紧跟分隔符的伴生文件会跟随改名，
    例如 ABC-123.mp4 改为 DEF-456.mp4 时，ABC-123.srt → DEF-456.srt。

    Returns:
        实际执行的 (旧路径 -> 新路径) 列表
    """
    src_path = Path(source)
    dst_path = Path(target)
    old_stem = src_path.stem
    new_stem = dst_path.stem

    changed: list[str] = []
    if old_stem == new_stem:
        return changed

    # 收集待改名的伴生文件（主文件自身 + 所有以 old_stem 开头的伴生文件）
    siblings = [src_path]
    try:
        siblings.extend(
            path for path in src_path.parent.iterdir()
            if path.is_file()
            and not _same_path(path, src_path)  # 排除源文件本身，避免重复处理
            and _renamed_companion_name(path.name, old_stem, new_stem) != path.name
        )
    except OSError:
        pass

    for sibling in siblings:
        if _same_path(sibling, src_path):
            pair = (src_path, dst_path)
        else:
            new_name = _renamed_companion_name(sibling.name, old_stem, new_stem)
            pair = (sibling, sibling.with_name(new_name))
        _rename_case_safe(pair[0], pair[1])
        changed.append(f"{pair[0]} -> {pair[1]}")
    return changed


def safe_move_file(src: str, dst: str, safe_mode: bool = True) -> dict:
    """安全移动文件（v4.1 B3）

    安全模式流程：
        1. 校验目标磁盘空间 (shutil.disk_usage) >= 文件大小 x 1.1
        2. 复制文件 (shutil.copy2)
        3. SHA256 校验源文件和目标文件完整性
        4. 校验通过才删除原文件 (os.remove)
        5. 任一环节失败自动回滚（删除已复制的目标文件）
    """
    result = {
        "success": False,
        "error": None,
        "checksum": None,
        "dst_checksum": None,
        "file_size": None,
        "src": src,
        "dst": dst,
        "safe_mode": safe_mode,
    }

    if not os.path.exists(src):
        result["error"] = f"源文件不存在: {src}"
        return result
    if not os.path.isfile(src):
        result["error"] = f"源路径不是文件: {src}"
        return result

    file_size = os.path.getsize(src)
    result["file_size"] = file_size

    target_dir = os.path.dirname(dst)
    if target_dir:
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            result["error"] = f"创建目标目录失败: {e}"
            return result

    if not safe_mode:
        try:
            shutil.move(src, dst)
            result["success"] = True
            return result
        except Exception as e:
            result["error"] = f"移动失败: {e}"
            return result

    # ===== 安全模式 =====
    try:
        target_disk = os.path.splitdrive(os.path.abspath(dst))[0] or "/"
        usage = shutil.disk_usage(target_disk)
        required = int(file_size * 1.1)
        if usage.free < required:
            result["error"] = (
                f"目标磁盘空间不足: 可用 {usage.free} 字节，需要 {required} 字节"
                f"（文件 {file_size} x 1.1）"
            )
            return result
    except Exception as e:
        result["error"] = f"磁盘空间校验失败: {e}"
        return result

    try:
        src_checksum = _sha256_of_file(src)
        result["checksum"] = src_checksum
    except Exception as e:
        result["error"] = f"源文件 SHA256 计算失败: {e}"
        return result

    copied = False
    try:
        shutil.copy2(src, dst)
        copied = True
    except Exception as e:
        result["error"] = f"复制文件失败: {e}"
        return result

    try:
        dst_checksum = _sha256_of_file(dst)
        result["dst_checksum"] = dst_checksum
    except Exception as e:
        if copied:
            try:
                os.remove(dst)
            except Exception:
                pass
        result["error"] = f"目标文件 SHA256 计算失败: {e}"
        return result

    if src_checksum != dst_checksum:
        try:
            os.remove(dst)
        except Exception:
            pass
        result["error"] = (
            f"SHA256 校验失败：源={src_checksum} 目标={dst_checksum}"
        )
        return result

    try:
        os.remove(src)
    except Exception as e:
        try:
            os.remove(dst)
        except Exception:
            pass
        result["error"] = f"删除源文件失败: {e}"
        return result

    result["success"] = True
    return result


# ============================================
# v4.1 B1：自动整理已观看视频
# ============================================

def _evaluate_condition(field_value: object, op: str, expected: str) -> bool:
    """评估单个规则条件是否成立

    支持的操作符：
        - eq: 等于
        - ne: 不等于
        - contains: 包含子串
        - gt / lt / ge / le: 数值比较
        - regex: 正则匹配
        - in: 子串包含（值以逗号分隔多个候选）
    """
    if field_value is None:
        return False
    fv_str = str(field_value)
    try:
        if op == "eq":
            return fv_str == expected
        if op == "ne":
            return fv_str != expected
        if op == "contains":
            return expected in fv_str
        if op == "in":
            return any(v.strip() == fv_str for v in expected.split(","))
        if op in ("gt", "lt", "ge", "le"):
            try:
                lhs = float(fv_str)
                rhs = float(expected)
            except ValueError:
                return False
            return {
                "gt": lhs > rhs,
                "lt": lhs < rhs,
                "ge": lhs >= rhs,
                "le": lhs <= rhs,
            }[op]
        if op == "regex":
            try:
                return re.search(expected, fv_str) is not None
            except re.error:
                return False
    except Exception:
        return False
    return False


def _get_movie_field(movie, field: str) -> object:
    """从影片对象中安全取出条件字段值"""
    return getattr(movie, field, None)


async def auto_organize_watched(session: AsyncSession, module: str = "jav") -> dict:
    """自动整理已观看视频（v4.1 B1）

    流程：
        1. 查询启用的 AutoOrganizeRule
        2. 对每条规则，按 condition_field / condition_op / condition_value
           过滤候选影片
        3. 当 condition_field 为 "play_count" 时，按观看次数阈值从 PlayHistory
           聚合后取候选；其它字段直接在 Movie 上过滤
        4. 用 safe_move_file 将命中影片移动到 target_path（action=move 时），
           或执行 copy/hardlink/symlink 等动作
        5. 移动成功后更新 Movie.file_path（move/rename 动作）
    """
    module = _resolve_module(module)
    MovieModel = get_module_model(module, "movie")
    AutoOrganizeRuleCls = _get_mod_cls(module, "AutoOrganizeRule")
    PlayHistoryCls = _get_mod_cls(module, "PlayHistory")

    summary = {
        "processed": 0,
        "moved": 0,
        "copied": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    stmt = select(AutoOrganizeRuleCls).where(AutoOrganizeRuleCls.enabled == True)  # noqa: E712
    rules = (await session.execute(stmt)).scalars().all()

    if not rules:
        return summary

    for rule in rules:
        rule_detail = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "action": rule.action,
            "matched": 0,
            "ok": 0,
            "failed": 0,
        }

        candidate_movies: list = []

        if rule.condition_field == "play_count":
            try:
                threshold = int(float(rule.condition_value))
            except ValueError:
                logger.warning(
                    f"规则 {rule.id} play_count 阈值无效: {rule.condition_value}"
                )
                continue

            agg = (
                select(
                    PlayHistoryCls.movie_id,
                    func.count(PlayHistoryCls.id).label("cnt"),
                )
                .group_by(PlayHistoryCls.movie_id)
                .having(func.count(PlayHistoryCls.id) >= threshold)
            )
            rows = (await session.execute(agg)).all()
            movie_ids = [r[0] for r in rows]

            if not movie_ids:
                continue

            m_stmt = select(MovieModel).where(
                MovieModel.id.in_(movie_ids),
                MovieModel.file_path.is_not(None),
            )
            candidate_movies = list((await session.execute(m_stmt)).scalars().all())
        else:
            try:
                m_stmt = select(MovieModel).where(MovieModel.file_path.is_not(None))
                candidates = (await session.execute(m_stmt)).scalars().all()
                for m in candidates:
                    fv = _get_movie_field(m, rule.condition_field)
                    if _evaluate_condition(fv, rule.condition_op, rule.condition_value):
                        candidate_movies.append(m)
            except Exception as e:
                logger.error(f"规则 {rule.id} 查询候选影片失败: {e}")
                continue

        rule_detail["matched"] = len(candidate_movies)

        for movie in candidate_movies:
            summary["processed"] += 1
            src = movie.file_path
            if not src or not os.path.exists(src):
                summary["skipped"] += 1
                rule_detail["failed"] += 1
                summary["details"].append({
                    "rule_id": rule.id,
                    "movie_id": movie.id,
                    "code": movie.code,
                    "status": "skipped",
                    "error": "源文件不存在",
                })
                continue

            if not rule.target_path:
                summary["skipped"] += 1
                rule_detail["failed"] += 1
                continue

            ext = os.path.splitext(src)[1]
            safe_code = re.sub(r'[\\/:*?"<>|]', "_", movie.code or f"movie_{movie.id}")
            dst = os.path.join(rule.target_path, f"{safe_code}{ext}")

            if os.path.exists(dst):
                summary["skipped"] += 1
                rule_detail["failed"] += 1
                summary["details"].append({
                    "rule_id": rule.id,
                    "movie_id": movie.id,
                    "code": movie.code,
                    "status": "skipped",
                    "error": "目标已存在",
                })
                continue

            action = (rule.action or "move").lower()

            try:
                if action == "move":
                    # 关键修复：safe_move_file 会整文件读取(SHA256)+整文件复制，
                    # 必须丢到线程池执行，否则会阻塞 asyncio 事件循环 → 整个服务端
                    # （含前端静态资源）假死。详见诊断。
                    res = await asyncio.to_thread(safe_move_file, src, dst, safe_mode=True)
                    if res["success"]:
                        movie.file_path = dst
                        await session.commit()
                        summary["moved"] += 1
                        rule_detail["ok"] += 1
                        summary["details"].append({
                            "rule_id": rule.id,
                            "movie_id": movie.id,
                            "code": movie.code,
                            "status": "moved",
                            "src": src,
                            "dst": dst,
                            "checksum": res.get("checksum"),
                        })
                    else:
                        summary["failed"] += 1
                        rule_detail["failed"] += 1
                        summary["details"].append({
                            "rule_id": rule.id,
                            "movie_id": movie.id,
                            "code": movie.code,
                            "status": "failed",
                            "error": res.get("error"),
                        })
                elif action == "copy":
                    res = await asyncio.to_thread(safe_move_file, src, dst, safe_mode=False)
                    if res["success"]:
                        summary["copied"] += 1
                        rule_detail["ok"] += 1
                        summary["details"].append({
                            "rule_id": rule.id,
                            "movie_id": movie.id,
                            "code": movie.code,
                            "status": "copied",
                            "src": src,
                            "dst": dst,
                        })
                    else:
                        summary["failed"] += 1
                        rule_detail["failed"] += 1
                        summary["details"].append({
                            "rule_id": rule.id,
                            "movie_id": movie.id,
                            "code": movie.code,
                            "status": "failed",
                            "error": res.get("error"),
                        })
                elif action == "hardlink":
                    try:
                        os.link(src, dst)
                        summary["copied"] += 1
                        rule_detail["ok"] += 1
                    except OSError as e:
                        if e.errno == 18:
                            res = await asyncio.to_thread(safe_move_file, src, dst, safe_mode=False)
                            if res["success"]:
                                summary["copied"] += 1
                                rule_detail["ok"] += 1
                            else:
                                raise
                        else:
                            raise
                elif action == "symlink":
                    os.symlink(os.path.abspath(src), dst)
                    summary["copied"] += 1
                    rule_detail["ok"] += 1
                else:
                    summary["skipped"] += 1
                    rule_detail["failed"] += 1
                    logger.warning(f"规则 {rule.id} 未知动作: {action}")
            except Exception as e:
                summary["failed"] += 1
                rule_detail["failed"] += 1
                summary["details"].append({
                    "rule_id": rule.id,
                    "movie_id": movie.id,
                    "code": movie.code,
                    "status": "failed",
                    "error": str(e),
                })
                logger.exception(f"自动整理影片 {movie.code} 失败: {e}")

    logger.info(
        f"自动整理完成：处理 {summary['processed']} 部，"
        f"移动 {summary['moved']}，复制 {summary['copied']}，"
        f"失败 {summary['failed']}，跳过 {summary['skipped']}"
    )
    return summary
