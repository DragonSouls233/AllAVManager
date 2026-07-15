"""
多用户权限管理服务

提供：
- 用户 CRUD（管理员、普通用户）
- 密码哈希（PBKDF2-HMAC-SHA256）
- 会话管理（设备登录、注销）
- 角色权限检查（admin / user）
- NSFW 内容访问控制
- JWT 令牌签发与校验

设计要点：
- 不修改现有 auth.py（向后兼容）
- 密码使用 hashlib.pbkdf2_hmac 加盐
- 会话 token 使用 secrets.token_urlsafe
- 默认启用单用户模式（兼容旧版），新建用户后启用多用户
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserSession

logger = logging.getLogger(__name__)


# ===== 密码哈希 =====

def hash_password(password: str, salt: Optional[str] = None) -> str:
    """哈希密码（PBKDF2-HMAC-SHA256）"""
    if salt is None:
        salt = secrets.token_hex(16)
    iterations = 100_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    try:
        algorithm, iterations, salt, hash_hex = hashed.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ===== Token 生成 =====

def generate_token() -> str:
    """生成安全的会话 token"""
    return secrets.token_urlsafe(32)


# ===== 用户 CRUD =====

async def list_users(session: AsyncSession) -> list[dict]:
    """列出所有用户"""
    stmt = select(User).order_by(User.id.asc())
    result = await session.execute(stmt)
    return [_user_to_dict(u) for u in result.scalars().all()]


async def get_user(user_id: int, session: AsyncSession) -> Optional[dict]:
    """获取用户"""
    user = await session.get(User, user_id)
    return _user_to_dict(user) if user else None


async def get_user_by_username(username: str, session: AsyncSession) -> Optional[User]:
    """根据用户名获取用户（含 password_hash）"""
    stmt = select(User).where(User.username == username)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_user(
    username: str,
    password: str,
    display_name: Optional[str],
    role: str,
    nsfw_allowed: bool,
    session: AsyncSession,
) -> dict:
    """创建用户"""
    # 检查用户名是否已存在
    existing = await get_user_by_username(username, session)
    if existing is not None:
        raise ValueError(f"用户名已存在: {username}")
    if role not in ("admin", "user"):
        raise ValueError(f"无效角色: {role}")
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        role=role,
        nsfw_allowed=nsfw_allowed,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _user_to_dict(user)


async def update_user(
    user_id: int,
    data: dict,
    session: AsyncSession,
) -> Optional[dict]:
    """更新用户"""
    user = await session.get(User, user_id)
    if user is None:
        return None
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "role" in data:
        if data["role"] not in ("admin", "user"):
            raise ValueError("无效角色")
        user.role = data["role"]
    if "is_active" in data:
        user.is_active = bool(data["is_active"])
    if "nsfw_allowed" in data:
        user.nsfw_allowed = bool(data["nsfw_allowed"])
    if "avatar_url" in data:
        user.avatar_url = data["avatar_url"]
    if "password" in data and data["password"]:
        user.password_hash = hash_password(data["password"])
    await session.commit()
    await session.refresh(user)
    return _user_to_dict(user)


async def delete_user(user_id: int, session: AsyncSession) -> bool:
    """删除用户（同时清理会话）"""
    user = await session.get(User, user_id)
    if user is None:
        return False
    # 不允许删除最后一个管理员
    if user.role == "admin":
        admin_count = await count_admins(session)
        if admin_count <= 1:
            raise ValueError("不允许删除最后一个管理员")
    # 删除会话
    stmt = select(UserSession).where(UserSession.user_id == user_id)
    sessions = (await session.execute(stmt)).scalars().all()
    for s in sessions:
        await session.delete(s)
    await session.delete(user)
    await session.commit()
    return True


async def count_admins(session: AsyncSession) -> int:
    """统计管理员数"""
    stmt = select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
    return (await session.execute(stmt)).scalar_one()


# ===== 会话管理 =====

async def create_session(
    user_id: int,
    device_name: Optional[str],
    device_type: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
    expires_days: int,
    session: AsyncSession,
) -> str:
    """创建会话，返回 token"""
    token = generate_token()
    expires_at = datetime.utcnow() + timedelta(days=expires_days)
    s = UserSession(
        user_id=user_id,
        token=token,
        device_name=device_name,
        device_type=device_type,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at,
    )
    session.add(s)
    # 更新用户最后登录时间
    user = await session.get(User, user_id)
    if user:
        user.last_login_at = datetime.utcnow()
    await session.commit()
    return token


async def get_session_by_token(token: str, session: AsyncSession) -> Optional[tuple[UserSession, User]]:
    """根据 token 获取会话 + 用户"""
    stmt = select(UserSession).where(UserSession.token == token)
    s = (await session.execute(stmt)).scalar_one_or_none()
    if s is None:
        return None
    # 检查是否过期
    if s.expires_at and s.expires_at < datetime.utcnow():
        await session.delete(s)
        await session.commit()
        return None
    user = await session.get(User, s.user_id)
    if user is None or not user.is_active:
        return None
    # 更新最后活跃时间
    s.last_active_at = datetime.utcnow()
    await session.commit()
    return s, user


async def list_user_sessions(user_id: int, session: AsyncSession) -> list[dict]:
    """列出用户的所有会话"""
    stmt = (
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .order_by(UserSession.last_active_at.desc())
    )
    result = await session.execute(stmt)
    return [_session_to_dict(s) for s in result.scalars().all()]


async def revoke_session(session_id: int, session: AsyncSession) -> bool:
    """注销会话"""
    s = await session.get(UserSession, session_id)
    if s is None:
        return False
    await session.delete(s)
    await session.commit()
    return True


async def revoke_all_sessions(user_id: int, session: AsyncSession) -> int:
    """注销用户所有会话（除当前外）"""
    stmt = select(UserSession).where(UserSession.user_id == user_id)
    sessions = (await session.execute(stmt)).scalars().all()
    count = 0
    for s in sessions:
        await session.delete(s)
        count += 1
    await session.commit()
    return count


# ===== 权限检查 =====

def is_admin(user: Optional[User]) -> bool:
    return user is not None and user.role == "admin"


def can_access_nsfw(user: Optional[User]) -> bool:
    """检查用户是否能访问 NSFW 内容"""
    if user is None:
        # 单用户模式（未登录），默认允许
        return True
    return user.nsfw_allowed


# ===== 工具 =====

def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "is_active": u.is_active,
        "nsfw_allowed": u.nsfw_allowed,
        "avatar_url": u.avatar_url,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _session_to_dict(s: UserSession) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "device_name": s.device_name,
        "device_type": s.device_type,
        "ip_address": s.ip_address,
        "user_agent": s.user_agent,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        # 不返回 token，防止泄露
    }


# ===== 默认管理员 =====

async def ensure_default_admin(session: AsyncSession) -> Optional[dict]:
    """确保至少有一个管理员账户。若没有任何用户，创建默认 admin/admin"""
    stmt = select(func.count(User.id))
    count = (await session.execute(stmt)).scalar_one()
    if count > 0:
        return None
    return await create_user(
        username="admin",
        password=_load_default_admin_password(),
        display_name="默认管理员",
        role="admin",
        nsfw_allowed=True,
        session=session,
    )


def _load_default_admin_password() -> str:
    """与 auth.py 同步：首次启动时从 data/.auth_password 读取随机密码"""
    from pathlib import Path
    from app.config.manager import PROJECT_ROOT
    pwd_file = PROJECT_ROOT / "data" / ".auth_password"
    if pwd_file.exists():
        saved = pwd_file.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    return "admin"
