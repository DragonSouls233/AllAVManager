"""
请求级数据库会话注册表与回收中间件

问题背景
--------
MDCX-Server 的大量路由/服务使用 ``session = await mod_db.get_session()`` 或
``await get_module_session(module)`` 获取**裸** ``AsyncSession``，但调用方经常忘记
``await session.close()``，导致连接长时间不归还连接池。这些连接最终由 Python
垃圾回收器回收时，SQLAlchemy 会打印
``The garbage collector is trying to clean up non-checked-in connection`` 警告，
并可能在高并发下耗尽连接池（pool_size=10 + overflow=20）。

解决方案
--------
1. 在 ``ModuleDatabase.get_session()`` / ``SystemDatabase.get_session()`` 创建 session
   时调用 :func:`register_session`，将其登记到**当前请求**的 ``ContextVar`` 列表。
2. 在请求级中间件 :func:`session_cleanup_middleware` 的响应送出后，统一
   ``await session.close()`` 归还连接池，并在 ``finally`` 中执行，确保任何异常路径
   下都不会泄漏。

这样无需改动几十处调用方的缩进，即可根治连接泄漏。已经用 ``async with`` 正确管理的
session 重复 close 是幂等的，不会产生副作用。

注意：主系统库（``app.db.database.Database``）通过 ``async with db.session()`` /
``async with get_session()`` 自管理连接，永不泄漏，因此不参与本注册表。
"""
from contextvars import ContextVar
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

# 当前请求生命周期内登记的所有裸 session（每个请求一个独立列表）
_request_sessions: ContextVar[List[AsyncSession]] = ContextVar("mdcx_request_sessions")


def register_session(session: AsyncSession) -> None:
    """登记一个 session，使其在请求结束时被自动关闭。

    同一 session 不会重复登记。
    """
    try:
        registry = _request_sessions.get()
    except LookupError:
        registry = []
        _request_sessions.set(registry)
    if session not in registry:
        registry.append(session)


async def close_registered_sessions() -> None:
    """关闭并清空当前请求登记的所有 session（幂等、异常安全）。"""
    try:
        registry = _request_sessions.get()
    except LookupError:
        return
    for session in registry:
        try:
            await session.close()
        except Exception:
            # 已关闭或底层连接已失效，忽略
            pass
    registry.clear()


async def session_cleanup_middleware(request, call_next):
    """请求级 session 回收中间件。

    每个 HTTP 请求开始时重置登记列表，在响应送出后（finally 中）统一关闭所有
    登记的裸 session，根治连接池泄漏。
    """
    token = _request_sessions.set([])
    try:
        response = await call_next(request)
    finally:
        await close_registered_sessions()
        _request_sessions.reset(token)
    return response
