# -*- coding: utf-8 -*-
"""类别（genre）归一化与中文化。

## 为什么需要
javbus / javmenu / javmost 等源的 ``/category/`` 链接返回**英文原文**
（``Married Woman``、``Huge Butt``、``Solowork``…），刮削时直接落库。
实测 jav 库 9722 部影片里有 565 种纯 ASCII 类别词、21578 个条目
（javmost 独占 14345），而 javdb 源本身给中文（``熟女``、``中出``），
同库两种语言并存，详情页「类别」区和按类别筛选全是英文。

另外部分源（javmenu 等）把整个类别列表塞进**一个** genre 元素，形如
``"Censor,Uncensor,Solowork,Big Tits,…"``，页面上会出现几十个词的超长
「类别」，点击筛选也匹配不到任何影片。

## 做什么
1. **拆逗号串**：按逗号拆成独立元素（仅对含逗号的元素拆，避免误伤）。
2. **英文 → 中文**：查 :data:`GENRE_ZH`（大小写/空格/连字符不敏感，
   ``Big Tits`` / ``bigtits`` / ``BIG-TITS`` 归一）。
3. **去重 + 剔除占位**：``N/A``、``Unknown`` 等占位词直接丢弃。

## 设计约束（重要）
- 🔴 **查不到就原样保留，绝不猜译。** 映射表只收录能确信的词条；
  未收录的英文词仍以原文入库，页面上照常显示，后续补表即可生效，
  不必重刮全库。宁可残留英文，也不要错译成不相干的标签。
- 已中文化的词（``熟女``）不会被二次处理：映射键全是 ASCII，汉字自然不命中。
- 本模块**纯函数、无副作用**，可在刮削链路（同步）与回填脚本（离线）共用。
"""

from __future__ import annotations

import re

__all__ = ["GENRE_ZH", "normalize_genres", "translate_genre"]


#: 占位词：源用它表示「无类别」，不该显示给用户
_PLACEHOLDERS = frozenset({
    "n/a", "na", "none", "null", "unknown", "uncategorized", "-", "--",
})

_ASCII_KEY = re.compile(r"^[\x00-\x7f]+$")
_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")


def _norm_key(word: str) -> str:
    """归一键：去首尾空白 + 转小写 + 去掉内部空格/连字符/下划线。"""
    return re.sub(r"[\s\-_]+", "", word.strip().lower())


def _register(pairs: dict[str, str]) -> None:
    for en, zh in pairs.items():
        GENRE_ZH[_norm_key(en)] = zh


#: 英文类别 → 中文。
#: 🔴 只收录**能确信**的对应关系；查不到的一律保留原文（见模块 docstring）。
#: 键统一由 :func:`_norm_key` 归一，写原文即可，不必手写小写变体。
GENRE_ZH: dict[str, str] = {}

