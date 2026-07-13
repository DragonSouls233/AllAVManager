"""手动数据字典(借鉴 mdcx manual.py:57-818)

移植自 mdcx 项目的 ManualConfig 类,包含:
- OUMEI_NAME:欧美番号缩写→全称映射(290+ 条)
- OFFICIAL:片商官网域名→番号前缀映射(24+ 片商)
- REPL_LIST:文件名清洗关键词列表(60+ 项)
- ALL_REP_WORD:HTML 实体 + 全角字符归一化(80+ 项)
- CHINESE_REP_WORD:繁简异体字归一化(13 项)
- SPECIAL_WORD:遮罩词还原(20+ 项)
- FULL_HALF_CHAR:完整全角→半角映射(90+ 项)

提供便捷函数:
- get_oumei_name(prefix):查找欧美番号全称
- get_official_url(code):根据番号查找片商官网
- normalize_text(text):应用 HTML 实体 + 全角字符归一化
- to_half_width(text):全角转半角
- clean_filename_markers(filename):移除文件名中的分辨率/编码标记
"""

import re
from typing import Optional

# ============================================
# 欧美番号缩写→全称映射(借鉴 mdcx manual.py:57-349)
# ============================================
OUMEI_NAME: dict[str, str] = {
    "wgp": "WhenGirlsPlay",
    "18og": "18OnlyGirls",
    "18yo": "18YearsOld",
    "1kf": "1000Facials",
    "21ea": "21EroticAnal",
    "21fa": "21FootArt",
    "21n": "21Naturals",
    "2cst": "2ChicksSameTime",
    "a1o1": "Asian1on1",
    "aa": "AmateurAllure",
    "ad": "AmericanDaydreams",
    "add": "ManualAddActors",
    "agm": "AllGirlMassage",
    "am": "AssMasterpiece",
    "analb": "AnalBeauty",
    "baebz": "Baeb",
    "bblib": "BigButtsLikeItBig",
    "bcasting": "BangCasting",
    "bconfessions": "BangConfessions",
    "bglamkore": "BangGlamkore",
    "bgonzo": "BangGonzo",
    "brealteens": "BangRealTeens",
    "bcb": "BigCockBully",
    "bch": "BigCockHero",
    "bdpov": "BadDaddyPOV",
    "bex": "BrazzersExxtra",
    "bgb": "BabyGotBoobs",
    "bgbs": "BoundGangbangs",
    "bin": "BigNaturals",
    "bjf": "BlowjobFridays",
    "bp": "ButtPlays",
    "btas": "BigTitsatSchool",
    "btaw": "BigTitsatWork",
    "btc": "BigTitCreampie",
    "btis": "BigTitsinSports",
    "btiu": "BigTitsinUniform",
    "btlbd": "BigTitsLikeBigDicks",
    "btra": "BigTitsRoundAsses",
    "burna": "BurningAngel",
    "bwb": "BigWetButts",
    "cfnm": "ClothedFemaleNudeMale",
    "clip": "LegalPorno",
    "cps": "CherryPimps",
    "cuf": "CumFiesta",
    "cws": "CzechWifeSwap",
    "da": "DoctorAdventures",
    "dbm": "DontBreakMe",
    "dc": "DorcelVision",
    "ddfb": "DDFBusty",
    "ddfvr": "DDFNetworkVR",
    "dm": "DirtyMasseur",
    "dnj": "DaneJones",
    "dpg": "DigitalPlayground",
    "dwc": "DirtyWivesClub",
    "dwp": "DayWithAPornstar",
    "dsw": "DaughterSwap",
    "esp": "EuroSexParties",
    "ete": "EuroTeenErotica",
    "ext": "ExxxtraSmall",
    "fams": "FamilyStrokes",
    "faq": "FirstAnalQuest",
    "fds": "FakeDrivingSchool",
    "fft": "FemaleFakeTaxi",
    "fhd": "FantasyHD",
    "fhl": "FakeHostel",
    "fho": "FakehubOriginals",
    "fka": "FakeAgent",
    "fm": "FuckingMachines",
    "fms": "FantasyMassage",
    "frs": "FitnessRooms",
    "ft": "FastTimes",
    "ftx": "FakeTaxi",
    "gft": "GrandpasFuckTeens",
    "gbcp": "GangbangCreampie",
    "gta": "GirlsTryAnal",
    "gw": "GirlsWay",
    "h1o1": "Housewife1on1",
    "ham": "HotAndMean",
    "hart": "Hegre",
    "hcm": "HotCrazyMess",
    "hegre-art": "Hegre",
    "hoh": "HandsOnHardcore",
    "hotab": "HouseofTaboo",
    "ht": "Hogtied",
    "ihaw": "IHaveAWife",
    "iktg": "IKnowThatGirl",
    "il": "ImmoralLive",
    "kha": "KarupsHA",
    "kow": "KarupsOW",
    "kpc": "KarupsPC",
    "la": "LatinAdultery",
    "lcd": "LittleCaprice-Dreams",
    "littlecaprice": "LittleCaprice-Dreams",
    "lhf": "LoveHerFeet",
    "lsb": "Lesbea",
    "lst": "LatinaSexTapes",
    "lta": "LetsTryAnal",
    "maj": "ManoJob",
    "mbb": "MommyBlowsBest",
    "mbt": "MomsBangTeens",
    "mc": "MassageCreep",
    "mcu": "MonsterCurves",
    "mdhf": "MyDaughtersHotFriend",
    "mdhg": "MyDadsHotGirlfriend",
    "mfa": "ManuelFerrara",
    "mfhg": "MyFriendsHotGirl",
    "mfhm": "MyFriendsHotMom",
    "mfl": "Mofos",
    "mfp": "MyFamilyPies",
    "mfst": "MyFirstSexTeacher",
    "mgbf": "MyGirlfriendsBustyFriend",
    "mgb": "MommyGotBoobs",
    "mic": "MomsInControl",
    "mj": "ManoJob",
    "mlib": "MildsLikeItBig",
    "mlt": "MomsLickTeens",
    "mmgs": "MommysGirl",
    "mnm": "MyNaughtyMassage",
    "mom": "MomXXX",
    "mpov": "MrPOV",
    "mrs": "MassageRooms",
    "mshf": "MySistersHotFriend",
    "mts": "MomsTeachSex",
    "mvft": "MyVeryFirstTime",
    "mwhf": "MyWifesHotFriend",
    "naf": "NeighborAffair",
    "nam": "NaughtyAmerica",
    "na": "NaughtyAthletics",
    "naughtyamericavr": "NaughtyAmerica",
    "nb": "NaughtyBookworms",
    "news": "NewSensations",
    "nf": "NubileFilms",
    "no": "NaughtyOffice",
    "nrg": "NaughtyRichGirls",
    "nubilef": "NubileFilms",
    "num": "NuruMassage",
    "nw": "NaughtyWeddings",
    "obj": "OnlyBlowjob",
    "otb": "OnlyTeenBlowjobs",
    "pav": "PixAndVideo",
    "pba": "PublicAgent",
    "pf": "PornFidelity",
    "phd": "PassionHD",
    "plib": "PornstarsLikeitBig",
    "pop": "PervsOnPatrol",
    "ppu": "PublicPickups",
    "prdi": "PrettyDirty",
    "ps": "PropertySex",
    "pud": "PublicDisgrace",
    "reg": "RealExGirlfriends",
    "rkp": "RKPrime",
    "rws": "RealWifeStories",
    "saf": "ShesAFreak",
    "sart": "SexArt",
    "sbj": "StreetBlowjobs",
    "sislove": "SisLovesMe",
    "smb": "ShareMyBF",
    "ssc": "StepSiblingsCaught",
    "ssn": "ShesNew",
    "sts": "StrandedTeens",
    "swsn": "SwallowSalon",
    "tdp": "TeensDoPorn",
    "tds": "TheDickSuckers",
    "ted": "Throated",
    "tf": "TeenFidelity",
    "tgs": "ThisGirlSucks",
    "these": "TheStripperExperience",
    "tla": "TeensLoveAnal",
    "tlc": "TeensLoveCream",
    "tle": "TheLifeErotic",
    "tlhc": "TeensLoveHugeCocks",
    "tlib": "TeensLikeItBig",
    "tlm": "TeensLoveMoney",
    "togc": "TonightsGirlfriendClassic",
    "tog": "TonightsGirlfriend",
    "tspa": "TrickySpa",
    "tss": "ThatSitcomShow",
    "tuf": "TheUpperFloor",
    "wa": "WhippedAss",
    "wfbg": "WeFuckBlackGirls",
    "wkp": "Wicked",
    "wlt": "WeLiveTogether",
    "woc": "WildOnCam",
    "wov": "WivesOnVacation",
    "wowg": "WowGirls",
    "wy": "WebYoung",
    "zzs": "ZZseries",
    "ztod": "ZeroTolerance",
    "itc": "InTheCrack",
    "abbw": "AbbyWinters",
    "abme": "AbuseMe",
    "ana": "AnalAngels",
    "atke": "ATKExotics",
    "atkg": "ATKGalleria",
    "atkgfs": "ATKGirlfriends",
    "atkh": "ATKHairy",
    "aktp": "ATKPetites",
    "btp": "BadTeensPunished",
    "brealmilfs": "Bang.RealMilfs",
    "byngr": "bang.YNGR",
    "ba": "Beauty-Angels",
    "bgfs": "BlackGFS",
    "bna": "BrandNew",
    "bam": "BruceAndMorgan",
    "bcast": "BrutalCastings",
    "bd": "BrutalDildos",
    "bpu": "BrutalPickups",
    "clubseventeen": "ClubSweethearts",
    "cfnmt": "CFNMTeens",
    "cfnms": "FNMSecret",
    "cza": "CzhecAmateurs",
    "czbb": "CzechBangBus",
    "czb": "CzechBitch",
    "cc": "CzechCasting",
    "czc": "CzechCouples",
    "czestro": "CzechEstrogenolit",
    "czf": "CzechFantasy",
    "czgb": "CzechGangBang",
    "cgfs": "CzechGFS",
    "czharem": "CzechHarem",
    "czm": "CzechMassage",
    "czo": "CzechOrgasm",
    "czps": "CzechPawnShop",
    "css": "CzechStreets",
    "cztaxi": "CzechTaxi",
    "czt": "CzechTwins",
    "dlla": "DadysLilAngel",
    "dts": "DeepThroatSirens",
    "deb": "DeviceBondage",
    "doan": "DiaryOfANanny",
    "dpf": "DPFanatics",
    "ds": "DungeonSex",
    "ffr": "FacialsForever",
    "ff": "FilthyFamily",
    "fbbg": "FirstBGG",
    "fab": "FuckedAndBound",
    "fum": "FuckingMachines",
    "fs": "FuckStudies",
    "tfcp": "FullyClothedPissing",
    "gfr": "GFRevenge",
    "gdp": "GirlsDoPorn",
    "hletee": "HelplessTeens",
    "hotb": "HouseOfTaboo",
    "Infr": "InfernalRestraints",
    "inh": "InnocentHigh",
    "jlmf": "JessieLoadsMonsterFacials",
    "university": "KinkUniversity",
    "lang": "LANewGirl",
    "mmp": "MMPNetwork",
    "mot": "MoneyTalks",
    "mbc": "MyBabysittersClub",
    "mdm": "MyDirtyMaid",
    "nvg": "NetVideoGirls",
    "nubp": "Nubiles-Porn",
    "oo": "Only-Opaques",
    "os": "Only-Secretaries",
    "oss": "OnlySilAndSatin",
    "psus": "PascalsSubSluts",
    "pbf": "PetiteBallerinasFucked",
    "phdp": "PetiteHDPoorn",
    "psp": "PorsntarsPunishment",
    "pc": "PrincessCum",
    "pdmqfo": "QuestForOrgasm",
    "rtb": "RealTimeBondage",
    "rab": "RoundAndBrown",
    "sr": "SadisticRope",
    "sas": "SexAndSubmission",
    "sed": "SexualDisgrace",
    "seb": "SexuallyBroken",
    "sislov": "SisLovesMe",
    "tslw": "SlimeWave",
    "steps": "StepSiblings",
    "stre": "StrictRestraint",
    "t18": "Taboo18",
    "tft": "TeacherFucksTeens",
    "tmf": "TeachMeFisting",
    "tsma": "TeenSexMania",
    "tsm": "TeenSexMovs",
    "ttw": "TeensInTheWoods",
    "tgw": "ThaiGirlsWild",
    "taob": "TheArtOfBlowJob",
    "trwo": "TheRealWorkout",
    "tto": "TheTrainingOfO",
    "tg": "TopGrl",
    "tt": "TryTeens",
    "th": "TwistysHard",
    "vp": "VIPissy",
    "wrh": "WeAreHairy",
    "wpa": "WhippedAss",
    "yt": "YoungThroats",
    "zb": "ZoliBoy",
}

