"""
刮削引擎模块
"""

from app.scraper.number import (
    NumberType,
    NumberResult,
    extract_number,
    normalize_number,
    get_number_type,
    clean_filename,
    is_uncensored,
    is_suren,
    normalize_uncensored_digit_number,
)

# 延迟导入避免触发爬虫模块的完整导入链
# 这些模块在 __init__ 中仅用于方便 from app.scraper import xxx 的用���
def __getattr__(name):
    import importlib
    if name in ("ScraperEngine", "ScrapeStatus", "ScrapeTask", "ScrapeProgress", "get_scraper_engine"):
        module = importlib.import_module("app.scraper.engine")
        return getattr(module, name)
    if name in ("MergeConfig", "ResultMerger", "merge_results"):
        module = importlib.import_module("app.scraper.merger")
        return getattr(module, name)
    if name in ("ScraperWorkflow", "scrape_file"):
        module = importlib.import_module("app.scraper.workflow")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # 番号识别
    "NumberType",
    "NumberResult",
    "extract_number",
    "normalize_number",
    "get_number_type",
    "clean_filename",
    "is_uncensored",
    "is_suren",
    "normalize_uncensored_digit_number",
    # 刮削引擎
    "ScraperEngine",
    "ScrapeStatus",
    "ScrapeTask",
    "ScrapeProgress",
    "get_scraper_engine",
    # 结果合并
    "MergeConfig",
    "ResultMerger",
    "merge_results",
    # 完整流程
    "ScraperWorkflow",
    "scrape_file",
]
