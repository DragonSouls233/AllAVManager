#!/usr/bin/env python3
"""
国产片标签/演员列表工具模块

从 MDCX 迁移，为国产爬虫提供标签和演员列表支持。
原始文件: guochan.py
"""

import os.path
import re

try:
    import zhconv
except ImportError:
    zhconv = None


def remove_escape_string(file_path):
    """兼容 MDCX 的 remove_escape_string 函数"""
    if not file_path:
        return file_path
    # 去除文件名中的特殊字符
    result = re.sub(r"[\[\]\(\)（）【】]", "", file_path)
    return result.strip()


def get_lable_list():
    return [
        "麻豆传媒", "91茄子", "Ed Mosaic", "HongKongDoll", "JVID",
        "MINI传媒", "SA国际传媒", "TWAV", "乌鸦传媒", "乐播传媒",
        "优蜜传媒", "偶蜜国际", "叮叮映画", "哔哩传媒", "大象传媒",
        "天美传媒", "开心鬼传媒", "微密圈", "扣扣传媒", "抖阴传媒",
        "星空无限传媒", "映秀传媒", "杏吧传媒", "果冻传媒", "模密传媒",
        "爱污传媒", "爱神传媒", "爱豆传媒", "狂点映像", "猛料原创",
        "猫爪影像", "皇家华人", "精东影业", "糖心VLOG", "维秘传媒",
        "草莓视频", "萝莉社", "蜜桃传媒", "西瓜影视", "起点传媒",
        "香蕉视频", "PsychoPorn色控", "蜜桃影像传媒", "大番号番啪啪",
        "REAL野性派", "豚豚创媒", "宫美娱乐", "肉肉传媒", "爱妃传媒",
        "91制片厂", "O-STAR", "兔子先生", "杏吧原创", "杏吧独家",
        "辣椒原创", "麻豆传媒映画", "红斯灯影像", "绝对领域", "麻麻传媒",
        "渡边传媒", "AV帝王", "桃花源", "蝌蚪传媒", "SWAG",
        "麻豆", "杏吧", "糖心", "国产短视频", "国产精品", "国产AV", "涩会",
    ]


def get_actor_list():
    return [
        "Madison Summers", "Spencer Bradley", "Madison Morgan",
        "Rosalyn Sphinx", "Braylin Bailey", "Whitney Wright",
        "Victoria Voxxx", "Alexia Anders", "Bella Rolland",
        "Violet Myers", "Sophia Leone", "Violet Starr",
        "Eliza Ibarra", "HongKongDoll", "Keira Croft",
        "April Olsen", "Avery Black", "Amber Moore",
        "Anny Aurora", "Skylar Snow", "Harley Haze",
        "Paige Owens", "Vanessa Sky", "MasukuChan",
        "Kate Bloom", "Kimmy Kimm", "Ana Foxxx",
        "Lexi Luna", "Gia Derza", "Skye Blue",
        "Nico Love", "Alyx Star", "Ryan Reid",
        "Kira Noir", "Karma Rx", "下面有根棒棒糖",
        "Vivian姐", "COLA酱", "cola醬", "Stacy",
        "ROXIE", "真木今日子", "小七软同学", "Chloe",
        "Alona", "小日向可怜", "NANA", "玩偶姐姐",
        "粉色情人", "桥本香菜", "冉冉学姐", "小二先生",
        "饼干姐姐", "Rona", "不见星空", "米娜学姐",
        "阿蛇姐姐", "樱花小猫", "樱井美里", "宸荨樱桃",
        "樱空桃桃",
    ]


def get_number_list(number, appoint_number="", file_path=""):
    """获取番号列表"""
    number_list = []
    filename_list = []

    if number:
        number_list.append(number)
        filename_list.append(file_path or number)

    if appoint_number and appoint_number not in number_list:
        number_list.append(appoint_number)
        filename_list.append(file_path or appoint_number)

    return number_list, filename_list


def get_extra_info(title, file_path, info_type="actor"):
    """获取额外信息"""
    if info_type == "actor":
        # 从文件名中提取可能的演员名
        if file_path:
            filename = os.path.splitext(os.path.basename(file_path))[0]
            # 尝试从文件名中提取演员信息
            return ""
    return ""
