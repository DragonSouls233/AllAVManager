"""Canonicalisation helpers: code aliases + studio/series name normalisation.

Two related problems, both observed on the real server data:

1. Code aliases — the same movie is written differently across sites:
      300MIUM-1437 (real)  vs  MIUM-1437 (dropped leading digits)
      200GANA-3426 (real)  vs  GANA-3426
   A query with the short form can hit a DIFFERENT movie, so every code we store
   or search must expand to its known variants.

2. Studio/series name variants — the same maker appears as many spellings, which
   makes grouping useless:
      マドンナ(258) / マドンナ(Madonna)(188) / Madonna(147)   -> Madonna
      ムーディーズ(271) / MOODYZ(453)                          -> MOODYZ
      プレステージ(153) / プレステージプレミアム(229)           -> PRESTIGE
"""
from __future__ import annotations

import os
import re
import time
from typing import Iterable

# --------------------------------------------------------------------------
# 1) code aliases
# --------------------------------------------------------------------------

# Heads that are known 素人 (amateur) labels. Only these get prefix expansion —
# expanding `ABP-123` into 33 fake codes would just be 33 wasted requests.
AMATEUR_HEADS = frozenset({
    "MIUM", "MAAN", "GANA", "LUXU", "JAC", "NTR", "KNB", "TEN", "PPZ", "OMG",
    "INON", "STH", "MFCS", "ARA", "STCV", "PAK", "DCV", "HMDNV", "ENDX",
    "SRTD", "SIMM", "SDHS", "ORECO", "FTHT", "MMKA", "SSCJ", "OERO",
    "REFUCK", "GESY", "DDHP", "EROFV", "PIZ", "LADY", "SIKA", "MGFX", "ID",
})

# Leading numeric prefixes actually observed on the server's 469 repaired rows.
AMATEUR_PREFIXES = (
    "200", "259", "261", "277", "285", "300", "318", "324", "326", "328",
    "336", "345", "348", "390", "406", "413", "420", "435", "459", "483",
    "494", "498", "521", "529", "546", "563", "739", "752", "758", "761",
    "857", "892",
)

_TAIL_RE = re.compile(r"^(\d*[A-Z]{2,})-(\d{2,})$")
_PREFIX3_RE = re.compile(r"^(\d{3})([A-Z]{2,})$")


def split_code(code: str) -> tuple[str | None, str, str]:
    """Split a code into (leading-digit-prefix, head, tail).

    `300MIUM-1437` -> ('300', 'MIUM', '1437')
    `MIUM-1437`    -> (None,   'MIUM', '1437')
    `ABP-123`      -> (None,   'ABP',  '123')
    """
    m = _TAIL_RE.match((code or "").strip().upper())
    if not m:
        return None, "", ""
    head, tail = m.group(1), m.group(2)
    p = _PREFIX3_RE.match(head)
    if p:
        return p.group(1), p.group(2), tail
    return None, head, tail


def code_aliases(code: str) -> list[str]:
    """Return every known spelling of `code`, canonical form first.

    `300MIUM-1437` -> ['300MIUM-1437', 'MIUM-1437']
    `MIUM-1437`    -> ['MIUM-1437', '200MIUM-1437', '300MIUM-1437', ...]

    The canonical form is the one WITH the leading digits (what the sites use);
    the short form is kept so we can still match rows imported before the fix.
    """
    if not code:
        return []
    c = code.strip().upper()
    out = [c]

    prefix, head, tail = split_code(c)
    if not head:
        return out
    if prefix:
        bare = "%s-%s" % (head, tail)
        if bare not in out:
            out.append(bare)
        return out

    # bare form -> propose the known prefixes, but ONLY for known 素人 labels
    if head not in AMATEUR_HEADS:
        return out
    for p in AMATEUR_PREFIXES:
        cand = "%s%s-%s" % (p, head, tail)
        if cand not in out:
            out.append(cand)
    return out


def is_amateur_code(code: str) -> bool:
    """True when the code carries a 素人 numeric prefix (e.g. 200GANA-3426)."""
    prefix, _head, _tail = split_code(code)
    return prefix is not None


