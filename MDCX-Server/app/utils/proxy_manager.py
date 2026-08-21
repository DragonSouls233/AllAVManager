"""
Compatibility shim: app.utils.proxy_manager -> app.services.proxy_manager

历史遗留模块可能仍通过 app.utils.proxy_manager 路径导入。
统一通过 app.services.proxy_manager 暴露，保证向后兼容，零逻辑差异。
"""

from app.services.proxy_manager import (
    ProxyManager,
    get_effective_proxy_url,
    get_proxy_manager,
)

__all__ = [
    "ProxyManager",
    "get_effective_proxy_url",
    "get_proxy_manager",
]
