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
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from app.crawlers.base import ActorInfo, ScrapeResult
from app.scraper.number import normalize_number

logger = logging.getLogger(__name__)


def _avid_key(code: str) -> str:
    """番号等价归一：用于跨源比较"是不是同一个番号"。

    🔴 2026-10-04 修正。原实现只做大写 + 去 `-`/`_`/空格，导致**语义前缀没归一**：
      `FC2-PPV-1234567` → `FC2PPV1234567`
      `FC2-1234567`     → `FC21234567`
    两者被当成**两个不同番号**，于是 >=2 票就能把规范番号 `FC2-1234567`
    投票改写成 `FC2-PPV-1234567`（实测复现）。
    而全仓已在 2026-10-04 统一为 `FC2-{id}`（见 number.py::FC2_PATTERN），
    库内既有 code 也是这个形态 ⇒ 投票结果会与库里对不上号。

    修法：先走 number.normalize_number（它会处理 FC2/PPV 前缀与分隔符），
    再去掉剩余分隔符做纯比较键。比较键仅用于投票，**返回给调用方的仍是原 code**。
    """
    if not code:
        return ""
    try:
        norm = normalize_number(code)
    except Exception:
        norm = code.upper()
    return re.sub(r"[-_\s]", "", norm)


#: 番号里不可能出现的字符（CJK / 日文假名 / 韩文 / 全角）。
#: 真实库 839 个 code 里只有 2 个含 CJK，且都是 pornhub 的目录名误填
#: （`_Channel__Anna_Cherry7__…__6a488932e1d19_`），属脏数据。
_CODE_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u3000-\u303f\uff00-\uffef]")

#: 日期式素人番号：`012213-831` / `012213831`（6 位日期 + 3 位序号）。
#: 真实库 uncensored 模块 8 条实测样本全部符合此形态。
_DATE_AVID_RE = re.compile(r"^\d{9}$")


