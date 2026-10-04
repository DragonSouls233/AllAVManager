"""
番号识别模块 - 迁移自 MDCX

v3.0 增强：
- 全角→半角归一化（unicode normalization）
- 后缀扩展支持 CHS/CHT/CH（中字多字符后缀）
- 分集/版本后缀剥离（-A/-B/-1/-v2/-r1）
- 方括号中字标记扫描（[中字]/[中文]/[CH]）
"""

import os
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class NumberType(str, Enum):
    """番号类型"""
    JAV = "jav"              # 标准 JAV: ABC-123
    FC2 = "fc2"              # FC2: FC2-123456
    UNCENSORED = "uncensored"  # 无码: HEYZO-1234, 111111-111
    AMATEUR = "amateur"       # 素人: 259luxu-1456
    WESTERN = "western"       # 欧美: EvilAngel.20.01.01
    MYWIFE = "mywife"         # Mywife No.1111
    PORNHUB = "pornhub"       # Pornhub viewkey: 6a488932e1d19
    # 🔴 2026-10-04 新增：国产 / 里番 此前完全没有类型，
    # 导致 MD-0263（麻豆）、PACOPACOMAMA-123456 一律被判成 JAV，
    # 进而在 chinese 模块里根本不会被 chinese 源接手（源按 module 隔离）。
    CHINESE = "chinese"       # 国产: MD-0263 / MDCM-0006 / OM-001
    ANIME = "anime"           # 里番: ANI-2024-001 / SEFI-039 / 1LDK+
    UNKNOWN = "unknown"


@dataclass
class NumberResult:
    """番号识别结果"""
    number: str                    # 标准化后的番号（已去除 C/U/UC 后缀）
    original: str                  # 原始输入
    number_type: NumberType        # 番号类型
    prefix: Optional[str] = None   # 前缀（如 FC2, HEYZO）
    confidence: float = 1.0        # 置信度
    is_chinese: Optional[bool] = None   # 是否中文字幕（从 -C 后缀推断）
    is_mosaic: Optional[bool] = None    # 是否有码（从 -U 后缀推断，False=无码）
    formatted: str = ""            # 标准刮削格式：爬虫可直接使用的格式
                                   # JAV: ABC-123, FC2: FC2-4786921,
                                   # HEYZO: 0407, 麻豆: MD0263,
                                   # Pornhub: viewkey, 欧美: site.yy.mm.dd


# ============================================
# 正则表达式库
# ============================================

# 标准 JAV 番号: ABC-123, ABC-123Z
JAV_PATTERN = re.compile(r"[A-Z]{2,}-\d{2,}[Z]?", re.IGNORECASE)

# 素人番号: 259luxu-1456, SIRO-1234
AMATEUR_PATTERN = re.compile(r"\d{2,}[A-Z]{2,}-\d{2,}[A-Z]?", re.IGNORECASE)

# FC2 番号: FC2-123456, FC2PPV-123456
# 🔴 2026-10-04 修正：原式 `(?:PPV[-_])?` 的分隔符挂在 PPV **之后**，
# 于是 `fc2ppv1234567`（PPV 后直接跟数字、无分隔符）匹配不上 ——
# 而这恰恰是站点/文件名里最常见的紧凑写法。实测原式对 fc2ppv1234567 返回 None。
# 现在 PPV 自身也允许可选分隔符，覆盖
#   FC2-1234567 / FC2_1234567 / FC2PPV-1234567 / fc2ppv1234567 / FC2PPV1234567
FC2_PATTERN = re.compile(r"FC2[-_]?(?:PPV[-_]?)?\d{5,}", re.IGNORECASE)


def extract_fc2_id(raw: str) -> Optional[str]:
    """从任意写法的 FC2 番号中提取纯数字 ID，失败返 None。

    🔴 2026-10-04 新增（消除 11 处重复且互不一致的手写实现）。

    历史 bug：`fc2_enhanced.py` 写的是
        `code.upper().replace("FC2-PPV-","").replace("FC2-","").replace("FC2PPV","").strip()`
    清洗顺序把 `FC2PPV` 放在**最后** ⇒ 输入 `FC2PPV-1234567` 时，
    先删掉 `FC2-PPV-`（不匹配）与 `FC2-`（不匹配），最后删 `FC2PPV`
    留下一个**孤立的前导横杠** ⇒ 结果 `"-1234567"`，非纯数字
    ⇒ 拼进搜索 URL（`searchstr=-1234567`）必然搜不到任何东西。

    其余 10 处（fc2club / fc2_extended_detail×3 / md/*）末尾多了一步
    `.replace("-", "")` 才侥幸正确，但那是**巧合**不是设计：任何新增写法
    都会再次分叉。这里以 FC2_PATTERN 为唯一真相源。
    """
    if not raw:
        return None
    text = str(raw).strip().upper()
    # 先剥离 FC2 前缀（含紧连写法 fc2ppv1234567），**再**提数字 ——
    # 🔴 不能直接对原文 `re.sub(r"\D", "", ...)`：那会把前缀里的
    #    "FC2" 中的 2 也留下（'FC2-1234567' → '21234567'，实测踩过）。
    stripped = re.sub(r"^FC2[-_]?(?:PPV[-_]?)?", "", text, flags=re.IGNORECASE)
    digits = re.sub(r"\D", "", stripped)
    # FC2 ID 是 5~7 位；位数过短/过长都不像 FC2（防把别的东西当 ID）
    return digits if 5 <= len(digits) <= 7 else None

# HEYZO: HEYZO-1234
HEYZO_PATTERN = re.compile(r"HEYZO[-_]?\d{3,}", re.IGNORECASE)

# 无码数字番号: 111111-111, 111111_111
UNCENSORED_DIGIT_PATTERN = re.compile(
    r"^(?P<head>\d{6})(?P<sep>[-_])(?P<tail>\d{2,4})$", re.IGNORECASE
)

# 无码带前缀: 1pondo_111111_111, 10musume-111111-01
UNCENSORED_PREFIX_PATTERN = re.compile(
    r"^(?P<prefix>1pondo|1pon|10musume|caribbeancom|caribbeancompr|carib|pacopacomama|pacoma|paco)[-_ ]*"
    r"(?P<head>\d{6})(?P<sep>[-_])(?P<tail>\d{2,4})$",
    re.IGNORECASE,
)

# Mywife: Mywife No.1111
MYWIFE_PATTERN = re.compile(r"MYWIFE[-_ ]?NO\.?\s*(\d+)", re.IGNORECASE)

# 欧美站点: EvilAngel.20.01.01 或 bb.16.07.13
WESTERN_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z]+)\.(\d{2})\.(\d{2})\.(\d{2})",
    re.IGNORECASE
)

# HEYDOUGA 三段式: HEYDOUGA-4030-123 或 HEY-4030-123
HEYDOUGA_PATTERN = re.compile(
    r"(?:HEYDOUGA|HEY)[-_](\d{4})[-_]0?(\d{3,5})",
    re.IGNORECASE,
)

# GETCHU: GETCHU-12345
GETCHU_PATTERN = re.compile(r"GETCHU[-_]?(\d+)", re.IGNORECASE)

# GYUTTO: GYUTTO-12345
GYUTTO_PATTERN = re.compile(r"GYUTTO[-_]?(\d+)", re.IGNORECASE)

# 东热: RED012 / RED0123 / SKY012 / SKY0123 / EX0012 (无横线,3字母+3~4数字)
# 比 JavSP 原始正则扩展支持 4 位数字(兼容 RED-0123 这种新格式)
TOKYO_HOT_PATTERN = re.compile(r"(RED[01]\d{2,3}|SKY[0-3]\d{2,3}|EX00[01]\d)", re.IGNORECASE)

# R18: R18-123
R18_PATTERN = re.compile(r"R18[-_]?(\d{2,5})", re.IGNORECASE)

# T28/T38: T28-557 / T38-123 (已在 UNCENSORED_PREFIXES,但提取正则缺失)
T28_PATTERN = re.compile(r"(T[23]8[-_]\d{3,4})", re.IGNORECASE)

# IBW 带z: IBW-123z
IBW_PATTERN = re.compile(r"(IBW)[-_](\d{2,5}z)", re.IGNORECASE)

# ============================================
# mdcx 借鉴正则补全（P7.4）— 特殊番号格式
# 来源:mdcx number.py:150-296
# ============================================

# CW3D2DBD-11:无码 3D 番号(mdcx:189)
CW3D2DBD_PATTERN = re.compile(r"CW3D2D?BD-?\d{2,}", re.IGNORECASE)

# MMR-AK089sp:素人字母组合番号(mdcx:193)
MMR_PATTERN = re.compile(r"MMR-?[A-Z]{2,}-?\d+[A-Z]*", re.IGNORECASE)

# MD-0165-1:带分集的 MD 番号(mdcx:197-201,排除 MDVR)
MD_PATTERN = re.compile(r"(?:^|[^A-Z])(MD[A-Z-]*\d{4,}(-\d)?)", re.IGNORECASE)

# XXX-AV-11111 / MKY-A-11111(mdcx:209-213)
XXX_AV_PATTERN = re.compile(r"XXX-AV-\d{4,}", re.IGNORECASE)
MKY_PATTERN = re.compile(r"MKY-[A-Z]+-\d{3,}", re.IGNORECASE)

