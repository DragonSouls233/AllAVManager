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


# ============================================
# 正则表达式库
# ============================================

# 标准 JAV 番号: ABC-123, ABC-123Z
JAV_PATTERN = re.compile(r"[A-Z]{2,}-\d{2,}[Z]?", re.IGNORECASE)

# 素人番号: 259luxu-1456, SIRO-1234
AMATEUR_PATTERN = re.compile(r"\d{2,}[A-Z]{2,}-\d{2,}[A-Z]?", re.IGNORECASE)

# FC2 番号: FC2-123456, FC2PPV-123456
FC2_PATTERN = re.compile(r"FC2[-_]?(?:PPV[-_])?\d{5,}", re.IGNORECASE)

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

# 欧美站点: EvilAngel.20.01.01
WESTERN_PATTERN = re.compile(
    r"([A-Z][A-Za-z]+)\.(\d{2})\.(\d{2})\.(\d{2})",
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
]


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
    return result


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
            number = base
            # CHS/CHT/CH → 仅中字
            if suffix in ("CHS", "CHT", "CH"):
                is_chinese = True
                is_mosaic = None
            else:
                is_chinese = True if "C" in suffix else None
                is_mosaic = False if "U" in suffix else None
            # 方括号中字补充
            if is_chinese is None and bracket_chinese:
                is_chinese = True
            return NumberResult(
                number=number, original=filename, number_type=NumberType.JAV,
                confidence=0.90, is_chinese=is_chinese, is_mosaic=is_mosaic,
            )

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
            if suffix in ("CHS", "CHT", "CH"):
                is_chinese = True
                is_mosaic = None
            else:
                is_chinese = True if "C" in suffix else None
                is_mosaic = False if "U" in suffix else None
            if is_chinese is None and bracket_chinese:
                is_chinese = True
            return NumberResult(
                number=number, original=filename, number_type=NumberType.JAV,
                confidence=0.85, is_chinese=is_chinese, is_mosaic=is_mosaic,
            )

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

    # 先在原始文件名上尝试匹配带后缀的番号（传入 bracket_chinese）
    raw_suffix_result = _try_match_raw_with_suffix(filename, bracket_chinese)
    if raw_suffix_result:
        return raw_suffix_result

    # 再尝试直接在原始文件名上匹配（保留括号等结构）
    raw_result = _try_match_raw(filename)
    if raw_result:
        return _apply_suffix(raw_result, bracket_chinese)

    cleaned = clean_filename(filename, escape_strings)

    # 1. 无码数字番号: 111111-111
    if number := normalize_uncensored_digit_number(cleaned):
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.UNCENSORED, confidence=0.95), bracket_chinese)

    # 2. Mywife: Mywife No.1111
    if match := MYWIFE_PATTERN.search(cleaned):
        number = f"Mywife No.{match.group(1)}"
        return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.MYWIFE, prefix="MYWIFE", confidence=0.95), bracket_chinese)

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
        return result

    # MD-0165-1:带分集的 MD 番号(排除 MDVR)
    if "MDVR" not in cleaned.upper():
        if match := MD_PATTERN.search(cleaned):
            number = match.group(1).upper()
            return _apply_suffix(NumberResult(number=number, original=original, number_type=NumberType.JAV, confidence=0.85), bracket_chinese)

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


def _try_match_raw(filename: str) -> Optional[NumberResult]:
    """在原始文件名上尝试匹配（不经过 clean_filename 处理）"""
    # 去除扩展名
    name = os.path.splitext(filename)[0]

    # 尝试匹配标准 JAV（带横线），并处理括号
    # 从 [xxx] 或 (xxx) 中提取
    for pattern in [r"\[([A-Za-z]{2,}-\d{2,}[A-Za-z]?)\]", r"\(([A-Za-z]{2,}-\d{2,}[A-Za-z]?)\)"]:
        if match := re.search(pattern, name):
            return NumberResult(
                number=match.group(1).upper(),
                original=filename,
                number_type=NumberType.JAV,
                confidence=0.95,
            )

    return None


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

    return NumberType.UNKNOWN


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
