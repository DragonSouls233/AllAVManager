"""
多站点结果合并策略

增强版(借鉴 JavSP `info_summary`):
- 支持标签优先级排序、is_mosaic/is_chinese 合并、tags 字段合并
- **多封面列表**:covers / big_covers 收集所有源,下载时按序尝试(避免单源失效)
- **番号投票**:`respect_site_avid` 多源番号投票纠正文件名错误
- **水印策略**:`use_javdb_cover` = fallback / no / yes(JavDB 封面有水印,优先用其他源)
- **女优别名统一**:`resolve_actress_alias` 用 alias 字典把多个艺名归一
- **hard_sub/uncensored 自动加 genre**:多源检测到内嵌字幕/无码流出自动加标签
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from app.crawlers.base import ActorInfo, ScrapeResult

logger = logging.getLogger(__name__)


class UseJavDBCover(str, Enum):
    """JavDB 水印封面策略(借鉴 JavSP UseJavDBCover)

    - fallback: 其他源无封面才用 javdb(默认,推荐)
    - no: 永不用 javdb 封面(有水印)
    - yes: 优先用 javdb 封面
    """
    FALLBACK = "fallback"
    NO = "no"
    YES = "yes"


@dataclass
class MergeConfig:
    """合并配置"""
    # 字段优先级（站点名 -> 优先级，数字越小优先级越高）
    source_priority: dict[str, int] = None

    # 是否优先使用非空的字段
    prefer_non_empty: bool = True

    # 演员信息合并策略
    merge_actors: bool = True

    # 标签合并策略
    merge_genres: bool = True

    # 样图合并策略
    merge_samples: bool = True

    # 标签优先级（站点名 -> 标签来源优先级）
    tag_source_priority: dict[str, int] = None

    # === 第 4 轮新增:JavSP 借鉴特性 ===

    # 多封面列表:收集所有源封面为 list,下载时按序尝试(避免单源失效)
    # merged.raw_data["covers"] / ["big_covers"] 存储列表
    collect_multi_covers: bool = True

    # 番号投票:多源番号投票决定最终番号(纠正文件名错误)
    # 例如文件名 "SSIS-018" 但 3 个源都返回 "SSIS-019" → 用 SSIS-019
    respect_site_avid: bool = True

    # JavDB 水印封面策略
    use_javdb_cover: UseJavDBCover = UseJavDBCover.FALLBACK

    # 女优别名统一:用 alias 字典把多个艺名归一
    # 例如 "三上悠亚" / "三上悠亞" / "Yua Mikami" 归一为 "三上悠亞"
    resolve_actress_alias: bool = True
    # 别名字典:{"三上悠亚": "三上悠亞", "Yua Mikami": "三上悠亞"}
    actress_alias_map: dict[str, str] = field(default_factory=dict)

    # 自动检测并添加 genre 标签
    auto_add_genres: bool = True

    def __post_init__(self):
        if self.source_priority is None:
            # 默认优先级（数字越小越优先）
            # 覆盖项目所有已注册爬虫，确保每个源都有明确优先级
            self.source_priority = {
                # === 主源（10）— 最可靠、速度快 ===
                "javbus": 10,       # 有码主站，数据全面稳定
                "fc2": 10,          # FC2 主站

                # === 高质量结构化源（15）— JSON/API 数据 ===
                "avmoo": 15,        # JSON API，中文多语言标题，质量高
                "dmm": 15,          # DMM md 版，JSON 结构化
                "dmm_web": 15,      # DMM 网页版

                # === 标准源（20）— 可靠的主流站点 ===
                "javdb": 20,        # 评分/标签质量好
                "missav": 20,       # MissAV，数据较全
                "javlibrary": 20,   # JavLibrary，老牌库
                "mgstage": 20,      # MGStage

                # === 次要源（25）— 补充数据 ===
                "jav321": 25,       # Jav321
                "freejavbt": 25,    # FreeJavBT
                "avsox": 30,        # AvSox，有码备用

                # === 中文聚合源（30）— 中文元数据补充 ===
                "airav": 30,        # AiRav，中文
                "iqqtv": 30,        # IQQTV，中文
                "cnmdb": 30,        # CNMDB，中文库
                "hdouban": 30,      # HDouban，中文

                # === FC2 变体源（35）— FC2 补充 ===
                "fc2hub": 35,       # FC2Hub
                "fc2club": 35,      # FC2Club
                "fc2ppvdb": 35,     # FC2PPVDB
                "fc2fanclub": 35,   # FC2 会员
                "fc2video": 35,     # FC2 视频
                "fc2search": 35,    # FC2 搜索

                # === 英文/专业源（40）— 英文数据补充 ===
                "javdatabase": 40,  # 英文数据源，补充演员档案
                "theporndb": 40,    # ThePornDB，英文

                # === 日本厂商源（45）— 厂商官方数据 ===
                "faleno": 45,       # Faleno
                "dahlia": 45,       # Dahlia
                "prestige": 45,     # Prestige
                "giga": 45,         # Giga
                "kin8": 45,         # Kin8
                "mywife": 45,       # Mywife
                "xcity": 45,        # XCity
                "getchu": 45,       # Getchu

                # === 无码源（50）— 无码内容专用 ===
                "caribbeancom": 50,     # 加勒比
                "heyzo": 50,            # 柚月
                "s1style": 50,          # S1 NO.1 STYLE
                "10musume": 50,         # 一本道
                "caribbeancompr": 50,   # 加勒比 Premium
                "ragdoll": 50,          # Ragdoll

                # === 其他中文源（55）— 补充 ===
                "hscangku": 55,     # HSCangku
                "madouqu": 55,      # Madouqu
                "mdtv": 55,         # MDTV
                "love6": 55,        # Love6
                "lulubar": 55,      # LuluBar
                "cableav": 55,      # CableAV
                "avsex": 55,        # AvSex
                "fantastica": 55,   # Fantastica
                "airav_cc": 55,     # AiRav CC

                # === 官方/新式源（60）— 优先级最低 ===
                "official": 60,         # Official
                "javday": 60,           # JavDay
                "mmtv": 60,             # MMTV
                "avbase": 60,           # Avbase
                "javdb_new": 60,        # JavDB 新版
                "getchu_dl": 60,        # Getchu DL
                "theporndb_movies": 60, # ThePornDB Movies
            }
        if self.tag_source_priority is None:
            # 标签来源优先级（数字越小越优先用于标签排序）
            self.tag_source_priority = {
                # === 最佳标签源（10-15）===
                "javdb": 10,        # 标签最准
                "avmoo": 15,        # 中文标签质量好

                # === 优质标签源（20）===
                "javbus": 20,       # 标签全面
                "missav": 20,       # 标签较全
                "fc2": 20,          # FC2 标签

                # === 标准标签源（25-30）===
                "javlibrary": 25,   # JavLibrary
                "mgstage": 25,      # MGStage
                "airav": 30,        # 中文标签
                "iqqtv": 30,        # 中文标签
                "cnmdb": 30,        # 中文标签
                "hdouban": 30,      # 中文标签

                # === 次要标签源（35）===
                "avsox": 35,        # AvSox
                "jav321": 35,       # Jav321
                "freejavbt": 35,    # FreeJavBT
                "dmm": 35,          # DMM
                "dmm_web": 35,      # DMM 网页

                # === 英文标签源（40）— 优先级较低 ===
                "javdatabase": 40,  # 英文标签
                "theporndb": 40,    # 英文标签

                # === 厂商源标签（45）===
                "faleno": 45,
                "dahlia": 45,
                "prestige": 45,
                "giga": 45,
                "kin8": 45,
                "mywife": 45,
                "xcity": 45,
                "getchu": 45,

                # === 无码源标签（50）===
                "caribbeancom": 50,
                "heyzo": 50,
                "s1style": 50,
                "10musume": 50,
                "caribbeancompr": 50,
                "ragdoll": 50,

                # === FC2 变体标签（55）===
                "fc2hub": 55,
                "fc2club": 55,
                "fc2ppvdb": 55,
                "fc2fanclub": 55,
                "fc2video": 55,
                "fc2search": 55,

                # === 其他/官方源标签（60）===
                "hscangku": 60,
                "madouqu": 60,
                "mdtv": 60,
                "love6": 60,
                "lulubar": 60,
                "cableav": 60,
                "avsex": 60,
                "fantastica": 60,
                "airav_cc": 60,
                "official": 60,
                "javday": 60,
                "mmtv": 60,
                "avbase": 60,
                "javdb_new": 60,
                "getchu_dl": 60,
                "theporndb_movies": 60,
            }


class ResultMerger:
    """
    结果合并器

    合并多个站点的刮削结果，选择最优字段
    支持标签优先级排序和去重
    """

    # 标签通用名映射（不同站点对同一标签的不同命名 → 标准名）
    TAG_NORMALIZE_MAP = {
        "中文字幕": "中文字幕",
        "字幕": "中文字幕",
        "中文字幕": "中文字幕",
        "无码": "无码",
        "無碼": "无码",
        "无修正": "无码",
        "無修正": "无��",
        "uncensored": "无码",
        "有码": "有码",
        "有碼": "有码",
        "高清": "高清",
        "hd": "高清",
        "vr": "VR",
    }

    # 标签黑名单（合并时过滤掉的低质量标签）
    TAG_BLACKLIST = {
        "單體作品", "單體作", "單體", "作品", "配信開始",
        "サンプル動画", "others", "other", "series",
    }

    def __init__(self, config: Optional[MergeConfig] = None):
        self.config = config or MergeConfig()
        # 自动加载女优别名字典(借鉴 JavSP)
        # 仅当用户启用 resolve_actress_alias 且未提供自定义 alias_map 时加载
        # 测试中可传入自定义 alias_map 覆盖此行为
        if (
            self.config.resolve_actress_alias
            and not self.config.actress_alias_map
        ):
            try:
                from app.utils.number_map import get_actress_alias_map
                self.config.actress_alias_map = get_actress_alias_map()
            except ImportError:
                pass  # 测试环境无 number_map 模块时不报错

    def merge(self, results: list[ScrapeResult]) -> Optional[ScrapeResult]:
        """
        合并多个结果

        Args:
            results: 刮削结果列表

        Returns:
            合并后的结果
        """
        if not results:
            return None

        # 单源也要应用自动 genre 标签和女优别名统一(借鉴 JavSP info_summary 行为)
        # 否则单源时 is_chinese/is_mosaic 标记无法转化为 genre,女优别名也无法归一
        if len(results) == 1:
            merged = results[0]
            sorted_results = results  # 单源列表
            if self.config.auto_add_genres:
                self._auto_add_genres(merged, sorted_results)
            if (
                self.config.merge_actors
                and self.config.resolve_actress_alias
                and self.config.actress_alias_map
                and merged.actors
            ):
                self._resolve_actress_aliases(merged.actors)
            # 单源也收集多封面列表(便于下载时按序尝试)
            if self.config.collect_multi_covers:
                covers, big_covers = self._merge_covers(sorted_results)
                merged.raw_data["covers"] = covers
                merged.raw_data["big_covers"] = big_covers
            return merged

        # 按优先级排序
        sorted_results = sorted(
            results,
            key=lambda r: self.config.source_priority.get(r.source, 100),
        )

        # 以优先级最高的结果为基础
        base = sorted_results[0]

        # === 第 4 轮新增:番号投票(纠正文件名错误) ===
        # 多源番号投票:如果多数源返回不同番号,采用多数票结果
        voted_code = base.code
        if self.config.respect_site_avid:
            voted_code = self._vote_avid(sorted_results, base.code)

        # 创建合并结果���结果
        merged = ScrapeResult(
            code=voted_code,
            title=self._merge_field("title", [r.title for r in sorted_results]),
            source=base.source,
        )

        # 合并各个字段
        merged.studio = self._merge_field("studio", [r.studio for r in sorted_results])
        merged.maker = self._merge_field("maker", [r.maker for r in sorted_results])
        merged.label = self._merge_field("label", [r.label for r in sorted_results])
        merged.series = self._merge_field("series", [r.series for r in sorted_results])
        merged.release_date = self._merge_date([r.release_date for r in sorted_results])
        merged.duration = self._merge_field("duration", [r.duration for r in sorted_results])
        merged.plot = self._merge_field("plot", [r.plot for r in sorted_results])
        merged.rating = self._merge_rating([r.rating for r in sorted_results])

        # 合并标签（带优先级排序和去重）
        if self.config.merge_genres:
            merged.genres = self._merge_genres(sorted_results)
        else:
            merged.genres = base.genres or []

        # 布尔字段合并（任一为 True 则取 True）— 必须在 _auto_add_genres 前
        # 因为 _auto_add_genres 依赖 is_chinese/is_mosaic 判断
        merged.is_mosaic = self._merge_bool_or([r.is_mosaic for r in sorted_results])
        merged.is_chinese = self._merge_bool_or([r.is_chinese for r in sorted_results])

        # === 第 4 轮新增:自动检测并添加 genre 标签 ===
        if self.config.auto_add_genres:
            self._auto_add_genres(merged, sorted_results)

        # 合并额外标签
        merged.tags = self._merge_lists([r.tags or [] for r in sorted_results])

        if self.config.merge_actors:
            actor_lists = [r.actors or [] for r in sorted_results]
            merged.actors = self._merge_actors(actor_lists)

            # === 第 4 轮新增:女优别名统一 ===
            if self.config.resolve_actress_alias and self.config.actress_alias_map:
                self._resolve_actress_aliases(merged.actors)
        else:
            merged.actors = base.actors or []

        if self.config.merge_samples:
            merged.sample_images = self._merge_lists([r.sample_images or [] for r in sorted_results])
        else:
            merged.sample_images = base.sample_images or []

        # === 第 4 轮新增:多封面列表 + JavDB 水印策略 ===
        if self.config.collect_multi_covers:
            covers, big_covers = self._merge_covers(sorted_results)
            merged.raw_data["covers"] = covers
            merged.raw_data["big_covers"] = big_covers
            # merged.cover_url 仍为单 URL(向后兼容),取 covers[0]
            if covers:
                merged.cover_url = covers[0]
            if big_covers:
                merged.poster_url = big_covers[0]
        else:
            merged.cover_url = self._merge_field("cover_url", [r.cover_url for r in sorted_results])
            merged.poster_url = self._merge_field("poster_url", [r.poster_url for r in sorted_results])

        merged.trailer_url = self._merge_field("trailer_url", [r.trailer_url for r in sorted_results])

        # 合并原始数据
        merged.raw_data["merged_from"] = [r.source for r in sorted_results]
        # 番号投票结果记录(便于调试)
        if self.config.respect_site_avid and voted_code != base.code:
            merged.raw_data["avid_vote"] = {
                "original": base.code,
                "voted": voted_code,
                "votes": self._count_avid_votes(sorted_results),
            }

        return merged

    # ============================================
    # 第 4 轮新增方法(借鉴 JavSP)
    # ============================================

    def _vote_avid(self, sorted_results: list[ScrapeResult], fallback_code: str) -> str:
        """番号投票:多源番号投票决定最终番号

        借鉴 JavSP `info_summary` 中的 `id_weight` 逻辑:
        - 收集每个源返回的番号
        - 按出现次数投票,取票数最多的
        - 票数相同则按 source_priority 优先级决定
        - 1 票或全相同则用 fallback_code(文件名提取的)
        """
        votes: dict[str, list[str]] = {}  # avid -> [source1, source2, ...]

        for result in sorted_results:
            avid = result.code
            if not avid:
                continue
            # 番号归一化(大写、去横线空格)以便跨源对比
            normalized = avid.upper().replace("-", "").replace("_", "").replace(" ", "")
            votes.setdefault(normalized, []).append(result.source)

        if not votes:
            return fallback_code

        # 按票数降序,票数相同按 source_priority 升序(优先级高在前)
        # 票数 >= 2 才认为有效(单票不纠正文件名)
        sorted_avids = sorted(
            votes.items(),
            key=lambda x: (-len(x[1]), self.config.source_priority.get(x[1][0], 100)),
        )

        if not sorted_avids:
            return fallback_code

        top_avid, top_voters = sorted_avids[0]
        # 仅当多数源(>=2 票)一致,且与文件名提取的番号不同时,才纠正
        normalized_fallback = fallback_code.upper().replace("-", "").replace("_", "").replace(" ", "")
        if len(top_voters) >= 2 and top_avid != normalized_fallback:
            # 还原原始格式(从 sorted_results 中找到对应结果)
            for result in sorted_results:
                normalized = result.code.upper().replace("-", "").replace("_", "").replace(" ", "")
                if normalized == top_avid:
                    logger.info(f"番号投票纠正: 文件名={fallback_code} → 多源一致={result.code} (票数 {len(top_voters)})")
                    return result.code

        return fallback_code

    def _count_avid_votes(self, sorted_results: list[ScrapeResult]) -> dict[str, list[str]]:
        """统计番号投票结果(用于调试日志)"""
        votes: dict[str, list[str]] = {}
        for result in sorted_results:
            if result.code:
                votes.setdefault(result.code, []).append(result.source)
        return votes

    def _merge_covers(
        self, sorted_results: list[ScrapeResult]
    ) -> tuple[list[str], list[str]]:
        """多封面合并 + JavDB 水印策略

        借鉴 JavSP `info_summary` 中的 covers/big_covers 收集逻辑:
        - 遍历所有源,收集不重复的封面 URL
        - JavDB 封面根据 use_javdb_cover 策略处理:
          - fallback: 移到列表末尾(其他源无封面才用)
          - no: 完全移除
          - yes: 正常添加

        Returns:
            (covers, big_covers) 两个列表
        """
        covers: list[str] = []
        big_covers: list[str] = []
        javdb_cover: Optional[str] = None
        seen_covers: set[str] = set()

        for result in sorted_results:
            # cover_url → covers
            if result.cover_url and result.cover_url not in seen_covers:
                if result.source == "javdb":
                    javdb_cover = result.cover_url  # 暂存,根据策略处理
                else:
                    covers.append(result.cover_url)
                    seen_covers.add(result.cover_url)

            # poster_url → big_covers
            if result.poster_url:
                big_covers.append(result.poster_url)

        # JavDB 封面水印策略
        if javdb_cover:
            strategy = self.config.use_javdb_cover
            if strategy == UseJavDBCover.YES:
                # 优先级最高,放在最前
                covers.insert(0, javdb_cover)
            elif strategy == UseJavDBCover.FALLBACK:
                # 移到末尾,其他源无封面才用
                covers.append(javdb_cover)
            elif strategy == UseJavDBCover.NO:
                # 完全不加入
                logger.debug(f"JavDB 封面被丢弃(use_javdb_cover=no): {javdb_cover}")

        return covers, big_covers

    def _resolve_actress_aliases(self, actors: list[ActorInfo]) -> None:
        """女优别名统一(就地修改)

        借鉴 JavSP `actress_alias.json` + `resolve_alias()`:
        - 用 actress_alias_map 把多个艺名归一为标准名
        - 例如 "三上悠亚" / "三上悠亞" / "Yua Mikami" → "三上悠亞"

        Args:
            actors: 演员列表(就地修改 name 字段)
        """
        if not self.config.actress_alias_map:
            return

        for actor in actors:
            if not actor.name:
                continue
            # 标准化键:trim + 大小写不敏感
            key = actor.name.strip()
            # 先尝试精确匹配
            if key in self.config.actress_alias_map:
                actor.name = self.config.actress_alias_map[key]
                continue
            # 再尝试大小写不敏感
            key_lower = key.lower()
            for alias, canonical in self.config.actress_alias_map.items():
                if alias.lower() == key_lower:
                    actor.name = canonical
                    break

    def _auto_add_genres(
        self, merged: ScrapeResult, sorted_results: list[ScrapeResult]
    ) -> None:
        """自动检测并添加 genre 标签

        借鉴 JavSP 的自动标签逻辑:
        - 任一源返回 is_chinese=True → 加 "中文字幕" 标签
        - 任一源返回 is_mosaic=False(无码) → 加 "无码" 标签
        - 检测标题/plot 包含 "内嵌字幕" 关键词 → 加 "内嵌字幕" 标签
        """
        if not merged.genres:
            merged.genres = []

        # 1. 中文字幕
        if merged.is_chinese and "中文字幕" not in merged.genres:
            merged.genres.append("中文字幕")

        # 2. 无码流出
        # is_mosaic=False 表示爬虫明确判定为无码
        has_uncensored = any(
            r.is_mosaic is False for r in sorted_results
        )
        if has_uncensored:
            if "无码" not in merged.genres and "無碼" not in merged.genres:
                merged.genres.append("无码")

        # 3. 检测标题/plot 包含 "内嵌字幕"
        text_to_check = (merged.title or "").lower() + " " + (merged.plot or "").lower()
        if "内嵌字幕" in text_to_check or "hardcoded" in text_to_check:
            if "内嵌字幕" not in merged.genres:
                merged.genres.append("内嵌字幕")

    def _merge_field(self, field_name: str, values: list) -> Optional[any]:
        """合并单个字段，优先使用非空值"""
        if not self.config.prefer_non_empty:
            return values[0] if values else None

        for value in values:
            if value is not None and value != "" and value != []:
                return value

        return None

    def _merge_date(self, dates: list[Optional[date]]) -> Optional[date]:
        """合并日期字段"""
        for date_val in dates:
            if date_val is not None:
                return date_val
        return None

    def _merge_rating(self, ratings: list[Optional[float]]) -> Optional[float]:
        """合并评分，返回最高分"""
        valid_ratings = [r for r in ratings if r is not None and 0 < r <= 10]

        if not valid_ratings:
            return None

        return max(valid_ratings)

    def _merge_bool_or(self, bools: list[Optional[bool]]) -> Optional[bool]:
        """合并布尔字段：任一为 True 则 True，全部 None 则 None"""
        has_true = False
        has_value = False
        for b in bools:
            if b is True:
                has_true = True
                has_value = True
            elif b is False:
                has_value = True
        if not has_value:
            return None
        return has_true

    def _merge_lists(self, lists: list[list]) -> list:
        """合并列表（去重保持顺序）"""
        result = []
        seen = set()

        for lst in lists:
            for item in lst:
                if item not in seen:
                    result.append(item)
                    seen.add(item)

        return result

    def _merge_genres(self, sorted_results: list[ScrapeResult]) -> list[str]:
        """
        合并标签（带优先级排序和去重）

        策略：
        1. 收集所有标签，记录每个标签的来源站点优先级
        2. 标签标准化（不同命名统一）
        3. 按来源优先级排序
        4. 过滤黑名单
        """
        # 标签 -> 最佳来源优先级
        tag_scores: dict[str, int] = {}

        for result in sorted_results:
            source_priority = self.config.tag_source_priority.get(result.source, 50)
            for genre in (result.genres or []):
                # 标准化
                normalized = self._normalize_tag(genre)
                if not normalized or normalized in self.TAG_BLACKLIST:
                    continue

                # 保留最佳（最小）优先级
                if normalized not in tag_scores or source_priority < tag_scores[normalized]:
                    tag_scores[normalized] = source_priority

        # 按优先级排序（数字小优先）
        sorted_tags = sorted(tag_scores.keys(), key=lambda t: tag_scores[t])

        return sorted_tags

    def _normalize_tag(self, tag: str) -> str:
        """标准化标签名称"""
        tag = tag.strip().lower()

        # 通用名映射
        for key, value in self.TAG_NORMALIZE_MAP.items():
            if tag == key.lower():
                return value

        # 移除多余空白
        tag = re.sub(r'\s+', '', tag)

        return tag

    def _merge_actors(self, actor_lists: list[list[ActorInfo]]) -> list[ActorInfo]:
        """
        合并演员列表

        去重并保留更多信息
        """
        actor_map: dict[str, ActorInfo] = {}

        for actors in actor_lists:
            for actor in actors:
                name = actor.name.strip()

                if name not in actor_map:
                    actor_map[name] = actor
                else:
                    existing = actor_map[name]

                    # 保留日文名
                    if actor.japanese_name and not existing.japanese_name:
                        existing.japanese_name = actor.japanese_name

                    # 保留头像
                    if actor.avatar_url and not existing.avatar_url:
                        existing.avatar_url = actor.avatar_url

        return list(actor_map.values())


def merge_results(
    results: list[ScrapeResult],
    config: Optional[MergeConfig] = None,
) -> Optional[ScrapeResult]:
    """
    合并多个刮削结果的便捷函数

    Args:
        results: 刮削结果列表
        config: 合并配置

    Returns:
        合并后的结果
    """
    merger = ResultMerger(config)
    return merger.merge(results)
