# syntax=docker/dockerfile:1.7
# =============================================================================
# MDCX 多阶段 Dockerfile - 支持四档渐进式部署
#
# 构建上下文应为项目根目录（包含 MDCX-Server/ 与 MDCX-Desktop/）：
#   docker build -f MDCX-Server/Dockerfile -t mdcx:latest .
#
# 可选构建参数：
#   --build-arg BUILD_FRONTEND=true   是否在镜像内构建前端（默认 true）
#   --build-arg PYTHON_VERSION=3.11   Python 版本
#   --build-arg NODE_VERSION=20       Node.js 版本
# =============================================================================
ARG PYTHON_VERSION=3.11
ARG NODE_VERSION=20

# -----------------------------------------------------------------------------
# Stage 1: 前端构建（Vue 3 + Element Plus + Vite）
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS frontend-builder
ARG BUILD_FRONTEND=true

WORKDIR /build

# 先复制 package 文件以利用 Docker 层缓存
COPY MDCX-Desktop/package.json MDCX-Desktop/package-lock.json* ./
RUN if [ "$BUILD_FRONTEND" = "true" ]; then \
        npm ci --no-audit --no-fund || npm install --no-audit --no-fund; \
    fi

# 复制前端源码并构建
COPY MDCX-Desktop/ ./
RUN if [ "$BUILD_FRONTEND" = "true" ]; then \
        npm run build:web || npx vite build --config vite.config.web.js; \
    fi

# -----------------------------------------------------------------------------
# Stage 2: 后端依赖层（缓存优化）
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS backend-builder

# 安装构建依赖（编译 curl_cffi/lxml/Pillow 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
        libjpeg-dev \
        zlib1g-dev \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY MDCX-Server/requirements.txt ./
# 安装依赖到独立目录，便于运行阶段复制
RUN pip install --user --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 3: 运行时镜像（精简）
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="MDCX"
LABEL org.opencontainers.image.description="龙魂视频管理系统 - 视频元数据刮削与管理平台"
LABEL org.opencontainers.image.source="https://github.com/MDCX/MDCX"
LABEL org.opencontainers.image.licenses="MIT"

# 安装运行时系统依赖（FFmpeg + 浏览器指纹库依赖 + 时区 + CA 证书）
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        tzdata \
        curl \
        tini \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户（安全）
RUN groupadd -r mdcx && useradd -r -g mdcx -m -d /home/mdcx -s /bin/bash mdcx

WORKDIR /app

# 复制 Python 依赖（从 builder 阶段）
COPY --from=backend-builder /root/.local /home/mdcx/.local
ENV PATH=/home/mdcx/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MDCX_STATIC_DIR=/app/static \
    MDCX_DEPLOY_TIER=standard

# 复制后端源码
COPY --chown=mdcx:mdcx MDCX-Server/ ./

# 复制前端构建产物（优先从 frontend-builder，回退到已存在的 static/）
COPY --from=frontend-builder --chown=mdcx:mdcx /build/dist-web/ ./static/
# 若前端构建产物在 dist/ 而非 dist-web/，用以下兜底
COPY --from=frontend-builder --chown=mdcx:mdcx /build/dist/ ./static-dist-fallback/

# 运行时如果 static/ 为空但 static-dist-fallback/ 有内容，则使用 fallback
RUN if [ ! -f /app/static/index.html ] && [ -f /app/static-dist-fallback/index.html ]; then \
        mv /app/static-dist-fallback/* /app/static/ && \
        rmdir /app/static-dist-fallback; \
    else \
        rm -rf /app/static-dist-fallback; \
    fi

# 创建数据目录
RUN mkdir -p /app/data/database /app/data/logs /app/data/config /app/data/backups /app/data/cache \
    && chown -R mdcx:mdcx /app

# 切换非 root 用户
USER mdcx

# 暴露端口
EXPOSE 8420

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8420/api/v1/health/live || exit 1

# 容器入口（处理数据库迁移 + 启动服务）
# docker-entrypoint.sh 已随 MDCX-Server/ 复制到 /app/，复制到 PATH 中
RUN cp /app/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8420", "--no-browser"]
