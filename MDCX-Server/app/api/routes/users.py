"""多用户管理路由

提供：
- 用户 CRUD（管理员权限）
- 会话管理（设备列表、注销）
- 用户登录 / 登出（基于 token）
- NSFW 权限检查
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services import user_manager as svc

router = APIRouter()


# ===== 用户 CRUD =====

@router.get("")
async def list_users(session: AsyncSession = Depends(get_session)):
    """列出所有用户"""
    items = await svc.list_users(session)
    return {"items": items}


@router.get("/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends(get_session)):
    """获取单个用户"""
    user = await svc.get_user(user_id, session)
    if user is None:
        raise HTTPException(404, "用户不存在")
    return user


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "user"            # admin / user
    nsfw_allowed: bool = True


@router.post("")
async def create_user(body: CreateUserRequest, session: AsyncSession = Depends(get_session)):
    """创建用户"""
    try:
        return await svc.create_user(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
            nsfw_allowed=body.nsfw_allowed,
            session=session,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    nsfw_allowed: Optional[bool] = None
    avatar_url: Optional[str] = None
    password: Optional[str] = None


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新用户"""
    try:
        result = await svc.update_user(user_id, body.model_dump(exclude_none=True), session)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result is None:
        raise HTTPException(404, "用户不存在")
    return result


@router.delete("/{user_id}")
async def delete_user(user_id: int, session: AsyncSession = Depends(get_session)):
    """删除用户"""
    try:
        success = await svc.delete_user(user_id, session)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": success}


# ===== 登录 / 登出 =====

class LoginRequest(BaseModel):
    username: str
    password: str
    device_name: Optional[str] = None
    device_type: Optional[str] = None  # web / desktop / mobile
    expires_days: int = 30


@router.post("/login")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
):
    """用户登录，返回 token + 用户信息"""
    user = await svc.get_user_by_username(body.username, session)
    if user is None or not svc.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(403, "用户已被禁用")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")
    token = await svc.create_session(
        user_id=user.id,
        device_name=body.device_name,
        device_type=body.device_type,
        ip_address=ip,
        user_agent=ua,
        expires_days=body.expires_days,
        session=session,
    )
    return {
        "token": token,
        "user": svc._user_to_dict(user),
    }


class VerifyTokenRequest(BaseModel):
    token: str


@router.post("/verify")
async def verify_token(
    body: VerifyTokenRequest,
    session: AsyncSession = Depends(get_session),
):
    """验证 token，返回用户信息"""
    result = await svc.get_session_by_token(body.token, session)
    if result is None:
        raise HTTPException(401, "无效或过期的 token")
    s, user = result
    return {
        "user": svc._user_to_dict(user),
        "session": svc._session_to_dict(s),
    }


@router.post("/logout")
async def logout(
    body: VerifyTokenRequest,
    session: AsyncSession = Depends(get_session),
):
    """登出（注销当前 token）"""
    result = await svc.get_session_by_token(body.token, session)
    if result is None:
        return {"ok": True}
    s, _ = result
    await svc.revoke_session(s.id, session)
    return {"ok": True}


# ===== 会话管理 =====

@router.get("/{user_id}/sessions")
async def list_sessions(user_id: int, session: AsyncSession = Depends(get_session)):
    """列出用户的所有设备会话"""
    items = await svc.list_user_sessions(user_id, session)
    return {"items": items}


@router.delete("/{user_id}/sessions/{session_id}")
async def revoke_session(
    user_id: int,
    session_id: int,
    session: AsyncSession = Depends(get_session),
):
    """注销指定会话"""
    success = await svc.revoke_session(session_id, session)
    return {"ok": success}


@router.post("/{user_id}/revoke-all-sessions")
async def revoke_all_sessions(user_id: int, session: AsyncSession = Depends(get_session)):
    """注销用户所有会话"""
    count = await svc.revoke_all_sessions(user_id, session)
    return {"revoked": count}


# ===== 初始化 =====

@router.post("/ensure-default-admin")
async def ensure_default_admin(session: AsyncSession = Depends(get_session)):
    """确保存在默认管理员账户（首次部署时调用）"""
    user = await svc.ensure_default_admin(session)
    if user is None:
        return {"created": False, "message": "已存在用户"}
    return {"created": True, "user": user, "message": "默认管理员已创建（admin/admin）"}
