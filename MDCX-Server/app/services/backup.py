"""
自动备份服务（Phase 6 生产级部署）

功能：
- 定时备份数据库（SQLite VACUUM INTO / PostgreSQL pg_dump）
- 备份配置文件（config.yaml）
- 可选备份日志文件
- 压缩备份（gzip / tar.gz）
- 保留策略：自动清理超出 max_backups 的旧备份
- 手动触发：立即创建备份
- 恢复：从备份文件恢复数据库/配置
- 定时调度：APScheduler 集成（daily/weekly/hourly）

备份目录结构：
    data/backups/
    ├── 2026-07-06_030000/
    │   ├── database.db        # SQLite 数据库快照
    │   ├── config.yaml        # 配置文件副本
    │   └── logs/              # 日志文件（可选）
    └── 2026-07-05_030000.tar.gz  # 压缩备份
"""

import gzip
import os
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config.manager import get_config, get_config_manager
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BackupInfo:
    """备份信息描述"""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.created_at = datetime.fromtimestamp(path.stat().st_mtime)
        self.size = path.stat().st_size
        self.is_compressed = path.suffix in (".gz", ".tgz") or path.name.endswith(".tar.gz")
        self.is_dir = path.is_dir()

    @property
    def size_str(self) -> str:
        """人类可读的文件大小"""
        for unit in ("B", "KB", "MB", "GB"):
            if self.size < 1024:
                return f"{self.size:.1f} {unit}"
            self.size /= 1024
        return f"{self.size:.1f} TB"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "created_at": self.created_at.isoformat(),
            "size": self.size,
            "size_str": self.size_str,
            "is_compressed": self.is_compressed,
            "is_dir": self.is_dir,
        }


