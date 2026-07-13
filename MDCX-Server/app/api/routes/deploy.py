"""
部署档位管理路由

提供四档渐进式部署方案的信息查询接口：
  - GET /deploy/tiers          四档对比表
  - GET /deploy/current        当前运行档位
  - GET /deploy/tiers/{tier}   指定档位详情
  - GET /deploy/tiers/{tier}/files   指定档位部署文件清单
  - GET /deploy/tiers/{tier}/env-vars 指定档位环境变量
  - GET /deploy/runtime-info   运行时环境信息（容器/K8s/Python 检测）
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.deploy_tiers import (
    DEPLOY_TIERS,
    TierId,
    detect_deploy_tier,
    get_current_tier_info,
    get_env_vars,
    get_tier_comparison,
    get_tier_files,
)

router = APIRouter()


@router.get("/tiers")
async def list_tiers():
    """获取四档部署对比表

    返回 lite/standard/advanced/enterprise 四档的完整对比信息，
    包含技术栈、能力、资源要求、特性、限制等。
    """
    return {
        "tiers": get_tier_comparison(),
        "current_tier": detect_deploy_tier(),
    }


@router.get("/current")
async def get_current_tier():
    """获取当前部署档位的详细信息"""
    tier = get_current_tier_info()
    return {
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
    }


@router.get("/tiers/{tier_id}")
async def get_tier_detail(tier_id: str):
    """获取指定档位的详细信息

    Args:
        tier_id: 档位 ID（lite/standard/advanced/enterprise）
    """
    if tier_id not in DEPLOY_TIERS:
        raise HTTPException(
            status_code=404,
            detail=f"未知档位: {tier_id}，可选值: {', '.join(DEPLOY_TIERS.keys())}",
        )
    tier = DEPLOY_TIERS[tier_id]  # type: ignore[index]
    return {
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


@router.get("/tiers/{tier_id}/files")
async def get_tier_files_list(tier_id: str):
    """获取指定档位所需的部署文件清单"""
    if tier_id not in DEPLOY_TIERS:
        raise HTTPException(
            status_code=404,
            detail=f"未知档位: {tier_id}，可选值: {', '.join(DEPLOY_TIERS.keys())}",
        )
    files = get_tier_files(tier_id)  # type: ignore[arg-type]
    return {
        "tier_id": tier_id,
        "files": files,
        "total": len(files),
        "required_count": sum(1 for f in files if f.get("required")),
    }


@router.get("/tiers/{tier_id}/env-vars")
async def get_tier_env_vars(tier_id: str):
    """获取指定档位需要配置的环境变量"""
    if tier_id not in DEPLOY_TIERS:
        raise HTTPException(
            status_code=404,
            detail=f"未知档位: {tier_id}，可选值: {', '.join(DEPLOY_TIERS.keys())}",
        )
    env_vars = get_env_vars(tier_id)  # type: ignore[arg-type]
    return {
        "tier_id": tier_id,
        "env_vars": env_vars,
        "total": len(env_vars),
        "required_count": sum(1 for v in env_vars if v.get("required")),
    }


@router.get("/runtime-info")
async def get_runtime_info():
    """获取运行时环境信息

    用于诊断当前部署环境，辅助判断档位选择是否正确。
    """
    # 检测容器/K8s 环境
    is_docker = Path("/.dockerenv").exists()
    is_k8s = bool(os.getenv("KUBERNETES_SERVICE_HOST"))
    has_compose = any(k.startswith("com.docker.compose.") for k in os.environ)

    # 收集 MDCX 相关环境变量
    mdcx_env = {
        k: ("***" if "PASSWORD" in k or "SECRET" in k or "TOKEN" in k else v)
        for k, v in os.environ.items()
        if k.startswith("MDCX_") or k in ("TZ", "LANG")
    }

    return {
        "detected_tier": detect_deploy_tier(),
        "explicit_tier": os.getenv("MDCX_DEPLOY_TIER", ""),
        "environment": {
            "is_docker": is_docker,
            "is_kubernetes": is_k8s,
            "is_docker_compose": has_compose,
            "k8s_service_host": os.getenv("KUBERNETES_SERVICE_HOST", ""),
            "k8s_namespace": os.getenv("KUBERNETES_NAMESPACE", "") or os.getenv("POD_NAMESPACE", ""),
        },
        "runtime": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
        },
        "mdcx_env_vars": mdcx_env,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/guide")
async def get_deploy_guide(
    tier: str = Query("auto", description="目标档位（auto=根据环境推荐）"),
):
    """获取部署指南

    根据目标档位返回对应的部署步骤、命令、注意事项。
    """
    if tier == "auto":
        target_tier = detect_deploy_tier()
    elif tier not in DEPLOY_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"未知档位: {tier}，可选值: auto, {', '.join(DEPLOY_TIERS.keys())}",
        )
    else:
        target_tier = tier  # type: ignore[assignment]

    tier_info = DEPLOY_TIERS[target_tier]  # type: ignore[index]

    guides: dict[str, dict] = {
        "lite": {
            "steps": [
                "1. 安装 Python 3.11+（https://python.org）",
                "2. 克隆项目代码到本地",
                "3. 运行 python deploy.py --tier lite",
                "4. 访问 http://127.0.0.1:8420",
            ],
            "commands": [
                "cd MDCX-Server",
                "python -m venv venv",
                "venv\\Scripts\\activate  # Windows",
                "source venv/bin/activate  # Linux/Mac",
                "pip install -r requirements.txt",
                "python deploy.py --tier lite",
            ],
            "notes": [
                "首次启动会自动创建数据库与配置文件",
                "Windows 用户可运行 deploy.py --install-service 注册开机自启",
                "Linux 用户可参考 deploy/systemd/mdcx.service",
            ],
        },
        "standard": {
            "steps": [
                "1. 安装 Docker 与 Docker Compose",
                "2. 进入 MDCX-Server 目录",
                "3. 运行 docker compose up -d",
                "4. 访问 http://宿主机IP:8420",
            ],
            "commands": [
                "cd MDCX-Server",
                "docker compose build",
                "docker compose up -d",
                "docker compose logs -f",
                "docker compose down",
            ],
            "notes": [
                "镜像构建包含前端+后端多阶段构建，首次构建约 5-10 分钟",
                "数据持久化于 mdcx-data 卷，删除容器不会丢失数据",
                "媒体库默认挂载 ./media，可在 docker-compose.yml 修改",
                "如已预构建前端，可用 --build-arg BUILD_FRONTEND=false 加速",
            ],
        },
        "advanced": {
            "steps": [
                "1. 安装 Docker 与 Docker Compose",
                "2. 复制 .env.example 为 .env 并修改密码",
                "3. 准备 TLS 证书（可选，放置于 deploy/nginx/certs/）",
                "4. 运行 docker compose -f docker-compose.advanced.yml up -d",
                "5. 访问 https://你的域名",
            ],
            "commands": [
                "cd MDCX-Server",
                "cp .env.example .env",
                "vim .env  # 修改 POSTGRES_PASSWORD/REDIS_PASSWORD",
                "mkdir -p deploy/nginx/certs",
                "# 放置 fullchain.pem 和 privkey.pem",
                "docker compose -f docker-compose.advanced.yml up -d",
                "docker compose -f docker-compose.advanced.yml logs -f mdcx",
            ],
            "notes": [
                "生产环境务必修改所有默认密码（至少 16 位强密码）",
                "PostgreSQL 数据持久化于 postgres-data 卷",
                "Redis 开启 AOF 持久化与 LRU 淘汰策略",
                "Nginx 默认启用 TLS，若无证书可使用 nginx-http.conf",
                "Let's Encrypt 用户可配合 acme-companion 自动签发证书",
            ],
        },
        "enterprise": {
            "steps": [
                "1. 准备 K8s 集群（>= 1.24）",
                "2. 配置 StorageClass（支持 RWX，如 NFS/CephFS）",
                "3. 部署 Ingress Controller（nginx-ingress）",
                "4. 部署 cert-manager（可选，自动 TLS）",
                "5. 构建并推送镜像到仓库",
                "6. 修改 mdcx.yaml 中的 Secret 与域名",
                "7. kubectl apply -f deploy/kubernetes/mdcx.yaml",
            ],
            "commands": [
                "# 构建并推送镜像",
                "docker build -f MDCX-Server/Dockerfile -t your-registry/mdcx:v1.0.0 .",
                "docker push your-registry/mdcx:v1.0.0",
                "",
                "# 修改 K8s 清单中的镜像地址与 Secret",
                "vim MDCX-Server/deploy/kubernetes/mdcx.yaml",
                "",
                "# 部署",
                "kubectl apply -f MDCX-Server/deploy/kubernetes/mdcx.yaml",
                "",
                "# 查看状态",
                "kubectl -n mdcx get pods,svc,ingress,hpa",
                "kubectl -n mdcx logs -f deployment/mdcx",
            ],
            "notes": [
                "PVC mdcx-media 需 RWX StorageClass（多副本共享）",
                "建议 PostgreSQL/Redis 使用集群外的高可用实例",
                "HPA 默认 CPU>70% 扩容，可根据实际调整",
                "Pod 反亲和确保副本分散到不同节点",
                "启用 NetworkPolicy 进一步限制网络访问",
                "Prometheus 监控需部署 kube-prometheus-stack",
            ],
        },
    }

    guide = guides[target_tier]
    return {
        "tier_id": target_tier,
        "tier_name": tier_info.name,
        "steps": guide["steps"],
        "commands": guide["commands"],
        "notes": guide["notes"],
        "deploy_command": tier_info.deploy_command,
        "files": get_tier_files(target_tier),
        "env_vars": get_env_vars(target_tier),
    }