_register({
    # ---- 打码 / 性质 / 制作 ----
    "Censor": "有码",
    "Uncensor": "无码",
    "Digital Mosaic": "数字打码",
    "Risky Mosaic": "高危打码",
    "Nampa": "纳米亚克力",
    "Amateur": "素人",
    "Documentary": "纪录片",
    "Impromptu Sex": "即兴做爱",
    "Subjectivity": "主观视角",
    "Planning": "剧情",
    "Multiple Story": "多段故事",
    "Drama": "剧情",
    "Best": "精选",
    "Omnibus": "合集",
    "Original Collaboration": "跨界合作",
    "Blu-ray": "蓝光",
    "VR": "VR",
    "8KVR": "8K VR",
    "High Quality VR": "高清VR",
    "4K": "4K",
    "HDTV": "高清电视",
    "4HR+": "4小时以上",
    "AV Actress": "AV女优",
    "Actress Best": "女优精选",
    "White Actress": "白人女优",
    "Black Actor": "黑人演员",
    "Entertainer": "女艺人",
    "Debut Production": "出道作",
    "Fan Appreciation": "粉丝见面会",
    "Delusion": "妄想",
    "Evil": "恶魔",
    "Cruel Expression": "残酷表情",
    "Cruel Express": "残酷表现",
    "Insult": "辱骂",
    "Abuse": "虐待",
    "Dark System": "黑暗题材",
    "Historical Play": "时代剧",
    "Action": "动作",
    "Fighters": "格斗",
    "Fighting Action": "格斗动作",
    "Sport": "运动",
    "Yoga": "瑜伽",
    "Dance": "舞蹈",
    "Catgirl": "猫娘",
    "Idol": "偶像",
    "Model": "模特",
    "Muscle": "肌肉",
    "How To": "教学",
    "Experience Confession": "经验分享",
    "Interview": "访谈",
    "Other Asian": "其他亚洲",
    "Other Students": "其他学生",
    "Celebrity": "名人",
    "Exposure": "露出",
    "FC2": "FC2",
    "Special Effects": "特殊效果",
    "Body Conscious": "意识清醒",
    "Look-alike": "替身",

    # ---- 体格 / 外貌 ----
    "Tits": "胸部",
    "Breasts": "乳房",
    "Big Tits": "巨乳",
    "Huge Tits": "爆乳",
    "Ultra-Huge Tits": "超爆乳",
    "Huge Butt": "巨臀",
    "Butt": "臀部",
    "BBW": "丰满体型",
    "Slender": "苗条",
    "Tall": "高挑",
    "Huge Cock": "巨根",
    "Sun tan": "古铜",
    "Glasses": "眼镜",
    "Bloomers": "灯笼裤",
    "Masked": "蒙面",

    # ---- 性格 / 关系 ----
    "Slut": "淫妇",
    "Bitch": "淫荡",
    "Nasty": "脏话",
    "Dirty Words": "脏话",
    "Hardcore": "激烈",
    "Vibe": "氛围",
    "Couple": "情侣",
    "Gal": "女孩",
    "Girl": "女孩",
    "Beautiful Girl": "美女",
    "Solowork": "单体作品",
    "Affair": "出轨",
    "Married Woman": "已婚妇女",
    "Mature Woman": "熟女",
    "Young Wife": "少妇",
    "Stepmother": "继母",
    "Mother-in-law": "婆婆",
    "Mother": "母亲",
    "Older Sister": "姐姐",
    "Sister": "姐妹",
    "Aunt": "阿姨",
    "Widow": "寡妇",
    "Bride": "新娘",
    "Princess": "公主",
    "Adopted Daughter": "养女",
    "Childhood Friend": "青梅竹马",
    "Mom Friends": "妈妈的朋友",
    "Elder Male": "年长男性",
    "Incest": "乱伦",
    "Rape": "强奸",
    "Molester": "猥亵",
    "Lesbian": "女同",
    "Lesbian Kiss": "女同接吻",
    "Transsexual": "跨性别",
    "Futanari": "扶她",
    "Cross Dressing": "伪娘",
    "Transformed Heroine": "变性女主",
    "Sex Conversion / Feminized": "性转",
    "Cosplay": "角色扮演",
    "Anime Characters": "动漫角色",

    # ---- 姿势 / 视角 ----
    "3P": "3P",
    "4P": "4P",
    "69": "69",
    "Creampie": "中出",
    "Cum": "射精",
    "Cowgirl": "骑乘",
    "Back": "后入",
    "Close Up": "特写",
    "POV": "主观视角",
    "Kiss": "接吻",
    "Blow": "口交",
    "Deep Throating": "深喉",
    "Cunnilingus": "口交",
    "Handjob": "手交",
    "Titty Fuck": "乳交",
    "Finger Fuck": "手插",
    "Footjob": "足交",
    "Anal": "肛交",
    "Gangbang": "轮奸",
    "Cuckold": "绿帽",
    "Paizuri": "乳交",
    "Deep Sex": "深喉",
    "Anal Sex (TS)": "肛交",
    "Group Sex": "群交",

    # ---- 身体液体 / 排泄 ----
    "Squirting": "潮吹",
    "Male Squirting": "男性潮吹",
    "Female Ejaculation": "女性潮吹",
    "Ejaculation": "射精",
    "Piss Drinking": "饮尿",
    "Urination": "尿尿",
    "Breast Pee": "乳汁",
    "Defecation": "排便",
    "Scatology": "粪便",
    "Vomit": "呕吐",
    "Enema": "灌肠",
    "Sweat": "汗",

    # ---- SM / 拘束 ----
    "SM": "SM",
    "Restraint": "拘束",
    "Restraints": "拘束",
    "Bondage": "捆绑",
    "Shibari": "缚",
    "Rope": "绳缚",
    "Spanking": "拍打臀",
    "Tickling": "挠痒",
    "Humiliation": "凌辱",
    "Submission": "臣服",
    "User Submission": "用户投稿",
    "Submissive Men": "男受",
    "Submissive Woman": "女受",
    "Submissive": "臣服",
    "Subordinates / Colleagues": "部下/同事",
    "Reversed Role": "逆袭角色",
    "Face Sitting": "颜射",
    "Fisting": "拳交",
    "Torture": "拷问",
    "Hypnosis": "催眠",
    "Drug": "药物",
    "Confinement": "监禁",
    "Naked Apron": "裸体围裙",
    "Foreign Objects": "异物",
    "Dildo": "假阳具",
    "Egg Vibrator": "震动棒",
    "Electric Massager": "电动按摩器",
    "Speculum": "窥器",
    "Cervix": "宫颈",
    "Nose Hook": "鼻钩",

    # ---- 服装 ----
    "Uniform": "制服",
    "School Uniform": "校服",
    "Sailor Suit": "水手服",
    "Swimsuit": "泳装",
    "School Swimsuit": "校园泳装",
    "Mini Skirt": "短裙",
    "Underwear": "内衣",
    "Lingerie": "内衣",
    "Erotic Wear": "情趣内衣",
    "Pantyhose": "连裤袜",
    "Knee Socks": "及膝袜",
    "Loose Socks": "宽松袜",
    "Long Boots": "长靴",
    "Kimono": "和服",
    "Yukata": "浴衣",
    "Cheongsam": "旗袍",
    "Business Attire": "职业装",
    "Blazer": "西装外套",
    "Leotard": "紧身衣",
    "Bunny Girl": "兔女郎",
    "No Bra": "不穿内衣",
    "No Undies": "不穿内裤",

    # ---- 职业 / 场景 ----
    "Female Teacher": "女教师",
    "Tutor": "家教",
    "Instructor": "教练",
    "Training": "培训",
    "Nurse": "护士",
    "Female Doctor": "女医生",
    "Doctor": "医生",
    "Hospital / Clinic": "医院/诊所",
    "Secretary": "秘书",
    "Landlady": "房东太太",
    "Hostess": "女招待",
    "Stewardess": "空姐",
    "Anchorwoman": "主播",
    "Waitress": "服务员",
    "Receptionist": "前台",
    "Mistress": "情人",
    "OL": "OL",
    "Female College Student": "女大学生",
    "School Girls": "女学生",
    "School Girl": "女学生",
    "School Stuff": "校园题材",
    "Teacher/Student": "师生",
    "Boss/Subordinate": "上下级",
    "Various Professions": "各种职业",
    "Beauty Shop": "美容院",
    "Soapland": "泡泡浴",
    "Bus Guide": "巴士导游",
    "Race Queen": "赛车 queen",
    "Hot Spring": "温泉",
    "Outdoor": "户外",
    "Outdoors": "户外",
    "Indoors": "室内",
    "Hotel": "酒店",
    "Apartments": "公寓",
    "Bath": "浴缸",
    "Massage": "按摩",
    "Voyeur": "偷拍",
    "Time Stop": "时停",
    "Flexible": "柔韧",
    "Tsundere": "傲娇",
    "Impromptu": "即兴",
    "Toy": "玩具",

    # ---- 其它 ----
    "Sleeping": "睡眠",
    "Tentacle": "触手",
    "Shotacon": "异端",

    # ---- 第二批：按实测库内残留词补齐（2026-10-20 回填后复扫发现）----
    "Facials": "颜射",
    "Other Fetish": "其他癖好",
    "Busty Fetish": "巨乳癖",
    "Leg Fetish": "腿部癖",
    "Fetish": "癖好",
    "Prostitutes": "风俗",
    "Promiscuity": "性滥",
    "Shaved": "剃毛",
    "Masturbation": "自慰",
    "Masturbation Support": "助撸",
    "Lotion": "爱抚液",
    "Bukkake": "颜射",
    "Mini": "迷你",
    "Female Boss": "女上司",
    "Image Video": "影片",
    "Mourning": "丧服",
    "Prank": "恶作剧",
    "Maid": "女仆",
    "Virgin Man": "处男",
    "Virgin": "处女",
    "Female Investigator": "女调查员",
    "Dead Drunk": "烂醉",
    "Love": "恋爱",
    "Miss": "小姐",
    "Date": "约会",
    "Conceived": "受孕",
    "Pregnant Woman": "孕妇",
    "Travel": "旅行",
    "Rolling Back Eyes / Fainting": "翻白眼/失神",
    "Immediate Oral": "立即口交",
    "Fantasy": "幻想",
    "Athlete": "运动员",
    "Breast Milk": "母乳",
    "Sexy": "性感",
    "Female Warrior": "女战士",
    "Slave": "奴隶",
    "Granny": "阿婆",
    "For Women": "女性向",
    "Drinking Party": "酒局",
    "Disk On Demand": "按需点播",
    "Car Sex": "车震",
    "Swingers": "换妻",
    "Premature Ejaculation": "早洩",
    "Cosplay Costumes": "角色扮演服",
    "Club Activities / Manager": "社团/经纪人",
    "Cheerleader": "啦啦队员",
    "Female Ninja": "女忍者",
    "Priestess": "女巫",
    "Nude": "全裸",
    "Hug": "拥抱",
    "Hostesses": "女招待",
    "Adult Movie": "成人电影",
    "Late 2010s (DOD)": "2010年代后期",
    "AV OPEN 2016 MILF/Housewife Dept.": "AV OPEN 2016 人妻部门",
    "AV OPEN 2016 Mania/Fetish Dept.": "AV OPEN 2016 癖好部门",
    "AV OPEN 2018 maidendept": "AV OPEN 2018 女仆部门",

    # ---- 源站截断残词：按可推断的完整词归一 ----
    "Deep Throatin": "深喉",
    "Finger Fuc": "手插",
    "Titty Fu": "乳交",
    "Digital Mosai": "数字打码",
    "Knee Soc": "及膝袜",
    "Long Boo": "长靴",
    "Original Collaboratio": "跨界合作",
    "Breast Pe": "乳汁",
    "Adopte": "收养",
})

