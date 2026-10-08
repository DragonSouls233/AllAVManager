"""P2-1 · 源能力矩阵（source capability matrix）。

## 为什么需要它（取代「只按源序盲试」）

`canon.source_order_for(code)` 给出的源序只解决「**先试谁**」，不解决
「**这个源到底能给什么**」。批量补刮 / 缺口补全时，MDCX 经常遇到：

- 一部片只缺 *演员*，却把 4 个主力源全跑一遍（其中 3 个压根不提供可靠演员）；
- 一部片只缺 *plot*，但 plot 在 8 个源里只有 2 个真正给（thejavdb / javplace），
  其余 6 个要么没有、要么给的是 SEO 垃圾（`_is_junk_plot` 已拦 javmost）；
- 一部片只缺 *封面*，却去试 pornhub 这种详情页 rating 恒 1.0、演员要从
  /model/ 链接另挖的源。

本模块把「每个源**能稳定提供哪些能力**」显式声明出来，让缺口补全可以
**优先挑能补上缺口的源**，而不是盲试整条序。

## 能力定义（三主 + 三辅）

- ``MOVIE``    ：核心元数据（title / studio / release_date / duration / maker /
                 label / series / **cover**）。**封面算 MOVIE**，因为每个电影源
                 都有封面；``GALLERY`` 专指封面之外的**额外剧照 / sample 图**。
- ``PERFORMER``：演员名（``actors`` / ``all_actors``）。
- ``GALLERY``  ：封面之外的额外图片（``sample_images`` / ``extrafanart`` /
                 ``trailer_url``）。
- ``PLOT``     ：剧情简介（真实简介，非 SEO 垃圾）。
- ``RATING``   ：数值评分（0-10）。
- ``GENRES``   ：类型 / 标签（``genres`` / ``tags``）。

## 口径（重要）

声明基于**实测 / 已知抓取行为**，不是猜。两条铁律：

1. **保守优于冒进**。不确定某个源给不给某项能力时，就**不声明**该能力。
   漏声明最多让该源在缺口补全里排得靠后（多试几个请求），**不会污染数据** ——
   因为 engine 仍会校验每个源的真实返回结果（`has_content` / 字段级合并）。
   冒进声明（把一个不给 plot 的源标成给 plot）才会让缺口补全去试一个试了也
   白试的源，纯浪费请求。
2. 未知源（不在 ``SOURCE_CAPABILITIES`` 里的）一律按 ``{MOVIE}`` 兜底 ——
   即「至少能给核心元数据」，但不会去抢 PERFORMER / GALLERY 等缺口。

声明随实测结果**随时收紧 / 扩充**（见各源注释）。新增源接入时，先在
`crawlerx_sites.py` 实测拿到字段，再回来补这一张表。

🔴 永不做的事：把 capability 当成「源一定成功」的保证。它只影响**尝试顺序**，
不影响「源返回了什么」的判定。源返回空 / 软 404 仍由 breaker / miss_cache 处理。
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional


class SourceCapability(str, Enum):
    """一个源能稳定提供的元数据能力。"""

    MOVIE = "movie"          # 核心元数据 + 封面
    PERFORMER = "performer"  # 演员名
    GALLERY = "gallery"      # 封面之外的额外图片 / 预告
    PLOT = "plot"            # 真实剧情简介
    RATING = "rating"        # 数值评分
    GENRES = "genres"        # 类型 / 标签

    @classmethod
    def from_field(cls, field_name: str) -> "SourceCapability":
        """把 ScrapeResult 字段名映射到能力。

        用于「这部片缺 ``actors`` → 需要 ``PERFORMER`` 能力的源」。
        """
        f = field_name
        if f in ("actors", "all_actors", "male_actors", "directors"):
            return cls.PERFORMER
        if f in ("cover_url", "poster_url", "thumb_url",
                 "sample_images", "extrafanart", "trailer_url"):
            return cls.GALLERY
        if f == "plot":
            return cls.PLOT
        if f in ("rating", "votes"):
            return cls.RATING
        if f in ("genres", "tags"):
            return cls.GENRES
        # title / studio / release_date / duration / maker / label / series / source
        return cls.MOVIE


# --------------------------------------------------------------------------
# 能力声明（保守，基于实测 / 已知抓取行为）
# --------------------------------------------------------------------------
# 每个源的注释写清「为什么这么标」，方便日后收紧 / 扩充时追责。
SOURCE_CAPABILITIES: dict[str, set[SourceCapability]] = {
    # === 主力（有码） ===
    # javdb：官方 App API（javdbapi 同款），字段最全 —— 标题/封面/演员/类型/
    # 简介/评分/10 张剧照。实测 avgW 最高，列为全能力。
    "javdb": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.RATING, SourceCapability.GENRES,
    },
    "javdbapi": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.RATING, SourceCapability.GENRES,
    },
    "javdb_enhancer": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.RATING, SourceCapability.GENRES,
    },
    # javmenu：标题/封面/演员/类型/简介都有，标全（含 PLOT）。
    "javmenu": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.GENRES,
    },
    # javmost：演员/类型有，但 plot 是 SEO 垃圾（_is_junk_plot 已拦）⇒ 不标 PLOT。
    "javmost": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GENRES,
    },
    # javbus：标题 + 封面 + 演员头像/名，无可靠额外剧照 ⇒ MOVIE+PERFORMER。
    "javbus": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
    },

    # === 日本官方源 ===
    # dmm_web / dmm_api：FANZA 官方 GraphQL，标题/演员/厂牌/系列/标签/时长/
    # 发行日/评分/封面/10 张剧照/预告片，字段齐。
    "dmm_web": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.RATING, SourceCapability.GENRES,
    },
    "dmm_api": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.RATING, SourceCapability.GENRES,
    },

    # === 辅助源 ===
    # thejavdb：第三方聚合 API，字段全（avgW 4.0），标全。
    "thejavdb": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.PLOT,
        SourceCapability.RATING, SourceCapability.GENRES,
    },
    # avmoo：标题/封面/演员/类型都有，标 MOVIE+PERFORMER+GENRES。
    "avmoo": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GENRES,
    },
    # javplace：实测**真正给 plot** 的少数源之一（与 thejavdb 并列），
    # 演员/类型也有 ⇒ MOVIE+PERFORMER+PLOT+GENRES。
    "javplace": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.PLOT, SourceCapability.GENRES,
    },
    "javdb_new": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GENRES,
    },
    "javdatabase": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GENRES,
    },
    "freejavbt": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GENRES,
    },

    # === crawlerx 新接入源（P1-4 实测） ===
    # heyzo：标题/演员/13 个 genres/封面（gallery/001.jpg）；详情页无 plot/
    # duration/studio ⇒ 不标 PLOT。GALLERY 给（gallery 多图）。
    "heyzo": {
        SourceCapability.MOVIE, SourceCapability.PERFORMER,
        SourceCapability.GALLERY, SourceCapability.GENRES,
    },

    # === 欧美 / 中文 / 里番 / 素人 等 ===
    # pornhub：详情页 rating 恒 1.0（返 None）、演员要 /model/ 链接另挖，
    # 常规 scrape 不可靠 ⇒ 只标 MOVIE（封面/标题）。
    "pornhub": {SourceCapability.MOVIE},
    "pornhub_api": {SourceCapability.MOVIE},
    "western": {SourceCapability.MOVIE},
    "western_aggregate": {SourceCapability.MOVIE},
    "chinese": {SourceCapability.MOVIE},
    "uncensored": {SourceCapability.MOVIE},
    "uncensored_aggregate": {SourceCapability.MOVIE},
    "uncensored_detail": {SourceCapability.MOVIE},
    # 里番（getchu/kin8）：标题/封面，无演员概念 ⇒ MOVIE。
    "getchu": {SourceCapability.MOVIE},
    "kin8": {SourceCapability.MOVIE},
    # 素人 / 通用有码站：保守标 MOVIE（标题/封面），演员/类型以实测为准再补。
    "wiki_amateur": {SourceCapability.MOVIE},
    "myjav": {SourceCapability.MOVIE},
    "javsb": {SourceCapability.MOVIE},
    "javxx": {SourceCapability.MOVIE},
    "av123": {SourceCapability.MOVIE},
    "avsox": {SourceCapability.MOVIE},
    "fc2": {SourceCapability.MOVIE},
    "fc2_enhanced": {SourceCapability.MOVIE},
    "fc2_extended": {SourceCapability.MOVIE},
    "fc2_extended_detail": {SourceCapability.MOVIE},
    "fc2_javbus": {SourceCapability.MOVIE},
    "fc2club": {SourceCapability.MOVIE},
    "fc2ppvdb": {SourceCapability.MOVIE},
    "javbooks": {SourceCapability.MOVIE},   # 已死，仅兜底
    "missav_api": {SourceCapability.MOVIE},
    # fanart：纯图片源（剧照 / logo / thumb），无元数据 ⇒ 只标 GALLERY。
    "fanart": {SourceCapability.GALLERY},
}


# 未知源兜底能力
_DEFAULT_CAPS: frozenset[SourceCapability] = frozenset({SourceCapability.MOVIE})


def capabilities_for_source(name: str) -> frozenset[SourceCapability]:
    """返回某源能稳定提供的能力集合（未知源兜底 ``{MOVIE}``）。"""
    caps = SOURCE_CAPABILITIES.get(name)
    if caps is None:
        return _DEFAULT_CAPS
    return frozenset(caps)


def has_capability(name: str, cap: SourceCapability) -> bool:
    return cap in SOURCE_CAPABILITIES.get(name, _DEFAULT_CAPS)


def sources_with_capability(
    cap: SourceCapability,
    candidate_sources: Optional[Iterable[str]] = None,
) -> list[str]:
    """返回具备某能力的源名列表（可选在 ``candidate_sources`` 范围内过滤）。

    用于「缺口补全只想试能补上缺口的源」这类查询。
    """
    if candidate_sources is not None:
        return [s for s in candidate_sources if has_capability(s, cap)]
    return [s for s, caps in SOURCE_CAPABILITIES.items() if cap in caps]


def prioritize_sources(
    order: list[str],
    missing_fields: Iterable[str],
) -> list[str]:
    """把一个源序按「能否补上缺失字段」重排（稳定排序，保留原层级）。

    这是「取代只按源序盲试」的核心原语：缺口补全时，把**能补上当前缺口**
    的源浮到前面，但同分（都行 / 都不行）时严格保持原顺序（主力序、素人序、
    日本源、辅助源的分层不被打乱）。

    - ``order``          ：原源序（通常来自 ``source_order_for(code)``）。
    - ``missing_fields`` ：缺失的 ScrapeResult 字段名（如 ``{"actors","plot"}``）。

    返回新列表（不修改入参）。缺失字段为空 ⇒ 原序返回（零开销）。
    """
    fields = list(missing_fields)
    if not fields:
        return list(order)

    # 缺失字段 → 需要的能力集合
    needed: set[SourceCapability] = {SourceCapability.from_field(f) for f in fields}

    # 每个源「能覆盖几个需要的能力」→ 分数越高越该往前
    def score(name: str) -> int:
        caps = SOURCE_CAPABILITIES.get(name, _DEFAULT_CAPS)
        return sum(1 for c in needed if c in caps)

    # 稳定排序：(-score, 原索引)。Python 的 sorted 是稳定排序，
    # 同分时按原列表顺序（即原索引）保留，正好保持分层。
    indexed = list(enumerate(order))
    indexed.sort(key=lambda item: (-score(item[1]), item[0]))
    return [name for _, name in indexed]


def source_order_for_fields(
    code: str,
    missing_fields: Iterable[str],
) -> list[str]:
    """ convenience：直接拿 ``source_order_for(code)`` 再按能力重排。

    ⚠️ 注意：``source_order_for`` 会触发 ``jp_fallback_order()``（可能探活
    日本代理），调用方若在意副作用请自己先算好 order 再调 ``prioritize_sources``。
    本函数仅作便捷包装。
    """
    from app.scraper.canon import source_order_for

    return prioritize_sources(
        list(source_order_for(code)),
        missing_fields,
    )