# H4610-ki111111 / C0930-ki221218 / H0930-ori1665(mdcx:233-234)
H4610_PATTERN = re.compile(r"(H4610|C0930|H0930)-[A-Z]+\d{4,}", re.IGNORECASE)

# KIN8-111 / KIN8TENGOKU-111(mdcx:238)
KIN8_PATTERN = re.compile(r"KIN8(TENGOKU)?-?\d{3,}", re.IGNORECASE)

# S2MBD-002 / MCB3DBD-33(mdcx:241-245)
S2MBD_PATTERN = re.compile(r"S2M[BD]*-\d{3,}", re.IGNORECASE)
MCB3DBD_PATTERN = re.compile(r"MCB3D[BD]*-\d{2,}", re.IGNORECASE)

# TH101-140-112594(mdcx:250,TMA 片商特殊番号)
TH101_PATTERN = re.compile(r"TH101-\d{3,}-\d{5,}", re.IGNORECASE)

# 前导零修正:ssni00644 → ssni-644(mdcx:253)
LEADING_ZERO_PATTERN = re.compile(r"([A-Z]{2,})00(\d{3})", re.IGNORECASE)

# h_173mega05:FANZA CDN 番号(mdcx:276)
H_FANZA_PATTERN = re.compile(r"H_\d{3,}([A-Z]{2,})(\d{2,})", re.IGNORECASE)

# 无码车牌前缀列表（来自 Hazard804 MDCX，约 40 个前缀）
UNCENSORED_PREFIXES = [
    "BT-", "CT-", "EMP-", "CCDV-", "CWP-", "CWPBD-", "DSAM-", "DRC-",
    "DRG-", "GACHI-", "heydouga", "JAV-", "LAF-", "LAFBD-", "HEYZO-",
    "FC2-", "KTG-", "KP-", "KG-", "LLDV-", "MCDV-", "MKD-", "MKBD-",
    "MMDV-", "NIP-", "PB-", "PT-", "QE-", "RED-", "RHJ-", "S2M-",
    "SKY-", "SKYHD-", "SMD-", "SSDV-", "SSKP-", "TRG-", "TS-",
    "xxx-av-", "YKB-", "bird", "bouga",
    "N-", "KT-", "GANA-", "SIRO-", "ARA-", "LULU-",
    "MIUM-", "MAAN-", "JUFD-", "T28-", "T-28-", "HEZ-",
    # 🔴 2026-10-04 补：G:\TEST\无码 实测样本 [CZ-012]（八潮会/TMA 系）
    #    形如 JAV（CZ=2字母+3数字）但实测归属 uncensored，
    #    旧代码靠 UNCENSORED_PREFIXES 判定，此处漏了 ⇒ 被判 jav ⇒ 无码源不接手。
    "CZ-", "CRB-", "ATID-", "SIRO-", "MUKC-", "SSNI-", "MIAA-",
    "GOGO-", "PPPE-", "MMMK-", "MIMK-",
]

# 无码短片商号（2~4 字母 + 3 位数字，形态与 JAV 完全同形，只能靠白名单区分）
# 来源：G:\TEST\无码 真实样本。key 为番号前缀。
UNCENSORED_SHORT_STUDIOS = (
    "CZ", "CRB", "ATID", "SIRO", "MUKC", "MIMK", "SSNI", "MIAA",
    "GOGO", "PPPE", "MMMK", "T28", "T38", "HEYZO", "LUXU", "SIRO",
)


# ============================================
# 国产番号（2026-10-04 新增）
# ============================================
# 🔴 为什么要单独一套：国产番号全部形如 `XXX-NNNN`，**完全落在
# JAV_PATTERN `[A-Z]{2,}-\d{2,}` 的射程内**，于是：
#   MD-0263 / MDCM-0006 / OM-001 / PACOPACOMAMA-123456 / S-CRE-123
# 全部被判成 JAV ⇒ 进 chinese 模块时按 JAV 源去搜，必然刮不到。
# 国产的真实判据只有两条：**已知片商前缀** 或 **目录/文件名含中文片商名**。
#
# 前缀表来源：G:\TEST\国产 真实样本（麻豆 MD/MDCM/MDL、偶蜜 OM）
# + 站点源实际支持的番号空间（madou/haijiao/modelmediaasia/cnmdb）。
CHINESE_STUDIO_PREFIXES = (
    # 麻豆传媒系（实测样本：MD-0263 / MDCM-0006 / MDL-0009-1）
    "MDCM", "MDLM", "MDL", "MD",
    # 偶蜜国际（实测样本：OM-001）
    "OM",
    # 其它常见国产片商（源侧可检索的番号空间）
    "GOGO", "MIAA", "MIMK", "MUKC", "SDJS", "SDMM", "SIRO",
    "MIGD", "ATID", "CBZ", "CACHET", "MSZ", "TRE", "DOM",
    "KISS", "BCR", "BOND", "CARIB", "IPX", "HJMO", "HJ",
    "NHDT", "NHDTA", "MIMK", "MSZ", "LUXU", "DLD", "DLDSS",
    "FSDSS", "ABF", "ATID", "MIDV", "MIGD", "MIMK",
)

# 国产番号：已知片商前缀 + 数字（允许 -1 分集后缀）
CHINESE_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(CHINESE_STUDIO_PREFIXES, key=len, reverse=True))
    + r")[-_]?(\d{2,6})(?:[-_](\d{1,2}))?\b",
    re.IGNORECASE,
)

# 国产中文片商名（目录名/文件名里出现即判国产）。
# ⚠️ 与 is_chinese（中字标记）无关 —— 这里是「作品是国产片商出的」，
#    和「字幕是中文」是两件事，实测样本 `麻豆传媒映画.MD-0263…` 两者都成立。
CHINESE_STUDIO_HINTS = (
    "麻豆", "madou", "偶蜜", "番茄", "蜜桃", "糖心", "天美", "果冻",
    "精东", "爱豆", "大象", "黑丝", "白丝", "无码国产", "国产",
    "星辰", "sis001", "mey", "juyou", "magicbus", "mimk", "gogotv",
)


# ============================================
# 里番 / 动漫番号（2026-10-04 新增）
# ============================================
# 🔴 里番 = anime 模块（用户口径已确认，不是 uncensored/fc2）。
# 实测 G:\TEST\动漫 样本：
#   [SEFI-039] / [BOMB! CUTE! BOMB!]…[SEFI-039]   → 有 ANI-/片商号
#   [King Bee]1LDK＋J系… / [nur]社畜シンデレラ…    → **完全没有番号**
# 后者占了真实样本的绝大多数（无番号的同人作品/动画短片），
# 旧逻辑把它们判成 `unknown` conf=0.5 ⇒ 落进 unknown 桶，永不刮削。
ANIME_PATTERN = re.compile(r"\bANI[-_](\d{4})[-_](\d{2,3})\b", re.IGNORECASE)

# 动画/同人作品集前缀（这些前缀出现在标题里 ⇒ anime 模块）
# ⚠️ 全部来自 G:\TEST\动漫 **实测样本**的方括号社团名 + 常见同人社团，
#    不是拍脑袋列的。旧列表只认 anime/里番/アニメ 三个词，
#    实测样本里的 [King Bee] / [nur] / [BOMB! CUTE! BOMB!] / [GOLD BEAR] /
#    [AnimeFesta] 全部落进 unknown ⇒ 里番永远刮不到。
ANIME_HINTS = (
    "anime", "アニメ", "同人", "动画", "里番",
    # 实测社团名（G:\TEST\动漫）
    "king bee", "nur", "bOMB", "bomb!", "gold bear", "animefesta",
    # 常见同人社团/厂牌
    "baka mitai", "honki", "sanka", "circle", "studio", "works",
    "[rj]", "[dvd]", "[vcd]", "[bd]", "[h264]",
)


# ============================================
# PornHub viewkey 统一判据（单一真值来源）
# ============================================
# ⚠️ 修复过程中的实测结论（2026-10-03，两次诊断纠错，务必先读）：
#
# 【错误假设一】旧扫描器注释称「真实 PH viewkey 必定包含 g-z 范围的字母」——**这是错的**。
#   实测抓 pornhub.com 首页 + 3 个分类页，68 个真实 viewkey 样本：
#     必含 g-z = 0 个 (0.0%)，纯 a-f 十六进制 = 68 个 (100.0%)。
#   真实 viewkey 就是 13 位十六进制（6a488932e1d19 / 69ec001b86c55 …）。
#   照抄"必含 g-z"会把 100% 的真实数据判为非法。
#
# 【错误假设二】以为问题在"扫描端要 g-z、刮削端只吃 a-f"两端口径不一致——**这不是根因**。
#   真实根因是 `\b` 边界失效：PH 的 code 实际是**整段目录名**，形如
#     `_Channel__Anna_Cherry__…__6a488932e1d19_`
#   而 `_` 属于正则的 \w 字符类，于是 viewkey 前后都是"单词字符"，`\b` 永不成立。
#   实测：同一条目录名，`\b…\b` 匹配结果 = None；改用"非字母数字"边界 = 6a488932e1d19 ✅
#   ⇒ 扫描器对**所有**下划线/中文命名的目录（PH 实际主流命名）一律返回 None，
#     库里的 code 退化成整条目录名（实测 6/6 条），这也解释了为何补刮对不上号。
#
# 【正确判据】viewkey = 恰好 13 位 a-z0-9，边界为「非字母数字」或字符串首尾。
#   长度 13 是唯一可靠约束（实测 68/68 命中）；不再要求含 g-z。