def _is_avid_shaped(code: str) -> bool:
    """判断字符串是否长得像一个**番号**，而不是标题/路径/演员名。

    🔴 2026-10-04 新增。番号投票有个结构性风险：它只数"几个源返回了同一个
    字符串"。于是**任何被误填进 ``ScrapeResult.code`` 的脏值**，只要有 >=2 个源
    同样脏，就能把正确的文件名番号投票改写掉。实测复现两种：

      - 标题/CJK：2 个源都返回 ``【2024】年 美熟女`` ⇒ 1 票的 ``SSIS-018``
        被改写成中文标题
      - 裸数字：2 个源都只返回 ``3000``（厂商站常见，缺 ``HEYZO-`` 前缀）
        ⇒ 规范番号 ``HEYZO-3000`` 被降级成 ``3000``

    而**这不是假想**：pornhub 扫描器的回退分支（文件名无 viewkey 时用相对路径
    当 code）产出的是 83~139 字符的路径串，库里已有 6 条这样的脏记录。

    规则刻意保守 —— 只排除"确定不是番号"的形态，避免误杀真实番号：
      - 含 CJK / 假名 / 韩文 / 全角  → 一定是标题或中文目录名
      - 归一后长度 > 40            → 真实番号最长 23 字符（`TOKYO-HOT N2040` 之类），
                                      超过必是标题/路径

    ⚠️⚠️ **不能简单要求"含 ASCII 字母"**。无码片的**日期式素人番号**
    （`012213-831` / `041207-923`）归一后是纯数字，实测真实库 uncensored 模块
    有 8 条。第一版用 `if not re.search(r"[A-Za-z]", s): return False` 把它们
    **全部误杀** —— 被自己的验收脚本 [H] 段当场抓住。
    纯数字是否合法取决于**形态**：
      - ``6 位日期 + 3 位序号``（`012213-831` / `012213831`）→ 合法素人番号
      - 其他纯数字（`3000`、`9999`）→ 是厂商站的 movie_id / 降级形态，
        已在 :func:`_vote_avid` 里用"裸数字不降级完整番号"单独处理
    """
    if not code:
        return False
    s = str(code).strip()
    if not s or _CODE_CJK_RE.search(s):
        return False
    if len(_avid_key(s)) > 40:
        return False
    if re.search(r"[A-Za-z]", s):
        return True
    # 纯数字：只接受日期式素人番号（YYMMDD-NNN / YYMMDDNNN）
    return bool(_DATE_AVID_RE.match(_avid_key(s)))


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
    use_javdb_cover: UseJavDBCover = UseJavDBCover.YES

    # 女优别名统一:用 alias 字典把多个艺名归一
    # 例如 "三上悠亚" / "三上悠亞" / "Yua Mikami" 归一为 "三上悠亞"
    resolve_actress_alias: bool = True
    # 别名字典:{"三上悠亚": "三上悠亞", "Yua Mikami": "三上悠亞"}
    actress_alias_map: dict[str, str] = field(default_factory=dict)

    # 自动检测并添加 genre 标签
    auto_add_genres: bool = True

    # === 逐字段来源优先级（2026-10-04）===
    # 全局 source_priority 的隐含假设是"最优先的源在每个字段上都最好"，
    # 实测不成立。field_priority 只写**差异项**，未列出的源沿用全局表。
    #   key   = ScrapeResult 字段名
    #   value = {源名: 优先级数字，越小越优先}
    field_priority: dict[str, dict[str, int]] = None

    def __post_init__(self):
        if self.source_priority is None:
            # 默认优先级（数字越小越优先）
            # 覆盖项目所有已注册爬虫，确保每个源都有明确优先级
            self.source_priority = {
                # === 主源（10）— 最可靠、速度快 ===
                "javbus": 10,       # 有码主站，数据全面稳定
                "fc2": 10,          # FC2 主站
                "javdb": 10,        # JAVDB 评分/标签最全 —— 与 JavBus 并列第一序列

                # === 高质量结构化源（15）— JSON/API 数据 ===
                "avmoo": 15,        # JSON API，中文多语言标题，质量高
                "dmm": 15,          # DMM md 版，JSON 结构化
                "dmm_web": 15,      # DMM 网页版

                # === 标准源（20）— 可靠的主流站点 ===
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

        if self.field_priority is None:
            # 逐字段优先级：只写与全局表**不一致**的字段。
            # 未列出的源沿用 source_priority（_field_order 用它做二级排序）。
            self.field_priority = {
                # ---- 标题：中文源优先 ----
                # 全局表里 pornhub 与 javbus 同为 10，但 PH 的 HTML 源只有英文标题，
                # 让位给有中文标题的聚合源。
                "title": {
                    "pornhub": 30, "pornhub_api": 30,
                    "javdb": 5, "javbus": 10, "avmoo": 8, "airav": 20,
                },
                # ---- 厂商 / 厂牌：官方厂商源最权威 ----
                # 聚合站会把 "S1 NO.1 STYLE" 之类简写或译名当成厂商名。
                "studio": {
                    "faleno": 5, "dahlia": 5, "prestige": 5, "giga": 5,
                    "kin8": 5, "mywife": 5, "xcity": 5, "getchu": 8,
                    "s1style": 5, "caribbeancom": 5, "heyzo": 5,
                    "10musume": 5, "caribbeancompr": 5, "ragdoll": 5,
                    "pornhub": 40, "javbus": 20,
                },
                "maker": {
                    "faleno": 5, "dahlia": 5, "prestige": 5, "giga": 5,
                    "kin8": 5, "mywife": 5, "xcity": 5, "getchu": 8,
                    "pornhub": 40,
                },
                "label": {
                    "s1style": 5, "caribbeancom": 5, "heyzo": 5,
                    "10musume": 5, "caribbeancompr": 5, "ragdoll": 5,
                    "pornhub": 40,
                },
                # ---- 评分：JavDB 评分最全，PH 用 0-100 折算值可作交叉验证 ----
                "rating": {
                    "javdb": 5, "dmm": 10, "dmm_web": 10,
                    "javlibrary": 20, "pornhub": 20, "pornhub_api": 20,
                },
                # ---- 封面：结构化 JSON 源的图更稳定，聚合站常有防盗链/占位图 ----
                "cover_url": {
                    "javdb": 5, "avmoo": 8, "dmm": 10,
                    "pornhub": 15, "pornhub_api": 12,
                    "javlibrary": 30, "missav": 35,
                },
                "poster_url": {
                    "javdb": 5, "avmoo": 8, "dmm": 10,
                    "pornhub": 15, "pornhub_api": 12,
                },
                # ---- 简介：中文源优先；无码片 FC2 官方描述最准 ----
                "plot": {
                    "airav": 10, "javdb": 12, "avmoo": 15,
                    "fc2": 8, "fc2ppvdb": 15,
                    "pornhub": 30, "javbus": 25,
                },
                # ---- 演员：官方/结构化源的演员表最完整 ----
                "actors": {
                    "javdb": 5, "javlibrary": 10, "dmm": 12,
                    "pornhub": 20, "theporndb": 20,
                },
                # ---- 时长：PH 返回 mm:ss 字符串，与其他源单位不同，排在后面 ----
                "duration": {
                    "javdb": 5, "javbus": 8, "dmm": 10,
                    "pornhub": 30, "pornhub_api": 30,
                },
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
            # 2026-10-04：单源路径也要有字段溯源，否则"单源"与"多源合并"
            # 在可观测性上表现不一致（排查时会误以为字段没被合并过）。
            merged.raw_data["field_sources"] = self._build_field_sources(
                merged, sorted_results, {"changed": False, "candidates": {}}
            )
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
        voted_marker: dict = {"changed": False, "candidates": {}}
        if self.config.respect_site_avid:
            voted_code = self._vote_avid(sorted_results, base.code)
            voted_marker = {
                "changed": voted_code != base.code,
                "candidates": self._count_avid_votes(sorted_results),
            }

        # 创建合并结果
        merged_title, merged_original_title = self._merge_title(sorted_results)
        merged = ScrapeResult(
            code=voted_code,
            title=merged_title,
            source=base.source,
        )
        merged.original_title = merged_original_title or self._merge_field_from(
            "original_title", sorted_results
        )

        # 合并各个字段（逐字段来源优先级，见 MergeConfig.field_priority）
        merged.studio = self._merge_field_from("studio", sorted_results)
        merged.maker = self._merge_field_from("maker", sorted_results)
        merged.label = self._merge_field_from("label", sorted_results)
        merged.series = self._merge_field_from("series", sorted_results)
        merged.release_date = self._merge_date([r.release_date for r in sorted_results])
        merged.duration = self._merge_field_from("duration", sorted_results)
        merged.plot = self._merge_field_from("plot", sorted_results)
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
        # 🔴 2026-10-04 修复：is_uncensored 原先**从未被赋值**（恒 None）。
        # 后果不是"字段为空"而是**污染已有数据**：workflow.persist() 里
        # `if hasattr(MovieCls, "is_uncensored"): common_fields["is_uncensored"] = result.is_uncensored`
        # 是**无条件 setattr**（不像 maker/studio 那样判空），于是走多源合并路径时
        # 会把库里已经是 True 的无码标记**覆盖成 None** —— 已有正确值被清空。
        # 语义与 is_mosaic 严格互反（无码 ⇔ 非有码），故优先用 is_mosaic 推导；
        # 只有全部源的 is_mosaic 都是 None 时，才回退读各源自己的 is_uncensored。
        merged.is_uncensored = self._derive_uncensored(sorted_results, merged.is_mosaic)

        # === 2026-10-04 修复：以下字段原先从未被合并，合并结果恒为空 ===
        # directors：workflow.persist() 只读 raw_data["director"]，而 merge() 的
        #   raw_data 只放 covers/field_sources 等 ⇒ **走多源合并时导演 100% 丢失**
        #   （单源路径反而正常 ⇒ 非常隐蔽，只在启用多源时才复现）。
        merged.directors = self._merge_lists([r.directors or [] for r in sorted_results])
        merged.male_actors = self._merge_lists([r.male_actors or [] for r in sorted_results])
        merged.extrafanart = self._merge_lists([r.extrafanart or [] for r in sorted_results])
        # all_actors 是"全部女优名"补充表；源没给就由已合并的 actors 派生
        merged.all_actors = self._merge_lists([r.all_actors or [] for r in sorted_results])
        if not merged.all_actors:
            merged.all_actors = [
                a.name for a in (merged.actors or []) if getattr(a, "name", None)
            ]
        # source_url 供 NFO <website>；thumb_url 供缩略图回退
        merged.source_url = self._merge_field_from("source_url", sorted_results)
        merged.thumb_url = self._merge_field_from("thumb_url", sorted_results)
        merged.votes = self._merge_int([r.votes for r in sorted_results])
        merged.javdb_id = self._merge_field_from("javdb_id", sorted_results)
        merged.wanted = self._merge_field_from("wanted", sorted_results)

        # === 第 4 轮新增:自动检测并添加 genre 标签 ===
        if self.config.auto_add_genres:
            self._auto_add_genres(merged, sorted_results)

        # 合并额外标签
        merged.tags = self._merge_lists([r.tags or [] for r in sorted_results])

        if self.config.merge_actors:
            # 演员按 actors 字段优先级排序：结构化源（javdb/官方）的演员表最完整，
            # 同名演员去重时保留靠前来源的档案信息。
            actor_lists = [r.actors or [] for r in self._field_order("actors", sorted_results)]
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
            merged.cover_url = self._merge_field_from("cover_url", sorted_results)
            merged.poster_url = self._merge_field_from("poster_url", sorted_results)

        merged.trailer_url = self._merge_field_from("trailer_url", sorted_results)

        # 合并原始数据
        merged.raw_data["merged_from"] = [r.source for r in sorted_results]
        # 番号投票结果记录(便于调试)
        if self.config.respect_site_avid and voted_code != base.code:
            merged.raw_data["avid_vote"] = {
                "original": base.code,
                "voted": voted_code,
                "votes": self._count_avid_votes(sorted_results),
            }

        # === 2026-10-04 新增:字段级来源溯源 ===
        merged.raw_data["field_sources"] = self._build_field_sources(
            merged, sorted_results, voted_marker
        )

        return merged

    def _build_field_sources(
        self,
        merged: ScrapeResult,
        sorted_results: list[ScrapeResult],
        voted_marker: Optional[dict] = None,
    ) -> dict:
        """回溯每个字段最终值来自哪个源，写入 raw_data["field_sources"]。

        动机：原实现只有**源级**溯源（`merged_from` = 参与合并的源列表），
        无法回答"这个标题/这张封面到底是哪个源贡献的"。排查字段污染时
        只能逐个源重跑对比。

        实现要点：
        - 纯标量字段（str/int/float/bool/date）：取第一个值等于最终值的源；
          都为空则记 base 源（表示"所有源都没有，是兜底"）。
        - 列表字段（genres/actors/sample_images/tags）：记录贡献了元素的源集合，
          因为列表是多源并集，逐元素溯源会过于冗长。
        - 数值容差：rating/duration 用近似比较，避免浮点/秒分钟换算误差导致
          明明来自该源却匹配不上。
        """
        out: dict = {}

        def pick_scalar(field_name: str, final_value, approx: bool = False):
            if final_value in (None, "", [], {}):
                out[field_name] = {"source": base_src, "value": None, "status": "empty"}
                return
            for r in sorted_results:
                v = getattr(r, field_name, None)
                if v in (None, "", [], {}):
                    continue
                if approx:
                    try:
                        if abs(float(v) - float(final_value)) < 1e-6:
                            out[field_name] = {"source": r.source, "value": v, "status": "from_source"}
                            return
                    except (TypeError, ValueError):
                        if v == final_value:
                            out[field_name] = {"source": r.source, "value": v, "status": "from_source"}
                            return
                elif v == final_value:
                    out[field_name] = {"source": r.source, "value": v, "status": "from_source"}
                    return
            # 有最终值但没匹配到任何源（如被 _apply_suffix / 归一化改写过）
            out[field_name] = {"source": base_src, "value": final_value, "status": "derived"}

        def pick_list(field_name: str, final_list: list):
            if not final_list:
                out[field_name] = {"sources": [], "count": 0, "status": "empty"}
                return
            contributors = []
            final_set = {str(x) for x in final_list}
            for r in sorted_results:
                v = getattr(r, field_name, None) or []
                if not v:
                    continue
                # 该源的元素有出现在最终列表里 → 视为贡献者
                if final_set & {str(x) for x in v}:
                    contributors.append(r.source)
            out[field_name] = {
                "sources": contributors,
                "count": len(final_list),
                "status": "from_sources" if contributors else "derived",
            }

        base_src = sorted_results[0].source if sorted_results else None

        # 标量字段
        for fname in (
            "title", "original_title", "plot", "studio", "maker",
            "label", "series", "release_date", "cover_url",
            "poster_url", "trailer_url", "source_url", "javdb_id",
        ):
            pick_scalar(fname, getattr(merged, fname, None))
        # 数值用近似比较
        pick_scalar("duration", getattr(merged, "duration", None), approx=True)
        pick_scalar("rating", getattr(merged, "rating", None), approx=True)
        pick_scalar("is_mosaic", getattr(merged, "is_mosaic", None))
        pick_scalar("is_chinese", getattr(merged, "is_chinese", None))
        # 番号是投票产物，单独记
        out["code"] = {
            "source": "vote" if voted_marker.get("changed") else base_src,
            "value": getattr(merged, "code", None),
            "status": "voted" if voted_marker.get("changed") else "from_source",
            **({"candidates": voted_marker["candidates"]} if voted_marker.get("changed") else {}),
        }
        # 列表字段
        for fname in ("genres", "tags", "sample_images", "extrafanart"):
            pick_list(fname, getattr(merged, fname, None) or [])
        # 演员取名字集合
        actors = merged.actors or []
        if actors:
            names = {a.name for a in actors if hasattr(a, "name")}
            contributors = [r.source for r in sorted_results
                            if names & {a.name for a in (r.actors or []) if hasattr(a, "name")}]
            out["actors"] = {"sources": contributors, "count": len(actors),
                             "status": "from_sources" if contributors else "derived"}
        else:
            out["actors"] = {"sources": [], "count": 0, "status": "empty"}

        return out

    # ============================================
    # 标题合并（中文优先）
    # ============================================

    def _merge_title(
        self, sorted_results: list[ScrapeResult]
    ) -> tuple[Optional[str], Optional[str]]:
        """合并标题：中文标题优先，日文/英文标题进 original_title

        各源标题情况：
        - avmoo:  title = title_cn（中文，优先 title_jp 兜底），original_title = title_jp（日文）
        - javdb:  title = current-title（locale=zh 下为中文），original_title = origin-title（日文）
        - javbus: title = 日文标题，无 original_title

        策略：
        1. 优先取中文源标题（avmoo / javdb / 中文聚合源），按 source_priority 升序；
           避免 javbus 等日文源（优先级与 javdb 并列 10）抢先覆盖中文标题。
        2. 无中文源时退回最高优先级源的非空标题（保持旧行为）。
        3. original_title 取各源已提供的日文/英文原始标题；若最终 title 本身为日文
           （无中文源可用）且无原始标题，则 original_title = title。

        Returns:
            (title, original_title)
        """
        # 标题为中文的源（含 javdb / avmoo / 各中文聚合源）
        CHINESE_TITLE_SOURCES = {
            "avmoo", "javdb",
            "airav", "iqqtv", "cnmdb", "hdouban",
            "hscangku", "madouqu", "mdtv", "love6", "lulubar",
            "cableav", "avsex", "fantastica", "airav_cc",
        }

        # 1) 中文源标题候选，按 source_priority 升序（数字小优先）
        cn_candidates = sorted(
            (
                r for r in sorted_results
                if r.title and r.source in CHINESE_TITLE_SOURCES
            ),
            key=lambda r: self.config.source_priority.get(r.source, 100),
        )

        title: Optional[str] = None
        if cn_candidates:
            title = cn_candidates[0].title
        else:
            # 无中文源：取优先级最高的非空标题（旧行为）
            for r in sorted_results:
                if r.title:
                    title = r.title
                    break

        # 2) original_title：优先取各源已提供的日文/英文原始标题
        original: Optional[str] = None
        for r in sorted_results:
            if r.original_title:
                original = r.original_title
                break

        # 若标题本身是日文（无中文源可用）且无原始标题，则 original_title = title
        if not original and title and not cn_candidates:
            original = title

        return title, original

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

        🔴 2026-10-04 加形态保护。原实现只数"几个源返回了同一字符串"，
        于是**任何被误填进 code 的脏值只要有 >=2 票就能改写正确番号**。实测两种：
          - 标题/CJK：2 源返回 ``【2024】年 美熟女`` ⇒ ``SSIS-018`` 被改写成中文标题
          - 裸数字：2 源只返回 ``3000`` ⇒ ``HEYZO-3000`` 被降级成 ``3000``
        （裸数字来自厂商站只给 movie_id 不给番号前缀，是真实常见形态。）
        现在进入投票的 code 必须通过 :func:`_is_avid_shaped`；
        裸数字胜出时若 fallback 带前缀，则保持 fallback（不降级）。
        """
        votes: dict[str, list[str]] = {}  # avid -> [source1, source2, ...]
        rejected: list[str] = []  # "source:code" 被形态保护拒掉

        for result in sorted_results:
            avid = result.code
            if not avid:
                continue
            # 番号等价归一（走 _avid_key，含 FC2/PPV 前缀处理），
            # 不能再用"只去分隔符"的写法 —— 那会把 FC2-1234567 与
            # FC2-PPV-1234567 判成两个番号，>=2 票就能把规范番号改写掉。
            if not _is_avid_shaped(avid):
                rejected.append(f"{result.source}:{str(avid)[:50]}")
                continue
            normalized = _avid_key(avid)
            votes.setdefault(normalized, []).append(result.source)

        if rejected:
            logger.debug(
                "番号投票: 形态保护拒掉 %d 条疑似脏 code（不计入票数）: %s",
                len(rejected), rejected,
            )

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

        # 裸数字降级保护：厂商站常只给 movie_id（`3000`）而不带番号前缀
        # （`HEYZO-3000`）。这类票数再多也不能把完整番号降级掉。
        # ⚠️ 反向不拦：日期式素人番号 `012213-831` 归一后也是纯数字，
        #    但它的 fallback 通常本身就是纯数字，条件不成立。
        if top_avid.isdigit() and not _avid_key(fallback_code).isdigit():
            logger.debug(
                "番号投票: 胜出者 %r 是裸数字而 fallback %r 带前缀 ⇒ 保持 fallback",
                top_avid, fallback_code,
            )
            return fallback_code

        # 仅当多数源(>=2 票)一致,且与文件名提取的番号不同时,才纠正
        normalized_fallback = _avid_key(fallback_code)
        if len(top_voters) >= 2 and top_avid != normalized_fallback:
            # 还原原始格式(从 sorted_results 中找到对应结果)
            for result in sorted_results:
                if _avid_key(result.code) == top_avid:
                    logger.info(f"番号投票纠正: 文件名={fallback_code} → 多源一致={result.code} (票数 {len(top_voters)})")
                    return result.code

        return fallback_code

    def _count_avid_votes(self, sorted_results: list[ScrapeResult]) -> dict:
        """统计番号投票结果(写入 raw_data["avid_vote"] 供排查)

        🔴 2026-10-04 修正：原先直接用**原始 code** 分组，而
        :meth:`_vote_avid` 用的是**归一后**的 ``_avid_key``。两者口径不一致
        ⇒ 排查时看到的票数与实际投票依据对不上（实测 FC2 三源
        ``FC2-1234567`` / ``FC2-PPV-1234567`` / ``fc2ppv1234567``：
        实际是 1 组 3 票，统计却显示 3 组各 1 票）。
        同时把被形态保护拒掉的脏值单列，便于定位是哪个源在污染番号。
        """
        votes: dict[str, list[str]] = {}
        rejected: list[str] = []
        for result in sorted_results:
            if not result.code:
                continue
            if not _is_avid_shaped(result.code):
                rejected.append(f"{result.source}:{str(result.code)[:50]}")
                continue
            votes.setdefault(_avid_key(result.code), []).append(result.source)
        if rejected:
            votes["__rejected__"] = rejected
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

        # 候选列表按 cover_url 字段优先级排序：下载端是「按序尝试直到成功」，
        # 所以越可靠的源越靠前，能显著减少 403/占位图导致的失败重试。
        for result in self._field_order("cover_url", sorted_results):
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

    def _field_order(
        self, field_name: str, results: list[ScrapeResult]
    ) -> list[ScrapeResult]:
        """按**该字段专属**的源优先级重排结果（逐字段优先级）。

        2026-10-04 新增。此前只有一张全局 `source_priority` 管所有字段，
        隐含假设是"最优先的源在每个字段上都最好"——实测不成立：
        PH 的 HTML 源评分/样图强但没有中文标题，JavBus 反之；
        厂商名（studio/label）应该信官方厂商源而不是聚合站。

        `field_priority` 只需写**差异项**，未列出的源沿用全局 `source_priority`。
        """
        overrides = self.config.field_priority.get(field_name)
        if not overrides:
            return results
        base_pri = self.config.source_priority
        return sorted(
            results,
            key=lambda r: (
                overrides.get(r.source, base_pri.get(r.source, 100)),
                base_pri.get(r.source, 100),
            ),
        )

    def _merge_field_from(
        self, field_name: str, results: list[ScrapeResult]
    ) -> Optional[any]:
        """逐字段优先级版取值：先按该字段的源优先级排序，再取首个非空值。"""
        if not self.config.prefer_non_empty:
            ordered = self._field_order(field_name, results)
            return getattr(ordered[0], field_name, None) if ordered else None
        for r in self._field_order(field_name, results):
            value = getattr(r, field_name, None)
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

    def _merge_int(self, values: list[Optional[int]]) -> Optional[int]:
        """合并整数字段：取第一个**大于 0** 的值。

        🔴 不能用 `_merge_field_from`：那个方法只排除 None/""/[]，
        而 votes=0（源站明确"0 人评分"）会被当成有效值抢在真实值前面。
        """
        for v in values:
            if v is not None and not isinstance(v, bool):
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if iv > 0:
                    return iv
        return None

    def _derive_uncensored(
        self, results: list[ScrapeResult], merged_is_mosaic: Optional[bool]
    ) -> Optional[bool]:
        """推导合并后的 is_uncensored（2026-10-04 新增）。

        优先用 `merged.is_mosaic` 取反 —— 二者在数据模型里严格互反
        （`sync.py::_resolve_version_flags` 就是 `is_mosaic = not is_uncensored`），
        所以同一份 `is_mosaic` 投票结果直接取反即可，不会出现自相矛盾。

        仅当所有源的 `is_mosaic` 都是 None（没有任何源表态）时，
        才回退用 `_merge_bool_or` 读各源自己的 `is_uncensored`。
        全程无值 ⇒ None（**不是 False**）：把"未知"写成"有码"同样是静默错误。
        """
        if merged_is_mosaic is not None:
            return not merged_is_mosaic
        return self._merge_bool_or([r.is_uncensored for r in results])

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
