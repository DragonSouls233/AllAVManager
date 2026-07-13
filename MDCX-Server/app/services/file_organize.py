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
import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Movie, FileOrganizeJob, PlayHistory, AutoOrganizeRule
from app.services.naming import render_dirpath, render_filename

logger = logging.getLogger(__name__)


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
    status: str  # completed/failed/skipped
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

        tasks: list[OrganizeTask] = []
        for movie_id in movie_ids:
            movie = await session.get(Movie, movie_id)
            if not movie:
                logger.warning(f"影片 {movie_id} 不存在，跳过")
                continue

            if not movie.file_path or not os.path.exists(movie.file_path):
                logger.warning(f"影片 {movie_id} ({movie.code}) 文件不存在: {movie.file_path}")
                continue

            # 渲染目标路径（用 naming 模块的 render_dirpath）
            try:
                # 准备 movie_dict 和 actors
                movie_dict = self._movie_to_dict(movie)
                actors = [a.actor.name for a in (movie.actors or []) if a.actor and a.actor.name]
                # 模板可能既包含目录部分又包含文件名部分，统一用 render_dirpath 渲染目录，
                # 再用 render_filename 渲染文件名（这里简化：模板整体当目录路径渲染）
                rendered = render_dirpath(template, movie_dict, actors)
            except Exception as e:
                logger.error(f"渲染命名模板失败（影片 {movie_id}）: {e}")
                continue

            # 拼接完整目标路径
            source_path = movie.file_path
            source_ext = os.path.splitext(source_path)[1]

            if job_type == OrganizeType.RENAME.value:
                # 原地点名：同目录，仅改文件名
                source_dir = os.path.dirname(source_path)
                target_path = os.path.join(source_dir, rendered + source_ext)
            else:
                # 其他模式：output_dir + rendered + 扩展名
                target_path = os.path.join(output_dir, rendered + source_ext)

            # 冲突检测
            if os.path.exists(target_path):
                if conflict_strategy == ConflictStrategy.RENAME.value:
                    target_path = self._generate_unique_path(target_path)
                elif conflict_strategy == ConflictStrategy.SKIP.value:
                    logger.info(f"目标已存在，跳过: {target_path}")
                    continue
                # overwrite 模式不在此处理，执行时再删除

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
    ) -> list[OrganizeResult]:
        """
        执行整理任务

        Args:
            session: 数据库会话
            tasks: 整理任务列表

        Returns:
            整理结果列表
        """
        results: list[OrganizeResult] = []

        for task in tasks:
            # 创建任务记录
            job = FileOrganizeJob(
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

            result = await self._execute_single(session, job, task)
            results.append(result)

        return results

    async def _execute_single(
        self,
        session: AsyncSession,
        job: FileOrganizeJob,
        task: OrganizeTask,
    ) -> OrganizeResult:
        """执行单个整理任务"""
        try:
            # 检查源文件
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

            # 文件大小
            job.file_size = os.path.getsize(task.source_path)

            # 冲突处理
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

            # 确保目标目录存在
            target_dir = os.path.dirname(task.target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)

            # 执行整理
            success = self._do_organize(task.job_type, task.source_path, task.target_path)
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

            # 更新影片 file_path（move/rename 模式）
            if task.job_type in (OrganizeType.MOVE.value, OrganizeType.RENAME.value):
                movie = await session.get(Movie, task.movie_id)
                if movie:
                    movie.file_path = task.target_path

            job.status = "completed"
            job.completed_at = datetime.now()
            await session.commit()

            logger.info(
                f"整理完成: {task.source_path} → {task.target_path} ({task.job_type})"
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
        """执行实际文件操作

        Args:
            job_type: 整理模式
            source: 源路径
            target: 目标路径

        Returns:
            是否成功
        """
        try:
            if job_type == OrganizeType.HARDLINK.value:
                # 硬链接：同盘符
                os.link(source, target)
            elif job_type == OrganizeType.COPY.value:
                # 复制
                shutil.copy2(source, target)
            elif job_type == OrganizeType.MOVE.value:
                # 移动
                shutil.move(source, target)
            elif job_type == OrganizeType.SYMLINK.value:
                # 软链接
                os.symlink(os.path.abspath(source), target)
            elif job_type == OrganizeType.RENAME.value:
                # 原地点名（等同 move，但同目录）
                shutil.move(source, target)
            else:
                logger.error(f"未知的整理模式: {job_type}")
                return False
            return True
        except OSError as e:
            # 硬链接跨盘符会失败
            if job_type == OrganizeType.HARDLINK.value and e.errno == 18:
                logger.warning(f"硬链接失败（跨盘符），降级为复制: {source} → {target}")
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

    def _movie_to_dict(self, movie: Movie) -> dict:
        """将 Movie ORM 对象转为 naming 模块所需的 dict

        Args:
            movie: Movie ORM 对象

        Returns:
            影片字段字典
        """
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
            # studio/series 名称需关联查询，此处简化，可后续扩展
            "studio": "",
            "series": "",
            "actor": "",
            "actors": [],
        }

    async def list_jobs(
        self,
        session: AsyncSession,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FileOrganizeJob]:
        """列出整理任务"""
        stmt = select(FileOrganizeJob)
        if status:
            stmt = stmt.where(FileOrganizeJob.status == status)
        if job_type:
            stmt = stmt.where(FileOrganizeJob.job_type == job_type)
        stmt = stmt.order_by(FileOrganizeJob.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_job_stats(self, session: AsyncSession) -> dict:
        """获取任务统计"""
        from sqlalchemy import func
        result = {}
        for status in ("pending", "running", "completed", "failed", "skipped"):
            stmt = select(func.count(FileOrganizeJob.id)).where(FileOrganizeJob.status == status)
            r = await session.execute(stmt)
            result[status] = r.scalar() or 0
        return result


# 单例
file_organize_service = FileOrganizeService()


# ============================================
# v4.1 B3：安全移动机制（带 SHA256 校验和回滚）
# ============================================

def _sha256_of_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """计算文件 SHA256 校验值

    Args:
        path: 文件路径
        chunk_size: 分块读取大小（字节）

    Returns:
        文件内容的 SHA256 十六进制摘要
    """
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha.update(chunk)
    return sha.hexdigest()


def safe_move_file(src: str, dst: str, safe_mode: bool = True) -> dict:
    """安全移动文件（v4.1 B3）

    安全模式流程：
        1. 校验目标磁盘空间 (shutil.disk_usage) ≥ 文件大小 × 1.1
        2. 复制文件 (shutil.copy2)
        3. SHA256 校验源文件和目标文件完整性
        4. 校验通过才删除原文件 (os.remove)
        5. 任一环节失败自动回滚（删除已复制的目标文件）

    Args:
        src: 源文件路径
        dst: 目标文件路径
        safe_mode: 是否启用安全模式（关闭则直接 shutil.move）

    Returns:
        dict，包含字段：
            - success: bool 是否成功
            - error: str | None 错误信息
            - checksum: str | None 源文件 SHA256（成功时）
            - dst_checksum: str | None 目标文件 SHA256（成功且 safe_mode 时）
            - file_size: int | None 文件大小
            - src: str 源路径
            - dst: str 目标路径
            - safe_mode: bool 是否启用了安全模式
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

    # 校验源文件
    if not os.path.exists(src):
        result["error"] = f"源文件不存在: {src}"
        return result
    if not os.path.isfile(src):
        result["error"] = f"源路径不是文件: {src}"
        return result

    file_size = os.path.getsize(src)
    result["file_size"] = file_size

    # 确保目标目录存在
    target_dir = os.path.dirname(dst)
    if target_dir:
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            result["error"] = f"创建目标目录失败: {e}"
            return result

    # 非安全模式：直接 shutil.move
    if not safe_mode:
        try:
            shutil.move(src, dst)
            result["success"] = True
            return result
        except Exception as e:
            result["error"] = f"移动失败: {e}"
            return result

    # ===== 安全模式 =====
    # 1. 校验目标磁盘空间
    try:
        target_disk = os.path.splitdrive(os.path.abspath(dst))[0] or "/"
        usage = shutil.disk_usage(target_disk)
        required = int(file_size * 1.1)
        if usage.free < required:
            result["error"] = (
                f"目标磁盘空间不足: 可用 {usage.free} 字节，需要 {required} 字节"
                f"（文件 {file_size} × 1.1）"
            )
            return result
    except Exception as e:
        result["error"] = f"磁盘空间校验失败: {e}"
        return result

    # 2. 计算源文件 SHA256（在复制前）
    try:
        src_checksum = _sha256_of_file(src)
        result["checksum"] = src_checksum
    except Exception as e:
        result["error"] = f"源文件 SHA256 计算失败: {e}"
        return result

    # 3. 复制文件（保留元数据）
    copied = False
    try:
        shutil.copy2(src, dst)
        copied = True
    except Exception as e:
        result["error"] = f"复制文件失败: {e}"
        return result

    # 4. 校验目标文件 SHA256
    try:
        dst_checksum = _sha256_of_file(dst)
        result["dst_checksum"] = dst_checksum
    except Exception as e:
        # 回滚
        if copied:
            try:
                os.remove(dst)
            except Exception:
                pass
        result["error"] = f"目标文件 SHA256 计算失败: {e}"
        return result

    # 5. 校验完整性
    if src_checksum != dst_checksum:
        # 回滚：删除已复制的目标文件
        try:
            os.remove(dst)
        except Exception:
            pass
        result["error"] = (
            f"SHA256 校验失败：源={src_checksum} 目标={dst_checksum}"
        )
        return result

    # 6. 校验通过，删除原文件
    try:
        os.remove(src)
    except Exception as e:
        # 源文件删除失败：清理目标文件以避免重复，整体视为失败
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

    Args:
        field_value: 影片字段的实际值
        op: 操作符
        expected: 规则中的期望值

    Returns:
        是否满足条件
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


def _get_movie_field(movie: Movie, field: str) -> object:
    """从影片对象中安全取出条件字段值

    Args:
        movie: Movie ORM 对象
        field: 字段名（如 play_count / view_status / code / maker 等）

    Returns:
        字段值；未知字段返回 None
    """
    return getattr(movie, field, None)


async def auto_organize_watched(session: AsyncSession) -> dict:
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

    Args:
        session: 数据库会话

    Returns:
        dict，包含 processed / moved / failed / skipped 数量与明细列表
    """
    summary = {
        "processed": 0,
        "moved": 0,
        "copied": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    # 查询所有启用的规则
    stmt = select(AutoOrganizeRule).where(AutoOrganizeRule.enabled == True)  # noqa: E712
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

        candidate_movies: list[Movie] = []

        # play_count 走 PlayHistory 聚合
        if rule.condition_field == "play_count":
            try:
                threshold = int(float(rule.condition_value))
            except ValueError:
                logger.warning(
                    f"规则 {rule.id} play_count 阈值无效: {rule.condition_value}"
                )
                continue

            # 聚合每部影片的观看次数
            agg = (
                select(
                    PlayHistory.movie_id,
                    func.count(PlayHistory.id).label("cnt"),
                )
                .group_by(PlayHistory.movie_id)
                .having(func.count(PlayHistory.id) >= threshold)
            )
            rows = (await session.execute(agg)).all()
            movie_ids = [r[0] for r in rows]

            if not movie_ids:
                continue

            m_stmt = select(Movie).where(
                Movie.id.in_(movie_ids),
                Movie.file_path.is_not(None),
            )
            candidate_movies = list((await session.execute(m_stmt)).scalars().all())
        else:
            # 通用：在 Movie 表上按字段过滤
            try:
                m_stmt = select(Movie).where(Movie.file_path.is_not(None))
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

            # 计算目标路径：target_path / 番号.ext
            if not rule.target_path:
                summary["skipped"] += 1
                rule_detail["failed"] += 1
                continue

            ext = os.path.splitext(src)[1]
            # 用番号做文件名（避免重名），含安全过滤
            safe_code = re.sub(r"[\\/:*?\"<>|]", "_", movie.code or f"movie_{movie.id}")
            dst = os.path.join(rule.target_path, f"{safe_code}{ext}")

            # 目标已存在则跳过（避免覆盖）
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
                    res = safe_move_file(src, dst, safe_mode=True)
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
                    res = safe_move_file(src, dst, safe_mode=False)
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
                        # 跨盘符降级为复制
                        if e.errno == 18:
                            res = safe_move_file(src, dst, safe_mode=False)
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
