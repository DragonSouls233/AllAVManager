"""
扩展翻译引擎 - 移植自 JavSP translate.py

包含 3 个 JavSP 实现但 MDCX-Server 缺失的引擎:
- Baidu Translator (百度翻译,API 签名 + QPS 限流)
- Bing Translator (微软 Bing 翻译,含女优名保护词典)
- Claude Translator (Anthropic Claude API)

移植来源: javsp/web/translate.py

原始实现差异(已修复):
- 原版用同步 requests + time.sleep,本版改为异步 httpx + asyncio.sleep
- 原版目标语言代码不统一(zh_CN/zh-Hans/zh),本版统一映射为各引擎原生代码
"""

import asyncio
import logging
import random
import time
import uuid
from hashlib import md5
from typing import Optional

import httpx

from app.utils.translate import BaseTranslator, TranslateConfig

logger = logging.getLogger(__name__)


# ============================================
# 目标语言代码映射
# ============================================

# 各引擎对目标语言代码的不同要求
_TARGET_LANG_MAP = {
    # MDCX 通用代码 → 各引擎原生代码
    "zh": {
        "baidu": "zh",
        "bing": "zh-Hans",
        "claude": "zh_CN",
        "google": "zh_CN",
    },
    "zh-CN": {
        "baidu": "zh",
        "bing": "zh-Hans",
        "claude": "zh_CN",
    },
    "zh-TW": {
        "baidu": "cht",
        "bing": "zh-Hant",
        "claude": "zh_TW",
    },
    "en": {
        "baidu": "en",
        "bing": "en",
        "claude": "en",
    },
    "ja": {
        "baidu": "jp",
        "bing": "ja",
        "claude": "ja",
    },
}


def _get_target_lang(target_lang: str, engine: str) -> str:
    """获取引擎原生的目标语言代码

    Args:
        target_lang: MDCX 通用语言代码 (zh/zh-CN/zh-TW/en/ja)
        engine: 引擎名 (baidu/bing/claude)

    Returns:
        引擎原生的语言代码
    """
    mapping = _TARGET_LANG_MAP.get(target_lang)
    if mapping is None:
        # 兜底:zh-CN 兜底
        mapping = _TARGET_LANG_MAP["zh"]
    return mapping.get(engine, target_lang)


# ============================================
# 百度翻译
# ============================================