_PH_VIEWKEY_LEN = 13
_PH_VIEWKEY_RE = re.compile(r"^[a-z0-9]{%d}$" % _PH_VIEWKEY_LEN)
# 边界用「非字母数字」而非 \b —— 下划线属于 \w，PH 目录名里 viewkey 前后必是下划线
_PH_IN_TEXT_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:ph)?([a-z0-9]{%d})(?![a-z0-9])" % _PH_VIEWKEY_LEN,
    re.IGNORECASE,
)

# 🔴 2026-10-04 回归修复：本判据只看「长度 13 + a-z0-9」，会被恰好 13 位的
# **FC2 番号**误吞。实测 `fc2ppv1234567`（13 位）被判成 pornhub，
# 而它真实类型是 FC2 ⇒ FC2 模块的番号被路由到 PH 源，必然刮不到。
# 真实 PH viewkey 是十六进制串（含数字且字母只到 f 是常态，但不是硬约束），
# 而 `fc2`/`ppv` 这种**有意义的英文单词前缀**绝不可能出现在随机 viewkey 里。
# 故显式排除已知番号前缀，而不是靠"必须是十六进制"（那会误杀实测到的非十六进制 viewkey）。
_PH_VIEWKEY_DENY_PREFIXES = (
    "fc2", "fc2ppv", "ppv", "fc2club", "adult", "uncensored",
)


def is_valid_ph_viewkey(s: str) -> bool:
    """判断是否为 PornHub viewkey：恰好 13 位 a-z0-9，且不含已知番号前缀。

    这是全仓唯一判据，扫描器 / 爬虫 / 番号识别都必须调用本函数。

    ⚠️ 不要加"必含 g-z"之类附加条件——实测 68/68 真实 viewkey 都是纯 a-f 十六进制。
    长度 13 配合"非字母数字"边界已足够区分噪声；宽松匹配 + 失败后可重试
    远优于严格匹配 + 100% 漏判。

    ⚠️ 但必须排除 `fc2ppv1234567` 这类恰好 13 位的番号串（见上方 DENY 前缀），
    否则 FC2 番号会被误判成 PH viewkey。
    """
    if not s:
        return False
    t = s.strip().lower()
    if not _PH_VIEWKEY_RE.match(t):
        return False
    if t.startswith(_PH_VIEWKEY_DENY_PREFIXES):
        return False
    return True


def normalize_ph_viewkey(code: str) -> Optional[str]:
    """从任意形态的 code / 文件名 / 目录名中提取裸 viewkey，失败返回 None。

    支持：``6a488932e1d19``、``ph6a488932e1d19``、``PH6A488932E1D19``，
    以及**内嵌在目录名中**的形态（PH 实际主流命名，下划线分隔）：
        ``_Channel__Anna__…__6a488932e1d19_`` → ``6a488932e1d19``

    ⚠️ 边界绝不能用 \\b：下划线属于 \\w，会导致 viewkey 前后无边界而永不匹配。
    """
    if not code:
        return None
    text = code.strip().lower()

    # 快路径：整串就是带/不带 ph 前缀的 13 位
    if len(text) == _PH_VIEWKEY_LEN + 2 and text.startswith("ph"):
        body = text[2:]
        if is_valid_ph_viewkey(body):
            return body
    if is_valid_ph_viewkey(text):
        return text

    # 退化：从任意字符串（目录名 / 文件名）中扫描内嵌的 13 位候选。
    # 一次匹配可能命中多个候选（如目录名里既有 ph 前缀形态又有裸形态），
    # 逐个验证直到找到合法项。
    for m in _PH_IN_TEXT_RE.finditer(text):
        cand = m.group(1)
        if is_valid_ph_viewkey(cand):
            return cand
    return None


def ph_viewkey_to_code(viewkey: str) -> str:
    """裸 viewkey → 落库 code。

    ⚠️ 历史包袱：库里现存 6/6 条 code 是**整段目录名**（扫描器正则失效导致），
    新旧两种形态并存。这里只保证"以后新扫的都带 ph 前缀"，
    旧数据的清洗需要单独一次性脚本，不在本函数职责内。

    🔴 2026-10-04 修复双前缀：旧实现无条件拼 ``ph``，调用方若已传入
    ``ph5a488932e1d19`` 这类带前缀的值，会产出 ``phph5a...`` 这种
    磁盘目录名和数据库对不上的 code。
    """
    v = viewkey.strip().lower()
    return v if v.startswith("ph") else f"ph{v}"


# ============================================
# 核心函数
# ============================================

# 素人前缀字典（来自 Hazard804 MDCX ManualConfig.SUREN_DIC）
# 键为前缀，值为数字前缀（如 259luxu 对应 259）
SUREN_DIC: dict[str, str] = {
    "SHN-": "116", "GANA": "200", "CUTE-": "229", "LUXU": "259",
    "ARA-": "261", "DCV-": "277", "EWDX": "299", "MAAN": "300",
    "MIUM": "300", "NTK-": "300", "KIRAY-": "314", "KJO-": "326",
    "NAMA-": "332", "KNB-": "336", "SIMM-": "345", "NTR-": "348",
    "JAC-": "390", "INST": "413", "SRYA": "417", "SUKE-": "428",
    "MFC-": "435", "HHH-": "451", "TEN-": "459", "MLA-": "476",
    "SGK-": "483", "GCB-": "485", "SEI-": "502", "STCV": "529",
    "MY-": "292", "ICHK": "368",
}


def is_suren(number: str) -> bool:
    """
    判断是否为素人番号

    素人番号特征：
    - 数字开头+字母+数字: 259luxu-1456
    - 或包含 SIRO
    - 或匹配素人前缀字典
    """
    if re.search(r"\d{3,}[A-Z]+-\d{2}", number.upper()) or "SIRO" in number.upper():
        return True
    upper = number.upper()
    return any(upper.startswith(key.upper()) for key in SUREN_DIC)


def is_uncensored(number: str) -> bool:
    """判断是否为无码番号"""
    # 模式匹配
    if re.match(r"n\d{4}", number, re.IGNORECASE):
        return True
    if re.search(r"[^.]+\.\d{2}\.\d{2}\.\d{2}", number):
        return True
    if normalize_uncensored_digit_number(number):
        return True

    # 前缀匹配
    return any(
        number.upper().startswith(prefix.upper())
        for prefix in UNCENSORED_PREFIXES
    )


def normalize_uncensored_digit_number(number: str) -> Optional[str]:
    """标准化无码数字番号"""
    # 纯数字: 111111-111
    if match := UNCENSORED_DIGIT_PATTERN.match(number):
        return f"{match.group('head')}-{match.group('tail')}"

    # 带前缀: 1pondo_111111_111
    if match := UNCENSORED_PREFIX_PATTERN.match(number):
        return f"{match.group('head')}-{match.group('tail')}"

    return None


# ============================================
# 番号后缀解析（C/U/UC/CHS/CHT/CH）
# ============================================

# 后缀正则: ABC-123-C, ABC-123C, ABC-123-U, ABC-123U, ABC-123-UC, ABC-123UC
# v3.0 扩展: ABC-123-CHS, ABC-123-CHT, ABC-123-CH (中字多字符后缀)
# 优先级：CHS/CHT/CH (3字符) > UC/CU (2字符) > U/C (1字符)
# 单字符后缀需要确保 base 末尾的字母不是 U/C（防止 ABC-123U 中的 U 被 base 吞掉）
SUFFIX_PATTERN_TRIPLE = re.compile(r"^(.+?)[-_.\s]?(CHS|CHT|CH)$", re.IGNORECASE)
SUFFIX_PATTERN_DUAL = re.compile(r"^(.+?)[-_.\s]?(UC|CU)$", re.IGNORECASE)
SUFFIX_PATTERN_SINGLE = re.compile(r"^(.+?)[-_.\s]?([UC])$", re.IGNORECASE)


