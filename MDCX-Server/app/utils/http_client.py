"""
HTTP 客户端工具类
基于 curl_cffi 实现，支持浏览器指纹模拟

v3.1 增强：
- 集成 browser_fingerprint 指纹池（6 个预定义指纹）
- 按 host + 用途选择指纹（document/api/asset/download）
- 同一 host 在会话内复用同一指纹（减少漂移）
- Amazon.co.jp 自动切换日语 Accept-Language
- 本地地址与 CF bypass URL 跳过指纹注入
"""

import asyncio
import logging
import random
import time
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import AsyncSession
from curl_cffi.requests import Response

from app.config.manager import get_config
from app.utils.browser_fingerprint import (
    BrowserFingerprint,
    RequestPurpose,
    build_fingerprint_headers,
    infer_request_purpose,
    merge_headers,
    select_fingerprint,
    should_apply_fingerprint,
)

logger = logging.getLogger(__name__)

# 会话级默认指纹（最现代的 Chrome 136 Windows）
# 每个请求可通过 impersonate 参数覆盖
_SESSION_DEFAULT_IMPERSONATE = "chrome136"

# 兼容旧代码：保留 BROWSER_IMPERSONATES 列表
BROWSER_IMPERSONATES = [
    "chrome120", "chrome123", "chrome124", "chrome131", "chrome136",
    "firefox133", "firefox135",
    "edge99", "edge101",
    "safari15_3", "safari15_5", "safari17_0", "safari18_0",
]


