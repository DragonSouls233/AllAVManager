"""
节点测速

简化方案：TCP 连接测试节点 address:port 的握手延迟。
不是准确的代理链路延迟，但能快速识别死节点。

如果需要精确测速，用户可以直接切换节点后看 /network-diag/check。
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.services.proxy_manager import NodeConfig, get_proxy_manager

logger = logging.getLogger(__name__)


async def test_node_tcp(node: NodeConfig, timeout: float = 5.0) -> int | None:
    """
    TCP 三次握手延迟测试。
    返回毫秒；失败返回 None。
    """
    loop = asyncio.get_event_loop()
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(node.address, node.port),
            timeout=timeout,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return elapsed_ms
    except (asyncio.TimeoutError, OSError) as e:
        logger.debug("tcp test %s:%s failed: %s", node.address, node.port, e)
        return None


async def test_all_nodes(concurrency: int = 8) -> dict[str, int | None]:
    """
    并发测速全部节点，写回 latency_ms，持久化。
    返回 {node_id: latency_ms | None}
    """
    mgr = get_proxy_manager()
    nodes = mgr.list_nodes()
    if not nodes:
        return {}

    sem = asyncio.Semaphore(concurrency)
    results: dict[str, int | None] = {}

    async def _one(n: NodeConfig) -> None:
        async with sem:
            ms = await test_node_tcp(n)
            n.latency_ms = ms
            results[n.id] = ms

    await asyncio.gather(*(_one(n) for n in nodes))
    mgr.save_nodes()
    logger.info("node speed test done: %d nodes, %d alive",
                len(results), sum(1 for v in results.values() if v is not None))
    return results
