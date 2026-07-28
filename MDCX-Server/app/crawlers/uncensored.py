"""
无码内容爬虫模块

包含以下站点的爬虫：
- Caribbeancom (加勒比)
- Heyzo (柚月)
- S1 NO.1 STYLE
- 10musume (一本道)
- Caribbeancompr (加勒比 Premium)
- Ragdoll
- UncensoredAggregate (无码聚合，自动站点路由)
- HeyzoEnhanced (HEYZO 专用)
- OnePondoCrawler (1PONDO 专用)
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
from app.crawlers.uncensored_aggregate import (
    UncensoredAggregateCrawler,
    HeyzoEnhancedCrawler,
    OnePondoCrawler,
)

__all__ = [
    "CaribbeancomCrawler",
    "HeyzoCrawler",
    "S1StyleCrawler",
    "TenMusumeCrawler",
    "CaribbeancomprCrawler",
    "RagdollCrawler",
    "UncensoredAggregateCrawler",
    "HeyzoEnhancedCrawler",
    "OnePondoCrawler",
]