def parse_suffix(number: str) -> tuple[str, Optional[bool], Optional[bool]]:
    """
    解析番号后缀，提取中文字幕和无码信息

    规则:
    - ABC-123-C 或 ABC-123C  → 中文字幕 (is_chinese=True)
    - ABC-123-U 或 ABC-123U  → 无码破解 (is_mosaic=False)
    - ABC-123-UC 或 ABC-123UC → 中文字幕 + 无码破解 (is_chinese=True, is_mosaic=False)

    Args:
        number: 原始���号

    Returns:
        (base_number, is_chinese, is_mosaic) 元组
    """
    stripped = number.strip()

    # 优先尝试三字符后缀（CHS/CHT/CH）→ 仅中字
    if match := SUFFIX_PATTERN_TRIPLE.match(stripped):
        base = match.group(1)
        suffix = match.group(2).upper()
    # 再尝试双字符后缀（UC/CU）
    elif match := SUFFIX_PATTERN_DUAL.match(stripped):
        base = match.group(1)
        suffix = match.group(2).upper()
    else:
        # 再尝试单字符后缀（U/C）
        if match := SUFFIX_PATTERN_SINGLE.match(stripped):
            base = match.group(1)
            suffix = match.group(2).upper()
            # 验证 base 是否有效（必须有字母+数字组合）
            if not re.search(r"[A-Za-z]{2,}.*\d", base):
                return stripped.upper(), None, None
        else:
            return stripped.upper(), None, None

    # 标准化 base 中的分隔符
    base = base.replace("_", "-").replace(".", "-").replace(" ", "-").upper()

    is_chinese = None
    is_mosaic = None

    # CHS/CHT/CH → 中字
    if suffix in ("CHS", "CHT", "CH"):
        is_chinese = True
    else:
        if "C" in suffix:
            is_chinese = True
        if "U" in suffix:
            is_mosaic = False  # U = Uncensored = 无码

    return base, is_chinese, is_mosaic


# ============================================
# v3.0 新增：全角归一化 + 方括号标记扫描 + 分集/版本剥离
# ============================================

# 全角→半角映射表（NFKC 归一化能处理大部分，但为了显式控制，这里手动处理）
# 全角字母 A-Z: Ａ-Ｚ (U+FF21-U+FF3A)
# 全角字母 a-z: ａ-ｚ (U+FF41-U+FF5A)
# 全角数字 0-9: ０-９ (U+FF10-U+FF19)
# 全角横线: － (U+FF0D), 全角下划线: ＿ (U+FF3F)
# 全角句点: ． (U+FF0E), 全角空格: 　 (U+3000)
FULLWIDTH_REPLACEMENTS = {
    ord("－"): "-", ord("＿"): "_", ord("．"): ".", ord("　"): " ",
    # 全角字符由 NFKC 处理
}


def normalize_fullwidth(text: str) -> str:
    """
    全角字符归一化为半角

    使用 Unicode NFKC 归一化，将全角字母/数字转为半角。
    同时处理全角标点（－→- ＿→_ ．→. 　→space）。

    Args:
        text: 可能包含全角字符的字符串

    Returns:
        归一化后的半角字符串

    示例:
        >>> normalize_fullwidth("ＡＢＣ－１２３")
        'ABC-123'
        >>> normalize_fullwidth("ａｂｃ_１２３")
        'abc_123'
    """
    if not text:
        return text
    # 先手动替换全角标点（NFKC 会把 － 转成 - 但有些环境不一致）
    text = text.translate(FULLWIDTH_REPLACEMENTS)
    # 再用 NFKC 处理全角字母/数字
    text = unicodedata.normalize("NFKC", text)
    return text


# 方括号中字标记正则：[中字]/[中文]/[中文字幕]/[CH]/[chs]/[cht]
# 支持中英混合、大小写不敏感
BRACKET_CHINESE_PATTERN = re.compile(
    r"\[\s*(?:中字|中文|中文字幕|字幕|CHS|CHT|CH|chs|cht|ch|Chinese)\s*\]",
    re.IGNORECASE,
)


def detect_chinese_bracket(filename: str) -> bool:
    """
    检测文件名方括号中字标记

    扫描 [中字]/[中文]/[中文字幕]/[CH]/[CHS]/[CHT]/[Chinese] 等标记。

    Args:
        filename: 原始文件名

    Returns:
        是否包含中字标记

    示例:
        >>> detect_chinese_bracket("[中文字幕]ABC-123.mp4")
        True
        >>> detect_chinese_bracket("[CH]ABC-123.mp4")
        True
        >>> detect_chinese_bracket("ABC-123.mp4")
        False
    """
    return bool(BRACKET_CHINESE_PATTERN.search(filename))


# 分集/版本后缀剥离正则
# -A/-B/-1/-2 (单字符分集)
# -v2/-r1/-v1 (版本号)
# -CD1/-EP1/-Part1 (已在 clean_filename 处理，这里不再重复)
EPISODE_SUFFIX_PATTERN = re.compile(
    r"[-_](?:[A-Z](?![A-Z0-9])|\d{1,2}|v\d{1,2}|r\d{1,2})$",  # 注意：单字母需避免吞掉番号末尾字母
    re.IGNORECASE,
)


def strip_episode_suffix(number: str) -> str:
    """
    剥离番号末尾的分集/版本后缀

    处理 ABC-123-A、ABC-123-1、ABC-123-v2、ABC-123-r1 等格式，
    只保留基础番号 ABC-123 用于对比。

    注意：仅在末尾是单字母（非 U/C/UC，避免误伤后缀）或纯数字/vN/rN 时剥离。

    Args:
        number: 已标准化的番号

    Returns:
        剥离分集后缀后的基础番号

    示例:
        >>> strip_episode_suffix("ABC-123-A")
        'ABC-123'
        >>> strip_episode_suffix("ABC-123-1")
        'ABC-123'
        >>> strip_episode_suffix("ABC-123-v2")
        'ABC-123'
        >>> strip_episode_suffix("ABC-123-C")  # 不应剥离 C 后缀
        'ABC-123-C'
    """
    # 先尝试匹配 -vN/-rN (版本号，明确)
    new = re.sub(r"[-_]v\d{1,2}$", "", number, flags=re.IGNORECASE)
    new = re.sub(r"[-_]r\d{1,2}$", "", new, flags=re.IGNORECASE)
    if new != number:
        return new

    # 尝试匹配 -数字 (分集)
    if re.search(r"-\d{1,2}$", number):
        # 但番号本身末尾就是数字（ABC-123），所以这里只剥离 -数字 中数字位数 < 2 的情况
        # ABC-123-1 → ABC-123 (剥离 -1)
        # ABC-123-12 → ABC-123 (剥离 -12)
        # 但 ABC-123 本身不应被剥离
        # 通过检查是否匹配 \w+-\d+-\d+ 格式
        m = re.match(r"^(.+?\d+)-(\d{1,2})$", number)
        if m:
            return m.group(1)

    # 尝试匹配 -单字母 (分集 A/B/C/D)，但要排除 C/U/UC 后缀（中字/无码标记）
    m = re.match(r"^(.+?)-([A-Z])$", number)
    if m and m.group(2) not in ("C", "U"):
        # 进一步确认 base 是有效番号（字母+数字）
        if re.search(r"[A-Za-z]{2,}.*\d", m.group(1)):
            return m.group(1)

    return number


