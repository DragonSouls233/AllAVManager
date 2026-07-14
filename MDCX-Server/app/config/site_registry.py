"""
内置站点 URL 配置

从网络搜索收集的国产/欧美/日韩站点域名列表，
供 DomainSwitcher 和刮削器使用。

分类：
  chinese    - 国产站点（麻豆/海角/糖心/精东/91等）
  western    - 欧美站点（Brazzers/BangBros/Vixen/NaughtyAmerica等）
  jav        - JAVDB/磁力搜索站点

更新日期: 2026-07-14
数据来源: 各站点官方公告/社区维护列表/搜索引擎收录
"""

from enum import Enum


class SiteCategory(str, Enum):
    CHINESE = "chinese"
    WESTERN = "western"
    JAV = "jav"
    MAGNET = "magnet"


# ============================================================
# 国产站点（拼音: guochan）
# ============================================================

CHINESE_SITES = {
    # ---- 麻豆传媒系列（官方地址）----
    "madou": {
        "name": "麻豆传媒",
        "primary": "https://madou.com",
        "fallbacks": [
            # 官方发布页（GitLab 持续更新）
            "https://lwabe.com",              # 最新国内访问地址 2025-12-31
            # 麻豆官方 APP 合作域���（从 mod.run 提取）
            "https://d2marrs9oi8z8w.cloudfront.net",
            # 历史备用域名（从 P1 PSP 提取）
            "https://madouqu.sbs",
            "https://madouqu.club",
            "https://madouqu.cc",
            "https://madouqu.net",
            "https://madouqu.org",
        ],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 麻豆社（聚合站）----
    "madou_club": {
        "name": "麻豆社",
        "primary": "https://madou.club",
        "fallbacks": [],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 海角社区 ----
    "haijiao": {
        "name": "海角社区",
        "primary": "https://haijiao.com",
        "fallbacks": [
            "https://www.haijiao.com",
        ],
        "type": "community",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 糖心视频 ----
    "tangxin": {
        "name": "糖心视频",
        "primary": "https://txsp1.com",
        "fallbacks": [
            "https://dgvoxsc1tqftg.cloudfront.net",  # 官方 CDN
        ],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 精品P站 ----
    "jingpin": {
        "name": "精品P站",
        "primary": "https://jpzhan.com",
        "fallbacks": [
            "https://d3hf4gks5aypnx.cloudfront.net",
        ],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 逼哩逼哩 ----
    "bilibili_adult": {
        "name": "逼哩逼哩",
        "primary": "https://blibli.com",
        "fallbacks": [
            "https://d2pshtn5kfiph2.cloudfront.net",
        ],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 快手视频 ----
    "kuaishou_adult": {
        "name": "快手视频",
        "primary": "https://kssp1.com",
        "fallbacks": [
            "https://ddy8kv6p5zh0x.cloudfront.net",
        ],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- XV暗网 ----
    "xv_anwang": {
        "name": "XV暗网",
        "primary": "https://xvanwang.com",
        "fallbacks": [
            "https://d1p0sb236m0pbk.cloudfront.net",
        ],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 萝莉岛 ----
    "luoli": {
        "name": "萝莉岛",
        "primary": "https://luolidao.com",
        "fallbacks": [
            "https://d1kwrb6cu8gmbv.cloudfront.net",
        ],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- oio禁漫 ----
    "oio": {
        "name": "oio禁漫",
        "primary": "https://oiojm.com",
        "fallbacks": [
            "https://d38r7pt28daq9u.cloudfront.net",
        ],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 草榴社区 ----
    "caoliu": {
        "name": "草榴社区",
        "primary": "https://t66y.com",
        "fallbacks": [
            "https://cl.1024.com",
        ],
        "type": "community",
        "supports_scrape": True,
        "supports_download": False,
        "note": "需要邀请码才能搜索",
    },

    # ---- 色花堂 ----
    "sehuatang": {
        "name": "色花堂",
        "primary": "https://sehuatang.org",
        "fallbacks": [
            "https://sehuatang.net",
        ],
        "type": "community",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- hjd2048 ----
    "hjd2048": {
        "name": "hjd2048",
        "primary": "https://hjd2048.com",
        "fallbacks": [],
        "type": "community",
        "supports_scrape": True,
        "supports_download": True,
        "note": "色花堂镜像站，可免费注册",
    },

    # ---- 国产资源采集站系列（来自 X 资源采集站合集）----
    "baiwan_zy": {
        "name": "百万资源站",
        "primary": "https://bwzy.tv",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
        "note": "无水印视频资源站",
    },
    "dadi_zy": {
        "name": "大地资源站",
        "primary": "https://dadizy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "didi_zy": {
        "name": "滴滴资源站",
        "primary": "https://didizy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "aosika_zy": {
        "name": "奥斯卡资源站",
        "primary": "https://aosikazy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "lajiao_zy": {
        "name": "辣椒资源站",
        "primary": "https://lajiaozy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
        "note": "19年老牌资源站",
    },
    "huanggua_zy": {
        "name": "黄瓜资源站",
        "primary": "https://avre00.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "shayu_zy": {
        "name": "鲨鱼资源站",
        "primary": "https://shayuzy5.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "senlin_zy": {
        "name": "森林资源站",
        "primary": "https://senlinzy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "semao_zy": {
        "name": "色猫资源站",
        "primary": "https://semaozy5.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "jkun_zy": {
        "name": "JKUN资源站",
        "primary": "https://jkunzy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "yutu_zy": {
        "name": "玉兔资源站",
        "primary": "https://yutuzy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "jipin_zy": {
        "name": "极品资源站",
        "primary": "https://jipinzy.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "naixiang_zy": {
        "name": "奶香香资源站",
        "primary": "https://naixxzy1.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    "tantan_zy": {
        "name": "探探资源站",
        "primary": "https://tantanzy8.com",
        "fallbacks": [],
        "type": "collector",
        "supports_scrape": True,
        "supports_download": True,
    },
    # ---- SWAG（亚洲直播平台）----
    "swag": {
        "name": "SWAG",
        "primary": "https://www.swag.live",
        "fallbacks": [],
        "type": "live",
        "supports_scrape": True,
        "supports_download": True,
        "note": "亚洲最大直播平台，号称亚洲PornHub",
    },
    # ---- AV Jiali（国产专业站点）----
    "avjiali": {
        "name": "AV Jiali",
        "primary": "https://www.avjiali.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
        "note": "国产专业成人内容站点",
    },
    # ---- 台湾 Psycho Porn ----
    "psycho_porn": {
        "name": "Psycho Porn TW",
        "primary": "https://www.psychoporn.tw",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
        "note": "台湾成人影��制作公司",
    },
    # ---- Love6 TV ----
    "love6": {
        "name": "Love6 TV",
        "primary": "https://www.love6.tv",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
    },
    # ---- BananaFever ----
    "bananafever": {
        "name": "BananaFever",
        "primary": "https://www.bananafever.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
    },
    # ---- MM Asia ----
    "mm_asia": {
        "name": "MM Asia",
        "primary": "https://www.modelmediaasia.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 91Porn ----
    "91porn": {
        "name": "91Porn",
        "primary": "https://91porn.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "国产知名Tube站",
    },

    # ---- 就色/Jiuse ----
    "jiuse": {
        "name": "就色/Jiuse",
        "primary": "https://jiuse.ai",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 91wuba ----
    "91wuba": {
        "name": "91五八",
        "primary": "https://www.91wuba.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": False,
        "note": "来自 XOVideos 参考项目",
    },

    # ---- 9xbuddy（下载链接解析代理）----
    "9xbuddy": {
        "name": "9xBuddy",
        "primary": "https://9xbuddy.com",
        "fallbacks": [],
        "type": "tool",
        "supports_scrape": False,
        "supports_download": True,
        "note": "下载链接解析代理，来自 XOVideos 项目",
    },

    # ---- Allcover ----
    "allcover": {
        "name": "Allcover",
        "primary": "https://allcover.com",
        "fallbacks": [],
        "type": "tool",
        "supports_scrape": False,
        "supports_download": False,
        "note": "封面/缩略图来源，来自 XOVideos 项目",
    },
}


# ============================================================
# 欧美站点（拼音: oumei）
# ============================================================

WESTERN_SITES = {
    # ---- Brazzers（Aylo 旗下）----
    "brazzers": {
        "name": "Brazzers",
        "primary": "https://www.brazzers.com",
        "fallbacks": [
            "https://landing.brazzersnetwork.com",
        ],
        "type": "official",
        "network": "Aylo",
        "api": "https://site-api.project1service.com/v2",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- NaughtyAmerica ----
    "naughtyamerica": {
        "name": "Naughty America",
        "primary": "https://www.naughtyamerica.com",
        "fallbacks": [
            "https://natour.naughtyamerica.com",
            "https://www.naughtyamericavr.com",
        ],
        "type": "official",
        "network": "NA Group",
        "api": "https://api.naughtyapi.com/tools/scenes/scenes",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- RealityKings（Aylo 旗下）----
    "realitykings": {
        "name": "Reality Kings",
        "primary": "https://www.realitykings.com",
        "fallbacks": [
            "https://landing.rk.com",
        ],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- BangBros ----
    "bangbros": {
        "name": "BangBros",
        "primary": "https://www.bangbros.com",
        "fallbacks": [
            "https://landing.bangbrosnetwork.com",
        ],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- Mofos（Aylo 旗下）----
    "mofos": {
        "name": "Mofos",
        "primary": "https://www.mofos.com",
        "fallbacks": [
            "https://landing.mofosnetwork.com",
        ],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- Vixen Network 系列网站 ----
    "vixen": {
        "name": "Vixen",
        "primary": "https://www.vixen.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },
    "blacked": {
        "name": "Blacked",
        "primary": "https://www.blacked.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },
    "tushy": {
        "name": "Tushy",
        "primary": "https://www.tushy.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },
    "deeper": {
        "name": "Deeper",
        "primary": "https://www.deeper.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },
    "slayed": {
        "name": "Slayed",
        "primary": "https://www.slayed.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },
    "milfy": {
        "name": "Milfy",
        "primary": "https://www.milfy.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- AdultTime 系列（更多子站）----
    "adulttime": {
        "name": "AdultTime",
        "primary": "https://www.adulttime.com",
        "fallbacks": [
            "https://members.adulttime.com",
        ],
        "type": "official",
        "network": "AdultTime Network",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- Digital Playground ----
    "digitalplayground": {
        "name": "Digital Playground",
        "primary": "https://www.digitalplayground.com",
        "fallbacks": [],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- Twistys（Aylo 旗下）----
    "twistys": {
        "name": "Twistys",
        "primary": "https://www.twistys.com",
        "fallbacks": [],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- Babes（Aylo 旗下）----
    "babes": {
        "name": "Babes",
        "primary": "https://www.babes.com",
        "fallbacks": [],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- EvilAngel ----
    "evilangel": {
        "name": "EvilAngel",
        "primary": "https://www.evilangel.com",
        "fallbacks": [],
        "type": "official",
        "network": "Gamma",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- TeamSkeet ----
    "teamskeet": {
        "name": "TeamSkeet",
        "primary": "https://www.teamskeet.com",
        "fallbacks": [],
        "type": "official",
        "network": "Paper Street Media",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- MYLF ----
    "mylf": {
        "name": "MYLF",
        "primary": "https://www.mylf.com",
        "fallbacks": [],
        "type": "official",
        "network": "Vixen Network",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- BrattySis ----
    "brattysis": {
        "name": "BrattySis",
        "primary": "https://www.brattysis.com",
        "fallbacks": [],
        "type": "official",
        "network": "Paper Street Media",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- True Amateurs ----
    "trueamateurs": {
        "name": "True Amateurs",
        "primary": "https://www.trueamateurs.com",
        "fallbacks": [],
        "type": "official",
        "network": "Aylo",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 查询站点（元数据来源）----
    "iafd": {
        "name": "IAFD",
        "primary": "https://www.iafd.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },
    "theporndb": {
        "name": "ThePornDB",
        "primary": "https://api.theporndb.net",
        "fallbacks": [
            "https://theporndb.net",
        ],
        "type": "api",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 欧美 Tube 站点（免费视频下载来源）----
    "xvideos": {
        "name": "XVideos",
        "primary": "https://www.xvideos.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "全球最大免费 Tube 站之一",
    },
    "xhamster": {
        "name": "xHamster",
        "primary": "https://xhamster.com",
        "fallbacks": [
            "https://xxxhamster.com",
        ],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "Tube 站，含 VR 和成人故事",
    },
    "xnxx": {
        "name": "XNXX",
        "primary": "https://www.xnxx.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "redtube": {
        "name": "RedTube",
        "primary": "https://www.redtube.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "youporn": {
        "name": "YouPorn",
        "primary": "https://www.youporn.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "spankbang": {
        "name": "SpankBang",
        "primary": "https://spankbang.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "eporner": {
        "name": "Eporner",
        "primary": "https://www.eporner.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "hqporner": {
        "name": "HQPorner",
        "primary": "https://hqporner.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "高清免费专业工作室视频",
    },
    "pornhoarder": {
        "name": "PornHoarder",
        "primary": "https://pornhoarder.tw",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "pornone": {
        "name": "PornOne",
        "primary": "https://pornone.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "spankwire": {
        "name": "SpankWire",
        "primary": "https://www.spankwire.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "来自 pornSpider 参考项目",
    },
    "xtube": {
        "name": "XTube",
        "primary": "https://www.xtube.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "来自 pornSpider 参考项目",
    },
    "hclips": {
        "name": "HClips",
        "primary": "https://www.hclips.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "txxx": {
        "name": "TXXX",
        "primary": "https://www.txxx.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "pornbaker": {
        "name": "PornBaker",
        "primary": "https://pornbaker.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "tnaflix": {
        "name": "TNAFlix",
        "primary": "https://www.tnaflix.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "tube8": {
        "name": "Tube8",
        "primary": "https://www.tube8.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "beeg": {
        "name": "Beeg",
        "primary": "https://beeg.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "pornhd3x": {
        "name": "PornHD3x",
        "primary": "https://pornhd3x.tv",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },
    "motherless": {
        "name": "Motherless",
        "primary": "https://motherless.com",
        "fallbacks": [],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
        "note": "硬核/极端/小众类内容",
    },

    # ---- PornHub 系列 ----
    "pornhub": {
        "name": "PornHub",
        "primary": "https://www.pornhub.com",
        "fallbacks": [
            "https://www.pornhubpremium.com",
            "https://rt.pornhub.com",
            "https://www.pornhub.org",
            "https://player.pornhub.com",
        ],
        "type": "tube",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- 磁力/种子站点 ----
    "thepiratebay": {
        "name": "The Pirate Bay",
        "primary": "https://thepiratebay.org",
        "fallbacks": [],
        "type": "torrent",
        "supports_scrape": False,
        "supports_download": True,
    },
    "rarbg": {
        "name": "RARBG",
        "primary": "https://rargb.to",
        "fallbacks": [],
        "type": "torrent",
        "supports_scrape": False,
        "supports_download": True,
    },
    "pornbay": {
        "name": "PornBay",
        "primary": "https://pornbay.org",
        "fallbacks": [],
        "type": "torrent",
        "supports_scrape": False,
        "supports_download": True,
    },
    "sex8": {
        "name": "Sex8/杏吧",
        "primary": "https://sex8.cc",
        "fallbacks": [],
        "type": "community",
        "supports_scrape": True,
        "supports_download": True,
        "note": "杏吧社区，全球华人成人论坛",
    },
}

JAV_SITES = {
    # ---- JAVDB（主站 + 镜像）----
    "javdb": {
        "name": "JavDB",
        "primary": "https://javdb.com",
        "fallbacks": [
            "https://javdb36.com", "https://javdb37.com", "https://javdb38.com",
            "https://javdb40.com", "https://javdb.live", "https://javdb5.com",
            "https://javdb30.com", "https://javdb33.com",
            "https://javdb.org", "https://javdb368.com",
        ],
        "type": "database",
        "supports_scrape": True,
        "supports_download": True,
        "api": {
            "search": "/search?q={query}&locale=zh",
            "detail": "/v/{code}?locale=zh",
        },
    },

    # ---- JavBus（主站 + 镜像）----
    "javbus": {
        "name": "JavBus",
        "primary": "https://www.javbus.com",
        "fallbacks": [
            "https://www.javbus.one",  # AVDC 备用
            "https://www.javbus.org",
            "https://www.javbus.info",
        ],
        "type": "database",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- JavLibrary ----
    "javlibrary": {
        "name": "JavLibrary",
        "primary": "https://www.javlibrary.com",
        "fallbacks": [
            "https://www.javlib.com",
            "https://www.y78k.com",  # JavSP 免代理
        ],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- AVSox（JavSP/AVDC 通用刮削源）----
    "avsox": {
        "name": "AVSox",
        "primary": "https://avsox.click",
        "fallbacks": [
            "https://avsox.website",
        ],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Jav321 ----
    "jav321": {
        "name": "Jav321",
        "primary": "https://www.jav321.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Fanza/DMM（日本最大AV平台）----
    "fanza": {
        "name": "Fanza/DMM",
        "primary": "https://www.dmm.co.jp",
        "fallbacks": [
            "https://www.r18.com",
        ],
        "type": "official",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- JavMenu ----
    "javmenu": {
        "name": "JavMenu",
        "primary": "https://www.javmenu.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- JavTrailers ----
    "javtrailers": {
        "name": "JavTrailers",
        "primary": "https://www.javtrailers.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Jav.place ----
    "javplace": {
        "name": "Jav.place",
        "primary": "https://jav.place",
        "fallbacks": [],
        "type": "aggregator",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- MGStage 系列 ----
    "mgstage": {
        "name": "MGStage",
        "primary": "https://www.mgstage.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- XCity ----
    "xcity": {
        "name": "XCity",
        "primary": "https://xcity.jp",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 加勒比/东热/HEYZO 系列 ----
    "caribbeancom": {
        "name": "加勒比/Caribbeancom",
        "primary": "https://www.caribbeancom.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": False,
    },
    "tokyo_hot": {
        "name": "Tokyo-Hot",
        "primary": "https://my.tokyo-hot.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": False,
    },
    "heyzo": {
        "name": "HEYZO",
        "primary": "https://www.heyzo.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": False,
    },
    "heydouga": {
        "name": "HeyDouga",
        "primary": "https://www.heydouga.com",
        "fallbacks": [
            "https://image01-www.heydouga.com",
        ],
        "type": "official",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Prestige（蚊香社）----
    "prestige": {
        "name": "Prestige/蚊香社",
        "primary": "https://www.prestige-av.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Arzon ----
    "arzon": {
        "name": "Arzon",
        "primary": "https://www.arzon.jp",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },
    "gyutto": {
        "name": "Gyutto",
        "primary": "https://gyutto.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },
    "dl_getchu": {
        "name": "DL Getchu",
        "primary": "http://dl.getchu.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },
    "airav": {
        "name": "Airav",
        "primary": "https://airav.wiki",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },
    "avwiki": {
        "name": "AV Wiki",
        "primary": "https://avwiki.net",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- FC2 相关 ----
    "fc2_ppv": {
        "name": "FC2 PPV",
        "primary": "https://adult.contents.fc2.com",
        "fallbacks": [],
        "type": "official",
        "supports_scrape": True,
        "supports_download": False,
    },
    "fc2club": {
        "name": "FC2 Club",
        "primary": "https://fc2club.net",
        "fallbacks": [],
        "type": "community",
        "supports_scrape": True,
        "supports_download": False,
    },
    "fc2fan": {
        "name": "FC2 Fan",
        "primary": "https://fc2fan.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },
    "fc2ppvdb": {
        "name": "FC2 PPV DB",
        "primary": "https://fc2ppvdb.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- 磁力搜索引擎 ----
    "sukebei": {
        "name": "Sukebei (Nyaa)",
        "primary": "https://sukebei.nyaa.si",
        "fallbacks": [],
        "type": "magnet",
        "supports_scrape": True,
        "supports_download": True,
    },
    "skrbtso": {
        "name": "Skrbtso",
        "primary": "https://skrbtso.top",
        "fallbacks": [],
        "type": "magnet",
        "supports_scrape": True,
        "supports_download": True,
    },
    "freejavbt": {
        "name": "FreeJavBT",
        "primary": "https://www.freejavbt.com",
        "fallbacks": [],
        "type": "magnet",
        "supports_scrape": True,
        "supports_download": True,
    },
    "jable": {
        "name": "Jable",
        "primary": "https://www.jable.tv",
        "fallbacks": [],
        "type": "streaming",
        "supports_scrape": True,
        "supports_download": True,
    },

    # ---- StashDB（Stash 官方元数据库）----
    "stashdb": {
        "name": "StashDB",
        "primary": "https://stashdb.org",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- AVMoo（JavBoss/AVMeta 刮削源）----
    "avmoo": {
        "name": "AVMoo",
        "primary": "https://avmoo.click",
        "fallbacks": [
            "https://avmoo.xyz",
        ],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- JavDatabase ----
    "javdatabase": {
        "name": "JavDatabase",
        "primary": "https://javdatabase.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Jav101 ----
    "jav101": {
        "name": "Jav101",
        "primary": "https://jav101.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Jav.Land（R18 数据）----
    "javland": {
        "name": "Jav.Land",
        "primary": "https://jav.land",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- All.TL（同人作品）----
    "all_tl": {
        "name": "All.TL（同人）",
        "primary": "https://www.all.tl",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Aiventertainment（熟女向）----
    "aientertainment": {
        "name": "Aiventertainment",
        "primary": "https://www.aientertainment.com",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- R18.dev API ----
    "r18dev": {
        "name": "R18.dev (API)",
        "primary": "https://www.r18.dev",
        "fallbacks": [],
        "type": "api",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- AV-Wiki（MDCx 刮削源）----
    "avwiki": {
        "name": "AV-Wiki",
        "primary": "https://av-wiki.net",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
    },

    # ---- Warashi（女优头像源）----
    "warashi": {
        "name": "Warashi（女优头像）",
        "primary": "https://warashi-asian-pornstars.fr",
        "fallbacks": [],
        "type": "database",
        "supports_scrape": True,
        "supports_download": False,
        "note": "女优头像专用来源，来自 JAVOneStop 项目",
    },
}


# ============================================================
# 合并所有站点（供统一查询）
# ============================================================

ALL_SITES = {
    SiteCategory.CHINESE: CHINESE_SITES,
    SiteCategory.WESTERN: WESTERN_SITES,
    SiteCategory.JAV: JAV_SITES,
}

SITE_BY_DOMAIN: dict[str, dict] = {}
for category_sites in ALL_SITES.values():
    for site_id, site_info in category_sites.items():
        primary = site_info["primary"].replace("https://", "").replace("http://", "").rstrip("/")
        SITE_BY_DOMAIN[primary] = {**site_info, "id": site_id, "category": category_sites}
        for fb in site_info.get("fallbacks", []):
            fb_domain = fb.replace("https://", "").replace("http://", "").rstrip("/")
            if fb_domain not in SITE_BY_DOMAIN:
                SITE_BY_DOMAIN[fb_domain] = {**site_info, "id": site_id, "category": category_sites}


def get_site_by_url(url: str) -> dict | None:
    """根据 URL 查找站点配置"""
    if not url:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    # 直接匹配
    if domain in SITE_BY_DOMAIN:
        return SITE_BY_DOMAIN[domain]
    # 子域名匹配
    for key, info in SITE_BY_DOMAIN.items():
        if domain.endswith("." + key.split(".")[0]):
            return info
    return None


def get_sites_by_category(category: SiteCategory) -> dict:
    """按分类获取站点列表"""
    return ALL_SITES.get(category, {})


def get_scrapable_sites(category: SiteCategory) -> list[dict]:
    """获取可刮削的站点列表"""
    return [
        {**v, "id": k}
        for k, v in ALL_SITES.get(category, {}).items()
        if v.get("supports_scrape")
    ]


def get_downloadable_sites(category: SiteCategory) -> list[dict]:
    """获取可下载的站点列表"""
    return [
        {**v, "id": k}
        for k, v in ALL_SITES.get(category, {}).items()
        if v.get("supports_download")
    ]