# --------------------------------------------------------------------------
# 1b) code-shaped tokens that must never be treated as person names
# --------------------------------------------------------------------------

#: Bare maker heads observed as `actors.name` on the live server (2026-10-05).
#: These are label codes, not people: NTK 12 movies, NTR 10, MAAN 10, URE 10,
#: PAKO 9, DCV 2, INSTV/MIRD/NAMH/LULU/CEMD/BLK 0-1, plus the 素人 labels
#: AIKA 186, AYA 126, RARA 44, KANBi 13, DOC 12, 259LUXU 3.
#: Data-driven alternative: any token that is also a code head in `movies.code`.
#: This set is the fallback for callers without DB access.
CODE_LIKE_HEADS: frozenset[str] = frozenset({
    "NTK", "NTR", "MAAN", "URE", "PAKO", "DCV", "INSTV", "MIRD", "NAMH",
    "LULU", "CEMD", "BLK", "AIKA", "AYA", "RARA", "KANBI", "DOC", "VERONICA",
    "LUXU", "GANA", "MIUM", "JAC", "SIRO", "S-CUTE", "MIDE", "ABP", "SSIS",
    "MIMK", "JUFE", "SONE", "PRED", "MIDV", "EKDV", "MIAB", "NPJS", "MFCW",
    "FSDSS", "ARBK", "MKMP", "JUQD", "MSFD", "SORA", "ROE", "MEYD", "DLDSS",
    "NSFS", "GDHH", "HMN", "DSW", "BAB", "CHD", "JUQ", "MSZ",
})

#: JavDB avatar-path fragments. `<thumb>https://…/avatars/xv/xvDYV.jpg</thumb>`
#: got split on `/` and the 2-char path segments became "actors".
_URL_FRAGMENT_RE = re.compile(r"^(?:https?|avatars?|[a-z]{2}\d[a-z0-9]*|"
                              r"index|thumb|actor|art|image|img)s?$", re.I)


def is_code_like_token(name: str | None) -> bool:
    """True when `name` is a code / label token rather than a person's name.

    Catches the three shapes seen polluting `actors`:
      * bare maker head            `NTK` `AIKA` `259LUXU`
      * head + tail glued together `390JAC` `200GANA`
      * URL path fragment          `xv` `gm` `my` (JavDB avatar paths)
    """
    n = (name or "").strip()
    if not n:
        return True
    if _URL_FRAGMENT_RE.match(n):
        return True
    up = n.upper()
    if up in CODE_LIKE_HEADS:
        return True
    if up in AMATEUR_HEADS:
        return True
    # 2 字符拉丁 token：JavDB 头像 URL 路径碎片（avatars/xv/xvDYV.jpg）实测就是
    # 这种形态。纯汉字 2 字可能是艺名（如「葵」），故只拦拉丁。
    if len(n) <= 2 and re.match(r"^[A-Za-z0-9]+$", n):
        return True
    # 200GANA / 390JAC / 259LUXU — numeric prefix + head, no tail
    if re.match(r"^\d{2,3}[A-Z]{2,}$", up):
        return True
    # head-tail or head_tail with no personal-name characters
    if re.match(r"^[A-Z]{2,6}[-_]\d{2,4}$", up):
        return True
    return False


# --------------------------------------------------------------------------
# 3) per-kind source strategy
# --------------------------------------------------------------------------

# 素人 (amateur) and mainstream (有码大厂) need DIFFERENT source orders.
#
# Measured on the real library (see engine.py's tiering comment, 40-code sample):
#   javbus  25/40 overall but **0/5 on 素人** (GANA/LUXU/MIUM) -> useless for 素人
#   javmenu 40/40, **素人 5/5**  -> the best 素人 source
#   javdb (official App API) hits both, and is the richest field-wise
# So for 素人 we try javmenu/javmost first (they actually carry 素人 entries)
# and only then fall back to the mainstream order.
AMATEUR_SOURCE_ORDER = ("javmenu", "javmost", "javdb", "javbus")
MAINSTREAM_SOURCE_ORDER = ("javdb", "javmenu", "javmost", "javbus")