# ============================================
# 片商官网域名→番号前缀映射(借鉴 mdcx manual.py:350-381)
# 用于根据番号直接访问片商官网,绕过第三方刮削站
# ============================================
OFFICIAL: dict[str, str] = {
    "https://s1s1s1.com": "sivr|ssis|ssni|snis|soe|oned|one|onsd|ofje|sps|tksoe",
    "https://moodyz.com": "mdvr|midv|mide|midd|mibd|mimk|miid|migd|mifd|miae|miad|miaa|mdl|mdj|mdi|mdg|mdf|mde|mdld|mded|mizd|mird|mdjd|rmid|mdid|mdmd|mimu|mdpd|mivd|mdud|mdgd|mdvd|mias|miqd|mint|rmpd|mdrd|tkmide|tkmidd|kmide|tkmigd|mdfd|rmwd|miab",
    "https://www.madonna-av.com": "juvr|jusd|juq|juy|jux|jul|juk|juc|jukd|jusd|oba|jufd|roeb|roe|ure|mdon|jfb|obe|jums",
    "https://www.wanz-factory.com": "wavr|waaa|bmw|wanz",
    "https://ideapocket.com": "ipvr|ipx|ipz|iptd|ipsd|idbd|supd|ipit|and|hpd|tkipz|ipzz|cosd|anpd|dan|alad|kipx",
    "https://kirakira-av.com": "kivr|blk|kibd|kifd|kird|kisd|set",
    "https://www.av-e-body.com": "ebvr|ebod|mkck|eyan",
    "https://bi-av.com": "cjvr|cjod|bbi|bib|cjob|beb|bid|bist|bwb",
    "https://premium-beauty.com": "prvr|pgd|pred|pbd|pjd|prtd|pxd|pid|ptv",
    "https://miman.jp": "mmvr|mmnd|mmxd|aom",
    "https://tameikegoro.jp": "mevr|meyd|mbyd|mdyd|mnyd",
    "https://fitch-av.com": "fcvr|jufe|jufd|jfb|juny|nyb|finh|gcf|nima",
    "https://kawaiikawaii.jp": "kavr|cawd|kwbd|kawd|kwsr|kwsd|kane",
    "https://befreebe.com": "bf",
    "https://muku.tv": "mucd|mudr|mukd|smcd|mukc",
    "https://attackers.net": "atvr|rbk|rbd|same|shkd|atid|adn|atkd|jbd|sspd|atad|azsd",
    "https://mko-labo.net": "mvr|mism|emlb",
    "https://dasdas.jp": "dsvr|dass|dazd|dasd|pla",
    "https://mvg.jp": "mvsd|mvbd",
    "https://av-opera.jp": "opvr|opbd|opud",
    "https://oppai-av.com": "ppvr|pppe|ppbd|pppd|ppsd|ppfd",
    "https://v-av.com": "vvvd|vicd|vizd|vspd",
    "https://to-satsu.com": "clvr|stol|club",
    "https://bibian-av.com": "bbvr|bban",
    "https://honnaka.jp": "hnvr|hmn|hndb|hnd|krnd|hnky|hnjc|hnse",
    "https://rookie-av.jp": "rvr|rbb|rki",
    "https://nanpa-japan.jp": "njvr|nnpj|npjb",
    "https://hajimekikaku.com": "hjbb|hjmo|avgl",
    "https://hhh-av.com": "huntb|hunta|hunt|hunbl|royd|tysf",
    "https://www.prestige-av.com": "abp|mbm|ezd|docp|onez|yrh|abw|abs|chn|mgt|tre|edd|ult|cmi|mbd|dnw|sga|rdd|dcx|evo|rdt|ppt|gets|sim|kil|tus|dtt|gnab|man|mas|tbl|rtp|ctd|fiv|dic|esk|kbi|tem|ama|kfne|trd|har|yrz|srs|mzq|zzr|gzap|tgav|rix|aka|bgn|lxv|afs|goal|giro|cpde|nmp|mct|abc|inu|shl|mbms|pxh|nrs|ftn|prdvr|fst|blo|shs|kum|gsx|ndx|atd|dld|kbh|bcv|raw|soud|job|chs|yok|bsd|fsb|nnn|hyk|sor|hsp|jbs|xnd|mei|day|mmy|kzd|jan|gyan|tdt|tok|dms|fnd|cdc|jcn|pvrbst|sdvr|docvr|fcp|abf",
}

