"""
播放地址构建工具

监听地址为 0.0.0.0 时，旧的实现会生成 localhost 播放地址，
导致浏览器/局域网客户端在各自机器上请求 localhost 而连接失败。
这里优先使用请求的 Host 头（即用户实际访问服务器的入口地址）。
"""
from typing import Any


def build_play_base_url(request: Any = None, host: str = "0.0.0.0", port: int = 8420) -> str:
    """构建播放 base URL。

    优先级：
    1. 请求 Host 头（局域网/公网访问时为用户实际访问的地址）
    2. 配置的 host（非 0.0.0.0/127.0.0.1/localhost）
    3. localhost 兜底
    """
    if request is not None:
        headers = getattr(request, "headers", None)
        if headers is not None:
            host_header = headers.get("host")
            if host_header:
                return f"http://{host_header}"
    if host in ("0.0.0.0", "127.0.0.1", "localhost", ""):
        return f"http://localhost:{port}"
    return f"http://{host}:{port}"
