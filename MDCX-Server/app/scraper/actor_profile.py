"""
演员资料刮削器模块

支持多个来源：
- DMM Actress (DMM.co.jp/idol)
- JavWiki
- AV Open
- AVWikiDB
- TheMovieDB
- Wikidata / Wikipedia（v3.0 新增，权威资料）
"""

from app.scraper.actor_profile_scrapers import (
    ActorProfileScraper,
    DMMActressScraper,
    JavWikiScraper,
    AVOpenScraper,
    AVWikiDBSraper,
    TheMovieDBScraper,
    GfriendsScraper,
    get_actor_profile_scraper,
)
from app.scraper.wikipedia_scraper import WikidataScraper, WikipediaScraper

__all__ = [
    "ActorProfileScraper",
    "DMMActressScraper",
    "JavWikiScraper",
    "AVOpenScraper",
    "AVWikiDBSraper",
    "TheMovieDBScraper",
    "GfriendsScraper",
    "WikidataScraper",
    "WikipediaScraper",
    "get_actor_profile_scraper",
]