# 预编译番号→官网查找索引(反转 OFFICIAL 字典)
_OFFICIAL_INDEX: dict[str, str] = {}
for _url, _prefixes in OFFICIAL.items():
    for _prefix in _prefixes.split("|"):
        _OFFICIAL_INDEX[_prefix.upper()] = _url

# ============================================
# 文件名清洗关键词列表(借鉴 mdcx manual.py:414-474)
# 这些关键词在番号识别前应从文件名中移除
# ============================================
REPL_LIST: list[str] = [
    "HEYDOUGA",
    "CARIBBEANCOM",
    "CARIB",
    "1PONDO",
    "1PON",
    "PACOMA",
    "PACO",
    "10MUSUME",
    "-10MU",
    "Tokyo Hot",
    "Tokyo_Hot",
    "TOKYO-HOT",
    "TOKYOHOT",
    "(S1)",
    "[THZU.CC]",
    "「麻豆」",
    "(",
    ")",
    ".PRT",
    "MP4-KTR",
    "rarbg",
    "WEBDL",
    "x2160x",
    "x1080x",
    "x2160p",
    "x1080p",
    "x264 aac",
    "x264_aac",
    "x264-aac",
    "x265 aac",
    "x265_aac",
    "x265-aac",
    "H.264",
    "H.265",
    "DVDRIP",
    "DVD ",
    "2160P",
    "1440P",
    "1080P",
    "960P",
    "720P",
    "540P",
    "480P",
    "360P",
    "4096x2160",
    "1920x1080",
    "1280x720",
    "960x720",
    "640x480",
    "4096×2160",
    "1920×1080",
    "1280×720",
    "960×720",
    "640×480",
    "90fps",
    "60fps",
    "30fps",
    ".cht",
    ".chs",
]