#: 辅助源（主力 + 日本源都试过仍未给全时才用）。
#:
#: 🔴 2026-10-05 用户决定：**thejavdb 降为辅助源，排在 DMM 之后**。
#: 依据（两条都指向同一结论）：
#:   1. 覆盖率：40 番号实测 thejavdb 仅 26/40 命中，作为首选命中率偏低；
#:   2. 数据源性质：`thejavdb` 是第三方开放 API（api.thejavdb.net），
#:      而 DMM 是 FANZA 官方 GraphQL（`api.video.dmm.co.jp`），真实番号 6/6 命中。
#:      官方源的字段权威性天然高于第三方聚合站，且已经打通，不需要为了「快」
#:      把第三方源排在官方源前面。
#: 保留它在辅助池首位（命中即字段全，avgW 4.0）而不是删掉：它仍是有效的
#: 补字段手段，只是**不该**先于 DMM 尝试。
#:
#: ⚠️ 命名陷阱见 engine.py 的分层注释：`thejavdb` ≠ JavDB 官方 API（那是 `javdb`）。
AUX_SOURCE_ORDER = ("thejavdb", "avmoo", "javbooks", "freejavbt")

# --------------------------------------------------------------------------
# 3b) 日本专属源（FANZA / DMM）—— 2026-10-05 实测结论
# --------------------------------------------------------------------------
# 前提事实：FANZA/DMM 对**海外 IP 地区封锁**。实测走原代理（美国出口）
# 拿到的永远是「年齢認証 - FANZA」空壳页（len=28361，零字段）；换日本出口后
# 首页/年龄认证页正常（len=507749 / title=FANZA 日本最大級のアダルトポータル），
# **日本链路本身是通的**。
#
# 🔴 2026-10-05 二次实测（推翻上一轮「0 命中」结论）：**DMM 数据已打通**。
# 上一轮只试了静态 HTML 与两个已废弃端点，漏掉了真正的现行入口。
# 现在确认可用的是官方 GraphQL：`https://api.video.dmm.co.jp/graphql`
# （从 assets.video.dmm.co.jp 的 Next.js chunk 里挖出来的，chunk 13662 模块
#  直接写死了这个域名）。
#
# 三个决定性事实（全部实测）：
#   1. **静态 HTML 确实没数据**（len=28361，`__NEXT_DATA__` 计数 0）—— 上轮没错。
#   2. 但 `api.fanza.xyz` DNS 失效、`api.dmm.com` **域名活着但全站 404**
#      （`/graphql` 也返回 `{"result":{"status":404,"message":"NOT FOUND"}}`）
#      —— 这两个才是真正废掉的，上轮把它们当成「DMM 整体不可用」的证据是错的。
#   3. `api.video.dmm.co.jp/graphql` 对真实番号 **4/4 命中**
#      （MIDE-980 / SSIS-001 / ATID-705 / MIDE-20），虚构番号 ABC-123 正确返回
#      null ⇒ 不是假阳性。字段齐：标题/演员/厂牌/系列/标签/时长/发行日/评分/
#      封面/10 张剧照/预告片，且封面与剧照实测可下载（JPEG 魔数 ffd8ff）。
#
# 番号→id 规则：`ABC-123` → `abc00123`（前缀小写 + 数字零填充 5 位）。
#
# ⚠️ 2026-10-05 用户决定：**DMM 已加入主力源序**（默认生效，无需环境变量）。
# 数据本身早已实测可用（见上），真正的顾虑是成本 —— 日本免费节点单部 ~70s。
# 因此在 engine 侧做了两处配套约束，使其「进主力但几乎不拖慢」：
#   1. `engine.JP_TAIL_CRAWLERS` 把 `dmm_web` 标为**固定尾部源**，
#      不参与 `_rotate_primary` 的按番号轮换 ⇒ 不会成为任何一部片的首选。
#   2. 排在前面的 javdb/javmenu/javmost/javbus 命中即返回，走不到 DMM；
#      只有前 4 个全未给出「标题+封面+演员」完整结果时，才付这 ~70s。
# 要临时关掉（排障/节点不稳时）：设 MDCX_JP_SOURCE_IN_ORDER=0
JP_SOURCE_ORDER: tuple[str, ...] = ("dmm_web",)

