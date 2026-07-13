"""文件名特殊属性检测(借鉴 JavSP javsp/lib.py:46-70)

检测影片文件名中的特殊属性标记:
- U: 无码(Uncensored / 无码 / 無碼 / 流出 / 破解)
- C: 中字(Chinese subtitle,文件名后缀 -C)
- UC: 无码+中字

典型用法:
    >>> from app.utils.file_attrs import detect_special_attr
    >>> detect_special_attr('IPX-177-UC.mp4', 'IPX-177')
    'UC'
    >>> detect_special_attr('SSIS-698-uncensored-leaked.mp4')
    'U'
    >>> detect_special_attr('ABP-001-C.mp4')
    'C'
"""

import os
import re
from typing import Optional

# 无码流出/破解检测正则(借鉴 JavSP lib.py:46)
# 匹配:uncensored / uncensor / uncen / uncensored-leaked / uncensored_leaked
#      无码流出 / 无碼流出 / 无码破解 / 無碼破解
_PATTERN_UNCENSORED = re.compile(
    r'(uncen(sor(ed)?)?([- _\s]*leak(ed)?)?|[无無][码碼](流出|破解))',
    flags=re.I,
)


def detect_special_attr(filepath: str, avid: Optional[str] = None) -> str:
    """通过文件名检测影片是否有特殊属性(内嵌字幕、无码流出/破解)

    借鉴 JavSP javsp/lib.py:47-70 的实现逻辑。

    Args:
        filepath: 文件路径(只取 basename + 去扩展名)
        avid: 番号(可选,用于精确匹配番号后缀的 -U/-C/-UC 标记)

    Returns:
        特殊属性字符串,可能值:
        - '': 无特殊属性
        - 'U': 无码(uncensored/无码流出/无码破解)
        - 'C': 中字(文件名后缀 -C)
        - 'UC': 无码+中字
        - 'CU': 同 UC(排序后为 'CU',实际与 'UC' 等价)

        注意:返回值会去重并按字母降序排序(借鉴 JavSP lib.py:69),
        所以 'U' + 'C' + 'U' → 'CU'(去重后 {C, U},降序排序为 'CU')。
        若需要统一比较,建议调用方用 set(result) 而非字符串比较。

    Examples:
        >>> detect_special_attr('ipx-177cd1.mp4', 'IPX-177')
        ''
        >>> detect_special_attr('SSIS-698-uncensored-leaked.mp4')
        'U'
        >>> detect_special_attr('ABP-001-C.mp4')
        'C'
        >>> detect_special_attr('TEST-001-UC.mp4')
        'UC'
    """
    result = ''
    # 取 basename 去扩展名,转大写
    base = os.path.splitext(os.path.basename(filepath))[0].upper()

    # 1. 正则匹配无码流出/破解标记
    match = _PATTERN_UNCENSORED.search(base)
    if match:
        result += 'U'

    # 2. 匹配 -U/-C/-UC 后缀
    # 取最后一个 - 后的部分
    parts = base.split('-')
    if len(parts) > 1:
        postfix = parts[-1]
        if postfix in ('U', 'C', 'UC', 'CU'):
            result += postfix
        elif avid:
            # 用番号精确匹配:番号 +(UC|U|C) 词边界
            # 借鉴 JavSP lib.py:64:re.sub(r'[_-]', '[_-]*', avid) 让 _ - 都能匹配
            pattern_str = re.sub(r'[_-]', '[_-]*', avid) + r'(UC|U|C)\b'
            match = re.search(pattern_str, base, flags=re.I)
            if match:
                result += match.group(1)

    # 3. 最终格式化:去重 + 降序排序(借鉴 JavSP lib.py:69)
    # 例如 'UU' → 'U','UCU' → 'CU'(set 去重 → {U, C} → 降序 → 'CU')
    result = ''.join(sorted(set(result), reverse=True))
    return result


def has_uncensored(filepath: str, avid: Optional[str] = None) -> bool:
    """便捷方法:检测文件名是否标记为无码

    Args:
        filepath: 文件路径
        avid: 番号(可选)

    Returns:
        True 如果文件名包含无码标记
    """
    return 'U' in detect_special_attr(filepath, avid)


def has_chinese_subtitle(filepath: str, avid: Optional[str] = None) -> bool:
    """便捷方法:检测文件名是否标记为中字

    Args:
        filepath: 文件路径
        avid: 番号(可选)

    Returns:
        True 如果文件名包含中字标记
    """
    return 'C' in detect_special_attr(filepath, avid)
