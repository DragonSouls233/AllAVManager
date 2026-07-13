"""
网络连通性检测

功能：
- 检测站点可达性
- 检测代理连接
- 检测 DNS 解析
- 网络延迟测试
"""

import asyncio
import logging
import socket
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class NetworkStatus(str, Enum):
    """网络状态"""
    OK = "ok"
    SLOW = "slow"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class ConnectivityResult:
    """连通性检测结果"""
    url: str
    status: NetworkStatus
    response_time: float  # 毫秒
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status.value,
            "response_time": self.response_time,
            "status_code": self.status_code,
            "error_message": self.error_message,
        }


class NetworkChecker:
    """
    网络连通性检测器
    
    检测站点可达性和响应时间
    """
    
    # 常用站点列表
    COMMON_SITES = [
        ("JavBus", "https://www.javbus.com"),
        ("JavDB", "https://javdb.com"),
        ("Google", "https://www.google.com"),
        ("Cloudflare", "https://1.1.1.1"),
    ]
    
    def __init__(
        self,
        timeout: int = 10,
        slow_threshold: float = 3000,  # 3秒
        proxy: Optional[str] = None,
    ):
        """
        初始化
        
        Args:
            timeout: 超时时间（秒）
            slow_threshold: 慢速阈值（毫秒）
            proxy: 代理地址
        """
        self.timeout = timeout
        self.slow_threshold = slow_threshold
        self.proxy = proxy
    
    async def check_url(self, url: str) -> ConnectivityResult:
        """
        检测单个 URL
        
        Args:
            url: 目标 URL
            
        Returns:
            ConnectivityResult 检测结果
        """
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=self.proxy,
                follow_redirects=True,
            ) as client:
                response = await client.head(url)
                
                response_time = (time.time() - start_time) * 1000  # 毫秒
                
                if response.status_code < 400:
                    status = NetworkStatus.OK if response_time < self.slow_threshold else NetworkStatus.SLOW
                else:
                    status = NetworkStatus.ERROR
                
                return ConnectivityResult(
                    url=url,
                    status=status,
                    response_time=response_time,
                    status_code=response.status_code,
                )
        
        except httpx.TimeoutException:
            response_time = (time.time() - start_time) * 1000
            return ConnectivityResult(
                url=url,
                status=NetworkStatus.TIMEOUT,
                response_time=response_time,
                error_message="Timeout",
            )
        
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return ConnectivityResult(
                url=url,
                status=NetworkStatus.ERROR,
                response_time=response_time,
                error_message=str(e),
            )
    
    async def check_multiple(self, urls: list[str]) -> list[ConnectivityResult]:
        """
        并发检测多个 URL
        
        Args:
            urls: URL 列表
            
        Returns:
            检测结果列表
        """
        tasks = [self.check_url(url) for url in urls]
        return await asyncio.gather(*tasks)
    
    async def check_common_sites(self) -> dict[str, ConnectivityResult]:
        """
        检测常用站点
        
        Returns:
            站点名称 -> 检测结果
        """
        results = {}
        
        for name, url in self.COMMON_SITES:
            result = await self.check_url(url)
            results[name] = result
        
        return results
    
    async def check_dns(self, hostname: str) -> bool:
        """
        检测 DNS 解析
        
        Args:
            hostname: 主机名
            
        Returns:
            是否成功
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.getaddrinfo(hostname, None)
            return True
        except socket.gaierror:
            return False
    
    async def check_proxy(self, proxy_url: str) -> ConnectivityResult:
        """
        检测代理连接
        
        Args:
            proxy_url: 代理地址
            
        Returns:
            检测结果
        """
        # 使用代理访问测试站点
        test_url = "https://www.google.com"
        
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=proxy_url,
            ) as client:
                response = await client.get(test_url)
                
                response_time = (time.time() - start_time) * 1000
                
                return ConnectivityResult(
                    url=proxy_url,
                    status=NetworkStatus.OK,
                    response_time=response_time,
                    status_code=response.status_code,
                )
        
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return ConnectivityResult(
                url=proxy_url,
                status=NetworkStatus.ERROR,
                response_time=response_time,
                error_message=str(e),
            )


async def check_network_connectivity() -> dict:
    """
    检测网络连通性的便捷函数
    
    Returns:
        检测结果汇总
    """
    checker = NetworkChecker()
    
    # 检测常用站点
    sites_result = await checker.check_common_sites()
    
    # 统计结果
    ok_count = sum(1 for r in sites_result.values() if r.status == NetworkStatus.OK)
    slow_count = sum(1 for r in sites_result.values() if r.status == NetworkStatus.SLOW)
    error_count = sum(1 for r in sites_result.values() if r.status in [NetworkStatus.ERROR, NetworkStatus.TIMEOUT])
    
    # 整体状态
    if ok_count >= len(sites_result) // 2:
        overall_status = "ok"
    elif ok_count + slow_count >= len(sites_result) // 2:
        overall_status = "slow"
    else:
        overall_status = "error"
    
    return {
        "status": overall_status,
        "sites": {name: r.to_dict() for name, r in sites_result.items()},
        "summary": {
            "ok": ok_count,
            "slow": slow_count,
            "error": error_count,
        },
    }


async def check_site_available(url: str) -> bool:
    """
    检测站点是否可用
    
    Args:
        url: 站点 URL
        
    Returns:
        是否可用
    """
    checker = NetworkChecker()
    result = await checker.check_url(url)
    return result.status == NetworkStatus.OK
