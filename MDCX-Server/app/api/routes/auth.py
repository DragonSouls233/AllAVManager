"""
登录认证路由

提供 JWT 登录认证，保护所有 API 端点（除登录和健康检查外）。
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import get_config, get_config_manager, PROJECT_ROOT
from app.db.database import get_session
from app.services import user_manager as svc

router = APIRouter()

# ===== 安全配置 =====
def _load_secret() -> str:
    """解析 JWT 签名密钥。

    - 优先用环境变量 SCRAPER_AUTH_SECRET（运维可显式指定）。
    - 否则把密钥持久化到 data/.auth_secret，使重启后旧 token 仍有效，
      避免每次重启都把已登录用户踢下线。
    - 任何异常都回退为本次进程内存密钥（行为等同旧版，仅本进程有效）。
    """
    env = os.getenv("SCRAPER_AUTH_SECRET")
    if env:
        return env
    try:
        secret_file = PROJECT_ROOT / "data" / ".auth_secret"
        if secret_file.exists():
            saved = secret_file.read_text(encoding="utf-8").strip()
            if saved:
                return saved
        secret = secrets.token_hex(32)
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secret, encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
        return secret
    except Exception:
        return secrets.token_hex(32)


SECRET_KEY = _load_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 天

# 默认管理员账号
DEFAULT_USERNAME = os.getenv("SCRAPER_AUTH_USERNAME", "admin")
DEFAULT_PASSWORD = "admin123654!"

# 使用 SHA256 哈希密码（避免 passlib bcrypt 在 Python 3.13 上的兼容问题）
security = HTTPBearer(auto_error=False)
_password_hash: Optional[str] = None


def _get_password_hash() -> str:
    global _password_hash
    if _password_hash is None:
        _password_hash = hashlib.sha256(DEFAULT_PASSWORD.encode()).hexdigest()
    return _password_hash


# ===== 数据模型 =====


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    username: str
    role: Optional[str] = None


# ===== 认证函数 =====


def verify_password(plain_password: str) -> bool:
    """验证密码"""
    return hashlib.sha256(plain_password.encode()).hexdigest() == _get_password_hash()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """解码 JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[dict]:
    """获取当前用户（可选认证，不强制）"""
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        return None
    username = payload.get("sub")
    if username != DEFAULT_USERNAME:
        return None
    return {"username": username}


async def require_user(current_user: Optional[dict] = Depends(get_current_user)):
    """要求用户已登录"""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_current_user_info(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """返回当前登录用户信息 {username, role}，任意已登录用户均可。

    引导账号(硬编码 admin)始终视为管理员；其他用户从 DB 加载并读取 role。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效")
    # 引导账号始终为管理员（即便 DB 中尚未初始化）
    if username == DEFAULT_USERNAME:
        return {"username": username, "role": "admin"}
    user = await svc.get_user_by_username(username, session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return {"username": username, "role": getattr(user, "role", "user")}


async def require_admin(current_user: dict = Depends(get_current_user_info)):
    """要求当前用户为管理员（服务端配置级操作使用）"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限才能执行此操作",
        )
    return current_user


# ===== API 端点 =====


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """用户登录"""
    if request.username != DEFAULT_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not verify_password(request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    access_token = create_access_token(data={"sub": request.username})
    return TokenResponse(
        access_token=access_token,
        username=request.username,
    )


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: dict = Depends(get_current_user_info)):
    """获取当前用户信息（含角色）"""
    return UserInfo(username=current_user["username"], role=current_user.get("role"))


@router.post("/check")
async def check_auth(current_user: Optional[dict] = Depends(get_current_user)):
    """检查认证状态"""
    if current_user:
        return {"authenticated": True, "username": current_user["username"]}
    return {"authenticated": False}


# ===== 可信 IP 配置 =====


class TrustedIPConfig(BaseModel):
    """可信 IP 配置"""
    enable_trusted_ip: bool
    trusted_ips: list[str]


@router.get("/trusted-ip")
async def get_trusted_ip_config():
    """获取可信 IP 配置（公开端点，便于登录页判断是否需要输入密码）"""
    cfg = get_config()
    return {
        "enable_trusted_ip": cfg.auth.enable_trusted_ip,
        "trusted_ips": cfg.auth.trusted_ips,
    }


@router.put("/trusted-ip", response_model=TrustedIPConfig)
async def update_trusted_ip_config(
    config: TrustedIPConfig,
    current_user: dict = Depends(require_user),
):
    """更新可信 IP 配置（需要登录）"""
    from app.config.manager import get_config_manager
    manager = get_config_manager()
    errors = manager.update(
        **{
            "auth.enable_trusted_ip": config.enable_trusted_ip,
            "auth.trusted_ips": config.trusted_ips,
        }
    )
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    manager.save()
    return TrustedIPConfig(
        enable_trusted_ip=manager.config.auth.enable_trusted_ip,
        trusted_ips=manager.config.auth.trusted_ips,
    )
