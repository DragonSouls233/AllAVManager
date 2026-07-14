"""
内置站点域名工厂

从 site_registry.py 自动构建 DomainSwitcher 实例，
供爬虫和刮削器使用。

所有切换器均使用 MDCX 内置代理。
"""

from typing import Optional

from app.config.site_registry import (
    CHINESE_SITES,
    WESTERN_SITES,
    JAV_SITES,
    get_scrapable_sites,
    SiteCategory,
)
from app.services.domain_switcher import DomainSwitcher
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 缓存实例
_switchers: dict[str, DomainSwitcher] = {}


def _collect_urls(site_info: dict) -> list[str]:
    """收集站点 primary + fallbacks 为列表"""
    urls = [site_info["primary"]]
    urls.extend(site_info.get("fallbacks", []))
    return urls


def get_or_create_switcher(site_id: str) -> Optional[DomainSwitcher]:
    """获取或创建 DomainSwitcher 实例"""
    if site_id in _switchers:
        return _switchers[site_id]

    # 搜索三��站点仓库
    site_info = None
    for sites in [CHINESE_SITES, WESTERN_SITES, JAV_SITES]:
        if site_id in sites:
            site_info = sites[site_id]
            break

    if not site_info:
        logger.warning(f"未找到站点配置: {site_id}")
        return None

    urls = _collect_urls(site_info)
    switcher = DomainSwitcher(
        name=site_id,
        candidate_urls=urls,
    )
    _switchers[site_id] = switcher
    return switcher


def get_all_switchers() -> dict[str, DomainSwitcher]:
    """获取所有 DomainSwitcher 实例"""
    for category_sites in [CHINESE_SITES, WESTERN_SITES, JAV_SITES]:
        for site_id in category_sites:
            if site_id not in _switchers:
                urls = _collect_urls(category_sites[site_id])
                _switchers[site_id] = DomainSwitcher(
                    name=site_id,
                    candidate_urls=urls,
                )
    return _switchers


def get_switchers_by_category(category: SiteCategory) -> dict[str, DomainSwitcher]:
    """按分类获取 DomainSwitcher 实例"""
    sites = {
        SiteCategory.CHINESE: CHINESE_SITES,
        SiteCategory.WESTERN: WESTERN_SITES,
        SiteCategory.JAV: JAV_SITES,
    }.get(category, {})

    result = {}
    for site_id in sites:
        result[site_id] = get_or_create_switcher(site_id)
    return {k: v for k, v in result.items() if v is not None}


# ============================================================
# 向后兼容的便捷工厂（保持原 madouqu/haijiao/javdb 不变）
# ============================================================

def make_madouqu_switcher() -> DomainSwitcher:
    """麻豆专用切换器（5+ 个备用域名，含官方地址）"""
    return DomainSwitcher(
        name="madou",
        candidate_urls=[
            "https://lwabe.com",              # 官方最新国内访问地址
            "https://madou.com",
            "https://madou.club",
            "https://madouqu.sbs",
            "https://madouqu.club",
            "https://madouqu.cc",
            "https://madouqu.net",
            "https://madouqu.org",
        ],
    )


def make_haijiao_switcher() -> DomainSwitcher:
    """海角专用切换器"""
    return DomainSwitcher(
        name="haijiao",
        candidate_urls=[
            "https://haijiao.com",
            "https://www.haijiao.com",
        ],
    )


def make_javdb_switcher() -> DomainSwitcher:
    """JAVDB 专用切换器（10+ 个镜像）"""
    return DomainSwitcher(
        name="javdb",
        candidate_urls=[
            "https://javdb.com",
            "https://javdb36.com",
            "https://javdb37.com",
            "https://javdb38.com",
            "https://javdb40.com",
            "https://javdb5.com",
            "https://javdb30.com",
            "https://javdb33.com",
            "https://javdb.live",
            "https://javdb.org",
            "https://javdb368.com",
        ],
    )


def make_javbus_switcher() -> DomainSwitcher:
    """JavBus 专用切换器"""
    return DomainSwitcher(
        name="javbus",
        candidate_urls=[
            "https://www.javbus.com",
            "https://www.javbus.one",
            "https://www.javbus.org",
            "https://www.javbus.info",
        ],
    )


# 欧美品牌集团公司切换器
def make_aylo_switcher() -> DomainSwitcher:
    """Aylo 集团切换器（Brazzers / BangBros / RealityKings / Mofos / DigitalPlayground 等）"""
    sites = WESTERN_SITES
    urls = []
    aylo_brands = ["brazzers", "realitykings", "bangbros", "mofos", "digitalplayground", "twistys", "babes", "trueamateurs"]
    for brand in aylo_brands:
        if brand in sites:
            urls.extend(_collect_urls(sites[brand]))
    return DomainSwitcher(name="aylo_network", candidate_urls=urls)


def make_vixen_switcher() -> DomainSwitcher:
    """Vixen Network 切换器（Vixen / Blacked / Tushy / Deeper / Slayed / Milfy）"""
    sites = WESTERN_SITES
    urls = []
    vixen_brands = ["vixen", "blacked", "tushy", "deeper", "slayed", "milfy"]
    for brand in vixen_brands:
        if brand in sites:
            urls.extend(_collect_urls(sites[brand]))
    return DomainSwitcher(name="vixen_network", candidate_urls=urls)
