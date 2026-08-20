"""演员名归一化 / 宽松匹配 / 别名拆分清洗工具

移植自 mdcx-diy（cdlongbow/mdcx-diy）`mdcx/crawlers/javdb_app.py`
（feat: JavDB 演员别名补全，本地副本 ref22-mdcx-diy，v1.8-71 之后的提交）。
原始实现由 JavDB 移动端 APK 逆向的别名补全功能演化而来，供多个模块复用：

- `app/services/javdb_actor_merge.py`    改名演员合并扫描（归一化匹配键）
- `app/services/javdb_app_client.py`     JavDB App API 按名查别名（fetch_actor_aliases）
- `app/utils/actor_alias.py`             别名聚合（清洗括号噪声）
- `app/services/actor_merge_service.py`  合并别名（清洗 + casefold 去重）
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from zhconv import convert as _zhconv_convert

# 日文异体字映射：把日文简化/新旧字形统一到传统字形一侧（亜->亞、沢->澤 …）。
# 用于「本地名」与「JavDB 目录/详情名」写法差异的匹配（如 亜樹 vs 亞樹）。
JP_VARIANT_MAP: dict[str, str] = {
    "亜": "亞",
    "亞": "亞",
    "凉": "涼",
    "涼": "涼",
    "高": "髙",
    "髙": "髙",
    "斎": "齋",
    "齋": "齋",
    "沢": "澤",
    "澤": "澤",
    "桜": "櫻",
    "櫻": "櫻",
    "垅": "壟",
    "壮": "壯",
    "壯": "壯",
    "屿": "嶼",
    "嶼": "嶼",
    "栗": "慄",
    "慄": "慄",
    "岬": "岬",
}


def normalize_actor_name(name: str) -> str:
    """归一化演员名用于匹配：NFKC + zhconv 繁体 + 日文异体字统一 + 去标点 + 小写"""
    name = unicodedata.normalize("NFKC", name or "")
    name = _zhconv_convert(name, "zh-hant")
    name = "".join(JP_VARIANT_MAP.get(c, c) for c in name)
    name = re.sub(r"[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]", "", name)
    return name.lower()


def is_pure_kana(name: str) -> bool:
    """判断归一化后的名字是否纯假名（无汉字）"""
    return bool(name) and all("\u3040" <= c <= "\u30ff" for c in name)


def actor_name_matches(target: str, candidate: str) -> bool:
    """宽松匹配演员名：归一化后完全一致、包含、或去掉末字后一致。

    纯假名短名（归一化后 ≤2 字）只允许精确匹配，不做子串包含——
    2 字假名作为子串极易误命中（如 "りな" 出现在 "新ありな" 中）。
    含汉字的名字不受此限制（如 "田中檸檬" 包含 "檸檬" 是安全的）。
    """
    t = normalize_actor_name(target)
    c = normalize_actor_name(candidate)
    if not t or not c:
        return False
    if t == c:
        return True
    # 纯假名短名（≤2字）不做子串包含，避免误匹配
    short_side = t if len(t) <= len(c) else c
    if is_pure_kana(short_side) and len(short_side) <= 2:
        # 但允许去掉末字后一致（处理异体字差异）
        if len(t) >= 3 and len(c) >= 3 and t[:-1] == c[:-1]:
            return True
        return False
    if t in c or c in t:
        return True
    if len(t) >= 3 and len(c) >= 3 and t[:-1] == c[:-1]:
        return True
    return False


def is_combo_name(alias: str) -> bool:
    """判断别名是否为组合名（A・B 格式，两边各自像完整的日本人姓名）。

    判断标准：去掉括号后，・ 两边各为 2-5 字的纯汉字/含假名姓名段。
    外国人名（含片假名外来语）、罗马音间隔、括号内标签不受影响。
    例: 朝比奈菜々子・水原麗子 -> True（双人名组合）
        アンジェラ・ホワイト   -> False（片假名外来语）
        岸畑孝美(人妻斬り・...)  -> False（括号内）
    """
    # 去掉括号内容后再判断
    clean = re.sub(r"\(.*?\)|【.*?】|\[.*?\]", "", alias or "").strip()
    if "・" not in clean:
        return False
    parts = [p.strip() for p in clean.split("・") if p.strip()]
    if len(parts) != 2:
        return False

    def _looks_like_jp_name(s: str) -> bool:
        """2-6 字，含汉字或平假名（非片假名外来语），像日本人姓名"""
        if not (2 <= len(s) <= 6):
            return False
        has_kanji = any("\u4e00" <= c <= "\u9fff" for c in s)
        has_hira = any("\u3040" <= c <= "\u309f" for c in s)
        # 片假名为主（外来语）不算日本人姓名
        has_kata = any("\u30a0" <= c <= "\u30ff" for c in s)
        if has_kata and not has_kanji:
            return False
        return has_kanji or has_hira

    return _looks_like_jp_name(parts[0]) and _looks_like_jp_name(parts[1])


def split_aliases(other_name: str, name_zht: str, search_name: str, db_name: str) -> list[str]:
    """拆分 other_name 字段为别名列表，排除原名和搜索名，过滤组合名"""
    seen = {normalize_actor_name(search_name), normalize_actor_name(db_name)}
    aliases: list[str] = []
    for part in (other_name or "").split(","):
        part = part.strip()
        if not part or normalize_actor_name(part) in seen:
            continue
        if is_combo_name(part):
            continue
        seen.add(normalize_actor_name(part))
        aliases.append(part)
    if name_zht and normalize_actor_name(name_zht) not in seen:
        aliases.append(name_zht)
    return aliases


def clean_alias_parens(alias: str) -> Optional[str]:
    """清洗别名中的括号后缀。

    返回清洗后的名字，或 None 表示整条删除。
    规则：
      1. (注)/（注） 开头的注释说明 → 整条删除
      2. 名字(数字/仮/仮名) + 后续内容 → 去括号及之后所有内容，只留括号前名字
      3. 名字(标签) 末尾括号 → 去括号保留名字
      4. 括号在中间（如 "しいなうしお SIR(...)"）→ 整条删除
      5. 括号前为空 → 整条删除
      6. 嵌套括号取最外层
    """
    s = (alias or "").strip()
    if not s:
        return None
    # 无括号 → 原样返回
    if "(" not in s and "（" not in s:
        return s
    # 统一全角括号
    s = s.replace("（", "(").replace("）", ")")
    # 规则1: (注) 开头的注释说明 → 整条删除
    if re.match(r"^\(注\)", s):
        return None
    # 规则4: 括号前有空格（括号在中间，如 "しいなうしお SIR(...)"）→ 整条删除
    if re.match(r"^\S+\s+\S*\(", s):
        return None
    # 找第一个括号
    m = re.match(r"^(.+?)\s*\(", s)
    if not m:
        return None
    base = m.group(1).strip()
    # 规则5: 括号前为空 → 整条删除
    if not base:
        return None
    # 规则2/3: 去括号及之后所有内容，只留括号前名字
    return base