class AsyncHttpClient:
    """
    异步 HTTP 客户端
    
    基于 curl_cffi 实现，支持：
    - 浏览器指纹模拟（绕过 Cloudflare）
    - 自动重试
    - 请求限流
    - 代理支持
    """
    
    def __init__(
        self,
        proxy: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        rate_limit: float = 20.0,  # 请求/秒
    ):
        # 如果没有传入代理，则从配置中读取
        if proxy is None:
            # 统一走项目唯一定义源：优先内置 xray 实际端口，回退旧版 config.proxy
            from app.services.proxy_manager import get_effective_proxy_url
            proxy = get_effective_proxy_url()

        self.proxy = proxy
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limit = rate_limit

        self._session: Optional[AsyncSession] = None
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()
        # 域名级速率限制（来自 Hazard804 MDCX）
        self._domain_limiters: dict[str, float] = {}
        self._domain_lock = asyncio.Lock()
        # 上一次使用的指纹 ID（用于排除连续重复）
        self._last_fingerprint_id: str = ""

    async def __aenter__(self) -> "AsyncHttpClient":
        """上下文管理器入口"""
        await self.init_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器退出"""
        await self.close_session()

    async def init_session(self) -> None:
        """初始化会话（使用 Chrome 136 作为默认 TLS 指纹）"""
        if self._session is None:
            self._session = AsyncSession(
                max_clients=200,
                verify=False,
                max_redirects=20,
                timeout=self.timeout,
                impersonate=_SESSION_DEFAULT_IMPERSONATE,
                proxy=self.proxy,
            )

    def _select_fingerprint_for_request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[dict] = None,
        json_data: object = None,
        stream: bool = False,
        purpose: Optional[RequestPurpose] = None,
    ) -> Optional[BrowserFingerprint]:
        """为单次请求选择浏览器指纹。

        Returns:
            BrowserFingerprint 实例，若应跳过指纹注入则返回 None
        """
        if not should_apply_fingerprint(url):
            return None

        # 推断用途（若调用方未指定）
        if purpose is None:
            purpose = infer_request_purpose(
                url,
                method=method,
                headers=headers,
                stream=stream,
                json_data=json_data,
            )

        host = ""
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            pass

        fp = select_fingerprint(
            host,
            purpose=purpose,
            exclude_fingerprint_id=self._last_fingerprint_id,
        )
        self._last_fingerprint_id = fp.fingerprint_id
        return fp

    def _build_request_headers(
        self,
        url: str,
        fingerprint: Optional[BrowserFingerprint],
        explicit_headers: Optional[dict],
        purpose: RequestPurpose = "document",
    ) -> dict:
        """合并指纹 headers 与显式 headers（显式优先）"""
        if fingerprint is None:
            # 跳过指纹注入，使用最小默认 headers
            fp_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            }
        else:
            fp_headers = build_fingerprint_headers(url, fingerprint=fingerprint, purpose=purpose)
        return merge_headers(fp_headers, None, explicit_headers)
    
    async def close_session(self) -> None:
        """关闭会话"""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def _wait_for_rate_limit(self, url: str = "") -> None:
        """等待以遵守速率限制（支持全局和域名级）"""
        if self.rate_limit <= 0:
            return

        # 全局速率限制
        async with self._lock:
            now = time.monotonic()
            interval = 1.0 / self.rate_limit
            wait_time = interval - (now - self._last_request_time)

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self._last_request_time = time.monotonic()

        # 域名级速率限制（每个域名独立限流，来自 Hazard804 MDCX）
        if url:
            domain = urlparse(url).hostname or ""
            if domain:
                async with self._domain_lock:
                    last = self._domain_limiters.get(domain, 0.0)
                    now = time.monotonic()
                    domain_interval = 1.0 / 20.0  # 每个域名 20 req/s
                    wait = domain_interval - (now - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._domain_limiters[domain] = time.monotonic()
    
    async def get(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> Response:
        """
        GET 请求

        Args:
            url: 请求URL
            headers: 请求头（与指纹 headers 合并，显式优先）
            cookies: Cookies
            purpose: 请求用途（document/api/asset/download），None 则自动推断
            **kwargs: 其他参数

        Returns:
            Response 响应对象

        Raises:
            Exception: 当响应状态码为 4xx 或 5xx 时抛出异常
        """
        await self.init_session()
        await self._wait_for_rate_limit(url)

        # 选择指纹并构建 headers
        fingerprint = self._select_fingerprint_for_request(
            url, method="GET", headers=headers, purpose=purpose
        )
        req_purpose: RequestPurpose = purpose or (
            fingerprint and infer_request_purpose(url, method="GET", headers=headers) or "document"
        )
        req_headers = self._build_request_headers(url, fingerprint, headers, req_purpose)

        # 重试逻辑
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                # 传入 per-request impersonate 覆盖会话默认值
                request_kwargs = dict(kwargs)
                if fingerprint is not None and "impersonate" not in request_kwargs:
                    request_kwargs["impersonate"] = fingerprint.impersonate

                response = await self._session.get(  # type: ignore
                    url,
                    headers=req_headers,
                    cookies=cookies,
                    **request_kwargs,
                )
                # 检查响应状态码
                if response.status_code and 400 <= response.status_code < 600:
                    raise Exception(f"HTTP {response.status_code}")
                return response

            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))

        raise last_error or Exception(f"Failed to fetch {url}")
    
    async def get_text(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        encoding: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        GET 请求并返回文本
        
        Args:
            url: 请求URL
            headers: 请求头
            cookies: Cookies
            encoding: 编码（默认自动检测）
            **kwargs: 其他参数
            
        Returns:
            响应文本
        """
        response = await self.get(url, headers, cookies, **kwargs)
        
        if encoding:
            return response.content.decode(encoding)
        
        return response.text

    async def get_bytes(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        **kwargs,
    ) -> bytes:
        """
        GET 请求并返回原始字节

        Args:
            url: 请求URL
            headers: 请求头
            cookies: Cookies
            **kwargs: 其他参数

        Returns:
            响应字节
        """
        response = await self.get(url, headers, cookies, **kwargs)
        return response.content

    async def get_json(
        self,
        url: str,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """
        GET 请求并返回 JSON

        Returns:
            响应 JSON 字典
        """
        response = await self.get(url, headers, cookies, **kwargs)
        try:
            return response.json()
        except Exception:
            import json as _json
            return _json.loads(response.text)

    async def post(
        self,
        url: str,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        purpose: Optional[RequestPurpose] = None,
        **kwargs,
    ) -> Response:
        """
        POST 请求

        Args:
            url: 请求URL
            data: 表单数据
            json: JSON数据
            headers: 请求头（与指纹 headers 合并，显式优先）
            cookies: Cookies
            purpose: 请求用途，默认推断为 api（POST 多为 API 调用）
            **kwargs: 其他参数

        Returns:
            Response 响应对象
        """
        await self.init_session()
        await self._wait_for_rate_limit(url)

        # 选择指纹并构建 headers（POST 默认推断为 api 用途）
        inferred_purpose: RequestPurpose = purpose or "api"
        fingerprint = self._select_fingerprint_for_request(
            url, method="POST", headers=headers, json_data=json, purpose=inferred_purpose
        )
        req_headers = self._build_request_headers(url, fingerprint, headers, inferred_purpose)

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                request_kwargs = dict(kwargs)
                if fingerprint is not None and "impersonate" not in request_kwargs:
                    request_kwargs["impersonate"] = fingerprint.impersonate

                response = await self._session.post(  # type: ignore
                    url,
                    data=data,
                    json=json,
                    headers=req_headers,
                    cookies=cookies,
                    **request_kwargs,
                )
                return response

            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))

        raise last_error or Exception(f"Failed to post {url}")

    # ============================================
    # HTML 解析辅助方法(移植自 JavSP web/base.py)
    # 集中处理编码检测与链接绝对化,减少爬虫重复代码
    # ============================================

    @staticmethod
    def resp_to_text(response: Response, encoding: Optional[str] = None) -> str:
        """从 Response 提取文本,支持 apparent_encoding 回退

        移植自 JavSP get_resp_text

        curl_cffi 的 response.text 在日文/中文站点可能编码错误,
        此方法提供 apparent_encoding 自动检测作为兜底。

        Args:
            response: curl_cffi Response 对象
            encoding: 强制指定编码(优先级最高)

        Returns:
            解码后的文本
        """
        if encoding:
            try:
                return response.content.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                pass

        # 优先用 response 自带的 encoding
        if response.encoding:
            try:
                return response.content.decode(response.encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                pass

        # 兜底:apparent_encoding 自动检测
        try:
            from charset_normalizer import from_bytes
            result = from_bytes(response.content).best()
            if result:
                return str(result)
        except ImportError:
            pass

        # 最终兜底:UTF-8 + replace
        return response.content.decode("utf-8", errors="replace")

    @staticmethod
    def resp_to_html(
        response: Response,
        encoding: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """Response → lxml HTML 文档,链接绝对化

        移植自 JavSP resp2html

        Args:
            response: curl_cffi Response 对象
            encoding: 强制指定编码
            base_url: 基础 URL(默认用 response.url)

        Returns:
            lxml.html.HtmlElement
        """
        from lxml import html as lxml_html

        text = AsyncHttpClient.resp_to_text(response, encoding)
        if not text:
            from lxml.html import HtmlElement
            return lxml_html.fromstring("<html></html>")

        # 解析为 HTML 文档
        doc = lxml_html.fromstring(text)

        # 链接绝对化(用 response.url 或显式 base_url)
        if base_url:
            url = base_url
        elif response.url:
            url = str(response.url)
        else:
            url = None
        if url:
            try:
                doc.make_links_absolute(url, resolve_base_href=True)
            except Exception:
                pass

        return doc

    async def get_html(
        self,
        url: str,
        encoding: Optional[str] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        **kwargs,
    ):
        """GET 请求并返回 lxml HTML 文档

        移植自 JavSP get_html

        集中处理编码检测与链接绝对化,减少爬虫重复代码。

        Args:
            url: 请求 URL
            encoding: 强制指定编码(如 'utf-8', 'shift_jis')
            headers: 请求头
            cookies: Cookies
            **kwargs: 其他参数

        Returns:
            lxml.html.HtmlElement
        """
        response = await self.get(url, headers, cookies, **kwargs)
        return AsyncHttpClient.resp_to_html(response, encoding, base_url=url)


# 全局客户端实例（懒加载）
_client: Optional[AsyncHttpClient] = None


async def get_http_client() -> AsyncHttpClient:
    """获取全局 HTTP 客户端实例"""
    global _client

    if _client is None:
        config = get_config()
        # 统一走项目唯一定义源：优先内置 xray 实际端口，回退旧版 config.proxy
        from app.services.proxy_manager import get_effective_proxy_url
        proxy = get_effective_proxy_url()
        _client = AsyncHttpClient(
            proxy=proxy,
            timeout=config.scraper.timeout,
            max_retries=config.scraper.retry_count,
        )
        await _client.init_session()
    
    return _client


async def close_http_client() -> None:
    """关闭全局 HTTP 客户端"""
    global _client
    
    if _client:
        await _client.close_session()
        _client = None
