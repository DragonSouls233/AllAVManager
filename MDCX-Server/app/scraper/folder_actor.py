"""
文件夹演员识别器（国产模块专用）
从文件夹名提取演员名的核心模块
"""

import re

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
    5. 英文名（首字母大写）保留
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

    cleaned = re.sub(r'^[A-Z]+-?\d+[._\s]?', '', name)

    parts = re.split(r'[.+_&,，、\s]+', cleaned)

    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(r'^[\u4e00-\u9fff]{2,8}$', part):
            if part not in result:
                result.append(part)
        elif re.match(r'^[A-Z][a-z]+$', part):
            if part not in result:
                result.append(part)
        elif re.match(r'^[\u4e00-\u9fff]{2,}[A-Za-z]+', part):
            if part not in result:
                result.append(part)

    return result if result else [name]


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