#: `jp_sources_available()` 的结果缓存秒数。
#: 🔴 必要性：`get_jp_proxy_url()` 在链路未起时会**同步拉起 xray 并 sleep 2.5s**，
#: 而本函数在 `source_order_for()`（排序热路径，同步）里被调用。缓存两个作用：
#:   1. 避免每部片子都付一次端口探活 + 可能 2.5s 的同步启动（阻塞事件循环）。
#:   2. 节点失效时不会对每个番号反复尝试重启。
_JP_AVAIL_TTL = 60.0
_jp_avail_cache: tuple[float, bool] | None = None


def jp_sources_available(force: bool = False) -> bool:
    """日本出口当前是否可用（不可用就别把日本源排进序里，白白浪费请求）。

    结果默认缓存 ``_JP_AVAIL_TTL`` 秒；``force=True`` 强制重探。
    """
    global _jp_avail_cache
    if not force and _jp_avail_cache is not None:
        ts, val = _jp_avail_cache
        if (time.time() - ts) < _JP_AVAIL_TTL:
            return val
    try:
        from app.services.jp_proxy import get_jp_proxy_url
        val = bool(get_jp_proxy_url())
    except Exception:  # noqa: BLE001
        val = False
    _jp_avail_cache = (time.time(), val)
    return val


