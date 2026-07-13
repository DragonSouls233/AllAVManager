"""马赛克类型识别服务

参考 Hazard804-mdcx 的 mosaic.py：
- 通过番号规则识别影片马赛克类型
- 影响爬虫选站（不同站点专注不同类型）
- 三种类型：国产 / 无码 / 有码

判断规则（按优先级）：
1. FC2-PPV / FC2PPV 系列 → 无码
2. Tokyo Hot / Caribbeancom / Heyzo / 1pondo 等无码片商前缀 → 无码
3. 含 "国产" / "国产自拍" 关键字 → 国产
4. 标准 ABC-123 番号格式 → 有码
5. 其他 → 默认有码
"""

import re
from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MosaicType:
    """马赛克类型"""
    code: str  # censored / uncensored / chinese
    display_name: str  # 有码 / 无码 / 国产
    is_mosaic: bool  # 是否有马赛克（True=有码）
    is_uncensored: bool  # 是否无码
    is_chinese: bool  # 是否国产
    confidence: float  # 置信度 0-1
    reason: str  # 判断依据


# 无码番号规则（前缀或正则匹配）
UNCENSORED_PATTERNS = [
    (re.compile(r"^FC2[-_]?PPV[-_]?\d{4,8}", re.IGNORECASE), "FC2-PPV 系列"),
    (re.compile(r"^\d{6}[-_]\d{2,4}", re.IGNORECASE), "FC2 标准 ID 格式"),
    (re.compile(r"^HEYZO[-_]?\d{3,5}", re.IGNORECASE), "Heyzo（无码片商）"),
    (re.compile(r"^Caribbeancom[-_]?\d{6}", re.IGNORECASE), "加勒比（无码片商）"),
    (re.compile(r"^Carib[-_]?\d{6}", re.IGNORECASE), "Carib（无码片商）"),
    (re.compile(r"^1pondo[-_]?\d{6}", re.IGNORECASE), "1pondo（一本道，无码片商）"),
    (re.compile(r"^1000giri[-_]?\w+", re.IGNORECASE), "1000giri（无码片商）"),
    (re.compile(r"^Pacopacomama[-_]?\d{6}", re.IGNORECASE), "Pacopacomama（无码片商）"),
    (re.compile(r"^Muramura[-_]?\d{6}", re.IGNORECASE), "Muramura（无码片商）"),
    (re.compile(r"^H0930[-_]?\w+", re.IGNORECASE), "H0930（无码人妻）"),
    (re.compile(r"^H4610[-_]?\w+", re.IGNORECASE), "H4610（无码素人）"),
    (re.compile(r"^C0930[-_]?\w+", re.IGNORECASE), "C0930（无码人妻）"),
    (re.compile(r"^heyzo[-_]?\d+", re.IGNORECASE), "Heyzo"),
    (re.compile(r"^Tokyo\s*Hot[-_]?\w+", re.IGNORECASE), "Tokyo Hot（无码片商）"),
    (re.compile(r"^n\d{4}", re.IGNORECASE), "n系列（无码）"),
]

# 国产标识关键字
CHINESE_KEYWORDS = ["国产", "国产自拍", "国产情侣", "国产主播", "国产精品", "中国", "大陆", "内地"]

# 标准有码番号格式（如 ABC-123）
CENSORED_PATTERN = re.compile(r"^[A-Za-z]{2,6}[-_]?\d{2,5}$")


def identify_mosaic_type(
    code: str,
    title: Optional[str] = None,
    studio: Optional[str] = None,
) -> MosaicType:
    """识别马赛克类型

    Args:
        code: 番号
        title: 标题（可选，用于辅助判断国产）
        studio: 片商（可选，用于辅助判断国产）

    Returns:
        MosaicType 对象
    """
    if not code:
        return MosaicType(
            code="censored",
            display_name="有码",
            is_mosaic=True,
            is_uncensored=False,
            is_chinese=False,
            confidence=0.3,
            reason="番号为空，默认有码",
        )

    # 1. 优先检查无码番号规则
    for pattern, reason in UNCENSORED_PATTERNS:
        if pattern.search(code):
            return MosaicType(
                code="uncensored",
                display_name="无码",
                is_mosaic=False,
                is_uncensored=True,
                is_chinese=False,
                confidence=0.95,
                reason=f"番号匹配无码规则: {reason}",
            )

    # 2. 检查国产关键字（在标题/片商中匹配）
    full_text = f"{title or ''} {studio or ''} {code}"
    for kw in CHINESE_KEYWORDS:
        if kw in full_text:
            return MosaicType(
                code="chinese",
                display_name="国产",
                is_mosaic=False,
                is_uncensored=False,
                is_chinese=True,
                confidence=0.85,
                reason=f"匹配国产关键字: {kw}",
            )

    # 3. 检查标准有码番号格式
    if CENSORED_PATTERN.match(code):
        return MosaicType(
            code="censored",
            display_name="有码",
            is_mosaic=True,
            is_uncensored=False,
            is_chinese=False,
            confidence=0.9,
            reason="标准番号格式（ABC-123）",
        )

    # 4. 兜底：默认有码
    return MosaicType(
        code="censored",
        display_name="有码",
        is_mosaic=True,
        is_uncensored=False,
        is_chinese=False,
        confidence=0.5,
        reason="未匹配任何规则，默认有码",
    )


def should_use_uncensored_crawler(mosaic: MosaicType, site_name: str) -> bool:
    """判断是否应使用无码专用爬虫

    Args:
        mosaic: 马赛克类型
        site_name: 站点名

    Returns:
        True 表示该站点适合此影片
    """
    # 无码站点优先服务无码/国产影片
    uncensored_sites = {"fc2ppvdb", "avsox", "missav"}
    censored_sites = {"javdb", "javbus", "mgstage"}

    if mosaic.is_uncensored or mosaic.is_chinese:
        return site_name in uncensored_sites
    if mosaic.is_mosaic:
        return site_name in censored_sites
    return True


async def detect_and_update_movie(movie_id: int, code: str, title: str = None, studio: str = None) -> MosaicType:
    """识别马赛克类型并更新影片记录

    Args:
        movie_id: 影片 ID
        code: 番号
        title: 标题
        studio: 片商

    Returns:
        识别结果
    """
    mosaic = identify_mosaic_type(code, title, studio)

    try:
        from app.db.database import get_session_factory
        from app.db.models import Movie
        from sqlalchemy import select

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(Movie).where(Movie.id == movie_id))
            movie = result.scalar_one_or_none()
            if movie:
                movie.is_uncensored = mosaic.is_uncensored
                movie.is_mosaic = mosaic.is_mosaic
                movie.is_chinese = mosaic.is_chinese
                await session.commit()
                logger.info(
                    f"影片 {code} 马赛克类型已更新: {mosaic.display_name} "
                    f"({mosaic.reason})"
                )
    except Exception as e:
        logger.warning(f"更新影片马赛克类型失败: {e}")

    return mosaic


def get_site_recommendation(mosaic: MosaicType, available_sites: list[str]) -> list[tuple[str, int]]:
    """根据马赛克类型推荐站点优先级

    Args:
        mosaic: 马赛克类型
        available_sites: 可用站点列表

    Returns:
        [(site_name, recommended_priority), ...]
    """
    recommendations = []
    for site in available_sites:
        if should_use_uncensored_crawler(mosaic, site):
            recommendations.append((site, 80))  # 推荐
        else:
            recommendations.append((site, 30))  # 不推荐
    recommendations.sort(key=lambda x: x[1], reverse=True)
    return recommendations
