"""
订阅链接抓取与刷新

- 支持 base64 编码的 v2rayN/Clash-style 订阅
- 用 curl_cffi (chrome136) 抓取，避免 CDN 拦截
- APScheduler 每 6h 自动刷新（如果已配置订阅）
"""

from __future__ import annotations

import logging
from typing import Any

from curl_cffi import AsyncSession

from app.services.proxy_manager import ProxyManager, get_proxy_manager
from app.services.proxy_parser import NodeConfig, parse_subscription_content

logger = logging.getLogger(__name__)


async def fetch_subscription(url: str, timeout: int = 30) -> list[NodeConfig]:
    """
    抓取订阅 URL 并解析为 NodeConfig 列表。

    大部分订阅返回 base64 编码文本，parse_subscription_content 会自动尝试解码。
    """
    async with AsyncSession(impersonate="chrome136", timeout=timeout) as sess:
        # 订阅本身可能是海外资源，若 xray 已运行走 xray；否则直连
        mgr = get_proxy_manager()
        proxy_url = mgr.get_current_socks5_url()
        if proxy_url:
            sess.proxies = {"all": proxy_url}  # type: ignore[attr-defined]

        resp = await sess.get(url, headers={"User-Agent": "MDCX-Sub/1.0"})
        resp.raise_for_status()
        content = resp.text

    nodes = parse_subscription_content(content)
    logger.info("subscription %s -> %d nodes", url[:60], len(nodes))
    return nodes


async def refresh_subscription(*, restart_xray: bool = True) -> dict[str, Any]:
    """
    刷新订阅：抓取 → 替换节点池 → 可选重启 xray。

    返回:
      {"ok": bool, "count": N, "error": str | None}
    """
    mgr: ProxyManager = get_proxy_manager()
    state = mgr.get_state()
    url = state.get("subscription_url")
    if not url:
        return {"ok": False, "count": 0, "error": "no subscription configured"}

    try:
        nodes = await fetch_subscription(url)
    except Exception as e:
        logger.exception("fetch subscription failed")
        return {"ok": False, "count": 0, "error": str(e)}

    if not nodes:
        return {"ok": False, "count": 0, "error": "subscription returned zero nodes"}

    mgr.replace_all_nodes(nodes)

    if restart_xray and state.get("running"):
        try:
            await mgr.restart()
        except Exception as e:
            logger.exception("restart xray after subscription refresh failed")
            return {"ok": False, "count": len(nodes), "error": f"restart failed: {e}"}

    return {"ok": True, "count": len(nodes), "error": None}
