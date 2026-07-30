"""
PORNHub 目录解析模块

从本地或服务器端的目录结构中提取演员名称、国籍信息。

支持的目录名格式:
  G:\\TEST\\pornhub\\<actor_dir>\\videofile.mp4
  E:\\MDCX-Server\\data\\videos\\pornhub\\<actor_dir>\\videofile.mp4

其中 <actor_dir> 支持多种格式:
  - Anna Cherry7
  - [ChannelName] Anna Cherry7
  - Anna Cherry7 [US]
  - [ChannelName] Anna Cherry7 [US]
  - Anna Cherry7 (US)
  - Anna Cherry7 + Sunny Leone [UK]   (多演员)
"""

import re
from pathlib import Path
from typing import Optional

# 常见国籍标记
_NATIONALITY_PATTERNS: dict[str, str] = {
    # 英文代码 → 中文
    "US": "美国", "USA": "美国",
    "UK": "英国", "GB": "英国",
    "JP": "日本", "KR": "韩国",
    "TW": "台湾", "CN": "中国",
    "HK": "香港", "FR": "法国",
    "DE": "德国", "IT": "意大利",
    "ES": "西班牙", "CA": "加拿大",
    "AU": "澳大利亚", "BR": "巴西",
    "RU": "俄罗斯", "NL": "荷兰",
    "SE": "瑞典", "CH": "瑞士",
    "TH": "泰国", "VN": "越南",
    "PH": "菲律宾", "IN": "印度",
    "AR": "阿根廷", "MX": "墨西哥",
    "CO": "哥伦比亚", "EE": "爱沙尼亚",
    "EU": "欧洲",
    # 中文名（支持上级目录直接用中文名）
    "美国": "美国", "英国": "英国", "日本": "日本",
    "韩国": "韩国", "台湾": "台湾", "中国": "中国",
    "香港": "香港", "法国": "法国", "德国": "德国",
    "意大利": "意大利", "西班牙": "西班牙",
    "加拿大": "加拿大", "澳大利亚": "澳大利亚",
    "巴西": "巴西", "俄罗斯": "俄罗斯",
    "荷兰": "荷兰", "瑞典": "瑞典", "瑞士": "瑞士",
    "泰国": "泰国", "越南": "越南",
    "菲律宾": "菲律宾", "印度": "印度",
    "阿根廷": "阿根廷", "墨西哥": "墨西哥",
    "哥伦比亚": "哥伦比亚", "爱沙尼亚": "爱沙尼亚",
    "欧洲": "欧洲",
}


def extract_actor_and_nationality(folder_name: str) -> tuple[Optional[str], Optional[str]]:
    """从文件夹名提取演员名和国籍

    支持的格式:
      - [ChannelName] Anna Cherry7 [US]  ->  ("Anna Cherry7", "美国")
      - Anna Cherry7 [US]                ->  ("Anna Cherry7", "美国")
      - [Channel] Anna Cherry7           ->  ("Anna Cherry7", None)
      - Anna Cherry7                     ->  ("Anna Cherry7", None)
      - Anna Cherry7 (US)                ->  ("Anna Cherry7", "美国")
      - Anna+Sunny [US]                  ->  ("Anna+Sunny", "美国")
      - Anna Cherry7 + Sunny Leone [UK]  ->  ("Anna Cherry7 + Sunny Leone", "英国")

    Returns:
        (actor_name, nationality) 元组
    """
    name = folder_name.strip()
    if not name:
        return None, None

    # 1. 去掉开头的 [ChannelName] / [Chan] 等标记
    name = re.sub(r'^\[.*?\]\s*', '', name).strip()

    # 2. 尝试从末尾提取国籍 [XX] 或 (XX)
    nationality = None

    # 匹配末尾 [US] [UK] [JP] 等
    m = re.search(r'\s*\[([A-Za-z]{2,4}(?:[,/\s][A-Za-z]{2,4})*)\]\s*$', name)
    if m:
        code = m.group(1).strip().upper()
        nationality = _NATIONALITY_PATTERNS.get(code, code)
        name = name[:m.start()].strip()

    # 匹配末尾 (US) (UK) 等
    if not nationality:
        m = re.search(r'\s*\(([A-Za-z]{2,4})\)\s*$', name)
        if m:
            code = m.group(1).strip().upper()
            nationality = _NATIONALITY_PATTERNS.get(code, code)
            name = name[:m.start()].strip()

    if not name:
        return None, None

    return name, nationality


def parse_local_path(file_path: str, base_dir: str) -> dict:
    """解析本地文件路径，提取演员名和国籍

    Args:
        file_path: 视频文件的完整路径
        base_dir: 媒体根目录（如 G:\\TEST\\pornhub）

    Returns:
        {"actor_name": str|None, "nationality": str|None, "relative_path": str}
    """
    result = {"actor_name": None, "nationality": None, "relative_path": ""}

    try:
        p = Path(file_path)
        rel = p.relative_to(Path(base_dir))
        result["relative_path"] = str(rel)

        # 取文件所在目录的父目录名
        parent = rel.parent
        if parent == Path("."):
            return result

        # 取最内层目录名作为演员文件夹名
        folder_name = parent.name if parent != Path(".") else None
        if not folder_name:
            return result

        actor_name, nationality = extract_actor_and_nationality(folder_name)
        result["actor_name"] = actor_name
        result["nationality"] = nationality

        # 如果文件夹名没提取到国籍，检查上级目录名
        if not nationality and parent.parent != Path("."):
            grandparent_name = parent.parent.name
            if grandparent_name in _NATIONALITY_PATTERNS:
                result["nationality"] = _NATIONALITY_PATTERNS[grandparent_name]
    except (ValueError, IndexError):
        pass

    return result


def parse_server_path(file_path: str, media_dirs: list[str]) -> dict:
    """解析服务器端文件路径，提取演员名和国籍

    服务器端路径可能带额外的层级，如:
      E:\\MDCX-Server\\data\\videos\\pornhub\\Anna Cherry7 [US]\\videofile.mp4
      L:\\MDCX-Server\\data\\videos\\pornhub\\[Channel] Anna Cherry7\\videofile.mp4

    Args:
        file_path: 视频文件的完整路径
        media_dirs: 媒体目录列表（依次尝试）

    Returns:
        {"actor_name": str|None, "nationality": str|None, "media_dir": str|None}
    """
    result = {"actor_name": None, "nationality": None, "media_dir": None}

    p = Path(file_path)
    for md in media_dirs:
        base = Path(md)
        try:
            rel = p.relative_to(base)
        except ValueError:
            continue

        result["media_dir"] = md

        # 从相对路径取最顶层目录作演员名
        parts = rel.parts
        if not parts:
            break

        # 检查最顶层是否为国籍目录（如 M:\\爱沙尼亚\\[Channel] Diana Rider\\video.mp4）
        top_dir = parts[0]
        if len(parts) >= 2 and top_dir in _NATIONALITY_PATTERNS:
            # 顶级是国籍目录，演员目录在下一层
            nationality = _NATIONALITY_PATTERNS[top_dir]
            actor_dir = parts[1]
            actor_name, _ = extract_actor_and_nationality(actor_dir)
        else:
            # 普通的单层结构：取第一层目录作为演员目录
            actor_name, nationality = extract_actor_and_nationality(top_dir)
        result["actor_name"] = actor_name
        result["nationality"] = nationality
        break

    return result