class BackupService:
    """自动备份服务"""

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job_id = "mdcx_auto_backup"

    # ===== 路径 =====

    def _get_backup_dir(self) -> Path:
        """获取备份根目录"""
        cfg = get_config().backup
        if cfg.backup_dir:
            backup_dir = Path(cfg.backup_dir)
        else:
            manager = get_config_manager()
            backup_dir = manager.computed.backups_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def _get_db_path(self) -> Path:
        """获取数据库文件路径"""
        manager = get_config_manager()
        return manager.computed.database_path

    def _get_config_path(self) -> Path:
        """获取配置文件路径"""
        manager = get_config_manager()
        return manager.computed.config_dir / "config.yaml"

    def _get_logs_dir(self) -> Path:
        """获取日志目录"""
        manager = get_config_manager()
        return manager.computed.logs_dir

    # ===== 核心备份逻辑 =====

    async def create_backup(self, note: str = "") -> dict:
        """创建一次完整备份

        返回备份信息字典
        """
        cfg = get_config().backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}" + (f"_{note}" if note else "")
        backup_dir = self._get_backup_dir()
        backup_path = backup_dir / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"开始创建备份: {backup_path}")

        # 1. 备份数据库
        if cfg.backup_database:
            try:
                db_path = self._get_db_path()
                if db_path.exists():
                    # SQLite: 使用 VACUUM INTO 创建一致性快照
                    if "sqlite" in str(db_path):
                        snapshot_path = backup_path / "database.db"
                        await self._backup_sqlite(db_path, snapshot_path)
                        logger.info(f"数据库快照已保存: {snapshot_path}")
                    else:
                        # PostgreSQL: 使用 pg_dump
                        snapshot_path = backup_path / "database.sql"
                        await self._backup_postgresql(snapshot_path)
                        logger.info(f"数据库导出已保存: {snapshot_path}")
                else:
                    logger.warning(f"数据库文件不存在: {db_path}")
            except Exception as e:
                logger.error(f"数据库备份失败: {e}")

        # 2. 备份配置文件
        if cfg.backup_config:
            try:
                config_path = self._get_config_path()
                if config_path.exists():
                    config_dest = backup_path / "config.yaml"
                    shutil.copy2(str(config_path), str(config_dest))
                    logger.info(f"配置文件已备份: {config_dest}")
                else:
                    logger.warning(f"配置文件不存在: {config_path}")
            except Exception as e:
                logger.error(f"配置备份失败: {e}")

        # 3. 备份日志文件（可选）
        if cfg.backup_logs:
            try:
                logs_dir = self._get_logs_dir()
                if logs_dir.exists():
                    logs_dest = backup_path / "logs"
                    shutil.copytree(str(logs_dir), str(logs_dest), dirs_exist_ok=True)
                    logger.info(f"日志文件已备份: {logs_dest}")
            except Exception as e:
                logger.error(f"日志备份失败: {e}")

        # 4. 压缩（可选）
        final_path = backup_path
        if cfg.compress:
            archive_path = backup_dir / f"{backup_name}.tar.gz"
            with tarfile.open(str(archive_path), "w:gz") as tar:
                tar.add(str(backup_path), arcname=backup_name)
            # 删除原始目录
            shutil.rmtree(str(backup_path), ignore_errors=True)
            final_path = archive_path
            logger.info(f"备份已压缩: {archive_path}")
        else:
            # 写入备份信息文件
            info_file = backup_path / "backup_info.json"
            import json
            with open(info_file, "w", encoding="utf-8") as f:
                json.dump({
                    "created_at": datetime.now().isoformat(),
                    "note": note,
                    "config": cfg.model_dump(),
                }, f, ensure_ascii=False, indent=2)

        # 5. 清理旧备份
        self._cleanup_old_backups()

        result = {
            "name": final_path.name,
            "path": str(final_path),
            "created_at": datetime.now().isoformat(),
            "note": note,
            "compressed": cfg.compress,
        }
        logger.info(f"备份完成: {final_path.name}")
        return result

    async def _backup_sqlite(self, source: Path, dest: Path):
        """SQLite 数据库备份（VACUUM INTO 创建一致性快照）"""
        from sqlalchemy import text
        from app.db.database import get_database

        db = get_database()
        async with db.session() as session:
            # VACUUM INTO 不阻塞写入，创建数据库一致性快照
            await session.execute(text(f"VACUUM INTO '{dest}'"))
            await session.commit()

    async def _backup_postgresql(self, dest: Path):
        """PostgreSQL 数据库备份（pg_dump）"""
        import subprocess
        cfg = get_config().deployment.postgres
        env = os.environ.copy()
        if cfg.password:
            env["PGPASSWORD"] = cfg.password
        cmd = [
            "pg_dump",
            "-h", cfg.host,
            "-p", str(cfg.port),
            "-U", cfg.username,
            "-F", "c",  # custom format
            "-f", str(dest),
            cfg.database,
        ]
        process = await subprocess.create_subprocess_exec(
            *cmd, env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {stderr.decode()}")

    def _cleanup_old_backups(self):
        """清理超出 max_backups 的旧备份"""
        cfg = get_config().backup
        backup_dir = self._get_backup_dir()
        max_backups = cfg.max_backups

        # 列出所有备份（目录和压缩包）
        backups = []
        for item in backup_dir.iterdir():
            if item.is_dir() or item.name.endswith(".tar.gz"):
                backups.append(BackupInfo(item))

        # 按创建时间排序（新→旧）
        backups.sort(key=lambda b: b.created_at, reverse=True)

        # 删除超出保留数量的旧备份
        if len(backups) > max_backups:
            for old_backup in backups[max_backups:]:
                try:
                    if old_backup.is_dir:
                        shutil.rmtree(str(old_backup.path), ignore_errors=True)
                    else:
                        old_backup.path.unlink(missing_ok=True)
                    logger.info(f"已清理旧备份: {old_backup.name}")
                except Exception as e:
                    logger.warning(f"清理旧备份失败 {old_backup.name}: {e}")

    # ===== 列表 / 恢复 / 删除 =====

    def list_backups(self) -> list[dict]:
        """列出所有备份"""
        backup_dir = self._get_backup_dir()
        backups = []
        for item in backup_dir.iterdir():
            if item.is_dir() or item.name.endswith(".tar.gz"):
                try:
                    backups.append(BackupInfo(item).to_dict())
                except Exception:
                    pass
        backups.sort(key=lambda b: b["created_at"], reverse=True)
        return backups

    def delete_backup(self, name: str) -> bool:
        """删除指定备份"""
        backup_dir = self._get_backup_dir()
        target = backup_dir / name
        if not target.exists():
            return False
        # 安全检查：确保路径在备份目录内
        if not str(target.resolve()).startswith(str(backup_dir.resolve())):
            return False
        if target.is_dir():
            shutil.rmtree(str(target), ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        logger.info(f"备份已删除: {name}")
        return True

    async def restore_backup(self, name: str) -> dict:
        """从备份恢复数据库/配置

        恢复策略：
        - 数据库：关闭当前连接 → 替换文件 → 重新初始化
        - 配置：直接覆盖 config.yaml
        - 日志：跳过恢复（避免覆盖当前运行日志）
        """
        backup_dir = self._get_backup_dir()
        backup_path = backup_dir / name

        if not backup_path.exists():
            raise FileNotFoundError(f"备份不存在: {name}")

        # 安全检查
        if not str(backup_path.resolve()).startswith(str(backup_dir.resolve())):
            raise ValueError("路径越界")

        result = {"restored": [], "errors": []}

        # 解压临时目录
        temp_dir = backup_dir / f"_restore_{name}"
        try:
            if backup_path.is_file() and backup_path.name.endswith(".tar.gz"):
                with tarfile.open(str(backup_path), "r:gz") as tar:
                    tar.extractall(str(temp_dir))
                # 找到解压后的实际目录
                extracted = list(temp_dir.iterdir())
                if extracted:
                    source_dir = extracted[0] if len(extracted) == 1 else temp_dir
                else:
                    raise RuntimeError("压缩包为空")
            elif backup_path.is_dir():
                source_dir = backup_path
            else:
                raise RuntimeError("不支持的备份格式")
        except Exception as e:
            raise RuntimeError(f"解压备份失败: {e}")

        # 恢复数据库
        db_snapshot = source_dir / "database.db"
        if db_snapshot.exists():
            try:
                db_path = self._get_db_path()
                # 关闭当前数据库连接
                from app.db.database import get_database
                db = get_database()
                await db.close()

                # 备份当前数据库（恢复前保险）
                if db_path.exists():
                    pre_restore = db_path.with_suffix(".db.prerestore")
                    shutil.copy2(str(db_path), str(pre_restore))

                # 替换数据库文件
                shutil.copy2(str(db_snapshot), str(db_path))
                result["restored"].append("database")

                # 重新初始化数据库
                await db.engine.dispose()
                logger.info("数据库已从备份恢复")
            except Exception as e:
                result["errors"].append(f"数据库恢复失败: {e}")
                logger.error(f"数据库恢复失败: {e}")

        # 恢复配置
        config_snapshot = source_dir / "config.yaml"
        if config_snapshot.exists():
            try:
                config_path = self._get_config_path()
                # 备份当前配置
                if config_path.exists():
                    pre_restore = config_path.with_suffix(".yaml.prerestore")
                    shutil.copy2(str(config_path), str(pre_restore))
                shutil.copy2(str(config_snapshot), str(config_path))
                result["restored"].append("config")
                logger.info("配置文件已从备份恢复")
            except Exception as e:
                result["errors"].append(f"配置恢复失败: {e}")

        # 清理临时目录
        if temp_dir.exists():
            shutil.rmtree(str(temp_dir), ignore_errors=True)

        return result

    def get_backup_stats(self) -> dict:
        """获取备份统计信息"""
        backups = self.list_backups()
        total_size = sum(b["size"] for b in backups)
        backup_dir = self._get_backup_dir()
        cfg = get_config().backup

        return {
            "total_backups": len(backups),
            "total_size": total_size,
            "total_size_str": _format_size(total_size),
            "backup_dir": str(backup_dir),
            "auto_backup_enabled": cfg.enabled,
            "interval": cfg.interval,
            "max_backups": cfg.max_backups,
            "last_backup": backups[0]["created_at"] if backups else None,
        }

    # ===== 定时调度 =====

    def start_scheduled(self):
        """启动定时备份调度器"""
        cfg = get_config().backup
        if not cfg.enabled:
            logger.info("自动备份未启用")
            return

        if self._scheduler:
            self.stop_scheduled()

        self._scheduler = AsyncIOScheduler()

        # 解析时间
        try:
            hour, minute = cfg.schedule_time.split(":")
            hour, minute = int(hour), int(minute)
        except (ValueError, AttributeError):
            hour, minute = 3, 0

        if cfg.interval == "hourly":
            trigger = CronTrigger(minute=minute)
        elif cfg.interval == "daily":
            trigger = CronTrigger(hour=hour, minute=minute)
        elif cfg.interval == "weekly":
            trigger = CronTrigger(day_of_week=cfg.schedule_day, hour=hour, minute=minute)
        else:
            logger.warning(f"未知备份间隔: {cfg.interval}")
            return

        self._scheduler.add_job(
            self._scheduled_backup,
            trigger=trigger,
            id=self._job_id,
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(f"自动备份已启动: {cfg.interval} @ {cfg.schedule_time}")

    def stop_scheduled(self):
        """停止定时备份调度器"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("自动备份已停止")

    async def _scheduled_backup(self):
        """定时备份任务（由调度器调用）"""
        try:
            await self.create_backup(note="scheduled")
        except Exception as e:
            logger.error(f"定时备份失败: {e}")


def _format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# 全局单例
backup_service = BackupService()