# ============================================
# HTML 实体 + 全角字符归一化字典(借鉴 mdcx manual.py:553-640)
# 用于清洗刮削到的标题/演员名等文本
# ============================================
ALL_REP_WORD: dict[str, str] = {
    "&amp;": "＆",
    "&lt;": "<",
    "&gt;": ">",
    "&apos;": "'",
    "&quot;": '"',
    "&lsquo;": "「",
    "&rsquo;": "」",
    "&hellip;": "…",
    "&rarr;": "→",
    "<br/>": "",
    "&": "＆",
    "&mdash;": "—",
    "<": "＜",
    ">": "＞",
    "・": "·",
    "“": "「",
    "”": "」",
    "...": "…",
    "……": "…",
    "’s": "'s",
    "‘": "「",
    "’": "」",
    "! ": "！",
    "Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D", "Ｅ": "E",
    "Ｆ": "F", "Ｇ": "G", "Ｈ": "H", "Ｉ": "I", "Ｊ": "J",
    "Ｋ": "K", "Ｌ": "L", "Ｍ": "M", "Ｎ": "N", "Ｏ": "O",
    "Ｐ": "P", "Ｑ": "Q", "Ｒ": "R", "Ｓ": "S", "Ｔ": "T",
    "Ｕ": "U", "Ｖ": "V", "Ｗ": "W", "Ｘ": "X", "Ｙ": "Y",
    "Ｚ": "Z",
    "ａ": "a", "ｂ": "b", "ｃ": "c", "ｄ": "d", "ｅ": "e",
    "ｆ": "f", "ｇ": "g", "ｈ": "h", "ｉ": "i", "ｊ": "j",
    "ｋ": "k", "ｌ": "l", "ｍ": "m", "ｎ": "n", "ｏ": "o",
    "ｐ": "p", "ｑ": "q", "ｒ": "r", "ｓ": "s", "ｔ": "t",
    "ｕ": "u", "ｖ": "v", "ｗ": "w", "ｘ": "x", "ｙ": "y",
    "ｚ": "z",
    "１": "1", "２": "2", "３": "3", "４": "4", "５": "5",
    "６": "6", "７": "7", "８": "8", "９": "9", "０": "0",
    "\t": " ",
}

