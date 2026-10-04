"""Kodi/Jellyfin NFO 富字段解析 —— 全仓唯一实现（多模块扫描器共用）。
🔴 为什么要共享：修复前项目里有**三套**质量递减的 NFO 解析实现：
  ① ``app/importer/nfo_parser.py::NFOParser``  —— 最全（ET 解析，11 个字段）
  ② ``app/tasks/anime_scanner.py::parse_nfo``   —— 中等（8 字段）
  ③ ``app/tasks/uncensored_scanner.py::_parse_nfo_metadata`` —— 旧版只 3 个字段
     （title/studio/actor），把 NFO 里**已经存在**的 ``<premiered>``/``<plot>``/
     ``<genre>``/``<runtime>`` 全部丢弃
  ④ fc2 / jav / western / pornhub 扫描器 —— 干脆完全不读 NFO，title 直接用文件名

实测（G:/TEST 43 个真实 NFO，scripts/_probe_nfo_impl.py）：
  ``<premiered>`` 命中 81%、``<genre>`` 81%、``<runtime>`` 79%、``<plot>`` 39%。
  这些数据一直在**本地磁盘**上，却因为扫描器不读而表现为库里字段大面积为空
  （uncensored 库 release_date 86.7% 空），看起来像"源站没数据"。

本模块用正则而非 ElementTree：现场 NFO 畸形（未转义 ``&``、缺闭合标签）极多，
正则 + 逐标签容错比 ET 整体失败更稳。时长换算见 ``app/utils/nfo_runtime.py``。
"""

import re
from pathlib import Path

from app.utils.nfo_runtime import parse_runtime_minutes

__all__ = ["parse_nfo_fields", "empty_nfo_fields", "EMPTY_NFO_META",
           "clean_nfo_text", "clean_nfo_title"]

#: 单片视频时长的可信上限（分钟）。超过即判为脏数据，不入库。
#: 取 600（10 小时）而非更紧的 300：动漫movie 合集与长篇 FC2 确实可能偏长，
#: 宁可放过少量可疑值，也不要错杀真实数据。
_MAX_PLAUSIBLE_MINUTES = 600


# 源 NFO 的 <title> 常见拼接形态（真实样本）：
#   "2025-10-26FC2-4786921【激レア…】… | FC2コンテンツマーケット"
#   "2013-01-22012213_831東京23区熟女ハメ廻し …"
#   即「YYYY-MM-DD」+ 番号 + 正文，有时还带 " | 来源站" 尾巴。
# 直接入库会让标题变成 "2025-10-26FC2-4786921…" 这种脏串。
_TITLE_DATE_RE = re.compile(r"^[\[\(]?\d{4}[-/]\d{1,2}[-/]\d{1,2}[\]\)]?\s*")
# 番号本体：FC2-4786921 / 012213_831 / 012213-831 / HEYZO-0407 / IPZZ-219
# 允许 [-_] 与空格互换（源 NFO 里同一番号出现过 012213_831 / 012213-831 两种写法），
# 末尾的 [\]\)]? 用于吃掉 "[2013-08-10][HEYZO-0407]…" 这种方括号包裹。
_TITLE_CODE_RE = re.compile(
    r"^[\[\(]?"
    r"(?:FC2[-_\s]?(?:PPV[-_\s]?)?\d{5,7}"
    r"|\d{6}[-_\s]\d{3}"
    r"|[A-Z]{2,10}[-_\s]\d{2,5}"
    r"|[A-Z]{2,}\d{3,5}"
    r")[\]\)]?\s*",
    re.IGNORECASE,
)


def _code_variants(code: str) -> list[str]:
    """把番号展开成多种分隔符写法，用于在标题前缀里匹配。

    "012213-831" → ["012213-831", "012213_831", "012213 831"]
    这样无论源 NFO 用的是哪种分隔符都能剥掉。
    """
    base = code.strip()
    out = [base]
    m = re.match(r"^(.*?)([-_\s])(\d+)$", base, re.IGNORECASE)
    if m:
        head, _, tail = m.groups()
        for sep in ("-", "_", " "):
            out.append(f"{head}{sep}{tail}")
    else:
        m2 = re.match(r"^(FC2)([-_\s]?)(PPV)?[-_\s]?(\d+)$", base, re.IGNORECASE)
        if m2:
            _, _, ppv, num = m2.groups()
            pre = "FC2" + (f"-{ppv}" if ppv else "")
            for sep in ("-", "_", " "):
                out.append(f"{pre}{sep}{num}")
    # 去重且保持长度降序（先匹配更长的形态）
    seen: set[str] = set()
    uniq = []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return sorted(uniq, key=len, reverse=True)


