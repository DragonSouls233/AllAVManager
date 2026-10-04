"""
文件夹演员识别器（国产模块专用）
从文件夹名提取演员名的核心模块
"""

import re

from app.utils.actor_name_guard import (
    STUDIO_NAMES,
    is_plausible_actor_name,
    is_studio_name as _is_studio_name,
)

DEFAULT_BLACKLIST = {
    "新建文件夹", "合集", "精选", "unknown",
    "未分类", "tmp", "temp", "downloads",
    "我的收藏", "精选集", "收藏", "新建",
}

# 2026-10-04：`STUDIO_NAMES` / `_STUDIO_SUFFIXES` / `_is_studio_name`
# 已下沉到 `app/utils/actor_name_guard.py`。
# 原因：演员名守卫本身漏掉了片商名 —— 实测 chinese 库回填关联表时，
# `麻豆传媒映画` 仍被写进 `actors`（守卫只查场所/描述语/形态，不查片商）。
# 而守卫被 `folder_actor` import，若守卫反向 import `folder_actor` 会循环，
# 所以常量必须放在守卫这一侧，由 folder_actor 单向取用。


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

    if not studio_names_as_folder and _is_studio_name(name):
        return []

    # 单字符（非中文）或纯数字名不可能是演员
    if len(name) == 1 and not ('\u4e00' <= name <= '\u9fff'):
        return []
    if name.isdigit():
        return []

    # 去除开头方括号内的元数据标记，如 [release][081225-001]密室陵辱 弘中れおな
    name = re.sub(r'^(\[[^\]]*\])+\s*', '', name)

    cleaned = re.sub(r'^[A-Z]+-?\d+[._\s]?', '', name)

    # 🔴 小数点是**演员名内部**的分隔符，不是词边界。
    # `Anna Cherry.7` / `anna.cherry` / `Rosi Lane.II` 这类目录名里，
    # 点两侧必须合并回一个名字。2026-10-04 实测：把 `.` 直接当分隔符时
    # `anna.cherry` 被切成 `anna`+`cherry`，两者都不匹配 `^[A-Z][a-z]+$`
    # （前者首字母大写要求不满足、后者只有一个词）⇒ 整个演员名丢失。
    #
    # 做法：先把「点两侧都是拉丁字母」的点替换成一个不会参与切分的占位符，
    # 切分完再还原。这样 `麻豆传媒映画.MDCM-0006` 的点（右侧是数字/大写）
    # 仍然是分隔符，而 `anna.cherry` 的点被保护。
    _DOT_PLACEHOLDER = "\x00"
    cleaned = re.sub(
        r"(?<=[A-Za-z])\.(?=[A-Za-z])", _DOT_PLACEHOLDER, cleaned
    )
    parts = re.split(r'[.+_&,，、\s]+', cleaned)

    result = []
    for part in parts:
        part = part.strip().replace(_DOT_PLACEHOLDER, ".")
        if not part:
            continue
        # 片商名逐片判定：整串是长标题时 `_is_studio_name` 会因长度放行
        # （见该函数里 "长串交给分片处理" 的说明），所以这里必须对每个
        # part 单独再判一次，否则 `麻豆传媒映画.MDCM-0006.梁佳芯.…`
        # 里的 `麻豆传媒映画` 会被当成演员。
        if not studio_names_as_folder and _is_studio_name(part):
            continue
        # 合理性校验前置：目录词 / 平台名 / 描述语 / 画质词 / 序号 一律拦下，
        # 否则「高清」「视频」「美女」这类纯中文 2-8 字会直接混进演员表
        if not is_plausible_actor_name(part, blacklist):
            continue
        if re.match(r'^[\u4e00-\u9fff]{2,8}$', part):
            if part not in result:
                result.append(part)
        elif re.match(r'^[A-Z][A-Za-z]*\d+$', part):
            # 艺名带数字后缀：`Anna Cherry7` / `Rosi Lane2` / `Abby lovee7`。
            # 2026-10-04 实测：这类名字在目录里极常见（PH/素人模块），
            # 但旧正则 `^[A-Z][a-z]{1,}$` 不接受尾数字 ⇒ 整段丢失，
            # 只剩被空格切开的前半截 `Anna`，把一个人拆成两个。
            if part not in result:
                result.append(part)
        elif re.match(r'^[A-Za-z][A-Za-z.\' ]{1,}$', part) and not part.islower():
            # 至少2个字母，且不能全小写 —— 全小写的是 `高清` 类目录词
            # 或 `anna.cherry` 这类被守卫放行但语义可疑的串。
            # 首字母大写或含大写字母的（Anna Cherry / Rosi Lane.II）才收。
            if part not in result:
                result.append(part)
        elif re.match(r'^[\u4e00-\u9fff]{2,}[A-Za-z]+', part):
            if part not in result:
                result.append(part)

    if result:
        return result

    # 拆不出合法 token 时的兜底：只有整串本身"看起来像人名"才保留。
    # 旧实现无条件返回 [name]，是整条文件标题被入库为演员名的根因。
    #
    # 🔴 兜底路径必须**跳过片段型规则**（场所/机构后缀、描述语）。
    # 整条标题里只要出现一个 `国风按摩院` 就把整串（含合法的 `梁佳芯`）否决，
    # 是 2026-10-04 引入 PLACE_SUFFIX_RE 后实测到的回归 ——
    # 片段规则只该用于"逐 token 判定"，不能否决一个长标题的整体形态。
    if _is_wholename_plausible(name, blacklist):
        return [name]
    return []


def _is_wholename_plausible(name: str, blacklist: set[str] | None = None) -> bool:
    """整串形态判定：只放行"短且无分隔符"的整串。

    用于兜底路径。片段型规则（场所后缀 / 描述语）已经作用于 ``parts``
    的逐 token 判定，兜底这里不再重复 —— 否则
    ``麻豆传媒映画.MDCM-0006.梁佳芯.国风按摩院.新欢夺爱享情欲``
    会因含"国风按摩院"被整串否决，把合法的 ``梁佳芯`` 一起丢掉
    （2026-10-04 实测到的回归）。

    真正要拦的是**含分隔符的长标题**：那种串一定是从文件名/目录名
    整体抄下来的，不是人名。
    """
    if not is_plausible_actor_name(name, blacklist):
        return False
    n = name.strip()
    if len(n) > 12:
        return False
    if any(sep in n for sep in "，,。.、；;！!？?/\\|[]【】「」《》"):
        return False
    # 允许内部空格（"Anna Cherry"），但不允许首尾空格造成的多段拼接
    return re.match(r'^[\u4e00-\u9fff A-Za-z]{2,12}$', n) is not None


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