# ============================================
# 繁简异体字归一化字典(借鉴 mdcx manual.py:641-655)
# 用于把繁体异体字统一为简体常用字
# ============================================
CHINESE_REP_WORD: dict[str, str] = {
    "姊": "姐",
    "著": "着",
    "慾": "欲",
    "肏": "操",
    "裡": "里",
    "係": "系",
    "繫": "联",
    "豔": "艳",
    "妳": "你",
    "歳": "岁",
    "廿": "二十",
    "卅": "三十",
    "卌": "四十",
}

# ============================================
# 遮罩词还原字典(借鉴 mdcx manual.py:793-818)
# 部分站点对敏感词用 ● 或 ○ 遮罩,这里还原原字
# ============================================
SPECIAL_WORD: dict[str, str] = {
    "強●": "強制",
    "犯●": "犯さ",
    "凌●": "凌辱",
    "折●": "折檻",
    "奴●": "奴隷",
    "輪●": "輪姦",
    "痴●": "痴漢",
    "近●": "近親",
    "小●生": "小学生",
    "中●生": "中学生",
    "女子●生": "女子校生",
    "強○": "強制",
    "犯○": "犯さ",
    "凌○": "凌辱",
    "折○": "折檻",
    "奴○": "奴隷",
    "輪○": "輪姦",
    "痴○": "痴漢",
    "近○": "近親",
    "小○生": "小学生",
    "中○生": "中学生",
    "女子○生": "女子校生",
    "ﾒｲﾄﾞ": "メイド",
    "ﾎｰﾙﾄﾞ": "ホールド",
}

