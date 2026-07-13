"""
FC2 系列爬虫模块

包含：
- FC2 Fanclub (会员内容)
- FC2 Video (非PPV内容)
- FC2 Search (搜索API)
"""

# 导入爬虫以触发 @register_crawler 装饰器
from app.crawlers.fc2_extended_detail import (
    FC2FanclubCrawler,
    FC2VideoCrawler,
    FC2SearchCrawler,
)

__all__ = [
    "FC2FanclubCrawler",
    "FC2VideoCrawler",
    "FC2SearchCrawler",
]