def clean_nfo_title(title: str | None, code: str | None = None) -> str | None:
    """剥掉标题开头的日期与番号前缀，以及末尾的 " | 来源站" 尾巴。

    只动**前缀/后缀**，不碰正文（正文里出现的番号是内容，不是噪声）。
    清洗后为空则返回 ``None``（调用方据此回退到文件名）。
    """
    if not title:
        return None
    s = title.strip()
    if not s:
        return None
    # 末尾 " | 来源站" / " - 来源站"（仅当分隔符两侧都够长时才砍，避免误伤正文破折号）
    s = re.sub(r"\s*\|\s*[^|]{2,30}$", "", s).strip()
    # 前缀日期（可重复，个别样本连写两个）
    prev = None
    while prev != s:
        prev = s
        s = _TITLE_DATE_RE.sub("", s, count=1)
    # 前缀番号：优先用本片 code（形态已知最准），否则用通用形态
    if code:
        for v in _code_variants(code):
            new = re.sub(r"^[\[\(]?" + re.escape(v) + r"[\]\)]?\s*", "", s, count=1, flags=re.IGNORECASE)
            if new != s:
                s = new
                break
    else:
        s = _TITLE_CODE_RE.sub("", s, count=1)
    return s.strip() or None


# parse_nfo_fields 的返回键契约。调用方按这些键 .get()，
# 找不到 NFO 时用本字典做空壳（列表值必须 deepcopy，不能共享同一对象）。
EMPTY_NFO_META: dict = {
    "code": None,
    "title": None, "original_title": None, "actors": [], "studio": None,
    "maker": None, "series": None, "plot": None, "plot_short": None,
    "release_date": None, "duration": None, "rating": None,
    "genre": [], "tag": [],
}


def empty_nfo_fields() -> dict:
    """返回一份全新的空 NFO 字段字典（列表是独立副本，可安全 append）。"""
    return {k: ([] if isinstance(v, list) else v) for k, v in EMPTY_NFO_META.items()}