# ============================================
# 完整全角→半角映射列表(借鉴 mdcx manual.py:694-792)
# 用于把全角符号统一为半角符号
# ============================================
FULL_HALF_CHAR: list[tuple[str, str]] = [
    ("・", "·"), ("．", "."), ("，", ","), ("！", "!"), ("？", "?"),
    ("”", '"'), ("’", "'"), ("‘", "`"), ("＠", "@"), ("＿", "_"),
    ("：", ":"), ("；", ";"), ("＃", "#"), ("＄", "$"), ("％", "%"),
    ("＆", "&"), ("（", "("), ("）", ")"), ("‐", "-"), ("＝", "="),
    ("＊", "*"), ("＋", "+"), ("－", "-"), ("／", "/"), ("＜", "<"),
    (">", ">"), ("＞", ">"), ("［", "["), ("￥", "\\"), ("］", "]"),
    ("＾", "^"), ("｛", "{"), ("｜", "|"), ("｝", "}"), ("～", "~"),
    ("ａ", "a"), ("ｂ", "b"), ("ｃ", "c"), ("ｄ", "d"), ("ｅ", "e"),
    ("ｆ", "f"), ("ｇ", "g"), ("ｈ", "h"), ("ｉ", "i"), ("ｊ", "j"),
    ("ｋ", "k"), ("ｌ", "l"), ("ｍ", "m"), ("ｎ", "n"), ("ｏ", "o"),
    ("ｐ", "p"), ("ｑ", "q"), ("ｒ", "r"), ("ｓ", "s"), ("ｔ", "t"),
    ("ｕ", "u"), ("ｖ", "v"), ("ｗ", "w"), ("ｘ", "x"), ("ｙ", "y"),
    ("ｚ", "z"),
    ("Ａ", "A"), ("Ｂ", "B"), ("Ｃ", "C"), ("Ｄ", "D"), ("Ｅ", "E"),
    ("Ｆ", "F"), ("Ｇ", "G"), ("Ｈ", "H"), ("Ｉ", "I"), ("Ｊ", "J"),
    ("Ｋ", "K"), ("Ｌ", "L"), ("Ｍ", "M"), ("Ｎ", "N"), ("Ｏ", "O"),
    ("Ｐ", "P"), ("Ｑ", "Q"), ("Ｒ", "R"), ("Ｓ", "S"), ("Ｔ", "T"),
    ("Ｕ", "U"), ("Ｖ", "V"), ("Ｗ", "W"), ("Ｘ", "X"), ("Ｙ", "Y"),
    ("Ｚ", "Z"),
    ("０", "0"), ("１", "1"), ("２", "2"), ("３", "3"), ("４", "4"),
    ("５", "5"), ("６", "6"), ("７", "7"), ("８", "8"), ("９", "9"),
    ("　", " "),
]

