"""
MDCX 爬虫兼容层

提供 MDCX 爬虫所需的运行时环境模拟，使得 MDCX 的爬虫代码
可以直接在 docker-scraper 项目中运行，无需逐行修改。

模拟的关键组件：
- manager: 配置管理器
- manager.computed.async_client: 异步 HTTP 客户端
- LogBuffer: 日志缓冲区
- signal: 信号/事件系统
"""

import logging
import time
from typing import Any, Optional

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


class MockLogBuffer:
    """模拟 MDCX 的 LogBuffer"""

    @staticmethod
    def req():
        return MockLogBuffer()

    @staticmethod
    def info():
        return MockLogBuffer()

    @staticmethod
    def error():
        return MockLogBuffer()

    def write(self, message: str):
        logger.debug(message.strip())


LogBuffer = MockLogBuffer()


class MockSignal:
    """模拟 MDCX 的 signal"""

    @staticmethod
    def add_log(message: str):
        logger.info(message)


signal = MockSignal()


def _looks_like_html(text: str) -> bool:
    """粗略判断响应体是否为 HTML（反爬/人机验证页通常是 HTML）。"""
    if not text:
        return False
    head = text.lstrip()[:256].lower()
    return (
        head.startswith("<!doctype html")
        or head.startswith("<html")
        or "<html" in head
        or "<head" in head
        or "cloudflare" in head
    )


class CompatAsyncClient:
    """
    兼容 MDCX 的异步 HTTP 客户端
    
    MDCX 爬虫使用 manager.computed.async_client.get_text(url, use_proxy=True)
    返回 (text, error) 元组格式，这里做适配。
    """

    def __init__(self):
        self._client: Optional[AsyncHttpClient] = None

    async def _get_client(self) -> AsyncHttpClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None:
            self._client = AsyncHttpClient()
            await self._client.init_session()
        return self._client

    async def get_text(self, url: str, use_proxy: bool = True, **kwargs) -> tuple[Optional[str], Optional[str]]:
        """
        GET 请求并返回文本
        
        Args:
            url: 请求 URL
            use_proxy: 是否使用代理（兼容参数，实际由全局配置决定）
            
        Returns:
            (text, error) 元组，成功时 error 为 None
        """
        try:
            client = await self._get_client()
            text = await client.get_text(url, **kwargs)
            return text, None
        except Exception as e:
            return None, str(e)

    async def get(self, url: str, use_proxy: bool = True, **kwargs):
        """GET 请求并返回 Response 对象"""
        try:
            client = await self._get_client()
            return await client.get(url, **kwargs), None
        except Exception as e:
            return None, str(e)

    async def get_json(self, url: str, use_proxy: bool = True, **kwargs) -> tuple:
        """
        GET 请求并返回 JSON 解析结果。
        原 MDCX 返回 (json_obj, error) 元组。

        健壮性增强（2026-08-10）：
        通过 client.get() 显式取得 Response 并检查 HTTP 状态码，避免把
        4xx/5xx 错误页、代理黑洞返回体、或 Cloudflare/反爬 HTML 挑战页
        误当成 "JSON 解析失败" 而静默吞掉。任何失败都通过 error 字段带回
        真实根因（状态码 / 异常 / 非 JSON 内容摘要），让调用方（如 prestige
        爬虫）能正确暴露问题，而非误报 "响应非合法 JSON"。
        """
        import json as _json

        try:
            client = await self._get_client()
            resp = await client.get(url, **kwargs)
        except Exception as e:
            return None, f"请求异常: {e}"

        # 统一检查 HTTP 状态码：
        # curl_cffi 路径遇 4xx/5xx 会抛异常（已由上方 except 捕获）；
        # httpx 降级路径不抛异常，此处兜底，避免把错误页当 JSON 解析。
        status = getattr(resp, "status_code", None)
        if status is not None and status >= 400:
            return None, f"HTTP {status}"

        # 用统一编码兜底提取文本（抗日文/中文乱码），比直接 resp.text 更稳。
        try:
            text = AsyncHttpClient.resp_to_text(resp)
        except Exception:
            try:
                text = resp.text
            except Exception:
                text = ""
        if not text:
            return None, "empty response"

        try:
            return _json.loads(text), None
        except Exception:
            snippet = text[:200].replace("\r", " ").replace("\n", " ")
            if _looks_like_html(text):
                return None, f"响应为HTML而非JSON(疑似反爬/人机验证页): {snippet}"
            return None, f"响应非合法JSON: {snippet}"

    async def post_json(self, url: str, data=None, json=None, use_proxy: bool = True, **kwargs) -> tuple:
        """POST 请求并返回 JSON 解析结果。返回 (json_obj, error)。"""
        import json as _json
        try:
            client = await self._get_client()
            resp = await client.post(url, data=data, json=json, **kwargs)
            text = resp.text if hasattr(resp, 'text') else str(resp)
            try:
                return _json.loads(text), None
            except Exception:
                return text, None
        except Exception as e:
            return None, str(e)

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.close_session()
            self._client = None


class MockComputed:
    """模拟 MDCX 的 manager.computed"""

    def __init__(self):
        self._async_client: Optional[CompatAsyncClient] = None

    @property
    def async_client(self) -> CompatAsyncClient:
        """获取兼容的异步 HTTP 客户端"""
        if self._async_client is None:
            self._async_client = CompatAsyncClient()
        return self._async_client


class MockConfig:
    """模拟 MDCX 的 manager.config"""

    def __init__(self):
        self.computed = MockComputed()
        self.config = _MockInnerConfig()

    @staticmethod
    def get_site_url(site, default_url: str = "") -> str:
        """获取站点 URL"""
        return default_url

    @staticmethod
    def get_site_config(site):
        """获取站点配置"""
        return MockSiteConfig()


class _MockInnerConfig:
    """
    模拟 MDCX manager.config 内嵌配置对象。
    原 MDCX 代码用 `manager.config.xxx` 访问全局配置,如 theporndb_api_token / switch_on 等。
    这里返回安全默认值,避免 AttributeError。
    """

    theporndb_api_token = ""
    switch_on = []

    def __getattr__(self, name):
        # 对未定义字段返回空字符串,让业务代码不至于炸
        return ""


class MockSiteConfig:
    """模拟站点配置"""
    custom_url = ""


# 全局 manager 实例
manager = MockConfig()


async def get_async_client() -> CompatAsyncClient:
    """获取异步 HTTP 客户端"""
    return manager.computed.async_client


# ===== guochan 工具函数转发 =====
# 这些函数由 guochan.py 提供，被 cableav/cnmdb/javday/hscangku/mdtv/madouqu/mmtv 使用
# 通过 compat 导入，保持与迁移脚本生成的导入路径一致

from app.crawlers.md.guochan import (  # noqa: F401, E402
    get_actor_list,
    get_extra_info,
    get_lable_list,
    get_number_list,
    remove_escape_string,
)
