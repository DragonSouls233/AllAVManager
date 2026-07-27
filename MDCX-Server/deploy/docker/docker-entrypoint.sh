#!/bin/sh
# =============================================================================
# MDCX Docker 容器入口脚本
#
# 职责：
#   1. 初始化数据目录
#   2. 应用数据库迁移
#   3. 生成默认配置（首次启动）
#   4. 启动 FastAPI 服务
#
# 支持环境变量：
#   MDCX_DEPLOY_TIER    部署档位（lite/standard/advanced/enterprise）
#   MDCX_DB_URL         数据库连接 URL（覆盖默认 SQLite）
#   MDCX_REDIS_URL      Redis 连接 URL（高级档以上）
#   MDCX_STATIC_DIR     前端静态目录（默认 /app/static）
#   MDCX_HOST           监听地址（默认 0.0.0.0）
#   MDCX_PORT           监听端口（默认 8420）
#   MDCX_LOG_LEVEL      日志级别（默认 info）
# =============================================================================

set -e

echo "============================================================"
echo "  MDCX 容器入口"
echo "  档位: ${MDCX_DEPLOY_TIER:-standard}"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"

# ---------- 1. 初始化数据目录 ----------
DATA_DIR="${MDCX_DATA_DIR:-/app/data}"
for sub_dir in database logs config backups cache; do
    mkdir -p "${DATA_DIR}/${sub_dir}"
done
echo "[1/4] 数据目录就绪: ${DATA_DIR}"

# ---------- 2. 处理配置文件 ----------
CONFIG_FILE="${DATA_DIR}/config/config.yaml"
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "[2/4] 首次启动，生成默认配置..."

    # 根据部署档位生成数据库 URL
    if [ -n "${MDCX_DB_URL}" ]; then
        DB_URL="${MDCX_DB_URL}"
    elif [ "${MDCX_DEPLOY_TIER}" = "advanced" ] || [ "${MDCX_DEPLOY_TIER}" = "enterprise" ]; then
        # 高级档/企业档默认使用 PostgreSQL
        DB_URL="postgresql+asyncpg://mdcx:${MDCX_DB_PASSWORD:-mdcx}@${MDCX_DB_HOST:-postgres}:5432/${MDCX_DB_NAME:-mdcx}"
    else
        # 轻量档/标准档默认使用 SQLite
        DB_URL="sqlite+aiosqlite:///${DATA_DIR}/database/scraper.db"
    fi

    cat > "${CONFIG_FILE}" <<EOF
# MDCX 配置文件 - 由 docker-entrypoint.sh 自动生成
# 部署档位: ${MDCX_DEPLOY_TIER:-standard}

app_name: 龙魂视频管理系统

server:
  host: "${MDCX_HOST:-0.0.0.0}"
  port: ${MDCX_PORT:-8420}
  workers: 1
  debug: false

database:
  url: "${DB_URL}"
  pool_size: ${MDCX_DB_POOL_SIZE:-10}
  echo: false

scraper:
  media_dirs: []
  output_dir: "${MDCX_OUTPUT_DIR:-/media}"
  concurrent_limit: 5
  retry_count: 3
  timeout: 30
  language: zh

log:
  level: "${MDCX_LOG_LEVEL:-info}"
  file_enabled: true
  console_enabled: true
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
EOF
    echo "      配置文件已生成: ${CONFIG_FILE}"
    echo "      数据库 URL: ${DB_URL}"
else
    echo "[2/4] 配置文件已存在: ${CONFIG_FILE}"
fi

# ---------- 3. 应用数据库迁移 ----------
echo "[3/4] 检查数据库迁移..."
# 通过 Python 执行迁移（避免直接调用 alembic 的复杂性）
python -c 'import asyncio, sys; sys.path.insert(0, "/app"); exec("""
async def _m():
    try:
        from app.db.database import init_database
        from app.db.migrations import run_migrations
        await init_database()
        applied = await run_migrations()
        if applied:
            print("  迁移完成: " + ", ".join(applied))
        else:
            print("  数据库已是最新版本")
    except Exception as e:
        print("  迁移警告: " + str(e), file=sys.stderr)
asyncio.run(_m())
""")' || echo "  迁移失败，将继续尝试启动服务"

# ---------- 4. 启动服务 ----------
echo "[4/4] 启动 MDCX 服务..."
echo "  监听: ${MDCX_HOST:-0.0.0.0}:${MDCX_PORT:-8420}"
echo "  前端: ${MDCX_STATIC_DIR:-/app/static}"
echo "============================================================"

# 执行传入的命令（默认为 server.py）
exec "$@"
