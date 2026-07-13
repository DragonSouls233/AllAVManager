"""LLM 刮削引擎

参考 mdcx (llm.py) 的设计实现 LLM 驱动的元数据提取：
- 对传统爬虫无法匹配的视频（尤其是国产模块无番号内容）使用 LLM 刮削
- OpenAI 兼容 API（支持 Ollama/Gemini/DeepSeek 等本地或云端模型）
- 双 Prompt 模板系统（system + user）
- 引用计数管理 + AsyncLimiter 限速
- 指数退避重试策略
"""

import asyncio
import contextlib
import json
import re
import threading
from collections.abc import Callable
from typing import Optional

from aiolimiter import AsyncLimiter
from httpx import AsyncClient, Timeout, Limits
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """你是AV元数据提取专家，从文件名或文件夹名中提取以下信息（JSON格式输出）：
{
  "title": "视频标题（清理后的完整标题）",
  "actors": ["演员名列表"],
  "studio": "制作商/工作室（如麻豆传媒、天美传媒）",
  "series": "系列名",
  "code": "番号（如果有，如 MD-0269）",
  "release_date": "发行日期（YYYY-MM-DD格式，未知则为空）",
  "genres": ["标签列表"],
  "is_uncensored": false,
  "is_chinese": true,
  "description": "简要描述"
}

要求：
1. 仅返回 JSON，不要包含其他文字
2. 不确定的字段设为 null 或空字符串
3. 演员名用中文全名
4. 番号格式保持原始大小写"""


