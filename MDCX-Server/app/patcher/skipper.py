"""
智能跳过逻辑

根据条件判断是否跳过补刮：
- 近期刮削（如 7 天内）
- 已审核标记
- 字段完整
- 用户自定义规则
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from app.patcher.detector import MissingInfo

logger = logging.getLogger(__name__)


class SkipReason(str, Enum):
    """跳过原因"""
    RECENTLY_SCRAPED = "recently_scraped"     # 近期已刮削
    ALREADY_VERIFIED = "already_verified"     # 已审核
    FIELDS_COMPLETE = "fields_complete"       # 字段完整
    NO_MISSING_DATA = "no_missing_data"       # 无缺失数据
    USER_SKIPPED = "user_skipped"             # 用户跳过
    CUSTOM_RULE = "custom_rule"               # 自定义规则


@dataclass
class SkipResult:
    """跳过结果"""
    should_skip: bool
    reason: Optional[SkipReason] = None
    message: str = ""
    
    def to_dict(self) -> dict:
        return {
            "should_skip": self.should_skip,
            "reason": self.reason.value if self.reason else None,
            "message": self.message,
        }


class Skipper:
    """
    智能跳过判断器
    
    根据多种条件判断是否应该跳过补刮
    """
    
    def __init__(
        self,
        skip_recent_days: int = 7,
        skip_verified: bool = True,
        skip_complete: bool = True,
        skip_no_missing: bool = True,
    ):
        """
        初始化
        
        Args:
            skip_recent_days: 跳过最近 N 天内刮削的（0 表示不跳过）
            skip_verified: 跳过已审核的
            skip_complete: 跳过字段完整的
            skip_no_missing: 跳过无缺失数据的
        """
        self.skip_recent_days = skip_recent_days
        self.skip_verified = skip_verified
        self.skip_complete = skip_complete
        self.skip_no_missing = skip_no_missing
    
    def should_skip(
        self,
        missing_info: MissingInfo,
        scraped_at: Optional[datetime] = None,
        is_verified: bool = False,
        custom_rules: Optional[list[dict]] = None,
    ) -> SkipResult:
        """
        判断是否应该跳过
        
        Args:
            missing_info: 缺失信息
            scraped_at: 刮削时间
            is_verified: 是否已审核
            custom_rules: 自定义规则列表
            
        Returns:
            SkipResult 跳过结果
        """
        # 1. 检查无缺失数据
        if self.skip_no_missing and not missing_info.has_missing():
            return SkipResult(
                should_skip=True,
                reason=SkipReason.NO_MISSING_DATA,
                message="No missing data detected",
            )
        
        # 2. 检查字段完整
        if self.skip_complete and self._is_complete(missing_info):
            return SkipResult(
                should_skip=True,
                reason=SkipReason.FIELDS_COMPLETE,
                message="All critical fields and images are complete",
            )
        
        # 3. 检查近期刮削
        if self.skip_recent_days > 0 and scraped_at:
            if self._is_recently_scraped(scraped_at):
                return SkipResult(
                    should_skip=True,
                    reason=SkipReason.RECENTLY_SCRAPED,
                    message=f"Scraped within {self.skip_recent_days} days",
                )
        
        # 4. 检查已审核
        if self.skip_verified and is_verified:
            return SkipResult(
                should_skip=True,
                reason=SkipReason.ALREADY_VERIFIED,
                message="Movie has been verified by user",
            )
        
        # 5. 检查自定义规则
        if custom_rules:
            result = self._check_custom_rules(missing_info, custom_rules)
            if result.should_skip:
                return result
        
        # 不跳过
        return SkipResult(
            should_skip=False,
            reason=None,
            message="Ready for patching",
        )
    
    def _is_recently_scraped(self, scraped_at: datetime) -> bool:
        """检查是否近期刮削"""
        threshold = datetime.now() - timedelta(days=self.skip_recent_days)
        return scraped_at > threshold
    
    def _is_complete(self, missing_info: MissingInfo) -> bool:
        """检查是否完整（无关键缺失）"""
        # 检查关键字段
        for field in missing_info.missing_fields:
            if field.importance == "critical":
                return False
        
        # 检查关键图片
        for image in missing_info.missing_images:
            if image.importance == "critical":
                return False
        
        # 检查 NFO
        if not missing_info.nfo_exists:
            return False
        
        return True
    
    def _check_custom_rules(
        self,
        missing_info: MissingInfo,
        rules: list[dict],
    ) -> SkipResult:
        """检查自定义规则"""
        for rule in rules:
            rule_type = rule.get("type")
            
            if rule_type == "field_count":
                # 字段缺失数量阈值
                threshold = rule.get("threshold", 5)
                if len(missing_info.missing_fields) >= threshold:
                    return SkipResult(
                        should_skip=True,
                        reason=SkipReason.CUSTOM_RULE,
                        message=f"Missing fields count ({len(missing_info.missing_fields)}) >= threshold ({threshold})",
                    )
            
            elif rule_type == "image_count":
                # 图片缺失数量阈值
                threshold = rule.get("threshold", 3)
                if len(missing_info.missing_images) >= threshold:
                    return SkipResult(
                        should_skip=True,
                        reason=SkipReason.CUSTOM_RULE,
                        message=f"Missing images count ({len(missing_info.missing_images)}) >= threshold ({threshold})",
                    )
            
            elif rule_type == "code_pattern":
                # 番号模式匹配
                pattern = rule.get("pattern", "")
                if pattern and pattern in missing_info.movie_code:
                    return SkipResult(
                        should_skip=True,
                        reason=SkipReason.CUSTOM_RULE,
                        message=f"Movie code matches skip pattern: {pattern}",
                    )
            
            elif rule_type == "source":
                # 来源站点过滤
                sources = rule.get("sources", [])
                # 这里需要额外信息，暂时跳过
                pass
        
        return SkipResult(should_skip=False)
    
    def batch_filter(
        self,
        missing_infos: list[MissingInfo],
        scraped_times: Optional[dict[int, datetime]] = None,
        verified_ids: Optional[set[int]] = None,
    ) -> tuple[list[MissingInfo], list[SkipResult]]:
        """
        批量过滤，返回需要补刮的和跳过的
        
        Args:
            missing_infos: 缺失信息列表
            scraped_times: 电影ID -> 刮削时间映射
            verified_ids: 已审核的电影ID集合
            
        Returns:
            (需要补刮的列表, 跳过结果列表)
        """
        to_patch = []
        skipped = []
        
        scraped_times = scraped_times or {}
        verified_ids = verified_ids or set()
        
        for info in missing_infos:
            scraped_at = scraped_times.get(info.movie_id)
            is_verified = info.movie_id in verified_ids
            
            result = self.should_skip(info, scraped_at, is_verified)
            
            if result.should_skip:
                skipped.append((info, result))
                logger.debug(f"Skipped {info.movie_code}: {result.message}")
            else:
                to_patch.append(info)
        
        logger.info(
            f"Filter result: {len(to_patch)} to patch, {len(skipped)} skipped"
        )
        
        return to_patch, skipped


def should_skip_patch(
    missing_info: MissingInfo,
    scraped_at: Optional[datetime] = None,
    is_verified: bool = False,
) -> SkipResult:
    """判断是否跳过补刮的便捷函数"""
    skipper = Skipper()
    return skipper.should_skip(missing_info, scraped_at, is_verified)