class BaiduTranslator(BaseTranslator):
    """百度翻译器

    移植自 JavSP baidu_translate

    特点:
    - API 签名验证 (MD5)
    - QPS 限制: 标准版 1QPS, 需要请求间至少 1 秒间隔
    - 免费配额: 标准版 5万字符/月

    配置:
    - api_key 格式: "app_id|api_key" (用 | 分隔)
      百度要求同时提供 app_id 和 api_key,这里合并存储
    """

    # 百度标准版 QPS=1,需要记录上次访问时间
    _last_access_time: float = -1.0
    _qps_lock = asyncio.Lock()

    def __init__(self, config: TranslateConfig):
        self.config = config
        # 解析 api_key "app_id|api_key"
        if not config.api_key or "|" not in config.api_key:
            logger.warning(
                "Baidu api_key 应为 'app_id|api_key' 格式,当前: %s",
                "***" if config.api_key else "None",
            )
            self.app_id = ""
            self.api_key = ""
        else:
            parts = config.api_key.split("|", 1)
            self.app_id = parts[0]
            self.api_key = parts[1]
        self.target_lang = _get_target_lang(config.target_lang, "baidu")
        self.timeout = config.timeout

    async def translate(self, text: str) -> Optional[str]:
        """翻译文本

        Args:
            text: 原文

        Returns:
            译文,失败返回 None
        """
        if not text or not self.app_id or not self.api_key:
            return None

        api_url = "https://api.fanyi.baidu.com/api/trans/vip/translate"
        salt = str(random.randint(0, 0x7FFFFFFF))
        sign_input = self.app_id + text + salt + self.api_key
        sign = md5(sign_input.encode("utf-8")).hexdigest()
        payload = {
            "appid": self.app_id,
            "q": text,
            "from": "auto",
            "to": self.target_lang,
            "salt": salt,
            "sign": sign,
        }

        # QPS 限流:确保请求间隔至少 1.0 秒
        async with self._qps_lock:
            now = time.perf_counter()
            wait = 1.0 - (now - self._last_access_time)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_access_time = time.perf_counter()

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        api_url,
                        data=payload,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response.raise_for_status()
                    result = response.json()

                    if "error_code" in result:
                        logger.error(
                            "Baidu translate error: %s: %s",
                            result.get("error_code"),
                            result.get("error_msg"),
                        )
                        return None

                    # 拼接多个段落的译文
                    paragraphs = [item["dst"] for item in result.get("trans_result", [])]
                    return "\n".join(paragraphs) if paragraphs else None

            except Exception as e:
                logger.error(f"Baidu translate error: {e}")
                return None

    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译

        百度标准版 QPS=1,逐条串行调用
        """
        results = []
        for text in texts:
            result = await self.translate(text)
            results.append(result)
        return results


# ============================================
# Bing 翻译
# ============================================


class BingTranslator(BaseTranslator):
    """Bing 翻译器 (微软 Azure Cognitive Services)

    移植自 JavSP bing_translate

    特点:
    - 使用 Azure Translator API v3.0
    - 支持 includeSentenceLength 自动断句
    - 女优名保护词典(防止翻译后认不出来)

    配置:
    - api_key: Azure Translator 的 Ocp-Apim-Subscription-Key
    - api_base: 可选,默认 https://api.cognitive.microsofttranslator.com
    """

    def __init__(self, config: TranslateConfig):
        self.config = config
        self.api_key = config.api_key
        self.api_base = (
            config.api_base
            or "https://api.cognitive.microsofttranslator.com"
        )
        self.target_lang = _get_target_lang(config.target_lang, "bing")
        self.timeout = config.timeout
        # 女优名保护词典(可在 translate 时动态注入)
        self.protected_names: list[str] = []

    def set_protected_names(self, names: list[str]) -> None:
        """设置女优名保护词典

        Bing 翻译 API 支持通过 <mstrans:dictionary> 标签保护专有名词,
        防止翻译后女优名认不出来。

        Args:
            names: 女优名列表
        """
        self.protected_names = [n for n in names if n]

    def _wrap_protected_names(self, text: str) -> str:
        """用 mstrans:dictionary 标签包裹女优名"""
        for name in self.protected_names:
            if name and name in text:
                text = text.replace(
                    name,
                    f'<mstrans:dictionary translation="{name}">{name}</mstrans:dictionary>',
                )
        return text

    async def translate(self, text: str) -> Optional[str]:
        """翻译文本

        Args:
            text: 原文

        Returns:
            译文,失败返回 None
        """
        if not text or not self.api_key:
            return None

        # 包裹女优名
        wrapped_text = self._wrap_protected_names(text)

        url = f"{self.api_base}/translate"
        params = {
            "api-version": "3.0",
            "to": self.target_lang,
            "includeSentenceLength": "true",
        }
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Ocp-Apim-Subscription-Region": "global",
            "Content-type": "application/json",
            "X-ClientTraceId": str(uuid.uuid4()),
        }
        body = [{"text": wrapped_text}]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url, params=params, headers=headers, json=body
                )
                response.raise_for_status()
                result = response.json()

                if isinstance(result, list) and result:
                    translation = result[0].get("translations", [])
                    if translation:
                        # Bing 会在译文每个句尾加空格,去掉
                        return translation[0].get("text", "").rstrip(" ")

                if isinstance(result, dict) and "error" in result:
                    err = result["error"]
                    logger.error(
                        "Bing translate error: %s: %s",
                        err.get("code"),
                        err.get("message"),
                    )
                return None

        except Exception as e:
            logger.error(f"Bing translate error: {e}")
            return None

    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译

        Bing API 支持一次请求多条文本(最多 100 条),这里实现真批量
        """
        if not texts or not self.api_key:
            return [None] * len(texts)

        # 包裹女优名
        wrapped = [self._wrap_protected_names(t) for t in texts]
        url = f"{self.api_base}/translate"
        params = {
            "api-version": "3.0",
            "to": self.target_lang,
            "includeSentenceLength": "true",
        }
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Ocp-Apim-Subscription-Region": "global",
            "Content-type": "application/json",
            "X-ClientTraceId": str(uuid.uuid4()),
        }
        body = [{"text": t} for t in wrapped]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url, params=params, headers=headers, json=body
                )
                response.raise_for_status()
                result = response.json()

                if isinstance(result, list):
                    return [
                        item.get("translations", [{}])[0].get("text", "").rstrip(" ")
                        if item.get("translations")
                        else None
                        for item in result
                    ]
                return [None] * len(texts)

        except Exception as e:
            logger.error(f"Bing batch translate error: {e}")
            return [None] * len(texts)


