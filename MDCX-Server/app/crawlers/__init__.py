"""
站点刮削器模块
"""

from app.crawlers.base import BaseCrawler, ScrapeResult
from app.crawlers.provider import (
    CrawlerProvider,
    register_crawler,
    get_crawler,
    get_crawlers_for_number,
    list_crawlers,
)

# 导入原始爬虫以触发注册（fc2/dmm在顶层，fc2ppvdb/fc2club在md/中已注册）
from app.crawlers import javbus, javdb, fc2, avsox, dmm, avmoo, javdatabase

# 导入 md 爬虫（包含 fc2ppvdb/fc2club 等，会自动注册）
from app.crawlers import md

# 导入 MDCX 迁移爬虫以触发注册
from app.crawlers.md import (
    airav, airav_cc, avbase, avsex, cableav, cnmdb, dahlia, dmm,
    faleno, fantastica, fc2club, fc2hub, fc2ppvdb, freejavbt, getchu,
    getchu_dl, giga, hdouban, hscangku, iqqtv, jav321, javday,
    javdb_new, javlibrary, kin8, love6, lulubar, madouqu, mdtv,
    mgstage, missav, mmtv, mywife, official, prestige, theporndb,
    theporndb_movies, xcity,
)

# 导入无码站点爬虫
from app.crawlers import uncensored, uncensored_detail

# 导入 FC2 扩展爬虫
from app.crawlers import fc2_extended, fc2_extended_detail

# 导入欧美刮削器（Vixen / NaughtyAmerica / AdultTime / AyloAPI）
from app.crawlers.western import vixen_network, naughtyamerica, adulttime, aylo_api, theporndb

# 导入国产模块增强爬虫
from app.crawlers import chinese

__all__ = [
    "BaseCrawler",
    "ScrapeResult",
    "CrawlerProvider",
    "register_crawler",
    "get_crawler",
    "get_crawlers_for_number",
    "list_crawlers",
    # 原始爬虫
    "javbus",
    "javdb",
    "fc2",
    "avsox",
    "dmm",
    "avmoo",
    "javdatabase",
    "fc2ppvdb",
    "fc2club",
    # MDCX 迁移爬虫
    "javlibrary",
    "mgstage",
    "jav321",
    "freejavbt",
    "avsex",
    "fantastica",
    "love6",
    "lulubar",
    "airav",
    "airav_cc",
    "iqqtv",
    "fc2club",
    "fc2hub",
    "fc2ppvdb",
    "faleno",
    "dahlia",
    "dmm",
    "prestige",
    "giga",
    "kin8",
    "mywife",
    "xcity",
    "getchu",
    "getchu_dl",
    "cnmdb",
    "cableav",
    "hdouban",
    "hscangku",
    "madouqu",
    "mdtv",
    "javday",
    "mmtv",
    "theporndb",
    "official",
    # 新式类爬虫
    "avbase",
    "javdb_new",
    "missav",
    "theporndb_movies",
]
