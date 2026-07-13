"""
MDCX 部署档位信息模块（四档渐进式部署）

四档部署方案：
  1. lite        轻量档 - 单机 Python 直接运行，SQLite，无缓存无代理
  2. standard    标准档 - 单容器 Docker，SQLite，无缓存无代理
  3. advanced    高级档 - 多容器编排（app+postgres+redis+nginx），PostgreSQL+Redis+Nginx
  4. enterprise  企业档 - Kubernetes 集群，PostgreSQL+Redis+Nginx+HPA 自动扩缩

档位选择原则：
  - 个人本地体验 / Windows 桌面 → lite
  - NAS / 小型服务器 / 快速部署 → standard
  - 中型团队 / 多用户并发 / 高性能 → advanced
  - 大规模生产 / 高可用 / 水平扩展 → enterprise

环境变量探测：
  - MDCX_DEPLOY_TIER  显式指定档位（最高优先级）
  - KUBERNETES_SERVICE_HOST  自动检测 K8s 环境 → enterprise
  - .dockerenv 文件存在  自动检测 Docker → standard
  - 其他  默认 → lite
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

__all__ = [
    "DeployTier",
    "DEPLOY_TIERS",
    "detect_deploy_tier",
    "get_current_tier_info",
    "get_tier_comparison",
]


TierId = Literal["lite", "standard", "advanced", "enterprise"]


@dataclass(frozen=True)
class DeployTier:
    """部署档位定义"""

    tier_id: TierId
    name: str
    tagline: str
    description: str

    # 技术栈
    runtime: str
    database: str
    cache: str
    reverse_proxy: str
    orchestration: str

    # 能力
    scalability: str
    high_availability: bool
    auto_scaling: bool
    tls_termination: bool
    monitoring: bool

    # 适用场景
    use_cases: list[str]
    min_resources: dict[str, str]
    recommended_resources: dict[str, str]

    # 特性列表
    features: list[str]
    limitations: list[str]

    # 部署命令
    deploy_command: str
    docs_anchor: str


# =============================================================================
# 四档定义
# =============================================================================
DEPLOY_TIERS: dict[TierId, DeployTier] = {
    "lite": DeployTier(
        tier_id="lite",
        name="轻量档",
        tagline="单机快速启动",
        description="直接使用 Python 运行，SQLite 数据库，适合个人本地体验与 Windows 桌面部署。零容器开销，启动最快。",
        runtime="Python 3.11+",
        database="SQLite (aiosqlite)",
        cache="无",
        reverse_proxy="无",
        orchestration="systemd / Windows 服务",
        scalability="单进程",
        high_availability=False,
        auto_scaling=False,
        tls_termination=False,
        monitoring=False,
        use_cases=[
            "个人本地观影管理",
            "Windows 桌面应用",
            "开发调试与功能体验",
            "资源受限的 VPS",
        ],
        min_resources={"cpu": "1 核", "memory": "512MB", "disk": "1GB"},
        recommended_resources={"cpu": "2 核", "memory": "2GB", "disk": "10GB"},
        features=[
            "零依赖容器运行",
            "SQLite 单文件数据库",
            "前端静态文件由 FastAPI 直接服务",
            "支持 Windows 服务 / Linux systemd 开机自启",
            "定时数据库备份",
        ],
        limitations=[
            "不支持多副本",
            "无 Redis 缓存层",
            "无反向代理与 TLS",
            "SQLite 并发写入受限",
        ],
        deploy_command="python deploy.py --tier lite",
        docs_anchor="lite",
    ),
    "standard": DeployTier(
        tier_id="standard",
        name="标准档",
        tagline="单容器 Docker 部署",
        description="使用 docker-compose 启动单个应用容器，SQLite 数据库，数据卷持久化。适合 NAS、小型服务器快速部署。",
        runtime="Docker (python:3.11-slim)",
        database="SQLite (aiosqlite)",
        cache="无",
        reverse_proxy="无（端口直接映射）",
        orchestration="docker compose",
        scalability="单容器",
        high_availability=False,
        auto_scaling=False,
        tls_termination=False,
        monitoring=True,
        use_cases=[
            "NAS 家庭媒体中心",
            "小型团队共享",
            "快速容器化部署",
            "CI/CD 流水线验证",
        ],
        min_resources={"cpu": "1 核", "memory": "1GB", "disk": "2GB"},
        recommended_resources={"cpu": "2 核", "memory": "2GB", "disk": "20GB"},
        features=[
            "一键 docker compose up 部署",
            "多阶段构建镜像（前端+后端）",
            "数据卷持久化（数据库/配置/日志/媒体）",
            "容器健康检查与自动重启",
            "资源限制（CPU/内存）",
            "非 root 用户运行（安全加固）",
            "FFmpeg 内置",
        ],
        limitations=[
            "单容器无法水平扩展",
            "SQLite 并发受限",
            "无反向代理（端口直接暴露）",
            "无 TLS 终止",
        ],
        deploy_command="docker compose up -d",
        docs_anchor="standard",
    ),
    "advanced": DeployTier(
        tier_id="advanced",
        name="高级档",
        tagline="多容器编排部署",
        description="使用 docker-compose 编排 app + PostgreSQL + Redis + Nginx 四个容器。PostgreSQL 提供高并发数据库，Redis 提供缓存层，Nginx 提供反向代理与 TLS 终止。",
        runtime="Docker Compose (多容器)",
        database="PostgreSQL 16 (asyncpg)",
        cache="Redis 7",
        reverse_proxy="Nginx 1.27",
        orchestration="docker compose -f docker-compose.advanced.yml",
        scalability="单主机多容器",
        high_availability=True,
        auto_scaling=False,
        tls_termination=True,
        monitoring=True,
        use_cases=[
            "中型团队多用户并发",
            "大规模媒体库（10万+ 影片）",
            "需要 TLS HTTPS 访问",
            "需要 Redis 缓存加速",
            "内网生产环境",
        ],
        min_resources={"cpu": "2 核", "memory": "4GB", "disk": "20GB"},
        recommended_resources={"cpu": "4 核", "memory": "8GB", "disk": "100GB"},
        features=[
            "PostgreSQL 16 高并发数据库",
            "Redis 7 缓存层（LRU + AOF 持久化）",
            "Nginx 反向代理 + HTTP/2 + TLS",
            "WebSocket 代理（实时日志流）",
            "HLS 视频流优化（关闭缓冲）",
            "静态资源强缓存（30天）",
            "gzip 压缩",
            "安全头（HSTS/X-Frame-Options 等）",
            "内部网络隔离（postgres/redis 不对外）",
            "Let's Encrypt 自动证书（ACME）",
        ],
        limitations=[
            "单主机部署，无跨节点水平扩展",
            "无自动扩缩容",
            "需手动管理 TLS 证书",
        ],
        deploy_command="docker compose -f docker-compose.advanced.yml up -d",
        docs_anchor="advanced",
    ),
    "enterprise": DeployTier(
        tier_id="enterprise",
        name="企业档",
        tagline="Kubernetes 生产级集群",
        description="部署到 Kubernetes 集群，支持多副本水平扩展、HPA 自动扩缩容、Pod 反亲和、滚动更新、Prometheus 监控。适合大规模生产环境。",
        runtime="Kubernetes",
        database="PostgreSQL 16（外部集群或集群内）",
        cache="Redis 7（外部集群或集群内）",
        reverse_proxy="Nginx Ingress Controller",
        orchestration="kubectl / Helm",
        scalability="多副本水平扩展",
        high_availability=True,
        auto_scaling=True,
        tls_termination=True,
        monitoring=True,
        use_cases=[
            "大规模生产环境",
            "多节点高可用",
            "弹性伸缩应对流量高峰",
            "企业级监控与告警",
            "CI/CD 持续部署",
        ],
        min_resources={"cpu": "4 核", "memory": "8GB", "disk": "50GB", "nodes": "2"},
        recommended_resources={"cpu": "8 核", "memory": "16GB", "disk": "200GB", "nodes": "3+"},
        features=[
            "多副本 Deployment（初始 2 副本）",
            "HPA 自动扩缩容（CPU/内存阈值）",
            "Pod 反亲和（跨节点分散）",
            "拓扑分布约束",
            "PodDisruptionBudget（保证可用性）",
            "滚动更新（maxSurge=1, maxUnavailable=0）",
            "startupProbe + livenessProbe + readinessProbe",
            "ConfigMap + Secret 配置分离",
            "PVC 持久化存储（data + media RWX）",
            "Nginx Ingress + cert-manager 自动证书",
            "Prometheus ServiceMonitor 抓取",
            "安全上下文（runAsNonRoot + drop ALL capabilities）",
            "资源 requests/limits",
            "网络策略可扩展",
        ],
        limitations=[
            "需要 K8s 集群运维能力",
            "需要支持 RWX 的 StorageClass（如 NFS/CephFS）",
            "配置复杂度较高",
        ],
        deploy_command="kubectl apply -f deploy/kubernetes/mdcx.yaml",
        docs_anchor="enterprise",
    ),
}


# =============================================================================
# 档位探测
# =============================================================================
def detect_deploy_tier() -> TierId:
    """自动探测当前部署档位

    探测优先级：
      1. MDCX_DEPLOY_TIER 环境变量（显式指定）
      2. KUBERNETES_SERVICE_HOST（K8s 集群内）
      3. /.dockerenv 文件存在（Docker 容器内）
      4. docker-compose 环境特征（com.docker.compose.* 环境变量）
      5. 默认 lite

    Returns:
        档位 ID
    """
    # 1. 显式指定
    explicit = os.getenv("MDCX_DEPLOY_TIER", "").strip().lower()
    if explicit in DEPLOY_TIERS:
        return explicit  # type: ignore[return-value]

    # 2. K8s 环境
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return "enterprise"

    # 3. Docker 容器
    if Path("/.dockerenv").exists():
        # 进一步判断是否多容器编排（有 postgres/redis 服务名解析）
        # 简化：若 MDCX_DB_HOST 指向 postgres 服务，视为 advanced
        db_host = os.getenv("MDCX_DB_HOST", "").lower()
        redis_url = os.getenv("MDCX_REDIS_URL", "").lower()
        if "postgres" in db_host or "redis" in redis_url:
            return "advanced"
        return "standard"

    # 4. 检查 docker-compose 特征
    for key in os.environ:
        if key.startswith("com.docker.compose."):
            return "standard"

    # 5. 默认
    return "lite"


def get_current_tier_info() -> DeployTier:
    """获取当前部署档位的完整信息"""
    tier_id = detect_deploy_tier()
    return DEPLOY_TIERS[tier_id]


def get_tier_comparison() -> list[dict]:
    """获取四档对比表（用于 API 返回）

    Returns:
        四档对比数据列表，每档包含 id/name/技术栈/能力/资源要求等
    """
    comparison = []
    for tier in DEPLOY_TIERS.values():
        comparison.append(
            {
                "tier_id": tier.tier_id,
                "name": tier.name,
                "tagline": tier.tagline,
                "description": tier.description,
                "runtime": tier.runtime,
                "database": tier.database,
                "cache": tier.cache,
                "reverse_proxy": tier.reverse_proxy,
                "orchestration": tier.orchestration,
                "scalability": tier.scalability,
                "high_availability": tier.high_availability,
                "auto_scaling": tier.auto_scaling,
                "tls_termination": tier.tls_termination,
                "monitoring": tier.monitoring,
                "use_cases": tier.use_cases,
                "min_resources": tier.min_resources,
                "recommended_resources": tier.recommended_resources,
                "features": tier.features,
                "limitations": tier.limitations,
                "deploy_command": tier.deploy_command,
                "is_current": tier.tier_id == detect_deploy_tier(),
            }
        )
    return comparison


def get_tier_files(tier_id: TierId) -> list[dict]:
    """获取指定档位相关的部署文件清单

    Args:
        tier_id: 档位 ID

    Returns:
        文件清单，每项含 path/description/required
    """
    files_map: dict[str, list[dict]] = {
        "lite": [
            {"path": "deploy.py", "description": "一键部署脚本（Python 直接运行）", "required": True},
            {"path": "server.py", "description": "服务启动入口（含进程守护）", "required": True},
            {"path": "requirements.txt", "description": "Python 依赖清单", "required": True},
            {"path": "deploy/systemd/mdcx.service", "description": "Linux systemd 服务单元", "required": False},
            {"path": "data/config/config.yaml", "description": "运行时配置（自动生成）", "required": False},
        ],
        "standard": [
            {"path": "Dockerfile", "description": "多阶段构建镜像定义", "required": True},
            {"path": "docker-compose.yml", "description": "标准档单容器编排", "required": True},
            {"path": ".dockerignore", "description": "构建上下文忽略清单", "required": True},
            {"path": "docker-entrypoint.sh", "description": "容器入口脚本", "required": True},
            {"path": "requirements.txt", "description": "Python 依赖清单", "required": True},
        ],
        "advanced": [
            {"path": "Dockerfile", "description": "多阶段构建镜像定义", "required": True},
            {"path": "docker-compose.advanced.yml", "description": "高级档四容器编排（app+pg+redis+nginx）", "required": True},
            {"path": ".dockerignore", "description": "构建上下文忽略清单", "required": True},
            {"path": "docker-entrypoint.sh", "description": "容器入口脚本", "required": True},
            {"path": ".env.example", "description": "环境变量配置模板", "required": True},
            {"path": "deploy/nginx/nginx.conf", "description": "Nginx 主配置（TLS+HTTP2）", "required": True},
            {"path": "deploy/nginx/nginx-http.conf", "description": "Nginx HTTP-only 配置（无 TLS）", "required": False},
            {"path": "deploy/nginx/certs/fullchain.pem", "description": "TLS 证书（用户自备）", "required": True},
            {"path": "deploy/nginx/certs/privkey.pem", "description": "TLS 私钥（用户自备）", "required": True},
        ],
        "enterprise": [
            {"path": "deploy/kubernetes/mdcx.yaml", "description": "K8s all-in-one 部署清单", "required": True},
            {"path": "Dockerfile", "description": "镜像构建定义（推送到仓库）", "required": True},
            {"path": ".dockerignore", "description": "构建上下文忽略清单", "required": True},
            {"path": "deploy/systemd/mdcx.service", "description": "单节点兜底方案（可选）", "required": False},
        ],
    }
    return files_map.get(tier_id, [])


def get_env_vars(tier_id: TierId) -> list[dict]:
    """获取指定档位需要的环境变量

    Args:
        tier_id: 档位 ID

    Returns:
        环境变量清单，每项含 name/description/default/required
    """
    common = [
        {"name": "MDCX_DEPLOY_TIER", "description": "部署档位", "default": tier_id, "required": True},
        {"name": "MDCX_HOST", "description": "监听地址", "default": "0.0.0.0", "required": True},
        {"name": "MDCX_PORT", "description": "监听端口", "default": "8420", "required": True},
        {"name": "MDCX_LOG_LEVEL", "description": "日志级别", "default": "info", "required": False},
        {"name": "MDCX_STATIC_DIR", "description": "前端静态目录", "default": "/app/static", "required": True},
        {"name": "MDCX_DATA_DIR", "description": "数据目录", "default": "/app/data", "required": True},
        {"name": "MDCX_OUTPUT_DIR", "description": "媒体输出目录", "default": "/media", "required": False},
        {"name": "TZ", "description": "时区", "default": "Asia/Shanghai", "required": False},
    ]

    if tier_id in ("advanced", "enterprise"):
        common.extend(
            [
                {"name": "MDCX_DB_HOST", "description": "PostgreSQL 主机", "default": "postgres", "required": True},
                {"name": "MDCX_DB_PORT", "description": "PostgreSQL 端口", "default": "5432", "required": True},
                {"name": "MDCX_DB_NAME", "description": "数据库名", "default": "mdcx", "required": True},
                {"name": "MDCX_DB_USER", "description": "数据库用户", "default": "mdcx", "required": True},
                {"name": "MDCX_DB_PASSWORD", "description": "数据库密码", "default": "", "required": True},
                {"name": "MDCX_DB_POOL_SIZE", "description": "连接池大小", "default": "20", "required": False},
                {"name": "MDCX_REDIS_URL", "description": "Redis 连接 URL", "default": "", "required": True},
            ]
        )

    if tier_id == "enterprise":
        common.extend(
            [
                {"name": "KUBERNETES_SERVICE_HOST", "description": "K8s API Server（自动注入）", "default": "", "required": False},
            ]
        )

    return common
