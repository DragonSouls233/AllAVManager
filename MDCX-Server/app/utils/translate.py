"""
翻译引擎集成

支持：
- OpenAI API
- Google Translate
- DeepL
- 自定义翻译服务
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TranslateEngine(str, Enum):
    """翻译引擎"""
    OPENAI = "openai"
    GOOGLE = "google"
    DEEPL = "deepl"
    BAIDU = "baidu"
    BING = "bing"
    CLAUDE = "claude"
    CUSTOM = "custom"


@dataclass
class TranslateConfig:
    """翻译配置"""
    engine: TranslateEngine = TranslateEngine.OPENAI
    api_key: Optional[str] = None
    api_base: Optional[str] = None  # 自定义 API 端点
    source_lang: str = "ja"
    target_lang: str = "zh"
    # 模型名(OpenAI/Claude 使用);None 表示由各 Translator 用自己的默认模型
    model: Optional[str] = None
    timeout: int = 30


class BaseTranslator(ABC):
    """翻译器基类"""
    
    @abstractmethod
    async def translate(self, text: str) -> Optional[str]:
        """翻译文本"""
        pass
    
    @abstractmethod
    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译"""
        pass


class OpenAITranslator(BaseTranslator):
    """OpenAI 翻译器"""
    
    def __init__(self, config: TranslateConfig):
        self.config = config
        self.api_key = config.api_key
        self.api_base = config.api_base or "https://api.openai.com/v1"
        # OpenAI 默认模型 gpt-4o-mini
        self.model = config.model or "gpt-4o-mini"
        self.timeout = config.timeout
    
    async def translate(self, text: str) -> Optional[str]:
        """翻译文本"""
        if not text or not self.api_key:
            return None
        
        import httpx
        
        prompt = f"""Translate the following text from {self.config.source_lang} to {self.config.target_lang}.
Only output the translation result, no explanations.

Text: {text}"""
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "You are a professional translator."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                data = response.json()
                
                return data["choices"][0]["message"]["content"].strip()
        
        except Exception as e:
            logger.error(f"OpenAI translate error: {e}")
            return None
    
    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译"""
        results = []
        for text in texts:
            result = await self.translate(text)
            results.append(result)
        return results


class GoogleTranslator(BaseTranslator):
    """Google 翻译器（使用 googletrans 库）"""
    
    def __init__(self, config: TranslateConfig):
        self.config = config
        self.source_lang = config.source_lang
        self.target_lang = config.target_lang
    
    async def translate(self, text: str) -> Optional[str]:
        """翻译文本"""
        if not text:
            return None
        
        try:
            # 使用 googletrans 库
            from googletrans import Translator
            
            translator = Translator()
            result = await translator.translate(
                text,
                src=self.source_lang,
                dest=self.target_lang,
            )
            
            return result.text
        
        except ImportError:
            logger.warning("googletrans not installed, falling back to httpx")
            return await self._translate_httpx(text)
        
        except Exception as e:
            logger.error(f"Google translate error: {e}")
            return None
    
    async def _translate_httpx(self, text: str) -> Optional[str]:
        """使用 httpx 直接调用 Google Translate API"""
        import httpx
        import urllib.parse
        
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": self.source_lang,
            "tl": self.target_lang,
            "dt": "t",
            "q": text,
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                # 解析结果
                result = ""
                for part in data[0]:
                    if part[0]:
                        result += part[0]
                
                return result
        
        except Exception as e:
            logger.error(f"Google translate httpx error: {e}")
            return None
    
    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译"""
        results = []
        for text in texts:
            result = await self.translate(text)
            results.append(result)
        return results


