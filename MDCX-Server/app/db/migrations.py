"""
数据库迁移管理

管理数据库 Schema 版本迁移，确保向后兼容。
参考 Hazard804 的迁移设计。

迁移记录存储在 migrations 表中。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text as sa_text

from app.db.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Migration:
    """单个迁移"""

    def __init__(
        self,
        version: str,
        description: str,
        upgrade_sql: str,
        downgrade_sql: Optional[str] = None,
    ):
        """
        初始化

        Args:
            version: 版本号（如 "001", "002"）
            description: 描述
            upgrade_sql: 升级 SQL
            downgrade_sql: 降级 SQL（可选）
        """
        self.version = version
        self.description = description
        self.upgrade_sql = upgrade_sql
        self.downgrade_sql = downgrade_sql


# ============================================
# 迁移定义
# ============================================

MIGRATIONS: list[Migration] = [
    Migration(
        version="001",
        description="初始数据库结构",
        upgrade_sql="SELECT 1; -- 初始表结构由 SQLAlchemy 自动创建，此迁移仅为版本占位",
    ),
    Migration(
        version="002",
        description="添加 movies 表索引优化",
        upgrade_sql="""
            CREATE INDEX IF NOT EXISTS idx_movies_source ON movies(source);
            CREATE INDEX IF NOT EXISTS idx_movies_scraped_at ON movies(scraped_at);
            CREATE INDEX IF NOT EXISTS idx_movies_release_date ON movies(release_date);
        """,
        downgrade_sql="""
            DROP INDEX IF EXISTS idx_movies_source;
            DROP INDEX IF EXISTS idx_movies_scraped_at;
            DROP INDEX IF EXISTS idx_movies_release_date;
        """,
    ),
    Migration(
        version="003",
        description="添加 movies 表 output_dir 字段",
        upgrade_sql="""
            ALTER TABLE movies ADD COLUMN output_dir TEXT DEFAULT NULL;
        """,
    ),
    Migration(
        version="004",
        description="添加 movies 表 verified 字段",
        upgrade_sql="""
            ALTER TABLE movies ADD COLUMN verified INTEGER DEFAULT 0;
        """,
    ),
    Migration(
        version="005",
        description="添加 patch_records 表 result 字段",
        upgrade_sql="""
            ALTER TABLE patch_records ADD COLUMN result TEXT DEFAULT NULL;
        """,
    ),
    Migration(
        version="006",
        description="添加 import_records 表 conflict 和 resolved 字段",
        upgrade_sql="""
            ALTER TABLE import_records ADD COLUMN conflict TEXT DEFAULT NULL;
            ALTER TABLE import_records ADD COLUMN resolved INTEGER DEFAULT 0;
        """,
    ),
    Migration(
        version="007",
        description="添加 settings 表",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """,
    ),
    Migration(
        version="008",
        description="添加 cache 表",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_cache_category ON cache(category);
            CREATE INDEX IF NOT EXISTS idx_cache_key ON cache(key);
        """,
    ),
    Migration(
        version="009",
        description="添加 tags.is_user 字段（区分用户/抓取标签）",
        upgrade_sql="""
            ALTER TABLE tags ADD COLUMN is_user INTEGER DEFAULT 0;
            CREATE INDEX IF NOT EXISTS idx_tags_is_user ON tags(is_user);
        """,
    ),
    Migration(
        version="010",
        description="添加多用户/观影历史/演员订阅表",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                role TEXT DEFAULT 'user',
                is_active INTEGER DEFAULT 1,
                nsfw_allowed INTEGER DEFAULT 1,
                avatar_url TEXT,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                device_name TEXT,
                device_type TEXT,
                ip_address TEXT,
                user_agent TEXT,
                expires_at TIMESTAMP,
                last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(token);

            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                movie_code TEXT,
                duration_watched INTEGER DEFAULT 0,
                total_duration INTEGER,
                progress REAL DEFAULT 0,
                completed INTEGER DEFAULT 0,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_play_history_user_id ON play_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_play_history_movie_id ON play_history(movie_id);
            CREATE INDEX IF NOT EXISTS idx_play_history_movie_code ON play_history(movie_code);
            CREATE INDEX IF NOT EXISTS idx_play_history_played_at ON play_history(played_at);

            CREATE TABLE IF NOT EXISTS actor_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
                notify_new_movie INTEGER DEFAULT 1,
                last_checked_at TIMESTAMP,
                last_movie_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, actor_id)
            );
            CREATE INDEX IF NOT EXISTS idx_actor_subscriptions_user_id ON actor_subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_actor_subscriptions_actor_id ON actor_subscriptions(actor_id);
        """,
    ),
    Migration(
        version="011",
        description="添加 movies.view_status 字段（三态视频标记：browsed/watched/wanted）",
        upgrade_sql="""
            ALTER TABLE movies ADD COLUMN view_status TEXT DEFAULT NULL;
            CREATE INDEX IF NOT EXISTS idx_movies_view_status ON movies(view_status);
        """,
        downgrade_sql="""
            DROP INDEX IF EXISTS idx_movies_view_status;
            ALTER TABLE movies DROP COLUMN view_status;
        """,
    ),
    Migration(
        version="012",
        description="添加 file_organize_jobs 表（文件整理任务：硬链接/复制/移动/软链接/原地点名）",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS file_organize_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL,              -- hardlink/copy/move/symlink/rename
                source_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                movie_id INTEGER REFERENCES movies(id) ON DELETE SET NULL,
                status TEXT DEFAULT 'pending',       -- pending/running/completed/failed/skipped
                conflict_strategy TEXT DEFAULT 'skip', -- skip/overwrite/rename
                error_message TEXT,
                file_size INTEGER,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_file_organize_jobs_status ON file_organize_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_file_organize_jobs_job_type ON file_organize_jobs(job_type);
            CREATE INDEX IF NOT EXISTS idx_file_organize_jobs_movie_id ON file_organize_jobs(movie_id);
        """,
        downgrade_sql="""
            DROP TABLE IF EXISTS file_organize_jobs;
        """,
    ),
    Migration(
        version="013",
        description="扩展 actors 表（name_en/alias/intro/source/source_url 字段，支持 Wikipedia/Wikidata 资料）",
        upgrade_sql="""
            ALTER TABLE actors ADD COLUMN name_en TEXT;
            ALTER TABLE actors ADD COLUMN alias TEXT;
            ALTER TABLE actors ADD COLUMN intro TEXT;
            ALTER TABLE actors ADD COLUMN source TEXT;
            ALTER TABLE actors ADD COLUMN source_url TEXT;
            CREATE INDEX IF NOT EXISTS idx_actors_name_en ON actors(name_en);
        """,
        downgrade_sql="""
            DROP INDEX IF EXISTS idx_actors_name_en;
            ALTER TABLE actors DROP COLUMN name_en;
            ALTER TABLE actors DROP COLUMN alias;
            ALTER TABLE actors DROP COLUMN intro;
            ALTER TABLE actors DROP COLUMN source;
            ALTER TABLE actors DROP COLUMN source_url;
        """,
    ),
    Migration(
        version="014",
        description="扩展 actors 表（zodiac/debut_year/social_links 字段，完善演员档案）",
        upgrade_sql="""
            ALTER TABLE actors ADD COLUMN zodiac TEXT;
            ALTER TABLE actors ADD COLUMN debut_year INTEGER;
            ALTER TABLE actors ADD COLUMN social_links TEXT;
        """,
        downgrade_sql="""
            ALTER TABLE actors DROP COLUMN zodiac;
            ALTER TABLE actors DROP COLUMN debut_year;
            ALTER TABLE actors DROP COLUMN social_links;
        """,
    ),
    Migration(
        version="015",
        description="添加 actor_tags 表（演员自由文本标签系统，与 Tier 分级互补）",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS actor_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                color TEXT,
                is_user INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(actor_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_actor_tags_actor_id ON actor_tags(actor_id);
            CREATE INDEX IF NOT EXISTS idx_actor_tags_name ON actor_tags(name);
            CREATE INDEX IF NOT EXISTS idx_actor_tags_is_user ON actor_tags(is_user);
        """,
        downgrade_sql="""
            DROP TABLE IF EXISTS actor_tags;
        """,
    ),
    Migration(
        version="016",
        description="添加系列订阅/自动整理规则/影片关联图谱/AI推荐表,扩展演员订阅字段",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS series_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
                notify_new_movie INTEGER DEFAULT 1,
                auto_download INTEGER DEFAULT 0,
                preferred_quality TEXT DEFAULT '1080p',
                preferred_tags TEXT,
                last_checked_at TIMESTAMP,
                last_movie_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, series_id)
            );
            CREATE INDEX IF NOT EXISTS idx_series_subscriptions_user_id ON series_subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_series_subscriptions_series_id ON series_subscriptions(series_id);

            CREATE TABLE IF NOT EXISTS auto_organize_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                condition_field TEXT NOT NULL,
                condition_op TEXT NOT NULL,
                condition_value TEXT NOT NULL,
                action TEXT NOT NULL,
                target_path TEXT,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS movie_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                related_movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(movie_id, related_movie_id, relation_type)
            );
            CREATE INDEX IF NOT EXISTS idx_movie_relations_movie_id ON movie_relations(movie_id);
            CREATE INDEX IF NOT EXISTS idx_movie_relations_related_movie_id ON movie_relations(related_movie_id);

            CREATE TABLE IF NOT EXISTS user_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                score REAL NOT NULL,
                reason TEXT,
                dismissed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, movie_id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_recommendations_user_id ON user_recommendations(user_id);

            ALTER TABLE actor_subscriptions ADD COLUMN auto_download INTEGER DEFAULT 0;
            ALTER TABLE actor_subscriptions ADD COLUMN preferred_quality TEXT DEFAULT '1080p';
            ALTER TABLE actor_subscriptions ADD COLUMN preferred_tags TEXT;
        """,
        downgrade_sql="""
            DROP TABLE IF EXISTS user_recommendations;
            DROP TABLE IF EXISTS movie_relations;
            DROP TABLE IF EXISTS auto_organize_rules;
            DROP TABLE IF EXISTS series_subscriptions;
        """,
    ),
    Migration(
        version="017",
        description="添加 movies 表 tmdb_id 字段（fanart.tv 集成）",
        upgrade_sql="""
            ALTER TABLE movies ADD COLUMN tmdb_id INTEGER DEFAULT NULL;
            CREATE INDEX IF NOT EXISTS idx_movies_tmdb_id ON movies(tmdb_id);
        """,
        downgrade_sql="""
            DROP INDEX IF EXISTS idx_movies_tmdb_id;
            ALTER TABLE movies DROP COLUMN tmdb_id;
        """,
    ),
    Migration(
        version="018",
        description="整合 database.py:_run_migrations 的所有列迁移(统一到 migrations.py)",
        upgrade_sql="""
            ALTER TABLE movies ADD COLUMN studio_id INTEGER REFERENCES studios(id) ON DELETE SET NULL;
            ALTER TABLE movies ADD COLUMN series_id INTEGER REFERENCES series(id) ON DELETE SET NULL;
            ALTER TABLE movies ADD COLUMN original_title VARCHAR(500);
            ALTER TABLE movies ADD COLUMN is_uncensored BOOLEAN;
            ALTER TABLE movies ADD COLUMN sample_images TEXT;
            ALTER TABLE movies ADD COLUMN play_count INTEGER DEFAULT 0;
            ALTER TABLE movies ADD COLUMN last_played_at DATETIME;
            ALTER TABLE movies ADD COLUMN fingerprint VARCHAR(64);
            CREATE INDEX IF NOT EXISTS idx_movies_fingerprint ON movies(fingerprint);
        """,
        downgrade_sql="""
            DROP INDEX IF EXISTS idx_movies_fingerprint;
            ALTER TABLE movies DROP COLUMN fingerprint;
            ALTER TABLE movies DROP COLUMN last_played_at;
            ALTER TABLE movies DROP COLUMN play_count;
            ALTER TABLE movies DROP COLUMN sample_images;
            ALTER TABLE movies DROP COLUMN is_uncensored;
            ALTER TABLE movies DROP COLUMN original_title;
            ALTER TABLE movies DROP COLUMN series_id;
            ALTER TABLE movies DROP COLUMN studio_id;
        """,
    ),
    Migration(
        version="019",
        description="新增 is_leak 字段标记流出/破解版本（配合 NFO 后缀 -Leak 识别）",
        upgrade_sql="""
            ALTER TABLE movies ADD COLUMN is_leak BOOLEAN;
        """,
        downgrade_sql="""
            ALTER TABLE movies DROP COLUMN is_leak;
        """,
    ),
    Migration(
        version="020",
        description="新增 actor_compare_urls 表（演员对比URL配置）",
        upgrade_sql="""
            CREATE TABLE IF NOT EXISTS actor_compare_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
                actor_name VARCHAR(100) NOT NULL,
                source VARCHAR(20) NOT NULL,
                url VARCHAR(500) NOT NULL,
                local_directory VARCHAR(500),
                auto_detected_dir BOOLEAN DEFAULT 0,
                last_compare_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS ix_actor_compare_urls_actor_id ON actor_compare_urls(actor_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_actor_compare_source ON actor_compare_urls(actor_id, source);
        """,
        downgrade_sql="""
            DROP TABLE IF EXISTS actor_compare_urls;
        """,
    ),
]


class MigrationManager:
    """
    迁移管理器

    管理数据库 Schema 版本迁移
    """

    def __init__(self):
        """初始化"""
        self.db = get_db()

    async def get_current_version(self) -> Optional[str]:
        """获取当前数据库版本"""
        async with self.db.session() as session:
            result = await session.execute(
                sa_text("SELECT version FROM migrations ORDER BY id DESC LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None

    async def get_applied_migrations(self) -> list[str]:
        """获取已应用的迁移列表"""
        async with self.db.session() as session:
            result = await session.execute(
                sa_text("SELECT version FROM migrations ORDER BY id ASC")
            )
            return [row[0] for row in result.fetchall()]

    async def is_applied(self, version: str) -> bool:
        """检查迁移是否已应用"""
        async with self.db.session() as session:
            result = await session.execute(
                sa_text("SELECT COUNT(*) FROM migrations WHERE version = :version"),
                {"version": version},
            )
            row = result.fetchone()
            return row[0] > 0 if row else False

    async def upgrade(self, target_version: Optional[str] = None) -> list[str]:
        """
        升级数据库

        Args:
            target_version: 目标版本，None 表示升级到最新

        Returns:
            应用的迁移版本列表
        """
        applied = await self.get_applied_migrations()
        applied_versions = set(applied)

        applied_migrations = []

        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue

            if target_version and migration.version > target_version:
                break

            try:
                logger.info(
                    f"Applying migration {migration.version}: {migration.description}"
                )

                # 执行升级 SQL
                if migration.upgrade_sql.strip():
                    async with self.db.session() as session:
                        for statement in migration.upgrade_sql.split(";"):
                            stmt = statement.strip()
                            if stmt:
                                await session.execute(sa_text(stmt))

                # 记录迁移
                async with self.db.session() as session:
                    await session.execute(
                        sa_text("""
                        INSERT INTO migrations (version, description, applied_at)
                        VALUES (:version, :description, :applied_at)
                        """),
                        {
                            "version": migration.version,
                            "description": migration.description,
                            "applied_at": datetime.now().isoformat(),
                        },
                    )

                applied_migrations.append(migration.version)
                logger.info(f"Migration {migration.version} applied successfully")

            except Exception as e:
                error_str = str(e)
                # 忽略"字段已存在"和"表已存在"错误，标记为已应用
                if "duplicate column" in error_str.lower() or "already exists" in error_str.lower():
                    logger.warning(
                        f"Migration {migration.version} skipped (already applied): {e}"
                    )
                    # 标记为已应用
                    try:
                        async with self.db.session() as session:
                            await session.execute(
                                sa_text("""
                                INSERT OR IGNORE INTO migrations (version, description, applied_at)
                                VALUES (:version, :description, :applied_at)
                                """),
                                {
                                    "version": migration.version,
                                    "description": migration.description,
                                    "applied_at": datetime.now().isoformat(),
                                },
                            )
                    except Exception:
                        pass
                    applied_migrations.append(migration.version)
                else:
                    logger.error(
                        f"Migration {migration.version} failed: {e}"
                    )
                    raise

        if not applied_migrations:
            logger.info("Database is up to date")

        return applied_migrations

    async def downgrade(self, target_version: str) -> list[str]:
        """
        降级数据库

        Args:
            target_version: 目标版本

        Returns:
            回滚的迁移版本列表
        """
        applied = await self.get_applied_migrations()
        rolled_back = []

        for migration in reversed(MIGRATIONS):
            if migration.version not in applied:
                continue

            if migration.version <= target_version:
                break

            if not migration.downgrade_sql:
                logger.warning(
                    f"Migration {migration.version} has no downgrade SQL, skipping"
                )
                continue

            try:
                logger.info(
                    f"Rolling back migration {migration.version}: {migration.description}"
                )

                # 执行降级 SQL
                async with self.db.session() as session:
                    for statement in migration.downgrade_sql.split(";"):
                        stmt = statement.strip()
                        if stmt:
                            await session.execute(sa_text(stmt))

                    # 删除迁移记录
                    await session.execute(
                        sa_text("DELETE FROM migrations WHERE version = :version"),
                        {"version": migration.version},
                    )

                rolled_back.append(migration.version)
                logger.info(f"Migration {migration.version} rolled back")

            except Exception as e:
                logger.error(
                    f"Rollback migration {migration.version} failed: {e}"
                )
                raise

        return rolled_back

    async def get_status(self) -> dict:
        """获取迁移状态"""
        applied = await self.get_applied_migrations()
        applied_set = set(applied)

        pending = [
            {
                "version": m.version,
                "description": m.description,
            }
            for m in MIGRATIONS
            if m.version not in applied_set
        ]

        return {
            "current_version": applied[-1] if applied else None,
            "total": len(MIGRATIONS),
            "applied": len(applied),
            "pending": len(pending),
            "pending_migrations": pending,
            "applied_migrations": applied,
        }


# ============================================
# 全局便捷函数
# ============================================

_manager: Optional[MigrationManager] = None


def get_migration_manager() -> MigrationManager:
    """获取迁移管理器实例"""
    global _manager
    if _manager is None:
        _manager = MigrationManager()
    return _manager


async def run_migrations() -> list[str]:
    """
    运行所有待处理的迁移

    Returns:
        应用的迁移版本列表
    """
    manager = get_migration_manager()
    return await manager.upgrade()


async def get_migration_status() -> dict:
    """获取迁移状态"""
    manager = get_migration_manager()
    return await manager.get_status()