class LLMScraper:
    """LLM 刮削引擎"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: int = 60,
        max_retry: int = 3,
        rate_per_second: float = 10.0,
        temperature: float = 0.3,
    ):
        cfg = get_config().llm_scraper if hasattr(get_config(), "llm_scraper") else None

        self.api_key = api_key or (cfg.api_key if cfg else "") or ""
        self.base_url = base_url or (cfg.base_url if cfg else "") or "https://api.openai.com/v1"
        self.model = model or (cfg.model if cfg else "") or "gpt-4o-mini"
        self.proxy = proxy or (cfg.proxy if cfg else None)
        self.timeout_sec = timeout or (cfg.timeout if cfg else 60)
        self.max_retry = max_retry or (cfg.max_retry if cfg else 3)
        self.temperature = temperature or (cfg.temperature if cfg else 0.3)
        rate = (cfg.rate_per_second if cfg else rate_per_second) or rate_per_second

        self._client: Optional[AsyncOpenAI] = None
        self._closed = False
        self._close_requested = False
        self._active_requests = 0
        self._active_lock = asyncio.Lock()
        self._lease_lock = threading.Lock()
        self._leases = 0

        self.limiter = AsyncLimiter(rate, 1)

    # ============ 生命周期管理 ============

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=AsyncClient(
                    proxy=self.proxy,
                    verify=False,
                    timeout=Timeout(self.timeout_sec),
                    follow_redirects=True,
                    limits=Limits(max_keepalive_connections=5, max_connections=10),
                ),
                timeout=self.timeout_sec,
            )
        return self._client

    def retain(self) -> None:
        with self._lease_lock:
            if self._closed:
                raise RuntimeError("LLMScraper 已关闭")
            self._leases += 1

    async def release(self) -> None:
        with self._lease_lock:
            if self._leases > 0:
                self._leases -= 1
        if self._close_requested:
            await self._close_if_idle()

    def _lease_count(self) -> int:
        with self._lease_lock:
            return self._leases

    async def _begin_request(self) -> None:
        async with self._active_lock:
            if self._closed:
                raise RuntimeError("LLMScraper 已关闭")
            self._active_requests += 1

    async def _end_request(self) -> None:
        async with self._active_lock:
            self._active_requests = max(self._active_requests - 1, 0)

    async def _is_idle(self) -> bool:
        async with self._active_lock:
            return self._active_requests == 0 and self._lease_count() == 0

    async def _close_if_idle(self) -> bool:
        if not await self._is_idle():
            return False
        await self.close()
        return True

    async def close_when_idle(self, poll_interval: float = 0.2) -> None:
        self._close_requested = True
        while not await self._is_idle():
            await asyncio.sleep(poll_interval)
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._close_requested = True
        self._closed = True
        with contextlib.suppress(Exception):
            if self._client:
                await self._client.close()

    # ============ 核心刮削方法 ============

    async def scrape(
        self,
        filename: str,
        filepath: Optional[str] = None,
        folder_name: Optional[str] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> Optional[dict]:
        """使用 LLM 从文件名/文件路径提取元数据

        Args:
            filename: 文件名（不含路径）
            filepath: 完整文件路径（可选，提供更多上下文）
            folder_name: 文件夹名（可选，提供更多上下文）
            log_fn: 日志回调函数

        Returns:
            解析后的元数据字典，失败返回 None
        """
        if not self.api_key:
            logger.warning("LLMScraper: API Key 未配置，跳过 LLM 刮削")
            return None

        if not self.model:
            self.model = "gpt-4o-mini"

        log = log_fn or (lambda msg: logger.debug(msg))

        # 构建 user prompt
        user_prompt = f"从以下视频文件名提取AV元数据:\n文件名: {filename}"
        if filepath:
            user_prompt += f"\n文件路径: {filepath}"
        if folder_name:
            user_prompt += f"\n文件夹名: {folder_name}"

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        wait = 1
        await self._begin_request()
        try:
            async with self.limiter:
                last_error = None
                for attempt in range(self.max_retry):
                    try:
                        chat = await self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=self.temperature,
                            response_format={"type": "json_object"},
                        )
                        text = chat.choices[0].message.content
                        if text:
                            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
                        return self._parse_response(text)

                    except Exception as e:
                        last_error = e
                        err_msg = f"LLM API 请求失败 (尝试 {attempt + 1}/{self.max_retry}): {e}"
                        log(err_msg)
                        if attempt < self.max_retry - 1:
                            await asyncio.sleep(wait)
                            wait *= 2

                log(f"LLM API 请求失败，已达最大重试次数")
                logger.error(f"LLM 刮削失败 ({filename}): {last_error}")
                return None

        finally:
            await self._end_request()

    async def batch_scrape(
        self,
        items: list[dict],
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> list[Optional[dict]]:
        """批量刮削

        Args:
            items: 每项包含 filename, 可选的 filepath, folder_name
            log_fn: 日志回调

        Returns:
            结果列表（顺序与输入一致）
        """
        results = []
        for item in items:
            result = await self.scrape(
                filename=item.get("filename", ""),
                filepath=item.get("filepath"),
                folder_name=item.get("folder_name"),
                log_fn=log_fn,
            )
            results.append(result)
        return results

    def _parse_response(self, text: Optional[str]) -> Optional[dict]:
        """解析 LLM 返回的 JSON"""
        if not text:
            return None

        text = text.strip()
        # 尝试提取 JSON 块
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

        try:
            data = json.loads(text)
            # 清理和规范化
            if "title" in data and isinstance(data["title"], str):
                data["title"] = data["title"].strip()
            if "actors" in data and isinstance(data["actors"], list):
                data["actors"] = [a.strip() for a in data["actors"] if a and a.strip()]
            if "genres" in data and isinstance(data["genres"], list):
                data["genres"] = [g.strip() for g in data["genres"] if g and g.strip()]
            if "code" in data and isinstance(data["code"], str):
                data["code"] = data["code"].strip().upper()
            return data

        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"LLM 响应解析失败: {e}\n原始响应: {text[:200]}")
            return None

    def build_prompt(self, filename: str, folder_name: Optional[str] = None) -> str:
        """构建 user prompt（供外部使用）"""
        prompt = f"从以下文件名提取AV元数据:\n{filename}"
        if folder_name:
            prompt += f"\n视频所在文件夹名: {folder_name}"
        return prompt


# 全局单例
_llm_scraper_instance: Optional[LLMScraper] = None
_llm_scraper_lock = threading.Lock()


def get_llm_scraper() -> LLMScraper:
    """获取全局 LLMScraper 单例"""
    global _llm_scraper_instance
    if _llm_scraper_instance is None:
        with _llm_scraper_lock:
            if _llm_scraper_instance is None:
                _llm_scraper_instance = LLMScraper()
    return _llm_scraper_instance


async def close_llm_scraper() -> None:
    """关闭全局 LLMScraper"""
    global _llm_scraper_instance
    if _llm_scraper_instance:
        await _llm_scraper_instance.close()
        _llm_scraper_instance = None


async def llm_scrape(
    filename: str,
    filepath: Optional[str] = None,
    folder_name: Optional[str] = None,
) -> Optional[dict]:
    """便捷函数：使用 LLM 刮削"""
    scraper = get_llm_scraper()
    return await scraper.scrape(filename, filepath, folder_name)


__all__ = [
    "LLMScraper",
    "get_llm_scraper",
    "close_llm_scraper",
    "llm_scrape",
]
