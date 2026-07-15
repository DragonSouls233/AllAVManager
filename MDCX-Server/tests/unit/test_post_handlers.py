"""
post_handlers.py 单元测试

测试后处理 handler 链（标签映射/翻译/去重）。
"""

import pytest
from app.crawlers.base import ScrapeResult
from app.scraper.post_handlers import (
    TagNormalizerHandler,
    TagTranslatorHandler,
    GenreDedupHandler,
    PostHandlerChain,
)


@pytest.fixture
def sample_result():
    return ScrapeResult(
        code="ABC-123",
        title="テストタイトル",
        source="javdb",
        genres=[
            "中文字幕", "高清", "无码", "流出",
            "巨乳", "美乳", "女教师", "制服",
            "bondage", "HD", "独占",
        ],
    )


class TestGenreDedupHandler:
    """标签去重 handler 测试"""

    async def test_dedup_basic(self, sample_result):
        handler = GenreDedupHandler()
        result = await handler.process(sample_result)
        # 简单检查去重后数量 <= 原始数量
        assert len(result.genres) <= len(sample_result.genres)

    async def test_dedup_case_insensitive(self):
        handler = GenreDedupHandler()
        result = ScrapeResult(
            code="TEST-001", title="test", source="test",
            genres=["高清", "高清", "HD", "hd"],
        )
        result = await handler.process(result)
        # 大小写不敏感去重："HD" 和 "hd" 被视为重复项
        assert result.genres == ["高清", "HD"]


class TestTagNormalizerHandler:
    """标签归一化 handler 测试"""

    async def test_normalize_synonyms(self, sample_result):
        handler = TagNormalizerHandler()
        result = await handler.process(sample_result)
        # "中文字幕" 同义词组合并
        assert "中文字幕" in result.genres
        # "HD" 被合并到 "高清"
        assert "HD" not in result.genres
        assert "高清" in result.genres

    async def test_normalize_uncensored(self):
        handler = TagNormalizerHandler()
        result = ScrapeResult(
            code="TEST-001", title="test", source="test",
            genres=["无码", "无修正", "流出"],
        )
        result = await handler.process(result)
        # "��修正" 被合并到 "无码"
        assert "无码" in result.genres
        assert "无修正" not in result.genres
        # "流出" 保留
        assert "流出" in result.genres


class TestTagTranslatorHandler:
    """标签翻译 handler 测试"""

    async def test_translate_japanese(self):
        handler = TagTranslatorHandler()
        result = ScrapeResult(
            code="TEST-001", title="test", source="test",
            genres=["巨乳", "女教師", "コスプレ", "中出し"],
        )
        result = await handler.process(result)
        assert "巨乳" in result.genres
        assert "女教师" in result.genres
        assert "角色扮演" in result.genres
        assert "内射" in result.genres

    async def test_keep_unknown(self):
        handler = TagTranslatorHandler()
        result = ScrapeResult(
            code="TEST-001", title="test", source="test",
            genres=["unknown_tag_xxx", "test123"],
        )
        result = await handler.process(result)
        assert "unknown_tag_xxx" in result.genres
        assert "test123" in result.genres


class TestPostHandlerChain:
    """handler 链测试"""

    async def test_default_chain_works(self, sample_result):
        chain = PostHandlerChain.default_chain()
        result = await chain.process(sample_result)
        assert result is not None
        assert len(result.genres) > 0
        # 默认链应该去重 + 归一化 + 翻译 + 再次去重
        # "HD" 被归一化为 "高清"
        assert "HD" not in result.genres

    async def test_empty_genres(self):
        chain = PostHandlerChain.default_chain()
        result = ScrapeResult(
            code="TEST-001", title="test", source="test",
            genres=[],
        )
        result = await chain.process(result)
        assert result.genres == []

    async def test_add_handler(self):
        handler = GenreDedupHandler()
        chain = PostHandlerChain([handler])
        assert len(chain.handlers) == 1
        chain.add_handler(TagNormalizerHandler())
        assert len(chain.handlers) == 2
