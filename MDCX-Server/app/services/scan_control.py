"""
扫描控制服务

管理启动自动扫描的冷却机制、有效期重置规则、扫描记录持久化。
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config
from app.db.database import get_database
from app.db.models import ScanRecord
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ScanControlService:
    """扫描控制服务

    功能：
    1. 冷却机制：首次启动扫描后，冷却期内不再自动扫描
    2. 有效期重置：超过指定天数未使用，重置冷却状态
    3. 记录持久化：所有扫描结果写入 scan_records 表
    4. 手动扫描：不受冷却限制，可随时触发
    """

    _instance: Optional["ScanControlService"] = None
    _scan_lock = asyncio.Lock()

    def __init__(self):
        self._initialized = False
        self._cooldown_remaining = 0.0  # 冷却剩余秒数（运行时状态）

    @classmethod
    def get_instance(cls) -> "ScanControlService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ============================================
    # 冷却判断
    # ============================================

    async def should_auto_scan(self) -> bool:
        """判断本次启动是否应该执行自动扫描

        规则：
        1. 如果没有任何扫描记录 → 首次启动，应该扫描
        2. 如果冷却期已过（记录中的 started_at + cooldown < now）→ 应该扫描
        3. 如果超过重置天数（上次扫描距今 > reset_days）→ 重置冷却，应该扫描
        4. 否则 → 冷却期内，不应该扫描

        Returns:
            True=可以自动扫描, False=冷却期内跳过
        """
        config = get_config()
        cooldown_hours = config.scan_control.scan_cooldown_hours
        reset_days = config.scan_control.scan_reset_days

        # 获取最近一次自动扫描（startup 类型）记录
        last_record = await self._get_last_auto_scan()

        if last_record is None:
            # 没有任何扫描记录 → 首次启动
            logger.info("扫描控制: 首次启动，执行自动扫描")
            return True

        last_time = last_record.started_at
        now = datetime.now()

        # 检查有效期重置规则：超过 reset_days 未扫描
        if last_time:
            days_since_last = (now - last_time).total_seconds() / 3600 / 24
            if days_since_last > reset_days:
                logger.info(
                    f"扫描控制: 距上次扫描已 {days_since_last:.1f} 天（阈值 {reset_days} 天），"
                    "重置冷却状态，执行自动扫描"
                )
                return True

        # 检查冷却期：是否还在冷却期内
        if last_time:
            cooldown_end = last_time + timedelta(hours=cooldown_hours)
            if now < cooldown_end:
                remaining = (cooldown_end - now).total_seconds()
                remaining_hours = remaining / 3600
                logger.info(
                    f"扫描控制: 冷却期中（剩余 {remaining_hours:.1f} 小时），"
                    f"跳过本次自动扫描。冷却时长={cooldown_hours}h，上次扫描={last_time}"
                )
                self._cooldown_remaining = remaining
                return False
            else:
                logger.info(f"扫描控制: 冷却期已过，执行自动扫描（冷却时长={cooldown_hours}h）")
                return True

        return True  # 默认执行扫描

    async def _get_last_auto_scan(self) -> Optional[ScanRecord]:
        """获取最近一次自动扫描（startup 类型）记录"""
        try:
            db = get_database()
            async with db.session() as session:
                stmt = (
                    select(ScanRecord)
                    .where(ScanRecord.scan_type == "startup")
                    .order_by(desc(ScanRecord.started_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"扫描控制: 读取最近扫描记录失败: {e}")
            return None

    @property
    def cooldown_remaining(self) -> float:
        """冷却剩余秒数"""
        return self._cooldown_remaining

    # ============================================
    # 扫描记录管理
    # ============================================

    async def create_scan_record(
        self,
        scan_type: str,
        module_name: str | None = None,
    ) -> int:
        """创建扫描记录，返回记录 ID

        Args:
            scan_type: startup / manual / scheduled
            module_name: all=全部模块，或具体模块名

        Returns:
            记录 ID
        """
        db = get_database()
        async with db.session() as session:
            record = ScanRecord(
                scan_type=scan_type,
                module_name=module_name or "all",
                status="running",
                started_at=datetime.now(),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.info(f"扫描控制: 创建记录 id={record.id}, type={scan_type}, module={module_name}")
            return record.id

    async def complete_scan_record(
        self,
        record_id: int,
        status: str,
        total_files: int | None = None,
        added_files: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """更新扫描记录为完成状态

        Args:
            record_id: 记录 ID
            status: completed / failed / timeout
            total_files: 发现的文件总数
            added_files: 新增的记录数
            error_message: 错误信息
        """
        db = get_database()
        # 带重试机制：SQLite 在并发写入时可能 database is locked
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with db.session() as session:
                    stmt = select(ScanRecord).where(ScanRecord.id == record_id)
                    result = await session.execute(stmt)
                    record = result.scalar_one_or_none()
                    if record:
                        record.status = status
                        record.total_files = total_files
                        record.added_files = added_files
                        record.error_message = error_message
                        record.completed_at = datetime.now()
                        await session.commit()
                        logger.info(
                            f"扫描控制: 更新记录 id={record_id}, status={status}, "
                            f"total={total_files}, added={added_files}"
                        )
                    else:
                        logger.warning(f"扫描控制: 记录 id={record_id} 不存在")
                break  # 成功则退出重试循环
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"扫描控制: 更新记录 id={record_id} 失败 (第{attempt+1}次)，重试中: {e}"
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    logger.error(
                        f"扫描控制: 更新记录 id={record_id} 失败（已重试{max_retries}次）: {e}"
                    )

    async def get_scan_records(
        self,
        limit: int = 50,
        offset: int = 0,
        scan_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict], int]:
        """获取扫描记录列表

        Args:
            limit: 每页条数
            offset: 偏移量
            scan_type: 筛选扫描类型
            status: 筛选状态

        Returns:
            (记录列表, 总条数)
        """
        db = get_database()
        async with db.session() as session:
            # 构建查询条件
            conditions = []
            if scan_type:
                conditions.append(ScanRecord.scan_type == scan_type)
            if status:
                conditions.append(ScanRecord.status == status)

            # 查询总数
            count_stmt = select(func.count(ScanRecord.id))
            for cond in conditions:
                count_stmt = count_stmt.where(cond)
            total = await session.scalar(count_stmt) or 0

            # 查询列表
            stmt = select(ScanRecord).order_by(desc(ScanRecord.started_at))
            for cond in conditions:
                stmt = stmt.where(cond)
            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            records = result.scalars().all()

            return [
                {
                    "id": r.id,
                    "scan_type": r.scan_type,
                    "module_name": r.module_name,
                    "status": r.status,
                    "total_files": r.total_files,
                    "added_files": r.added_files,
                    "error_message": r.error_message,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ], total

    # ============================================
    # 手动扫描（不受冷却限制）
    # ============================================

    async def trigger_manual_scan(self) -> dict:
        """触发手动扫描

        手动扫描不受冷却限制，立即执行所有模块的扫描。

        Returns:
            {record_id, message}
        """
        # 创建扫描记录
        record_id = await self.create_scan_record(scan_type="manual")

        # 启动后台扫描任务
        asyncio.create_task(self._run_manual_scan(record_id))

        return {
            "record_id": record_id,
            "message": "手动扫描已启动，扫描任务在后台执行",
        }

    async def _run_manual_scan(self, record_id: int) -> None:
        """执行手动扫描（在后台运行）"""
        import importlib
        from pathlib import Path

        from app.config.manager import get_config
        from app.utils.media_helpers import filter_reachable

        config = get_config()
        modules_config = getattr(config, "modules", None)
        if not modules_config:
            await self.complete_scan_record(
                record_id, "failed", error_message="modules config not found"
            )
            return

        module_scanner_map = {
            "jav": ("app.tasks.jav_scanner", "JavScanner"),
            "chinese": ("app.tasks.chinese_scanner", "ChineseScanner"),
            "fc2": ("app.tasks.fc2_scanner", "Fc2Scanner"),
            "uncensored": ("app.tasks.uncensored_scanner", "UncensoredScanner"),
            "pornhub": ("app.tasks.pornhub_scanner", "PornhubScanner"),
            "western": ("app.tasks.western_scanner", "WesternScanner"),
        }

        total_all = 0
        added_all = 0
        errors = []

        for mod_name, (mod_path, cls_name) in module_scanner_map.items():
            mod_cfg = getattr(modules_config, mod_name, None)
            if mod_cfg and getattr(mod_cfg, "enabled", False):
                dirs = getattr(mod_cfg, "media_dirs", None) or []
                valid_dirs = filter_reachable([str(d) for d in dirs])
                if valid_dirs:
                    try:
                        scanner_mod = importlib.import_module(mod_path)
                        scanner_cls = getattr(scanner_mod, cls_name)
                        scanner = scanner_cls(valid_dirs)
                        result = await asyncio.wait_for(scanner.scan(), timeout=600)
                        added = result.get("movies_added", 0)
                        total = result.get("total", 0)
                        total_all += total
                        added_all += added
                        logger.info(
                            f"手动扫描 [{mod_name}]: 共发现 {total} 个文件，新增 {added} 条记录"
                        )
                    except asyncio.TimeoutError:
                        errors.append(f"{mod_name}: 超时")
                        logger.warning(f"手动扫描 [{mod_name}] 超时")
                    except Exception as e:
                        errors.append(f"{mod_name}: {e}")
                        logger.warning(f"手动扫描 [{mod_name}] 失败: {e}")

        status = "completed" if not errors else "failed"
        await self.complete_scan_record(
            record_id,
            status=status,
            total_files=total_all,
            added_files=added_all,
            error_message="; ".join(errors) if errors else None,
        )
        logger.info(f"手动扫描完成: 共 {total_all} 文件，新增 {added_all}，状态={status}")