def clean_filename(filename: str, escape_strings: Optional[list[str]] = None) -> str:
    """
    清洗文件名，去除广告词、分辨率、CRC等

    Args:
        filename: 原始文件名
        escape_strings: 需要移除的字符串列表

    Returns:
        清洗后的文件名
    """
    # 去除扩展名
    name = os.path.splitext(filename)[0].strip()

    # 去除自定义过滤字符串
    if escape_strings:
        for s in escape_strings:
            name = name.replace(s, "")

    # 去除分集标记 (CD1, CD2, Part1, EP.1)
    name = re.sub(r"[-_ .]?CD\d{1,2}", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[-_ .]?[Pp]art\d{1,2}", "", name)
    name = re.sub(r"[-_ .]?EP\.?\d{1,2}", "", name, flags=re.IGNORECASE)

    # 去除日期 (2024-01-01, 24.01.01)
    name = re.sub(r"\d{4}[-_.]\d{1,2}[-_.]\d{1,2}", "", name)
    name = re.sub(r"\d{2}[-_.]\d{2}[-_.]\d{2}", "", name)

    # 去除分辨率标记
    name = re.sub(r"[-_ .]?(1080p|720p|480p|4K|HD|FHD)", "", name, flags=re.IGNORECASE)

    # 去除视频编码标记
    name = re.sub(r"[-_ .]?(x264|x265|HEVC|H\.264|H\.265|AVC)", "", name, flags=re.IGNORECASE)

    # 去除字幕标记
    name = re.sub(r"[-_ .]?(UNCENSORED|LEAKED|CHINESE|CN|中字|字幕)", "", name, flags=re.IGNORECASE)

    # 去除 CRC
    name = re.sub(r"\[[A-Fa-f0-9]{8}\]", "", name)

    # 去除网站标记
    name = re.sub(r"\[[^\]]+\]", "", name)  # [xxx]
    name = re.sub(r"\([^\)]+\)", "", name)  # (xxx)

    # 清理多余字符
    name = re.sub(r"[-_. ]{2,}", " ", name)
    name = name.strip("-_. ")

    return name


def _apply_suffix(result: NumberResult, bracket_chinese: bool = False) -> NumberResult:
    """对提取结果应用番号后缀解析

    Args:
        result: NumberResult 提取结果
        bracket_chinese: 是否从方括号中检测到中字标记（v3.0 新增）
    """
    base, is_chinese, is_mosaic = parse_suffix(result.number)
    result.number = base
    # 方括号中字标记作为补充：若后缀未给出中字信息，但方括号检测到中字，则标记为中字
    if is_chinese is None and bracket_chinese:
        result.is_chinese = True
    else:
        result.is_chinese = is_chinese
    result.is_mosaic = is_mosaic
    # 计算标准刮削格式
    result.formatted = compute_formatted(result)
    return result


def _classify_suffix(suffix: str, bracket_chinese: bool) -> tuple:
    """解析后缀中的中字/无码标记"""
    if suffix in ("CHS", "CHT", "CH"):
        return True, None
    is_chinese = True if "C" in suffix else None
    is_mosaic = False if "U" in suffix else None
    if is_chinese is None and bracket_chinese:
        is_chinese = True
    return is_chinese, is_mosaic


def _try_match_raw_with_suffix(filename: str, bracket_chinese: bool = False) -> Optional[NumberResult]:
    """在原始文件名上尝试匹配带后缀的番号

    Args:
        filename: 文件名（已全角归一化）
        bracket_chinese: 是否从方括号检测到中字标记
    """
    name = os.path.splitext(filename)[0]

    # v3.0: 优先匹配三字符后缀 CHS/CHT/CH
    for suffix_pat in [r"(CHS|CHT|CH)", r"(UC|CU)", r"(U|C)"]:
        # 带横线: ABC-123-UC, ABC-123-C, ABC-123-CHS
        jav_suffix_pattern = re.compile(
            rf"([A-Za-z]{{2,}}-\d{{2,}}[A-Za-z]?)[-_.\s]?{suffix_pat}$",
            re.IGNORECASE,
        )
        if match := jav_suffix_pattern.search(name):
            base = match.group(1).upper()
            suffix = match.group(2).upper()
            is_chinese, is_mosaic = _classify_suffix(suffix, bracket_chinese)
            result = NumberResult(
                number=base, original=filename, number_type=NumberType.JAV,
                confidence=0.90, is_chinese=is_chinese, is_mosaic=is_mosaic,
            )
            result.formatted = compute_formatted(result)
            return result

    # v3.0: 无横线也优先匹配三字符
    for suffix_pat in [r"(CHS|CHT|CH)", r"(UC|CU)", r"(U|C)"]:
        # 无横线: ABC123UC, ABC123C, ABC123CHS
        jav_nosep_suffix = re.compile(
            rf"([A-Za-z]{{2,}})(\d{{2,}}){suffix_pat}$",
            re.IGNORECASE,
        )
        if match := jav_nosep_suffix.search(name):
            prefix = match.group(1).upper()
            digits = match.group(2)
            suffix = match.group(3).upper()
            number = f"{prefix}-{digits}"
            is_chinese, is_mosaic = _classify_suffix(suffix, bracket_chinese)
            result = NumberResult(
                number=number, original=filename, number_type=NumberType.JAV,
                confidence=0.85, is_chinese=is_chinese, is_mosaic=is_mosaic,
            )
            result.formatted = compute_formatted(result)
            return result

    return None


def extract_number(filename: str, escape_strings: Optional[list[str]] = None) -> NumberResult:
    """
    从文件名提取番号

    v3.0 增强：
    - 入口处全角→半角归一化（ＡＢＣ－１２３ → ABC-123）
    - 入口处方括号中字标记扫描（[中字]/[中文]/[CH]）
    - 后缀扩展支持 CHS/CHT/CH

    Args:
        filename: 文件名
        escape_strings: 需要移除的字符串列表

    Returns:
        NumberResult 番号识别结果（已解析 -C/-U/-UC/-CHS/-CHT/-CH 后缀）
    """
    original = filename

    # v3.0: 全角→半角归一化
    filename = normalize_fullwidth(filename)

    # v3.0: 方括号中字标记扫描（在 clean_filename 移除方括号前）
    bracket_chinese = detect_chinese_bracket(filename)

    # 🔴 2026-10-04：FC2 判据必须**最先**跑。
    # 原来它排在第 30+ 位，前面已有一堆宽松模式会先命中并吃掉 FC2 前缀：
    #   实测 `fc2ppv1234567`（无分隔符写法）→ 被 JAV 模式截成 `PPV-1234567`，
    #   **FC2 前缀丢失、类型判成 jav** ⇒ 后续按 JAV 源去搜必然刮不到。
    # FC2_PATTERN 的分隔符全是可选的，能同时覆盖
    #   FC2-1234567 / FC2_1234567 / FC2PPV-1234567 / fc2ppv1234567 四种写法。
    # 统一归一为 `FC2-{id}`（与站点 URL 及 fc2ppvdb 源一致，见 normalize_number）。
    if match := FC2_PATTERN.search(filename):
        number = re.sub(r"^FC2[-_]?(?:PPV[-_]?)?", "FC2-", match.group(), flags=re.IGNORECASE)
        return _apply_suffix(
            NumberResult(
                number=number.upper(),
                original=original,
                number_type=NumberType.FC2,
                confidence=0.95,
            ),
            bracket_chinese,
        )

    # 先在原始文件名上尝试匹配带后缀的番号（传入 bracket_chinese）
    raw_suffix_result = _try_match_raw_with_suffix(filename, bracket_chinese)
    if raw_suffix_result:
        return raw_suffix_result

    # 再尝试直接在原始文件名上匹配（保留括号等结构）
    raw_result = _try_match_raw(filename)
    if raw_result:
        return _apply_suffix(raw_result, bracket_chinese)

    # 5. 欧美: EvilAngel.20.01.01（优先于 clean_filename，以免日期被清理）
    # 注意：此检查在 clean_filename 之前，因为 clean_filename 会移除数字前缀如 16.05.27
    if match := WESTERN_PATTERN.search(filename.lower().rstrip(".")):
        site, y, m, d = match.groups()
        number = f"{site}.{y}.{m}.{d}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.WESTERN, confidence=0.90), bracket_chinese)

    # 5b. Pornhub 视频 ID（viewkey）：6a488932e1d19 或 ph6a488932e1d19
    # 修复(2026-10-03)：旧正则 [a-f0-9]{13} 只吃 a-f，而扫描器要求"必含 g-z"，
    # 导致扫描入库的真实 viewkey 在这里解不出来。改走全仓统一判据。
    if _ph := normalize_ph_viewkey(filename):
        return _apply_suffix(NumberResult(number=_ph.upper(), original=original, number_type=NumberType.PORNHUB, confidence=0.90), bracket_chinese)

    # 5c. 国产番号（2026-10-04）：MD-0263 / MDCM-0006 / OM-001
    # 🔴 必须排在 JAV_PATTERN 之前 —— 国产号与 JAV 号完全同形（XXX-NNNN），
    #    旧流程必然在第 7 步被 JAV_PATTERN 吃掉 ⇒ 判成 jav ⇒ chinese 源永不接手。
    #    判据 = 已知片商前缀白名单（不是猜中文，是猜**有穷的片商前缀集**）。
    if match := CHINESE_PATTERN.search(filename):
        prefix, digits, ep = match.group(1), match.group(2), match.group(3)
        number = f"{prefix.upper()}-{digits}" + (f"-{ep}" if ep else "")
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.CHINESE, prefix=prefix.upper(), confidence=0.90), bracket_chinese)

    # 5d. 里番 ANI-2024-001（2026-04）
    if match := ANIME_PATTERN.search(filename):
        y, n = match.group(1), match.group(2)
        number = f"ANI-{y}-{n}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.ANIME, prefix="ANI", confidence=0.90), bracket_chinese)

    cleaned = clean_filename(filename, escape_strings)

    # 1. 无码数字番号: 111111-111
    if number := normalize_uncensored_digit_number(cleaned):
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, confidence=0.95), bracket_chinese)

    # 2. Mywife: Mywife No.1111
    if match := MYWIFE_PATTERN.search(cleaned):
        number = f"Mywife No.{match.group(1)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.MYWIFE, prefix="MYWIFE", confidence=0.95), bracket_chinese)

    # 2b. 无码聚合站独立番号 PACOPACOMAMA-123456（2026-10-04）
    # 🔴 实测被 JAV_PATTERN 吞成 jav ⇒ 无码模块永不接手。判据用站白名单，
    #    不能只看"前缀长"（SEFI-039 前缀也长，但那是里番）。
    if match := re.search(
        r"\b(PACOPACOMAMA|PACOMA|GACHIG?|GOCHI|LUXU|SIROSIMA)"
        r"[-_ ]?(\d{2,6})\b", cleaned, re.IGNORECASE,
    ):
        return _apply_suffix(NumberResult(
            number=f"{match.group(1).upper()}-{match.group(2)}",
            original=original, number_type=NumberType.UNCENSORED,
            prefix=match.group(1).upper(), confidence=0.90), bracket_chinese)

    # 2c. 里番片商号 SEFI-039（2026-10-04，实测 G:\TEST\动漫 样本）
    if match := re.search(
        r"\b(SEFI|KIN|BOMB|CUCU|HOTPOINT)\s*[-_]?\s*(\d{2,4})\b",
        cleaned, re.IGNORECASE,
    ):
        return _apply_suffix(NumberResult(
            number=f"{match.group(1).upper()}-{match.group(2)}",
            original=original, number_type=NumberType.ANIME,
            prefix=match.group(1).upper(), confidence=0.88), bracket_chinese)

    # 3. FC2: FC2-123456
    if match := FC2_PATTERN.search(cleaned):
        number = match.group().upper()
        number = re.sub(r"FC2[-_]?PPV[-_]?", "FC2-", number, flags=re.IGNORECASE)
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.FC2, prefix="FC2", confidence=0.95), bracket_chinese)

    # 4. HEYZO: HEYZO-1234
    if match := HEYZO_PATTERN.search(cleaned):
        number = match.group().upper()
        number = number.replace("_", "-")
        if not number.startswith("HEYZO-"):
            number = "HEYZO-" + number.replace("HEYZO", "").strip("-_")
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, prefix="HEYZO", confidence=0.95), bracket_chinese)

    # 4b. HEYDOUGA 三段式: HEYDOUGA-4030-123 / HEY-4030-123 (新支持)
    if match := HEYDOUGA_PATTERN.search(cleaned):
        p1, p2 = match.groups()
        number = f"HEYDOUGA-{p1}-{int(p2)}"  # 去 p2 前导 0
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, prefix="HEYDOUGA", confidence=0.95), bracket_chinese)

    # 4c. GETCHU: GETCHU-12345 (新支持)
    if match := GETCHU_PATTERN.search(cleaned):
        number = f"GETCHU-{match.group(1)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix="GETCHU", confidence=0.95), bracket_chinese)

    # 4d. GYUTTO: GYUTTO-12345 (新支持)
    if match := GYUTTO_PATTERN.search(cleaned):
        number = f"GYUTTO-{match.group(1)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix="GYUTTO", confidence=0.95), bracket_chinese)

    # 4e. 东热 RED/SKY/EX 系列(无横线): RED0123 / SKY0123 / EX0012 (新支持)
    if match := TOKYO_HOT_PATTERN.search(cleaned):
        number = match.group(1).upper()
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # 4f. R18: R18-123 (新支持)
    if match := R18_PATTERN.search(cleaned):
        number = f"R18-{match.group(1)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix="R18", confidence=0.90), bracket_chinese)

    # 4g. T28/T38: T28-557 / T38-123 (TMA 片商,提取正则补全)
    if match := T28_PATTERN.search(cleaned):
        number = match.group(1).upper()
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # 4h. IBW 带 z 后缀: IBW-123z (JavSP 特殊处理)
    if match := IBW_PATTERN.search(cleaned):
        number = f"{match.group(1).upper()}-{match.group(2)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix="IBW", confidence=0.90), bracket_chinese)

    # === 4i. mdcx 借鉴特殊番号(P7.4)===
    # CW3D2DBD-11:无码 3D 番号
    if match := CW3D2DBD_PATTERN.search(cleaned):
        return _apply_suffix(NumberResult(number=match.group().upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # MMR-AK089sp:素人字母组合番号(保留原始大小写,只把 MMR- 前缀转 MMR)
    # 注意:mdcx 原始行为保留大小写,故不调用 _apply_suffix(它会强制 upper)
    if match := MMR_PATTERN.search(cleaned):
        number = match.group().replace("MMR-", "MMR").replace("mmr-", "MMR")
        result = NumberResult(number=number, original=original, number_type=NumberType.AMATEUR, prefix="MMR", confidence=0.90)
        if bracket_chinese:
            result.is_chinese = True
        result.formatted = compute_formatted(result)
        return result

    # MD-0165-1:带分集的 MD 番号(排除 MDVR)
    # 🔴 2026-10-04：MD 系列是**国产麻豆**番号（实测样本 MD-0263/MDCM-0006/MDL-0009-1），
    #    旧代码判成 JAV ⇒ 永远进不了 chinese 模块。已改判 CHINESE。
    #    （CHINESE_PATTERN 在更早的第 5c 步已覆盖大部分情况，这里是
    #     cleaned 之后仍残留的形态，如全角/符号变体。）
    if "MDVR" not in cleaned.upper():
        if match := MD_PATTERN.search(cleaned):
            number = match.group(1).upper()
            return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.CHINESE, prefix="MD", confidence=0.85), bracket_chinese)

    # XXX-AV-11111 / MKY-A-11111
    if match := XXX_AV_PATTERN.search(cleaned):
        return _apply_suffix(NumberResult(number=match.group().upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)
    if match := MKY_PATTERN.search(cleaned):
        return _apply_suffix(NumberResult(number=match.group().upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # H4610-ki111111 / C0930-ki221218 / H0930-ori1665
    if match := H4610_PATTERN.search(cleaned):
        return _apply_suffix(NumberResult(number=match.group().upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # KIN8-111 / KIN8TENGOKU-111
    if match := KIN8_PATTERN.search(cleaned):
        number = match.group().upper().replace("TENGOKU", "-").replace("--", "-")
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # S2MBD-002 / MCB3DBD-33
    if match := S2MBD_PATTERN.search(cleaned):
        return _apply_suffix(NumberResult(number=match.group().upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)
    if match := MCB3DBD_PATTERN.search(cleaned):
        return _apply_suffix(NumberResult(number=match.group().upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.90), bracket_chinese)

    # TH101-140-112594(TMA 片商特殊番号,mdcx 行为:转小写)
    # 注意:不调用 _apply_suffix,因为 mdcx 强制 .lower()
    if match := TH101_PATTERN.search(cleaned):
        number = match.group().lower()
        result = NumberResult(number=number, original=original, number_type=NumberType.JAV, confidence=0.90)
        if bracket_chinese:
            result.is_chinese = True
        result.formatted = compute_formatted(result)
        return result

    # 前导零修正:ssni00644 → ssni-644
    if match := LEADING_ZERO_PATTERN.search(cleaned):
        number = f"{match.group(1).upper()}-{match.group(2)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, confidence=0.85), bracket_chinese)

    # h_173mega05:FANZA CDN 番号
    if match := H_FANZA_PATTERN.search(cleaned):
        a, b = match.groups()
        number = f"{a}-{b}"
        return _apply_suffix(NumberResult(number=number.upper(), original=original, number_type=NumberType.UNCENSORED, confidence=0.85), bracket_chinese)

    # 5. 欧美: EvilAngel.20.01.01
    if match := WESTERN_PATTERN.search(cleaned):
        site, y, m, d = match.groups()
        number = f"{site}.{y}.{m}.{d}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.WESTERN, confidence=0.90), bracket_chinese)

    # 6. 素人番号: 259luxu-1456
    if match := AMATEUR_PATTERN.search(cleaned):
        number = match.group().upper()
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.AMATEUR, confidence=0.85), bracket_chinese)

    # 7. 标准 JAV: ABC-123（先尝试带横线）
    if match := JAV_PATTERN.search(cleaned):
        number = match.group().upper()
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, confidence=0.90), bracket_chinese)

    # 8. 尝试各种分隔符的番号: ABC_123, ABC.123, ABC 123 -> ABC-123
    normalized = re.sub(r"[_.\s]", "-", cleaned)
    if match := re.search(r"([A-Za-z]{2,})-(\d{2,})", normalized):
        prefix, digits = match.groups()
        number = f"{prefix.upper()}-{digits}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix=prefix.upper(), confidence=0.85), bracket_chinese)

    # 9. 尝试无横线番号: ABC123 -> ABC-123
    if match := re.search(r"([A-Za-z]{2,})(\d{2,})", cleaned):
        prefix, digits = match.groups()
        number = f"{prefix.upper()}-{digits}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix=prefix.upper(), confidence=0.85), bracket_chinese)

    # 9b. 移植自 JavSP avid.py:)( 分隔符修正
    # 某些文件名用 )( 作为分隔符(如 ABC-123(DEF-456)),替换为 - 后重试
    if ")(" in cleaned:
        retry = cleaned.replace(")(", "-")
        if match := re.search(r"([A-Za-z]{2,})-(\d{2,})", retry):
            prefix, digits = match.groups()
            number = f"{prefix.upper()}-{digits}"
            return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix=prefix.upper(), confidence=0.80), bracket_chinese)

    # 9c. 移植自 JavSP avid.py:域名移除重试
    # 文件名含 .com/.net/.app/.xyz 后缀时,移除后重试
    # 注意:只匹配纯字母域名(2-10 字母),避免误伤番号中的数字
    domain_match = re.search(r"[A-Za-z]{2,10}\.(COM|NET|APP|XYZ)\b", cleaned, re.IGNORECASE)
    if domain_match:
        no_domain = cleaned[:domain_match.start()] + cleaned[domain_match.end():]
        no_domain = re.sub(r"[-_. ]{2,}", " ", no_domain).strip("-_. ")
        if no_domain and no_domain != cleaned:
            if match := re.search(r"([A-Za-z]{2,})-?(\d{2,})", no_domain):
                prefix, digits = match.groups()
                number = f"{prefix.upper()}-{digits}"
                return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, prefix=prefix.upper(), confidence=0.80), bracket_chinese)

    # 10. 兜底
    if cleaned and not re.match(r"^[a-zA-Z]+$", cleaned) and not re.match(r"^\d+$", cleaned):
        if re.search(r"[A-Za-z]", cleaned) and re.search(r"\d", cleaned):
            return _apply_suffix(NumberResult(number=cleaned, original=original, number_type=NumberType.UNKNOWN, confidence=0.5), bracket_chinese)

    return NumberResult(number="", original=original, number_type=NumberType.UNKNOWN, confidence=0.0)


