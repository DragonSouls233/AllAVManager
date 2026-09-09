"""
文件夹演员识别器（国产模块专用）
从文件夹名提取演员名的核心模块
"""

import re

from app.utils.actor_name_guard import is_plausible_actor_name

STUDIO_NAMES = {
    "麻豆传媒", "天美传媒", "果冻传媒", "精东影业",
    "糖心VLOG", "蜜桃传媒", "星空无限", "SWAG",
    "大象传媒", "爱豆传媒", "皇家华人", "猫爪影像",
    "狂点映像", "映秀传媒", "抖阴传媒", "涩会传媒",
    "乌鸦传媒", "乐播传媒", "优蜜传媒", "偶蜜国际",
    "叮叮映画", "哔哩传媒", "开心鬼传媒",
}

DEFAULT_BLACKLIST = {
    "新建文件夹", "合集", "精选", "unknown",
    "未分类", "tmp", "temp", "downloads",
    "我的收藏", "精选集", "收藏", "新建",
}


def extract_actor_from_folder(
    folder_name: str,
    blacklist: set[str] | None = None,
    studio_names_as_folder: bool = False,
) -> list[str]:
    """从文件夹名提取演员名列表

    规则:
    1. 过滤黑名单文件夹名
    2. 排除已知工作室名（除非 studio_names_as_folder=True）
    3. "xxx+xxx" / "xxx.xxx" 格式分割为多个演员
    4. 中文名（2-8字）保留
    5. 英文名（首字母大写，至少2个字母）保留
    6. **每个候选名都必须通过 `is_plausible_actor_name` 合理性校验**

    变更说明（2026-09-09）：
    旧实现在拆不出任何合法 token 时无条件 `return [name]`，把**整个目录名/文件标题**
    原样当成演员名，导致线上 chinese 模块产生大量垃圾演员（`视频` 722 部、
    `高清` 176 部、整条 40 字文件标题等）。现在该兜底改为"仅当整串本身通过合理性
    校验时才保留"，否则返回空列表。含数字的网名（lmzzyn568、xixibaby123）属合法
    创作者标识，仍会保留。
    """
    if blacklist is None:
        blacklist = DEFAULT_BLACKLIST

    name = folder_name.strip()
    if not name:
        return []

    if name in blacklist:
        return []

    if not studio_names_as_folder and name in STUDIO_NAMES:
        return []

    # 单字符（非中文）或纯数字名不可能是演员
    if len(name) == 1 and not ('\u4e00' <= name <= '\u9fff'):
        return []
    if name.isdigit():
        return []

    # 去除开头方括号内的元数据标记，如 [release][081225-001]密室陵辱 弘中れおな
    name = re.sub(r'^(\[[^\]]*\])+\s*', '', name)

    cleaned = re.sub(r'^[A-Z]+-?\d+[._\s]?', '', name)

    parts = re.split(r'[.+_&,，、\s]+', cleaned)

    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 合理性校验前置：目录词 / 平台名 / 描述语 / 画质词 / 序号 一律拦下，
        # 否则「高清」「视频」「美女」这类纯中文 2-8 字会直接混进演员表
        if not is_plausible_actor_name(part, blacklist):
            continue
        if re.match(r'^[\u4e00-\u9fff]{2,8}$', part):
            if part not in result:
                result.append(part)
        elif re.match(r'^[A-Z][a-z]{1,}$', part):  # 至少2个字母: Aa+
            if part not in result:
                result.append(part)
        elif re.match(r'^[\u4e00-\u9fff]{2,}[A-Za-z]+', part):
            if part not in result:
                result.append(part)

    if result:
        return result

    # 拆不出合法 token 时的兜底：只有整串本身"看起来像人名"才保留。
    # 旧实现无条件返回 [name]，是整条文件标题被入库为演员名的根因。
    if is_plausible_actor_name(name, blacklist):
        return [name]
    return []


def clean_actor_name(name: str) -> str:
    """清洗演员名"""
    name = name.strip().strip('.')
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    return name[:100]


def is_actor_folder(folder_name: str, config: dict | None = None) -> bool:
    """判断文件夹名是否为有效演员名"""
    blacklist = set(config.get("blacklist", [])) | DEFAULT_BLACKLIST if config else DEFAULT_BLACKLIST
    studio_flag = config.get("studio_names_as_folder", False) if config else False
    actors = extract_actor_from_folder(folder_name, blacklist, studio_flag)
    return len(actors) > 0
