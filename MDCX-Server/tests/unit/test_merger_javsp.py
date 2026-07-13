"""merger.py 多源合并单元测试 - 验证 JavSP 借鉴的 5 个新特性"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pytest

from app.crawlers.base import ActorInfo, ScrapeResult
from app.scraper.merger import (
    MergeConfig,
    ResultMerger,
    UseJavDBCover,
    merge_results,
)


def make_result(
    code: str = "SSIS-018",
    source: str = "javbus",
    title: str = "",
    cover_url: Optional[str] = None,
    poster_url: Optional[str] = None,
    actors: list = None,
    genres: list = None,
    is_chinese: Optional[bool] = None,
    is_mosaic: Optional[bool] = None,
    plot: str = "",
) -> ScrapeResult:
    """构造测试用 ScrapeResult"""
    return ScrapeResult(
        code=code,
        title=title or f"{code} 测试标题",
        source=source,
        cover_url=cover_url,
        poster_url=poster_url,
        actors=actors or [],
        genres=genres or [],
        is_chinese=is_chinese,
        is_mosaic=is_mosaic,
        plot=plot,
    )


@pytest.mark.unit
class TestAvidVote:
    """番号投票测试"""

    def test_single_source_keeps_original(self):
        """单源不纠正番号"""
        results = [make_result(code="SSIS-018", source="javbus")]
        merged = merge_results(results)
        assert merged.code == "SSIS-018"

    def test_majority_vote_corrects_filename(self):
        """多源投票纠正文件名错误(>=2 票)"""
        results = [
            make_result(code="SSIS-018", source="javbus"),  # 文件名提取的
            make_result(code="SSIS-019", source="javdb"),
            make_result(code="SSIS-019", source="dmm"),
            make_result(code="SSIS-019", source="avmoo"),
        ]
        merged = merge_results(results)
        # 3 票 SSIS-019 vs 1 票 SSIS-018 → 应该用 SSIS-019
        assert merged.code == "SSIS-019"
        # raw_data 应记录纠正信息
        assert "avid_vote" in merged.raw_data
        assert merged.raw_data["avid_vote"]["original"] == "SSIS-018"
        assert merged.raw_data["avid_vote"]["voted"] == "SSIS-019"

    def test_one_vote_no_correction(self):
        """单票不纠正(2 票才纠正)"""
        results = [
            make_result(code="SSIS-018", source="javbus"),
            make_result(code="SSIS-019", source="javdb"),  # 仅 1 票
        ]
        merged = merge_results(results)
        # 1 票不够,保持文件名 SSIS-018
        assert merged.code == "SSIS-018"
        assert "avid_vote" not in merged.raw_data

    def test_disable_respect_site_avid(self):
        """禁用番号投票"""
        config = MergeConfig(respect_site_avid=False)
        results = [
            make_result(code="SSIS-018", source="javbus"),
            make_result(code="SSIS-019", source="javdb"),
            make_result(code="SSIS-019", source="dmm"),
        ]
        merged = merge_results(results, config)
        assert merged.code == "SSIS-018"  # 禁用后保持 base


@pytest.mark.unit
class TestMultiCovers:
    """多封面列表测试"""

    def test_collects_unique_covers(self):
        """收集所有不重复封面"""
        results = [
            make_result(source="javbus", cover_url="https://javbus.com/cover.jpg"),
            make_result(source="javdb", cover_url="https://javdb.com/cover.jpg"),
            make_result(source="dmm", cover_url="https://javbus.com/cover.jpg"),  # 重复
            make_result(source="avmoo", cover_url="https://avmoo.com/cover.jpg"),
        ]
        merged = merge_results(results)
        covers = merged.raw_data.get("covers", [])
        # 去重后应该 3 个(javbus + javdb + avmoo)
        assert len(covers) == 3
        # javbus 优先级最高,应该在前
        assert "javbus" in covers[0]

    def test_javdb_fallback_strategy(self):
        """fallback: javdb 封面移到末尾"""
        results = [
            make_result(source="javbus", cover_url="https://javbus.com/c.jpg"),
            make_result(source="javdb", cover_url="https://javdb.com/c.jpg"),
        ]
        config = MergeConfig(use_javdb_cover=UseJavDBCover.FALLBACK)
        merged = merge_results(results, config)
        covers = merged.raw_data["covers"]
        # javdb 应该在末尾
        assert covers[0] == "https://javbus.com/c.jpg"
        assert covers[-1] == "https://javdb.com/c.jpg"

    def test_javdb_no_strategy(self):
        """no: javdb 封面完全移除"""
        results = [
            make_result(source="javbus", cover_url="https://javbus.com/c.jpg"),
            make_result(source="javdb", cover_url="https://javdb.com/c.jpg"),
        ]
        config = MergeConfig(use_javdb_cover=UseJavDBCover.NO)
        merged = merge_results(results, config)
        covers = merged.raw_data["covers"]
        assert "https://javdb.com/c.jpg" not in covers
        assert "https://javbus.com/c.jpg" in covers

    def test_javdb_yes_strategy(self):
        """yes: javdb 封面放最前"""
        results = [
            make_result(source="javbus", cover_url="https://javbus.com/c.jpg"),
            make_result(source="javdb", cover_url="https://javdb.com/c.jpg"),
        ]
        config = MergeConfig(use_javdb_cover=UseJavDBCover.YES)
        merged = merge_results(results, config)
        covers = merged.raw_data["covers"]
        assert covers[0] == "https://javdb.com/c.jpg"


@pytest.mark.unit
class TestActressAlias:
    """女优别名统一测试"""

    def test_resolve_alias_exact(self):
        """精确匹配别名"""
        alias_map = {"三上悠亚": "三上悠亞", "Yua Mikami": "三上悠亞"}
        config = MergeConfig(
            resolve_actress_alias=True,
            actress_alias_map=alias_map,
        )
        actors = [
            ActorInfo(name="三上悠亚", japanese_name="三上悠亞"),
            ActorInfo(name="波多野结衣"),
        ]
        results = [make_result(source="javbus", actors=actors)]
        merged = merge_results(results, config)
        assert merged.actors[0].name == "三上悠亞"
        assert merged.actors[1].name == "波多野结衣"

    def test_resolve_alias_case_insensitive(self):
        """大小写不敏感匹配"""
        alias_map = {"yua mikami": "三上悠亞"}
        config = MergeConfig(
            resolve_actress_alias=True,
            actress_alias_map=alias_map,
        )
        actors = [ActorInfo(name="Yua Mikami")]
        results = [make_result(source="javbus", actors=actors)]
        merged = merge_results(results, config)
        assert merged.actors[0].name == "三上悠亞"


@pytest.mark.unit
class TestAutoAddGenres:
    """自动检测并添加 genre 标签测试"""

    def test_add_chinese_subtitle_genre(self):
        """is_chinese=True → 加 "中文字幕" 标签"""
        results = [make_result(source="javdb", is_chinese=True, genres=["高清"])]
        merged = merge_results(results)
        assert "中文字幕" in merged.genres
        assert "高清" in merged.genres

    def test_add_uncensored_genre(self):
        """is_mosaic=False → 加 "无码" 标签"""
        results = [make_result(source="javdb", is_mosaic=False, genres=[])]
        merged = merge_results(results)
        assert "无码" in merged.genres

    def test_add_hardcoded_subtitle_genre(self):
        """标题包含 "内嵌字幕" → 加 "内嵌字幕" 标签"""
        results = [
            make_result(source="javdb", title="SSIS-018 [内嵌字幕] 测试", genres=[])
        ]
        merged = merge_results(results)
        assert "内嵌字幕" in merged.genres

    def test_no_duplicate_genre(self):
        """已有标签不重复添加"""
        results = [make_result(source="javdb", is_chinese=True, genres=["中文字幕"])]
        merged = merge_results(results)
        # "中文字幕" 只出现一次
        assert merged.genres.count("中文字幕") == 1


@pytest.mark.unit
class TestBackwardCompatibility:
    """向后兼容测试(确保新特性不影响旧调用方)"""

    def test_default_config_works(self):
        """默认配置下合并仍正常工作"""
        results = [
            make_result(source="javbus", title="JavBus 标题", cover_url="https://1.jpg"),
            make_result(source="javdb", title="JavDB 标题", cover_url="https://2.jpg"),
        ]
        merged = merge_results(results)
        # 字段优先级:javbus 优先级 10 < javdb 20,base=javbus
        assert merged.title == "JavBus 标题"
        # cover_url 仍为单 URL(向后兼容),取 covers[0]
        assert merged.cover_url == "https://1.jpg"
        # raw_data 中有 covers 列表(新特性)
        assert "covers" in merged.raw_data
        assert "merged_from" in merged.raw_data

    def test_disable_all_new_features(self):
        """禁用所有新特性后,行为应与改造前一致"""
        config = MergeConfig(
            collect_multi_covers=False,
            respect_site_avid=False,
            resolve_actress_alias=False,
            auto_add_genres=False,
        )
        results = [
            make_result(source="javbus", cover_url="https://1.jpg"),
            make_result(source="javdb", cover_url="https://2.jpg"),
        ]
        merged = merge_results(results, config)
        # 不收集多封面,cover_url 用 _merge_field
        assert merged.cover_url == "https://1.jpg"
        assert "covers" not in merged.raw_data
        assert "avid_vote" not in merged.raw_data
