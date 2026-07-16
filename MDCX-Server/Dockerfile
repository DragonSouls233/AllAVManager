# =============================================================================
# MDCX 服务端 Dockerfile
# 构建命令：
#   docker build -f Dockerfile -t mdcx-server:latest .
# =============================================================================
ARG PYTHON_VERSION=3.11

# -----------------------------------------------------------------------------
# Stage 1: 依赖构建层
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

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
COPY requirements.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: 运行时镜像
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

LABEL org.opencontainers.image.title="MDCX-Server"
LABEL org.opencontainers.image.description="视频元数据刮削与管理平台"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        tzdata \
        curl \
        tini \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r mdcx && useradd -r -g mdcx -m -d /home/mdcx -s /bin/bash mdcx

WORKDIR /app

COPY --from=builder /root/.local /home/mdcx/.local

ENV PATH=/home/mdcx/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# 复制全部项目文件
COPY --chown=mdcx:mdcx . ./

RUN mkdir -p /app/data/database /app/data/logs /app/data/config \
             /app/data/backups /app/data/cache \
    && chown -R mdcx:mdcx /app

USER mdcx

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8420/api/v1/health || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8420"]
