"""
API 认证中间件 - ASGI 版本

保护所有 API 端点，除登录和健康检查外都需要认证。
使用 ASGI 中间件而非 BaseHTTPMiddleware，解决与 app.mount() 的兼容问题。

支持可信 IP 自动放行：配置 auth.enable_trusted_ip 后，白名单内的 IP 无需 token。
"""

import ipaddress
import logging

from fastapi.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED

from app.api.routes.auth import decode_access_token
from app.config.manager import get_config

logger = logging.getLogger(__name__)


# 不需要认证的路径前缀
PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/check",
    "/api/v1/auth/trusted-ip",
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/health/live",
    "/api/v1/health/metrics",
    "/metrics",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/api/debug/paths",
}


def _get_client_ip(scope) -> str | None:
    """从 ASGI scope 中提取客户端真实 IP（处理反向代理 X-Forwarded-For）"""
    # 优先用 X-Forwarded-For（反向代理场景）
    headers = scope.get("headers", [])
    for item in headers:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            if item[0] == b"x-forwarded-for":
                # 取第一个（最原始的客户端）
                val = item[1].decode("utf-8", "ignore")
                return val.split(",")[0].strip()

    # 回退到连接信息
    client = scope.get("client")
    if client and len(client) >= 1:
        return client[0]
    return None


def _is_ip_trusted(client_ip: str, trusted_ips: list) -> bool:
    """检查 IP 是否在可信列表中（支持单 IP 和 CIDR 段）"""
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for entry in trusted_ips:
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if ip in network:
                    return True
            else:
                if ip == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            # 无效的 IP/CIDR 配置项，跳过
            continue
    return False


class AuthMiddleware:
    """认证中间件 - ASGI 版本"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 公开路径放行
        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        # API 文档路径放行
        if path.startswith("/api/docs") or path.startswith("/api/redoc") or path.startswith("/api/openapi"):
            await self.app(scope, receive, send)
            return

        # 非 API 路径放行（静态文件、首页等）
        if not path.startswith("/api/"):
            # /emby 路径走 Emby 协议自身的 API Key 认证
            if path.startswith("/emby/"):
                await self._check_emby_auth(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        # 图片文件端点放行（浏览器 <img> 标签无法携带 Bearer token）
        if path.startswith("/api/v1/actors/") and path.endswith("/avatar/file"):
            await self.app(scope, receive, send)
            return
        if path.startswith("/api/v1/movies/") and (path.endswith("/cover/file") or path.endswith("/poster/file") or path.endswith("/thumb/file")):
            await self.app(scope, receive, send)
            return
        # 视频流端点放行（浏览器 <video> 标签无法携带 Bearer token）
        if path.startswith("/api/v1/movies/") and path.endswith("/play/file"):
            await self.app(scope, receive, send)
            return
        # HLS 流媒体端点放行（hls.js 无法携带 Bearer token）
        if path.startswith("/api/v1/movies/") and "/hls/" in path:
            await self.app(scope, receive, send)
            return
        # 播放器静态资源放行（精灵图、GIF、章节缩略图、字幕）
        # /api/v1/player/{movie_id}/thumbnail-sprite/{filename}
        # /api/v1/player/{movie_id}/gifs/{filename}
        # /api/v1/player/{movie_id}/chapters/thumbnails/{filename}
        if path.startswith("/api/v1/player/"):
            # 仅放行静态资源，metadata 端点仍需认证
            if any(seg in path for seg in (
                "/thumbnail-sprite/sprite.jpg",
                "/thumbnail-sprite/sprite.vtt",
                "/gifs/",
                "/chapters/thumbnails/",
                "/subtitles/file",
            )):
                await self.app(scope, receive, send)
                return

        # ===== 可信 IP 自动放行 =====
        # 注意：仅对「配置读取 + IP 判定」做容错，下游 self.app 调用必须放在 try 之外，
        # 否则下游异常会被吞掉且响应永不发送，导致客户端挂起（HTTP 000）。
        trusted = False
        try:
            cfg = get_config()
            if cfg.auth.enable_trusted_ip and cfg.auth.trusted_ips:
                client_ip = _get_client_ip(scope)
                if client_ip and _is_ip_trusted(client_ip, cfg.auth.trusted_ips):
                    trusted = True
        except Exception as e:
            logger.warning(f"AuthMiddleware: 可信IP检查失败: {e}")

        if trusted:
            logger.debug(f"AuthMiddleware: 可信 IP 放行 {_get_client_ip(scope)}")
            await self.app(scope, receive, send)
            return

        # API 请求检查认证
        headers = scope.get("headers", [])
        auth_header = b""
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                key, value = item[0], item[1]
                if key == b"authorization":
                    auth_header = value
                    break

        auth_str = auth_header.decode() if auth_header else ""
        if not auth_str.startswith("Bearer "):
            response = JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "未登录，请先登录"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        token = auth_str[7:]
        payload = decode_access_token(token)
        if payload is None:
            response = JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Token 无效或已过期，请重新登录"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _check_emby_auth(self, scope, receive, send):
        """Emby 协议自身的 API Key 认证

        - 公共路径（System/Info/Public, Users/Public, web/*）无需认证
        - 其他路径需 X-Emby-Token header 或 api_key query 参数匹配
        """
        path = scope.get("path", "")

        # Emby 协议公共路径放行
        EMBY_PUBLIC_PATHS = {
            "/emby/System/Info/Public",
            "/emby/Users/Public",
            "/emby/System/Info",
            "/emby/web/System/Info/Public",
        }
        if path in EMBY_PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        # web 路径放行（Emby Web UI 资源）
        if path.startswith("/emby/web/"):
            await self.app(scope, receive, send)
            return

        # 提取 Emby Token（X-Emby-Token header 或 api_key query 参数）
        try:
            cfg = get_config()
            emby_cfg = cfg.emby_compat
            if not emby_cfg.enabled:
                response = JSONResponse(
                    status_code=503,
                    content={"detail": "Emby 协议兼容未启用"},
                )
                await response(scope, receive, send)
                return

            # 提取 query 参数中的 api_key
            query_string = scope.get("query_string", b"").decode("utf-8", "ignore")
            api_key = None
            for pair in query_string.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k in ("api_key", "Api_key", "X-Emby-Token"):
                        api_key = v
                        break

            # 提取 X-Emby-Token header
            if not api_key:
                headers = scope.get("headers", [])
                for item in headers:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        if item[0] == b"x-emby-token":
                            api_key = item[1].decode("utf-8", "ignore")
                            break

            # 如果未配置 api_key，则放行（让路由自己处理）
            if not emby_cfg.api_key:
                await self.app(scope, receive, send)
                return

            # 校验 api_key
            if api_key == emby_cfg.api_key:
                await self.app(scope, receive, send)
                return

            response = JSONResponse(
                status_code=401,
                content={"detail": "Emby API Key 无效"},
            )
            await response(scope, receive, send)

        except Exception as e:
            logger.warning(f"Emby 认证失败: {e}")
            response = JSONResponse(
                status_code=500,
                content={"detail": f"认证异常: {e}"},
            )
            await response(scope, receive, send)