# ============================================
# Claude 翻译
# ============================================


class ClaudeTranslator(BaseTranslator):
    """Claude 翻译器 (Anthropic Claude API)

    移植自 JavSP claude_translate

    特点:
    - 使用 Anthropic Messages API
    - 默认模型: claude-3-haiku-20240307 (性价比最高)
    - 系统提示要求保留非日文文本
    - 仅翻译日文部分,保留人名/品牌/技术术语

    配置:
    - api_key: Anthropic API key
    - api_base: 可选,默认 https://api.anthropic.com
    - model: 模型名,默认 claude-3-haiku-20240307
    """

    # 默认模型
    DEFAULT_MODEL = "claude-3-haiku-20240307"

    # 系统提示(来自 JavSP)
    SYSTEM_PROMPT = (
        "Translate the following Japanese paragraph into {to}, "
        "while leaving non-Japanese text, names, or text that does not look "
        "like Japanese untranslated. Reply with the translated text only, "
        "do not add any text that is not in the original content."
    )

    def __init__(self, config: TranslateConfig):
        self.config = config
        self.api_key = config.api_key
        self.api_base = config.api_base or "https://api.anthropic.com"
        # 使用 config.model 或默认模型
        self.model = config.model or self.DEFAULT_MODEL
        self.target_lang = _get_target_lang(config.target_lang, "claude")
        self.timeout = config.timeout

    async def translate(self, text: str) -> Optional[str]:
        """翻译文本

        Args:
            text: 原文

        Returns:
            译文,失败返回 None
        """
        if not text or not self.api_key:
            return None

        url = f"{self.api_base}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        data = {
            "model": self.model,
            "system": self.SYSTEM_PROMPT.format(to=self.target_lang),
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": text}],
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=data)
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("content", [{}])
                    if content and isinstance(content, list):
                        return content[0].get("text", "").strip()
                    return None
                else:
                    try:
                        err_data = response.json()
                        err = err_data.get("error", {})
                        logger.error(
                            "Claude translate error: %s: %s",
                            response.status_code,
                            err.get("message", response.reason_phrase),
                        )
                    except Exception:
                        logger.error(
                            "Claude translate error: HTTP %s: %s",
                            response.status_code,
                            response.text[:200],
                        )
                    return None

        except Exception as e:
            logger.error(f"Claude translate error: {e}")
            return None

    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译

        Claude 没有原生批量 API,逐条串行调用
        """
        results = []
        for text in texts:
            result = await self.translate(text)
            results.append(result)
        return results


# ============================================
# 导出
# ============================================

__all__ = [
    "BaiduTranslator",
    "BingTranslator",
    "ClaudeTranslator",
    "_get_target_lang",
]