#: 归一化键 → 中文 的运行时缓存（惰性填充）
_ZH_CACHE: dict[str, str] = {}


def translate_genre(word: str) -> str:
    """单个类别词 → 中文。

    查不到映射时**原样返回**（不猜译），这样新出现的英文词仍能正常入库与展示，
    后续往 :data:`GENRE_ZH` 补一条即可全局生效，不必重刮全库。
    """
    raw = (word or "").strip()
    if not raw:
        return ""
    key = _norm_key(raw)
    if not key or key in _PLACEHOLDERS:
        return ""
    # 已含中日文字符 ⇒ 上游（javdb 等）已中文化，不动
    if _HAS_CJK.search(raw):
        return raw

    hit = _ZH_CACHE.get(key)
    if hit is not None:
        return hit
    # 先按归一键直接命中；再退化到「原文小写无空格」匹配，兼容源里
    # `big tits` 写成 `bigtits` 的情况（两者归一键相同，此处是双保险）
    zh = GENRE_ZH.get(key)
    if zh and zh.strip():
        _ZH_CACHE[key] = zh
        return zh
    return raw


def normalize_genres(words) -> list[str]:
    """整组类别：拆逗号串 → 中文化 → 去重（保持原顺序）。

    仅当元素**含逗号**时才拆分，避免把本就是一个标签的写法切坏。
    """
    out: list[str] = []
    seen: set[str] = set()
    for w in words or []:
        if isinstance(w, (list, tuple)):
            parts = list(w)
        else:
            text = str(w)
            parts = text.split(",") if "," in text else [text]
        for p in parts:
            zh = translate_genre(str(p))
            if not zh:
                continue
            key = _norm_key(zh)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(zh)
    return out


def has_translatable(word: str) -> bool:
    """该词是否会（可能）被中文化 —— 供回填脚本筛选用。"""
    raw = (word or "").strip()
    if not raw or _HAS_CJK.search(raw):
        return False
    key = _norm_key(raw)
    if not key or key in _PLACEHOLDERS:
        return False
    return _ASCII_KEY.match(raw) is not None