def clean_nfo_text(s: str) -> str:
    """清洗 NFO 文本：去 CDATA 包裹与残留标签，折叠空白。"""
    if not s:
        return s
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _nfo_all_text(text: str, tag: str) -> str | None:
    """取 NFO 中某个标签的文本（支持 CDATA 包裹），空值返回 None。"""
    m = re.search(
        rf"<{tag}>\s*(?:<!\[CDATA\[(.*?)\]\]>|(.*?))\s*</{tag}>",
        text, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    val = clean_nfo_text(m.group(1) if m.group(1) is not None else (m.group(2) or ""))
    return val or None


def _nfo_all_list(text: str, tag: str) -> list[str]:
    """取 NFO 中可重复标签（<tag>/<genre>）的全部非空值，保持顺序去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        rf"<{tag}>\s*(?:<!\[CDATA\[(.*?)\]\]>|(.*?))\s*</{tag}>",
        text, re.DOTALL | re.IGNORECASE,
    ):
        v = clean_nfo_text(m.group(1) if m.group(1) is not None else (m.group(2) or ""))
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def parse_nfo_fields(nfo_path: Path) -> dict:
    """从 movie.nfo 提取富字段。**全仓唯一的 NFO 富字段解析实现**。

    🔴 历史缺口：本函数旧版只读 title/studio/actor 三个字段，把 NFO 里**已经存在**的
    ``<premiered>``（81% 命中）/``<plot>``/``<genre>``（81%）/``<runtime>``（79%）
    全部丢弃 —— 直接表现为库里 ``release_date`` 86.7% 为空，看起来像"源站没数据"，
    实际数据一直在本地 NFO 里。实测见 scripts/_probe_nfo_impl.py。

    其它模块扫描器（fc2 等）也复用本函数，不要再各写一份正则版。
    返回键固定为 ``EMPTY_NFO_META`` 的键集合，调用方可安全 ``.get()``。
    """
    meta: dict = empty_nfo_fields()
    try:
        text = nfo_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return meta

    # 标题：<title>；原标题 <originaltitle> 存在时优先（更干净）
    # 🔴 源 NFO 的 title 普遍是「日期+番号+正文 [| 来源站]」拼接（见 clean_nfo_title），
    #    不清洗直接入库会得到 "2025-10-26FC2-4786921…" 这种脏标题。
    raw_title = _nfo_all_text(text, "title")
    raw_otitle = _nfo_all_text(text, "originaltitle")
    # 本片番号：优先 <id>/<num>；缺失时从原始标题前缀反推（用**未清洗**的原文匹配）
    code_hint = _nfo_all_text(text, "id") or _nfo_all_text(text, "num")
    if not code_hint:
        for raw in (raw_title, raw_otitle):
            if not raw:
                continue
            m = _TITLE_CODE_RE.match(raw.strip())
            if m:
                code_hint = m.group(0).strip().strip("[]()")
                break
    meta["code"] = code_hint
    meta["title"] = clean_nfo_title(raw_title, code_hint)
    meta["original_title"] = clean_nfo_title(raw_otitle, code_hint)
    # title 清洗后为空（源 title 就是纯番号）时，用 original_title 兜底
    if meta["title"] is None and meta["original_title"]:
        meta["title"] = meta["original_title"]

    # studio / maker：任一非空即可
    for tag in ("studio", "maker"):
        v = _nfo_all_text(text, tag)
        if v:
            meta["studio"] = v
            meta["maker"] = meta["maker"] or (v if tag == "maker" else None)
            break

    # 系列：Kodi 用 <set><name>，部分工具直接写 <set> 文本
    m = re.search(r"<set>\s*(?:<!\[CDATA\[(.*?)\]\]>|(.*?))\s*</set>", text, re.DOTALL | re.IGNORECASE)
    if m:
        inner = m.group(1) if m.group(1) is not None else (m.group(2) or "")
        mn = re.search(r"<name>\s*(.*?)\s*</name>", inner, re.DOTALL | re.IGNORECASE)
        meta["series"] = clean_nfo_text(mn.group(1) if mn else inner) or None
    else:
        meta["series"] = _nfo_all_text(text, "series")

    # 简介：<plot> 优先，回退 <outline>
    plot = _nfo_all_text(text, "plot") or _nfo_all_text(text, "outline")
    meta["plot"] = plot
    if plot:
        meta["plot_short"] = plot[:500]

    # 发行日期：premiered / releasedate / release 任一；只取日期部分
    for tag in ("premiered", "releasedate", "release"):
        v = _nfo_all_text(text, tag)
        if v:
            md = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
            if md:
                y, mo, d = (int(x) for x in md.groups())
                meta["release_date"] = f"{y:04d}-{mo:02d}-{d:02d}"
            else:
                my = re.search(r"(\d{4})", v)
                if my:
                    meta["release_date"] = my.group(1)
            if meta["release_date"]:
                break

    # 时长：走统一换算（hh:mm:ss / mm:ss / "42分鍾" / 纯分钟），契约=分钟
    rt = _nfo_all_text(text, "runtime")
    if rt:
        dur = parse_runtime_minutes(rt)
        # 🔴 可信度钳制：>600 分钟（10 小时）不可能是单片视频时长。
        #    实测 G:\TEST\pornhub 的 NFO 里 <runtime>644/865/661</runtime> ——
        #    那些 NFO 是 MDCX 自己从**旧版错误数据**导出的（库里 duration=644
        #    分钟 = 10.7 小时，真实值 644 秒 ≈ 10.7 分钟，60 倍偏差）。
        #    无条件读回会把污染继续传播到新库。宁可留空让刮削阶段填正确值。
        if dur is not None and dur > _MAX_PLAUSIBLE_MINUTES:
            meta["duration"] = None
        else:
            meta["duration"] = dur

    # 评分：⚠️ 只认 <rating>，**不要**回退 <customrating>。
    # 真实样本里 <customrating>JP-18+</customrating> 是**内容分级**（18+），
    # 误当评分会往库里写 rating=18.0，比留空更糟。
    rv = _nfo_all_text(text, "rating")
    if rv:
        mr = re.search(r"\d+(?:\.\d+)?", rv)
        if mr:
            try:
                val = float(mr.group(0))
                # 合理区间 0~10，超出视为分级/脏值丢弃
                if 0.0 <= val <= 10.0:
                    meta["rating"] = val
            except ValueError:
                pass

    # 类型 / 标签
    meta["genre"] = _nfo_all_list(text, "genre")
    meta["tag"] = _nfo_all_list(text, "tag")

    # 演员（只认 <actor><name>，不扫全文的 <name>，否则会误吃 <set><name>）
    for block in re.finditer(r"<actor\b[^>]*>(.*?)</actor>", text, re.DOTALL | re.IGNORECASE):
        nm = re.search(r"<name>\s*(.*?)\s*</name>", block.group(1), re.DOTALL | re.IGNORECASE)
        if nm:
            name = clean_nfo_text(nm.group(1))
            if name and name not in meta["actors"]:
                meta["actors"].append(name)
    return meta
