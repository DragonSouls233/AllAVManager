"""
后处理 handler 链（标签映射/翻译/AI 增强）

参考 yamdc 的 post_handlers 设计，提供链式处理功能：
1. 标签映射/归一化（同义标签合并）
2. 标签翻译（日本语 → 中文）
3. AI 标签增强（从标题/简介中提取额外标签）
4. 字段补全（缺失字段填充）

每个 handler 实现 Handler 接口，可通过配置链式调用。
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from app.crawlers.base import ScrapeResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PostHandler(ABC):
    """后处理 handler 基类"""

    @abstractmethod
    async def process(self, result: ScrapeResult) -> ScrapeResult:
        """处理刮削结果，返回处理后的结果"""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class TagNormalizerHandler(PostHandler):
    """标签归一化 handler

    合并同义标签：
      - 中文字幕 → 中文字幕/中文
      - 无码流出 → 无码/流出
      - 高清 → HD/高清
    """

    # 标签同义词映射
    TAG_SYNONYMS = {
        "中文字幕": {"中文字幕", "中文", "中字", "简体中文", "繁体中文", "中文化"},
        "无码": {"无码", "无码流出", "无修正", "无码高清"},
        "流出": {"流出", "泄露", "偷拍"},
        "高清": {"高清", "HD", "高画质"},
        "独家": {"独家", "首发", "原创"},
        "3D": {"3D", "立体", "三维"},
        "4K": {"4K", "超高清", "2160p"},
    }

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}

    async def process(self, result: ScrapeResult) -> ScrapeResult:
        if not result.genres:
            return result

        normalized = []
        seen = set()

        for genre in result.genres:
            g = genre.strip()
            if not g:
                continue
            # 检查是否匹配同义词组的某个词
            matched = False
            for canonical, synonyms in self.TAG_SYNONYMS.items():
                if g in synonyms:
                    if canonical not in seen:
                        normalized.append(canonical)
                        seen.add(canonical)
                    matched = True
                    break
            if not matched:
                if g not in seen:
                    normalized.append(g)
                    seen.add(g)

        result.genres = normalized
        return result


class TagTranslatorHandler(PostHandler):
    """标签翻译 handler

    将日语标签翻译为中文（基于内置词典）。
    目前支持的翻译映射有限，后续可对接外部翻译 API。
    """

    # 日语→中文标签映射（常用标签）
    JP_TO_CN = {
        "高清": "高清", "高画質": "高清", "ハイビジョン": "高清",
        "独占": "独家", "オリジナル": "原创",
        "中文字幕": "中文字幕",
        "巨乳": "巨乳", "爆乳": "巨乳",
        "美乳": "美乳", "美巨乳": "美乳",
        "美脚": "美腿", "美足": "美腿",
        "美尻": "美臀",
        "制服": "制服",
        "痴女": "痴女", "痴漢": "痴汉",
        "人妻": "人妻", "人妻不倫": "人妻",
        "熟女": "熟女", "熟女人妻": "熟女",
        "少女": "少女", "美少女": "少女",
        "萝莉": "萝莉", "ロリ": "萝莉",
        "SM": "SM", "緊縛": "绑缚", "縛り": "绑缚",
        "調教": "调教",
        "アナル": "肛交",
        "乱交": "乱交", "大乱交": "乱交",
        "ギャル": "辣妹", "ギャル系": "辣妹",
        "美少女戦士": "美少女战士",
        "コスプレ": "角色扮演",
        "ナース": "护士", "看護婦": "护士",
        "教師": "教师", "女教師": "女教师",
        "凌辱": "凌辱", "陵辱": "凌辱",
        "レイプ": "强奸", "強姦": "强奸",
        "近親相姦": "近亲相奸", "近親": "近亲",
        "中出し": "内射", "中出": "内射",
        "顔射": "颜射",
        "スレンダー": "苗条",
        "長身": "高挑",
        "ショート": "短发",
        "ポニーテール": "马尾辫",
        "ツインテール": "双马尾",
        "メガネ": "眼镜",
        "清楚": "清纯",
        "天然": "天然呆",
        "元気": "活泼",
        "強気": "强势",
        "気弱": "温柔", "弱気": "温柔",
    }

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}

    async def process(self, result: ScrapeResult) -> ScrapeResult:
        if not result.genres:
            return result

        translated = []
        for genre in result.genres:
            g = genre.strip()
            if g in self.JP_TO_CN:
                translated.append(self.JP_TO_CN[g])
            else:
                translated.append(g)

        result.genres = translated
        return result


class GenreDedupHandler(PostHandler):
    """标签去重 handler

    去除重复标签，并合并大小写不同的同类标签。
    """

    async def process(self, result: ScrapeResult) -> ScrapeResult:
        if not result.genres:
            return result

        seen = set()
        unique = []
        for genre in result.genres:
            # 统一大小写进行比较
            key = genre.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(genre.strip())

        result.genres = unique
        return result


class PostHandlerChain:
    """后处理 handler 链

    按顺序执行多个 handler，前一个 handler 的输出作为下一个的输入。
    """

    def __init__(self, handlers: list[PostHandler]):
        self.handlers = handlers

    async def process(self, result: ScrapeResult) -> ScrapeResult:
        """按顺序执行所有 handler"""
        for handler in self.handlers:
            try:
                result = await handler.process(result)
                logger.debug(f"Handler {handler.name} 处理完成")
            except Exception as e:
                logger.warning(f"Handler {handler.name} 处理失败: {e}", exc_info=True)
        return result

    def add_handler(self, handler: PostHandler) -> "PostHandlerChain":
        """追加 handler"""
        self.handlers.append(handler)
        return self

    @classmethod
    def default_chain(cls) -> "PostHandlerChain":
        """创建默认的 handler 链"""
        return cls([
            GenreDedupHandler(),
            TagNormalizerHandler(),
            TagTranslatorHandler(),
            GenreDedupHandler(),  # 翻译后再次去重
        ])