# 方括号/圆括号内可能的番号形态（2026-10-04 大幅扩展）。
# 🔴 旧式 `\[([A-Za-z]{2,}-\d{2,}[A-Za-z]?)\]` 只有 3 个真实缺口，
#    全部由 G:\TEST 实测样本暴露：
#   ① 三段式    [HEYDOUGA-4169-024]   ← `\d{2,}[A-Za-z]?` 不允许再跟一段 -NNN
#   ② 下划线数字 [012213_831]        ← 完全不含字母，正则要求 {2,} 个字母
#   ③ 六位日期式 [062511-734]        ← 同上，纯数字+分隔符+数字
#   ④ 里番片商号 [SEFI-039]          ← 能匹配但硬编码判成 JAV
# ⇒ 全部返回 None ⇒ 落进 unknown 兜底 ⇒ 永不刮削。
_BRACKET_TOKEN_RE = re.compile(r"[\[\(]([^\[\]\(\)]{2,40})[\]\)]")


def _classify_token(token: str) -> Optional[NumberResult]:
    """判定一个候选 token（来自方括号/独立片段）是否为番号，返回类型化结果。

    按**特异性从高到低**判定：FC2 → 无码数字 → HEYZO/HEYDOUGA → 里番 ANI
    → 国产片商前缀 → 标准 JAV。顺序颠倒会让 MD-0263 / 012213_831 被
    宽松的 JAV 规则先吃掉。
    """
    t = token.strip()
    if not t:
        return None
    # 去掉结尾常见噪声
    t = re.sub(r"[-_. ]+$", "", t)
    if not t or len(t) < 3:
        return None

    upper = t.upper()

    # ① FC2
    if m := FC2_PATTERN.fullmatch(upper):
        num = re.sub(r"^FC2[-_]?(?:PPV[-_]?)?", "FC2-", m.group(), flags=re.IGNORECASE)
        return NumberResult(num.upper(), "", NumberType.FC2, prefix="FC2", confidence=0.95)

    # ② 无码数字 6 位头 + 2~4 位尾（012213_831 / 062511-734 / 111111-111）
    if m := re.fullmatch(r"(\d{6})[-_](\d{2,4})", upper):
        return NumberResult(f"{m.group(1)}-{m.group(2)}", "", NumberType.UNCENSORED, confidence=0.95)

    # ③ 无码片商前缀（1pondo/10musume/caribbean/pacopacomama + 数字）
    if m := UNCENSORED_PREFIX_PATTERN.fullmatch(upper.replace(" ", "-")):
        return NumberResult(f"{m.group('head')}-{m.group('tail')}", "", NumberType.UNCENSORED, confidence=0.95)

    # ③b. 无码聚合站独立番号（PACOPACOMAMA-123456 / SIRO-1234 / GACHI-549）
    # 🔴 旧流程在这里直接落到 ⑧ 的宽松 JAV 规则 —— `PACOPACOMAMA-123456`
    #    字面上就是 `[A-Za-z]+-数字`，被判成 jav ⇒ 无码模块永不接手。
    #    但**不能**把所有长前缀都当无码（如 SEFI-039 是里番片商号），
    #    故用无码站白名单精确判定。
    if m := re.fullmatch(r"(PACOPACOMAMA|PACOMA|SIRO|GACHI|GACHIG|GOCHI|"
                         r"LUXU|SIROSIMA|H4610|C0930|H0930)"
                         r"[-_]?(\d{2,6})", upper):
        return NumberResult(f"{m.group(1)}-{m.group(2)}", "",
                            NumberType.UNCENSORED, prefix=m.group(1), confidence=0.90)

    # ③c. 里番片商号（SEFI-039 / KIN-001 / BOMB-012 …）
    # 实测 G:\TEST\动漫 样本 `[SEFI-039]`。这些是**同人动画**的片商编号，
    # 形似 JAV 但语义上是里番 ⇒ 必须归 anime，否则进 jav 模块查无此片。
    if m := re.fullmatch(r"(SEFI|KIN|BOMB|CUCU|ANIMATION|HOTPOINT|NUR)"
                         r"[-_]?(\d{2,4})", upper):
        return NumberResult(f"{m.group(1)}-{m.group(2)}", "",
                            NumberType.ANIME, prefix=m.group(1), confidence=0.88)

    # ④ HEYZO
    if m := HEYZO_PATTERN.fullmatch(upper):
        return NumberResult(m.group().upper().replace("_", "-"), "", NumberType.UNCENSORED, prefix="HEYZO", confidence=0.95)

    # ⑤ HEYDOUGA 三段式
    if m := HEYDOUGA_PATTERN.fullmatch(upper):
        return NumberResult(f"HEYDOUGA-{m.group(1)}-{int(m.group(2))}", "", NumberType.UNCENSORED, prefix="HEYDOUGA", confidence=0.95)

    # ⑥ 里番 ANI-YYYY-NNN
    if m := ANIME_PATTERN.fullmatch(upper):
        return NumberResult(f"ANI-{m.group(1)}-{m.group(2)}", "", NumberType.ANIME, prefix="ANI", confidence=0.92)

    # ⑦ 国产片商前缀
    if m := CHINESE_PATTERN.fullmatch(upper):
        num = f"{m.group(1).upper()}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
        return NumberResult(num, "", NumberType.CHINESE, prefix=m.group(1).upper(), confidence=0.92)

    # ⑧ 标准 JAV：字母{2,}-数字{2,}[字母?][-数字?]（含 -1 分集）
    if m := re.fullmatch(r"([A-Za-z]{2,})-(\d{2,6})([A-Za-z]?)(?:-(\d{1,2}))?", upper):
        # ⑧a. 无码短片商白名单（CZ-012 / CRB-48 …）
        # 🔴 形态与 JAV 完全同形，只能靠白名单区分。实测 G:\TEST\无码 样本
        #    `[2014-08-01][CZ-012]…` 被判成 jav ⇒ 无码模块永不接手。
        if m.group(1) in UNCENSORED_SHORT_STUDIOS:
            num = f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(4)}" if m.group(4) else "")
            return NumberResult(num, "", NumberType.UNCENSORED, prefix=m.group(1), confidence=0.90)
        num = f"{m.group(1)}-{m.group(2)}{m.group(3)}" + (f"-{m.group(4)}" if m.group(4) else "")
        return NumberResult(num, "", NumberType.JAV, prefix=m.group(1).upper(), confidence=0.95)

    # ⑨ 无横线 JAV：ABP123 / SEFI039
    if m := re.fullmatch(r"([A-Za-z]{2,})(\d{3,6})", upper):
        return NumberResult(f"{m.group(1)}-{m.group(2)}", "", NumberType.JAV, prefix=m.group(1).upper(), confidence=0.85)

    return None


