"""
无码内容爬虫模块

包含以下站点的爬虫：
- Caribbeancom (加勒比)
- Heyzo (柚月)
- S1 NO.1 STYLE
- 10musume (一本道)
- Caribbeancompr (加勒比 Premium)
- Ragdoll
"""

# 导入爬虫以触发 @register_crawler 装饰器
from app.crawlers.uncensored_detail import (
    CaribbeancomCrawler,
    HeyzoCrawler,
    S1StyleCrawler,
    TenMusumeCrawler,
    CaribbeancomprCrawler,
    RagdollCrawler,
)

__all__ = [
    "CaribbeancomCrawler",
    "HeyzoCrawler",
    "S1StyleCrawler",
    "TenMusumeCrawler",
    "CaribbeancomprCrawler",
    "RagdollCrawler",
]
