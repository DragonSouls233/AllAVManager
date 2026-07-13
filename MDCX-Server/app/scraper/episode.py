"""
分集识别模块 - 移植自 mdcx/core/file.py

识别文件名中的分集信息(cd_part)、中字标记(c_word)、
破解版(leak)、无码(wuma)、有码(youma)等元信息。

mdcx 原始逻辑:
1. 预处理:移除 VOL/CASE/NO/CWP/CWPBD/ACT 系列编号
2. 四种分集识别模式:
   - cd_path_1: 显式 CD/Part/HD 标记 (如 -cd1, _part2, .hd3)
   - cd_path_2: 末尾数字 (如 -1, -12)
   - cd_path_3: 末尾字母 a-o (如 -a, -b,排除 c 中字)
   - cd_path_4: 中间单数字 (如 -1-, -1_)
3. -C/-U 区分:-C 默认为中字标记,不作为分集

移植来源:
- mdcx/core/file.py:354-483 (cd_part 识别)
- mdcx/config/models.py:543 (cnword_char 默认值)
- mdcx/core/file.py:584-595 (中字关键词检测)
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ============================================
# 常量
# ============================================

# 中字标记关键词(来自 mdcx config.cnword_char 默认值 + 扩展)
# mdcx 默认: ["-C.", "-C-", "ch.", "字幕"]
CHINESE_SUB_KEYWORDS: list[str] = [
    "-C.", "-C-", "-C ",  # -C 后缀(带分隔符)
    "ch.", "ch-", "CH.", "CH-",  # ch 缩写
    "CHS", "CHT", "CH", "chs", "cht",  # 三字符/双字符中字
    "字幕", "中字", "中文", "中文字幕",  # 中文标记
    "chinese", "Chinese", "CHINESE",  # 英文标记
]

# 无码标记关键词
UNCENSORED_KEYWORDS: list[str] = [
    "无码", "無碼", "无修正", "無修正",
    "uncensored", "Uncensored", "UNCENSORED",
    "UnCensor",  # JavSP detect_special_attr 兼容
]

# 有码标记关键词
CENSORED_KEYWORDS: list[str] = [
    "有码", "有碼",
]

# 流出/破解标记关键词
LEAK_KEYWORDS: list[str] = [
    "流出", "破解",
    "leaked", "Leaked", "LEAKED",
]

# 马赛克破坏版标记
DESTROYED_KEYWORDS: list[str] = [
    "马赛克破坏", "马赛克破壞",
    "mosaic destroy", "Mosaic Destroy", "MOSAIC DESTROY",
    "破壞", "破坏",
]

# 排除字幕词(防止误判)
NOT_SUB_KEYWORDS: list[str] = [
    "無字幕", "无字幕", "no subtitle", "No Subtitle",
]

# 系列编号前缀(预处理时移除,避免误识别为分集)
SERIES_NUMBER_PATTERN = re.compile(
    r"(vol|case|no|cwp|cwpbd|act)[-\.]?\d+",
    re.IGNORECASE,
)


# ============================================
# 分集识别正则(移植自 mdcx/core/file.py:427-432)
# ============================================

# 模式 1: 显式 CD/Part/HD 标记 (如 -cd1, _part2, .hd3)
CD_PATTERN_EXPLICIT = re.compile(
    r"[-_ .]{1}(cd|part|hd)([0-9]{1,2})",
    re.IGNORECASE,
)

# 模式 2: 末尾数字 (如 -1, -12)
CD_PATTERN_END_DIGIT = re.compile(
    r"-([0-9]{1,2})\.?$",
    re.IGNORECASE,
)

# 模式 3: 末尾字母 a-o (如 -a, -b,排除 c 中字)
CD_PATTERN_END_LETTER = re.compile(
    r"(-|\d{2,}|\.)([a-o]{1})\.?$",
    re.IGNORECASE,
)

# 模式 4: 中间单数字 (如 -1-, -1_)
CD_PATTERN_MIDDLE_DIGIT = re.compile(
    r"-([0-9]{1})[^a-z0-9]",
    re.IGNORECASE,
)


# ============================================
# 数据结构
# ============================================


@dataclass
class EpisodeInfo:
    """分集/标记识别结果

    字段对应 mdcx FileInformation 的子集:
    - cd_part: 分集号(如 "1", "2"),格式化后为 "-cd1" / "-CD1" / "-1"
    - has_sub: 是否中文字幕(从文件名/NFO/字幕文件检测)
    - c_word: 中字标记后缀(如 "-C", "-中字"),用于命名
    - destroyed: 马赛克破坏版标记后缀(如 "-破坏")
    - leak: 流出/破解标记后缀(如 "-流出")
    - wuma: 无码标记后缀(如 "-无码")
    - youma: 有码标记后缀(如 "-有码")
    """
    cd_part: str = ""           # 原始分集号(如 "1")
    has_sub: bool = False      # 是否中文字幕
    c_word: str = ""            # 中字命名后缀
    destroyed: str = ""         # 破坏版后缀
    leak: str = ""               # 流出后缀
    wuma: str = ""               # 无码后缀
    youma: str = ""              # 有码后缀
    # 额外信息(非 mdcx 原字段)
    raw_keywords_found: list[str] = field(default_factory=list)  # 命中的关键词(调试用)


# ============================================
# 核心函数
# ============================================


def detect_cd_part(filename: str, allow_c_as_part: bool = False) -> str:
    """识别文件名中的分集号

    移植自 mdcx/core/file.py:427-471

    四种识别模式(按优先级):
    1. 显式 CD/Part/HD 标记: -cd1, _part2, .hd3
    2. 末尾数字: -1, -12
    3. 末尾字母 a-o: -a, -b (排除 c 中字,除非 allow_c_as_part=True)
    4. 中间单数字: -1-, -1_

    Args:
        filename: 文件名(可含扩展名,会自动去除)
        allow_c_as_part: 是否允许 c 作为分集号
            (默认 False,因为 c 通常是中字标记)

    Returns:
        分集号字符串(如 "1", "2"),无分集返回 ""
    """
    # 去除扩展名
    name = os.path.splitext(filename)[0]
    # 移除系列编号(VOL/CASE/NO/CWP/CWPBD/ACT + 数字)
    name = SERIES_NUMBER_PATTERN.sub("", name)
    # 统一分隔符为 -
    name = name.replace("_", "-").replace(" ", "-").replace(".", "-")
    # 小写化并去除两端分隔符
    name = name.lower().strip("-")

    if not name:
        return ""

    # 模式 1: 显式 CD/Part/HD 标记
    m = CD_PATTERN_EXPLICIT.search(name)
    if m and int(m.group(2)) > 0:
        return m.group(2)

    # 模式 2: 末尾数字
    m = CD_PATTERN_END_DIGIT.search(name)
    if m:
        try:
            n = int(m.group(1))
            if n > 0:
                return str(n)
        except ValueError:
            pass

    # 模式 3: 末尾字母 a-o
    m = CD_PATTERN_END_LETTER.search(name)
    if m:
        letter = m.group(2).lower()
        # c 默认视为中字,不作为分集
        if letter != "c" or allow_c_as_part:
            return str(ord(letter) - ord("a") + 1)

    # 模式 4: 中间单数字
    m = CD_PATTERN_MIDDLE_DIGIT.search(name)
    if m:
        try:
            n = int(m.group(1))
            if n > 0:
                return str(n)
        except ValueError:
            pass

    return ""


def format_cd_part(cd_part: str, style: str = "cd") -> str:
    """格式化分集号为命名后缀

    移植自 mdcx/core/file.py:474-483

    Args:
        cd_part: 分集号(如 "1")
        style: 格式风格
            - "cd"  → "-cd1" (小写)
            - "CD"  → "-CD1" (大写)
            - "raw" → "-1"  (无前缀)

    Returns:
        格式化后的分集后缀,无分集返回 ""
    """
    if not cd_part:
        return ""
    try:
        n = int(cd_part)
    except ValueError:
        return ""
    if n == 0:
        return ""
    if style == "cd":
        return f"-cd{n}"
    if style == "CD":
        return f"-CD{n}"
    return f"-{n}"


def detect_chinese_sub(filename: str) -> tuple[bool, list[str]]:
    """检测文件名是否包含中字标记

    移植自 mdcx/core/file.py:584-595

    规则:
    - 文件名包含 cnword_list 中的关键词 → 视为中字
    - 但若同时包含 "無字幕"/"无字幕" → 不视为中字

    Args:
        filename: 文件名(可包含路径)

    Returns:
        (是否中字, 命中的关键词列表)
    """
    # 排除:无字幕
    for not_sub in NOT_SUB_KEYWORDS:
        if not_sub in filename:
            return False, []

    found: list[str] = []
    for kw in CHINESE_SUB_KEYWORDS:
        if kw in filename:
            found.append(kw)

    # 去重并保持顺序
    seen = set()
    unique_found = []
    for kw in found:
        if kw not in seen:
            seen.add(kw)
            unique_found.append(kw)

    return bool(unique_found), unique_found


def detect_mosaic_info(filename: str) -> tuple[str, str, str, str, list[str]]:
    """检测文件名的马赛克/流出/破坏信息

    移植自 mdcx/core/file.py:605-617 (NFO 检测部分移植为文件名扫描)

    Returns:
        (wuma, youma, leak, destroyed, keywords_found) 五元组
        - wuma: 无码后缀(如 "-无码"),无则空
        - youma: 有码后缀(如 "-有码"),无则空
        - leak: 流出后缀(如 "-流出"),无则空
        - destroyed: 破坏版后缀(如 "-破坏"),无则空
        - keywords_found: 命中的关键词列表(调试用)
    """
    wuma = ""
    youma = ""
    leak = ""
    destroyed = ""
    found: list[str] = []

    for kw in UNCENSORED_KEYWORDS:
        if kw in filename:
            wuma = "-无码"
            found.append(kw)
            break
    for kw in CENSORED_KEYWORDS:
        if kw in filename:
            youma = "-有码"
            found.append(kw)
            break
    for kw in LEAK_KEYWORDS:
        if kw in filename:
            leak = "-流出"
            found.append(kw)
            break
    for kw in DESTROYED_KEYWORDS:
        if kw in filename:
            destroyed = "-破坏"
            found.append(kw)
            break

    return wuma, youma, leak, destroyed, found


def detect_episode(
    filename: str,
    allow_c_as_part: bool = False,
    cnword_style: str = "-C",
) -> EpisodeInfo:
    """识别文件名的所有分集/中字/无码元信息

    综合检测入口,整合 detect_cd_part / detect_chinese_sub / detect_mosaic_info。

    Args:
        filename: 文件名(可含扩展名)
        allow_c_as_part: 是否允许 c 作为分集号
        cnword_style: 中字命名后缀风格(如 "-C", "-中字")

    Returns:
        EpisodeInfo 对象
    """
    cd_part = detect_cd_part(filename, allow_c_as_part)
    has_sub, sub_keywords = detect_chinese_sub(filename)
    c_word = cnword_style if has_sub else ""
    wuma, youma, leak, destroyed, mosaic_keywords = detect_mosaic_info(filename)

    return EpisodeInfo(
        cd_part=cd_part,
        has_sub=has_sub,
        c_word=c_word,
        destroyed=destroyed,
        leak=leak,
        wuma=wuma,
        youma=youma,
        raw_keywords_found=sub_keywords + mosaic_keywords,
    )


# ============================================
# 番号分集后缀剥离(用于番号对比归一化)
# ============================================


def strip_episode_by_number(number: str, allow_c_as_part: bool = False) -> str:
    """从已识别的番号中剥离分集后缀

    用于番号对比时的归一化(去除 -A/-B/-1 等分集标记)。
    与 detect_cd_part 不同,此函数假设输入是已标准化的番号(如 ABC-123)。

    规则:
    - ABC-123-A → ABC-123 (剥离单字母分集,排除 C/U 中字/无码)
    - ABC-123-1 → ABC-123 (剥离数字分集)
    - ABC-123-v2 → ABC-123 (剥离版本号)
    - ABC-123-r1 → ABC-123 (剥离修订号)
    - ABC-123-C → ABC-123-C (保留 C 中字后缀,除非 allow_c_as_part=True)

    Args:
        number: 番号(如 ABC-123-A, ABC-123-1)
        allow_c_as_part: 是否允许 c 作为分集号

    Returns:
        剥离分集后缀后的基础番号
    """
    if not number:
        return number

    # 1. 尝试 -vN/-rN (版本号/修订号)
    new = re.sub(r"[-_]v\d{1,2}$", "", number, flags=re.IGNORECASE)
    new = re.sub(r"[-_]r\d{1,2}$", "", new, flags=re.IGNORECASE)
    if new != number:
        return new

    # 2. 尝试 -数字 (分集)
    m = re.match(r"^(.+?\d+)-(\d{1,2})$", number)
    if m:
        return m.group(1)

    # 3. 尝试 -单字母 (分集 A/B/D...),排除 C/U(中字/无码)
    m = re.match(r"^(.+?)-([A-Za-z])$", number)
    if m:
        letter = m.group(2).lower()
        excluded = {"c", "u"} if not allow_c_as_part else {"u"}
        if letter not in excluded:
            # 确认 base 是有效番号(字母+数字)
            if re.search(r"[A-Za-z]{2,}.*\d", m.group(1)):
                return m.group(1)

    return number


def is_episode_marker(number: str, allow_c_as_part: bool = False) -> bool:
    """判断番号末尾是否是分集标记

    用于区分 ABC-123-C (中字) 和 ABC-123-A (分集)。

    Args:
        number: 番号
        allow_c_as_part: 是否允许 c 作为分集号

    Returns:
        True 如果末尾是分集标记(应剥离)
    """
    if not number:
        return False

    # 版本号
    if re.search(r"[-_]v\d{1,2}$", number, re.IGNORECASE):
        return True
    if re.search(r"[-_]r\d{1,2}$", number, re.IGNORECASE):
        return True

    # 数字分集
    if re.match(r"^.+?\d+-\d{1,2}$", number):
        return True

    # 字母分集(排除 C/U)
    m = re.match(r"^(.+?)-([A-Za-z])$", number)
    if m:
        letter = m.group(2).lower()
        excluded = {"c", "u"} if not allow_c_as_part else {"u"}
        if letter not in excluded:
            if re.search(r"[A-Za-z]{2,}.*\d", m.group(1)):
                return True

    return False