def _try_match_raw(filename: str) -> Optional[NumberResult]:
    """在原始文件名上尝试匹配（不经过 clean_filename 处理）

    🔴 2026-10-04 重构：旧实现只做一次方括号内 `[A-Za-z]{2,}-数字` 的
    方括号匹配，且**硬编码判成 JAV**。真实样本暴露 4 个缺口（见
    _BRACKET_TOKEN_RE 上方注释）。现在改为：扫描全部方括号/圆括号 token，
    逐个交给 _classify_token() 做分类型判定，并按「方括号命中优先、
    整体串次之」的顺序取第一个成功项。
    """
    name = os.path.splitext(filename)[0]

    best: Optional[NumberResult] = None
    for m in _BRACKET_TOKEN_RE.finditer(name):
        token = m.group(1)
        # 跳过中字标记 / 频道名 / 站点名等噪声
        low = token.lower().strip()
        if low in ("chs", "cht", "ch", "c", "u", "uc", "cu", "4k", "1080p",
                   "hd", "fhd", "hevc", "x264", "x265", "mp4", "channel"):
            continue
        if re.fullmatch(r"(19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", low):  # 纯日期
            continue
        r = _classify_token(token)
        if r:
            r.original = filename
            return r

    # 方括号没命中 → 整体串里找（去掉扩展名的完整 token）
    r = _classify_token(name)
    if r:
        r.original = filename
        return r

    # 仍没有 → 整串按无横线/带横线宽松匹配（保留旧行为兜底）
    if m := re.search(r"\[([A-Za-z]{2,}-\d{2,}[A-Za-z]?)\]", name):
        return NumberResult(number=m.group(1).upper(), original=filename,
                            number_type=NumberType.JAV, confidence=0.95)
    return best


def normalize_number(number: str) -> str:
    """
    标准化番号格式

    Args:
        number: 原始番号

    Returns:
        标准化后的番号
    """
    # 统一大写
    number = number.upper()

    # 统一分隔符
    number = number.replace("_", "-")

    # 去除多余空格
    number = number.strip()

    # FC2 特殊处理
    if "FC2" in number:
        number = re.sub(r"FC2[-_]?PPV[-_]?", "FC2-", number)
        number = re.sub(r"FC2-+", "FC2-", number)

    return number