# 预编译 REPL_LIST 为正则(大小写不敏感)
_REPL_PATTERN = re.compile("|".join(re.escape(w) for w in REPL_LIST), re.IGNORECASE)


# ============================================
# 便捷查询函数
# ============================================

def get_oumei_name(prefix: str) -> Optional[str]:
    """查找欧美番号缩写对应的全称

    Args:
        prefix: 番号前缀(如 "bblib"、"sislove")

    Returns:
        全称(如 "BigButtsLikeItBig"),未找到返回 None

    Examples:
        >>> get_oumei_name("bblib")
        'BigButtsLikeItBig'
        >>> get_oumei_name("sislove")
        'SisLovesMe'
    """
    if not prefix:
        return None
    return OUMEI_NAME.get(prefix.lower())


def get_official_url(code: str) -> Optional[str]:
    """根据番号查找片商官网 URL

    Args:
        code: 番号(如 "SSIS-698"、"ipx-177")

    Returns:
        片商官网 URL(如 "https://s1s1s1.com"),未找到返回 None

    Examples:
        >>> get_official_url("SSIS-698")
        'https://s1s1s1.com'
        >>> get_official_url("ipx-177")
        'https://ideapocket.com'
    """
    if not code:
        return None
    # 提取番号前缀(字母部分)
    match = re.match(r"^([A-Za-z]+)", code)
    if not match:
        return None
    prefix = match.group(1).upper()
    return _OFFICIAL_INDEX.get(prefix)


def normalize_text(text: str) -> str:
    """应用 HTML 实体 + 全角字符 + 繁简异体 + 遮罩词归一化

    借鉴 mdcx 的文本清洗逻辑,依次应用:
    1. ALL_REP_WORD:HTML 实体解码 + 全角英数字归一化
    2. CHINESE_REP_WORD:繁简异体字归一化
    3. SPECIAL_WORD:遮罩词还原

    Args:
        text: 待清洗的文本(标题/演员名/简介等)

    Returns:
        清洗后的文本

    Examples:
        >>> normalize_text("Tom &amp; Jerry")
        'Tom ＆ Jerry'
        >>> normalize_text("強●凌辱")
        '強制凌辱'
    """
    if not text:
        return text
    # 1. HTML 实体 + 全角英数字
    for old, new in ALL_REP_WORD.items():
        text = text.replace(old, new)
    # 2. 繁简异体字
    for old, new in CHINESE_REP_WORD.items():
        text = text.replace(old, new)
    # 3. 遮罩词还原
    for old, new in SPECIAL_WORD.items():
        text = text.replace(old, new)
    return text


def to_half_width(text: str) -> str:
    """全角符号转半角符号

    借鉴 mdcx manual.py:694-792 的 FULL_HALF_CHAR 映射。
    注意:此函数只转换符号,不转换英数字(英数字归一化用 normalize_text)。

    Args:
        text: 待转换的文本

    Returns:
        转换后的文本

    Examples:
        >>> to_half_width("（测试）")
        '(测试)'
        >>> to_half_width("＃标签")
        '#标签'
    """
    if not text:
        return text
    for full, half in FULL_HALF_CHAR:
        text = text.replace(full, half)
    return text


def clean_filename_markers(filename: str) -> str:
    """移除文件名中的分辨率/编码标记

    借鉴 mdcx manual.py:414-474 的 REPL_LIST,移除文件名中的:
    - 分辨率标记(1080P/2160P/720P 等)
    - 编码标记(x264/x265/H.264/H.265 等)
    - 发布组标记(MP4-KTR/rarbg/WEBDL 等)
    - 站点标记(HEYDOUGA/CARIBBEANCOM 等)

    Args:
        filename: 待清洗的文件名(不含扩展名)

    Returns:
        清洗后的文件名

    Examples:
        >>> clean_filename_markers("SSIS-698.1080P.MP4-KTR")
        'SSIS-698.'
        >>> clean_filename_markers("ipx-177.x264 aac")
        'ipx-177.'
    """
    if not filename:
        return filename
    return _REPL_PATTERN.sub("", filename)