class DeepLTranslator(BaseTranslator):
    """DeepL 翻译器"""
    
    def __init__(self, config: TranslateConfig):
        self.config = config
        self.api_key = config.api_key
        self.api_base = config.api_base or "https://api-free.deepl.com/v2"
    
    async def translate(self, text: str) -> Optional[str]:
        """翻译文本"""
        if not text or not self.api_key:
            return None
        
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.api_base}/translate",
                    headers={
                        "Authorization": f"DeepL-Auth-Key {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": [text],
                        "source_lang": self.config.source_lang.upper(),
                        "target_lang": self.config.target_lang.upper(),
                    },
                )
                response.raise_for_status()
                data = response.json()
                
                return data["translations"][0]["text"]
        
        except Exception as e:
            logger.error(f"DeepL translate error: {e}")
            return None
    
    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """批量翻译"""
        if not texts or not self.api_key:
            return [None] * len(texts)
        
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.api_base}/translate",
                    headers={
                        "Authorization": f"DeepL-Auth-Key {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": texts,
                        "source_lang": self.config.source_lang.upper(),
                        "target_lang": self.config.target_lang.upper(),
                    },
                )
                response.raise_for_status()
                data = response.json()
                
                return [t["text"] for t in data["translations"]]
        
        except Exception as e:
            logger.error(f"DeepL batch translate error: {e}")
            return [None] * len(texts)


class TranslateService:
    """
    翻译服务
    
    统一接口，支持多种翻译引擎
    """
    
    def __init__(self, config: TranslateConfig):
        """
        初始化
        
        Args:
            config: 翻译配置
        """
        self.config = config
        self.translator = self._create_translator()
    
    def _create_translator(self) -> BaseTranslator:
        """创建翻译器"""
        if self.config.engine == TranslateEngine.OPENAI:
            return OpenAITranslator(self.config)
        elif self.config.engine == TranslateEngine.GOOGLE:
            return GoogleTranslator(self.config)
        elif self.config.engine == TranslateEngine.DEEPL:
            return DeepLTranslator(self.config)
        elif self.config.engine == TranslateEngine.BAIDU:
            from app.utils.translate_extra import BaiduTranslator
            return BaiduTranslator(self.config)
        elif self.config.engine == TranslateEngine.BING:
            from app.utils.translate_extra import BingTranslator
            return BingTranslator(self.config)
        elif self.config.engine == TranslateEngine.CLAUDE:
            from app.utils.translate_extra import ClaudeTranslator
            return ClaudeTranslator(self.config)
        else:
            raise ValueError(f"Unsupported translate engine: {self.config.engine}")
    
    async def translate(self, text: str) -> Optional[str]:
        """
        翻译文本
        
        Args:
            text: 原文
            
        Returns:
            译文
        """
        return await self.translator.translate(text)
    
    async def translate_title(self, title: str) -> Optional[str]:
        """
        翻译标题
        
        Args:
            title: 标题
            
        Returns:
            翻译后的标题
        """
        return await self.translate(title)
    
    async def translate_plot(self, plot: str) -> Optional[str]:
        """
        翻译简介
        
        Args:
            plot: 简介
            
        Returns:
            翻译后的简介
        """
        return await self.translate(plot)
    
    async def translate_actor_name(self, name: str) -> Optional[str]:
        """
        翻译演员名
        
        Args:
            name: 演员名
            
        Returns:
            翻译后的演员名
        """
        return await self.translate(name)
    
    async def translate_batch(self, texts: list[str]) -> list[Optional[str]]:
        """
        批量翻译
        
        Args:
            texts: 文本列表
            
        Returns:
            翻译结果列表
        """
        return await self.translator.translate_batch(texts)


async def translate_text(
    text: str,
    engine: TranslateEngine = TranslateEngine.GOOGLE,
    source_lang: str = "ja",
    target_lang: str = "zh",
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    翻译文本的便捷函数
    
    Args:
        text: 原文
        engine: 翻译引擎
        source_lang: 源语言
        target_lang: 目标语言
        api_key: API Key（某些引擎需要）
        
    Returns:
        译文
    """
    config = TranslateConfig(
        engine=engine,
        api_key=api_key,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    
    service = TranslateService(config)
    return await service.translate(text)