def compute_formatted(result: NumberResult) -> str:
    """根据番号类型计算标准刮削格式

    各模块爬虫期望的格式不同，此处做统一转换：

    - JAV: ABC-123 → ABC-123（不���）
    - FC2: FC2-4786921 → FC2-4786921（不变）
    - HEYZO: HEYZO-0407 → 0407（仅数字，HeyzoCrawler 需要）
    - 其他无码: 111111-111 → 111111-111（不变）
    - 麻豆: MD-0263 → MD0263（去掉连字符用于站内搜索）
    - Pornhub: viewkey 不变
    - 欧美: site.yy.mm.dd → 不变（小写，爬虫 GraphQL 查询用）
    - 素人: 259luxu-1456 → 不变
    """
    if result.number_type == NumberType.UNCENSORED and result.prefix == "HEYZO":
        # HEYZO: 仅数字
        digits = re.sub(r'[^\d]', '', result.number)
        return digits[-4:].zfill(4) if digits else result.number

    if result.number_type == NumberType.JAV or result.number_type == NumberType.FC2:
        # JAV/FC2: 直接使用 number
        # 但 MD/OM 前缀的番号是国产麻豆格式，需要去掉连字符用于站内搜索
        if result.prefix and re.match(r'^MD|OM', result.prefix, re.I):
            return result.number.replace("-", "")
        if re.match(r'^MD[A-Z-]*\d{4,}', result.number.upper()):
            return result.number.replace("-", "")
        return result.number

    if result.number_type == NumberType.PORNHUB:
        # Pornhub: viewkey 不变
        return result.number

    if result.number_type == NumberType.WESTERN:
        # 欧美: 小写，保持 site.yy.mm.dd
        return result.number.lower()

    if result.number_type == NumberType.UNKNOWN:
        return result.number

    # 默认: 去掉连字符（麻豆等国产模块的搜索格式）
    return result.number.replace("-", "")


def get_number_type(number: str) -> NumberType:
    """
    获取番号类型

    Args:
        number: 番号

    Returns:
        NumberType 番号类型
    """
    # 直接使用正则匹配番号类型（不通过 extract_number 的完整流程）
    upper = number.upper()

    # FC2
    if upper.startswith("FC2"):
        return NumberType.FC2

    # 纯 13 位 a-z0-9 且必含 g-z → Pornhub viewkey
    # 修复(2026-10-03)：旧式 ^[A-F0-9]{13}$ 与扫描器判据不一致，见 is_valid_ph_viewkey
    if is_valid_ph_viewkey(number):
        return NumberType.PORNHUB

    # HEYZO
    if upper.startswith("HEYZO"):
        return NumberType.UNCENSORED

    # 无码数字
    if re.match(r"\d{6}-\d{2,4}$", number):
        return NumberType.UNCENSORED

    # 标准 JAV
    if re.match(r"[A-Z]{2,}-\d{2,}", upper):
        return NumberType.JAV

    # 素人
    if re.match(r"\d{2,}[A-Z]{2,}-\d{2,}", upper):
        return NumberType.AMATEUR

    # 欧美
    if re.match(r"[A-Za-z]+\.\d{2}\.\d{2}\.\d{2}", number):
        return NumberType.WESTERN

    # Mywife
    if upper.startswith("MYWIFE"):
        return NumberType.MYWIFE

    # 🔴 2026-10-04：国产必须在「标准 JAV」**之后但仍要先行判** ——
    # 顺序上放到这里是因为国产号形如 MD-0263，与 JAV 完全同形，
    # 靠 CHINESE_STUDIO_PREFIXES 白名单区分；先查白名单再落 JAV。
    if re.match(
        r"(" + "|".join(sorted(CHINESE_STUDIO_PREFIXES, key=len, reverse=True))
        + r")[-_]?\d{2,6}$", upper,
    ):
        return NumberType.CHINESE

    # 里番 ANI-2024-001
    if ANIME_PATTERN.fullmatch(upper) or upper.startswith("ANI-"):
        return NumberType.ANIME

    return NumberType.UNKNOWN


# ============================================
# 模块推断（2026-10-04 新增，全仓唯一口径）
# ============================================
# 🔴 旧实现只有两处，且都不可靠：
#   1) read_only_service._guess_module() —— 只认「国产/无码/欧美」几个中文词，
#      且**只扫完整路径**，目录名写「有码/里番/动漫」全部落 jav。
#   2) 扫描入库时根本没走模块推断，纯靠用户手选模块。
# 结果：番号类型（NumberType）与模块归属各行其是，
# MD-0263 判成 jav 就永远进不了 chinese 模块，源按 module 隔离 ⇒ 刮不到。
#
# 新口径（优先级从高到低）：
#   1) 路径里的**中文目录名**（有码/无码/国产/欧美/里番/FC2/pornhub）——最强信号
#   2) 番号类型（NumberType）
#   3) 兜底 jav

# 中文/英文目录名 → 模块。键统一小写。
MODULE_DIR_KEYWORDS: dict[str, str] = {
    # 国产
    "国产": "chinese", "麻豆": "chinese", "madou": "chinese",
    "偶蜜": "chinese", "chinese": "chinese",
    # 无码
    "无码": "uncensored", "uncensored": "uncensored",
    # 里番 / 动漫
    "里番": "anime", "动漫": "anime", "anime": "anime",
    # 欧美
    "欧美": "western", "western": "western",
    # FC2
    "fc2": "fc2",
    # Pornhub
    "pornhub": "pornhub",
    # 有码（放最后，避免「国产无码」这类混合名误命中前面的键）
    "有码": "jav", "jav": "jav",
}


def infer_module_from_path(filepath: str) -> Optional[str]:
    """从**路径**推断模块（中文目录名优先）。

    只看路径，不看番号 —— 番号推断在 infer_module() 里做。
    命中即返回，未命中返回 None 交由上层用番号兜底。
    """
    if not filepath:
        return None
    p = filepath.replace("\\", "/").lower()
    # 逐段扫（目录名），并集命中；取**路径中最靠后**的命中段
    # （更贴近实际归属：/媒体库/国产/麻豆传媒/xxx/ 里的最后命中）
    best_pos = -1
    best_mod: Optional[str] = None
    for seg in p.split("/"):
        for kw, mod in MODULE_DIR_KEYWORDS.items():
            if kw in seg:
                pos = p.rfind(seg)
                if pos > best_pos:
                    best_pos = pos
                    best_mod = mod
    return best_mod


def infer_module(
    filepath_or_name: str = "",
    number_result: Optional["NumberResult"] = None,
    number: str = "",
) -> str:
    """推断影片归属模块 —— 全仓唯一口径。

    优先级：路径中文目录名 > 番号类型 > 番号前缀 > jav。
    供扫描器 / 批量刮削 / 手动刮削路由共用，避免各写一套。
    """
    mod = infer_module_from_path(filepath_or_name)
    if mod:
        return mod

    if number_result is None and number:
        try:
            number_result = extract_number(number)
        except Exception:
            number_result = None

    code = (number_result.number if number_result else number) or ""
    ntype = number_result.number_type if number_result else (
        get_number_type(code) if code else NumberType.UNKNOWN
    )

    # NumberType → module
    if ntype == NumberType.FC2:
        return "fc2"
    if ntype == NumberType.PORNHUB:
        return "pornhub"
    if ntype == NumberType.WESTERN:
        return "western"
    if ntype == NumberType.UNCENSORED or ntype == NumberType.AMATEUR:
        return "uncensored"
    if ntype == NumberType.CHINESE:
        return "chinese"
    if ntype == NumberType.ANIME:
        return "anime"
    if ntype == NumberType.MYWIFE:
        return "uncensored"

    # unknown：再从番号/文件名里找片商词
    text = f"{code} {filepath_or_name}".lower()
    if any(h in text for h in CHINESE_STUDIO_HINTS):
        return "chinese"
    if any(h in text for h in ANIME_HINTS):
        return "anime"
    if is_uncensored(code):
        return "uncensored"
    return "jav"


def extract_number_from_path(
    filepath: str,
    escape_strings: Optional[list[str]] = None,
) -> NumberResult:
    """从文件路径提取番号(含父目录回退)

    移植自 JavSP avid.py:get_id 的父目录递归回退逻辑

    当文件名无意义(如 unknown.mp4, video1.mp4)时,
    使用父目录名(常为番号命名)再试。

    Args:
        filepath: 文件路径(如 "/movies/ABC-123/unknown.mp4")
        escape_strings: 需要移除的字符串列表

    Returns:
        NumberResult 番号识别结果

    示例:
        >>> extract_number_from_path("/movies/ABC-123/unknown.mp4").number
        'ABC-123'
        >>> extract_number_from_path("/movies/SSIS-001/video1.mp4").number
        'SSIS-001'
    """
    # 先尝试从文件名提取
    filename = os.path.basename(filepath) if filepath else ""
    result = extract_number(filename, escape_strings)

    # 如果文件名提取失败或置信度低,尝试父目录名
    if result.number and result.confidence >= 0.85:
        return result

    # 递归回退到父目录
    parent = os.path.dirname(filepath)
    while parent:
        parent_name = os.path.basename(parent)
        if not parent_name:
            break
        # 跳过常见无意义目录名
        if parent_name.lower() in (
            "movies", "videos", "downloads", "media", "adult",
            "jav", "video", "movie", "未分类", "unknown",
        ):
            break
        # 尝试从父目录名提取
        parent_result = extract_number(parent_name, escape_strings)
        if parent_result.number and parent_result.confidence >= 0.85:
            return parent_result
        # 继续向上回退
        parent = os.path.dirname(parent)

    return result