def jp_fallback_order() -> tuple[str, ...]:
    """日本源在源序里的实际位置。

    🔴 2026-10-05 起**默认追加**（用户决定加入主力），出口不可用时自动落空 ——
    宁可少一个源，也不要让整条链路因日本节点起不来而失败。
    设 ``MDCX_JP_SOURCE_IN_ORDER=0`` 可显式关闭。
    """
    flag = os.environ.get("MDCX_JP_SOURCE_IN_ORDER", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return ()
    return JP_SOURCE_ORDER if jp_sources_available() else ()


def source_order_for(code: str, include_aux: bool = True) -> tuple[str, ...]:
    """Return the crawler names to try, in order, for this code.

    素人 and mainstream titles live in different places, so a single global
    order wastes requests (or misses entirely) on one of the two kinds.

    完整结构（2026-10-05 用户决定 **DMM 优先于 thejavdb**）：

        主力（有码）  javdb → javmenu → javmost → javbus
        主力（素人）  javmenu → javmost → javdb → javbus
        日本官方源    dmm_web        ← 排在 thejavdb **之前**
        辅助源        thejavdb → avmoo → javbooks → freejavbt

    日本源由 ``jp_fallback_order()`` 追加，出口不可用时自动落空 ——
    宁可少一个源，也不要让整条链路因日本节点起不来而失败。
    设 ``MDCX_JP_SOURCE_IN_ORDER=0`` 可显式关闭。

    ``include_aux=False`` 时只返回主力 + 日本源（供已自带辅助池的调用方，
    如 engine 的分层执行，避免把辅助源重复算进主力池）。
    """
    order = AMATEUR_SOURCE_ORDER if is_amateur_code(code) else MAINSTREAM_SOURCE_ORDER
    order = order + jp_fallback_order()
    if not include_aux:
        return order
    return order + tuple(s for s in AUX_SOURCE_ORDER if s not in order)


# --------------------------------------------------------------------------
# 2) studio / series name normalisation
# --------------------------------------------------------------------------

# Explicit alias table: variant -> canonical. Order matters (longest first at
# lookup time). Keys are compared after normalisation (lower, no spaces).
STUDIO_ALIASES: dict[str, str] = {
    # Madonna
    "マドンナ(madonna)": "Madonna",
    "マドンナ": "Madonna",
    "madonna": "Madonna",
    # MOODYZ
    "ムーディーズ": "MOODYZ",
    "moodyz": "MOODYZ",
    "moodyz diva": "MOODYZ DIVA",
    "ムーディーズ diva": "MOODYZ DIVA",
    "moodyzdiva": "MOODYZ DIVA",
    # Moodyz kana/kanji variants seen in the wild
    "ムーディーズdiva": "MOODYZ DIVA",
    # PRESTIGE
    "プレステージプレミアム(prestige premium)": "PRESTIGE",
    "プレステージプレミアム": "PRESTIGE",
    "プレステージ": "PRESTIGE",
    "prestige premium": "PRESTIGE",
    "prestigepremium": "PRESTIGE",
    "prestige": "PRESTIGE",
    # S1
    "s1 no.1 style": "S1 NO.1 STYLE",
    "s1no.1style": "S1 NO.1 STYLE",
    "エスワン ナンバーワンスタイル": "S1 NO.1 STYLE",
    "エスワンナンバーワンスタイル": "S1 NO.1 STYLE",
    # Idea Pocket
    "idea pocket": "IDEA POCKET",
    "ideapocket": "IDEA POCKET",
    "アイデアポケット": "IDEA POCKET",
    # SOD
    "sod create": "SOD",
    "sodクリエイト": "SOD",
    "sodcreate": "SOD",
    # Attackers
    "アタック捐赠": "Attackers",
    "attackers": "Attackers",
    # others seen in the top-20 list
    "faleno": "FALENO",
    "dls": "DLS",
    "ダスッ！": "DLS",
    "ダスッ": "DLS",
    "dasu": "DLS",
    "sod": "SOD",
}

def _norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def normalize_studio(name: str | None) -> str | None:
    """Map a studio/series variant to its canonical spelling."""
    if not name:
        return None
    raw = name.strip()
    if not raw:
        return None
    key = _norm_key(raw)
    if not key:
        return None
    if key in STUDIO_ALIASES:
        return STUDIO_ALIASES[key]
    # try removing a trailing parenthesised gloss: "X (Y)" -> "X"
    stripped = re.sub(r"\s*[（(].*?[)）]\s*$", "", raw).strip()
    if stripped and _norm_key(stripped) in STUDIO_ALIASES:
        return STUDIO_ALIASES[_norm_key(stripped)]
    return raw


def looks_like_plot_not_series(name: str | None) -> bool:
    """True when a `series` value is really a plot sentence.

    Measured on the server's 3785 non-empty series values:
      len  0-10: 1430   len 11-15:  844
      len 16-20:  556   len 21-25:  346
      len 26-30:  234   len 31-40:  212   len 41+: 163
    Real series names sit in the short buckets (`S1 NO.1STYLE`, `DAHLIAデビュー`,
    `マジ軟派、初撮。`, `満足度満点ソープ`), while synopses dominate >25.
    So: >25 chars => plot. Punctuation alone is NOT a signal, because genuine
    series names also contain 「、」 and 「。」.
    """
    if not name:
        return True
    s = name.strip()
    if not s:
        return True
    if len(s) > 25:
        return True
    # Long English sentences are always synopses even when under the limit.
    if re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}\s+[A-Za-z]{4,}", s):
        return True
    # Japanese synopses in the 15-25 char band: they are dominated by particles
    # (が/の/に/を/て/で/と) and read as a clause. Real series names are noun
    # phrases and have far fewer particles relative to their length.
    # e.g. 「時短営業で暇になったバイト先の後輩が「逆痴●」 (21 chars, 6 particles)
    if re.search(r"[がのにてをでとがの]", s):
        particles = len(re.findall(r"[がのにてをでと]", s))
        if particles >= 3 and len(s) >= 14:
            return True
    return False


def build_series_index(movies: Iterable[tuple[str, str | None, str | None]]
                       ) -> dict[str, list[str]]:
    """Group codes by canonical series/studio.

    `movies` yields (code, series, studio). Only usable series values are kept
    (plot blurbs are dropped), and a code is indexed under the series first,
    then the studio, so lookups succeed even when one of the two is missing.
    """
    idx: dict[str, list[str]] = {}
    for code, series, studio in movies:
        s_ok = None if looks_like_plot_not_series(series) else normalize_studio(series)
        st = normalize_studio(studio)
        for key in (s_ok, st):
            if key:
                idx.setdefault(key, []).append(code)
    return idx
