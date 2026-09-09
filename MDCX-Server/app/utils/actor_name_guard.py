"""演员名合理性守卫（防目录名 / 描述语 / 画质词 / 标题串被误当作演员名）

背景
----
扫描器从**目录名**推断演员（`app/scraper/folder_actor.py`）以及从**路径**推断
（`app/utils/pornhub_path_parser.py`）时，缺乏语义校验，导致大量非人名入库：

- 目录/分类词：视频、高清、未归类、合集、資源集
- 平台名：推特、91短视频
- 描述语：极品、美女、校花、熟女、博主、网红
- 序号：第234弹、第12期
- 画质/年份：1080p、4K、2024
- 整条文件标题：超嫩极品00后嫩妹【小橘娘】……

chinese 模块线上实测 1524 个演员中，按 movie_count 排序前 30 名有一半是上述垃圾，
涉及数千部影片（`视频` 一个就挂了 722 部）。本模块提供统一判定，避免各扫描器各写一套。

设计原则
--------
**只做高精度拦截，不追求高召回**。漏掉一个真演员（假阴性）只是少一条数据；
误判一个真演员为垃圾（假阳性）会直接丢数据。涉及数字的网名（lmzzyn568、
xixibaby123、fkabuto）在国产/pornhub 场景是**合法的创作者标识**，必须放行，
因此"含数字"本身不构成拒绝理由。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 词表

# 目录 / 分类 / 整理用语（只做全等匹配，避免误伤含这些字的真名）
FOLDER_WORDS = {
    # 整理目录
    "视频", "影片", "影视", "高清", "标清", "超清", "蓝光", "原盘",
    "未归类", "未分类", "待整理", "已整理", "新建文件夹", "新建",
    "我的收藏", "收藏", "精选", "精选集", "合集", "全集", "完结",
    "資源集", "资源集", "资源", "資源", "素材", "下载", "downloads",
    "tmp", "temp", "cache", "unknown", "other", "其他", "杂项",
    # 分类标签
    "国产", "亚洲", "欧美", "日本", "韩国", "中国", "台湾", "香港", "澳门",
    "无码", "有码", "步兵", "骑兵", "字幕", "中字",
    # 系列/企划词（国产场景常见顶层目录）
    "探花", "街拍", "自拍", "偷拍", "约拍", "福利", "试看", "预览",
}

# 国籍 / 地区目录名（pornhub 等模块常以国籍做一级目录，如 M:\爱沙尼亚\[Channel] xxx）
# 与 app/utils/pornhub_path_parser.py::_NATIONALITY_PATTERNS 的值保持一致；
# 不直接 import 那个模块，避免循环依赖（它反过来 import 本模块）。
NATIONALITY_WORDS = {
    "美国", "英国", "日本", "韩国", "台湾", "中国", "香港", "澳门",
    "法国", "德国", "意大利", "西班牙", "加拿大", "澳大利亚",
    "巴西", "俄罗斯", "荷兰", "瑞典", "瑞士",
    "泰国", "越南", "菲律宾", "印度",
    "阿根廷", "墨西哥", "哥伦比亚", "爱沙尼亚",
    "欧洲", "葡萄牙", "希腊", "波兰", "捷克",
    "匈牙利", "罗马尼亚", "乌克兰", "白俄罗斯",
    "土耳其", "以色列", "印尼", "马来西亚",
    "新加坡", "新西兰", "丹麦", "挪威",
    "芬兰", "比利时", "奥地利", "智利", "秘鲁",
    "古巴", "南非", "尼日利亚", "亚洲", "欧美", "俄罗斯",
}

# 平台 / 站点名（国产场景大量以平台名为目录）
PLATFORM_WORDS = {
    "推特", "twitter", "微博", "weibo", "抖音", "快手", "小红书", "instagram",
    "pornhub", "xvideos", "xhamster", "onlyfans", "fansly", "patreon",
    "91", "91短视频", "91porn", "草榴", "sixty9",
}

# 描述语 / 营销词：命中即判定为"描述性文本"而非人名
# 这类词几乎不出现在真人名里，命中即拦（子串匹配）
DESCRIPTIVE_KEYWORDS = (
    "极品", "美女", "校花", "嫩妹", "熟女", "少妇", "人妻", "御姐", "萝莉",
    "博主", "网红", "模特", "主播", "女神", "尤物", "辣妹", "欲女",
    "身材", "性感", "诱惑", "勾人", "销魂", "高潮", "潮吹", "口爆",
    "大尺度", "无码", "有码", "高清", "精品", "高清无码",
    "私拍", "偷拍", "自拍", "街拍", "约炮", "援交", "乱伦",
    "合集", "全集", "资源", "資源", "打包", "下载", "在线", "免费",
    "第一弹", "第二弹", "第三弹", "第四弹", "第五弹",
    "性价比", "极品", "包养", "约拍", "外围", "嫩模",
)

# 画质 / 编码 / 来源标签
QUALITY_RE = re.compile(
    r"^(1080p|1080i|720p|2160p|1440p|480p|360p|4k|8k|hd|sd|uhd|fhd|qhd|"
    r"bluray|blueray|bd|dvd|web-?dl|web-?rip|remux|hdr|sdr|"
    r"x264|x265|h264|h265|hevc|avc|aac|ac3|dts|"
    r"vr|3d|60fps|30fps|120fps|cbr|vbr)$",
    re.I,
)

# 年份 / 纯序号
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
EPISODE_RE = re.compile(r"^第?\s*\d+\s*(弹|期|集|部|话|話|章|季|辑|輯)$")

# HTML / 刮削器噪声
# 两类：成对标签 <b>...</b>、以及未闭合的标签碎片（如线上 jav 库里真实存在的 "<img"）
_HTML_TAG_RE = re.compile(
    r"<[^>]{0,80}>"                 # 成对标签
    r"|</?\s*[a-zA-Z][a-zA-Z0-9]*"  # 未闭合标签碎片：<img / <div / </span
    r"|<\s*!\s*--"                  # 注释开头
    r"|&(?:nbsp|amp|lt|gt|quot|#\d+);",  # HTML 实体
    re.I,
)

# 句子级标点（真人艺名不会带句号、感叹号、逗号）
# 注意：日文顿号「、」**不在其中**——它会合法出现在"本名（别名、别名）"式艺名里
# （如 jav 库真实存在的「新井エリー（晶エリー、大沢佑香）」），误杀代价太高。
# 半角/全角逗号保留：那是多演员串的特征（如「葵つかさ,坂道みる」）。
_SENTENCE_PUNCT = "。！？!?，,；;~～…"
# 成对装饰符（标题党常用，如【小橘娘】「yuumeilyn」）
_DECOR_BRACKETS = ("【", "】", "「", "」", "《", "》")

# 日文/中文人名允许的字符（用于"整串是否像人名"的兜底判断）
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uff66-\uff9f]")
_LATIN_RE = re.compile(r"[A-Za-z]")

MAX_NAME_LEN = 40
MIN_NAME_LEN = 2

# 人工白名单：确认是真实演员、但会被上述规则误判的名字。
# 用法：把名字加进来即可（如 JAV 里含义模糊的艺名「女神ジュン」）。
WHITELIST: set[str] = set()


def _norm(name: str) -> str:
    return (name or "").strip()


def reject_reason(name: str, extra_blacklist: set[str] | None = None) -> str | None:
    """判定演员名是否为垃圾，返回拒绝原因；正常名字返回 None。

    规则按"最确定 → 最不确定"排列，命中任一即拒绝。
    """
    n = _norm(name)

    # 人工白名单优先（确认过的真实演员不受规则影响）
    if n in WHITELIST:
        return None

    # ---- 基础形态 ----
    if not n:
        return "空名"
    if len(n) > MAX_NAME_LEN:
        return f"过长(>{MAX_NAME_LEN})"
    if len(n) < MIN_NAME_LEN:
        # 单字符：拉丁字母/数字必垃圾；单汉字可能是艺名（如 葵），放行
        if not _CJK_RE.search(n):
            return "单字符非汉字"

    low = n.lower()

    # ---- 显式词表 ----
    if low in {w.lower() for w in FOLDER_WORDS}:
        return "目录/分类词"
    if low in {w.lower() for w in PLATFORM_WORDS}:
        return "平台名"
    if n in NATIONALITY_WORDS:
        return "国籍/地区"
    if extra_blacklist and (n in extra_blacklist or low in {w.lower() for w in extra_blacklist}):
        return "配置黑名单"

    # ---- 画质 / 年份 / 序号 ----
    if QUALITY_RE.match(n):
        return "画质/编码词"
    if YEAR_RE.match(n):
        return "年份"
    if EPISODE_RE.match(n):
        return "序号"

    # ---- 刮削噪声 ----
    if _HTML_TAG_RE.search(n):
        return "HTML/实体噪声"
    if n.startswith("[") and n.endswith("]"):
        return "方括号标记"

    # ---- 描述性文本 ----
    for kw in DESCRIPTIVE_KEYWORDS:
        if kw in n:
            return f"描述语:{kw}"

    # ---- 句子级标点 / 装饰括号（整条文件标题的典型特征）----
    if any(p in n for p in _SENTENCE_PUNCT):
        return "句子标点"
    if any(b in n for b in _DECOR_BRACKETS):
        return "装饰括号"

    # ---- 字符构成：既非 CJK 也非拉丁（纯数字/纯符号）----
    if n.isdigit():
        return "纯数字"
    if not _CJK_RE.search(n) and not _LATIN_RE.search(n):
        return "无有效文字字符"

    return None


def is_plausible_actor_name(name: str, extra_blacklist: set[str] | None = None) -> bool:
    """演员名是否"看起来像人名"——扫描器写入演员表前的最后一道闸。"""
    return reject_reason(name, extra_blacklist) is None
